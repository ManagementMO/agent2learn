"""Regression tests for the deterministic local calendar and daily study view."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent2learn import calendar as calendar_module
from agent2learn import metadata_coverage
from agent2learn.schools import UWaterloo
from agent2learn.vault import Vault


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _calendar_vault(root: Path) -> Vault:
    Vault.claim(root)
    course = root / "Spring 2026" / "COURSE101_1265"
    meta = course / "_meta"
    _write_json(
        meta / "content_map.json",
        {
            "schema_version": 1,
            "topics": [
                {
                    "source_key": "uwaterloo:101:topic:1",
                    "source_id": "1",
                    "topic_id": 1,
                    "course_code": "COURSE101_1265",
                    "course_name": "Synthetic Course",
                    "term": "1265",
                    "title": "Lecture",
                }
            ],
        },
    )
    _write_json(
        meta / "assignments.json",
        [
            {"id": 2, "title": "DST essay", "due_date": "2026-03-08"},
            {
                "id": 1,
                "title": "Spring quiz",
                "due_date": "2026-03-08T07:30:00Z",
            },
        ],
    )
    _write_json(
        meta / "quizzes.json",
        [{"id": 3, "title": "Quiz 2", "due_date": "2026-11-01T06:30:00Z"}],
    )
    _write_json(
        meta / "exams.json",
        [{"id": "midterm", "title": "Midterm", "start_date": "2026-11-15T15:00:00Z"}],
    )
    _write_json(
        meta / "office_hours.json",
        [
            {
                "id": "office-1",
                "title": "Instructor office hours",
                "start_date": "2026-03-09T16:00:00Z",
                "end_date": "2026-03-09T17:00:00Z",
                "location": "Engineering 101",
            }
        ],
    )
    return Vault(root)


def _unfold(value: str) -> str:
    return value.replace("\r\n ", "")


def _event_blocks(value: str) -> list[str]:
    return [block.split("END:VEVENT", 1)[0] for block in _unfold(value).split("BEGIN:VEVENT")[1:]]


@pytest.mark.parametrize(
    "coverage",
    [
        None,
        metadata_coverage.QuizCoverage(),
        metadata_coverage.QuizCoverage("incomplete"),
        metadata_coverage.QuizCoverage("unavailable", 403),
    ],
)
def test_calendar_discloses_uncertain_quiz_coverage_and_cached_dates(
    tmp_path: Path, coverage: metadata_coverage.QuizCoverage | None
) -> None:
    vault = _calendar_vault(tmp_path)
    course = tmp_path / "Spring 2026" / "COURSE101_1265"
    if coverage is not None:
        metadata_coverage.write_quiz_coverage(course, coverage, root=vault.root)
    before = (course / "_meta" / "quizzes.json").read_bytes()
    exported = calendar_module.render_ics(
        vault, UWaterloo(), now=datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
    )

    assert "X-A2L-COVERAGE-WARNING:" in _unfold(exported).split("BEGIN:VEVENT")[0]
    events = _event_blocks(exported)
    assert len(events) == 5
    for event in events:
        if "X-A2L-KIND:quiz\r\n" in event:
            assert "DESCRIPTION:Cached quiz date" in event
            assert "not confirmed current" in event
            assert "STATUS:" not in event
        else:
            assert "DESCRIPTION:" not in event
            assert "STATUS:CONFIRMED" in event
    assert (course / "_meta" / "quizzes.json").read_bytes() == before
    assert all(len(line.encode("utf-8")) <= 75 for line in exported.split("\r\n"))
    assert "\n" not in exported.replace("\r\n", "")


@pytest.mark.parametrize("status", ["complete", "unknown", "unavailable"])
def test_calendar_zero_cached_quizzes_is_not_proof_of_complete_inventory(
    tmp_path: Path, status: metadata_coverage.CoverageStatus
) -> None:
    vault = _calendar_vault(tmp_path)
    course = tmp_path / "Spring 2026" / "COURSE101_1265"
    _write_json(course / "_meta" / "quizzes.json", [])
    metadata_coverage.write_quiz_coverage(
        course,
        metadata_coverage.QuizCoverage(status, 403 if status == "unavailable" else None),
        root=vault.root,
    )

    exported = calendar_module.render_ics(vault, UWaterloo())

    assert ("X-A2L-COVERAGE-WARNING:" in exported) == (status != "complete")
    assert exported.count("BEGIN:VEVENT") == 4
    assert "X-A2L-KIND:quiz" not in exported
    assert "DESCRIPTION:" not in exported


def test_calendar_quiz_warning_is_course_scoped_and_does_not_change_event_identity(
    tmp_path: Path,
) -> None:
    vault = _calendar_vault(tmp_path)
    first = tmp_path / "Spring 2026" / "COURSE101_1265"
    second = tmp_path / "Other term" / "COURSE101_1265"
    # Same course code and quiz id in different terms must not share a coverage decision.
    _write_json(
        second / "_meta" / "content_map.json",
        {
            "schema_version": 1,
            "topics": [{"course_code": "COURSE101_1265", "term": "other", "title": "Other"}],
        },
    )
    _write_json(
        second / "_meta" / "quizzes.json",
        [{"id": 3, "title": "Current quiz", "due_date": "2026-11-01T06:30:00Z"}],
    )
    metadata_coverage.write_quiz_coverage(
        second, metadata_coverage.QuizCoverage("complete"), root=vault.root
    )
    stamp = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
    before = calendar_module.render_ics(vault, UWaterloo(), now=stamp)
    quizzes = [block for block in _event_blocks(before) if "X-A2L-KIND:quiz" in block]
    assert len(quizzes) == 2
    for event in quizzes:
        assert ("DESCRIPTION:Cached quiz date" in event) == ("Current quiz" not in event)

    metadata_coverage.write_quiz_coverage(
        first, metadata_coverage.QuizCoverage("complete"), root=vault.root
    )
    after = calendar_module.render_ics(vault, UWaterloo(), now=stamp)
    assert "X-A2L-COVERAGE-WARNING:" not in after
    assert "DESCRIPTION:" not in after
    stable_prefixes = ("UID:", "DTSTART", "DTEND", "DTSTAMP:", "SUMMARY:")
    assert [line for line in before.splitlines() if line.startswith(stable_prefixes)] == [
        line for line in after.splitlines() if line.startswith(stable_prefixes)
    ]


def test_calendar_malformed_coverage_warns_without_exporting_raw_diagnostics(
    tmp_path: Path,
) -> None:
    vault = _calendar_vault(tmp_path)
    meta = tmp_path / "Spring 2026" / "COURSE101_1265" / "_meta"
    _write_json(
        meta / "metadata_coverage.json",
        {
            "schema_version": 1,
            "collections": {
                "quizzes": {"status": "complete", "detail": "PRIVATE_SENTINEL\r\nURL:bad"}
            },
        },
    )

    exported = _unfold(calendar_module.render_ics(vault, UWaterloo()))

    assert "X-A2L-COVERAGE-WARNING:" in exported
    assert "DESCRIPTION:Cached quiz date" in exported
    assert "PRIVATE_SENTINEL" not in exported
    assert "URL:bad" not in exported


def test_calendar_is_valid_deterministic_and_timezone_explicit(tmp_path: Path) -> None:
    vault = _calendar_vault(tmp_path)
    school = UWaterloo()
    stamp = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)

    first = calendar_module.render_ics(vault, school, now=stamp)
    second = calendar_module.render_ics(vault, school, now=stamp)

    assert first == second
    assert first.startswith("BEGIN:VCALENDAR\r\n")
    assert first.endswith("END:VCALENDAR\r\n")
    assert first.count("BEGIN:VEVENT\r\n") == 5
    assert "PRODID:-//Agent2Learn//Calendar//EN\r\n" in first
    assert "DTSTAMP:20260828T160000Z\r\n" in first
    assert "DTSTART;VALUE=DATE:20260308\r\n" in first
    # 07:30Z is 03:30 in Toronto after the spring-forward transition.
    assert "DTSTART;TZID=America/Toronto:20260308T033000\r\n" in first
    # 06:30Z is 01:30 in Toronto before the fall-back transition.
    assert "DTSTART;TZID=America/Toronto:20261101T013000\r\n" in first
    assert "DTSTART;TZID=America/Toronto:20260309T120000\r\n" in first
    assert "DTEND;TZID=America/Toronto:20260309T130000\r\n" in first
    assert "TZID=America/Toronto" in first
    assert "DTSTAMP;TZID" not in first

    uids = [line for line in first.splitlines() if line.startswith("UID:")]
    assert len(uids) == len(set(uids)) == 5


def test_calendar_does_not_depend_on_machine_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(time, "tzset"):
        pytest.skip("the platform does not expose tzset")

    vault = _calendar_vault(tmp_path)
    school = UWaterloo()
    stamp = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)

    original_tz = os.environ.get("TZ")
    try:
        monkeypatch.setenv("TZ", "Pacific/Auckland")
        time.tzset()
        Auckland = calendar_module.render_ics(vault, school, now=stamp)
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        LosAngeles = calendar_module.render_ics(vault, school, now=stamp)
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    assert Auckland == LosAngeles


def test_calendar_uids_survive_reordered_metadata(tmp_path: Path) -> None:
    vault = _calendar_vault(tmp_path)
    school = UWaterloo()
    stamp = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
    before = calendar_module.render_ics(vault, school, now=stamp)

    assignments = vault.root / "Spring 2026" / "COURSE101_1265" / "_meta" / "assignments.json"
    rows = json.loads(assignments.read_text(encoding="utf-8"))
    assignments.write_text(json.dumps(list(reversed(rows))) + "\n", encoding="utf-8")
    after = calendar_module.render_ics(vault, school, now=stamp)

    assert before == after


def test_calendar_output_file_is_atomic(tmp_path: Path) -> None:
    vault = _calendar_vault(tmp_path)
    destination = tmp_path / "exports" / "deadlines.ics"

    written = calendar_module.write_ics(
        vault, UWaterloo(), destination, now=datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
    )

    assert written == destination
    assert destination.read_bytes()
    assert not list(destination.parent.glob("*.tmp"))


def test_today_uses_the_school_zone_for_due_windows_and_exam_countdown(tmp_path: Path) -> None:
    vault = _calendar_vault(tmp_path)
    course_meta = tmp_path / "Spring 2026" / "COURSE101_1265" / "_meta"
    _write_json(
        course_meta / "assignments.json",
        [
            {"id": "overdue", "title": "Overdue", "due_date": "2026-08-28T15:59:00Z"},
            {"id": "soon", "title": "Soon", "due_date": "2026-09-04T15:00:00Z"},
        ],
    )
    _write_json(
        course_meta / "exams.json",
        [{"id": "exam", "title": "Exam", "start_date": "2026-09-10T15:00:00Z"}],
    )

    report = calendar_module.build_today(
        vault,
        UWaterloo(),
        now=datetime(2026, 8, 28, 16, 0, tzinfo=UTC),
    )

    assert {event.source_id for event in report.overdue} == {"overdue"}
    assert {event.source_id for event in report.due_soon} == {"soon"}
    assert [(item.event.source_id, item.days_remaining) for item in report.exam_countdowns] == [
        ("exam", 13)
    ]
