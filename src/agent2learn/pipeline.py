"""Typed production orchestration for metadata-first vault synchronization.

The public sync command and golden-vault harness share this sequence; onboarding can adopt the same
entry point in its dedicated integration task. Metadata is completed and exposed to an optional
observer before any browser or file work begins, and later phases use that stable local projection.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

from agent2learn import aipolicy, clock, paths
from agent2learn.api import Client
from agent2learn.audit import write_audit
from agent2learn.convert import DEFAULT_OCR_WORDS_PER_PAGE, ConversionReport, convert_vault
from agent2learn.errors import AuthenticationError
from agent2learn.index import read_content_map, reconcile_content_map, write_content_map
from agent2learn.ingest import (
    FileReport,
    MetadataReport,
    OutlineReport,
    _topic_from_row,
    _write_index,
    ingest_files,
    ingest_metadata,
)
from agent2learn.outlines import (
    OutlineBrowserFactory,
    dedicated_profile_outline_factory,
    ingest_outlines,
)
from agent2learn.schools import School
from agent2learn.snapshot import write_snapshot
from agent2learn.vault import Vault

SyncScope = Literal["all", "priority"]
MetadataObserver = Callable[[MetadataReport], None]
DEFAULT_SYNC_SCOPE: SyncScope = "all"
_INIT_STATE_SCHEMA = 1


@dataclass(frozen=True)
class SyncPreferences:
    """Validated initializer choices that a later unflagged sync may reuse."""

    scope: SyncScope = DEFAULT_SYNC_SCOPE
    term: str | None = None
    only: tuple[int, ...] | None = None
    profile_consent: bool | None = None


class _UnavailableOutlineFactory:
    """Record discovered outlines as unavailable without opening a declined browser profile."""

    def open_browser(self) -> NoReturn:
        raise AuthenticationError("dedicated outline profile is not enabled")

    def close(self) -> None:
        return


@dataclass(frozen=True)
class PipelineReport:
    """Deterministic, privacy-bounded result of one production synchronization pass."""

    scope: SyncScope
    include_media: bool
    include_grades: bool
    include_discussions: bool
    metadata: MetadataReport
    outlines: OutlineReport
    files: FileReport
    conversion: ConversionReport
    indexed_courses: int
    snapshot_path: str
    audit_path: str
    errors: tuple[str, ...] = ()
    exit_code: int = 0


def load_sync_preferences(
    vault: Vault, *, scope_override: SyncScope | None = None
) -> SyncPreferences:
    """Read validated init choices without letting corrupt state broaden a course selection.

    ``later`` describes an onboarding deferral, not a reusable file-transfer scope.  When the user
    later invokes ``a2l sync`` without an override, it therefore falls back to the design's
    recommended full document archive (``all``), still excluding media unless separately enabled.
    A missing state file supports pre-initializer vaults; an existing invalid file fails closed.
    """

    fallback_scope = scope_override or DEFAULT_SYNC_SCOPE
    if fallback_scope not in {"all", "priority"}:
        raise ValueError("scope override must be 'all' or 'priority'")
    destination = vault.state() / "init.json"
    if paths.is_link(destination):
        raise ValueError("saved sync preferences must not be a symlink")
    try:
        exists = paths.long_path(destination).exists()
        is_file = paths.long_path(destination).is_file()
    except OSError as exc:
        raise ValueError("saved sync preferences are unavailable") from exc
    if not exists:
        return SyncPreferences(scope=fallback_scope)
    if not is_file:
        raise ValueError("saved sync preferences are not a regular file")
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("saved sync preferences are unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("saved sync preferences must be an object")
    schema_version = raw.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != _INIT_STATE_SCHEMA:
        raise ValueError("saved sync preferences use an unsupported schema")

    stored_scope = raw.get("file_scope")
    if stored_scope not in (None, "full", "priority", "later"):
        raise ValueError("saved sync preferences have an invalid file scope")
    if scope_override is not None:
        scope = scope_override
    elif stored_scope == "priority":
        scope = "priority"
    else:
        scope = DEFAULT_SYNC_SCOPE

    term_value = raw.get("term")
    if term_value is not None and (not isinstance(term_value, str) or not term_value):
        raise ValueError("saved sync preferences have an invalid term")
    term = term_value

    offering_value = raw.get("selected_offering_ids")
    only = _offering_ids(offering_value)
    if offering_value is not None and only is None:
        raise ValueError("saved sync preferences have invalid offering IDs")

    consent_value = raw.get("profile_consent")
    if consent_value is not None and not isinstance(consent_value, bool):
        raise ValueError("saved sync preferences have invalid profile consent")
    profile_consent = consent_value
    return SyncPreferences(scope=scope, term=term, only=only, profile_consent=profile_consent)


def run_pipeline(
    client: Client,
    vault: Vault,
    school: School,
    *,
    scope: SyncScope = DEFAULT_SYNC_SCOPE,
    include_media: bool = False,
    include_grades: bool = False,
    include_discussions: bool = False,
    ocr_words_per_page: int = DEFAULT_OCR_WORDS_PER_PAGE,
    term: str | None = None,
    only: Iterable[int | str] | None = None,
    metadata_observer: MetadataObserver | None = None,
    outline_factory: OutlineBrowserFactory | None = None,
    profile_consent: bool | None = None,
    render_outlines: bool = True,
    rebuild_indexes: bool = True,
) -> PipelineReport:
    """Run the single metadata → outlines → files → local-artifact production sequence."""

    if scope not in {"all", "priority"}:
        raise ValueError("scope must be 'all' or 'priority'")
    if profile_consent is not None and not isinstance(profile_consent, bool):
        raise ValueError("profile_consent must be a boolean or None")
    selection = tuple(only) if only is not None else None
    metadata = ingest_metadata(
        client,
        vault,
        school,
        term=term,
        only=selection,
        include_grades=include_grades,
        create_snapshot=False,
    )
    if metadata_observer is not None:
        metadata_observer(metadata)

    outlines = OutlineReport()
    files = FileReport()
    conversion = ConversionReport()
    metadata_complete = not metadata.errors and metadata.exit_code == 0
    if metadata_complete:
        if render_outlines:
            if profile_consent is False:
                factory: OutlineBrowserFactory = _UnavailableOutlineFactory()
            else:
                factory = outline_factory or dedicated_profile_outline_factory()
            outlines = ingest_outlines(factory, vault, school, metadata)
        files = ingest_files(
            client,
            vault,
            school,
            term=term,
            only=selection,
            scope=scope,
            include_media=include_media,
            include_discussions=include_discussions,
        )
        # This is intentionally unconditional: already-local sources still need conversion after
        # an interrupted, deferred, priority, or fully unchanged download pass.
        conversion = convert_vault(vault, ocr_words_per_page=ocr_words_per_page)

    indexed_courses = refresh_indexes(vault, school, metadata) if rebuild_indexes else 0
    timestamp = clock.stamp()
    course_dirs = tuple(course.directory for course in metadata.courses)
    snapshot_path = write_snapshot(
        vault,
        course_dirs,
        include_grades=include_grades,
        timestamp=timestamp,
    )
    audit_path = write_audit(vault, timestamp=timestamp)
    errors, exit_code = _result_status(metadata, outlines, files, conversion)
    return PipelineReport(
        scope=scope,
        include_media=include_media,
        include_grades=include_grades,
        include_discussions=include_discussions,
        metadata=metadata,
        outlines=outlines,
        files=files,
        conversion=conversion,
        indexed_courses=indexed_courses,
        snapshot_path=paths.rel_posix(snapshot_path, vault.root),
        audit_path=paths.rel_posix(audit_path, vault.root),
        errors=errors,
        exit_code=exit_code,
    )


def refresh_indexes(vault: Vault, school: School, metadata: MetadataReport) -> int:
    """Reconcile every selected content map and rebuild its index from current trusted state."""

    refreshed = 0
    for course_metadata in sorted(
        metadata.courses,
        key=lambda value: paths.rel_posix(value.directory, vault.root),
    ):
        payload = read_content_map(course_metadata.directory)
        raw_rows = payload.get("topics")
        if not isinstance(raw_rows, list):
            raise ValueError("content map topics must be a list")
        rows = reconcile_content_map(vault, raw_rows)
        write_content_map(course_metadata.directory, rows)
        topics = tuple(
            _topic_from_row(row, course=course_metadata.course)
            for row in rows
            if isinstance(row, Mapping)
        )
        _write_index(
            course_metadata.directory,
            school=school,
            course=course_metadata.course,
            topics=topics,
        )
        _restore_ai_policy_line(course_metadata.directory)
        refreshed += 1
    return refreshed


def render_report(report: PipelineReport) -> str:
    """Render stable terminal counts without echoing course names, IDs, paths, or source errors."""

    lines = [
        (
            f"metadata · {len(report.metadata.courses)} courses · "
            f"{report.metadata.topic_count} topics · {report.metadata.deadline_count} deadlines"
        ),
        (
            f"outlines · {report.outlines.rendered} rendered · "
            f"{report.outlines.unavailable} unavailable"
        ),
        (
            f"files · {report.files.downloaded} downloaded · {report.files.skipped} skipped · "
            f"{report.files.metadata_only} metadata only"
        ),
        (
            f"conversion · {report.conversion.converted} converted · "
            f"{report.conversion.skipped} current · {report.conversion.gaps} gaps"
        ),
        f"index · {report.indexed_courses} courses",
        f"audit · {report.audit_path}",
    ]
    if report.errors:
        lines.append("sync completed with gaps · " + ", ".join(report.errors))
    else:
        lines.append("sync complete")
    return "\n".join(lines) + "\n"


def _offering_ids(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, list):
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(cast(list[int], value))


def _restore_ai_policy_line(course_dir: Path) -> None:
    destination = course_dir / "_meta" / "ai_policy.json"
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("AI-policy metadata is unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("AI-policy metadata has an invalid root")
    status = raw.get("status")
    if status not in {"found", "not_found_in_scanned_outline", "outline_unavailable"}:
        raise ValueError("AI-policy metadata has an invalid status")
    aipolicy._surface_index_line(course_dir, cast(dict[str, object], raw))


def _result_status(
    metadata: MetadataReport,
    outlines: OutlineReport,
    files: FileReport,
    conversion: ConversionReport,
) -> tuple[tuple[str, ...], int]:
    errors: list[str] = []
    if metadata.errors or metadata.exit_code:
        errors.append("metadata incomplete")
    if outlines.unavailable or outlines.errors:
        errors.append("outline unavailable")
    if files.failed or files.errors or files.exit_code:
        errors.append("file sync incomplete")
    if conversion.errors:
        errors.append("conversion incomplete")
    if files.interrupted or files.exit_code == 130:
        return tuple(errors), 130
    if metadata.exit_code:
        return tuple(errors), metadata.exit_code
    if files.exit_code:
        return tuple(errors), files.exit_code
    return tuple(errors), 1 if errors else 0


__all__ = [
    "DEFAULT_SYNC_SCOPE",
    "MetadataObserver",
    "PipelineReport",
    "SyncPreferences",
    "SyncScope",
    "load_sync_preferences",
    "refresh_indexes",
    "render_report",
    "run_pipeline",
]
