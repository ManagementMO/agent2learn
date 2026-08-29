"""Public CLI contracts for the production ``a2l sync`` command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import strip_ansi
from typer.testing import CliRunner

from agent2learn import cli, config
from agent2learn.calibrate import Calibration, CourseRef
from agent2learn.errors import SessionExpired
from agent2learn.vault import Vault


def _configured_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    include_grades: bool = False,
    include_discussions: bool = False,
    file_scope: str = "priority",
    profile_consent: bool | None = None,
) -> tuple[Path, list[dict[str, object]]]:
    root = tmp_path / "vault"
    Vault.claim(root)
    init_state: dict[str, object] = {
        "schema_version": 1,
        "term": "1265",
        "selected_offering_ids": [111111],
        "file_scope": file_scope,
    }
    if profile_consent is not None:
        init_state["profile_consent"] = profile_consent
    root.joinpath(".a2l", "init.json").write_text(
        json.dumps(init_state) + "\n",
        encoding="utf-8",
    )
    cfg = config.Config(
        vault=root,
        include_grades=include_grades,
        include_discussions=include_discussions,
    )
    monkeypatch.setattr(cli.config, "load", lambda: cfg)
    monkeypatch.setattr(cli.session_store, "load", lambda: object())

    client = SimpleNamespace()
    monkeypatch.setattr(cli, "Client", lambda _school, _session: client)
    calibration = Calibration(
        lp="1.62",
        le="1.96",
        download_template=None,
        courses=[CourseRef(111111, "COURSE101_sec01_1265", "Course 101", "1265", True)],
    )
    monkeypatch.setattr(cli, "calibrate", lambda _client: calibration)

    calls: list[dict[str, object]] = []

    def fake_run_pipeline(*_args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(cli.pipeline_module, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(cli.pipeline_module, "render_report", lambda _report: "sync complete\n")
    return root, calls


def test_top_level_help_exposes_sync() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])
    output = strip_ansi(result.output)

    assert result.exit_code == 0
    assert " sync " in output


def test_sync_help_exposes_only_public_scope_and_media_options() -> None:
    result = CliRunner().invoke(cli.app, ["sync", "--help"])
    output = strip_ansi(result.output)

    assert result.exit_code == 0, output
    assert "--all" in output
    assert "--priority" in output
    assert "--include-media" in output
    assert "--include-grades" not in output
    assert "--include-discussions" not in output
    assert "saved configuration" in output.casefold()


def test_sync_rejects_all_and_priority_together() -> None:
    result = CliRunner().invoke(cli.app, ["sync", "--all", "--priority"])
    output = strip_ansi(result.output)

    assert result.exit_code == 2
    assert "--all and --priority are mutually exclusive" in output


def test_sync_uses_persisted_scope_and_configured_sensitive_categories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _root, calls = _configured_sync(
        monkeypatch,
        tmp_path,
        include_grades=True,
        include_discussions=True,
        file_scope="priority",
        profile_consent=False,
    )

    result = CliRunner().invoke(cli.app, ["sync", "--include-media"])

    assert result.exit_code == 0, result.output
    assert result.output == "sync complete\n"
    assert calls == [
        {
            "scope": "priority",
            "include_media": True,
            "include_grades": True,
            "include_discussions": True,
            "ocr_words_per_page": 80,
            "term": "1265",
            "only": (111111,),
            "metadata_observer": cli._print_sync_metadata,
            "profile_consent": False,
        }
    ]


def test_sync_preserves_expired_session_exit_and_one_auth_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configured_sync(monkeypatch, tmp_path)

    def expired(*_args: object, **_kwargs: object) -> object:
        raise SessionExpired("untrusted transport detail")

    monkeypatch.setattr(cli.pipeline_module, "run_pipeline", expired)

    result = CliRunner().invoke(cli.app, ["sync"])

    assert result.exit_code == 75
    assert result.output == "session expired · run: a2l auth\n"
    assert result.output.count("a2l auth") == 1


def test_sync_normalizes_a_typed_temporary_failure_to_one_auth_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configured_sync(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.pipeline_module,
        "run_pipeline",
        lambda *_args, **_kwargs: SimpleNamespace(exit_code=75),
    )

    result = CliRunner().invoke(cli.app, ["sync"])

    assert result.exit_code == 75
    assert result.output == "session expired · run: a2l auth\n"
    assert result.output.count("a2l auth") == 1


def test_sync_fails_closed_on_an_invalid_saved_course_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, calls = _configured_sync(monkeypatch, tmp_path)
    root.joinpath(".a2l", "init.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "term": "1265",
                "selected_offering_ids": [True],
                "file_scope": "priority",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "calibrate",
        lambda _client: (_ for _ in ()).throw(
            AssertionError("invalid local scope must stop before network calibration")
        ),
    )

    result = CliRunner().invoke(cli.app, ["sync"])

    assert result.exit_code == 1
    assert result.output == "sync failed (ValueError) · run: a2l doctor\n"
    assert calls == []
