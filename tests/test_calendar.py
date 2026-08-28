"""Regression tests for the deterministic local calendar and daily study view."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent2learn import calendar as calendar_module
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


def test_calendar_does_not_depend_on_machine_timezone(tmp_path: Path, monkeypatch) -> None:
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
