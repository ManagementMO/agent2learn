# ruff: noqa: E501
"""Deterministic, provenance-checked course navigation artifacts.

This module deliberately never downloads or converts content.  It only projects the
manifest and metadata that already exist in the local vault into a readable course
index and ``content_map.json``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from agent2learn import paths
from agent2learn.errors import A2LError
from agent2learn.vault import ManifestEntry, Vault

CONTENT_MAP_VERSION = 1
_EMPTY_HTML = re.compile(r"(?:<[^>]*>|&nbsp;|\s)+", re.IGNORECASE)
_PRESERVED_GAPS = frozenset({"unsupported_format", "integrity_gap"})


def read_content_map(course_dir: Path) -> dict[str, object]:
    """Read the small, versioned content projection for one course."""
    destination = course_dir / "_meta" / "content_map.json"
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return {"schema_version": CONTENT_MAP_VERSION, "topics": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise A2LError("content_map.json is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != CONTENT_MAP_VERSION:
        raise A2LError("content_map.json has an unsupported schema")
    topics = raw.get("topics")
    if not isinstance(topics, list):
        raise A2LError("content_map.json topics must be an array")
    return {"schema_version": CONTENT_MAP_VERSION, "topics": topics}


def write_content_map(course_dir: Path, rows: Sequence[object]) -> None:
    """Atomically write a canonical, stable-ID-sorted content map."""
    payload = {
        "schema_version": CONTENT_MAP_VERSION,
        "topics": sorted(
            (dict(row) for row in rows if isinstance(row, Mapping)),
            key=lambda row: str(row.get("source_key", "")),
        ),
    }
    _write_json(course_dir / "_meta" / "content_map.json", payload)


def reconcile_content_map(vault: Vault, rows: Sequence[object]) -> list[dict[str, object]]:
    """Resolve rows only from their stable keys and verified current manifest artifacts.

    A title and a file on disk are deliberately insufficient evidence.  The manifest key
    identifies the source, and both the materialized original and markdown twin must still hash
    to their current manifest records before a row becomes ``markdown_ready``.
    """
    manifest = vault.manifest()
    reconciled: list[dict[str, object]] = []
    for raw in sorted(
        (value for value in rows if isinstance(value, Mapping)),
        key=lambda row: str(row.get("source_key", "")),
    ):
        row = dict(raw)
        source_key = row.get("source_key")
        source_id = row.get("source_id")
        if not isinstance(source_key, str) or not isinstance(source_id, str):
            raise A2LError("content_map contains an invalid topic identity")
        if row.get("availability") == "external_link":
            row.update(
                {"source_path": None, "path": None, "next_action": "open the LEARN link manually"}
            )
            reconciled.append(row)
            continue
        entry = manifest.get(source_key)
        if entry is None:
            if row.get("availability") in _PRESERVED_GAPS:
                row.update({"source_path": None, "path": None, "next_action": "retry conversion"})
                reconciled.append(row)
                continue
            row.update(
                {
                    "availability": "metadata_only",
                    "source_path": None,
                    "path": None,
                    "next_action": f"a2l fetch {source_id}",
                }
            )
            reconciled.append(row)
            continue
        row.update(
            {
                "source_path": entry.path,
                "sha256": entry.sha256,
                "source_sha256": entry.sha256,
                "size": entry.size,
            }
        )
        if not _entry_bytes_are_current(vault, entry):
            row.update(
                {
                    "availability": "integrity_gap",
                    "path": None,
                    "next_action": "verify or re-fetch the source",
                }
            )
            reconciled.append(row)
            continue
        artifact = entry.derived.get("markdown")
        if (
            artifact is not None
            and artifact.source_sha256 == entry.sha256
            and _artifact_bytes_are_current(vault, artifact.path, artifact.sha256)
        ):
            row.update(
                {
                    "availability": "markdown_ready",
                    "path": artifact.path,
                    "next_action": "ready for citation",
                }
            )
        else:
            availability = str(row.get("availability", "source_only"))
            if availability not in _PRESERVED_GAPS:
                availability = "source_only"
            row.update(
                {
                    "availability": availability,
                    "path": None,
                    "next_action": "retry conversion"
                    if availability in _PRESERVED_GAPS
                    else "convert source to a markdown twin",
                }
            )
        reconciled.append(row)
    return reconciled


def write_course_index(
    course_dir: Path,
    *,
    course_code: str,
    course_name: str,
    term_label: str,
    term_code: str | None,
    topics: Sequence[Mapping[str, object]],
    deadlines: Sequence[tuple[str, str, str]] = (),
) -> None:
    """Write the portable, local-only course navigation surface."""
    lines = [
        f"# {course_code} — {course_name}",
        "",
        f"Term: {term_label} ({term_code or 'none'})",
        "",
        "## Deadlines",
        "",
    ]
    for date, title, kind in sorted(deadlines):
        lines.append(f"- {date} — {title} ({kind})")
    if not deadlines:
        lines.append("- No deadlines recorded.")
    lines.extend(["", "## Content", ""])
    for topic in sorted(
        topics, key=lambda row: str(row.get("source_key", row.get("source_id", "")))
    ):
        title = str(topic.get("title") or "Untitled")
        value = topic.get("path") or topic.get("source_path") or topic.get("stub_path")
        if isinstance(value, str):
            display = f"[{title}]({_course_relative_link(value, course_dir)})"
        else:
            display = f"{title} _(metadata only)_"
        module_path = topic.get("module_path")
        module_depth = (
            len([part for part in module_path if isinstance(part, str)])
            if isinstance(module_path, (list, tuple))
            else 0
        )
        indent = "  " * module_depth
        lines.append(f"{indent}- {display} — {topic.get('availability', 'metadata_only')}")
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Topics discovered: {len(topics)}",
            f"- Markdown-ready topics: {sum(row.get('availability') == 'markdown_ready' for row in topics)}",
            "",
        ]
    )
    paths.atomic_write_text(paths.long_path(course_dir / "INDEX.md"), "\n".join(lines))


def write_submission_readme(
    assignment_dir: Path, *, title: str, content_links: Sequence[tuple[str, str]]
) -> None:
    """Create the hub for a Dropbox folder with no rendered instructions.

    Only near-empty generated instruction stubs are removed; any substantive local instruction
    file remains untouched.
    """
    stub = assignment_dir / "instructions.html"
    if paths.long_path(stub).is_file():
        with open(os.fspath(paths.long_path(stub)), encoding="utf-8", newline="") as handle:
            is_substantive = bool(_EMPTY_HTML.sub("", handle.read()))
        # Windows does not allow a file to be unlinked while its read handle is open.
        if not is_substantive:
            os.unlink(os.fspath(paths.long_path(stub)))
    course_dir = assignment_dir.parent.parent
    prefix = "../" * len(assignment_dir.relative_to(course_dir).parts)
    lines = [
        f"# {title}",
        "",
        "No Dropbox instructions were published locally.",
        "",
        "## Related course content",
        "",
    ]
    if content_links:
        for topic_id, target in sorted(content_links):
            lines.append(f"- [Topic {topic_id}]({prefix}{PurePosixPath(target).as_posix()})")
    else:
        lines.append("- No matching course content recorded.")
    lines.append("")
    paths.atomic_write_text(paths.long_path(assignment_dir / "README.md"), "\n".join(lines))


def _entry_bytes_are_current(vault: Vault, entry: ManifestEntry) -> bool:
    return _hash(vault.materialized(entry)) == entry.sha256


def _artifact_bytes_are_current(vault: Vault, relative_path: str, expected_hash: str) -> bool:
    artifact = vault.root / PurePosixPath(relative_path)
    return _hash(artifact) == expected_hash


def _hash(path: Path) -> str | None:
    try:
        digest = sha256()
        with open(os.fspath(paths.long_path(path)), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None


def _course_relative_link(value: str, course_dir: Path) -> str:
    parts = list(PurePosixPath(value).parts)
    try:
        index = parts.index(course_dir.name)
    except ValueError:
        return PurePosixPath(value).as_posix()
    return PurePosixPath(*parts[index + 1 :]).as_posix() or "."


def _write_json(destination: Path, payload: object) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )
    paths.atomic_write_text(paths.long_path(destination), text)
