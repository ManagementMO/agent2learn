"""Focused contracts for the reusable production sync orchestrator."""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar

import pytest
from ingest_support import FakeClient, course

from agent2learn import clock
from agent2learn import ingest as ingest_module
from agent2learn.convert import ConversionReport
from agent2learn.errors import AuthenticationError, NotConfigured
from agent2learn.ingest import FileReport, MetadataReport, OutlineReport
from agent2learn.vault import Vault


def _pipeline() -> Any:
    return importlib.import_module("agent2learn.pipeline")


_T = TypeVar("_T")


class _UnusedOutlineFactory:
    def open_browser(self) -> object:
        raise AssertionError("no outline target should be requested")

    def close(self) -> None:
        return


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_pipeline_exposes_metadata_before_every_expensive_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline = _pipeline()
    events: list[str] = []
    metadata = MetadataReport(courses=(), topic_count=4, deadline_count=2)

    def record(event: str, value: _T) -> _T:
        events.append(event)
        return value

    monkeypatch.setattr(
        pipeline,
        "ingest_metadata",
        lambda *_args, **_kwargs: record("metadata", metadata),
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_outlines",
        lambda *_args, **_kwargs: record("outlines", OutlineReport()),
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_files",
        lambda *_args, **_kwargs: record("files", FileReport()),
    )
    monkeypatch.setattr(
        pipeline,
        "convert_vault",
        lambda *_args, **_kwargs: record("conversion", ConversionReport()),
    )
    monkeypatch.setattr(
        pipeline,
        "refresh_indexes",
        lambda *_args, **_kwargs: record("indexes", 0),
    )
    monkeypatch.setattr(
        pipeline,
        "write_snapshot",
        lambda *_args, **_kwargs: record("snapshot", tmp_path / ".a2l/snapshot.json"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_audit",
        lambda *_args, **_kwargs: record("audit", tmp_path / ".a2l/AUDIT.md"),
    )

    report = pipeline.run_pipeline(
        object(),
        Vault(tmp_path),
        SimpleNamespace(),
        outline_factory=_UnusedOutlineFactory(),
        metadata_observer=lambda value: events.append(f"observer:{value.topic_count}"),
    )

    assert events == [
        "metadata",
        "observer:4",
        "outlines",
        "files",
        "conversion",
        "indexes",
        "snapshot",
        "audit",
    ]
    assert report.metadata is metadata


def test_pipeline_uses_precomputed_metadata_without_refetching_and_can_skip_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline = _pipeline()
    metadata = MetadataReport(courses=(), topic_count=2, deadline_count=1)
    monkeypatch.setattr(
        pipeline,
        "ingest_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completed onboarding metadata must not be refetched")
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("later scope must not download files")
        ),
    )
    monkeypatch.setattr(pipeline, "convert_vault", lambda *_args, **_kwargs: ConversionReport())
    monkeypatch.setattr(pipeline, "refresh_indexes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(pipeline, "write_snapshot", lambda *_args, **_kwargs: tmp_path / "s.json")
    monkeypatch.setattr(pipeline, "write_audit", lambda *_args, **_kwargs: tmp_path / "AUDIT.md")

    report = pipeline.run_pipeline(
        object(),
        Vault(tmp_path),
        SimpleNamespace(),
        metadata=metadata,
        download_files=False,
        render_outlines=False,
    )

    assert report.metadata is metadata
    assert report.files == FileReport()
    assert report.audit_path == "AUDIT.md"


def test_pipeline_converts_all_local_sources_when_no_file_was_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline = _pipeline()
    converted: list[tuple[Vault, int]] = []
    metadata = MetadataReport(courses=(), topic_count=0, deadline_count=0)

    monkeypatch.setattr(pipeline, "ingest_metadata", lambda *_args, **_kwargs: metadata)
    monkeypatch.setattr(pipeline, "ingest_outlines", lambda *_args, **_kwargs: OutlineReport())
    monkeypatch.setattr(
        pipeline,
        "ingest_files",
        lambda *_args, **_kwargs: FileReport(downloaded=0),
    )

    def convert(vault: Vault, *, ocr_words_per_page: int) -> ConversionReport:
        converted.append((vault, ocr_words_per_page))
        return ConversionReport(skipped=3)

    monkeypatch.setattr(pipeline, "convert_vault", convert)
    monkeypatch.setattr(pipeline, "refresh_indexes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(pipeline, "write_snapshot", lambda *_args, **_kwargs: tmp_path / "s.json")
    monkeypatch.setattr(pipeline, "write_audit", lambda *_args, **_kwargs: tmp_path / "AUDIT.md")
    vault = Vault(tmp_path)

    report = pipeline.run_pipeline(
        object(),
        vault,
        SimpleNamespace(),
        outline_factory=_UnusedOutlineFactory(),
        ocr_words_per_page=91,
    )

    assert converted == [(vault, 91)]
    assert report.files.downloaded == 0
    assert report.conversion.skipped == 3


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("full", "all"), ("priority", "priority"), ("later", "all")],
)
def test_sync_preferences_use_valid_init_scope_then_recommended_full_default(
    tmp_path: Path, stored: str | None, expected: str
) -> None:
    pipeline = _pipeline()
    root = tmp_path / (stored or "missing")
    Vault.claim(root)
    if stored is not None:
        (root / ".a2l" / "init.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "file_scope": stored,
                    "term": "1265",
                    "selected_offering_ids": [111111, 222222],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    preferences = pipeline.load_sync_preferences(Vault(root))

    assert preferences.scope == expected
    if stored is None:
        assert preferences.term is None
        assert preferences.only is None
    else:
        assert preferences.term == "1265"
        assert preferences.only == (111111, 222222)


def test_sync_preferences_require_initializer_state_before_any_course_can_broaden(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    Vault.claim(root)

    with pytest.raises(NotConfigured, match="a2l init"):
        _pipeline().load_sync_preferences(Vault(root), scope_override="all")


def test_sync_preferences_reject_an_invalid_existing_course_selection(tmp_path: Path) -> None:
    pipeline = _pipeline()
    root = tmp_path / "vault"
    Vault.claim(root)
    (root / ".a2l" / "init.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "file_scope": "priority",
                "term": "1265",
                "selected_offering_ids": [True],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="offering IDs"):
        pipeline.load_sync_preferences(Vault(root))


def test_sync_preferences_reject_an_unhashable_existing_file_scope(tmp_path: Path) -> None:
    pipeline = _pipeline()
    root = tmp_path / "vault"
    Vault.claim(root)
    (root / ".a2l" / "init.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "file_scope": ["priority"],
                "selected_offering_ids": [111111],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="file scope"):
        pipeline.load_sync_preferences(Vault(root))


@pytest.mark.parametrize("profile_consent", [False, None])
def test_absent_or_declined_profile_consent_records_outlines_without_opening_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile_consent: bool | None
) -> None:
    pipeline = _pipeline()
    metadata = MetadataReport(courses=(), topic_count=0, deadline_count=0)
    observed_factories: list[object] = []

    monkeypatch.setattr(pipeline, "ingest_metadata", lambda *_args, **_kwargs: metadata)

    def outlines(factory: Any, *_args: object) -> OutlineReport:
        observed_factories.append(factory)
        with pytest.raises(AuthenticationError, match="not enabled"):
            factory.open_browser()
        return OutlineReport(unavailable=1, errors=("outline: AuthenticationError",))

    monkeypatch.setattr(pipeline, "ingest_outlines", outlines)
    monkeypatch.setattr(
        pipeline,
        "dedicated_profile_outline_factory",
        lambda: (_ for _ in ()).throw(AssertionError("profile must remain closed")),
    )
    monkeypatch.setattr(pipeline, "ingest_files", lambda *_args, **_kwargs: FileReport())
    monkeypatch.setattr(pipeline, "convert_vault", lambda *_args, **_kwargs: ConversionReport())
    monkeypatch.setattr(pipeline, "refresh_indexes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(pipeline, "write_snapshot", lambda *_args, **_kwargs: tmp_path / "s.json")
    monkeypatch.setattr(pipeline, "write_audit", lambda *_args, **_kwargs: tmp_path / "AUDIT.md")

    report = pipeline.run_pipeline(
        object(),
        Vault(tmp_path),
        SimpleNamespace(),
        profile_consent=profile_consent,
    )

    assert len(observed_factories) == 1
    assert report.outlines.unavailable == 1
    assert report.exit_code == 0


def test_declined_outline_profile_is_coverage_not_a_sync_failure() -> None:
    pipeline = _pipeline()

    errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(unavailable=1),
        FileReport(),
        ConversionReport(),
        outline_failure=False,
    )

    assert errors == ()
    assert exit_code == 0


def test_actual_outline_failure_makes_the_typed_report_nonzero() -> None:
    pipeline = _pipeline()

    errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(unavailable=1),
        FileReport(),
        ConversionReport(),
        outline_failure=True,
    )

    assert errors == ("outline unavailable",)
    assert exit_code == 1


def test_second_unchanged_pipeline_run_is_byte_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline = _pipeline()
    monkeypatch.setattr(clock, "stamp", lambda: "2026-08-25T12:00:00Z")
    metadata_snapshot_calls: list[None] = []
    original_metadata_snapshot = ingest_module.snapshot.write_snapshot

    def metadata_snapshot(
        vault: Vault,
        course_dirs: Sequence[Path],
        *,
        include_grades: bool,
        timestamp: str,
    ) -> Path:
        metadata_snapshot_calls.append(None)
        return original_metadata_snapshot(
            vault,
            course_dirs,
            include_grades=include_grades,
            timestamp=timestamp,
        )

    monkeypatch.setattr(ingest_module.snapshot, "write_snapshot", metadata_snapshot)
    toc = {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Week 1",
                "Modules": [],
                "Topics": [
                    {
                        "TopicId": 1,
                        "Title": "Reading.Rmd",
                        "TypeIdentifier": "File",
                        "Url": "/content/enforced/111111-COURSE101/reading.Rmd",
                        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
                        "Size": 64,
                        "IsBroken": False,
                    }
                ],
            }
        ]
    }
    client = FakeClient([course()], tocs={111111: toc})
    root = tmp_path / "vault"
    Vault.claim(root)
    vault = Vault(root)

    first_report = pipeline.run_pipeline(
        client,
        vault,
        client.school,
        outline_factory=_UnusedOutlineFactory(),
    )
    first = _tree(root)
    index_text = next(root.rglob("INDEX.md")).read_text(encoding="utf-8")
    assert "Reading.md" in index_text
    assert "markdown_ready" in index_text
    second_report = pipeline.run_pipeline(
        client,
        vault,
        client.school,
        outline_factory=_UnusedOutlineFactory(),
    )

    assert first_report.files.downloaded == 1
    assert second_report.files.downloaded == 0
    assert second_report.conversion.converted == 0
    assert metadata_snapshot_calls == []
    assert len(list((root / ".a2l" / "snapshots").glob("*.json"))) == 1
    assert first_report.snapshot_path == second_report.snapshot_path
    assert _tree(root) == first
