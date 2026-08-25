# ruff: noqa: E501
"""Informational AI-policy surfacing from already-rendered local outlines."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

from agent2learn import paths

AI_POLICY_SCHEMA_VERSION = 1
_KEYWORDS = re.compile(
    r"generative ai|chatgpt|artificial intelligence|genai|large language model", re.IGNORECASE
)


def surface_ai_policy(course_dir: Path, outline: Path | None) -> dict[str, object]:
    """Record a local observation without classifying, scoring, or enforcing a policy."""
    if outline is None:
        record: dict[str, object] = {
            "schema_version": AI_POLICY_SCHEMA_VERSION,
            "status": "outline_unavailable",
            "text": None,
            "source": None,
        }
    else:
        try:
            with open(os.fspath(paths.long_path(outline)), encoding="utf-8", newline="") as handle:
                lines = handle.read().splitlines()
        except (FileNotFoundError, OSError, UnicodeError):
            record = {
                "schema_version": AI_POLICY_SCHEMA_VERSION,
                "status": "outline_unavailable",
                "text": None,
                "source": None,
            }
        else:
            hit = next((index for index, line in enumerate(lines) if _KEYWORDS.search(line)), None)
            if hit is None:
                record = {
                    "schema_version": AI_POLICY_SCHEMA_VERSION,
                    "status": "not_found_in_scanned_outline",
                    "text": None,
                    "source": None,
                }
            else:
                end = next(
                    (index for index in range(hit + 1, len(lines)) if lines[index].startswith("#")),
                    len(lines),
                )
                text = "\n".join(lines[hit:end]).strip()
                record = {
                    "schema_version": AI_POLICY_SCHEMA_VERSION,
                    "status": "found",
                    "text": text,
                    "source": f"{outline.relative_to(course_dir).as_posix()}:{hit + 1}",
                }
    destination = course_dir / "_meta" / "ai_policy.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(
        paths.long_path(destination),
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n",
    )
    _surface_index_line(course_dir, record)
    return record


def surface_course_ai_policy(course_dir: Path, outlines: Sequence[Path]) -> dict[str, object]:
    """Record the first found clause across successful local outline renders.

    All supplied paths were successfully rendered by the outline boundary.  An empty set is
    therefore unavailable coverage; a non-empty set with no keyword is a scanned no-match.
    """
    if not outlines:
        return surface_ai_policy(course_dir, None)
    last: dict[str, object] | None = None
    for outline in sorted(outlines, key=lambda value: value.as_posix()):
        record = surface_ai_policy(course_dir, outline)
        if record["status"] == "found":
            return record
        last = record
    assert last is not None
    return last


def _surface_index_line(course_dir: Path, record: dict[str, object]) -> None:
    index = course_dir / "INDEX.md"
    try:
        with open(os.fspath(paths.long_path(index)), encoding="utf-8", newline="") as handle:
            lines = [
                line for line in handle.read().splitlines() if not line.startswith("- AI policy: ")
            ]
    except FileNotFoundError:
        return
    status = str(record["status"])
    detail = str(record["source"]) if record["source"] is not None else status
    lines.extend(["", "## AI policy", "", f"- AI policy: {status} — {detail}", ""])
    paths.atomic_write_text(paths.long_path(index), "\n".join(lines))
