from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from requests import HTTPError

from agent2learn import paths
from agent2learn.vault import Vault

CoverageStatus = Literal["complete", "unavailable", "incomplete", "unknown"]
CollectionName = Literal["assignments", "news", "grades", "discussions"]
_OPTIONAL_COLLECTION_NAMES = ("assignments", "news", "grades", "discussions")
_OPTIONAL_COLLECTIONS = frozenset(_OPTIONAL_COLLECTION_NAMES)
_PERMISSION = "Quizzing.SeeQuizzing"
_PROBLEM_TYPE = "http://docs.valence.desire2learn.com/res/apiprop.html#not-authorized"


@dataclass(frozen=True)
class QuizCoverage:
    status: CoverageStatus = "unknown"
    http_status: int | None = None
    error_code: str | None = None
    permission: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"complete", "unavailable", "incomplete", "unknown"}:
            raise ValueError("invalid quiz coverage status")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 400 <= self.http_status <= 599
        ):
            raise ValueError("invalid quiz coverage HTTP status")
        if self.error_code not in {None, "not_authorized"} or self.permission not in {
            None,
            _PERMISSION,
        }:
            raise ValueError("unreviewed quiz coverage diagnostic")
        if self.status in {"complete", "unknown"} and any(
            value is not None for value in (self.http_status, self.error_code, self.permission)
        ):
            raise ValueError("unexpected quiz coverage diagnostic")
        if self.status == "unavailable" and self.http_status not in {403, 404}:
            raise ValueError("unavailable quiz coverage requires HTTP 403 or 404")
        if (self.error_code or self.permission) and self.status != "unavailable":
            raise ValueError("permission diagnostic requires unavailable quiz coverage")

    @property
    def gap(self) -> str | None:
        if self.status == "complete":
            return None
        label = {
            "unavailable": "quizzes unavailable",
            "incomplete": "quizzes metadata incomplete",
            "unknown": "quizzes coverage unknown",
        }[self.status]
        details = [f"HTTP {self.http_status}"] if self.http_status is not None else []
        details.extend(value for value in (self.error_code, self.permission) if value is not None)
        return label + (f" ({'; '.join(details)})" if details else "")


def quiz_coverage(complete: bool, error: Exception | None) -> QuizCoverage:
    if complete:
        return QuizCoverage("complete")
    response = error.response if isinstance(error, HTTPError) else None
    status = response.status_code if response is not None else None
    if status == 404:
        return QuizCoverage("unavailable", 404)
    if status != 403:
        return QuizCoverage("incomplete", http_status=status)
    error_code = None
    permission = None
    if response is not None and len(response.content) <= 8192:
        try:
            problem = response.json()
        except ValueError:
            problem = None
        if isinstance(problem, dict) and problem.get("type") == _PROBLEM_TYPE:
            error_code = "not_authorized"
            detail = problem.get("detail")
            if isinstance(detail, str) and re.search(
                r"securityVariableName:\s*Quizzing\.SeeQuizzing\s*\]", detail
            ):
                permission = _PERMISSION
    return QuizCoverage("unavailable", 403, error_code, permission)


@dataclass(frozen=True)
class CollectionCoverage:
    """Coverage state for an optional non-quiz metadata collection.

    An unavailable collection is different from a successfully fetched empty collection. D2L
    installations can omit optional tools entirely or deny an otherwise valid session access to
    one collection, so HTTP 403 and 404 are recorded as unavailable and do not prevent
    independently accessible course content from being archived. Other failed requests remain
    incomplete and are still fatal to the metadata phase.
    """

    status: CoverageStatus = "unknown"
    http_status: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"complete", "unavailable", "incomplete", "unknown"}:
            raise ValueError("invalid collection coverage status")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 400 <= self.http_status <= 599
        ):
            raise ValueError("invalid collection coverage HTTP status")
        if self.status in {"complete", "unknown"} and self.http_status is not None:
            raise ValueError("unexpected collection coverage diagnostic")
        if self.status == "unavailable" and self.http_status not in {403, 404}:
            raise ValueError("unavailable collection coverage requires HTTP 403 or 404")

    def gap(self, collection: str) -> str | None:
        if collection not in _OPTIONAL_COLLECTIONS:
            raise ValueError("unsupported optional metadata collection")
        if self.status == "complete":
            return None
        label = {
            "unavailable": f"{collection} unavailable",
            "incomplete": f"{collection} metadata incomplete",
            "unknown": f"{collection} coverage unknown",
        }[self.status]
        detail = f" (HTTP {self.http_status})" if self.http_status is not None else ""
        return label + detail


def collection_coverage(
    collection: CollectionName, complete: bool, error: BaseException | None
) -> CollectionCoverage:
    """Classify an optional collection without turning arbitrary failures into gaps."""

    if collection not in _OPTIONAL_COLLECTIONS:
        raise ValueError("unsupported optional metadata collection")
    if complete:
        return CollectionCoverage("complete")
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if type(status) is int and status in {403, 404}:
        return CollectionCoverage("unavailable", status)
    return CollectionCoverage(
        "incomplete",
        status if type(status) is int and 400 <= status <= 599 else None,
    )


def _read_coverage_collections(course_dir: Path) -> dict[str, dict[str, object]]:
    destination = course_dir / "_meta" / "metadata_coverage.json"
    if paths.has_link_component(destination):
        return {}
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("collections"), dict)
    ):
        return {}
    collections: dict[str, dict[str, object]] = {}
    for name, fields in payload["collections"].items():
        if not isinstance(name, str) or not isinstance(fields, dict):
            continue
        normalized: dict[str, object]
        if name == "quizzes":
            allowed = {"status", "http_status", "error_code", "permission"}
            if set(fields) - allowed:
                continue
            try:
                status = fields.get("status")
                http_status = fields.get("http_status")
                error_code = fields.get("error_code")
                permission = fields.get("permission")
                if not isinstance(status, str) or (
                    http_status is not None and type(http_status) is not int
                ):
                    continue
                if error_code is not None and not isinstance(error_code, str):
                    continue
                if permission is not None and not isinstance(permission, str):
                    continue
                quiz_coverage_value = QuizCoverage(
                    cast(CoverageStatus, status),
                    http_status,
                    error_code,
                    permission,
                )
            except (ValueError, TypeError):
                continue
            normalized = {
                key: value
                for key, value in asdict(quiz_coverage_value).items()
                if value is not None
            }
        elif name in _OPTIONAL_COLLECTIONS:
            if set(fields) - {"status", "http_status"}:
                continue
            try:
                status = fields.get("status")
                http_status = fields.get("http_status")
                if not isinstance(status, str) or (
                    http_status is not None and type(http_status) is not int
                ):
                    continue
                collection_coverage_value = CollectionCoverage(
                    cast(CoverageStatus, status), http_status
                )
            except (ValueError, TypeError):
                continue
            normalized = {
                key: value
                for key, value in asdict(collection_coverage_value).items()
                if value is not None
            }
        else:
            continue
        collections[name] = normalized
    return collections


def _write_coverage(
    course_dir: Path,
    collection: str,
    fields: dict[str, object],
    *,
    root: Path,
) -> None:
    existing = _read_coverage_collections(course_dir)
    existing[collection] = fields
    payload = {"schema_version": 1, "collections": existing}
    paths.atomic_write_text(
        course_dir / "_meta" / "metadata_coverage.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        root=root,
    )


def write_quiz_coverage(course_dir: Path, coverage: QuizCoverage, *, root: Path) -> None:
    fields = {key: value for key, value in asdict(coverage).items() if value is not None}
    _write_coverage(course_dir, "quizzes", fields, root=root)


def write_collection_coverage(
    course_dir: Path,
    collection: CollectionName,
    coverage: CollectionCoverage,
    *,
    root: Path,
) -> None:
    if collection not in _OPTIONAL_COLLECTIONS:
        raise ValueError("unsupported optional metadata collection")
    fields = {key: value for key, value in asdict(coverage).items() if value is not None}
    _write_coverage(course_dir, collection, fields, root=root)


def read_quiz_coverage(course_dir: Path) -> QuizCoverage:
    fields = _read_coverage_collections(course_dir).get("quizzes")
    if not isinstance(fields, dict) or set(fields) - {
        "status",
        "http_status",
        "error_code",
        "permission",
    }:
        return QuizCoverage()
    try:
        return QuizCoverage(
            cast(CoverageStatus, fields.get("status")),
            _stored_http_status(fields.get("http_status")),
            _stored_text(fields.get("error_code")),
            _stored_text(fields.get("permission")),
        )
    except (ValueError, TypeError):
        return QuizCoverage()


def read_collection_coverage(course_dir: Path, collection: CollectionName) -> CollectionCoverage:
    if collection not in _OPTIONAL_COLLECTIONS:
        raise ValueError("unsupported optional metadata collection")
    fields = _read_coverage_collections(course_dir).get(collection)
    if not isinstance(fields, dict) or set(fields) - {"status", "http_status"}:
        return CollectionCoverage()
    try:
        return CollectionCoverage(
            cast(CoverageStatus, fields.get("status")),
            _stored_http_status(fields.get("http_status")),
        )
    except (ValueError, TypeError):
        return CollectionCoverage()


def has_collection_coverage(course_dir: Path, collection: CollectionName) -> bool:
    if collection not in _OPTIONAL_COLLECTIONS:
        raise ValueError("unsupported optional metadata collection")
    return collection in _read_coverage_collections(course_dir)


def _stored_http_status(value: object) -> int | None:
    return value if type(value) is int else None


def _stored_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def vault_quiz_gaps(vault: Vault) -> tuple[str, ...]:
    if not paths.long_path(vault.root).is_dir():
        return ()
    return tuple(
        sorted(
            {
                gap
                for path in paths.walk(vault.root)
                if path.name == "content_map.json" and ".a2l" not in path.parts
                if (gap := read_quiz_coverage(path.parent.parent).gap) is not None
            }
        )
    )


def vault_metadata_gaps(vault: Vault) -> tuple[str, ...]:
    """Return recorded gaps for quiz and optional metadata collections.

    Legacy vaults have no non-quiz coverage records, so they retain their previous behaviour. A
    newly recorded unavailable/incomplete collection is included without treating a missing file
    as an empty collection.
    """

    if not paths.long_path(vault.root).is_dir():
        return ()
    gaps: set[str] = set(vault_quiz_gaps(vault))
    for path in paths.walk(vault.root):
        if path.name != "content_map.json" or ".a2l" in path.parts:
            continue
        course_dir = path.parent.parent
        for collection in _OPTIONAL_COLLECTION_NAMES:
            if not has_collection_coverage(course_dir, cast(CollectionName, collection)):
                continue
            coverage = read_collection_coverage(course_dir, cast(CollectionName, collection))
            if (gap := coverage.gap(collection)) is not None:
                gaps.add(gap)
    return tuple(sorted(gaps))
