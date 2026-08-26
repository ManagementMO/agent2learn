"""The audit must report gaps honestly and never round a partial archive up to complete."""

from __future__ import annotations

import json
from pathlib import Path

from agent2learn import audit
from agent2learn import index as course_index
from agent2learn.vault import Vault


def _course(root: Path, code: str = "COURSE101") -> Path:
    course = root / "2026-Fall" / code
    (course / "_meta").mkdir(parents=True, exist_ok=True)
    return course


def _row(source_id: int, title: str, availability: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_key": f"uwaterloo:111111:topic:{source_id}",
        "source_id": str(source_id),
        "title": title,
        "kind": "File",
        "availability": availability,
        "course_code": "COURSE101",
        "course_name": "Intro to Everything",
    }
    row.update(extra)
    return row


def _vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / ".a2l").mkdir(parents=True, exist_ok=True)
    return Vault(root)


def test_coverage_counts_only_citable_topics(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(
        course,
        [
            _row(1, "Lecture Slides", "markdown_ready"),
            _row(2, "Reading list", "source_only"),
            _row(3, "Notebook", "metadata_only"),
            _row(4, "Site Archive", "unsupported_format"),
        ],
    )

    (result,) = audit.audit_vault(vault)

    assert result.topics == 4
    assert result.citable == 1
    assert result.coverage_percent == 25
    assert result.coverage == {
        "markdown_ready": 1,
        "metadata_only": 1,
        "source_only": 1,
        "unsupported_format": 1,
    }


def test_partial_coverage_never_rounds_up_to_complete(tmp_path: Path) -> None:
    """199 of 200 topics is 99%, not 100%. A student must never read 100% and be wrong."""
    vault = _vault(tmp_path)
    course = _course(vault.root)
    rows = [_row(index, f"Topic {index}", "markdown_ready") for index in range(199)]
    rows.append(_row(999, "Missing", "metadata_only"))
    course_index.write_content_map(course, rows)

    (result,) = audit.audit_vault(vault)

    assert result.citable == 199
    assert result.topics == 200
    assert result.coverage_percent == 99


def test_empty_course_reports_zero_rather_than_dividing_by_zero(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course_index.write_content_map(_course(vault.root), [])

    (result,) = audit.audit_vault(vault)

    assert result.topics == 0
    assert result.coverage_percent == 0


def test_links_are_inventoried_by_kind_and_never_offered_for_fetch(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(
        course,
        [
            _row(1, "Publisher eText", "external_link", kind="Link"),
            _row(2, "External Tool", "external_link", kind="lti"),
            _row(3, "Quicklink", "external_link", kind="Link"),
        ],
    )

    (result,) = audit.audit_vault(vault)
    report = (audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z")).read_text(
        encoding="utf-8"
    )

    assert result.links == {"LTI tool": 1, "external link": 2}
    assert "Open them in LEARN directly" in report
    assert "a2l fetch" not in report


def test_media_is_counted_from_the_stored_path_not_the_title(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(
        course,
        [
            _row(1, "Lecture Recording", "source_only", source_path="2026-Fall/C/a.mp4"),
            _row(2, "Podcast.mp3 discussion", "markdown_ready", source_path="2026-Fall/C/b.pdf"),
        ],
    )

    (result,) = audit.audit_vault(vault)

    assert result.media == 1


def test_assignment_with_no_shared_term_is_reported_as_a_prompt_not_a_finding(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(course, [_row(1, "Thermodynamics Lecture", "markdown_ready")])
    (course / "_meta" / "assignments.json").write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "title": "Thermodynamics Problem Set",
                    "due_date": "2026-10-01T03:59:00Z",
                },
                {"id": 2, "title": "Genetics Poster", "due_date": "2026-11-01T03:59:00Z"},
            ]
        ),
        encoding="utf-8",
    )

    (result,) = audit.audit_vault(vault)
    report = (audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z")).read_text(
        encoding="utf-8"
    )

    # "Thermodynamics Problem Set" shares "thermodynamics" and so is not reported.
    assert [item.title for item in result.unmatched_assignments] == ["Genetics Poster"]
    assert "may have been posted somewhere the API does not expose" in report


def test_generic_coursework_words_alone_never_count_as_a_match(tmp_path: Path) -> None:
    """'Lab 4' matching 'Lab Notes' on the word 'lab' would be a false reassurance."""
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(course, [_row(1, "Lab Notes", "markdown_ready")])
    (course / "_meta" / "assignments.json").write_text(
        json.dumps([{"id": 1, "title": "Assignment Part 1", "due_date": None}]),
        encoding="utf-8",
    )

    (result,) = audit.audit_vault(vault)

    assert [item.title for item in result.unmatched_assignments] == ["Assignment Part 1"]


def test_unreadable_metadata_is_reported_instead_of_counted_as_empty(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(course, [_row(1, "Lecture", "markdown_ready")])
    (course / "_meta" / "assignments.json").write_text('{"items": []}', encoding="utf-8")

    (result,) = audit.audit_vault(vault)
    report = audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z").read_text(encoding="utf-8")

    assert result.assignments == 0
    assert result.metadata_gaps == ("assignments.json has an invalid root",)
    assert "Metadata gaps" in report
    assert "assignments.json has an invalid root" in report


def test_report_is_byte_identical_for_the_same_vault_and_timestamp(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    course = _course(vault.root)
    course_index.write_content_map(
        course,
        [_row(index, f"Topic {index}", "markdown_ready") for index in range(12)],
    )

    first = audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z").read_bytes()
    second = audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z").read_bytes()

    assert first == second
    assert b"\r\n" not in first


def test_multiple_courses_are_ordered_deterministically(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    for code in ("ZOO101", "ANT202", "MID150"):
        course_index.write_content_map(_course(vault.root, code), [_row(1, "T", "markdown_ready")])

    results = audit.audit_vault(vault)

    assert [item.course for item in results] == [
        "2026-Fall/ANT202",
        "2026-Fall/MID150",
        "2026-Fall/ZOO101",
    ]


def test_audit_is_written_into_vault_state_with_no_courses(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    destination = audit.write_audit(vault, timestamp="2026-08-25T12:00:00Z")

    assert destination == vault.state() / "AUDIT.md"
    assert "No courses have been ingested yet" in destination.read_text(encoding="utf-8")
