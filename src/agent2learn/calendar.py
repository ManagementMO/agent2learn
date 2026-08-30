"""Local calendar export and the read-only ``today`` study view.

Calendar input is deliberately limited to typed metadata already written in a vault.  The
module never contacts LEARN, follows URLs, or copies announcement/grade bodies into an iCalendar
file.  Assignment and quiz due dates come from their normalized ``_meta`` projections; optional
``exams.json`` and ``office_hours.json`` projections use the same small date-field vocabulary.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent2learn import clock, paths, snapshot
from agent2learn.errors import A2LError
from agent2learn.schools import School, parse_api_timestamp
from agent2learn.vault import Vault

CalendarKind = Literal["assignment", "quiz", "exam", "office_hour"]


@dataclass(frozen=True)
class CalendarEvent:
    """One normalized event before it is serialized to iCalendar."""

    uid: str
    course: str
    course_name: str
    kind: CalendarKind
    source_id: str
    summary: str
    start: datetime | date
    end: datetime | date | None = None
    location: str | None = None

    @property
    def all_day(self) -> bool:
        """Return whether this event came from a date-only value."""

        return isinstance(self.start, date) and not isinstance(self.start, datetime)


@dataclass(frozen=True)
class ExamCountdown:
    """A future exam's local date and whole-day countdown."""

    event: CalendarEvent
    days_remaining: int


@dataclass(frozen=True)
class TodayReport:
    """Structured local information shown by ``a2l today``."""

    as_of: datetime
    timezone: str
    due_soon: tuple[CalendarEvent, ...]
    overdue: tuple[CalendarEvent, ...]
    exam_countdowns: tuple[ExamCountdown, ...]
    changes: snapshot.SnapshotDiff


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_FILES: tuple[tuple[str, CalendarKind], ...] = (
    ("assignments.json", "assignment"),
    ("quizzes.json", "quiz"),
    ("exams.json", "exam"),
    ("office_hours.json", "office_hour"),
)
_CALENDAR_CONTAINER_KEYS = {
    "assignment": "assignments",
    "quiz": "quizzes",
    "exam": "exams",
    "office_hour": "office_hours",
}


def collect_events(vault: Vault, school: School) -> tuple[CalendarEvent, ...]:
    """Collect deterministic assignment, quiz, exam, and office-hour events.

    A missing optional exam or office-hour projection is a valid partial calendar: this function
    cannot invent events from a course end date or from a web URL.  Malformed present metadata is
    surfaced as an error, matching the rest of the vault's typed metadata readers.
    """

    if not paths.long_path(vault.root).is_dir():
        return ()

    events: list[CalendarEvent] = []
    seen_uids: set[str] = set()
    for content_map in sorted(
        (
            candidate
            for candidate in paths.walk(vault.root)
            if candidate.name == "content_map.json" and ".a2l" not in candidate.parts
        ),
        key=lambda candidate: paths.rel_posix(candidate, vault.root),
    ):
        if paths.is_link(content_map):
            raise A2LError("content_map.json must not be a symlink")
        course_dir = content_map.parent.parent
        context = _course_context(content_map, course_dir)
        for filename, kind in _SOURCE_FILES:
            rows = _read_rows(course_dir / "_meta" / filename)
            for row in rows:
                event = _event_from_row(row, kind, context, school)
                if event is None or event.uid in seen_uids:
                    continue
                seen_uids.add(event.uid)
                events.append(event)

        # A single normalized container is convenient for adapters that receive exams and office
        # hours together.  The dedicated files above remain the canonical simple form.
        for kind in ("exam", "office_hour"):
            rows = _read_container_rows(course_dir / "_meta" / "calendar.json", kind)
            for row in rows:
                event = _event_from_row(row, kind, context, school)
                if event is None or event.uid in seen_uids:
                    continue
                seen_uids.add(event.uid)
                events.append(event)

    return tuple(sorted(events, key=lambda event: _event_sort_key(event, school.timezone)))


def render_ics(vault: Vault, school: School, *, now: datetime | None = None) -> str:
    """Render a CRLF-terminated RFC 5545 calendar with stable event UIDs."""

    timezone = _zone(school.timezone)
    stamp = _aware_utc(now if now is not None else clock.now(), "calendar timestamp")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Agent2Learn//Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{_escape_text(school.timezone)}",
    ]
    for event in collect_events(vault, school):
        lines.extend(_event_lines(event, timezone, stamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(line for raw in lines for line in _fold_line(raw)) + "\r\n"


def write_ics(
    vault: Vault,
    school: School,
    destination: Path,
    *,
    now: datetime | None = None,
) -> Path:
    """Atomically write a calendar export to an explicit local destination."""

    if paths.is_link(destination) or paths.has_link_component(destination.parent):
        raise A2LError("calendar destination must not contain a symlink")
    try:
        destination.relative_to(vault.root)
    except ValueError:
        bound_root = None
    else:
        bound_root = vault.root
    paths.ensure_dir(destination.parent, root=bound_root)
    paths.atomic_write_text(destination, render_ics(vault, school, now=now), root=bound_root)
    return destination


def build_today(
    vault: Vault,
    school: School,
    *,
    now: datetime | None = None,
    include_grades: bool = False,
) -> TodayReport:
    """Build the local daily view using explicit school-zone date arithmetic."""

    as_of = _aware_utc(now if now is not None else clock.now(), "today timestamp")
    timezone = _zone(school.timezone)
    local_now = as_of.astimezone(timezone)
    local_today = local_now.date()
    week_end = local_today + timedelta(days=7)
    due_soon: list[CalendarEvent] = []
    overdue: list[CalendarEvent] = []
    exam_countdowns: list[ExamCountdown] = []

    for event in collect_events(vault, school):
        if event.kind in {"assignment", "quiz"}:
            if event.all_day:
                event_date = event.start
                if event_date < local_today:
                    overdue.append(event)
                elif event_date <= week_end:
                    due_soon.append(event)
            else:
                start = cast(datetime, event.start)
                if start < as_of:
                    overdue.append(event)
                elif start.astimezone(timezone).date() <= week_end:
                    due_soon.append(event)
        elif event.kind == "exam":
            event_date = (
                event.start
                if event.all_day
                else cast(datetime, event.start).astimezone(timezone).date()
            )
            if event_date >= local_today and event_date <= local_today + timedelta(days=30):
                exam_countdowns.append(
                    ExamCountdown(event, max(0, (event_date - local_today).days))
                )

    due_soon.sort(key=lambda event: _event_sort_key(event, school.timezone))
    overdue.sort(key=lambda event: _event_sort_key(event, school.timezone))
    exam_countdowns.sort(key=lambda item: _event_sort_key(item.event, school.timezone))
    return TodayReport(
        as_of=as_of,
        timezone=school.timezone,
        due_soon=tuple(due_soon),
        overdue=tuple(overdue),
        exam_countdowns=tuple(exam_countdowns),
        changes=snapshot.diff_vault(vault, include_grades=include_grades),
    )


def render_today(report: TodayReport, *, include_grades: bool = False) -> str:
    """Render a concise daily view; sensitive grades remain opt-in at presentation time too."""

    lines = [
        f"Today · {report.as_of.astimezone(_zone(report.timezone)).date()} ({report.timezone})",
        "",
    ]
    if report.exam_countdowns:
        lines.append("Exam countdown:")
        for countdown in report.exam_countdowns:
            lines.append(
                f"- {countdown.event.summary} · {countdown.days_remaining} day(s) remaining"
            )
        lines.append("")
    if report.overdue:
        lines.append("Overdue:")
        lines.extend(f"- {_display_event(event)}" for event in report.overdue)
        lines.append("")
    if report.due_soon:
        lines.append("Due within 7 days:")
        lines.extend(f"- {_display_event(event)}" for event in report.due_soon)
        lines.append("")
    if not report.overdue and not report.due_soon:
        lines.extend(["No assignments or quizzes due within 7 days.", ""])

    change_text = snapshot.render_diff(report.changes, include_grades=include_grades).rstrip()
    if report.changes.has_baseline:
        lines.extend(["Changes since last sync:", change_text, ""])
    else:
        lines.extend(["Changes since last sync:", "- No previous sync snapshot.", ""])
    return "\n".join(lines).rstrip() + "\n"


def _event_lines(event: CalendarEvent, timezone: ZoneInfo, stamp: datetime) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.uid}",
        f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_escape_text(event.summary)}",
        f"X-A2L-KIND:{event.kind}",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
    ]
    if event.all_day:
        lines.append(f"DTSTART;VALUE=DATE:{event.start.strftime('%Y%m%d')}")
        if isinstance(event.end, date) and not isinstance(event.end, datetime):
            lines.append(f"DTEND;VALUE=DATE:{event.end.strftime('%Y%m%d')}")
    else:
        lines.append(f"DTSTART;TZID={timezone.key}:{_local_datetime(event.start, timezone)}")
        if isinstance(event.end, datetime):
            lines.append(f"DTEND;TZID={timezone.key}:{_local_datetime(event.end, timezone)}")
    if event.location:
        lines.append(f"LOCATION:{_escape_text(event.location)}")
    lines.append("END:VEVENT")
    return lines


def _local_datetime(value: datetime | date, timezone: ZoneInfo) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        raise ValueError("a date-only event cannot use a timed iCalendar field")
    return value.astimezone(timezone).strftime("%Y%m%dT%H%M%S")


def _event_from_row(
    row: Mapping[str, object], kind: CalendarKind, context: Mapping[str, str], school: School
) -> CalendarEvent | None:
    if row.get("withdrawn_at"):
        return None
    value = _first_value(row, _date_keys(kind))
    if value is None:
        return None
    start = _parse_event_time(value, school.timezone)
    end_value = _first_value(row, ("end_date", "end", "end_time", "EndDate"))
    end = _parse_event_time(end_value, school.timezone) if end_value is not None else None
    if end is not None and _event_sort_key_values(end, school.timezone) < _event_sort_key_values(
        start, school.timezone
    ):
        raise A2LError("calendar event end precedes its start")
    identifier = _event_id(row, kind)
    course_key = context["course_key"]
    event_key = f"{school.id}:{course_key}:{kind}:{identifier}"
    uid = f"{sha256(event_key.encode('utf-8')).hexdigest()}@agent2learn"
    title = (
        _first_text(row, ("title", "name", "Name", "Title"))
        or f"{kind.replace('_', ' ').title()} {identifier}"
    )
    course_code = context["course_code"]
    return CalendarEvent(
        uid=uid,
        course=course_code,
        course_name=context["course_name"],
        kind=kind,
        source_id=identifier,
        summary=f"[{course_code}] {title}",
        start=start,
        end=end,
        location=_first_text(row, ("location", "Location", "room", "Room")),
    )


def _date_keys(kind: CalendarKind) -> tuple[str, ...]:
    if kind in {"assignment", "quiz"}:
        return ("due_date", "DueDate", "date")
    return ("start_date", "start", "exam_date", "date", "Date", "StartDate")


def _event_id(row: Mapping[str, object], kind: CalendarKind) -> str:
    for key in ("id", "Id", "QuizId", "exam_id", "office_hour_id"):
        value = row.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return str(value)
    canonical = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(f"{kind}:{canonical}".encode()).hexdigest()[:24]


def _course_context(content_map: Path, course_dir: Path) -> dict[str, str]:
    raw = _read_json(content_map)
    topics = raw.get("topics")
    if not isinstance(topics, list):
        raise A2LError("content_map.json topics must be an array")
    for item in topics:
        if not isinstance(item, dict):
            continue
        code = item.get("course_code")
        name = item.get("course_name")
        term = item.get("term")
        if isinstance(code, str) and code:
            course_key = f"{code}|{term}" if isinstance(term, str) and term else code
            offering_id = item.get("course_org_unit_id", item.get("org_unit_id"))
            if isinstance(offering_id, (str, int)) and not isinstance(offering_id, bool):
                course_key = f"{course_key}|{offering_id}"
            return {
                "course_key": course_key,
                "course_code": code,
                "course_name": name if isinstance(name, str) and name else code,
            }
    relative = paths.rel_posix(course_dir, course_dir.parents[1])
    return {"course_key": relative, "course_code": course_dir.name, "course_name": course_dir.name}


def _read_rows(path: Path) -> list[dict[str, object]]:
    if not paths.long_path(path).exists():
        return []
    if paths.is_link(path):
        raise A2LError("calendar metadata must not be a symlink")
    raw = _read_json_value(path)
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise A2LError(f"{path.name} must contain a list of objects")
    return [cast(dict[str, object], item) for item in raw]


def _read_container_rows(path: Path, kind: str) -> list[dict[str, object]]:
    if not paths.long_path(path).exists():
        return []
    if paths.is_link(path):
        raise A2LError("calendar metadata must not be a symlink")
    if not paths.long_path(path).is_file():
        raise A2LError("calendar.json must be a regular file")
    raw = _read_json(path)
    value = raw.get(_CALENDAR_CONTAINER_KEYS[kind])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise A2LError(f"calendar.json {_CALENDAR_CONTAINER_KEYS[kind]} must be a list")
    return [cast(dict[str, object], item) for item in value]


def _read_json(path: Path) -> dict[str, object]:
    raw = _read_json_value(path)
    if not isinstance(raw, dict):
        raise A2LError(f"{path.name} must contain an object")
    return cast(dict[str, object], raw)


def _read_json_value(path: Path) -> Any:
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A2LError(f"{path.name} is unreadable") from exc


def _parse_event_time(value: object, timezone_name: str) -> datetime | date:
    if isinstance(value, datetime):
        return _normalize_datetime(value, timezone_name)
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        raise A2LError("calendar event date must be an ISO-8601 string")
    if _DATE_ONLY.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise A2LError("calendar event date is invalid") from exc
    try:
        return _normalize_datetime(parse_api_timestamp(value), timezone_name)
    except ValueError as exc:
        # Adapter-authored local calendar rows may omit an offset.  They are interpreted in the
        # school zone explicitly; machine TZ is never consulted.
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as inner:
            raise A2LError("calendar event timestamp is invalid") from inner
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            raise A2LError("calendar event timestamp is invalid") from exc
        return parsed.replace(tzinfo=_zone(timezone_name))


def _normalize_datetime(value: datetime, timezone_name: str) -> datetime:
    return _aware_utc(value, "calendar event timestamp").astimezone(_zone(timezone_name))


def _event_sort_key(event: CalendarEvent, timezone_name: str) -> tuple[datetime, str]:
    return (*_event_sort_key_values(event.start, timezone_name), event.uid)


def _event_sort_key_values(value: datetime | date, timezone_name: str) -> tuple[datetime]:
    timezone = _zone(timezone_name)
    if isinstance(value, datetime):
        return (value.astimezone(timezone),)
    return (datetime.combine(value, datetime.min.time(), tzinfo=timezone),)


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise A2LError("school timezone is unavailable") from exc


def _first_value(row: Mapping[str, object], keys: Sequence[str]) -> object | None:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _first_text(row: Mapping[str, object], keys: Sequence[str]) -> str | None:
    value = _first_value(row, keys)
    return value if isinstance(value, str) and value.strip() else None


def _escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold_line(line: str) -> list[str]:
    """Fold an iCalendar content line at 75 UTF-8 octets."""

    chunks: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 75 and current:
            chunks.append(current)
            current = " " + char
        else:
            current = candidate
    chunks.append(current)
    return chunks


def _display_event(event: CalendarEvent) -> str:
    if event.all_day:
        when = event.start.isoformat()
    else:
        when = cast(datetime, event.start).isoformat(timespec="minutes")
    return f"{when} · {event.summary}"


__all__ = [
    "CalendarEvent",
    "ExamCountdown",
    "TodayReport",
    "build_today",
    "collect_events",
    "render_ics",
    "render_today",
    "write_ics",
]
