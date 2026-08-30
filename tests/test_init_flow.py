"""End-to-end onboarding orchestration tests for ``a2l init``.

The command is exercised through Typer, while authentication, calibration, and the expensive
ingest phases are replaced with small synthetic collaborators.  This keeps the tests offline and
proves the CLI's ordering and persistence contract rather than duplicating browser or HTTP tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from typer.testing import CliRunner

from agent2learn import cli, clock, config
from agent2learn import index as course_index
from agent2learn.calibrate import Calibration, CourseRef
from agent2learn.errors import A2LError
from agent2learn.ingest import CourseMetadata, FileReport, MetadataReport, TopicRecord
from agent2learn.skills import Destination
from agent2learn.vault import Vault


@dataclass
class InitWorld:
    root: Path
    courses: list[CourseRef]
    events: list[str]
    metadata_calls: list[dict[str, object]]
    file_calls: list[dict[str, object]]
    auth_backends: list[str]


@dataclass
class _FakeClient:
    courses: list[CourseRef]
    calibration: Calibration | None = None


def _isolated_dirs(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        user_config_path=root / "config" / "agent2learn",
        user_state_path=root / "state" / "agent2learn",
        user_data_path=root / "data" / "agent2learn",
        user_log_path=root / "logs" / "agent2learn",
    )


def _courses(*, term: str = "1265") -> list[CourseRef]:
    return [
        CourseRef(111111, "COURSE101_sec01_1265", "Current Example", term, True),
        CourseRef(222222, "COURSE202_sec02_1265", "Another Example", term, True),
        CourseRef(333333, "EXAMPLEDEPT", "Example Department", None, True),
        CourseRef(444444, "COURSE404_sec01_1261", "Past Example", "1261", False),
    ]


def _calibration(courses: list[CourseRef]) -> Calibration:
    return Calibration(
        lp="1.62",
        le="1.96",
        download_template=None,
        courses=courses,
        calibrated_at="2026-08-28T12:00:00Z",
    )


def _metadata_report(world: InitWorld) -> MetadataReport:
    reports: list[CourseMetadata] = []
    topic_number = 900000
    for course in world.courses:
        if not course.is_active or course.term is None:
            continue
        directory = world.root / "Spring 2026" / f"{course.code}_{course.term}"
        directory.joinpath("_meta").mkdir(parents=True, exist_ok=True)
        assignments = [
            {
                "id": f"assignment-{course.org_unit_id}",
                "title": "Problem Set 3",
                "due_date": "2026-09-18T23:59:00Z",
            }
        ]
        quizzes = [
            {
                "id": f"quiz-{course.org_unit_id}",
                "title": "Quiz 1",
                "due_date": "2026-09-25T23:59:00Z",
            }
        ]
        directory.joinpath("_meta", "assignments.json").write_text(
            json.dumps(assignments) + "\n", encoding="utf-8"
        )
        directory.joinpath("_meta", "quizzes.json").write_text(
            json.dumps(quizzes) + "\n", encoding="utf-8"
        )
        topics = (
            _topic_record(
                course,
                topic_number,
                "Lecture notes.pdf",
                "/d2l/content/download/notes",
                8 * 1024 * 1024,
            ),
            _topic_record(
                course,
                topic_number + 1,
                "Lecture recording.mp4",
                "/d2l/content/download/recording",
                20 * 1024 * 1024,
            ),
            _topic_record(
                course,
                topic_number + 2,
                "Worksheet.pdf",
                "/d2l/content/download/worksheet.mp4",
                4 * 1024 * 1024,
            ),
        )
        course_index.write_content_map(directory, [asdict(topic) for topic in topics])
        reports.append(
            CourseMetadata(
                course=course,
                directory=directory,
                topics=topics,
                module_tree=(),
            )
        )
        topic_number += 10
    return MetadataReport(
        courses=tuple(reports),
        topic_count=sum(len(report.topics) for report in reports),
        deadline_count=len(reports) * 2,
    )


def _topic_record(
    course: CourseRef,
    topic_id: int,
    title: str,
    url_path: str,
    remote_size: int | None,
) -> TopicRecord:
    source_id = str(topic_id)
    return TopicRecord(
        source_key=f"uwaterloo:{course.org_unit_id}:topic:{source_id}",
        source_id=source_id,
        topic_id=topic_id,
        course_org_unit_id=course.org_unit_id,
        course_code=course.code,
        course_name=course.name,
        term=course.term,
        title=title,
        kind="File",
        module_path=(),
        module_ids=(),
        view_url="https://learn.uwaterloo.ca/d2l/home",
        outline_url=None,
        url_path=url_path,
        external_host=None,
        etag=None,
        last_modified=None,
        is_broken=False,
        remote_size=remote_size,
    )


def _prepare_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> InitWorld:
    root = tmp_path / "vault"
    Vault.claim(root)
    root.joinpath(".agents").mkdir()
    root.joinpath(".claude").mkdir()
    world = InitWorld(
        root=root,
        courses=_courses(),
        events=[],
        metadata_calls=[],
        file_calls=[],
        auth_backends=[],
    )
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True, raising=False)

    fake_session = object()

    def fake_auth(_school: object, *, backend: str) -> object:
        world.events.append("auth")
        world.auth_backends.append(backend)
        return fake_session

    def fake_client(_school: object, _session: object) -> _FakeClient:
        world.events.append("client")
        return _FakeClient(world.courses)

    def fake_calibrate(client: _FakeClient) -> Calibration:
        world.events.append("discovery")
        calibration = _calibration(world.courses)
        client.calibration = calibration
        client.courses = calibration.courses
        return calibration

    def fake_metadata(
        client: object,
        vault: Vault,
        school: object,
        *,
        term: str | None = None,
        only: Iterable[int | str] | None = None,
        include_grades: bool = False,
        create_snapshot: bool = True,
    ) -> MetadataReport:
        del client, vault, school, create_snapshot
        world.events.append("metadata")
        selected = list(only) if only is not None else None
        world.metadata_calls.append(
            {"term": term, "only": selected, "include_grades": include_grades}
        )
        return _metadata_report(world)

    def fake_files(
        client: object,
        vault: Vault,
        school: object,
        *,
        term: str | None = None,
        only: Iterable[int | str] | None = None,
        scope: str = "all",
        include_media: bool = False,
        **kwargs: object,
    ) -> FileReport:
        del client, vault, school, kwargs
        world.events.append("files")
        world.file_calls.append(
            {
                "term": term,
                "only": list(only) if only is not None else None,
                "scope": scope,
                "include_media": include_media,
            }
        )
        return FileReport(downloaded=2)

    def fake_install(*, confirm: object, **kwargs: object) -> object:
        del kwargs
        world.events.append("skills")
        assert callable(confirm)
        accepted = confirm("synthetic skills preview\n")
        return SimpleNamespace(cancelled=not accepted)

    monkeypatch.setattr(cli, "authenticate", fake_auth)
    monkeypatch.setattr(cli, "Client", fake_client)
    monkeypatch.setattr(cli, "calibrate", fake_calibrate)
    monkeypatch.setattr(cli, "ingest_metadata", fake_metadata)

    def fake_pipeline(*args: object, **kwargs: object) -> object:
        file_report = FileReport()
        if kwargs.get("download_files", True):
            file_report = cast(Callable[..., FileReport], fake_files)(*args, **kwargs)
        return SimpleNamespace(files=file_report, exit_code=0, errors=())

    def record_destination(**kwargs: object) -> tuple[Destination, ...]:
        world.events.append("skill_preview")
        project = cast(Path, kwargs["project"])
        return (
            Destination(
                path=project / ".agents" / "skills",
                agents=("Claude Code", "Codex"),
            ),
        )

    monkeypatch.setattr(cli.pipeline_module, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(
        cli.skills_module,
        "detect_destinations",
        record_destination,
    )
    monkeypatch.setattr(
        cli.skills_module,
        "detect_installed_agents",
        lambda: ("Claude Code", "Codex"),
    )
    monkeypatch.setattr(cli.skills_module, "install", fake_install)
    monkeypatch.setattr(cli.skills_module, "install_detected_project", fake_install)
    monkeypatch.setattr(cli.session_store, "load", lambda: fake_session)
    return world


def _state(root: Path) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(root.joinpath(".a2l", "init.json").read_text(encoding="utf-8")),
    )


def test_init_noninteractive_has_no_side_effects_and_hands_off_to_tty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    isolated = _isolated_dirs(tmp_path)
    monkeypatch.setattr(config, "DIRS", isolated)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 3
    assert "run: a2l init" in result.output
    assert result.output.count("run:") == 1
    assert not list(tmp_path.iterdir())


def test_init_runs_consent_and_sync_stages_in_order_and_persists_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert world.events == ["skill_preview", "skills", "auth", "client", "discovery", "metadata"]
    assert world.metadata_calls == [
        {"term": "1265", "only": [111111, 222222], "include_grades": False}
    ]
    assert world.file_calls == []
    assert _state(world.root)["selected_offering_ids"] == [111111, 222222]
    assert _state(world.root)["include_grades"] is False
    assert "6 topics" in result.stdout
    assert "2 assignments" in result.stdout
    assert "2 quizzes" in result.stdout
    assert "4 deadlines" in result.stdout
    assert "Problem Set 3" in result.stdout
    assert "grades not synced" in result.stdout
    assert "Files:" in result.stdout
    assert "download later" in result.stdout
    assert result.stdout.index("Include private grade values") < result.stdout.index(
        "dedicated local browser"
    )
    assert result.stdout.index("dedicated local browser") < result.stdout.index("Spring 2026")
    assert result.stdout.index("Spring 2026") < result.stdout.index("reading 2 courses")
    assert result.stdout.index("reading 2 courses") < result.stdout.index("Files:")


def test_init_deselection_passes_only_stable_offering_ids_to_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["init"], input="y\nn\nn\ny\nn\n1\nlater\n")

    assert result.exit_code == 0, result.output
    assert world.metadata_calls == [{"term": "1265", "only": [111111], "include_grades": False}]
    assert _state(world.root)["selected_offering_ids"] == [111111]
    assert "Example Department" not in result.stdout
    assert "Past Example" not in result.stdout


def test_init_without_active_academic_term_stops_before_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    world.courses = [
        CourseRef(333333, "EXAMPLEDEPT", "Example Department", None, True),
        CourseRef(444444, "COURSE404_sec01_1261", "Past Example", "1261", False),
    ]

    result = CliRunner().invoke(cli.app, ["init"], input="y\nn\nn\ny\n")

    assert result.exit_code == 3
    assert world.metadata_calls == []
    assert "run: a2l courses --all-terms" in result.output
    assert result.output.count("run:") == 1


def test_init_maps_globally_detected_agents_into_a_fresh_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    world.root.joinpath(".agents").rmdir()
    world.root.joinpath(".claude").rmdir()
    installed: list[tuple[Path, tuple[str, ...]]] = []
    monkeypatch.setattr(
        cli.skills_module,
        "detect_installed_agents",
        lambda: ("Claude Code", "Codex"),
        raising=False,
    )

    def install_detected(
        *, project: Path, agents: tuple[str, ...], confirm: object, **_kwargs: object
    ) -> object:
        installed.append((project, agents))
        assert callable(confirm)
        accepted = confirm("fresh project skill preview\n")
        return SimpleNamespace(cancelled=not accepted)

    monkeypatch.setattr(
        cli.skills_module,
        "install_detected_project",
        install_detected,
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert installed == [(world.root, ("Claude Code", "Codex"))]
    assert "Found Claude Code and Codex" in result.stdout


def test_init_declining_profile_uses_paste_without_calling_browser_auth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["init"], input="y\nn\nn\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert world.auth_backends == ["paste"]
    assert "hidden-TTY" in result.stdout


def test_init_failure_emits_one_safe_next_command_without_raw_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_world(monkeypatch, tmp_path)

    def fail_auth(_school: object, *, backend: str) -> object:
        del backend
        raise RuntimeError("/private/student/session-secret")

    monkeypatch.setattr(cli, "authenticate", fail_auth)
    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\n")

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "/private/student/session-secret" not in result.output
    assert result.output.count("run:") == 1
    assert "run: a2l auth" in result.output


def test_init_uses_agent2learn_2_for_an_occupied_default_without_touching_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    sentinel = root / "student-file.txt"
    sentinel.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True, raising=False)
    monkeypatch.setattr(cli, "authenticate", lambda _school, *, backend: object())
    monkeypatch.setattr(cli, "Client", lambda _school, _session: SimpleNamespace())
    courses = [CourseRef(111111, "COURSE101_sec01_1265", "Current", "1265", True)]
    monkeypatch.setattr(cli, "calibrate", lambda _client: _calibration(courses))
    monkeypatch.setattr(cli, "ingest_metadata", lambda *args, **kwargs: MetadataReport((), 0, 0))
    monkeypatch.setattr(
        cli.pipeline_module,
        "run_pipeline",
        lambda *args, **kwargs: SimpleNamespace(files=FileReport(), exit_code=0, errors=()),
    )
    monkeypatch.setattr(cli.skills_module, "detect_destinations", lambda **kwargs: ())
    monkeypatch.setattr(cli.skills_module, "detect_installed_agents", lambda: ())

    result = CliRunner().invoke(cli.app, ["init"], input="y\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert root.joinpath(".a2l").is_dir() is False
    assert root.with_name("vault-2").joinpath(".a2l").is_dir()
    assert root.with_name("vault-2").joinpath(".agents").is_dir() is False
    assert root.with_name("vault-2").joinpath(".claude").is_dir() is False
    assert "vault-2" in result.stdout


def test_init_preserves_an_existing_obsidian_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    obsidian = world.root / ".obsidian"
    obsidian.mkdir()
    sentinel = obsidian / "sentinel.json"
    sentinel.write_text('{"user": "owned"}\n', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert sentinel.read_text(encoding="utf-8") == '{"user": "owned"}\n'
    assert list(obsidian.iterdir()) == [sentinel]


def test_init_is_idempotent_and_resumes_when_a_new_term_appears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)

    first = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")
    assert first.exit_code == 0, first.output
    first_metadata_calls = list(world.metadata_calls)
    first_auth_backends = list(world.auth_backends)

    second = CliRunner().invoke(cli.app, ["init"], input="")
    assert second.exit_code == 0, second.output
    assert world.metadata_calls == first_metadata_calls
    assert world.auth_backends == first_auth_backends
    assert "saved local session" in second.stdout
    assert "files already handled (later)" in second.stdout

    world.courses = [CourseRef(555555, "COURSE303_sec01_1266", "New Example", "1266", True)]
    third = CliRunner().invoke(cli.app, ["init"], input="y\ny\nlater\n")

    assert third.exit_code == 0, third.output
    assert world.metadata_calls[-1] == {
        "term": "1266",
        "only": [555555],
        "include_grades": False,
    }
    assert _state(world.root)["term"] == "1266"
    assert _state(world.root)["selected_offering_ids"] == [555555]
    assert "New term detected: 1 courses. Sync?" in third.stdout


def test_init_full_reuses_production_pipeline_with_completed_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_world(monkeypatch, tmp_path)
    calls: list[dict[str, object]] = []
    snapshot_flags: list[object] = []
    metadata_ingest: Callable[..., MetadataReport] = cli.ingest_metadata

    def metadata_without_snapshot(*args: object, **kwargs: object) -> MetadataReport:
        snapshot_flags.append(kwargs.get("create_snapshot"))
        return metadata_ingest(*args, **kwargs)

    monkeypatch.setattr(cli, "ingest_metadata", metadata_without_snapshot)

    def pipeline_run(*_args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            files=FileReport(downloaded=2),
            exit_code=0,
            errors=(),
        )

    monkeypatch.setattr(cli.pipeline_module, "run_pipeline", pipeline_run)

    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nfull\n")

    assert result.exit_code == 0, result.output
    assert snapshot_flags == [False]
    assert len(calls) == 1
    assert isinstance(calls[0]["metadata"], MetadataReport)
    assert calls[0]["scope"] == "all"
    assert calls[0]["download_files"] is True
    assert calls[0]["include_media"] is False


def test_init_later_finalizes_metadata_without_downloading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_world(monkeypatch, tmp_path)
    calls: list[dict[str, object]] = []

    def pipeline_run(*_args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(files=FileReport(), exit_code=0, errors=())

    monkeypatch.setattr(cli.pipeline_module, "run_pipeline", pipeline_run)
    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["download_files"] is False
    assert calls[0]["render_outlines"] is False
    assert isinstance(calls[0]["metadata"], MetadataReport)


def test_init_opt_in_grades_and_full_files_after_estimate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    original_estimator = cli._print_file_estimates

    def recording_estimate(report: Iterable[object]) -> None:
        world.events.append("estimate")
        original_estimator(report)

    monkeypatch.setattr(cli, "_print_file_estimates", recording_estimate)
    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\ny\ny\ny\nfull\n")

    assert result.exit_code == 0, result.output
    assert world.events == [
        "skill_preview",
        "skills",
        "auth",
        "client",
        "discovery",
        "metadata",
        "estimate",
        "files",
    ]
    assert world.metadata_calls == [
        {"term": "1265", "only": [111111, 222222], "include_grades": True}
    ]
    assert world.file_calls == [
        {
            "term": "1265",
            "only": [111111, 222222],
            "scope": "all",
            "include_media": False,
        }
    ]
    assert _state(world.root)["include_grades"] is True
    assert "Files:" in result.stdout


def test_priority_estimate_uses_the_actual_bounded_subset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = _courses()[0]
    topics = [
        _topic_record(
            selected,
            1,
            "Assignment brief.pdf",
            "/content/assignment.pdf",
            120_000_000,
        ),
        _topic_record(
            selected,
            2,
            "Lecture notes.pdf",
            "/content/lecture.pdf",
            100_000_000,
        ),
        _topic_record(
            selected,
            3,
            "Recording.mp4",
            "/content/recording.mp4",
            50_000_000,
        ),
    ]

    cli._print_file_estimates(topics)
    output = capsys.readouterr().out

    assert "full document archive ~210 MB" in output
    assert "priority set ~114 MB" in output
    assert "200 MB budget" in output
    assert "audio/video ~48 MB excluded" in output


def test_deadline_rendering_uses_waterloo_time_across_dst_and_not_machine_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "UTC")

    assert cli._format_deadline("2026-03-08T07:30:00Z", cli.UWaterloo()) == ("Sun Mar 8, 3:30am")
    assert cli._format_deadline("2026-11-01T06:30:00Z", cli.UWaterloo()) == ("Sun Nov 1, 1:30am")
    assert cli._format_deadline("not-a-date", cli.UWaterloo()) == "time unavailable"


def test_upcoming_deadlines_are_not_displaced_by_old_overdue_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 9, 1, 12, tzinfo=UTC))
    rows = [(f"2026-0{month}-01T12:00:00Z", f"Old {month}", "C") for month in range(1, 7)] + [
        ("2026-09-02T12:00:00Z", "Tomorrow", "C"),
        ("2026-09-03T12:00:00Z", "Next", "C"),
    ]

    selected = cli._first_value_deadlines(rows, cli.UWaterloo(), limit=5)

    assert [title for _, title, _ in selected[:2]] == ["Tomorrow", "Next"]


def test_init_detects_new_term_while_previous_term_remains_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    first = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")
    assert first.exit_code == 0, first.output
    world.courses = [
        CourseRef(111111, "COURSE101_sec01_1265", "Spring", "1265", True),
        CourseRef(555555, "COURSE303_sec01_1269", "Fall", "1269", True),
    ]

    second = CliRunner().invoke(cli.app, ["init"], input="y\n\ny\nlater\n")

    assert second.exit_code == 0, second.output
    assert "New term detected: 1 courses. Sync?" in second.stdout
    assert _state(world.root)["term"] == "1269"


def test_declining_overlapping_new_term_keeps_previous_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    first = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\ny\nlater\n")
    assert first.exit_code == 0, first.output
    before = list(world.metadata_calls)
    world.courses = [
        CourseRef(111111, "COURSE101_sec01_1265", "Spring", "1265", True),
        CourseRef(555555, "COURSE303_sec01_1269", "Fall", "1269", True),
    ]

    second = CliRunner().invoke(cli.app, ["init"], input="n\n")

    assert second.exit_code == 0, second.output
    assert "New term detected: 1 courses. Sync?" in second.stdout
    assert _state(world.root)["term"] == "1265"
    assert world.metadata_calls == before

    third = CliRunner().invoke(cli.app, ["init"], input="\n")
    assert third.exit_code == 0, third.output
    assert "New term detected" not in third.stdout
    assert _state(world.root)["term"] == "1265"


def test_init_requires_an_explicit_choice_when_multiple_terms_are_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    world.courses = [
        CourseRef(111111, "COURSE101_sec01_1265", "Spring Example", "1265", True),
        CourseRef(555555, "COURSE303_sec01_1266", "Summer Example", "1266", True),
    ]

    result = CliRunner().invoke(cli.app, ["init"], input="y\ny\nn\ny\n1265\ny\nlater\n")

    assert result.exit_code == 0, result.output
    assert world.metadata_calls == [{"term": "1265", "only": [111111], "include_grades": False}]
    assert "Multiple active academic terms found" in result.stdout
    assert "Choose an active term code" in result.stdout

    second = CliRunner().invoke(cli.app, ["init"], input="\n")

    assert second.exit_code == 0, second.output
    assert world.metadata_calls == [{"term": "1265", "only": [111111], "include_grades": False}]
    assert "New term detected" not in second.stdout


def test_init_refuses_an_existing_vault_with_a_newer_schema_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    Vault.claim(root)
    root.joinpath(".a2l", "VERSION").write_text("99\n", encoding="utf-8")
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True, raising=False)

    result = CliRunner().invoke(cli.app, ["init"], input="y\n")

    assert result.exit_code == 1, result.output
    assert result.output.count("run:") == 1
    assert "run: a2l init" in result.output
    assert root.joinpath(".a2l", "VERSION").read_text(encoding="utf-8") == "99\n"
    assert root.joinpath(".a2l", "init.json").is_file() is False
    assert root.joinpath(".obsidian").is_dir() is False


def test_init_resumed_file_estimate_reads_persisted_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    _metadata_report(world)
    cli._save_init_state(
        world.root,
        {
            "school": "uwaterloo",
            "vault_confirmed": True,
            "skills_status": "installed",
            "grades_configured": True,
            "include_grades": False,
            "profile_consent": True,
            "auth_backend": "auto",
            "authenticated": True,
            "term": "1265",
            "selected_offering_ids": [111111, 222222],
            "metadata_complete": True,
        },
    )

    result = CliRunner().invoke(cli.app, ["init"], input="later\n")

    assert result.exit_code == 0, result.output
    assert world.metadata_calls == []
    assert world.file_calls == []
    assert "full document archive ~24 MB" in result.stdout
    assert "audio/video ~40 MB" in result.stdout
    assert "full document archive 0 B" not in result.stdout


def test_init_does_not_follow_a_claim_race_to_an_unapproved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True, raising=False)
    allow_suffix_values: list[bool] = []

    def claim_elsewhere(path: Path, *, allow_suffix: bool = True) -> Path:
        del path
        allow_suffix_values.append(allow_suffix)
        return root.with_name("vault-2")

    monkeypatch.setattr(cli.Vault, "claim", claim_elsewhere)
    result = CliRunner().invoke(cli.app, ["init"], input="y\n")

    assert result.exit_code == 1, result.output
    assert allow_suffix_values == [False]
    assert result.output.count("run:") == 1
    assert "run: a2l init" in result.output
    assert root.with_name("vault-2").is_dir() is False


def test_exact_vault_claim_refuses_an_occupied_path_without_suffixing(tmp_path: Path) -> None:
    occupied = tmp_path / "vault"
    occupied.mkdir()

    with pytest.raises(A2LError):
        Vault.claim(occupied, allow_suffix=False)

    assert occupied.with_name("vault-2").is_dir() is False


def test_init_reprompts_invalid_course_input_and_prioritizes_stable_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    world.courses = [
        CourseRef(100, "AAA100_sec01_1265", "First", "1265", True),
        CourseRef(1, "ZZZ001_sec01_1265", "Second", "1265", True),
    ]

    result = CliRunner().invoke(
        cli.app,
        ["init"],
        input="y\ny\nn\ny\nn\nnot-a-course\n1\nlater\n",
    )

    assert result.exit_code == 0, result.output
    assert world.metadata_calls == [{"term": "1265", "only": [1], "include_grades": False}]
    assert "Selection did not match a known course" in result.stdout
