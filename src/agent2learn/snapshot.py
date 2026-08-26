# ruff: noqa: E501
"""Atomic, privacy-bounded sync snapshots consumed by a later diff command."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent2learn import paths
from agent2learn.vault import Vault

SNAPSHOT_SCHEMA_VERSION = 1


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
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(
        destination,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n",
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
    canonical = utc.isoformat(timespec="microseconds" if utc.microsecond else "seconds").replace(
        "+00:00", "Z"
    )
    filename = canonical.replace("-", "").replace(":", "").replace(".", "")
    return canonical, filename
