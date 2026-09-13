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
from golden_support import CANONICAL_ORIGIN, FROZEN_NOW, GoldenSchool, _CanonicalOriginAdapter
from ingest_support import FakeClient, course
from pytest_httpserver import HTTPServer
from pytest_httpserver.httpserver import RequestHandler

from agent2learn import audit, calendar, clock, doctor, metadata_coverage
from agent2learn import ingest as ingest_module
from agent2learn.api import Client
from agent2learn.convert import ConversionReport
from agent2learn.errors import AuthenticationError, NotConfigured, SessionExpired
from agent2learn.index import read_content_map
from agent2learn.ingest import FileReport, MetadataReport, OutlineReport
from agent2learn.session import Session
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
        return OutlineReport(unavailable=1)

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

    gaps, errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(unavailable=1),
        FileReport(),
        ConversionReport(),
        outline_failure=False,
    )

    assert gaps == ()
    assert errors == ()
    assert exit_code == 0


def test_unavailable_outline_is_a_recorded_gap_not_a_failure() -> None:
    pipeline = _pipeline()

    gaps, errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(unavailable=1),
        FileReport(),
        ConversionReport(),
        outline_failure=True,
    )

    assert gaps == ("outline gaps",)
    assert errors == ()
    assert exit_code == 0


def test_persistent_download_gap_is_recorded_without_failing_the_sync() -> None:
    pipeline = _pipeline()

    gaps, errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(),
        FileReport(downloaded=3, download_gaps=1),
        ConversionReport(),
        outline_failure=True,
    )

    assert gaps == ("download gaps",)
    assert errors == ()
    assert exit_code == 0


def test_outline_renderer_infrastructure_failure_makes_the_typed_report_nonzero() -> None:
    pipeline = _pipeline()

    gaps, errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(rendered=1, errors=("outline: target cleanup failed (RuntimeError)",)),
        FileReport(),
        ConversionReport(),
        outline_failure=True,
    )

    assert gaps == ()
    assert errors == ("outline renderer incomplete",)
    assert exit_code == 1


def test_local_download_failure_still_makes_the_typed_report_nonzero() -> None:
    pipeline = _pipeline()

    gaps, errors, exit_code = pipeline._result_status(
        MetadataReport(courses=(), topic_count=0, deadline_count=0),
        OutlineReport(),
        FileReport(failed=1, errors=("download: DiskSpaceExhausted",)),
        ConversionReport(),
        outline_failure=True,
    )

    assert gaps == ()
    assert errors == ("file sync incomplete",)
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


@pytest.mark.parametrize("selection", [{}, {"selected_offering_ids": None}])
def test_incomplete_initializer_selection_does_not_authorize_sync(
    tmp_path: Path, selection: dict[str, object]
) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    (vault.state() / "init.json").write_text(
        json.dumps({"schema_version": 1, "vault_confirmed": True, **selection}),
        encoding="utf-8",
    )

    with pytest.raises(NotConfigured, match="a2l init"):
        _pipeline().load_sync_preferences(vault)


def _reading_toc() -> dict[str, object]:
    return {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Readings",
                "Modules": [],
                "Topics": [
                    {
                        "TopicId": 1,
                        "Title": "Reading.txt",
                        "TypeIdentifier": "File",
                        "Url": "/content/reading.txt",
                        "Size": 50,
                    }
                ],
            }
        ]
    }


def test_empty_selected_course_does_not_stop_other_courses(tmp_path: Path) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    client = FakeClient(
        [course(), course(222222, code="COURSE202")],
        tocs={111111: {"Modules": []}, 222222: _reading_toc()},
    )

    report = _pipeline().run_pipeline(client, vault, client.school, render_outlines=False)

    assert report.exit_code == 0
    assert report.files.downloaded == 1
    assert report.indexed_courses == 2
    assert vault.entry("uwaterloo:222222:topic:1") is not None
    assert (vault.root / report.snapshot_path).is_file()


@pytest.mark.parametrize("invalid", [{"unexpected": []}, {"Modules": [{"ModuleId": 1}]}])
def test_malformed_toc_keeps_cache_but_blocks_success_and_downloads(
    tmp_path: Path, invalid: dict[str, object]
) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    client = FakeClient([course()], tocs={111111: _reading_toc()})
    initial = ingest_module.ingest_metadata(client, vault, client.school)
    client.tocs[111111] = invalid

    report = _pipeline().run_pipeline(client, vault, client.school, render_outlines=False)

    assert report.exit_code != 0 and report.metadata.errors
    assert any(error.startswith("toc:") for error in report.metadata.errors)
    assert client.download_calls == []
    assert report.metadata.topic_count == initial.topic_count == 1
    row = report.metadata.courses[0].topics[0]
    assert row.missing_since is None and row.withdrawn_at is None


def _deny_quizzes(
    handler: RequestHandler,
    *,
    detail: str = (
        "Not authorized for [ orgUnitId: 111111, securityVariableName: Quizzing.SeeQuizzing ]"
    ),
) -> None:
    handler.respond_with_json(
        {
            "type": "http://docs.valence.desire2learn.com/res/apiprop.html#not-authorized",
            "title": "Not Authorized",
            "status": 403,
            "detail": detail,
        },
        status=403,
        content_type="application/problem+json; charset=UTF-8",
    )


def _quiz_client(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, GoldenSchool, RequestHandler]:
    monkeypatch.setattr("agent2learn.api.JITTER_MAX", 0.0)
    school = GoldenSchool(CANONICAL_ORIGIN)
    client: Any = Client(school, Session(CANONICAL_ORIGIN, (), None, FROZEN_NOW, None), workers=1)
    client.lp_version = "1.62"
    client.le_version = "1.97"
    client.courses = [course()]
    client.download_template = "{base}/content/reading.txt"
    client._transport.mount(
        CANONICAL_ORIGIN,
        _CanonicalOriginAdapter(CANONICAL_ORIGIN, httpserver.url_for("")),
    )
    prefix = "/d2l/api/le/1.97/111111/"
    httpserver.expect_request(prefix + "content/toc").respond_with_json(_reading_toc())
    httpserver.expect_request(prefix + "dropbox/folders/").respond_with_json([])
    httpserver.expect_request(prefix + "news/").respond_with_json([])
    quiz_handler = httpserver.expect_request(prefix + "quizzes/")
    _deny_quizzes(quiz_handler)
    httpserver.expect_request("/content/reading.txt").respond_with_data(
        "Readable course material.\n", content_type="text/plain"
    )
    return client, school, quiz_handler


def _quiz_denied_pipeline(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Any, Vault, GoldenSchool]:
    client, school, _ = _quiz_client(httpserver, monkeypatch)
    vault = Vault(Vault.claim(tmp_path / "vault"))
    report = _pipeline().run_pipeline(client, vault, school, render_outlines=False)
    return report, vault, school


def test_quiz_permission_denial_keeps_accessible_content_citable(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report, vault, _ = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)

    assert report.files.downloaded == 1
    assert report.conversion.converted == 1
    coverage_file = report.metadata.courses[0].directory / "_meta" / "metadata_coverage.json"
    assert coverage_file.is_file()
    coverage = json.loads(coverage_file.read_text(encoding="utf-8"))
    assert coverage == {
        "schema_version": 1,
        "collections": {
            "quizzes": {
                "status": "unavailable",
                "http_status": 403,
                "error_code": "not_authorized",
                "permission": "Quizzing.SeeQuizzing",
            }
        },
    }
    rows = read_content_map(report.metadata.courses[0].directory)["topics"]
    assert isinstance(rows, list)
    row = rows[0]
    assert row["availability"] == "markdown_ready"
    assert "Readable course material." in (vault.root / row["path"]).read_text(encoding="utf-8")
    assert report.exit_code == 0
    summary = _pipeline().render_report(report)
    assert "quizzes" in summary and "403" in summary
    assert "Quizzing.SeeQuizzing" in summary


def test_resumed_metadata_retains_the_quiz_permission_gap(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, vault, school = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)

    restored = ingest_module.load_metadata_report(vault, school, [course()])

    assert len(restored.gaps) == 1
    assert "quizzes" in restored.gaps[0] and "403" in restored.gaps[0]
    assert "Quizzing.SeeQuizzing" in restored.gaps[0]
    assert not restored.errors


def test_audit_does_not_present_denied_quiz_inventory_as_zero(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report, vault, _ = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)

    result = audit.audit_vault(vault)[0]
    rendered = (vault.root / report.audit_path).read_text(encoding="utf-8")

    assert any("quizzes" in gap and "403" in gap for gap in result.metadata_gaps)
    assert "Quizzing.SeeQuizzing" in rendered
    assert "- 0 quizzes" not in rendered
    assert "unavailable" in rendered


def test_today_warns_that_quiz_deadlines_are_unavailable(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, vault, school = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)

    rendered = calendar.render_today(calendar.build_today(vault, school, now=FROZEN_NOW))

    assert "quizzes" in rendered and "403" in rendered
    assert "Quizzing.SeeQuizzing" in rendered
    assert "No assignments or quizzes due within 7 days." not in rendered


def test_public_doctor_report_identifies_the_denied_collection_without_identifiers(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, vault, _ = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)

    checks = doctor._vault(vault)
    rendered = doctor.report(checks)

    assert any("quizzes" in check.name and check.status == "warn" for check in checks)
    assert "quizzes" in rendered and "403" in rendered
    assert "111111" not in rendered
    assert "COURSE101" not in rendered
    assert str(vault.root) not in rendered


def test_quiz_denial_preserves_cache_and_recovery_replaces_coverage(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(clock, "stamp", lambda: "2026-08-25T12:00:00Z")
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    quiz_response.respond_with_json(
        {"Next": None, "Objects": [{"QuizId": 77, "Name": "Recorded quiz", "DueDate": None}]}
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))
    initial = _pipeline().run_pipeline(client, vault, school, render_outlines=False)
    directory = initial.metadata.courses[0].directory
    quiz_file = directory / "_meta" / "quizzes.json"
    original_quizzes = quiz_file.read_bytes()
    rows = read_content_map(directory)["topics"]
    assert isinstance(rows, list)
    row = rows[0]
    twin = vault.root / row["path"]
    original_twin = twin.read_bytes()

    _deny_quizzes(quiz_response)
    for _ in range(2):
        denied = _pipeline().run_pipeline(client, vault, school, render_outlines=False)
        assert denied.exit_code == 0 and denied.gaps
        assert quiz_file.read_bytes() == original_quizzes
        assert twin.read_bytes() == original_twin
        assert metadata_coverage.read_quiz_coverage(directory).status == "unavailable"
        cached = json.loads(quiz_file.read_text(encoding="utf-8"))[0]
        assert not cached.get("missing_since") and not cached.get("withdrawn_at")

    quiz_response.respond_with_json({"Next": None, "Objects": []})
    recovered = _pipeline().run_pipeline(client, vault, school, render_outlines=False)
    cached = json.loads(quiz_file.read_text(encoding="utf-8"))[0]

    assert recovered.exit_code == 0 and not recovered.gaps
    assert metadata_coverage.read_quiz_coverage(directory).status == "complete"
    assert cached.get("missing_since") and not cached.get("withdrawn_at")
    assert "403" not in (vault.root / recovered.audit_path).read_text(encoding="utf-8")
    assert "403" not in calendar.render_today(calendar.build_today(vault, school, now=FROZEN_NOW))
    assert "403" not in doctor.report(doctor._vault(vault))


def test_successfully_fetched_empty_quizzes_are_not_an_unavailable_inventory(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    quiz_response.respond_with_json({"Next": None, "Objects": []})
    vault = Vault(Vault.claim(tmp_path / "vault"))

    report = _pipeline().run_pipeline(client, vault, school, render_outlines=False)

    assert report.exit_code == 0 and not report.gaps
    assert (
        metadata_coverage.read_quiz_coverage(report.metadata.courses[0].directory).status
        == "complete"
    )
    assert "- 0 quizzes" in (vault.root / report.audit_path).read_text(encoding="utf-8")
    assert not calendar.build_today(vault, school, now=FROZEN_NOW).metadata_gaps


def test_failed_quiz_cache_write_cannot_publish_complete_coverage(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    vault = Vault(Vault.claim(tmp_path / "vault"))
    denied = _pipeline().run_pipeline(client, vault, school, render_outlines=False)
    directory = denied.metadata.courses[0].directory
    original = ingest_module._write_list

    def fail_quiz_write(destination: Path, rows: Sequence[Any], **kwargs: Any) -> None:
        if destination.name == "quizzes.json":
            raise OSError("synthetic local write failure")
        original(destination, rows, **kwargs)

    monkeypatch.setattr(ingest_module, "_write_list", fail_quiz_write)
    quiz_response.respond_with_json({"Next": None, "Objects": []})

    with pytest.raises(OSError, match="synthetic local write failure"):
        _pipeline().run_pipeline(client, vault, school, render_outlines=False)

    coverage = metadata_coverage.read_quiz_coverage(directory)
    assert coverage.status == "unavailable" and coverage.http_status == 403


def test_html_quiz_forbidden_still_requires_reauthentication(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    quiz_response.respond_with_data(
        "<html><body>Sign in</body></html>", status=403, content_type="text/html"
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))

    with pytest.raises(SessionExpired):
        _pipeline().run_pipeline(client, vault, school, render_outlines=False)

    assert vault.entry("synthetic:111111:topic:1") is None


@pytest.mark.parametrize("status", [401, 404])
def test_other_quiz_http_failures_are_not_downgraded_to_permission_gaps(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int
) -> None:
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    quiz_response.respond_with_json({"status": status}, status=status)
    vault = Vault(Vault.claim(tmp_path / "vault"))

    report = _pipeline().run_pipeline(client, vault, school, render_outlines=False)

    assert report.exit_code != 0 and report.metadata.errors
    assert report.files.downloaded == 0
    assert not report.metadata.gaps
    assert vault.entry("synthetic:111111:topic:1") is None
    restored = ingest_module.load_metadata_report(vault, school, [course()])
    assert restored.errors


@pytest.mark.parametrize(
    "detail",
    [
        "PRIVATE-DIAGNOSTIC Not authorized for [ orgUnitId: 111111, "
        "securityVariableName: Quizzing.SeeQuizzing ]",
        "PRIVATE-DIAGNOSTIC securityVariableName: Unreviewed.Permission ]",
        "PRIVATE-DIAGNOSTIC " * 600,
    ],
)
def test_quiz_gap_never_persists_or_renders_arbitrary_problem_details(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, detail: str
) -> None:
    client, school, quiz_response = _quiz_client(httpserver, monkeypatch)
    _deny_quizzes(quiz_response, detail=detail)
    vault = Vault(Vault.claim(tmp_path / "vault"))

    report = _pipeline().run_pipeline(client, vault, school, render_outlines=False)

    coverage_file = report.metadata.courses[0].directory / "_meta" / "metadata_coverage.json"
    rendered = "\n".join(
        [
            coverage_file.read_text(encoding="utf-8"),
            _pipeline().render_report(report),
            (vault.root / report.audit_path).read_text(encoding="utf-8"),
            calendar.render_today(calendar.build_today(vault, school, now=FROZEN_NOW)),
            doctor.report(doctor._vault(vault)),
        ]
    )
    assert report.exit_code == 0 and report.files.downloaded == 1
    assert "403" in rendered
    assert "PRIVATE-DIAGNOSTIC" not in rendered
    assert "Unreviewed.Permission" not in rendered


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "not json",
        '{"schema_version": 99, "collections": {"quizzes": {"status": "complete"}}}',
        '{"schema_version": 1, "collections": {"quizzes": {"status": "unavailable", '
        '"http_status": 403, "permission": "UNREVIEWED-DIAGNOSTIC"}}}',
    ],
)
def test_missing_or_invalid_coverage_cannot_be_presented_as_known_empty_quizzes(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stored: str | None
) -> None:
    report, vault, school = _quiz_denied_pipeline(httpserver, monkeypatch, tmp_path)
    coverage_file = report.metadata.courses[0].directory / "_meta" / "metadata_coverage.json"
    if stored is None:
        coverage_file.unlink()
    else:
        coverage_file.write_text(stored, encoding="utf-8")

    today = calendar.render_today(calendar.build_today(vault, school, now=FROZEN_NOW))
    audit_text = audit.write_audit(vault).read_text(encoding="utf-8")
    diagnostics = doctor.report(doctor._vault(vault))

    assert "quizzes coverage unknown" in today
    assert "No assignments or quizzes due within 7 days." not in today
    assert "- 0 quizzes" not in audit_text
    assert "metadata.quizzes" in diagnostics and "warn" in diagnostics
    assert "UNREVIEWED-DIAGNOSTIC" not in today + audit_text + diagnostics
