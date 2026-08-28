"""Metadata-first, revision-safe ingestion of a LEARN course vault.

The module deliberately separates the inexpensive JSON phase from the potentially large file
phase.  Metadata is a typed projection of the API, not a raw response archive: external URLs are
classified before persistence, and only a query-free LEARN view URL plus a destination hostname
can survive as a link stub.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlsplit, urlunsplit

from requests import RequestException

from agent2learn import api, clock, paths, snapshot
from agent2learn import index as course_index
from agent2learn.api import Client, DownloadError, DownloadResult
from agent2learn.calibrate import CourseRef, calibrate, load_calibration
from agent2learn.errors import A2LError, NotConfigured, SessionExpired
from agent2learn.schools import (
    School,
    hostname_matches_suffix,
    parse_api_timestamp,
    topic_is_excluded,
)
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

CONTENT_MAP_VERSION = course_index.CONTENT_MAP_VERSION
DEFAULT_SCOPE: Literal["all", "priority"] = "all"
_MAX_PAGES = 1000
_COURSE_CONTENT = "content"
_OFFICE_LOCK = re.compile(r"^~\$", re.IGNORECASE)
_MEDIA_SUFFIXES = frozenset(
    {
        ".3gp",
        ".aac",
        ".avi",
        ".flac",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".wav",
        ".webm",
        ".wmv",
    }
)
_DOWNLOADABLE_KINDS = frozenset({"file", "html", "htmlfile"})
_PENDING_MARKER_SUFFIX = ".meta.json"
_PENDING_INSTALL_SUFFIX = ".part" + _PENDING_MARKER_SUFFIX
_PENDING_INSTALL_KEYS = frozenset(
    {
        "version",
        "source_key",
        "destination",
        "sha256",
        "size",
        "etag",
        "last_modified",
        "prior_sha256",
        "revision_preserved",
    }
)


@dataclass(frozen=True)
class TopicRecord:
    """The safe, typed projection of one content topic."""

    source_key: str
    source_id: str
    topic_id: int
    course_org_unit_id: int
    course_code: str
    course_name: str
    term: str | None
    title: str
    kind: str
    module_path: tuple[str, ...]
    module_ids: tuple[int, ...]
    view_url: str
    outline_url: str | None
    url_path: str | None
    external_host: str | None
    etag: str | None
    last_modified: str | None
    is_broken: bool
    availability: str = "metadata_only"
    source_path: str | None = None
    path: str | None = None
    sha256: str | None = None
    size: int | None = None
    stub_path: str | None = None
    remote_size: int | None = None
    next_action: str = "a2l fetch <topic-id>"
    missing_since: str | None = None
    withdrawn_at: str | None = None


@dataclass(frozen=True)
class CourseMetadata:
    """Metadata and safe content projections for one selected course."""

    course: CourseRef
    directory: Path
    topics: tuple[TopicRecord, ...]
    module_tree: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class MetadataReport:
    """Result of the complete cheap metadata phase."""

    courses: tuple[CourseMetadata, ...]
    topic_count: int
    deadline_count: int
    errors: tuple[str, ...] = ()
    exit_code: int = 0


@dataclass(frozen=True)
class FileReport:
    """Result of a resumable source-file phase."""

    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    metadata_only: int = 0
    interrupted: bool = False
    errors: tuple[str, ...] = ()
    exit_code: int = 0


@dataclass(frozen=True)
class FetchReport:
    """Result of resolving and fetching one stable topic identity."""

    source_key: str
    availability: str
    source_path: str | None
    citation_path: str | None
    changed: bool


@dataclass(frozen=True)
class OutlineReport:
    """The outline renderer's bounded result; implemented in :mod:`outlines`."""

    rendered: int = 0
    unavailable: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PendingInstall:
    """Durable proof that a validated download is waiting only on filesystem installation."""

    marker: Path
    part: Path
    source_key: str
    destination: str
    sha256: str
    size: int
    etag: str | None
    last_modified: str | None
    prior_sha256: str | None
    revision_preserved: bool


def ingest_metadata(
    client: Client,
    vault: Vault,
    school: School,
    *,
    term: str | None = None,
    only: Iterable[int | str] | None = None,
    include_grades: bool = False,
    create_snapshot: bool = True,
) -> MetadataReport:
    """Fetch and persist complete typed metadata for the selected courses.

    No file endpoint is touched here. The function is safe to call before the user chooses a file
    scope, and every category writer merges stable IDs rather than deleting expired records. Direct
    callers retain the historical metadata snapshot by default; the production pipeline disables
    that interim write and creates its single snapshot after conversion and index reconciliation.
    """

    courses = _selected_courses(client, term=term, only=only)
    reports: list[CourseMetadata] = []
    errors: list[str] = []
    deadline_count = 0

    for course in courses:
        course_dir = _course_directory(vault, school, course)
        paths.long_path(course_dir).mkdir(parents=True, exist_ok=True)
        try:
            toc_payload, toc_complete, toc_error = _fetch_one(client, _toc_path(client, course))
            if toc_error is not None:
                errors.append(_safe_error("toc", toc_error))
            records, module_tree, toc_valid = _topics_from_toc(
                toc_payload, course=course, school=school
            )
            toc_complete = toc_complete and toc_valid
        except SessionExpired:
            raise
        except Exception as exc:
            errors.append(_safe_error("toc", exc))
            records, module_tree, toc_complete = [], [], False

        assignments, assignments_complete, assignments_error = _fetch_collection(
            client, _endpoint_path(client, course, "dropbox/folders/")
        )
        if assignments_error is not None:
            errors.append(_safe_error("assignments", assignments_error))
        existing_map = _read_content_map(course_dir)
        attachment_topics = _assignment_attachment_topics(assignments, course=course, school=school)
        merged_topics = _merge_topic_records(
            existing_map.get("topics", []),
            [*records, *attachment_topics],
            # Attachment identities come from Dropbox as well as the TOC.  A failure in either
            # listing must not mark a previously captured source absent.
            complete=toc_complete and assignments_complete,
        )
        merged_topics = _materialize_external_stubs(
            merged_topics, course_dir=course_dir, vault=vault, school=school, course=course
        )

        if toc_complete:
            _write_toc(course_dir, module_tree)
        else:
            try:
                module_tree = _read_toc_modules(course_dir)
            except A2LError as exc:
                # A failed TOC fetch must not turn a corrupt cached tree into an apparently empty
                # course.  Keep the metadata phase usable, but make the coverage gap explicit.
                errors.append(_safe_error("toc cache", exc))
                module_tree = []

        assignments_rows = _project_assignments(assignments)
        assignments_rows = _merge_rows(
            _read_list(course_dir / "_meta" / "assignments.json"),
            assignments_rows,
            id_field="id",
            complete=assignments_complete,
        )
        assignment_artifacts = _materialize_assignments(
            assignments, course_dir=course_dir, vault=vault, school=school, course=course
        )
        for row in assignments_rows:
            artifact = assignment_artifacts.get(str(row.get("id")))
            if artifact is not None:
                row.update(artifact)
        _write_list(course_dir / "_meta" / "assignments.json", assignments_rows)

        news, news_complete, news_error = _fetch_collection(
            client, _endpoint_path(client, course, "news/")
        )
        if news_error is not None:
            errors.append(_safe_error("news", news_error))
        news_rows = _project_news(news)
        news_rows = _merge_rows(
            _read_list(course_dir / "_meta" / "news.json"),
            news_rows,
            id_field="id",
            complete=news_complete,
        )
        _write_list(course_dir / "_meta" / "news.json", news_rows)
        _write_announcements(course_dir / "announcements" / "announcements.md", news_rows)

        quizzes, quizzes_complete, quizzes_error = _fetch_collection(
            client, _endpoint_path(client, course, "quizzes/")
        )
        if quizzes_error is not None:
            errors.append(_safe_error("quizzes", quizzes_error))
        quiz_rows = _project_quizzes(quizzes)
        quiz_rows = _merge_rows(
            _read_list(course_dir / "_meta" / "quizzes.json"),
            quiz_rows,
            id_field="id",
            complete=quizzes_complete,
        )
        _write_list(course_dir / "_meta" / "quizzes.json", quiz_rows)

        if include_grades:
            grades, grades_complete, grades_error = _fetch_collection(
                client, _endpoint_path(client, course, "grades/values/myGradeValues/")
            )
            if grades_error is not None:
                errors.append(_safe_error("grades", grades_error))
            grades_path = course_dir / "_meta" / "my_grades.json"
            if grades_complete:
                grade_rows = _merge_rows(
                    _read_list(grades_path),
                    _project_grades(grades),
                    id_field="id",
                    complete=True,
                )
                _write_list(grades_path, grade_rows)
            else:
                # Grade values are sensitive, but they still obey merge-not-replace: an
                # incomplete response must never erase the last complete opt-in snapshot.
                partial_grades = _project_grades(grades)
                if partial_grades:
                    grade_rows = _merge_rows(
                        _read_list(grades_path),
                        partial_grades,
                        id_field="id",
                        complete=False,
                    )
                    _write_list(grades_path, grade_rows)
                errors.append("grades: incomplete response")

        merged_topics = course_index.reconcile_content_map(vault, merged_topics)
        _write_content_map(course_dir, merged_topics)
        _materialize_submission_only_readmes(
            assignments,
            artifacts=assignment_artifacts,
            course_dir=course_dir,
            topics=merged_topics,
        )
        deadline_count += sum(1 for row in assignments_rows + quiz_rows if row.get("due_date"))
        typed_topics = tuple(_topic_from_row(row, course=course) for row in merged_topics)
        _write_index(course_dir, school=school, course=course, topics=typed_topics)
        reports.append(
            CourseMetadata(
                course=course,
                directory=course_dir,
                topics=typed_topics,
                module_tree=tuple(module_tree),
            )
        )

    if create_snapshot:
        snapshot.write_snapshot(
            vault,
            [report.directory for report in reports],
            include_grades=include_grades,
            timestamp=_now(),
        )
    return MetadataReport(
        courses=tuple(reports),
        topic_count=sum(len(report.topics) for report in reports),
        deadline_count=deadline_count,
        errors=tuple(errors),
    )


def load_metadata_topics(
    vault: Vault, school: School, courses: Iterable[CourseRef]
) -> tuple[TopicRecord, ...]:
    """Load validated topic projections for a completed local metadata phase.

    This is intentionally a local read.  It lets a resumed onboarding run show an honest file
    estimate without repeating the network metadata phase, while using the same row decoder and
    filename/media rules as :func:`ingest_files`.
    """

    topics: list[TopicRecord] = []
    for course in courses:
        course_dir = _course_directory(vault, school, course)
        content_map_path = course_dir / "_meta" / "content_map.json"
        if paths.is_link(content_map_path) or not paths.long_path(content_map_path).is_file():
            raise A2LError("course metadata is unavailable; run a2l init")
        content_map = _read_content_map(course_dir)
        topics.extend(_topic_from_row(row, course=course) for row in _map_topics(content_map))
    return tuple(topics)


def ingest_files(
    client: Client,
    vault: Vault,
    school: School,
    *,
    term: str | None = None,
    only: Iterable[int | str] | None = None,
    scope: Literal["all", "priority"] = DEFAULT_SCOPE,
    include_media: bool = False,
    priority_budget_bytes: int = 200_000_000,
    include_discussions: bool = False,
    discussion_authors: bool = False,
) -> FileReport:
    """Download an explicit, resumable source scope after metadata is available."""

    if scope not in {"all", "priority"}:
        raise ValueError("scope must be 'all' or 'priority'")
    if isinstance(priority_budget_bytes, bool) or not isinstance(priority_budget_bytes, int):
        raise ValueError("priority_budget_bytes must be an integer")
    if priority_budget_bytes <= 0:
        raise ValueError("priority_budget_bytes must be positive")

    selected = _selected_courses(client, term=term, only=only)
    downloaded = skipped = failed = metadata_only = 0
    errors: list[str] = []

    for course in selected:
        course_dir = _course_directory(vault, school, course)
        content_map = _read_content_map(course_dir)
        rows = [_topic_from_row(row, course=course) for row in _map_topics(content_map)]
        if not rows:
            # Keep the public entry point safe when called directly: metadata remains a separate
            # phase, but a missing map is a configuration problem rather than a silent no-op.
            raise A2LError("course metadata is unavailable; run ingest_metadata first")

        planned = _plan_file_paths(rows, course_dir=course_dir, vault=vault, scope=scope)
        chosen = _priority_rows(planned, scope=scope, budget=priority_budget_bytes)
        if include_discussions:
            discussion_error = _ingest_discussions(
                client,
                course,
                course_dir,
                vault,
                include_authors=discussion_authors,
            )
            if discussion_error is not None:
                errors.append(discussion_error)

        for topic in chosen:
            if topic.availability == "external_link":
                skipped += 1
                continue
            if topic.url_path is None or topic.kind.casefold() not in _DOWNLOADABLE_KINDS:
                skipped += 1
                metadata_only += 1
                _update_row_state(
                    course_dir,
                    topic.source_key,
                    availability="metadata_only",
                    next_action="topic is metadata-only until explicitly fetched",
                )
                continue
            if _is_office_lock(topic):
                skipped += 1
                metadata_only += 1
                _update_row_state(
                    course_dir,
                    topic.source_key,
                    availability="metadata_only",
                    next_action="office lock file skipped",
                )
                continue
            if _is_media(topic) and not include_media:
                skipped += 1
                metadata_only += 1
                _update_row_state(
                    course_dir,
                    topic.source_key,
                    availability="metadata_only",
                    next_action="media excluded; rerun with --include-media",
                )
                continue
            if topic.is_broken:
                skipped += 1
                metadata_only += 1
                _update_row_state(
                    course_dir,
                    topic.source_key,
                    availability="metadata_only",
                    next_action="topic is marked broken in LEARN",
                )
                continue
            if topic.remote_size is None or topic.remote_size > api.DEFAULT_MAX_BYTES:
                skipped += 1
                metadata_only += 1
                _update_row_state(
                    course_dir,
                    topic.source_key,
                    availability="metadata_only",
                    next_action=f"a2l fetch --allow-large {topic.source_id}",
                )
                continue

            try:
                result = _ingest_one_topic(client, vault, school, course_dir, topic)
            except KeyboardInterrupt:
                return FileReport(
                    downloaded=downloaded,
                    skipped=skipped,
                    failed=failed,
                    metadata_only=metadata_only,
                    interrupted=True,
                    errors=tuple(errors),
                    exit_code=130,
                )
            except SessionExpired:
                raise
            except DownloadError as exc:
                failed += 1
                errors.append(_safe_error("download", exc))
                continue

            if result == "downloaded":
                downloaded += 1
            else:
                skipped += 1

    return FileReport(
        downloaded=downloaded,
        skipped=skipped,
        failed=failed,
        metadata_only=metadata_only,
        errors=tuple(errors),
    )


def fetch_topic(
    client: Client,
    vault: Vault,
    school: School,
    topic: str,
    *,
    allow_large: bool = False,
    confirm: Callable[[int | None], bool] | None = None,
) -> FetchReport:
    """Resolve one stable topic ID/path/title and fetch only that source."""

    match = _resolve_topic(vault, topic)
    if match is None:
        raise A2LError(f"topic not found: {topic}")
    course, record, course_dir = match
    if record.availability == "external_link":
        raise A2LError("external or licensed topics are link stubs and cannot be fetched")
    if record.remote_size is None or record.remote_size > api.DEFAULT_MAX_BYTES:
        if not allow_large:
            raise A2LError(
                "source size is unknown or exceeds the default limit; run: "
                f"a2l fetch --allow-large {record.source_id}"
            )
        if confirm is None or not confirm(record.remote_size):
            raise A2LError("large-file fetch cancelled")

    planned = _plan_file_paths([record], course_dir=course_dir, vault=vault, scope="all")
    if not planned or planned[0].source_path is None:
        raise A2LError("topic has no fetchable first-party source")
    record = planned[0]

    result = _ingest_one_topic(
        client,
        vault,
        school,
        course_dir,
        record,
        max_bytes=None if allow_large else api.DEFAULT_MAX_BYTES,
    )
    refreshed = _topic_from_row(
        _find_content_row(course_dir, record.source_key) or _topic_to_row(record), course=course
    )
    return FetchReport(
        source_key=record.source_key,
        availability=refreshed.availability,
        source_path=refreshed.source_path,
        citation_path=refreshed.path,
        changed=result == "downloaded",
    )


def _selected_courses(
    client: Client,
    *,
    term: str | None,
    only: Iterable[int | str] | None,
) -> list[CourseRef]:
    raw_courses: object = getattr(client, "courses", None)
    if raw_courses is None:
        calibration = getattr(client, "calibration", None)
        if calibration is None:
            try:
                calibration = load_calibration()
            except NotConfigured:
                calibration = calibrate(client)
        raw_courses = getattr(calibration, "courses", None)
        if getattr(client, "lp_version", None) is None:
            client.lp_version = getattr(calibration, "lp", None)
        if getattr(client, "le_version", None) is None:
            client.le_version = getattr(calibration, "le", None)
        if client.download_template is None:
            client.download_template = getattr(calibration, "download_template", None)

    if not isinstance(raw_courses, Sequence) or isinstance(raw_courses, (str, bytes)):
        raise A2LError("course metadata is unavailable; run calibration first")
    selectors = {str(value).casefold() for value in only} if only is not None else None
    courses: list[CourseRef] = []
    for raw in raw_courses:
        course = _course_ref(raw)
        if not course.is_active:
            continue
        if term is not None and course.term != term:
            continue
        if selectors is not None and not (
            str(course.org_unit_id).casefold() in selectors or course.code.casefold() in selectors
        ):
            continue
        courses.append(course)
    return sorted(
        courses, key=lambda item: (item.term or "", item.code.casefold(), item.org_unit_id)
    )


def _course_ref(raw: object) -> CourseRef:
    if isinstance(raw, CourseRef):
        return raw
    if not isinstance(raw, Mapping):
        raise A2LError("course metadata contains an invalid course")
    try:
        org_unit_id = raw["org_unit_id"]
        code = raw["code"]
        name = raw["name"]
        term = raw.get("term")
        is_active = raw["is_active"]
    except KeyError as exc:
        raise A2LError("course metadata contains an invalid course") from exc
    if (
        isinstance(org_unit_id, bool)
        or not isinstance(org_unit_id, int)
        or not isinstance(code, str)
        or not code
        or not isinstance(name, str)
        or not name
        or not isinstance(is_active, bool)
        or term is not None
        and not isinstance(term, str)
    ):
        raise A2LError("course metadata contains an invalid course")
    return CourseRef(org_unit_id, code, name, term, is_active)


def _course_directory(vault: Vault, school: School, course: CourseRef) -> Path:
    term_code = course.term or "unclassified"
    if course.term is None:
        term_label = "Unclassified"
    else:
        try:
            term_label = school.term_label(course.term)
        except ValueError:
            term_label = f"Term {course.term}"
    course_label = f"{course.code}_{term_code}" if course.code else f"Course-{course.org_unit_id}"
    return vault.root / paths.safe_name(term_label) / paths.safe_name(course_label)


def _toc_path(client: Client, course: CourseRef) -> str:
    le = getattr(client, "le_version", None)
    if not isinstance(le, str) or not le:
        raise A2LError("LE API version is not calibrated")
    return f"/d2l/api/le/{le}/{course.org_unit_id}/content/toc"


def _endpoint_path(client: Client, course: CourseRef, endpoint: str) -> str:
    le = getattr(client, "le_version", None)
    if not isinstance(le, str) or not le:
        raise A2LError("LE API version is not calibrated")
    return f"/d2l/api/le/{le}/{course.org_unit_id}/{endpoint}"


def _fetch_one(client: Client, path: str) -> tuple[object, bool, Exception | None]:
    try:
        return client.get_json(path), True, None
    except SessionExpired:
        raise
    except Exception as exc:
        return {}, False, exc


def _fetch_collection(client: Client, path: str) -> tuple[list[object], bool, Exception | None]:
    values: list[object] = []
    seen: set[str] = set()
    current = path
    for _ in range(_MAX_PAGES):
        if current in seen:
            return values, False, A2LError("metadata pagination repeated a page")
        seen.add(current)
        try:
            payload = client.get_json(current)
        except SessionExpired:
            raise
        except Exception as exc:
            return values, False, exc
        page, next_page, valid = _page_values(payload, current)
        if not valid:
            return values, False, A2LError("metadata endpoint returned an invalid page")
        if any(not _collection_item_is_valid(item, current) for item in page):
            return values, False, A2LError("metadata endpoint returned an invalid item")
        values.extend(page)
        if next_page is None:
            return values, True, None
        if not isinstance(next_page, str) or not next_page:
            return values, False, A2LError("metadata pagination returned an invalid next route")
        current = next_page
    return values, False, A2LError("metadata pagination exceeded its limit")


def _page_values(payload: object, current: str) -> tuple[list[object], str | None, bool]:
    if isinstance(payload, list):
        return list(payload), None, True
    if not isinstance(payload, dict):
        return [], None, False
    if isinstance(payload.get("Objects"), list):
        next_page = payload.get("Next")
        return list(payload["Objects"]), cast(str | None, next_page), True
    if isinstance(payload.get("Items"), list):
        paging = payload.get("PagingInfo")
        if paging is None:
            return list(payload["Items"]), cast(str | None, payload.get("Next")), True
        if not isinstance(paging, dict) or not isinstance(paging.get("HasMoreItems"), bool):
            return [], None, False
        if not paging["HasMoreItems"]:
            return list(payload["Items"]), None, True
        bookmark = paging.get("Bookmark")
        if not isinstance(bookmark, str) or not bookmark:
            return [], None, False
        # D2L's bookmark route is endpoint-specific; retain the path and add only the opaque
        # bookmark value needed for the next request.  It is never persisted in the vault.
        next_route = _as_route_string(payload.get("Next")) or current
        separator = "&" if "?" in next_route else "?"
        return (
            list(payload["Items"]),
            f"{next_route}{separator}bookmark={bookmark}",
            True,
        )
    return [], None, False


def _collection_item_is_valid(value: object, path: str) -> bool:
    """Require stable IDs before a response can be considered complete for merge purposes."""
    if not isinstance(value, dict):
        return False
    route = path.casefold()
    if "dropbox/folders" in route or "/news/" in route:
        identifier = value.get("Id")
        if not isinstance(identifier, int) or isinstance(identifier, bool):
            return False
        if "dropbox/folders" in route:
            return _assignment_attachments_are_valid(value)
        return True
    if "/quizzes/" in route:
        identifier = value.get("QuizId")
        return isinstance(identifier, int) and not isinstance(identifier, bool)
    if "/grades/" in route:
        identifier = value.get("GradeObjectIdentifier")
        return (isinstance(identifier, int) and not isinstance(identifier, bool)) or (
            isinstance(identifier, str) and bool(identifier)
        )
    if "/discussions/forums/" in route:
        identifier = value.get("ForumId")
        return isinstance(identifier, int) and not isinstance(identifier, bool)
    return True


def _as_route_string(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def _topics_from_toc(
    payload: object, *, course: CourseRef, school: School
) -> tuple[list[TopicRecord], list[dict[str, object]], bool]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Modules"), list):
        return [], [], False
    records: list[TopicRecord] = []
    valid = True

    def walk(
        modules: object, parent_titles: tuple[str, ...], parent_ids: tuple[int, ...]
    ) -> list[dict[str, object]]:
        nonlocal valid
        if not isinstance(modules, list):
            valid = False
            return []
        projected: list[dict[str, object]] = []
        for module in modules:
            if not isinstance(module, dict):
                valid = False
                continue
            module_id = module.get("ModuleId")
            title = module.get("Title")
            children = module.get("Modules")
            topics = module.get("Topics")
            if (
                isinstance(module_id, bool)
                or not isinstance(module_id, int)
                or not isinstance(title, str)
                or not isinstance(children, list)
                or not isinstance(topics, list)
            ):
                valid = False
                continue
            module_titles = parent_titles + (title,)
            module_ids = parent_ids + (module_id,)
            topic_projection: list[dict[str, object]] = []
            for raw_topic in topics:
                record = _topic_from_api(
                    raw_topic,
                    course=course,
                    school=school,
                    module_titles=module_titles,
                    module_ids=module_ids,
                )
                if record is None:
                    valid = False
                    continue
                records.append(record)
                topic_projection.append(_topic_projection(record))
            projected.append(
                {
                    "module_id": module_id,
                    "title": title,
                    "topics": topic_projection,
                    "modules": walk(children, module_titles, module_ids),
                }
            )
        return projected

    modules = walk(payload["Modules"], (), ())
    records.sort(key=lambda record: record.source_key)
    return records, modules, valid


def _topic_from_api(
    raw: object,
    *,
    course: CourseRef,
    school: School,
    module_titles: tuple[str, ...],
    module_ids: tuple[int, ...],
) -> TopicRecord | None:
    if not isinstance(raw, dict):
        return None
    topic_id = raw.get("TopicId")
    title = raw.get("Title")
    kind = raw.get("TypeIdentifier")
    raw_url = raw.get("Url")
    if (
        isinstance(topic_id, bool)
        or not isinstance(topic_id, int)
        or not isinstance(title, str)
        or not isinstance(kind, str)
        or raw_url is not None
        and not isinstance(raw_url, str)
    ):
        return None
    last_modified = raw.get("LastModifiedDate")
    if last_modified is not None and not isinstance(last_modified, str):
        last_modified = None
    is_broken = raw.get("IsBroken", False)
    if not isinstance(is_broken, bool):
        is_broken = False
    remote_size = raw.get("Size")
    if isinstance(remote_size, bool) or not isinstance(remote_size, int) or remote_size < 0:
        remote_size = None

    key = f"{school.id}:{course.org_unit_id}:topic:{topic_id}"
    view_url = _view_url(school, course.org_unit_id, topic_id)
    external = bool(raw_url) and topic_is_excluded(kind, raw_url, school.topic_exclusion_policy())
    url_path = _first_party_path(raw_url, school.base_url)
    outline_url = _allowed_outline_url(raw_url, school)
    external_host = _safe_hostname(raw_url)
    if external or (raw_url and url_path is None and outline_url is None):
        return TopicRecord(
            source_key=key,
            source_id=str(topic_id),
            topic_id=topic_id,
            course_org_unit_id=course.org_unit_id,
            course_code=course.code,
            course_name=course.name,
            term=course.term,
            title=title,
            kind=kind,
            module_path=module_titles,
            module_ids=module_ids,
            view_url=view_url,
            outline_url=None,
            url_path=None,
            external_host=external_host,
            etag=_optional_text(raw.get("ETag")),
            last_modified=last_modified,
            is_broken=is_broken,
            availability="external_link",
            remote_size=remote_size,
            next_action="open the LEARN link manually",
        )

    if is_broken:
        reason = "topic is marked broken in LEARN"
    elif url_path is None or kind.casefold() not in _DOWNLOADABLE_KINDS:
        reason = "fetch the topic explicitly"
    else:
        reason = f"a2l fetch {topic_id}"
    return TopicRecord(
        source_key=key,
        source_id=str(topic_id),
        topic_id=topic_id,
        course_org_unit_id=course.org_unit_id,
        course_code=course.code,
        course_name=course.name,
        term=course.term,
        title=title,
        kind=kind,
        module_path=module_titles,
        module_ids=module_ids,
        view_url=view_url,
        outline_url=outline_url,
        url_path=url_path,
        external_host=None,
        etag=_optional_text(raw.get("ETag")),
        last_modified=last_modified,
        is_broken=is_broken,
        availability="metadata_only",
        remote_size=remote_size,
        next_action=reason,
    )


def _topic_projection(record: TopicRecord) -> dict[str, object]:
    return {
        "id": record.topic_id,
        "title": record.title,
        "kind": record.kind,
        "url_path": record.url_path,
        "external_host": record.external_host,
        "view_url": record.view_url,
        "last_modified": record.last_modified,
        "availability": record.availability,
    }


def _merge_topic_records(
    existing: object,
    incoming: Sequence[TopicRecord],
    *,
    complete: bool,
) -> list[dict[str, object]]:
    old_rows = existing if isinstance(existing, list) else []
    by_key: dict[str, dict[str, object]] = {}
    for value in old_rows:
        if isinstance(value, dict) and isinstance(value.get("source_key"), str):
            by_key[value["source_key"]] = dict(value)
    incoming_keys: set[str] = set()
    for record in incoming:
        incoming_keys.add(record.source_key)
        prior = by_key.get(record.source_key, {})
        row = _topic_to_row(record)
        for field in ("source_path", "path", "sha256", "size", "stub_path", "source_sha256"):
            if row.get(field) is None and prior.get(field) is not None:
                row[field] = prior[field]
        if prior.get("availability") in {
            "source_only",
            "markdown_ready",
            "unsupported_format",
            "integrity_gap",
        }:
            row["availability"] = prior["availability"]
            row["next_action"] = prior.get("next_action", row["next_action"])
        row["missing_since"] = None
        row["withdrawn_at"] = None
        by_key[record.source_key] = row

    if complete:
        now = _now()
        for key, row in by_key.items():
            if key in incoming_keys:
                continue
            if row.get("missing_since") is None:
                row["missing_since"] = now
            elif row.get("withdrawn_at") is None:
                row["withdrawn_at"] = now
    return sorted(by_key.values(), key=lambda row: str(row.get("source_key", "")))


def _topic_to_row(record: TopicRecord) -> dict[str, object]:
    return {
        "source_key": record.source_key,
        "source_id": record.source_id,
        "topic_id": record.topic_id,
        "course_org_unit_id": record.course_org_unit_id,
        "course_code": record.course_code,
        "course_name": record.course_name,
        "term": record.term,
        "title": record.title,
        "kind": record.kind,
        "module_path": list(record.module_path),
        "module_ids": list(record.module_ids),
        "view_url": record.view_url,
        "outline_url": record.outline_url,
        "url_path": record.url_path,
        "external_host": record.external_host,
        "etag": record.etag,
        "last_modified": record.last_modified,
        "is_broken": record.is_broken,
        "availability": record.availability,
        "source_path": record.source_path,
        "path": record.path,
        "sha256": record.sha256,
        "source_sha256": record.sha256,
        "size": record.size,
        "stub_path": record.stub_path,
        "remote_size": record.remote_size,
        "next_action": record.next_action,
        "missing_since": record.missing_since,
        "withdrawn_at": record.withdrawn_at,
    }


def _topic_from_row(row: object, *, course: CourseRef) -> TopicRecord:
    if not isinstance(row, dict):
        raise A2LError("content_map contains an invalid topic row")
    source_key = row.get("source_key")
    source_id = row.get("source_id")
    topic_id = row.get("topic_id")
    if (
        not isinstance(source_key, str)
        or not isinstance(source_id, str)
        or isinstance(topic_id, bool)
        or not isinstance(topic_id, int)
    ):
        raise A2LError("content_map contains an invalid topic identity")
    return TopicRecord(
        source_key=source_key,
        source_id=source_id,
        topic_id=topic_id,
        course_org_unit_id=course.org_unit_id,
        course_code=str(row.get("course_code", course.code)),
        course_name=str(row.get("course_name", course.name)),
        term=row.get("term") if isinstance(row.get("term"), str) else course.term,
        title=str(row.get("title", "untitled")),
        kind=str(row.get("kind", "File")),
        module_path=tuple(value for value in row.get("module_path", []) if isinstance(value, str)),
        module_ids=tuple(value for value in row.get("module_ids", []) if isinstance(value, int)),
        view_url=str(row.get("view_url", "")),
        outline_url=row.get("outline_url") if isinstance(row.get("outline_url"), str) else None,
        url_path=row.get("url_path") if isinstance(row.get("url_path"), str) else None,
        external_host=row.get("external_host")
        if isinstance(row.get("external_host"), str)
        else None,
        etag=row.get("etag") if isinstance(row.get("etag"), str) else None,
        last_modified=row.get("last_modified")
        if isinstance(row.get("last_modified"), str)
        else None,
        is_broken=bool(row.get("is_broken", False)),
        availability=str(row.get("availability", "metadata_only")),
        source_path=row.get("source_path") if isinstance(row.get("source_path"), str) else None,
        path=row.get("path") if isinstance(row.get("path"), str) else None,
        sha256=row.get("sha256") if isinstance(row.get("sha256"), str) else None,
        size=row.get("size") if isinstance(row.get("size"), int) else None,
        stub_path=row.get("stub_path") if isinstance(row.get("stub_path"), str) else None,
        remote_size=row.get("remote_size") if isinstance(row.get("remote_size"), int) else None,
        next_action=str(row.get("next_action", f"a2l fetch {source_id}")),
        missing_since=row.get("missing_since")
        if isinstance(row.get("missing_since"), str)
        else None,
        withdrawn_at=row.get("withdrawn_at") if isinstance(row.get("withdrawn_at"), str) else None,
    )


def _assignment_attachment_topics(
    values: Sequence[object], *, course: CourseRef, school: School
) -> list[TopicRecord]:
    """Project only allowlisted first-party Dropbox attachments into the normal file pipeline."""

    records: list[TopicRecord] = []
    for assignment in values:
        if (
            not isinstance(assignment, dict)
            or not isinstance(assignment.get("Id"), int)
            or isinstance(assignment.get("Id"), bool)
        ):
            continue
        assignment_id = assignment["Id"]
        assignment_title = _safe_text(assignment.get("Name")) or f"Assignment {assignment_id}"
        for attachment in _attachment_values(assignment):
            if not isinstance(attachment, dict):
                continue
            raw_id = attachment.get("Id", attachment.get("FileId"))
            if raw_id is None:
                continue
            attachment_id = str(raw_id)
            source_id = f"{assignment_id}-{attachment_id}".replace(":", "_")
            raw_url = _first_string(attachment, "Url", "URL", "Href", "DownloadUrl")
            url_path = _first_party_path(raw_url, school.base_url)
            if url_path is None:
                continue
            title = (
                _first_string(attachment, "FileName", "Name", "Title")
                or f"attachment-{attachment_id}"
            )
            remote_size = attachment.get("Size")
            if isinstance(remote_size, bool) or not isinstance(remote_size, int) or remote_size < 0:
                remote_size = None
            topic_id = (
                raw_id
                if isinstance(raw_id, int) and not isinstance(raw_id, bool)
                else _stable_numeric_id(source_id)
            )
            records.append(
                TopicRecord(
                    source_key=f"{school.id}:{course.org_unit_id}:attachment:{source_id}",
                    source_id=source_id,
                    topic_id=topic_id,
                    course_org_unit_id=course.org_unit_id,
                    course_code=course.code,
                    course_name=course.name,
                    term=course.term,
                    title=title,
                    kind="File",
                    module_path=("Assignments", assignment_title),
                    module_ids=(),
                    view_url=_view_url(school, course.org_unit_id, topic_id),
                    outline_url=None,
                    url_path=url_path,
                    external_host=None,
                    etag=_first_string(attachment, "ETag", "Etag"),
                    last_modified=_first_string(attachment, "LastModifiedDate", "LastModified"),
                    is_broken=False,
                    remote_size=remote_size,
                    next_action=f"a2l fetch {source_id}",
                )
            )
    return sorted(records, key=lambda item: item.source_key)


def _attachment_values(assignment: Mapping[str, object]) -> list[object]:
    raw = assignment.get("Attachments", assignment.get("attachments", []))
    if isinstance(raw, dict):
        raw = raw.get("Items", raw.get("Objects", []))
    return list(raw) if isinstance(raw, list) else []


def _assignment_attachments_are_valid(assignment: Mapping[str, object]) -> bool:
    """Reject malformed attachment containers before they can mark old files missing."""
    if "Attachments" not in assignment and "attachments" not in assignment:
        return True
    raw = assignment.get("Attachments", assignment.get("attachments"))
    if isinstance(raw, dict):
        raw = raw.get("Items", raw.get("Objects"))
    if not isinstance(raw, list):
        return False
    for attachment in raw:
        if not isinstance(attachment, dict):
            return False
        identifier = attachment.get("Id", attachment.get("FileId"))
        if isinstance(identifier, bool) or not isinstance(identifier, (int, str)):
            return False
        if isinstance(identifier, str) and not identifier:
            return False
    return True


def _first_string(value: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _stable_numeric_id(value: str) -> int:
    return int.from_bytes(sha256(value.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF


def _materialize_assignments(
    values: Sequence[object], *, course_dir: Path, vault: Vault, school: School, course: CourseRef
) -> dict[str, dict[str, object]]:
    """Sanitize Dropbox RichText and persist a provenance-backed source/twin pair."""

    manifest = vault.manifest()
    reserved: set[str] = set()
    artifacts: dict[str, dict[str, object]] = {}
    assignments = sorted(
        (value for value in values if isinstance(value, dict) and isinstance(value.get("Id"), int)),
        key=lambda value: int(value["Id"]),
    )
    for assignment in assignments:
        assignment_id = int(assignment["Id"])
        richtext = _assignment_richtext(assignment)
        if richtext is None:
            continue
        raw_html, raw_text = richtext
        canonical_html = _sanitize_richtext(raw_html or raw_text or "", school.base_url)
        if not canonical_html.strip():
            continue
        html_bytes = canonical_html.encode("utf-8")
        source_hash = sha256(html_bytes).hexdigest()
        key = f"{school.id}:{course.org_unit_id}:dropbox:{assignment_id}"
        prior = manifest.get(key)
        if prior is not None:
            source_destination = vault.materialized(prior)
        else:
            title = _safe_text(assignment.get("Name")) or f"Assignment {assignment_id}"
            candidate = course_dir / "assignments" / paths.safe_name(title)
            assignment_directory = _unique_reserved(candidate, reserved)
            source_destination = assignment_directory / "instructions.html"
        if prior is not None and prior.sha256 != source_hash:
            preserved = vault.preserve_revision(key, changed_at=clock.now())
            if preserved is None and paths.long_path(vault.materialized(prior)).exists():
                raise A2LError("assignment instructions could not be preserved")
        paths.long_path(source_destination.parent).mkdir(parents=True, exist_ok=True)
        paths.atomic_write_bytes(source_destination, html_bytes)

        title = _safe_text(assignment.get("Name")) or f"Assignment {assignment_id}"
        markdown_bytes = _richtext_markdown(title, canonical_html).encode("utf-8")
        if prior is not None and prior.derived.get("markdown") is not None:
            artifact = prior.derived["markdown"]
            markdown_destination = vault.materialized(
                ManifestEntry(
                    path=artifact.path,
                    sha256=artifact.sha256,
                    source_id="derived",
                    etag=None,
                    last_modified=None,
                    size=0,
                    fetched_at=_now(),
                )
            )
        else:
            markdown_destination = source_destination.with_suffix(".md")
        paths.long_path(markdown_destination.parent).mkdir(parents=True, exist_ok=True)
        paths.atomic_write_bytes(markdown_destination, markdown_bytes)
        derived = DerivedArtifact(
            path=paths.rel_posix(markdown_destination, vault.root),
            sha256=sha256(markdown_bytes).hexdigest(),
            source_sha256=source_hash,
            tool="richtext-sanitizer",
            tool_version="1",
            created_at=_now(),
        )
        entry = ManifestEntry(
            path=paths.rel_posix(source_destination, vault.root),
            sha256=source_hash,
            source_id=str(assignment_id),
            etag=None,
            last_modified=_optional_text(assignment.get("LastModifiedDate")),
            size=len(html_bytes),
            fetched_at=_now(),
            derived={"markdown": derived},
        )
        vault.mark(key, entry)
        vault.save_manifest()
        manifest[key] = entry

        _write_assignment_readme(
            source_destination.parent,
            title=title,
            entry=entry,
            attachments=_assignment_attachment_display(assignment, school),
        )
        artifacts[str(assignment_id)] = {
            "instructions_html": entry.path,
            "instructions_md": derived.path,
            "instructions_sha256": source_hash,
        }
    return artifacts


def _assignment_richtext(assignment: Mapping[str, object]) -> tuple[str | None, str | None] | None:
    for field in ("Description", "Instructions", "RichText", "Body"):
        value = assignment.get(field)
        if isinstance(value, str):
            return value, None
        if isinstance(value, dict):
            html_value = _first_string(value, "Html", "HTML", "html")
            text_value = _first_string(value, "Text", "text")
            if html_value is not None or text_value is not None:
                return html_value, text_value
    return None


def _assignment_attachment_display(
    assignment: Mapping[str, object], school: School
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    assignment_id = assignment.get("Id")
    for attachment in _attachment_values(assignment):
        if not isinstance(attachment, dict):
            continue
        raw_id = attachment.get("Id", attachment.get("FileId"))
        if raw_id is None:
            continue
        attachment_id = str(raw_id)
        name = (
            _first_string(attachment, "FileName", "Name", "Title") or f"attachment-{attachment_id}"
        )
        raw_url = _first_string(attachment, "Url", "URL", "Href", "DownloadUrl")
        path = _first_party_path(raw_url, school.base_url)
        if path is not None:
            rows.append(
                {
                    "name": name,
                    "action": f"a2l fetch {assignment_id}-{attachment_id}",
                }
            )
        else:
            host = _safe_hostname(raw_url) or "unknown-host"
            rows.append({"name": name, "action": f"external link · {host}"})
    return rows


def _write_assignment_readme(
    directory: Path,
    *,
    title: str,
    entry: ManifestEntry,
    attachments: Sequence[Mapping[str, str]],
) -> None:
    markdown_path = entry.derived["markdown"].path
    lines = [
        f"# {title}",
        "",
        f"- Instructions source: `{PurePosixPath(entry.path).name}`",
        f"- Instructions twin: `{PurePosixPath(markdown_path).name}`",
        f"- Source SHA-256: `{entry.sha256}`",
        "",
        "## Attachments",
        "",
    ]
    if attachments:
        lines.extend(f"- {row['name']} — {row['action']}" for row in attachments)
    else:
        lines.append("- None recorded.")
    lines.append("")
    paths.atomic_write_text(directory / "README.md", "\n".join(lines))


def _materialize_submission_only_readmes(
    values: Sequence[object],
    *,
    artifacts: Mapping[str, Mapping[str, object]],
    course_dir: Path,
    topics: Sequence[Mapping[str, object]],
) -> None:
    """Give a Dropbox folder without RichText a generated navigation hub.

    This is deliberately a metadata-only projection: it creates no fetch route and does not copy
    a prompt into the README.  Exact display-title matches are only navigation cross-links; topic
    resolution itself remains stable-ID/manifest based in :mod:`agent2learn.index`.
    """
    for assignment in sorted(
        (row for row in values if isinstance(row, Mapping) and isinstance(row.get("Id"), int)),
        key=lambda row: int(row["Id"]),
    ):
        assignment_id = str(assignment["Id"])
        if assignment_id in artifacts:
            continue
        title = _safe_text(assignment.get("Name")) or f"Assignment {assignment_id}"
        directory = course_dir / "assignments" / paths.safe_name(f"{title} {assignment_id}")
        paths.long_path(directory).mkdir(parents=True, exist_ok=True)
        links: list[tuple[str, str]] = []
        for topic in topics:
            if str(topic.get("title", "")).casefold() != title.casefold():
                continue
            target = topic.get("path") or topic.get("source_path") or topic.get("stub_path")
            source_id = topic.get("source_id")
            if isinstance(target, str) and isinstance(source_id, str):
                links.append((source_id, _course_relative_link(target, course_dir)))
        course_index.write_submission_readme(directory, title=title, content_links=links)


def _materialize_external_stubs(
    rows: list[dict[str, object]],
    *,
    course_dir: Path,
    vault: Vault,
    school: School,
    course: CourseRef,
) -> list[dict[str, object]]:
    reserved: set[str] = set()
    for row in sorted(rows, key=lambda value: str(value.get("source_key", ""))):
        if row.get("availability") != "external_link":
            continue
        prior = row.get("stub_path")
        if isinstance(prior, str):
            stub = _vault_relative_path(vault, prior)
        else:
            record = _topic_from_row(row, course=course)
            destination = _content_directory(course_dir, record.module_path) / (
                f"{paths.safe_name(record.title)}.url.txt"
            )
            stub = _unique_reserved(destination, reserved)
            row["stub_path"] = paths.rel_posix(stub, vault.root)
        paths.long_path(stub.parent).mkdir(parents=True, exist_ok=True)
        if not paths.long_path(stub).is_file():
            record = _topic_from_row(row, course=course)
            text = (
                "Agent2Learn external-topic stub\n"
                f"topic: {record.title}\n"
                f"view in LEARN: {record.view_url}\n"
                f"destination host: {record.external_host or 'unknown-host'}\n"
            )
            # Keep the ordinary path as the value passed between layers; long_path belongs only
            # at filesystem boundaries, and atomic_write_text applies it internally.
            paths.atomic_write_text(stub, text)
    return rows


def _plan_file_paths(
    rows: Sequence[TopicRecord], *, course_dir: Path, vault: Vault, scope: str
) -> list[TopicRecord]:
    del scope
    manifest = Vault(vault.root).manifest()
    reserved_by_folder: dict[str, set[str]] = defaultdict(set)
    planned: list[TopicRecord] = []
    for topic in sorted(rows, key=lambda item: item.source_key):
        if topic.availability == "external_link":
            planned.append(topic)
            continue
        entry = manifest.get(topic.source_key)
        if entry is not None:
            planned.append(
                replace(topic, source_path=entry.path, path=_derived_path(manifest, entry))
            )
            continue
        if topic.url_path is None or topic.kind.casefold() not in _DOWNLOADABLE_KINDS:
            planned.append(topic)
            continue
        destination = _content_directory(course_dir, topic.module_path) / _topic_filename(topic)
        folder_key = destination.parent.as_posix()
        candidate = _unique_reserved(destination, reserved_by_folder[folder_key])
        planned.append(replace(topic, source_path=paths.rel_posix(candidate, vault.root)))
    return planned


def _priority_rows(
    rows: Sequence[TopicRecord], *, scope: Literal["all", "priority"], budget: int
) -> list[TopicRecord]:
    if scope == "all":
        return list(rows)
    ranked = sorted(
        rows,
        key=lambda topic: (
            0 if _is_priority(topic) else 1,
            0 if topic.last_modified is not None else 1,
            -(int(_timestamp_sort(topic.last_modified)) if topic.last_modified else 0),
            topic.source_key,
        ),
    )
    selected: list[TopicRecord] = []
    total = 0
    for topic in ranked:
        if topic.remote_size is not None and total + topic.remote_size > budget:
            continue
        if topic.remote_size is not None:
            total += topic.remote_size
        selected.append(topic)
    return selected


def _is_priority(topic: TopicRecord) -> bool:
    value = f"{topic.title} {'/'.join(topic.module_path)}".casefold()
    return "assignment" in value or "outline" in value or "syllabus" in value


def _ingest_one_topic(
    client: Client,
    vault: Vault,
    school: School,
    course_dir: Path,
    topic: TopicRecord,
    *,
    max_bytes: int | None = api.DEFAULT_MAX_BYTES,
) -> Literal["downloaded", "skipped"]:
    if topic.url_path is None:
        raise DownloadError("topic has no first-party download route")
    key = topic.source_key
    manifest = vault.manifest()
    prior = manifest.get(key)
    destination = _destination_for_topic(vault, course_dir, topic, prior)
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    pending = _find_pending_install(vault, destination, topic)
    if pending is not None:
        retried = _retry_pending_install(
            vault, course_dir, school, topic, destination, prior, pending
        )
        if retried is not None:
            return retried
    if prior is not None and _unchanged_local(prior, topic, vault):
        _mark_topic_source_only(vault, course_dir, topic, school)
        return "skipped"

    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=os.fspath(paths.long_path(destination.parent)),
    )
    os.close(fd)
    temporary = paths.plain_path(Path(raw_temp))
    install_attempted = False
    installed = False
    try:
        result = _download_with_candidates(
            client, school, topic, temporary, prior=prior, max_bytes=max_bytes
        )
        if result.not_modified:
            if prior is None or not paths.long_path(vault.materialized(prior)).is_file():
                raise DownloadError("server returned 304 without a local source")
            _mark_topic_source_only(vault, course_dir, topic, school)
            return "skipped"
        if result.temp is None or not paths.long_path(result.temp).is_file():
            raise DownloadError("download did not produce a source file")
        actual_hash, actual_size = _hash_file(result.temp)
        if actual_size <= 0 or result.sha256 != actual_hash or result.size != actual_size:
            raise DownloadError("download integrity validation failed")
        pending = _PendingInstall(
            marker=_pending_marker_path(temporary),
            part=temporary,
            source_key=key,
            destination=paths.rel_posix(destination, vault.root),
            sha256=actual_hash,
            size=actual_size,
            etag=result.etag or topic.etag or (prior.etag if prior else None),
            last_modified=result.last_modified
            or topic.last_modified
            or (prior.last_modified if prior else None),
            prior_sha256=(
                prior.sha256 if prior is not None and actual_hash != prior.sha256 else None
            ),
            revision_preserved=prior is None or actual_hash == prior.sha256,
        )
        _write_pending_install(pending)
        install_attempted = True
        if pending.prior_sha256 is not None:
            if prior is None:
                raise A2LError("pending source revision has no current manifest entry")
            preserved = vault.preserve_revision(key, changed_at=clock.now())
            if preserved is None and paths.long_path(vault.materialized(prior)).exists():
                raise A2LError("current source could not be preserved; refusing replacement")
            pending = replace(pending, revision_preserved=True)
            _write_pending_install(pending)

        paths.atomic_install_temp(destination, temporary)
        installed = True
        entry = _manifest_entry_for_install(
            vault,
            topic,
            destination=destination,
            prior=prior,
            sha256=actual_hash,
            size=actual_size,
            etag=pending.etag,
            last_modified=pending.last_modified,
        )
        vault.mark(key, entry)
        vault.save_manifest()
        _mark_topic_source_only(vault, course_dir, topic, school)
        _remove_pending_install(pending)
        return "downloaded"
    except BaseException:
        # A failed transfer has an incomplete part and may be restarted from byte zero.  A
        # completed part whose *install* failed is different: paths.atomic_install_temp owns the
        # deliberate retention guarantee, so do not clean it here once installation was attempted.
        if not install_attempted:
            _remove_quietly(temporary)
        raise
    finally:
        if installed:
            _remove_quietly(temporary)


def _pending_marker_path(part: Path) -> Path:
    return part.with_name(part.name + _PENDING_MARKER_SUFFIX)


def _write_pending_install(pending: _PendingInstall) -> None:
    payload = {
        "version": 1,
        "source_key": pending.source_key,
        "destination": pending.destination,
        "sha256": pending.sha256,
        "size": pending.size,
        "etag": pending.etag,
        "last_modified": pending.last_modified,
        "prior_sha256": pending.prior_sha256,
        "revision_preserved": pending.revision_preserved,
    }
    paths.atomic_write_text(
        pending.marker,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _read_pending_install(marker: Path, part: Path) -> _PendingInstall | None:
    if not _is_safe_local_file(marker):
        return None
    try:
        with open(os.fspath(paths.long_path(marker)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(raw, dict) or set(raw) != _PENDING_INSTALL_KEYS:
        return None
    source_key = raw.get("source_key")
    destination = raw.get("destination")
    sha256_value = raw.get("sha256")
    size = raw.get("size")
    etag = raw.get("etag")
    last_modified = raw.get("last_modified")
    prior_sha256 = raw.get("prior_sha256")
    revision_preserved = raw.get("revision_preserved")
    if (
        raw.get("version") != 1
        or not isinstance(source_key, str)
        or not source_key
        or not isinstance(destination, str)
        or not destination
        or not isinstance(sha256_value, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256_value) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or (etag is not None and not isinstance(etag, str))
        or (last_modified is not None and not isinstance(last_modified, str))
        or (
            prior_sha256 is not None
            and (
                not isinstance(prior_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", prior_sha256) is None
            )
        )
        or not isinstance(revision_preserved, bool)
    ):
        return None
    return _PendingInstall(
        marker=marker,
        part=part,
        source_key=source_key,
        destination=destination,
        sha256=sha256_value,
        size=size,
        etag=etag,
        last_modified=last_modified,
        prior_sha256=prior_sha256,
        revision_preserved=revision_preserved,
    )


def _is_safe_local_file(path: Path) -> bool:
    try:
        file_stat = os.lstat(os.fspath(paths.long_path(path)))
    except OSError:
        return False
    return (
        not paths.is_link(path)
        and stat.S_ISREG(file_stat.st_mode)
        and getattr(file_stat, "st_nlink", 1) == 1
    )


def _remove_pending_install(pending: _PendingInstall) -> None:
    # The marker is removed first so an orphaned part is never treated as a validated download.
    _remove_pending_paths(pending.marker, pending.part)


def _remove_pending_paths(marker: Path, part: Path) -> None:
    paths.remove_tree(marker, ignore_errors=True)
    paths.remove_tree(part, ignore_errors=True)


def _pending_matches_topic(pending: _PendingInstall, topic: TopicRecord) -> bool:
    # A stable key and matching byte count do not prove that a remote file with no validator is
    # unchanged. Revalidate it over the network rather than replaying a potentially stale part.
    if topic.etag is None and topic.last_modified is None:
        return False
    if topic.etag is not None and pending.etag != topic.etag:
        return False
    if topic.last_modified is not None and pending.last_modified != topic.last_modified:
        return False
    return topic.remote_size is None or pending.size == topic.remote_size


def _find_pending_install(
    vault: Vault, destination: Path, topic: TopicRecord
) -> _PendingInstall | None:
    """Find a validated install left by a prior sync, rejecting stale or untrusted markers."""
    expected_destination = paths.rel_posix(destination, vault.root)
    prefix = f".{destination.name}."
    try:
        with os.scandir(os.fspath(paths.long_path(destination.parent))) as iterator:
            candidates = sorted(entry.name for entry in iterator)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise A2LError("pending download state is unreadable") from exc

    for name in candidates:
        if not name.startswith(prefix) or not name.endswith(_PENDING_INSTALL_SUFFIX):
            continue
        marker = destination.parent / name
        part = destination.parent / name[: -len(_PENDING_MARKER_SUFFIX)]
        pending = _read_pending_install(marker, part)
        if pending is None:
            _remove_pending_paths(marker, part)
            continue
        if pending.destination == expected_destination and pending.source_key != topic.source_key:
            _remove_pending_install(pending)
            continue
        if pending.source_key != topic.source_key or pending.destination != expected_destination:
            continue
        if not _pending_matches_topic(pending, topic) or not _is_safe_local_file(pending.part):
            _remove_pending_install(pending)
            continue
        actual_hash, actual_size = _hash_file(pending.part)
        if actual_hash != pending.sha256 or actual_size != pending.size:
            _remove_pending_install(pending)
            continue
        return pending
    return None


def _retry_pending_install(
    vault: Vault,
    course_dir: Path,
    school: School,
    topic: TopicRecord,
    destination: Path,
    prior: ManifestEntry | None,
    pending: _PendingInstall,
) -> Literal["downloaded"] | None:
    """Install a previously validated part; return ``None`` when it is stale and was removed."""
    if pending.prior_sha256 is None:
        if prior is not None and pending.sha256 != prior.sha256:
            _remove_pending_install(pending)
            return None
    elif prior is None or pending.prior_sha256 != prior.sha256:
        _remove_pending_install(pending)
        return None

    if pending.prior_sha256 is not None and not pending.revision_preserved:
        if prior is None:
            _remove_pending_install(pending)
            return None
        preserved = vault.preserve_revision(topic.source_key, changed_at=clock.now())
        if preserved is None and paths.long_path(vault.materialized(prior)).exists():
            raise A2LError("current source could not be preserved; refusing replacement")
        pending = replace(pending, revision_preserved=True)
        _write_pending_install(pending)

    paths.atomic_install_temp(destination, pending.part)
    entry = _manifest_entry_for_install(
        vault,
        topic,
        destination=destination,
        prior=prior,
        sha256=pending.sha256,
        size=pending.size,
        etag=pending.etag,
        last_modified=pending.last_modified,
    )
    vault.mark(topic.source_key, entry)
    vault.save_manifest()
    _mark_topic_source_only(vault, course_dir, topic, school)
    _remove_pending_install(pending)
    return "downloaded"


def _manifest_entry_for_install(
    vault: Vault,
    topic: TopicRecord,
    *,
    destination: Path,
    prior: ManifestEntry | None,
    sha256: str,
    size: int,
    etag: str | None,
    last_modified: str | None,
) -> ManifestEntry:
    return ManifestEntry(
        path=paths.rel_posix(destination, vault.root),
        sha256=sha256,
        source_id=topic.source_id,
        etag=etag,
        last_modified=last_modified,
        size=size,
        fetched_at=_now(),
        derived=prior.derived if prior is not None and sha256 == prior.sha256 else {},
    )


def _download_with_candidates(
    client: Client,
    school: School,
    topic: TopicRecord,
    temporary: Path,
    *,
    prior: ManifestEntry | None,
    max_bytes: int | None,
) -> DownloadResult:
    candidates = _download_candidates(client, school, topic)
    last_error: DownloadError | None = None
    for candidate in candidates:
        try:
            kwargs: dict[str, object] = {
                "prior": prior,
                "is_html_topic": topic.kind.casefold() == "html"
                or (topic.url_path or "").casefold().endswith((".html", ".htm")),
            }
            kwargs["max_bytes"] = max_bytes
            return client.download(candidate, temporary, **kwargs)  # type: ignore[arg-type]
        except SessionExpired:
            raise
        except DownloadError as exc:
            last_error = exc
            _remove_quietly(temporary)
        except RequestException:
            last_error = DownloadError("download route returned an unusable response")
            _remove_quietly(temporary)
    if last_error is not None:
        raise last_error
    raise DownloadError("no first-party download route was available")


def _download_candidates(client: Client, school: School, topic: TopicRecord) -> list[str]:
    base = school.base_url.rstrip("/")
    le = getattr(client, "le_version", None)
    ou = topic.course_org_unit_id
    tid = topic.topic_id
    candidates: list[str] = []
    if ":attachment:" in topic.source_key and topic.url_path is not None:
        return [urljoin(base + "/", topic.url_path.lstrip("/"))]
    template = client.download_template
    if isinstance(template, str) and template:
        with suppress(KeyError, ValueError):
            candidates.append(template.format(base=base, le=le or "", ou=ou, tid=tid))
    candidates.extend(
        [
            f"{base}/d2l/le/content/{ou}/topics/files/download/{tid}/DirectFileTopicDownload",
            f"{base}/d2l/api/le/{le}/{ou}/content/topics/{tid}/file"
            if isinstance(le, str) and le
            else "",
        ]
    )
    if topic.url_path is not None:
        candidates.append(urljoin(base + "/", topic.url_path.lstrip("/")))
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _destination_for_topic(
    vault: Vault, course_dir: Path, topic: TopicRecord, prior: ManifestEntry | None
) -> Path:
    if prior is not None:
        return vault.materialized(prior)
    if topic.source_path is None:
        raise A2LError("topic has no allocated source path")
    return _vault_relative_path(vault, topic.source_path)


def _unchanged_local(entry: ManifestEntry, topic: TopicRecord, vault: Vault) -> bool:
    if topic.etag is None and topic.last_modified is None:
        return False
    if topic.etag is not None and entry.etag != topic.etag:
        return False
    if topic.last_modified is not None and entry.last_modified != topic.last_modified:
        return False
    source = vault.materialized(entry)
    if not paths.long_path(source).is_file():
        return False
    actual_hash, actual_size = _hash_file(source)
    return actual_hash == entry.sha256 and actual_size == entry.size


def _mark_topic_source_only(
    vault: Vault,
    course_dir: Path,
    topic: TopicRecord,
    school: School,
) -> None:
    rows = _map_topics(_read_content_map(course_dir))
    # A manifest artifact record is not proof that the current twin bytes are still trusted.
    # Reconcile through the same source-and-derived hash checks used by metadata sync.
    reconciled = course_index.reconcile_content_map(vault, rows)
    _write_content_map(course_dir, reconciled)
    course = CourseRef(
        topic.course_org_unit_id,
        topic.course_code,
        topic.course_name,
        topic.term,
        True,
    )
    topics = tuple(
        _topic_from_row(row, course=course) for row in reconciled if isinstance(row, dict)
    )
    _write_index(course_dir, school=school, course=course, topics=topics)


def _update_row_state(course_dir: Path, source_key: str, **updates: object) -> None:
    content_map = _read_content_map(course_dir)
    rows = _map_topics(content_map)
    for row in rows:
        if isinstance(row, dict) and row.get("source_key") == source_key:
            row.update(updates)
    _write_content_map(course_dir, rows)


def _find_content_row(course_dir: Path, source_key: str) -> dict[str, object] | None:
    for row in _map_topics(_read_content_map(course_dir)):
        if isinstance(row, dict) and row.get("source_key") == source_key:
            return row
    return None


def _resolve_topic(vault: Vault, query: str) -> tuple[CourseRef, TopicRecord, Path] | None:
    if not isinstance(query, str) or not query.strip():
        raise A2LError("topic selector must not be empty")
    exact: list[tuple[CourseRef, TopicRecord, Path]] = []
    fuzzy: list[tuple[CourseRef, TopicRecord, Path]] = []
    folded = query.casefold()
    for map_path in sorted(
        path for path in paths.walk(vault.root) if path.name == "content_map.json"
    ):
        course_dir = map_path.parent.parent
        raw = _read_content_map(course_dir)
        for row in _map_topics(raw):
            if not isinstance(row, dict):
                continue
            try:
                course = CourseRef(
                    int(row["course_org_unit_id"]),
                    str(row["course_code"]),
                    str(row["course_name"]),
                    row.get("term") if isinstance(row.get("term"), str) else None,
                    True,
                )
                record = _topic_from_row(row, course=course)
            except (KeyError, TypeError, ValueError, A2LError):
                continue
            candidate = (course, record, course_dir)
            if query in {record.source_key, record.source_id} or query == record.source_path:
                exact.append(candidate)
            elif folded in record.title.casefold() or (
                record.path is not None and folded in record.path.casefold()
            ):
                fuzzy.append(candidate)
    if exact:
        if len(exact) > 1:
            raise A2LError(f"ambiguous topic selector: {query}")
        return exact[0]
    if len(fuzzy) > 1:
        raise A2LError(f"ambiguous topic selector: {query}")
    return fuzzy[0] if fuzzy else None


def _read_content_map(course_dir: Path) -> dict[str, object]:
    return course_index.read_content_map(course_dir)


def _map_topics(content_map: Mapping[str, object]) -> list[object]:
    topics = content_map.get("topics")
    if not isinstance(topics, list):
        raise A2LError("content_map.json topics must be an array")
    return topics


def _write_content_map(course_dir: Path, rows: Sequence[object]) -> None:
    course_index.write_content_map(course_dir, rows)


def _write_toc(course_dir: Path, modules: Sequence[dict[str, object]]) -> None:
    _write_json(course_dir / "_meta" / "toc.json", {"schema_version": 1, "modules": list(modules)})


def _read_toc_modules(course_dir: Path) -> list[dict[str, object]]:
    destination = course_dir / "_meta" / "toc.json"
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A2LError(f"{destination.name} is unreadable") from exc
    if not isinstance(raw, dict):
        raise A2LError(f"{destination.name} must contain an object")
    modules = raw.get("modules")
    if not isinstance(modules, list):
        raise A2LError(f"{destination.name} must contain a modules list")
    if any(not isinstance(value, dict) for value in modules):
        raise A2LError(f"{destination.name} contains an invalid module")
    return [cast(dict[str, object], value) for value in modules]


def _write_json(destination: Path, payload: object) -> None:
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )
    paths.atomic_write_text(destination, text)


def _read_list(destination: Path) -> list[dict[str, object]]:
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A2LError(f"{destination.name} is unreadable") from exc
    if not isinstance(raw, list):
        raise A2LError(f"{destination.name} must contain a list")
    if any(not isinstance(row, dict) for row in raw):
        raise A2LError(f"{destination.name} contains an invalid item")
    return [cast(dict[str, object], row) for row in raw]


def _write_list(destination: Path, rows: Sequence[Mapping[str, object]]) -> None:
    _write_json(destination, list(rows))


def _merge_rows(
    existing: Sequence[Mapping[str, object]],
    incoming: Sequence[Mapping[str, object]],
    *,
    id_field: str,
    complete: bool,
) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for row in existing:
        value = row.get(id_field)
        if value is not None:
            by_id[str(value)] = dict(row)
    incoming_ids: set[str] = set()
    for row in incoming:
        value = row.get(id_field)
        if value is None:
            continue
        key = str(value)
        incoming_ids.add(key)
        merged = dict(by_id.get(key, {}))
        merged.update(row)
        merged["missing_since"] = None
        merged["withdrawn_at"] = None
        by_id[key] = merged
    if complete:
        now = _now()
        for key, row in by_id.items():
            if key in incoming_ids:
                continue
            if row.get("missing_since") is None:
                row["missing_since"] = now
            elif row.get("withdrawn_at") is None:
                row["withdrawn_at"] = now
    return sorted(
        by_id.values(), key=lambda row: (_date_key(row.get("date")), str(row.get(id_field)))
    )


def _project_assignments(values: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("Id"), int)
            or isinstance(value.get("Id"), bool)
        ):
            continue
        availability = value.get("Availability")
        rows.append(
            {
                "id": value["Id"],
                "title": _safe_text(value.get("Name")),
                "due_date": _optional_text(value.get("DueDate")),
                "start_date": _nested_optional_text(availability, "StartDate"),
                "end_date": _nested_optional_text(availability, "EndDate"),
                "grade_item": isinstance(value.get("GradeItemId"), int),
                "group": isinstance(value.get("GroupTypeId"), int),
                "date": _optional_text(value.get("DueDate")) or "",
            }
        )
    return rows


def _project_news(values: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("Id"), int)
            or isinstance(value.get("Id"), bool)
        ):
            continue
        body = value.get("Body")
        body_text = body.get("Text") if isinstance(body, dict) else None
        body_html = body.get("Html") if isinstance(body, dict) else None
        start = _optional_text(value.get("StartDate")) or ""
        rows.append(
            {
                "id": value["Id"],
                "title": _safe_text(value.get("Title")),
                "text": _safe_text(body_text),
                "html": _sanitize_html_text(body_html) if isinstance(body_html, str) else None,
                "start_date": _optional_text(value.get("StartDate")),
                "end_date": _optional_text(value.get("EndDate")),
                "published": bool(value.get("IsPublished", False)),
                "date": start,
            }
        )
    return rows


def _project_quizzes(values: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("QuizId"), int)
            or isinstance(value.get("QuizId"), bool)
        ):
            continue
        due = _optional_text(value.get("DueDate"))
        rows.append(
            {
                "id": value["QuizId"],
                "title": _safe_text(value.get("Name")),
                "due_date": due,
                "start_date": _optional_text(value.get("StartDate")),
                "end_date": _optional_text(value.get("EndDate")),
                "active": bool(value.get("IsActive", False)),
                "date": due or "",
            }
        )
    return rows


def _project_grades(values: Sequence[object]) -> list[dict[str, object]]:
    # Grades are opt-in, but the projection still excludes all unrelated response fields.
    rows: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        identifier = value.get("GradeObjectIdentifier")
        if identifier is None:
            continue
        rows.append(
            {
                "id": str(identifier),
                "name": _safe_text(value.get("GradeObjectName")),
                "type": _safe_text(value.get("GradeObjectType")),
                "numerator": value.get("PointsNumerator"),
                "denominator": value.get("PointsDenominator"),
                "displayed": _safe_text(value.get("DisplayedGrade")),
            }
        )
    return rows


def _write_announcements(destination: Path, rows: Sequence[Mapping[str, object]]) -> None:
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    lines = ["# Announcements", ""]
    for row in rows:
        title = str(row.get("title") or "Untitled")
        date = str(row.get("start_date") or "")
        lines.extend([f"## {title}", "", f"Date: {date}" if date else "", ""])
        if row.get("withdrawn_at"):
            lines.extend(["> No longer posted in LEARN.", ""])
        text = str(row.get("text") or "").strip()
        if text:
            lines.extend([text, ""])
    paths.atomic_write_text(destination, "\n".join(lines).rstrip() + "\n")


def _write_index(
    course_dir: Path,
    *,
    school: School | None,
    course: CourseRef | None,
    topics: Sequence[TopicRecord] | None,
) -> None:
    if school is None or course is None or topics is None:
        # A file-only checkpoint updates the coverage tree without needing to retain a second
        # network response in memory. The existing index remains valid until metadata runs again.
        return
    term_label = school.term_label(course.term) if course.term else "Unclassified"
    assignments = _read_list(course_dir / "_meta" / "assignments.json")
    quizzes = _read_list(course_dir / "_meta" / "quizzes.json")
    deadlines = [
        (str(row.get("due_date")), str(row.get("title") or "Untitled"), "assignment")
        for row in assignments
        if row.get("due_date")
    ] + [
        (str(row.get("due_date")), str(row.get("title") or "Untitled"), "quiz")
        for row in quizzes
        if row.get("due_date")
    ]
    course_index.write_course_index(
        course_dir,
        course_code=course.code,
        course_name=course.name,
        term_label=term_label,
        term_code=course.term,
        topics=[_topic_to_row(topic) for topic in topics],
        deadlines=deadlines,
    )


def _course_relative_link(value: str, course_dir: Path) -> str:
    parts = list(PurePosixPath(value).parts)
    try:
        index = parts.index(course_dir.name)
    except ValueError:
        return PurePosixPath(value).as_posix()
    relative = parts[index + 1 :]
    return PurePosixPath(*relative).as_posix() if relative else "."


def _content_directory(course_dir: Path, module_path: Sequence[str]) -> Path:
    directory = course_dir / _COURSE_CONTENT
    for component in module_path:
        directory /= paths.safe_name(component)
    return directory


def _extension(name: str) -> str:
    """Return a usable extension, treating a bare trailing dot as no extension.

    Python 3.14 changed ``PurePath.suffix``: ``'Reading list.'`` now reports ``'.'`` where
    earlier versions report ``''``. Taken at face value that lone dot looks like an
    extension, so a topic titled with a trailing dot keeps no real extension and the file
    lands with none at all — a different vault on 3.14 than on 3.11. A single dot is not an
    extension on any version, so it is normalized away here rather than at each call site.
    """
    suffix = PurePosixPath(name).suffix
    return suffix if len(suffix) > 1 else ""


def _topic_filename(topic: TopicRecord) -> str:
    title = topic.title.strip() or "untitled"
    title_path = PurePosixPath(title).name
    url_name = PurePosixPath(urlsplit(topic.url_path or "").path).name
    title_suffix = _extension(title_path)
    suffix = title_suffix or _extension(url_name)
    base = title_path if title_suffix else f"{title_path}{suffix}"
    return paths.safe_name(base)


def _unique_reserved(destination: Path, reserved: set[str]) -> Path:
    candidate = paths.unique_path(destination)
    for number in range(1, 100_000):
        if _canonical_name(candidate) not in reserved and not paths.collides(candidate):
            reserved.add(_canonical_name(candidate))
            return candidate
        stem, extension = _split_name(candidate.name)
        suffix = "" if number == 1 else f"_{number}"
        candidate = candidate.with_name(paths.safe_name(f"{stem}{suffix}{extension}"))
    raise A2LError("could not allocate a unique content path")


def _canonical_name(path: Path) -> str:
    return path.name.casefold()


def _split_name(name: str) -> tuple[str, str]:
    # ``_extension`` rather than ``.suffix``: a collision suffix must be inserted at the
    # same place on every Python version (see the 3.14 note there).
    suffix = _extension(name)
    return (name[: -len(suffix)], suffix) if suffix else (name, "")


def _vault_relative_path(vault: Vault, value: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(value).parts)
    ):
        raise A2LError("content path must be a normalized relative POSIX path")
    candidate = (vault.root / Path(*PurePosixPath(value).parts)).resolve()
    try:
        candidate.relative_to(vault.root)
    except ValueError as exc:
        raise A2LError("content path escapes the vault root") from exc
    return candidate


def _derived_path(manifest: Mapping[str, ManifestEntry], entry: ManifestEntry) -> str | None:
    artifact = entry.derived.get("markdown")
    if artifact is None:
        return None
    return artifact.path if artifact.path else None


def _is_media(topic: TopicRecord) -> bool:
    return PurePosixPath(_topic_filename(topic)).suffix.casefold() in _MEDIA_SUFFIXES


def is_media_topic(topic: TopicRecord) -> bool:
    """Return the canonical media classification used by file ingestion and previews."""

    return _is_media(topic)


def _is_office_lock(topic: TopicRecord) -> bool:
    filename = _topic_filename(topic)
    url_name = PurePosixPath(urlsplit(topic.url_path or "").path).name
    return bool(_OFFICE_LOCK.match(filename) or _OFFICE_LOCK.match(url_name))


def _safe_hostname(value: str | None) -> str | None:
    if not value:
        return None
    try:
        hostname = urlsplit(value).hostname
        if hostname is None:
            return None
        return hostname.encode("idna").decode("ascii").casefold().rstrip(".")
    except (UnicodeError, ValueError):
        return None


def _first_party_path(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    try:
        candidate = urljoin(base_url.rstrip("/") + "/", value)
        parsed = urlsplit(candidate)
        base = urlsplit(base_url)
        if parsed.scheme.casefold() not in {"http", "https"}:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = _safe_hostname(candidate)
        base_host = _safe_hostname(base_url)
        if host != base_host or parsed.port != base.port:
            return None
        path = parsed.path or "/"
        return urlunsplit(("", "", path, "", ""))
    except (TypeError, ValueError):
        return None


def _allowed_outline_url(value: str | None, school: School) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or not hostname_matches_suffix(value, school.outline_hosts())
        ):
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path or "/", "", ""))
    except (TypeError, ValueError):
        return None


def _view_url(school: School, org_unit_id: int, topic_id: int) -> str:
    return f"{school.base_url.rstrip('/')}/d2l/le/content/{org_unit_id}/viewContent/{topic_id}/View"


def _safe_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _nested_optional_text(value: object, key: str) -> str | None:
    return _optional_text(value.get(key)) if isinstance(value, dict) else None


class _RichTextSanitizer(HTMLParser):
    """Render inert, deterministic HTML without executing or retaining active attributes."""

    _ALLOWED_TAGS = frozenset(
        {
            "a",
            "b",
            "blockquote",
            "br",
            "code",
            "dd",
            "div",
            "em",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "hr",
            "img",
            "li",
            "ol",
            "p",
            "pre",
            "section",
            "span",
            "strong",
            "table",
            "tbody",
            "td",
            "th",
            "thead",
            "tr",
            "u",
            "ul",
        }
    )
    _VOID_TAGS = frozenset({"br", "hr", "img"})

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self._skip_depth:
            if tag not in self._VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in {"script", "style", "form", "iframe", "object", "embed", "template"}:
            self._skip_depth = 1
            return
        if tag not in self._ALLOWED_TAGS:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name = name.casefold()
            if name == "href" and tag == "a" and value is not None:
                safe_url = _safe_richtext_url(value, self.base_url)
                if safe_url is not None:
                    safe_attrs.append(f'href="{escape(safe_url, quote=True)}"')
            elif name in {"alt", "title"} and value is not None and tag in {"a", "img"}:
                safe_attrs.append(f'{name}="{escape(value, quote=True)}"')
        suffix = "" if not safe_attrs else " " + " ".join(safe_attrs)
        self.parts.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self._ALLOWED_TAGS and tag not in self._VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&#{name};")

    def handle_comment(self, _data: str) -> None:
        return


def _sanitize_richtext(value: str, base_url: str) -> str:
    parser = _RichTextSanitizer(base_url)
    try:
        parser.feed(value)
        parser.close()
    except (TypeError, ValueError):
        return ""
    return "".join(parser.parts).strip()


def _safe_richtext_url(value: str, base_url: str) -> str | None:
    try:
        candidate = urljoin(base_url.rstrip("/") + "/", value)
        parsed = urlsplit(candidate)
        if parsed.scheme.casefold() not in {"http", "https"}:
            return None
        if parsed.username is not None or parsed.password is not None or parsed.hostname is None:
            return None
        # RichText links are inert and query-free. They are never followed by conversion or sync.
        return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path or "/", "", ""))
    except (TypeError, ValueError):
        return None


def _richtext_markdown(title: str, sanitized_html: str) -> str:
    body = re.sub(r"(?s)<br\s*/?>", "\n", sanitized_html, flags=re.IGNORECASE)
    body = re.sub(r"(?s)</(?:p|div|h[1-6]|li|tr|blockquote)>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"(?s)<[^>]+>", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = body.strip()
    return f"# {title}\n\n{body}\n"


def _sanitize_html_text(value: str) -> str:
    # News remains a typed projection; unlike assignment instructions it does not become an
    # evidence-bearing source/twin, so retain a compact plain-text rendering only.
    text = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def _now() -> str:
    return clock.stamp()


def _date_key(value: object) -> str:
    return value if isinstance(value, str) else ""


def _timestamp_sort(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return parse_api_timestamp(value).timestamp()
    except ValueError:
        return 0.0


def _hash_file(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with open(os.fspath(paths.long_path(path)), "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(os.fspath(paths.long_path(path)))
    except OSError:
        return


def _safe_error(stage: str, exc: BaseException) -> str:
    # Reports are intentionally category-level. Never include URL, title, path, or response text.
    return f"{stage}: {type(exc).__name__}"


def _ingest_discussions(
    client: Client,
    course: CourseRef,
    course_dir: Path,
    vault: Vault,
    *,
    include_authors: bool,
) -> str | None:
    """Fetch opt-in discussions while keeping raw author identity out of the vault."""

    values, complete, error = _fetch_collection(
        client, _endpoint_path(client, course, "discussions/forums/")
    )
    if error is not None:
        return _safe_error("discussions", error)
    if not complete:
        return _safe_error("discussions", A2LError("incomplete response"))
    if any(
        not isinstance(value, dict) or not _discussion_forum_is_valid(value) for value in values
    ):
        return _safe_error("discussions", A2LError("metadata endpoint returned an invalid forum"))
    forum_ids = [value["ForumId"] for value in values if isinstance(value, dict)]
    if len({str(value) for value in forum_ids}) != len(forum_ids):
        return _safe_error("discussions", A2LError("metadata endpoint returned duplicate forums"))
    try:
        existing_rows = _read_discussion_rows(course_dir / "_meta" / "discussions.json")
    except A2LError as exc:
        return _safe_error("discussions", exc)
    key = _discussion_key(vault)
    posts = [
        post for value in values if isinstance(value, dict) for post in _discussion_posts(value)
    ]
    identities = {
        identity for post in posts if (identity := _discussion_identity(post)) is not None
    }
    pseudonyms = _discussion_pseudonyms(key, identities)
    incoming_rows: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("ForumId"), int):
            continue
        description = value.get("Description")
        description_text = _discussion_body_text(description, school_base=client.school.base_url)
        forum_row: dict[str, object] = {
            "id": value["ForumId"],
            "name": _safe_text(value.get("Name")),
            "description": description_text,
        }
        rendered_posts: list[dict[str, object]] = []
        for post in _discussion_posts(value):
            identity = _discussion_identity(post)
            body = _discussion_body_text(post.get("Body", post), school_base=client.school.base_url)
            author = _discussion_author(post, identity, pseudonyms, include_authors)
            rendered_posts.append(
                {
                    "id": _discussion_post_id(post),
                    "author": author,
                    "text": body,
                    "date": _first_string(post, "Date", "PostingDate", "LastModifiedDate"),
                }
            )
        if rendered_posts:
            forum_row["posts"] = rendered_posts
        incoming_rows.append(forum_row)

    rows = _merge_discussion_rows(existing_rows, incoming_rows)
    _write_list(course_dir / "_meta" / "discussions.json", rows)
    markdown_lines = ["# Discussions", ""]
    for forum_row in rows:
        markdown_lines.extend([f"## {forum_row['name'] or 'Untitled forum'}", ""])
        description_text = str(forum_row.get("description") or "")
        if description_text:
            markdown_lines.extend([description_text, ""])
        if forum_row.get("withdrawn_at"):
            markdown_lines.extend(["> No longer posted in LEARN.", ""])
        raw_posts = forum_row.get("posts", [])
        for post in raw_posts if isinstance(raw_posts, list) else []:
            if not isinstance(post, dict):
                continue
            markdown_lines.extend(
                [
                    f"### {post.get('author') or 'author-unknown'}",
                    "",
                    str(post.get("text") or ""),
                    "",
                ]
            )

    discussion_dir = course_dir / "discussions"
    paths.long_path(discussion_dir).mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(discussion_dir / "discussions.md", "\n".join(markdown_lines))
    return None


def _discussion_key(vault: Vault) -> bytes:
    private = vault.state() / "private"
    paths.long_path(private).mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = private / "discussion-hmac.key"
    try:
        with open(os.fspath(paths.long_path(destination)), "rb") as handle:
            key = handle.read()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        paths.atomic_write_bytes(destination, key)
    if len(key) != 32:
        raise A2LError("discussion pseudonym key is invalid")
    return key


def _discussion_posts(forum: Mapping[str, object]) -> list[dict[str, object]]:
    raw_topics = forum.get("Topics", forum.get("topics", []))
    if isinstance(raw_topics, dict):
        raw_topics = raw_topics.get("Items", raw_topics.get("Objects", []))
    raw_posts: list[object] = []
    if isinstance(raw_topics, list):
        for topic in raw_topics:
            if isinstance(topic, dict):
                posts = topic.get("Posts", topic.get("posts", []))
                if isinstance(posts, list):
                    raw_posts.extend(posts)
    direct_posts = forum.get("Posts", forum.get("posts", []))
    if isinstance(direct_posts, list):
        raw_posts.extend(direct_posts)
    return [post for post in raw_posts if isinstance(post, dict)]


def _read_discussion_rows(destination: Path) -> list[dict[str, object]]:
    rows = _read_list(destination)
    validated: list[dict[str, object]] = []
    seen_forums: set[str] = set()
    for row in rows:
        identifier = row.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, int):
            raise A2LError("discussions.json contains an invalid forum ID")
        forum_key = str(identifier)
        if forum_key in seen_forums:
            raise A2LError("discussions.json contains duplicate forum IDs")
        seen_forums.add(forum_key)
        raw_posts = row.get("posts", [])
        if not isinstance(raw_posts, list) or any(
            not isinstance(post, dict) or not _discussion_post_is_valid(post) for post in raw_posts
        ):
            raise A2LError("discussions.json contains invalid posts")
        post_ids = [str(post["id"]) for post in raw_posts if isinstance(post, dict)]
        if len(set(post_ids)) != len(post_ids):
            raise A2LError("discussions.json contains duplicate post IDs")
        validated.append(dict(row))
    return validated


def _merge_discussion_rows(
    existing: Sequence[Mapping[str, object]], incoming: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Union complete discussion captures by forum and post ID without deleting history."""
    by_forum: dict[str, dict[str, object]] = {
        str(row["id"]): dict(row) for row in existing if isinstance(row.get("id"), int)
    }
    incoming_forums: set[str] = set()
    for row in incoming:
        forum_id = row.get("id")
        if isinstance(forum_id, bool) or not isinstance(forum_id, int):
            raise A2LError("discussion capture contains an invalid forum ID")
        forum_key = str(forum_id)
        incoming_forums.add(forum_key)
        prior = by_forum.get(forum_key, {})
        merged = dict(prior)
        for field, value in row.items():
            if field == "posts":
                continue
            if field in {"name", "description"} and not value and prior.get(field):
                continue
            merged[field] = value
        old_posts = prior.get("posts", [])
        new_posts = row.get("posts", [])
        merged["posts"] = _merge_rows(
            old_posts if isinstance(old_posts, list) else [],
            new_posts if isinstance(new_posts, list) else [],
            id_field="id",
            complete=True,
        )
        merged["missing_since"] = None
        merged["withdrawn_at"] = None
        by_forum[forum_key] = merged

    now = _now()
    for forum_key, row in by_forum.items():
        if forum_key in incoming_forums:
            continue
        if row.get("missing_since") is None:
            row["missing_since"] = now
        elif row.get("withdrawn_at") is None:
            row["withdrawn_at"] = now
    return sorted(by_forum.values(), key=lambda row: str(row.get("id")))


def _discussion_forum_is_valid(forum: Mapping[str, object]) -> bool:
    """Validate nested discussion containers before replacing a prior capture."""
    raw_topics = forum.get("Topics", forum.get("topics", []))
    if "Topics" in forum or "topics" in forum:
        if isinstance(raw_topics, dict):
            raw_topics = raw_topics.get("Items", raw_topics.get("Objects"))
        if not isinstance(raw_topics, list) or any(
            not isinstance(topic, dict) for topic in raw_topics
        ):
            return False
        for topic in raw_topics:
            if "Posts" not in topic and "posts" not in topic:
                return False
            raw_posts = topic.get("Posts", topic.get("posts", []))
            if not isinstance(raw_posts, list) or any(
                not isinstance(post, dict) or not _discussion_post_is_valid(post)
                for post in raw_posts
            ):
                return False

    direct_posts = forum.get("Posts", forum.get("posts", []))
    if ("Posts" in forum or "posts" in forum) and (
        not isinstance(direct_posts, list)
        or any(
            not isinstance(post, dict) or not _discussion_post_is_valid(post)
            for post in direct_posts
        )
    ):
        return False
    posts = _discussion_posts(forum)
    post_ids = [str(_discussion_post_id(post)) for post in posts]
    return len(set(post_ids)) == len(post_ids)


def _discussion_post_is_valid(post: Mapping[str, object]) -> bool:
    identifier = _discussion_post_id(post)
    return identifier is not None and (not isinstance(identifier, str) or bool(identifier))


def _discussion_identity(post: Mapping[str, object]) -> str | None:
    author = post.get("Author", post.get("author", post.get("User", post.get("user"))))
    if isinstance(author, dict):
        for key in ("Identifier", "UserId", "AuthorId", "Id", "id"):
            value = author.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                return f"id:{value}"
    for key in ("Identifier", "UserId", "AuthorId"):
        value = post.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return f"id:{value}"
    candidates: list[object] = [author, post]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("DisplayName", "Name", "UserName", "name"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                normalized = unicodedata.normalize("NFKC", value)
                normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
                return f"name:{normalized}"
    return None


def _discussion_pseudonyms(key: bytes, identities: Iterable[str]) -> dict[str, str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for identity in identities:
        digest = hmac.new(key, identity.encode("utf-8"), "sha256").hexdigest()
        grouped[digest[:20]].append(identity)
    result: dict[str, str] = {}
    for digest, values in grouped.items():
        for identity in sorted(values):
            suffix = ""
            if len(values) > 1:
                suffix = "-" + sha256(identity.encode("utf-8")).hexdigest()[:16]
            result[identity] = f"author-{digest}{suffix}"
    return result


def _discussion_author(
    post: Mapping[str, object],
    identity: str | None,
    pseudonyms: Mapping[str, str],
    include_authors: bool,
) -> str:
    if include_authors:
        author = post.get("Author", post.get("author", post.get("User", post.get("user"))))
        if isinstance(author, dict):
            return (
                _first_string(author, "DisplayName", "Name", "UserName")
                or _first_string(post, "DisplayName", "Name")
                or "unknown-author"
            )
    return pseudonyms.get(identity or "", "author-unknown")


def _discussion_post_id(post: Mapping[str, object]) -> str | int | None:
    for key in ("PostId", "Id", "id"):
        value = post.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return value
    return None


def _discussion_body_text(value: object, *, school_base: str) -> str:
    if isinstance(value, dict):
        html_value = _first_string(value, "Html", "HTML", "html")
        text_value = _first_string(value, "Text", "text")
        value = html_value if html_value is not None else text_value
    if not isinstance(value, str):
        return ""
    sanitized = _sanitize_richtext(value, school_base)
    return _richtext_markdown("", sanitized).split("\n\n", 1)[-1].strip()


def _update_course_index_from_map(course_dir: Path) -> None:
    del course_dir


__all__ = [
    "CourseMetadata",
    "FetchReport",
    "FileReport",
    "MetadataReport",
    "OutlineReport",
    "TopicRecord",
    "fetch_topic",
    "is_media_topic",
    "ingest_files",
    "ingest_metadata",
    "load_metadata_topics",
]
