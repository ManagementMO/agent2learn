"""End-to-end onboarding orchestration tests for ``a2l init``.

The command is exercised through Typer, while authentication, calibration, and the expensive
ingest phases are replaced with small synthetic collaborators.  This keeps the tests offline and
proves the CLI's ordering and persistence contract rather than duplicating browser or HTTP tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agent2learn import cli, config
from agent2learn.calibrate import Calibration, CourseRef
from agent2learn.ingest import FileReport, MetadataReport
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
    return MetadataReport(courses=(), topic_count=7, deadline_count=8)


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

    def fake_client(_school: object, _session: object) -> object:
        world.events.append("client")
        return SimpleNamespace(courses=world.courses)

    def fake_calibrate(client: object) -> Calibration:
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
        only: object = None,
        include_grades: bool = False,
    ) -> MetadataReport:
        del client, vault, school
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
        only: object = None,
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
    monkeypatch.setattr(cli, "ingest_files", fake_files)
    monkeypatch.setattr(
        cli.skills_module,
        "detect_destinations",
        lambda **kwargs: (
            world.events.append("skill_preview")
            or (
                Destination(
                    path=kwargs["project"] / ".agents" / "skills",
                    agents=("Claude Code", "Codex"),
                ),
            )
        ),
    )
    monkeypatch.setattr(cli.skills_module, "install", fake_install)
    monkeypatch.setattr(cli.session_store, "load", lambda: fake_session)
    return world


def _state(root: Path) -> dict[str, object]:
    return json.loads(root.joinpath(".a2l", "init.json").read_text(encoding="utf-8"))


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
    assert "7 topics" in result.stdout
    assert "8 deadlines" in result.stdout
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
    monkeypatch.setattr(cli, "ingest_files", lambda *args, **kwargs: FileReport())
    monkeypatch.setattr(cli.skills_module, "detect_destinations", lambda **kwargs: ())

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


def test_init_opt_in_grades_and_full_files_after_estimate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = _prepare_world(monkeypatch, tmp_path)
    original_estimator = cli._print_file_estimates

    def recording_estimate(report: MetadataReport | None) -> None:
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
