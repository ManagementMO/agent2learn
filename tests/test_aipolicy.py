# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

from agent2learn.aipolicy import surface_ai_policy
from agent2learn.snapshot import write_snapshot
from agent2learn.vault import Vault


def test_ai_policy_found_records_verbatim_clause_and_line_citation(tmp_path: Path) -> None:
    """Dropping the original paragraph or its line address loses the informational evidence."""
    course = tmp_path / "Term" / "COURSE_1"
    outline = course / "content" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# Outline\n\n## Generative AI\n\nChatGPT may not be used on assessments.\n",
        encoding="utf-8",
        newline="\n",
    )

    record = surface_ai_policy(course, outline)

    assert record == {
        "schema_version": 1,
        "status": "found",
        "text": "## Generative AI\n\nChatGPT may not be used on assessments.",
        "source": "content/outline.md:3",
    }
    assert (
        json.loads((course / "_meta" / "ai_policy.json").read_text(encoding="utf-8"))["status"]
        == "found"
    )


def test_ai_policy_distinguishes_scanned_no_match_from_unavailable_outline(tmp_path: Path) -> None:
    """Treating an unavailable outline as permission is a policy-safety bug."""
    course = tmp_path / "Term" / "COURSE_1"
    course.mkdir(parents=True)
    outline = course / "outline.md"
    outline.write_text("# Outline\n\nNo policy language here.\n", encoding="utf-8", newline="\n")

    assert surface_ai_policy(course, outline)["status"] == "not_found_in_scanned_outline"
    assert surface_ai_policy(course, None)["status"] == "outline_unavailable"


def test_snapshot_is_atomic_and_omits_stale_grades_when_disabled(tmp_path: Path) -> None:
    """Retaining a prior grade when collection is disabled leaks an opted-out category."""
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    meta = course / "_meta"
    meta.mkdir(parents=True)
    (meta / "content_map.json").write_text(
        '{"schema_version": 1, "topics": [{"topic_id": 3}]}', encoding="utf-8", newline="\n"
    )
    (meta / "assignments.json").write_text(
        '[{"id": 1, "due_date": "2026-09-01T00:00:00Z"}]', encoding="utf-8", newline="\n"
    )
    (meta / "news.json").write_text('[{"id": 2}]', encoding="utf-8", newline="\n")
    (meta / "my_grades.json").write_text(
        '[{"id": "grade", "displayed": "100%"}]', encoding="utf-8", newline="\n"
    )

    included = json.loads(
        write_snapshot(
            vault, [course], include_grades=True, timestamp="2026-08-25T00:00:00Z"
        ).read_text(encoding="utf-8")
    )
    excluded = json.loads(
        write_snapshot(
            vault, [course], include_grades=False, timestamp="2026-08-26T00:00:00Z"
        ).read_text(encoding="utf-8")
    )

    assert included["courses"][0]["grades"] == [{"id": "grade", "displayed": "100%"}]
    assert "grades" not in excluded["courses"][0]
