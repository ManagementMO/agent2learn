"""Tests for the thin, explicit single-topic fetch command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent2learn import config, session
from agent2learn.cli import app
from agent2learn.ingest import FetchReport


def test_fetch_requires_a_saved_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))
    monkeypatch.setattr(session, "load", lambda: None)

    result = CliRunner().invoke(app, ["fetch", "123"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "no saved session" in result.stderr


def test_fetch_prints_only_the_verified_citation_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=tmp_path))
    monkeypatch.setattr(session, "load", lambda: object())
    monkeypatch.setattr("agent2learn.cli.Client", lambda school, saved: object())
    calls: list[str] = []

    def fake_fetch(client, vault, school, topic, **kwargs) -> FetchReport:
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
