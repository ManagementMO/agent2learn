"""Tests for the thin, explicit single-topic fetch command."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agent2learn import cli as cli_module
from agent2learn import config, session
from agent2learn.cli import app
from agent2learn.ingest import FetchReport


def test_fetch_requires_a_saved_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))
    monkeypatch.setattr(session, "load", lambda: None)

    result = CliRunner().invoke(app, ["fetch", "123"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "no saved session" in result.stderr


def test_fetch_reports_unreadable_session_without_echoing_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))

    def unreadable() -> object:
        raise PermissionError("/private/student/session.json")

    monkeypatch.setattr(session, "load", unreadable)

    result = CliRunner().invoke(app, ["fetch", "123"])

    assert result.exit_code == 1
    assert "run: a2l auth" in result.stderr
    assert "/private/student/session.json" not in result.output


def test_auth_check_reports_unreadable_session_without_echoing_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreadable() -> object:
        raise PermissionError("/private/student/session.json")

    monkeypatch.setattr(session, "load", unreadable)

    result = CliRunner().invoke(app, ["auth", "--check"])

    assert result.exit_code == 1
    assert "run: a2l auth" in result.stderr
    assert "/private/student/session.json" not in result.output


def test_fetch_reports_unreadable_config_without_echoing_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreadable() -> object:
        raise PermissionError("/private/student/config.json")

    monkeypatch.setattr(config, "load", unreadable)

    result = CliRunner().invoke(app, ["fetch", "123"])

    assert result.exit_code == 3
    assert "run: a2l init" in result.stderr
    assert "/private/student/config.json" not in result.output


def test_fetch_prints_only_the_verified_citation_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))
    monkeypatch.setattr(session, "load", lambda: object())
    monkeypatch.setattr("agent2learn.cli.Client", lambda school, saved: object())
    calls: list[str] = []

    def fake_fetch(
        client: object, vault: object, school: object, topic: str, **kwargs: object
    ) -> FetchReport:
        del client, vault, school, kwargs
        calls.append(topic)
        return FetchReport(
            source_key="uwaterloo:111111:topic:123",
            availability="markdown_ready",
            source_path="Winter 2026/COURSE101/content/outline.pdf",
            citation_path="Winter 2026/COURSE101/content/outline.md",
            changed=True,
        )

    monkeypatch.setattr("agent2learn.cli.fetch_topic", fake_fetch)

    result = CliRunner().invoke(app, ["fetch", "123"])

    assert result.exit_code == 0
    assert calls == ["123"]
    assert result.stdout == ("verified citation: Winter 2026/COURSE101/content/outline.md\n")


def test_large_fetch_confirmation_uses_the_long_path_disk_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))
    monkeypatch.setattr(session, "load", lambda: object())
    monkeypatch.setattr("agent2learn.cli.Client", lambda school, saved: object())
    monkeypatch.setattr(cli_module, "_interactive_terminal", lambda: True)
    extended = tmp_path / "extended-vault"
    disk_paths: list[object] = []
    monkeypatch.setattr(cli_module.paths, "long_path", lambda path: extended)

    def record_disk_usage(path: Path) -> SimpleNamespace:
        disk_paths.append(path)
        return SimpleNamespace(free=10_000)

    monkeypatch.setattr(cli_module.shutil, "disk_usage", record_disk_usage)
    monkeypatch.setattr(cli_module.typer, "confirm", lambda *args, **kwargs: True)

    def fake_fetch(
        client: object, vault: object, school: object, topic: str, **kwargs: object
    ) -> FetchReport:
        del client, vault, school, topic
        confirm = kwargs["confirm"]
        assert callable(confirm)
        assert confirm(1) is True
        return FetchReport(
            source_key="uwaterloo:111111:topic:123",
            availability="metadata_only",
            source_path=None,
            citation_path=None,
            changed=False,
        )

    monkeypatch.setattr("agent2learn.cli.fetch_topic", fake_fetch)

    result = CliRunner().invoke(app, ["fetch", "123", "--allow-large"])

    assert result.exit_code == 1
    assert disk_paths == [extended]
