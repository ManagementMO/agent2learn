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
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_POLICY_START = "<!-- a2l:ai-policy:start -->"
_POLICY_END = "<!-- a2l:ai-policy:end -->"


def surface_ai_policy(
    course_dir: Path, outline: Path | None, *, root: Path | None = None
) -> dict[str, object]:
    """Record a local observation without classifying, scoring, or enforcing a policy."""
    record = _scan_outline(course_dir, outline)
    _write_record(course_dir, record, root=root)
    return record


def _scan_outline(course_dir: Path, outline: Path | None) -> dict[str, object]:
    if outline is None:
        return _unavailable()
    try:
        with open(os.fspath(paths.long_path(outline)), encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return _unavailable()

    heading_match = next(
        (
            (index, line)
            for index, line in enumerate(lines)
            if _HEADING.match(line) and _KEYWORDS.search(line)
        ),
        None,
    )
    if heading_match is not None:
        start, _ = heading_match
        end = next(
            (index for index in range(start + 1, len(lines)) if _HEADING.match(lines[index])),
            len(lines),
        )
        text = "\n".join(lines[start:end]).strip()
        return _found(course_dir, outline, text, start)

    for offset, block in _paragraph_blocks(lines):
        if _KEYWORDS.search("\n".join(block)):
            return _found(course_dir, outline, "\n".join(block).strip(), offset)
    return {
        "schema_version": AI_POLICY_SCHEMA_VERSION,
        "status": "not_found_in_scanned_outline",
        "text": None,
        "source": None,
    }


def _paragraph_blocks(lines: Sequence[str]) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for index, line in enumerate(lines):
        if line.strip():
            if not current:
                start = index
            current.append(line)
        elif current:
            blocks.append((start, current))
            current = []
    if current:
        blocks.append((start, current))
    return blocks


def _found(course_dir: Path, outline: Path, text: str, line: int) -> dict[str, object]:
    try:
        source = f"{outline.relative_to(course_dir).as_posix()}:{line + 1}"
    except ValueError:
        source = f"{outline.name}:{line + 1}"
    return {
        "schema_version": AI_POLICY_SCHEMA_VERSION,
        "status": "found",
        "text": text,
        "source": source,
    }


def _unavailable() -> dict[str, object]:
    return {
        "schema_version": AI_POLICY_SCHEMA_VERSION,
        "status": "outline_unavailable",
        "text": None,
        "source": None,
    }


def _write_record(course_dir: Path, record: dict[str, object], *, root: Path | None = None) -> None:
    destination = course_dir / "_meta" / "ai_policy.json"
    paths.ensure_dir(destination.parent, root=root)
    paths.atomic_write_text(
        destination,
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n",
        root=root,
    )
    _surface_index_line(course_dir, record, root=root)


def surface_course_ai_policy(
    course_dir: Path, outlines: Sequence[Path], *, root: Path | None = None
) -> dict[str, object]:
    """Record the first found clause across successful local outline renders.

    All supplied paths were successfully rendered by the outline boundary.  An empty set is
    therefore unavailable coverage; a non-empty set with no keyword is a scanned no-match.
    """
    if not outlines:
        return surface_ai_policy(course_dir, None, root=root)
    last: dict[str, object] | None = None
    for outline in sorted(outlines, key=lambda value: value.as_posix()):
        record = _scan_outline(course_dir, outline)
        if record["status"] == "found":
            _write_record(course_dir, record, root=root)
            return record
        last = record
    assert last is not None
    _write_record(course_dir, last, root=root)
    return last


def _surface_index_line(
    course_dir: Path, record: dict[str, object], *, root: Path | None = None
) -> None:
    index = course_dir / "INDEX.md"
    try:
        with open(os.fspath(paths.long_path(index)), encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return
    cleaned: list[str] = []
    index_position = 0
    while index_position < len(lines):
        if lines[index_position] == _POLICY_START:
            index_position += 1
            while index_position < len(lines) and lines[index_position] != _POLICY_END:
                index_position += 1
            index_position += 1
            continue
        if lines[index_position].strip() == "## AI policy":
            index_position += 1
            while index_position < len(lines) and not _HEADING.match(lines[index_position]):
                index_position += 1
            continue
        cleaned.append(lines[index_position])
        index_position += 1
    status = str(record["status"])
    detail = str(record["source"]) if record["source"] is not None else status
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    cleaned.extend(
        [
            "",
            _POLICY_START,
            "## AI policy",
            "",
            f"- AI policy: {status} — {detail}",
            _POLICY_END,
            "",
        ]
    )
    paths.atomic_write_text(index, "\n".join(cleaned), root=root)
