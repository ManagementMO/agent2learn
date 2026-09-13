"""A public init invocation must leave a cited vault, not merely call its phases."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from conftest import COURSE_A_OU, LE, SyntheticAPI
from golden_support import (
    CANONICAL_ORIGIN,
    FROZEN_NOW,
    _CanonicalOriginAdapter,
    frozen_clock,  # noqa: F401
)
from typer.testing import CliRunner

from agent2learn import cli, config
from agent2learn.api import Client as RealClient
from agent2learn.schools._base import CONSERVATIVE_TOPIC_EXCLUSION_POLICY
from agent2learn.session import Session


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


@pytest.mark.parametrize("quiz_forbidden", [False, True])
def test_full_init_through_public_cli_produces_verified_twins_and_audit(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: Any,
    frozen_clock: object,  # noqa: F811
    quiz_forbidden: bool,
) -> None:
    root = tmp_path / "vault"
    if quiz_forbidden:
        cast(SyntheticAPI, synthetic_api).server.expect_oneshot_request(
            f"/d2l/api/le/{LE}/{COURSE_A_OU}/quizzes/"
        ).respond_with_json(
            {
                "type": "http://docs.valence.desire2learn.com/res/apiprop.html#not-authorized",
                "title": "Not Authorized",
                "status": 403,
                "detail": (
                    f"Not authorized for [ orgUnitId: {COURSE_A_OU}, "
                    "securityVariableName: Quizzing.SeeQuizzing ]"
                ),
            },
            status=403,
            content_type="application/problem+json; charset=UTF-8",
        )
    monkeypatch.setattr(config, "DIRS", _isolated_dirs(tmp_path))
    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli, "UWaterloo", _SyntheticWaterloo)
    monkeypatch.setattr(
        cli,
        "authenticate",
        lambda _school, *, backend: Session(CANONICAL_ORIGIN, (), None, FROZEN_NOW, None),
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
    if quiz_forbidden:
        before_file_choice = result.output.split("Files:", 1)[0]
        assert "Quizzing.SeeQuizzing" in before_file_choice
        assert "403" in before_file_choice
        assert "0 quizzes" not in before_file_choice
        state = json.loads((root / ".a2l" / "init.json").read_text(encoding="utf-8"))
        assert state["metadata_complete"] is True and state["file_complete"] is True
        assert "run: a2l init" not in result.output
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
    if quiz_forbidden:
        resumed = CliRunner().invoke(cli.app, ["init", "--vault", str(root)])
        assert resumed.exit_code == 0, resumed.output
        assert "Quizzing.SeeQuizzing" in resumed.output
        assert "403" in resumed.output
        assert "No upcoming deadlines recorded" not in resumed.output
