"""A public init invocation must leave a cited vault, not merely call its phases."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from golden_support import (
    CANONICAL_ORIGIN,
    GoldenSession,
    _CanonicalOriginAdapter,
    frozen_clock,  # noqa: F401
)
from typer.testing import CliRunner

from agent2learn import cli, config
from agent2learn.api import Client as RealClient
from agent2learn.schools._base import CONSERVATIVE_TOPIC_EXCLUSION_POLICY


class _SyntheticWaterloo:
    id = "uwaterloo"
    name = "Synthetic Waterloo"
    base_url = CANONICAL_ORIGIN
    timezone = "UTC"
    auth_hint = "synthetic"

    def term_from_offering(self, code: str) -> str | None:
        tail = code.rsplit("_", 1)[-1]
        return tail if tail.isdigit() else None

    def term_label(self, term: str) -> str:
        return f"Term {term}"

    def auth_hosts(self) -> list[str]:
        return []

    def outline_hosts(self) -> list[str]:
        return []

    def topic_exclusion_policy(self) -> Any:
        return CONSERVATIVE_TOPIC_EXCLUSION_POLICY


def _isolated_dirs(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        user_config_path=root / "config",
        user_state_path=root / "state",
        user_data_path=root / "data",
        user_log_path=root / "logs",
    )


def test_full_init_through_public_cli_produces_verified_twins_and_audit(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: Any,
    frozen_clock: object,  # noqa: F811
) -> None:
    root = tmp_path / "vault"
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli, "UWaterloo", _SyntheticWaterloo)
    monkeypatch.setattr(
        cli,
        "authenticate",
        lambda _school, *, backend: GoldenSession(CANONICAL_ORIGIN),
    )
    monkeypatch.setattr(cli.skills_module, "detect_installed_agents", lambda: ())
    monkeypatch.setattr(cli.skills_module, "detect_destinations", lambda **_kwargs: ())

    def client_factory(school: object, session: object) -> RealClient:
        client = RealClient(school, session, workers=1)  # type: ignore[arg-type]
        client._transport.mount(
            CANONICAL_ORIGIN,
            _CanonicalOriginAdapter(CANONICAL_ORIGIN, synthetic_api.base_url),  # type: ignore[attr-defined]
        )
        return client

    monkeypatch.setattr(cli, "Client", client_factory)
    monkeypatch.setattr("agent2learn.api.JITTER_MAX", 0.0)

    result = CliRunner().invoke(
        cli.app,
        ["init", "--vault", str(root)],
        input="y\nn\nn\ny\ny\nfull\n",
    )

    assert result.exit_code == 0, result.output
    assert (root / ".a2l" / "AUDIT.md").is_file()
    names = {path.name for path in root.rglob("*") if path.is_file()}
    for expected in (
        "Lecture Slides.pdf",
        "Lecture Slides.md",
        "Notebook.ipynb",
        "Notebook.md",
        "R Notes.Rmd",
        "R Notes.md",
        "Site Archive.zip",
        "Site Archive.md",
        "Publisher eText.url.txt",
        "External Tool.url.txt",
    ):
        assert expected in names

    maps = sorted(root.rglob("content_map.json"))
    assert maps
    rows = [row for path in maps for row in json.loads(path.read_text(encoding="utf-8"))["topics"]]
    ready = [row for row in rows if row.get("availability") == "markdown_ready"]
    assert ready
    for row in ready:
        twin = root / Path(*str(row["path"]).split("/"))
        assert twin.is_file() and twin.stat().st_size > 0
    assert not [path for path in root.rglob("*") if path.suffix.casefold() in {".mp3", ".mp4"}]
