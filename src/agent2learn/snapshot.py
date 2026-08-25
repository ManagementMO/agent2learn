# ruff: noqa: E501
"""Atomic, privacy-bounded sync snapshots consumed by a later diff command."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
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
    for course in sorted(course_dirs, key=lambda value: paths.rel_posix(value, vault.root)):
        meta = course / "_meta"
        content = _read_json(meta / "content_map.json", {"topics": []})
        assignments = _read_json(meta / "assignments.json", [])
        news = _read_json(meta / "news.json", [])
        item: dict[str, object] = {
            "course": paths.rel_posix(course, vault.root),
            "topic_ids": sorted(
                row["topic_id"]
                for row in content.get("topics", [])
                if isinstance(row, dict) and isinstance(row.get("topic_id"), int)
            ),
            "due_dates": sorted(
                {
                    str(row["due_date"])
                    for row in assignments
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
            item["grades"] = _read_json(meta / "my_grades.json", [])
        courses.append(item)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": timestamp,
        "courses": courses,
    }
    filename = timestamp.replace("-", "").replace(":", "").replace("+00:00", "Z") + ".json"
    destination = vault.state() / "snapshots" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(
        paths.long_path(destination),
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n",
    )
    return destination


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            return json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default
