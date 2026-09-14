"""CLI integration checks for Task 17's local-only commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent2learn import config, metadata_coverage
from agent2learn.cli import app
from agent2learn.vault import Vault


def _configured_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = Vault.claim(tmp_path)
    course = root / "Spring 2026" / "COURSE101_1265"
    metadata = course / "_meta"
    metadata.mkdir(parents=True)
    (metadata / "content_map.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topics": [
                    {
                        "source_key": "uwaterloo:101:topic:1",
                        "source_id": "1",
                        "topic_id": 1,
                        "course_code": "COURSE101",
                        "course_name": "Materials",
                        "term": "1265",
                        "title": "Phase diagrams",
                        "kind": "File",
                        "path": "Spring 2026/COURSE101_1265/content/phase.md",
                        "source_path": "Spring 2026/COURSE101_1265/content/phase.pdf",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        config,
        "load",
        lambda: config.Config(vault=root, include_grades=False),
    )
    return root, course


@pytest.mark.parametrize("output_file", [False, True])
@pytest.mark.parametrize("status", ["complete", "unknown", "unavailable"])
def test_calendar_cli_warns_on_partial_coverage_without_corrupting_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_file: bool,
    status: metadata_coverage.CoverageStatus,
) -> None:
    root, course = _configured_vault(tmp_path, monkeypatch)
    (course / "_meta" / "assignments.json").write_text(
        '[{"id": 1, "title": "Essay", "due_date": "2026-09-15"}]\n', encoding="utf-8"
    )
    (course / "_meta" / "quizzes.json").write_text("[]\n", encoding="utf-8")
    metadata_coverage.write_quiz_coverage(
        course,
        metadata_coverage.QuizCoverage(status, 403 if status == "unavailable" else None),
        root=root,
    )
    before = {path.name: path.read_bytes() for path in (course / "_meta").iterdir()}
    destination = root / "deadlines.ics"
    args = ["calendar", "--output", str(destination)] if output_file else ["calendar"]

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert ("Warning: Quiz coverage" in result.stderr) == (status != "complete")
    if status != "complete":
        assert "not confirmed current" in result.stderr
    assert str(root) not in result.stderr
    assert "COURSE101" not in result.stderr
    exported = destination.read_text(encoding="utf-8") if output_file else result.stdout
    assert exported.startswith("BEGIN:VCALENDAR\n")
    assert exported.endswith("END:VCALENDAR\n")
    assert exported.count("BEGIN:VEVENT") == 1
    assert "Warning:" not in exported
    assert {path.name: path.read_bytes() for path in (course / "_meta").iterdir()} == before


def test_where_and_open_are_local_and_redaction_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _course = _configured_vault(tmp_path, monkeypatch)
    opened: list[Path] = []
    monkeypatch.setattr("agent2learn.cli.paths.reveal", opened.append)

    where_result = CliRunner().invoke(app, ["where", "phase"])
    open_result = CliRunner().invoke(app, ["open", "COURSE101"])

    assert where_result.exit_code == 0
    assert "Spring 2026/COURSE101_1265" in where_result.stdout
    assert "twin=Spring 2026/COURSE101_1265/content/phase.md" in where_result.stdout
    assert "source=Spring 2026/COURSE101_1265/content/phase.pdf" in where_result.stdout
    assert str(root) not in where_result.stdout
    assert open_result.exit_code == 0
    assert opened == [root / "Spring 2026" / "COURSE101_1265"]


def test_privacy_purge_cli_previews_but_non_tty_cannot_mutate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, course = _configured_vault(tmp_path, monkeypatch)
    grade_path = course / "_meta" / "my_grades.json"
    grade_path.write_text('[{"id": "g1", "displayed": "97%"}]\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["privacy", "purge", "grades"])

    assert result.exit_code == 1
    assert "Privacy purge preview" in result.stdout
    assert "97%" not in result.output
    assert "interactive terminal" in result.stderr
    assert grade_path.exists()
    assert str(root) not in result.output


def test_privacy_status_does_not_echo_sensitive_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, course = _configured_vault(tmp_path, monkeypatch)
    (course / "_meta" / "my_grades.json").write_text(
        '[{"id": "g1", "displayed": "97%"}]\n', encoding="utf-8"
    )

    result = CliRunner().invoke(app, ["privacy", "status"])

    assert result.exit_code == 0
    assert "grades: disabled; retained locally" in result.stdout
    assert "97%" not in result.output
    assert "COURSE101" not in result.output
