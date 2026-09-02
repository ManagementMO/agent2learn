"""Drive the real CLI over what the production pipeline actually writes.

Unit fixtures are built by hand to match the implementer's assumptions, so they cannot catch the
assumption being wrong. This module runs the full production pipeline against the synthetic API
and then exercises the user-facing commands over that vault. It exists because doing exactly this
by hand on 2026-09-01 found three defects a 912-test suite had missed: assignment folders are
named ``{title} {dropbox id}`` and grounding could not resolve a typed title, and two empty-result
paths blamed ``a2l sync`` when sync would have changed nothing.

Everything runs inside ONE test on purpose. A full pipeline run costs about a minute on the
Windows runners, which were already near their 20-minute job budget; five function-scoped runs of
it pushed all four Windows matrix jobs into the timeout on the first attempt. Each block below is
labelled so a failure still names what broke.
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


def _run(*argv: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(argv))
    return result.exit_code, strip_ansi(result.output)


def test_the_cli_works_over_real_pipeline_output(
    tmp_path: Path, synthetic_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    # --- The folder-naming contract the grounding resolver honours. If this changes, ground.py
    # must change with it.
    rows = json.loads((course / "_meta" / "assignments.json").read_text(encoding="utf-8"))
    folders = {path.name for path in (course / "assignments").iterdir() if path.is_dir()}
    assert folders, "the pipeline produced no assignment folders"
    for row in rows:
        assert f"{row['title']} {row['id']}" in folders, ("folder naming", row, folders)

    # --- ground resolves the title a student types, plus the id and folder forms.
    for selector in ("Problem Set 1", "problem set 1", "700001", "Problem Set 1 700001"):
        exit_code, output = _run("ground", code, selector)
        assert exit_code == 0, ("ground", selector, output)
        assert "assignments/Problem Set 1 700001/GROUNDING.md" in output, ("ground", selector)
    pack = course / "assignments" / "Problem Set 1 700001" / "GROUNDING.md"
    assert pack.is_file()
    assert pack.read_text(encoding="utf-8").splitlines()[0].endswith("· Problem Set 1")

    # --- An assignment nothing matches must not blame sync: ten verified twins exist and
    # 'Team Report' simply shares no term with any of them.
    exit_code, output = _run("ground", code, "Team Report")
    assert exit_code != 0, ("ground empty", output)
    assert "a2l sync" not in output, ("ground empty", output)
    assert "Team Report" in output, ("ground empty", output)

    draft = course / "assignments" / "Team Report 700003" / "DRAFT.md"
    draft.write_text("We use binary variables in this model.\n", encoding="utf-8")
    exit_code, output = _run("check", str(draft), "--course", code)
    assert exit_code != 0, ("check empty scope", output)
    assert "a2l sync" not in output, ("check empty scope", output)
    assert "Team Report" in output and "whole course" in output, ("check empty scope", output)

    # --- A scoped check with matching material cites it and names the assignment TITLE, not the
    # raw folder name.
    twin = sorted(course.rglob("content/**/Lecture Slides.md"))[0]
    draft = course / "assignments" / "Problem Set 1 700001" / "DRAFT.md"
    draft.write_text(twin.read_text(encoding="utf-8")[:300] + "\n", encoding="utf-8")
    exit_code, output = _run("check", str(draft), "--course", code)
    assert exit_code == 0, ("check scoped", output)
    assert output.splitlines()[0].startswith("Experimental lexical evidence scan")
    assert f"{code} · Problem Set 1 ·" in output, ("check scoped header", output)
    assert "Problem Set 1 700001 ·" not in output, ("check scoped header", output)

    # --- The read-only surface.
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

    # --- Uploads stay disabled in this build, and the refusal never sends anyone to sign in.
    refusals: tuple[tuple[str, ...], ...] = (
        ("enable-submit",),
        ("submit", code, "Problem Set 1", str(tmp_path / "x.pdf")),
    )
    for argv in refusals:
        exit_code, output = _run(*argv)
        assert exit_code != 0, argv
        assert "disabled in this build" in output, (argv, output)
        assert "a2l auth" not in output, (argv, output)
