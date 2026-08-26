# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent2learn import snapshot as snapshot_module
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


def test_ai_policy_keeps_the_complete_matching_markdown_paragraph(tmp_path: Path) -> None:
    course = tmp_path / "Term" / "COURSE_1"
    course.mkdir(parents=True)
    outline = course / "outline.md"
    outline.write_text(
        "# Outline\n\n"
        "This opening sentence explains the rule before ChatGPT is mentioned.\n"
        "The second sentence remains part of the same paragraph.\n\n"
        "This unrelated paragraph must not be captured.\n",
        encoding="utf-8",
        newline="\n",
    )

    record = surface_ai_policy(course, outline)

    assert record["text"] == (
        "This opening sentence explains the rule before ChatGPT is mentioned.\n"
        "The second sentence remains part of the same paragraph."
    )
    assert record["source"] == "outline.md:3"


def test_ai_policy_index_block_is_idempotent_for_multiple_outlines(tmp_path: Path) -> None:
    course = tmp_path / "Term" / "COURSE_1"
    course.mkdir(parents=True)
    (course / "INDEX.md").write_text("# COURSE\n\n## Coverage\n", encoding="utf-8", newline="\n")
    first = course / "outline-a.md"
    second = course / "outline-b.md"
    first.write_text("# A\n\nNo policy here.\n", encoding="utf-8", newline="\n")
    second.write_text("# B\n\n## GenAI\nChatGPT clause.\n", encoding="utf-8", newline="\n")

    from agent2learn.aipolicy import surface_course_ai_policy

    surface_course_ai_policy(course, [first, second])

    index = (course / "INDEX.md").read_text(encoding="utf-8")
    assert index.count("## AI policy") == 1
    assert index.count("- AI policy:") == 1


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
    (meta / "quizzes.json").write_text(
        '[{"id": 4, "due_date": "2026-09-02T00:00:00Z"}]', encoding="utf-8", newline="\n"
    )
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
    assert included["courses"][0]["due_dates"] == [
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
    ]
    assert "grades" not in excluded["courses"][0]


@pytest.mark.parametrize("timestamp", ["../../../escaped", r"..\\..\\escaped"])
def test_snapshot_rejects_a_filename_traversal_timestamp(tmp_path: Path, timestamp: str) -> None:
    vault = Vault(tmp_path)

    with pytest.raises(ValueError, match="timestamp"):
        write_snapshot(vault, [], include_grades=False, timestamp=timestamp)

    assert not (tmp_path / "escaped.json").exists()


@pytest.mark.parametrize("metadata", ["[]", '"text"', "1"])
def test_snapshot_rejects_wrong_shaped_content_metadata(tmp_path: Path, metadata: str) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    meta = course / "_meta"
    meta.mkdir(parents=True)
    (meta / "content_map.json").write_text(metadata, encoding="utf-8")

    with pytest.raises(ValueError, match="content_map"):
        write_snapshot(vault, [course], include_grades=False, timestamp="2026-08-25T00:00:00Z")


def test_snapshot_does_not_treat_missing_course_metadata_as_empty(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    (course / "_meta").mkdir(parents=True)

    with pytest.raises(ValueError, match="content_map"):
        write_snapshot(vault, [course], include_grades=False, timestamp="2026-08-25T00:00:00Z")


def test_snapshot_does_not_silently_drop_invalid_metadata_items(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    meta = course / "_meta"
    meta.mkdir(parents=True)
    (meta / "content_map.json").write_text(
        '{"schema_version": 1, "topics": [{"topic_id": 1}, "lost row"]}',
        encoding="utf-8",
    )
    for name in ("assignments.json", "quizzes.json", "news.json"):
        (meta / name).write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="content_map"):
        write_snapshot(vault, [course], include_grades=False, timestamp="2026-08-25T00:00:00Z")


def test_snapshot_does_not_hide_unreadable_metadata_as_empty(tmp_path: Path, monkeypatch) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    meta = course / "_meta"
    meta.mkdir(parents=True)

    def denied(*args: object, **kwargs: object) -> object:
        raise PermissionError("metadata denied")

    monkeypatch.setattr(snapshot_module, "open", denied, raising=False)

    with pytest.raises(ValueError, match="metadata is unreadable"):
        write_snapshot(vault, [course], include_grades=False, timestamp="2026-08-25T00:00:00Z")
    assert not (tmp_path / ".a2l" / "snapshots").exists()


def test_snapshot_rejects_malformed_utf8_metadata_as_unreadable(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    meta = course / "_meta"
    meta.mkdir(parents=True)
    (meta / "content_map.json").write_bytes(b"{\xff")

    with pytest.raises(ValueError, match="metadata is unreadable"):
        write_snapshot(vault, [course], include_grades=False, timestamp="2026-08-25T00:00:00Z")
