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
        if self.status == "unavailable" and self.http_status != 403:
            raise ValueError("unavailable quiz coverage requires HTTP 403")
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


def write_quiz_coverage(course_dir: Path, coverage: QuizCoverage, *, root: Path) -> None:
    fields = {key: value for key, value in asdict(coverage).items() if value is not None}
    payload = {"schema_version": 1, "collections": {"quizzes": fields}}
    paths.atomic_write_text(
        course_dir / "_meta" / "metadata_coverage.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        root=root,
    )


def read_quiz_coverage(course_dir: Path) -> QuizCoverage:
    destination = course_dir / "_meta" / "metadata_coverage.json"
    if paths.has_link_component(destination):
        return QuizCoverage()
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
            return QuizCoverage()
        if payload["schema_version"] != 1 or not isinstance(payload.get("collections"), dict):
            return QuizCoverage()
        fields = payload["collections"].get("quizzes")
        if not isinstance(fields, dict) or set(fields) - {
            "status",
            "http_status",
            "error_code",
            "permission",
        }:
            return QuizCoverage()
        return QuizCoverage(
            cast(CoverageStatus, fields.get("status")),
            fields.get("http_status"),
            fields.get("error_code"),
            fields.get("permission"),
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        return QuizCoverage()


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
