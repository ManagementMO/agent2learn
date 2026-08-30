# ruff: noqa: E501
"""Atomic, privacy-bounded sync snapshots consumed by a later diff command."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from agent2learn import paths
from agent2learn.vault import Vault

SNAPSHOT_SCHEMA_VERSION = 1


class _CourseSnapshot(TypedDict):
    topic_ids: set[int]
    announcement_ids: set[str]
    due_dates: tuple[str, ...]
    grades: dict[str, dict[str, object]]


@dataclass(frozen=True)
class SnapshotDiff:
    """The privacy-bounded result of comparing two completed sync snapshots.

    The snapshot format intentionally stores stable IDs rather than source text.  A diff can
    therefore say what changed without copying announcements, grade comments, or course content
    into a report.  ``new_grades`` is populated only when the caller explicitly opts in.
    """

    previous_timestamp: str | None
    current_timestamp: str | None
    new_content: tuple[dict[str, object], ...] = ()
    new_announcements: tuple[dict[str, object], ...] = ()
    changed_due_dates: tuple[dict[str, object], ...] = ()
    new_grades: tuple[dict[str, object], ...] = ()

    @property
    def has_baseline(self) -> bool:
        """Return whether the current snapshot had an earlier snapshot to compare against."""

        return self.previous_timestamp is not None


def write_snapshot(
    vault: Vault, course_dirs: Sequence[Path], *, include_grades: bool, timestamp: str
) -> Path:
    """Write one deterministic local snapshot; omitted grades are never copied forward."""
    courses: list[dict[str, object]] = []
    canonical_timestamp, filename_timestamp = _snapshot_timestamp(timestamp)
    for course in sorted(course_dirs, key=lambda value: paths.rel_posix(value, vault.root)):
        meta = course / "_meta"
        content = _read_json(meta / "content_map.json", None)
        if not isinstance(content, dict) or not isinstance(content.get("topics"), list):
            raise ValueError("content_map metadata must contain a topics list")
        topics = _object_rows(content["topics"], "content_map topics")
        assignments = _object_rows(_read_json(meta / "assignments.json", None), "assignments")
        quizzes = _object_rows(_read_json(meta / "quizzes.json", None), "quizzes")
        news = _object_rows(_read_json(meta / "news.json", None), "news")
        topic_ids: list[int] = []
        for row in topics:
            topic_id = row.get("topic_id")
            if isinstance(topic_id, bool) or not isinstance(topic_id, int):
                raise ValueError("content_map topics contain an invalid topic_id")
            topic_ids.append(topic_id)
        item: dict[str, object] = {
            "course": paths.rel_posix(course, vault.root),
            "topic_ids": sorted(topic_ids),
            "due_dates": sorted(
                {
                    str(row["due_date"])
                    for row in [*assignments, *quizzes]
                    if isinstance(row, dict) and row.get("due_date")
                }
            ),
            "announcement_ids": sorted(
                str(row["id"])
                for row in news
                if isinstance(row, dict) and row.get("id") is not None
            ),
        }
        if include_grades:
            item["grades"] = _object_rows(_read_json(meta / "my_grades.json", None), "grades")
        courses.append(item)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": canonical_timestamp,
        "courses": courses,
    }
    filename = f"{filename_timestamp}.json"
    destination = vault.state() / "snapshots" / filename
    paths.ensure_dir(destination.parent, root=vault.root)
    paths.atomic_write_text(
        destination,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n",
        root=vault.root,
    )
    return destination


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("snapshot metadata is unreadable") from exc


def _object_rows(value: Any, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} metadata must be a list")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} metadata contains an invalid item")
    return value


def _snapshot_timestamp(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("snapshot timestamp must be an ISO-8601 string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("snapshot timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("snapshot timestamp must be timezone-aware")
    utc = parsed.astimezone(UTC)
    canonical = _canonical_timestamp(utc)
    filename = canonical.replace("-", "").replace(":", "").replace(".", "")
    return canonical, filename


def diff_vault(
    vault: Vault, *, since: str | None = None, include_grades: bool = False
) -> SnapshotDiff:
    """Compare the latest local snapshot with its previous snapshot.

    ``since`` may be an exact snapshot filename/stem or an exact ``created_at`` value.  Requiring
    an exact match avoids silently comparing against the wrong sync when a vault contains several
    snapshots from the same day.  An empty snapshot directory is a valid first-sync state and
    returns an honest no-baseline result; malformed snapshots remain errors rather than becoming
    empty data.
    """

    snapshots = _read_snapshots(vault)
    if not snapshots:
        return SnapshotDiff(None, None)

    ordered = sorted(snapshots, key=lambda item: (item[0], item[1].name))
    current_timestamp, current_path, current = ordered[-1]
    del current_path
    previous: tuple[str, Path, dict[str, object]] | None = None
    if since is None:
        if len(ordered) > 1:
            previous = ordered[-2]
    else:
        previous = _select_snapshot(ordered, since, current_timestamp)

    return compare_snapshots(
        previous[2] if previous is not None else None,
        current,
        include_grades=include_grades,
    )


def compare_snapshots(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
    *,
    include_grades: bool = False,
) -> SnapshotDiff:
    """Compare two validated snapshot-shaped mappings without reading the filesystem."""

    current_timestamp = _snapshot_created_at(current)
    previous_timestamp = _snapshot_created_at(previous) if previous is not None else None
    current_courses = _course_map(current)
    previous_courses = _course_map(previous) if previous is not None else {}

    new_content: list[dict[str, object]] = []
    new_announcements: list[dict[str, object]] = []
    changed_due_dates: list[dict[str, object]] = []
    new_grades: list[dict[str, object]] = []

    for course in sorted(current_courses):
        current_row = current_courses[course]
        previous_row = previous_courses.get(course)
        if previous_row is None:
            # A first snapshot for a newly selected course is not presented as a pile of changes;
            # the next sync can establish a meaningful baseline for it.
            continue

        for topic_id in sorted(current_row["topic_ids"] - previous_row["topic_ids"]):
            new_content.append({"course": course, "topic_id": topic_id})
        for announcement_id in sorted(
            current_row["announcement_ids"] - previous_row["announcement_ids"]
        ):
            new_announcements.append({"course": course, "announcement_id": announcement_id})
        if current_row["due_dates"] != previous_row["due_dates"]:
            changed_due_dates.append(
                {
                    "course": course,
                    "previous": previous_row["due_dates"],
                    "current": current_row["due_dates"],
                }
            )

        if include_grades:
            old_grades = previous_row["grades"]
            for grade_id, grade in sorted(current_row["grades"].items()):
                if old_grades.get(grade_id) != grade:
                    new_grades.append({"course": course, "grade": grade})

    return SnapshotDiff(
        previous_timestamp=previous_timestamp,
        current_timestamp=current_timestamp,
        new_content=tuple(new_content),
        new_announcements=tuple(new_announcements),
        changed_due_dates=tuple(changed_due_dates),
        new_grades=tuple(new_grades) if include_grades else (),
    )


def render_diff(diff: SnapshotDiff, *, include_grades: bool = False) -> str:
    """Render a stable human-readable diff without exposing opt-in grades by default."""

    if not diff.has_baseline:
        return "No previous sync snapshot; changes will appear after the next sync.\n"

    lines = [
        f"Changes since {diff.previous_timestamp} (latest sync {diff.current_timestamp}):",
        "",
    ]
    if diff.new_content:
        lines.extend(["New content:"])
        lines.extend(f"- {row['course']} · topic {row['topic_id']}" for row in diff.new_content)
        lines.append("")
    if diff.new_announcements:
        lines.extend(["New announcements:"])
        lines.extend(
            f"- {row['course']} · announcement {row['announcement_id']}"
            for row in diff.new_announcements
        )
        lines.append("")
    if diff.changed_due_dates:
        lines.extend(["Changed due dates:"])
        for row in diff.changed_due_dates:
            previous = ", ".join(cast(tuple[str, ...], row["previous"])) or "none"
            current = ", ".join(cast(tuple[str, ...], row["current"])) or "none"
            lines.append(f"- {row['course']} · {previous} → {current}")
        lines.append("")
    if include_grades and diff.new_grades:
        lines.extend(["New grades:"])
        for row in diff.new_grades:
            grade = cast(dict[str, object], row["grade"])
            lines.append(
                f"- {row['course']} · {grade.get('name') or grade.get('id') or 'grade'}: "
                f"{grade.get('displayed', 'posted')}"
            )
        lines.append("")
    visible_grades = diff.new_grades if include_grades else ()
    if not any((diff.new_content, diff.new_announcements, diff.changed_due_dates, visible_grades)):
        lines.append("No changes recorded.")
    return "\n".join(lines).rstrip() + "\n"


def _read_snapshots(vault: Vault) -> list[tuple[str, Path, dict[str, object]]]:
    directory = vault.state() / "snapshots"
    if paths.is_link(directory):
        raise ValueError("snapshot directory must not be a symlink")
    if not paths.long_path(directory).is_dir():
        return []
    results: list[tuple[str, Path, dict[str, object]]] = []
    for path in sorted(paths.walk(directory)):
        if paths.is_link(path):
            raise ValueError("snapshot must not be a symlink")
        if path.suffix.casefold() != ".json":
            continue
        raw = _read_json(path, None)
        if not isinstance(raw, dict):
            raise ValueError("snapshot must contain an object")
        if raw.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("snapshot has an unsupported schema")
        created_at = _snapshot_created_at(raw)
        if not isinstance(raw.get("courses"), list):
            raise ValueError("snapshot courses must be a list")
        _course_map(raw)  # validate the small comparison surface before selecting a baseline
        results.append((created_at, path, raw))
    return results


def _select_snapshot(
    ordered: Sequence[tuple[str, Path, dict[str, object]]], since: str, current: str
) -> tuple[str, Path, dict[str, object]]:
    normalized = since.strip()
    matches = [
        item
        for item in ordered
        if item[0] == normalized or item[1].stem == normalized or item[0].startswith(normalized)
    ]
    if len(matches) != 1:
        raise ValueError("--since must identify exactly one prior snapshot")
    selected = matches[0]
    if selected[0] >= current:
        raise ValueError("--since must identify a snapshot before the latest sync")
    return selected


def _snapshot_created_at(value: Mapping[str, object] | None) -> str:
    if value is None:
        raise ValueError("snapshot is missing created_at")
    created_at = value.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("snapshot created_at must be an ISO-8601 string")
    candidate = created_at[:-1] + "+00:00" if created_at.endswith("Z") else created_at
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("snapshot created_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("snapshot created_at must be timezone-aware")
    return _canonical_timestamp(parsed.astimezone(UTC))


def _canonical_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds" if value.microsecond else "seconds").replace(
        "+00:00", "Z"
    )


def _course_map(
    value: Mapping[str, object] | None,
) -> dict[str, _CourseSnapshot]:
    if value is None:
        return {}
    raw_courses = value.get("courses")
    if not isinstance(raw_courses, list):
        raise ValueError("snapshot courses must be a list")
    courses: dict[str, _CourseSnapshot] = {}
    for raw in raw_courses:
        if not isinstance(raw, dict):
            raise ValueError("snapshot contains an invalid course")
        course = raw.get("course")
        if not isinstance(course, str) or not course or course in courses:
            raise ValueError("snapshot contains an invalid or duplicate course")
        courses[course] = {
            "topic_ids": _int_set(raw.get("topic_ids"), "topic_ids"),
            "announcement_ids": _str_set(raw.get("announcement_ids"), "announcement_ids"),
            "due_dates": tuple(sorted(_str_set(raw.get("due_dates"), "due_dates"))),
            "grades": _grade_map(raw.get("grades")),
        }
    return courses


def _int_set(value: object, label: str) -> set[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValueError(f"snapshot {label} must be an integer list")
    return set(value)


def _str_set(value: object, label: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"snapshot {label} must be a string list")
    return set(value)


def _grade_map(value: object) -> dict[str, dict[str, object]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ValueError("snapshot grades must be a list")
    result: dict[str, dict[str, object]] = {}
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise ValueError("snapshot contains an invalid grade")
        identifier = raw["id"]
        if identifier in result:
            raise ValueError("snapshot contains duplicate grades")
        result[identifier] = dict(raw)
    return result


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "SnapshotDiff",
    "compare_snapshots",
    "diff_vault",
    "render_diff",
    "write_snapshot",
]
