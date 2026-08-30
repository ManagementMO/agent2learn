"""Offline integration tests for the production per-outline CDP lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from ingest_support import FakeClient, course

from agent2learn import outlines
from agent2learn.errors import AuthenticationError
from agent2learn.ingest import MetadataReport, ingest_metadata
from agent2learn.schools.uwaterloo import UWaterloo
from agent2learn.vault import Vault


def _outline_topic(topic_id: int) -> dict[str, object]:
    return {
        "TopicId": topic_id,
        "Title": f"Course Outline {topic_id}",
        "TypeIdentifier": "Link",
        "Url": f"/content/enforced/111111-COURSE101/outline-{topic_id}.html",
        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
        "IsBroken": False,
    }


def _metadata(tmp_path: Path) -> tuple[Vault, MetadataReport]:
    toc = {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Outlines",
                "Modules": [],
                "Topics": [_outline_topic(1), _outline_topic(2)],
            }
        ]
    }
    client = FakeClient([course()], tocs={111111: toc})
    vault = Vault(tmp_path)
    return vault, ingest_metadata(client, vault, client.school)


class _PageConnection:
    def __init__(
        self,
        number: int,
        events: list[str],
        *,
        close_error: bool = False,
        blocked_url: str | None = None,
    ) -> None:
        self.number = number
        self.events = events
        self.close_error = close_error
        self.blocked_url = blocked_url
        self.url = ""
        self.sent: list[tuple[str, dict[str, object]]] = []

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        event_handler: Any = None,
    ) -> dict[str, object]:
        self.events.append(f"page-{self.number}:{method}")
        if method == "Page.navigate":
            assert params is not None
            self.url = str(params["url"])
        if method == "Runtime.evaluate":
            expression = str((params or {}).get("expression", ""))
            if expression == "document.readyState":
                if self.blocked_url is not None:
                    event_handler(
                        {
                            "method": "Fetch.requestPaused",
                            "params": {
                                "requestId": f"blocked-{self.number}",
                                "request": {"url": self.blocked_url},
                            },
                        }
                    )
                return {"result": {"value": "complete"}}
            return {
                "result": {
                    "value": {
                        "html": f"<html><body>outline {self.number}</body></html>",
                        "url": self.url,
                    }
                }
            }
        if method == "Page.close" and self.close_error:
            raise RuntimeError("synthetic close failure")
        return {}

    def send_without_wait(self, method: str, params: dict[str, object]) -> None:
        self.sent.append((method, params))

    def close(self) -> None:
        self.events.append(f"page-{self.number}:socket-close")


class _PageSource:
    def __init__(
        self,
        *,
        close_error_on: int | None = None,
        blocked_on: int | None = None,
    ) -> None:
        self.events: list[str] = []
        self.connections: list[_PageConnection] = []
        self.close_error_on = close_error_on
        self.blocked_on = blocked_on

    def open_page(self) -> _PageConnection:
        number = len(self.connections) + 1
        self.events.append(f"open:{number}")
        connection = _PageConnection(
            number,
            self.events,
            close_error=number == self.close_error_on,
            blocked_url=(
                "https://learn.uwaterloo.ca.evil.example/track.js"
                if number == self.blocked_on
                else None
            ),
        )
        self.connections.append(connection)
        return connection

    def close(self) -> None:
        self.events.append("factory:close")


class _UnavailablePageSource:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = False

    def open_page(self) -> _PageConnection:
        self.opened += 1
        raise AuthenticationError("synthetic browser unavailable")

    def close(self) -> None:
        self.closed = True


def _status_rows(metadata: MetadataReport) -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads(
            (metadata.courses[0].directory / "_meta" / "outlines.json").read_text(encoding="utf-8")
        ),
    )


def test_multiple_outlines_reject_a_single_borrowed_browser_before_rendering(
    tmp_path: Path,
) -> None:
    vault, metadata = _metadata(tmp_path)
    connection = _PageConnection(1, [])
    borrowed = outlines.CDPOutlineBrowser(connection)

    with pytest.raises(TypeError, match="OutlineBrowserFactory"):
        outlines.ingest_outlines(
            cast(outlines.OutlineBrowserFactory, borrowed), vault, UWaterloo(), metadata
        )

    assert connection.events == []


def test_two_outlines_use_fresh_targets_and_close_each_before_the_next(tmp_path: Path) -> None:
    vault, metadata = _metadata(tmp_path)
    source = _PageSource()
    factory = outlines.CDPOutlineBrowserFactory(source)

    report = outlines.ingest_outlines(factory, vault, UWaterloo(), metadata)

    assert report.rendered == 2
    assert len(source.connections) == 2
    assert source.connections[0] is not source.connections[1]
    assert source.events.index("page-1:Page.close") < source.events.index("open:2")
    assert source.events.index("page-1:socket-close") < source.events.index("open:2")
    assert source.events[-1] == "factory:close"


def test_unchanged_outline_keeps_the_existing_manifest_revision(
    monkeypatch: Any, tmp_path: Path
) -> None:
    vault, metadata = _metadata(tmp_path)
    monkeypatch.setattr(outlines.clock, "stamp", lambda: "2026-08-25T12:00:00Z")
    first_report = outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )
    first = vault.entry("uwaterloo:111111:topic:1")
    assert first is not None

    monkeypatch.setattr(outlines.clock, "stamp", lambda: "2026-08-26T12:00:00Z")
    second_report = outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )

    second = vault.entry("uwaterloo:111111:topic:1")
    assert second is not None
    assert first_report.rendered == second_report.rendered == 2
    assert second_report.unavailable == 0
    assert second_report.errors == ()
    assert second.fetched_at == first.fetched_at
    assert second.derived["markdown"].created_at == first.derived["markdown"].created_at


def test_locally_modified_outline_twin_is_preserved_before_replacement(tmp_path: Path) -> None:
    vault, metadata = _metadata(tmp_path)
    first_report = outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )
    first = vault.entry("uwaterloo:111111:topic:1")
    assert first_report.rendered == 2
    assert first is not None
    twin = vault.root / Path(*first.derived["markdown"].path.split("/"))
    twin.write_text("# Local outline note\n", encoding="utf-8")

    second_report = outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )

    assert second_report.rendered == 2
    assert second_report.unavailable == 0
    revisions = list((vault.state() / "history").rglob("revision.json"))
    assert len(revisions) == 1
    assert '"status": "local-modification"' in revisions[0].read_text(encoding="utf-8")
    preserved_twins = [
        path
        for path in revisions[0].parent.joinpath("derived").glob("*.md")
        if path.read_text(encoding="utf-8") == "# Local outline note\n"
    ]
    assert len(preserved_twins) == 1


def test_missing_outline_source_never_allows_a_local_twin_to_be_overwritten(
    tmp_path: Path,
) -> None:
    vault, metadata = _metadata(tmp_path)
    outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )
    first = vault.entry("uwaterloo:111111:topic:1")
    assert first is not None
    source = vault.materialized(first)
    twin = vault.root / Path(*first.derived["markdown"].path.split("/"))
    source.unlink()
    twin.write_text("# Local outline note without source\n", encoding="utf-8")

    report = outlines.ingest_outlines(
        outlines.CDPOutlineBrowserFactory(_PageSource()),
        vault,
        UWaterloo(),
        metadata,
    )

    assert report.rendered == 1
    assert report.unavailable == 1
    assert twin.read_text(encoding="utf-8") == "# Local outline note without source\n"


def test_target_cleanup_failure_stops_and_marks_remaining_outline_unavailable(
    tmp_path: Path,
) -> None:
    vault, metadata = _metadata(tmp_path)
    source = _PageSource(close_error_on=1)
    factory = outlines.CDPOutlineBrowserFactory(source)

    report = outlines.ingest_outlines(factory, vault, UWaterloo(), metadata)

    assert report.rendered == 1
    assert len(source.connections) == 1
    assert source.connections[0].events.count("page-1:socket-close") == 1
    rows = _status_rows(metadata)
    assert len(rows) == 2
    assert rows[0]["cleanup_error"] == "target could not be closed"
    assert rows[1]["status"] == "outline_unavailable"
    assert rows[1]["reason"] == "previous target cleanup failed"


def test_off_origin_subresource_is_blocked_before_rendered_bytes_are_installed(
    tmp_path: Path,
) -> None:
    vault, metadata = _metadata(tmp_path)
    source = _PageSource(blocked_on=1)
    factory = outlines.CDPOutlineBrowserFactory(source)

    report = outlines.ingest_outlines(factory, vault, UWaterloo(), metadata)

    assert report.unavailable == 1
    assert report.rendered == 1
    assert source.connections[0].sent == [
        (
            "Fetch.failRequest",
            {"requestId": "blocked-1", "errorReason": "BlockedByClient"},
        )
    ]
    rows = _status_rows(metadata)
    assert rows[0]["status"] == "outline_unavailable"
    assert rows[1]["status"] == "rendered"
    assert vault.entry("uwaterloo:111111:topic:1") is None
    assert vault.entry("uwaterloo:111111:topic:2") is not None


def test_browser_unavailability_is_explicit_for_every_discovered_outline(tmp_path: Path) -> None:
    vault, metadata = _metadata(tmp_path)
    source = _UnavailablePageSource()
    factory = outlines.CDPOutlineBrowserFactory(source)

    report = outlines.ingest_outlines(factory, vault, UWaterloo(), metadata)

    assert report.unavailable == 2
    assert source.opened == 2
    assert source.closed is True
    assert [row["status"] for row in _status_rows(metadata)] == [
        "outline_unavailable",
        "outline_unavailable",
    ]
    policy = json.loads(
        (metadata.courses[0].directory / "_meta" / "ai_policy.json").read_text(encoding="utf-8")
    )
    assert policy["status"] == "outline_unavailable"
