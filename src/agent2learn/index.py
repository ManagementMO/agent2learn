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
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, cast

from agent2learn import paths
from agent2learn.errors import A2LError
from agent2learn.vault import ManifestEntry, Vault

CONTENT_MAP_VERSION = 1
_EMPTY_HTML = re.compile(r"(?:<[^>]*>|&nbsp;|\s)+", re.IGNORECASE)
_PRESERVED_GAPS = frozenset({"unsupported_format", "conversion_gap", "integrity_gap"})
_SENSITIVE_SEARCH_MARKERS = frozenset({"grade", "grades", "discussion", "discussions"})
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class TopicMatch:
    """A redaction-safe fuzzy match from a local content map."""

    course: str
    course_code: str
    course_name: str
    term: str
    title: str
    kind: str
    source_id: str
    source_key: str
    availability: str
    path: str | None
    source_path: str | None
    stub_path: str | None
    next_action: str | None
    score: int


def search_topics(vault: Vault, query: str, *, limit: int = 20) -> tuple[TopicMatch, ...]:
    """Fuzzy-find non-sensitive topics across every term in a local vault.

    Search uses only structured ``content_map.json`` fields and returns vault-relative POSIX
    paths.  Discussion and grade rows are excluded unless a future command explicitly opts into
    those categories; this keeps a convenience search from becoming an accidental disclosure.
    """

    if not isinstance(query, str) or not query.strip():
        raise A2LError("where query must not be empty")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("where limit must be a positive integer")
    wanted = _search_tokens(query)
    matches: list[TopicMatch] = []
    for content_map in _content_maps(vault):
        course_dir = content_map.parent.parent
        raw = read_content_map(course_dir)
        topics = raw.get("topics")
        if not isinstance(topics, list):
            raise A2LError("content_map.json topics must be an array")
        for row in topics:
            if not isinstance(row, dict):
                raise A2LError("content_map.json contains an invalid topic")
            if _is_sensitive_topic(row):
                continue
            candidate = _topic_match(vault, course_dir, row, wanted)
            if candidate is not None:
                matches.append(candidate)
    matches.sort(key=lambda item: (-item.score, item.course, item.source_key))
    return tuple(matches[:limit])


def resolve_course(vault: Vault, selector: str) -> Path:
    """Resolve one course selector to a known course directory, refusing ambiguity."""

    if not isinstance(selector, str) or not selector.strip():
        raise A2LError("course selector must not be empty")
    if (
        "\\" in selector
        or _WINDOWS_ABSOLUTE.match(selector) is not None
        or Path(selector).is_absolute()
        or ".." in PurePosixPath(selector).parts
    ):
        raise A2LError("course selector must identify a local course, not a path escape")
    wanted = _normalize(selector)
    candidates: dict[Path, dict[str, str]] = {}
    for content_map in _content_maps(vault):
        course_dir = content_map.parent.parent
        raw = read_content_map(course_dir)
        topics = raw.get("topics")
        if not isinstance(topics, list):
            raise A2LError("content_map.json topics must be an array")
        metadata = candidates.setdefault(
            course_dir,
            {
                "course": paths.rel_posix(course_dir, vault.root),
                "code": course_dir.name,
                "name": course_dir.name,
                "term": course_dir.parent.name,
            },
        )
        for item in topics:
            if not isinstance(item, dict):
                continue
            for field, target in (
                ("course_code", "code"),
                ("course_name", "name"),
                ("term", "term"),
            ):
                value = item.get(field)
                if isinstance(value, str) and value:
                    metadata[target] = value

    if not candidates:
        raise A2LError("no local courses found; run: a2l sync")

    exact = [
        path
        for path, metadata in candidates.items()
        if wanted
        in {_normalize(metadata["course"]), _normalize(path.name), _normalize(metadata["code"])}
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise A2LError("course selector is ambiguous; include the term or course folder")

    scored = sorted(
        ((_selector_score(wanted, metadata), path) for path, metadata in candidates.items()),
        key=lambda item: (-item[0], paths.rel_posix(item[1], vault.root)),
    )
    if not scored or scored[0][0] == 0:
        raise A2LError("course was not found in the local vault")
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise A2LError("course selector is ambiguous; include the term or course folder")
    return scored[0][1]


def _content_maps(vault: Vault) -> tuple[Path, ...]:
    if not paths.long_path(vault.root).is_dir():
        raise A2LError("vault is unavailable; run: a2l init")
    try:
        result = []
        for candidate in paths.walk(vault.root):
            if candidate.name != "content_map.json":
                continue
            if paths.is_link(candidate):
                raise A2LError("content_map.json must not be a symlink")
            if ".a2l" in candidate.parts:
                continue
            result.append(candidate)
        return tuple(sorted(result, key=lambda value: paths.rel_posix(value, vault.root)))
    except OSError as exc:
        raise A2LError("content map inventory is unreadable") from exc


def _topic_match(
    vault: Vault,
    course_dir: Path,
    row: dict[str, object],
    wanted: tuple[str, ...],
) -> TopicMatch | None:
    fields: dict[str, str] = {}
    for key in (
        "title",
        "kind",
        "source_id",
        "source_key",
        "course_code",
        "course_name",
        "term",
        "module_path",
    ):
        value = row.get(key)
        if isinstance(value, str):
            fields[key] = value
        elif isinstance(value, (list, tuple)):
            fields[key] = " ".join(str(item) for item in value)
    haystack = _normalize(" ".join(fields.values()))
    if not all(token in haystack for token in wanted):
        return None
    title = fields.get("title") or "Untitled"
    exact_title = _normalize(title) == _normalize(" ".join(wanted))
    score = 100 if exact_title else 0
    for token in wanted:
        if token in _normalize(title):
            score += 20
        elif token in _normalize(fields.get("source_key", "")):
            score += 10
        else:
            score += 1
    return TopicMatch(
        course=paths.rel_posix(course_dir, vault.root),
        course_code=fields.get("course_code", course_dir.name),
        course_name=fields.get("course_name", course_dir.name),
        term=fields.get("term", course_dir.parent.name),
        title=title,
        kind=fields.get("kind", "topic"),
        source_id=fields["source_id"],
        source_key=fields["source_key"],
        availability=str(row.get("availability", "metadata_only")),
        path=_safe_result_path(row.get("path")),
        source_path=_safe_result_path(row.get("source_path")),
        stub_path=_safe_result_path(row.get("stub_path")),
        next_action=cast(str, row["next_action"])
        if isinstance(row.get("next_action"), str)
        else None,
        score=score,
    )


def _is_sensitive_topic(row: Mapping[str, object]) -> bool:
    values: list[str] = []
    for key in ("kind", "source_key", "path", "source_path", "stub_path"):
        value = row.get(key)
        if isinstance(value, str):
            values.append(_normalize(value))
    return any(
        any(
            marker in value.split(":") or marker in value.split("/")
            for marker in _SENSITIVE_SEARCH_MARKERS
        )
        for value in values
    )


def _safe_result_path(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or _WINDOWS_ABSOLUTE.match(value) is not None
    ):
        raise A2LError("content map contains an invalid result path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise A2LError("content map result path escapes the vault")
    return candidate.as_posix()


def _search_tokens(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalize(token) for token in value.split() if token.strip()))


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _selector_score(wanted: str, metadata: Mapping[str, str]) -> int:
    return max(
        (50 if wanted in _normalize(value) else 0) + (20 if _normalize(value) == wanted else 0)
        for value in metadata.values()
    )


def read_content_map(course_dir: Path) -> dict[str, object]:
    """Read the small, versioned content projection for one course."""
    destination = course_dir / "_meta" / "content_map.json"
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return {"schema_version": CONTENT_MAP_VERSION, "topics": []}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A2LError("content_map.json is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != CONTENT_MAP_VERSION:
        raise A2LError("content_map.json has an unsupported schema")
    topics = raw.get("topics")
    if not isinstance(topics, list):
        raise A2LError("content_map.json topics must be an array")
    validated: list[dict[str, object]] = []
    for topic in topics:
        if not isinstance(topic, Mapping):
            raise A2LError("content_map.json contains an invalid topic")
        row = dict(topic)
        _validate_topic_identity(row)
        validated.append(row)
    return {"schema_version": CONTENT_MAP_VERSION, "topics": validated}


def write_content_map(
    course_dir: Path, rows: Sequence[object], *, root: Path | None = None
) -> None:
    """Atomically write a canonical, stable-ID-sorted content map."""
    validated: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise A2LError("content_map contains an invalid topic")
        value = dict(row)
        _validate_topic_identity(value)
        validated.append(value)
    payload = {
        "schema_version": CONTENT_MAP_VERSION,
        "topics": sorted(
            validated,
            key=lambda row: str(row.get("source_key", "")),
        ),
    }
    _write_json(course_dir / "_meta" / "content_map.json", payload, root=root)


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
        _validate_topic_identity(row)
        source_key = row["source_key"]
        source_id = row["source_id"]
        assert isinstance(source_key, str)
        assert isinstance(source_id, str)
        if row.get("availability") == "external_link":
            row.update(
                {"source_path": None, "path": None, "next_action": "open the LEARN link manually"}
            )
            reconciled.append(row)
            continue
        entry = manifest.get(source_key)
        if entry is None:
            # Every source-backed gap needs a manifest entry as its proof. Without that proof,
            # including for conversion/integrity/format gaps, this row is metadata again and must
            # offer fetch rather than a conversion-only or integrity-only action. A download gap
            # is the one exception: it records that the server never served the source, so the
            # row must keep the gap and its retry action instead of pretending it was never
            # attempted.
            if row.get("availability") == "download_gap":
                next_action = row.get("next_action")
                row.update(
                    {
                        "source_path": None,
                        "path": None,
                        "next_action": next_action
                        if isinstance(next_action, str) and next_action
                        else f"a2l fetch {source_id}",
                    }
                )
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
        # A manifest entry for an older remote revision is not evidence that the current
        # revision was served. While the recorded validators disagree with the entry, the
        # download gap stands and the stale twin must not be promoted to citation evidence.
        if row.get("availability") == "download_gap" and not _entry_matches_row_validators(
            row, entry
        ):
            next_action = row.get("next_action")
            row.update(
                {
                    "path": None,
                    "next_action": next_action
                    if isinstance(next_action, str) and next_action
                    else f"a2l fetch {source_id}",
                }
            )
            reconciled.append(row)
            continue
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
                next_action = "convert source to a markdown twin"
            else:
                stored_action = row.get("next_action")
                next_action = (
                    stored_action
                    if isinstance(stored_action, str) and stored_action
                    else "retry conversion"
                )
            row.update(
                {
                    "availability": availability,
                    "path": None,
                    "next_action": next_action,
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
    root: Path | None = None,
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
    paths.atomic_write_text(course_dir / "INDEX.md", "\n".join(lines), root=root)


def write_submission_readme(
    assignment_dir: Path,
    *,
    title: str,
    content_links: Sequence[tuple[str, str]],
    root: Path | None = None,
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
    paths.atomic_write_text(assignment_dir / "README.md", "\n".join(lines), root=root)


def _entry_bytes_are_current(vault: Vault, entry: ManifestEntry) -> bool:
    return _hash(vault.materialized(entry)) == entry.sha256


def _entry_matches_row_validators(row: Mapping[str, object], entry: ManifestEntry) -> bool:
    """Whether a manifest entry still represents the revision the metadata row describes."""
    etag = row.get("etag")
    if isinstance(etag, str) and etag and entry.etag != etag:
        return False
    last_modified = row.get("last_modified")
    return not (
        isinstance(last_modified, str) and last_modified and entry.last_modified != last_modified
    )


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


def _write_json(destination: Path, payload: object, *, root: Path | None = None) -> None:
    paths.ensure_dir(destination.parent, root=root)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )
    paths.atomic_write_text(destination, text, root=root)


def _validate_topic_identity(row: Mapping[str, object]) -> None:
    source_key = row.get("source_key")
    source_id = row.get("source_id")
    if (
        not isinstance(source_key, str)
        or not source_key
        or not isinstance(source_id, str)
        or not source_id
        or source_key.rsplit(":", 1)[-1] != source_id
    ):
        raise A2LError("content_map contains an invalid topic identity")


__all__ = [
    "CONTENT_MAP_VERSION",
    "TopicMatch",
    "read_content_map",
    "reconcile_content_map",
    "resolve_course",
    "search_topics",
    "write_content_map",
    "write_course_index",
    "write_submission_readme",
]
