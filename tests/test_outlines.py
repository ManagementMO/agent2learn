"""Offline tests for the bounded first-party outline renderer."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from ingest_support import FakeClient, course

from agent2learn import outlines as outlines_module
from agent2learn.ingest import MetadataReport, ingest_metadata
from agent2learn.outlines import (
    CDPOutlineBrowser,
    OutlinePage,
    ingest_outlines,
)
from agent2learn.schools.uwaterloo import UWaterloo
from agent2learn.vault import Vault


def _outline_topic(topic_id: int = 1, *, url: str | None = None) -> dict[str, object]:
    return {
        "TopicId": topic_id,
        "Title": "Course Outline",
        "TypeIdentifier": "Link",
        "Url": url or f"/content/enforced/111111-COURSE101/outline-{topic_id}.html",
        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
        "IsBroken": False,
    }


def _toc(topic: dict[str, object]) -> dict[str, object]:
    return {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Week 1",
                "Modules": [],
                "Topics": [topic],
            }
        ]
    }


class FakeOutlineBrowser:
    def __init__(self, result: OutlinePage | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[str, ...], float]] = []
        self.closed = 0

    def render_outline(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float,
    ) -> OutlinePage:
        self.calls.append((url, allowed_hosts, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def close_target(self) -> None:
        self.closed += 1


def _metadata(tmp_path: Path, *, raw_url: str | None = None) -> tuple[Vault, MetadataReport]:
    client = FakeClient(
        [course()],
        tocs={111111: _toc(_outline_topic(url=raw_url))},
    )
    vault = Vault(tmp_path)
    report = ingest_metadata(client, vault, client.school)
    return vault, report


def _retarget(report: MetadataReport, url: str) -> MetadataReport:
    course_metadata = report.courses[0]
    topic = replace(course_metadata.topics[0], outline_url=url, url_path=None)
    updated_course = replace(course_metadata, topics=(topic,))
    return replace(report, courses=(updated_course,))


def test_allowed_outline_saves_source_and_markdown_twin(tmp_path: Path) -> None:
    vault, metadata = _metadata(tmp_path)
    page_url = "https://learn.uwaterloo.ca/content/enforced/111111-COURSE101/outline-1.html"
    browser = FakeOutlineBrowser(
        OutlinePage(
            html="<html><head><title>Outline</title></head><body><h1>Policies</h1></body></html>",
            canonical_url=page_url,
            subresources=("https://learn.uwaterloo.ca/d2l/styles.css",),
            top_level_requests=(page_url,),
        )
    )

    result = ingest_outlines(browser, vault, UWaterloo(), metadata)

    assert result.rendered == 1
    assert result.unavailable == 0
    assert browser.closed == 1
    entry = vault.entry("uwaterloo:111111:topic:1")
    assert entry is not None
    source = vault.materialized(entry)
    markdown = vault.root / Path(*entry.derived["markdown"].path.split("/"))
    assert source.suffix == ".html"
    source_text = source.read_text(encoding="utf-8")
    assert "<script" not in source_text
    assert "Policies" in source_text
    assert "# Course Outline" in markdown.read_text(encoding="utf-8")
    assert entry.derived["markdown"].source_sha256 == sha256(source.read_bytes()).hexdigest()

    row = metadata.courses[0].directory / "_meta" / "content_map.json"
    assert '"availability": "markdown_ready"' in row.read_text(encoding="utf-8")


def test_declared_outline_host_is_query_free_and_pdf_is_twinned(tmp_path: Path) -> None:
    class ReviewSchool(UWaterloo):
        base_url = "https://learn.example.test"

        def outline_hosts(self) -> list[str]:
            return ["outline.example.test"]

    school = ReviewSchool()
    client = FakeClient(
        [course()],
        tocs={
            111111: _toc(
                _outline_topic(
                    url="https://outline.example.test/syllabus.pdf?signature=do-not-store#fragment"
                )
            )
        },
    )
    vault = Vault(tmp_path)
    metadata = ingest_metadata(client, vault, school)
    browser = FakeOutlineBrowser(
        OutlinePage(
            html="<html><body>PDF wrapper</body></html>",
            canonical_url="https://outline.example.test/syllabus.pdf",
            pdf=b"%PDF-synthetic-outline",
            subresources=("https://outline.example.test/styles.css",),
        )
    )

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.rendered == 1
    assert browser.calls[0][0] == "https://outline.example.test/syllabus.pdf"
    assert "signature" not in browser.calls[0][0]
    entry = vault.entry("uwaterloo:111111:topic:1")
    assert entry is not None
    assert vault.materialized(entry).suffix == ".pdf"
    assert (vault.root / Path(*entry.derived["markdown"].path.split("/"))).is_file()


def test_rendered_canonical_url_is_normalized_before_metadata_is_persisted(tmp_path: Path) -> None:
    class ReviewSchool(UWaterloo):
        base_url = "https://learn.example.test"

        def outline_hosts(self) -> list[str]:
            return ["outline.example.test"]

    school = ReviewSchool()
    vault, metadata = _metadata(tmp_path)
    metadata = _retarget(metadata, "https://outline.example.test/syllabus.pdf")
    browser = FakeOutlineBrowser(
        OutlinePage(
            html="<html><body>PDF wrapper</body></html>",
            canonical_url="https://outline.example.test/syllabus.pdf?signature=SECRET#fragment",
            pdf=b"%PDF-synthetic-outline",
        )
    )

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.rendered == 1
    outline_metadata = next(vault.root.rglob("outlines.json")).read_text(encoding="utf-8")
    assert "https://outline.example.test/syllabus.pdf" in outline_metadata
    assert "SECRET" not in outline_metadata
    assert "#fragment" not in outline_metadata


@pytest.mark.parametrize(
    ("canonical_url", "subresources", "top_level_requests", "popups", "html"),
    [
        ("https://evil.example/outline.html", (), (), (), "<html>outline</html>"),
        (
            "https://learn.example.test/outline.html",
            ("https://evil.example/style.css",),
            (),
            (),
            "<html>outline</html>",
        ),
        (
            "https://learn.example.test/outline.html",
            (),
            ("https://evil.example/redirect",),
            (),
            "<html>outline</html>",
        ),
        (
            "https://learn.example.test/outline.html",
            (),
            (),
            ("https://evil.example/popup",),
            "<html>outline</html>",
        ),
        (
            "https://learn.example.test/outline.html",
            (),
            (),
            (),
            "<html><title>Sign in</title><body>login</body></html>",
        ),
    ],
)
def test_unsafe_outline_render_is_unavailable_and_not_installed(
    tmp_path: Path,
    canonical_url: str,
    subresources: tuple[str, ...],
    top_level_requests: tuple[str, ...],
    popups: tuple[str, ...],
    html: str,
) -> None:
    vault, metadata = _metadata(tmp_path)
    metadata = _retarget(metadata, "https://learn.example.test/outline.html")
    browser = FakeOutlineBrowser(
        OutlinePage(
            html=html,
            canonical_url=canonical_url,
            subresources=subresources,
            top_level_requests=top_level_requests,
            popups=popups,
        )
    )
    school = type("ReviewSchool", (UWaterloo,), {"base_url": "https://learn.example.test"})()

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.rendered == 0
    assert result.unavailable == 1
    assert browser.closed == 1
    assert vault.manifest() == {}
    assert not [path for path in tmp_path.rglob("*") if "Outlines" in path.parts]


@pytest.mark.parametrize(
    "url",
    [
        "http://learn.example.test/outline.html",
        "https://user:password@learn.example.test/outline.html",  # pragma: allowlist secret
        "https://learn.example.test.evil/outline.html",
    ],
)
def test_unsafe_outline_target_is_rejected_before_browser_navigation(
    tmp_path: Path, url: str
) -> None:
    vault, metadata = _metadata(tmp_path)
    metadata = _retarget(metadata, url)
    browser = FakeOutlineBrowser(
        OutlinePage(
            html="<html><body>never rendered</body></html>",
            canonical_url="https://learn.example.test/outline.html",
        )
    )
    school = type("ReviewSchool", (UWaterloo,), {"base_url": "https://learn.example.test"})()

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.rendered == 0
    assert result.unavailable == 1
    assert browser.calls == []
    assert browser.closed == 0


def test_outline_timeout_is_a_gap_and_target_is_closed(tmp_path: Path) -> None:
    vault, metadata = _metadata(tmp_path)
    metadata = _retarget(metadata, "https://learn.example.test/outline.html")
    browser = FakeOutlineBrowser(TimeoutError("settle timeout"))
    school = type("ReviewSchool", (UWaterloo,), {"base_url": "https://learn.example.test"})()

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.unavailable == 1
    assert result.errors == ("outline: TimeoutError",)
    assert browser.closed == 1


def test_outline_target_cleanup_failure_is_reported_and_stops_following_targets(
    tmp_path: Path,
) -> None:
    vault, metadata = _metadata(tmp_path)
    metadata = _retarget(metadata, "https://learn.example.test/outline.html")

    class FailingCloseBrowser(FakeOutlineBrowser):
        def close_target(self) -> None:
            raise RuntimeError("synthetic close failure")

    browser = FailingCloseBrowser(
        OutlinePage(
            html="<html><body>outline</body></html>",
            canonical_url="https://learn.example.test/outline.html",
        )
    )
    school = type("ReviewSchool", (UWaterloo,), {"base_url": "https://learn.example.test"})()

    result = ingest_outlines(browser, vault, school, metadata)

    assert result.rendered == 1
    assert result.errors == ("outline: target cleanup failed (RuntimeError)",)
    rows = json.loads(
        (metadata.courses[0].directory / "_meta" / "outlines.json").read_text(encoding="utf-8")
    )
    assert rows[0]["cleanup_error"] == "target could not be closed"


def test_outline_mapping_rejects_malformed_request_audit() -> None:
    with pytest.raises(ValueError, match="subresources"):
        outlines_module._coerce_page(
            {
                "html": "<html><body>outline</body></html>",
                "canonical_url": "https://learn.example.test/outline.html",
                "subresources": [123],
            }
        )


class FakeCDP:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        event_handler: Any = None,
    ) -> dict[str, object]:
        del params, event_handler
        self.calls.append(method)
        if method == "Runtime.evaluate":
            if self.calls.count(method) == 1:
                return {"result": {"value": "complete"}}
            return {
                "result": {
                    "value": {
                        "html": "<html><body>outline</body></html>",
                        "url": "https://learn.example.test/outline.html",
                    }
                }
            }
        return {}

    def send_without_wait(self, method: str, params: dict[str, object]) -> None:
        self.sent.append((method, params))

    def close(self) -> None:
        self.closed = True


def test_cdp_outline_browser_uses_existing_connection_and_no_new_profile() -> None:
    connection = FakeCDP()
    browser = CDPOutlineBrowser(connection)

    page = browser.render_outline(
        "https://learn.example.test/outline.html",
        allowed_hosts=("learn.example.test",),
        timeout=0.1,
    )

    assert page.canonical_url == "https://learn.example.test/outline.html"
    assert "Page.navigate" in connection.calls
    assert "Fetch.enable" in connection.calls
    browser.close_target()
    assert connection.calls[-1] == "Page.close"
    assert connection.closed is True
