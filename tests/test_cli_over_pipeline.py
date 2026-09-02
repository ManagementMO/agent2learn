"""Drive the real CLI over what the production pipeline actually writes.

Unit fixtures are built by hand to match the implementer's assumptions, so they cannot catch the
assumption being wrong. This module runs the full production pipeline against the synthetic API
and then exercises the user-facing commands over that vault. It exists because doing exactly this
by hand on 2026-09-01 found three defects a 912-test suite had missed: assignment folders are
named ``{title} {dropbox id}`` and grounding could not resolve a typed title, and two empty-result
paths blamed ``a2l sync`` when sync would have changed nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import strip_ansi
from golden_support import run_full_pipeline  # noqa: F401
from typer.testing import CliRunner

from agent2learn import config, paths
from agent2learn.cli import app
from agent2learn.index import read_content_map


@pytest.fixture
def pipeline_vault(
    tmp_path: Path, synthetic_api: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, str]:
    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)
    root = vault.root
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    monkeypatch.setattr(paths, "reveal", lambda _path: None)
    course = sorted(
        path.parent.parent
        for path in root.rglob("_meta/content_map.json")
        if ".a2l" not in path.parts
    )[0]
    topics = read_content_map(course)["topics"]
    assert isinstance(topics, list) and isinstance(topics[0], dict)
    code = str(topics[0]["course_code"])
    return root, course, code


def _run(*argv: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(argv))
    return result.exit_code, strip_ansi(result.output)


def test_pipeline_names_assignment_folders_with_their_dropbox_id(
    pipeline_vault: tuple[Path, Path, str],
) -> None:
    """The contract the grounding resolver must honour; if this changes, ground.py must too."""
    _root, course, _code = pipeline_vault
    rows = json.loads((course / "_meta" / "assignments.json").read_text(encoding="utf-8"))
    folders = {path.name for path in (course / "assignments").iterdir() if path.is_dir()}

    assert folders, "the pipeline produced no assignment folders"
    for row in rows:
        assert f"{row['title']} {row['id']}" in folders, (row, folders)


def test_ground_resolves_the_title_a_student_types(
    pipeline_vault: tuple[Path, Path, str],
) -> None:
    root, course, code = pipeline_vault

    for selector in ("Problem Set 1", "problem set 1", "700001", "Problem Set 1 700001"):
        exit_code, output = _run("ground", code, selector)
        assert exit_code == 0, (selector, output)
        assert "assignments/Problem Set 1 700001/GROUNDING.md" in output, selector

    pack = course / "assignments" / "Problem Set 1 700001" / "GROUNDING.md"
    assert pack.is_file()
    assert pack.read_text(encoding="utf-8").splitlines()[0].endswith("· Problem Set 1")


def test_an_assignment_nothing_matches_does_not_blame_sync(
    pipeline_vault: tuple[Path, Path, str],
) -> None:
    """Ten verified twins exist; 'Team Report' simply shares no term with any of them."""
    _root, course, code = pipeline_vault

    exit_code, output = _run("ground", code, "Team Report")
    assert exit_code != 0
    assert "a2l sync" not in output
    assert "Team Report" in output

    draft = course / "assignments" / "Team Report 700003" / "DRAFT.md"
    draft.write_text("We use binary variables in this model.\n", encoding="utf-8")
    exit_code, output = _run("check", str(draft), "--course", code)
    assert exit_code != 0
    assert "a2l sync" not in output
    assert "Team Report" in output
    assert "whole course" in output


def test_scoped_check_over_real_output_cites_and_names_the_title(
    pipeline_vault: tuple[Path, Path, str],
) -> None:
    _root, course, code = pipeline_vault
    twin = sorted(course.rglob("content/**/Lecture Slides.md"))[0]
    draft = course / "assignments" / "Problem Set 1 700001" / "DRAFT.md"
    draft.write_text(twin.read_text(encoding="utf-8")[:300] + "\n", encoding="utf-8")

    exit_code, output = _run("check", str(draft), "--course", code)

    assert exit_code == 0, output
    assert output.splitlines()[0].startswith("Experimental lexical evidence scan")
    assert f"{code} · Problem Set 1 ·" in output
    assert "Problem Set 1 700001 ·" not in output  # the title, not the folder name


def test_the_read_only_surface_works_over_real_output(
    pipeline_vault: tuple[Path, Path, str], tmp_path: Path
) -> None:
    _root, _course, code = pipeline_vault

    read_only: tuple[tuple[str, ...], ...] = (
        ("courses",),
        ("today",),
        ("diff",),
        ("where", "lecture"),
        ("open", code),
        ("privacy", "status"),
        ("calendar", "-o", str(tmp_path / "out.ics")),
    )
    for argv in read_only:
        exit_code, output = _run(*argv)
        assert exit_code == 0, (argv, output)
    assert (tmp_path / "out.ics").stat().st_size > 0

    # Uploads stay disabled in this build, and the refusal must not send anyone to sign in.
    refusals: tuple[tuple[str, ...], ...] = (
        ("enable-submit",),
        ("submit", code, "Problem Set 1", str(tmp_path / "x.pdf")),
    )
    for argv in refusals:
        exit_code, output = _run(*argv)
        assert exit_code != 0, argv
        assert "disabled in this build" in output, argv
        assert "a2l auth" not in output, argv
