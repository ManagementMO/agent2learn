"""Structural coverage audit over what the vault actually holds.

The audit answers one question honestly: *what is missing, and why?*  It never guesses that
coverage is complete, never treats a title match as proof, and never reports a number it
cannot substantiate from the manifest and the reconciled content map.

Its most important output is the part users dislike: assignments with no matching course
content, conversion gaps, integrity gaps, and links that were deliberately not fetched.  A
report that only counted successes would let a silent ingest failure look like a finished
archive.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from agent2learn import clock, paths
from agent2learn import index as course_index
from agent2learn.vault import Vault

AUDIT_VERSION = 1

_MEDIA_EXTENSIONS = frozenset(
    {".mp3", ".mp4", ".m4a", ".m4v", ".mov", ".avi", ".wav", ".webm", ".mkv", ".flv"}
)
_CITABLE = "markdown_ready"
_GAP_LABELS: dict[str, str] = {
    "metadata_only": "known but not fetched",
    "source_only": "fetched, no markdown twin",
    "unsupported_format": "no converter for this format",
    "conversion_gap": "fetched, but conversion produced no markdown twin",
    "integrity_gap": "on-disk bytes do not match the manifest",
    "download_gap": "the server did not serve this file; retry the fetch",
    "external_link": "external link, deliberately not fetched",
}
# Tokens that appear in nearly every coursework title and so carry no matching signal.
# Shared in spirit with ground.py's GENERIC set; kept local because changing one must not
# silently change the other's scoring.
_GENERIC = frozenset(
    {
        "a", "an", "and", "activity", "assignment", "class", "copy", "for", "home", "in",
        "lab", "of", "part", "solution", "take", "the", "to", "week",
    }
)  # fmt: skip


@dataclass(frozen=True)
class AssignmentMatch:
    """One assignment and the single best content guess, always labelled as a guess."""

    title: str
    due_date: str | None
    best_match: str | None
    overlap: int


@dataclass(frozen=True)
class CourseAudit:
    """Everything the report says about one course, computed from local evidence only."""

    course: str
    code: str
    name: str
    topics: int
    citable: int
    coverage: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    media: int = 0
    quizzes: int = 0
    quizzes_with_due_dates: int = 0
    assignments: int = 0
    metadata_gaps: tuple[str, ...] = ()
    unmatched_assignments: tuple[AssignmentMatch, ...] = ()

    @property
    def coverage_percent(self) -> int:
        """Citable share, floored so a partial archive never rounds up to 100%."""
        if self.topics == 0:
            return 0
        return int(self.citable * 100 // self.topics)


def audit_vault(vault: Vault) -> list[CourseAudit]:
    """Compute a per-course structural audit from the manifest and content maps."""
    results: list[CourseAudit] = []
    for map_path in sorted(
        path for path in paths.walk(vault.root) if path.name == "content_map.json"
    ):
        course_dir = map_path.parent.parent
        rows = course_index.read_content_map(course_dir)["topics"]
        if not isinstance(rows, list):
            continue
        results.append(_audit_course(vault, course_dir, rows))
    return results


def write_audit(vault: Vault, *, timestamp: str | None = None) -> Path:
    """Write ``.a2l/AUDIT.md`` and return its path."""
    audits = audit_vault(vault)
    stamp = timestamp if timestamp is not None else clock.stamp()
    destination = vault.state() / "AUDIT.md"
    paths.atomic_write_text(destination, _render(audits, stamp), root=vault.root)
    return destination


def _audit_course(vault: Vault, course_dir: Path, rows: Sequence[object]) -> CourseAudit:
    coverage: Counter[str] = Counter()
    links: Counter[str] = Counter()
    media = 0
    citable = 0
    topics = 0
    titles: list[tuple[str, set[str]]] = []

    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        topics += 1
        availability = str(raw.get("availability", "metadata_only"))
        coverage[availability] += 1
        if availability == _CITABLE:
            citable += 1
        if availability == "external_link":
            links[_link_kind(raw)] += 1
        if _is_media(raw):
            media += 1
        title = str(raw.get("title") or "")
        if title:
            titles.append((title, _terms(title)))

    assignments, assignments_gap = _read_json_list(course_dir / "_meta" / "assignments.json")
    quizzes, quizzes_gap = _read_json_list(course_dir / "_meta" / "quizzes.json")
    unmatched = _unmatched_assignments(assignments, titles)
    metadata_gaps = tuple(gap for gap in (assignments_gap, quizzes_gap) if gap is not None)

    first = next((row for row in rows if isinstance(row, Mapping)), {})
    return CourseAudit(
        course=paths.rel_posix(course_dir, vault.root),
        code=str(first.get("course_code") or course_dir.name),
        name=str(first.get("course_name") or course_dir.name),
        topics=topics,
        citable=citable,
        coverage=dict(sorted(coverage.items())),
        links=dict(sorted(links.items())),
        media=media,
        quizzes=len(quizzes),
        quizzes_with_due_dates=sum(1 for row in quizzes if row.get("due_date")),
        assignments=len(assignments),
        metadata_gaps=metadata_gaps,
        unmatched_assignments=unmatched,
    )


def _unmatched_assignments(
    assignments: Sequence[Mapping[str, object]], titles: Sequence[tuple[str, set[str]]]
) -> tuple[AssignmentMatch, ...]:
    """Return assignments sharing no distinguishing term with any topic in the course.

    This is deliberately a weak, lexical signal, and it is reported as a prompt to look
    rather than as a finding.  An assignment with no overlap usually means the brief lives
    somewhere the API does not expose — a quiz description, an announcement, or a slide.
    The best-overlapping title is carried along so the student has somewhere to start.
    """
    unmatched: list[AssignmentMatch] = []
    for row in assignments:
        title = str(row.get("title") or "")
        wanted = _terms(title)
        if not wanted:
            continue
        # Highest overlap wins; ties break on the title so the report is stable everywhere.
        ranked = sorted(
            ((len(wanted & terms), candidate) for candidate, terms in titles),
            key=lambda pair: (-pair[0], pair[1]),
        )
        best_overlap, best_title = ranked[0] if ranked else (0, None)
        if best_overlap == 0:
            unmatched.append(
                AssignmentMatch(
                    title=title,
                    due_date=_optional_text(row.get("due_date")),
                    best_match=best_title,
                    overlap=0,
                )
            )
    return tuple(sorted(unmatched, key=lambda item: (item.due_date or "", item.title)))


def _terms(value: str) -> set[str]:
    """Tokenise a title into distinguishing terms, dropping generic coursework words."""
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", value.casefold()):
        if len(word) > 1 or word.isdigit():
            tokens.add(word)
        parts = re.findall(r"[a-z]+|[0-9]+", word)
        if len(parts) > 1:
            tokens.update(part for part in parts if len(part) > 1 or part.isdigit())
    return tokens - _GENERIC


def _link_kind(row: Mapping[str, object]) -> str:
    kind = str(row.get("kind") or "").casefold()
    if kind in {"lti", "externallink", "link"}:
        return {"lti": "LTI tool", "externallink": "external link", "link": "external link"}[kind]
    return kind or "unknown"


def _is_media(row: Mapping[str, object]) -> bool:
    candidate = str(row.get("source_path") or row.get("url_path") or "")
    return _suffix(candidate) in _MEDIA_EXTENSIONS


def _suffix(value: str) -> str:
    _, _, tail = value.rpartition("/")
    _, dot, extension = tail.rpartition(".")
    return f".{extension.casefold()}" if dot else ""


def _read_json_list(destination: Path) -> tuple[list[Mapping[str, object]], str | None]:
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return [], None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], f"{destination.name} is unreadable"
    if not isinstance(raw, list):
        return [], f"{destination.name} has an invalid root"
    rows = [row for row in raw if isinstance(row, Mapping)]
    if len(rows) != len(raw):
        return rows, f"{destination.name} contains invalid item(s)"
    return rows, None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural or singular + 's'}"


def _render(audits: Sequence[CourseAudit], stamp: str) -> str:
    lines = [
        "# Coverage audit",
        "",
        f"Generated {stamp} · audit schema {AUDIT_VERSION}",
        "",
        "This report describes only what is in this vault. A gap here means the material was "
        "not retrievable through the API, not that it does not exist in the course.",
        "",
    ]

    if not audits:
        lines.extend(["No courses have been ingested yet. Run `a2l sync` to begin.", ""])
        return "\n".join(lines)

    lines.extend(
        ["## Summary", "", "| Course | Citable | Topics | Coverage |", "| --- | --- | --- | --- |"]
    )
    for audit in audits:
        lines.append(
            f"| {audit.code} | {audit.citable} | {audit.topics} | {audit.coverage_percent}% |"
        )
    lines.append("")

    for audit in audits:
        lines.extend([f"## {audit.code} — {audit.name}", ""])
        lines.append(
            f"{audit.citable} of {audit.topics} topics are citable ({audit.coverage_percent}%)."
        )
        lines.append("")

        gaps = [(state, count) for state, count in audit.coverage.items() if state != _CITABLE]
        if gaps:
            lines.extend(["### Gaps", "", "| State | Count | Meaning |", "| --- | --- | --- |"])
            for state, count in gaps:
                lines.append(f"| `{state}` | {count} | {_GAP_LABELS.get(state, 'unclassified')} |")
            lines.append("")

        if audit.metadata_gaps:
            lines.extend(
                [
                    "### Metadata gaps",
                    "",
                    "The local metadata projection could not be read completely; inventory "
                    "counts below may be incomplete.",
                    "",
                    *[f"- {gap}" for gap in audit.metadata_gaps],
                    "",
                ]
            )

        if audit.links:
            lines.extend(["### Links not fetched", "", "| Kind | Count |", "| --- | --- |"])
            for kind, count in audit.links.items():
                lines.append(f"| {kind} | {count} |")
            lines.extend(
                ["", "These are external or licensed targets. Open them in LEARN directly.", ""]
            )

        counts = [
            f"- {_plural(audit.assignments, 'assignment')}",
            f"- {_plural(audit.quizzes, 'quiz', 'quizzes')}"
            f" ({audit.quizzes_with_due_dates} with due dates)",
            f"- {_plural(audit.media, 'media file')}",
        ]
        lines.extend(["### Inventory", "", *counts, ""])

        if audit.unmatched_assignments:
            lines.extend(
                [
                    "### Assignments with no matching content",
                    "",
                    "No topic in this course shares a distinguishing term with these "
                    "assignments. The brief may have been posted somewhere the API does not "
                    "expose, such as a quiz description or an announcement.",
                    "",
                    "| Assignment | Due |",
                    "| --- | --- |",
                ]
            )
            for item in audit.unmatched_assignments:
                lines.append(f"| {item.title} | {item.due_date or '—'} |")
            lines.append("")

    return "\n".join(lines)


__all__ = ["AUDIT_VERSION", "AssignmentMatch", "CourseAudit", "audit_vault", "write_audit"]
