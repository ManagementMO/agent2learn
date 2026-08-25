"""Instance calibration and metadata-only enrolment discovery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from agent2learn import config, paths
from agent2learn.api import Client
from agent2learn.errors import A2LError, NotConfigured

_CALIBRATION_FILENAME = "calibration.json"
_SCHEMA_VERSION = 1
_MAX_PAGES = 1000


@dataclass(frozen=True)
class CourseRef:
    """The typed, metadata-only projection needed to list one course offering."""

    org_unit_id: int
    code: str
    name: str
    term: str | None
    is_active: bool
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class Calibration:
    """The discovered API versions and metadata-only course inventory."""

    lp: str
    le: str
    download_template: str | None
    courses: list[CourseRef]
    calibrated_at: str | None = None


def calibrate(client: Client) -> Calibration:
    """Discover versions, verify the session, enumerate enrolments, and persist the result.

    Calibration intentionally makes no content, file, grades, or discussion request.  A download
    route is learned later, during a student-approved file transfer, rather than by a hidden body
    probe during authentication or onboarding.
    """

    versions = client.get_json("/d2l/api/versions/")
    lp, le = _versions(versions)
    client.lp_version = lp
    client.le_version = le

    whoami = client.get_json(f"/d2l/api/lp/{lp}/users/whoami")
    if not isinstance(whoami, dict) or not isinstance(whoami.get("Identifier"), str):
        raise A2LError("calibration could not verify the authenticated user")

    courses = _enumerate_courses(client, lp)
    previous_template = _previous_template()
    calibrated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result = Calibration(
        lp=lp,
        le=le,
        download_template=previous_template,
        courses=courses,
        calibrated_at=calibrated_at,
    )
    _write(result)
    return result


def load_calibration() -> Calibration:
    """Load calibration or give the single safe next action required to create it."""

    destination = config.state_dir() / _CALIBRATION_FILENAME
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError as exc:
        raise NotConfigured("calibration unavailable · run: a2l auth") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise NotConfigured("calibration is unreadable · run: a2l auth") from exc
    try:
        return _decode(raw)
    except (TypeError, ValueError, KeyError, A2LError) as exc:
        raise NotConfigured("calibration is invalid · run: a2l auth") from exc


def display_courses(value: Calibration, *, all_terms: bool = False) -> list[CourseRef]:
    """Return deterministic course offerings for the ``courses`` command.

    The default is deliberately conservative: only active, term-classified academic offerings
    are shown.  ``--all-terms`` exposes every discovered course offering, including inactive or
    not-yet-classified records, without making another network request.
    """

    selected = (
        value.courses
        if all_terms
        else [course for course in value.courses if course.is_active and course.term is not None]
    )
    return sorted(
        selected,
        key=lambda course: (
            course.term is None,
            course.term or "",
            course.code.casefold(),
            course.org_unit_id,
        ),
    )


def _versions(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, list):
        raise A2LError("version discovery returned an invalid response")
    found: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        product = item.get("ProductCode")
        version = item.get("LatestVersion")
        if isinstance(product, str) and isinstance(version, str) and version:
            found[product.casefold()] = version
    lp = found.get("lp")
    le = found.get("le")
    if lp is None or le is None:
        raise A2LError("version discovery did not advertise both lp and le")
    return lp, le


def _enumerate_courses(client: Client, lp: str) -> list[CourseRef]:
    courses: list[CourseRef] = []
    bookmark: str | None = None
    seen_bookmarks: set[str] = set()
    for _page in range(_MAX_PAGES):
        path = f"/d2l/api/lp/{lp}/enrollments/myenrollments/"
        if bookmark is not None:
            path += f"?bookmark={quote(bookmark, safe='')}"
        payload = client.get_json(path)
        if not isinstance(payload, dict):
            raise A2LError("enrolment discovery returned an invalid response")
        items = payload.get("Items")
        paging = payload.get("PagingInfo")
        if not isinstance(items, list) or not isinstance(paging, dict):
            raise A2LError("enrolment discovery returned an invalid page")
        for item in items:
            course = _course_from_item(client, item)
            if course is not None:
                courses.append(course)

        has_more = paging.get("HasMoreItems")
        if has_more is False:
            break
        if has_more is not True:
            raise A2LError("enrolment discovery returned an invalid paging marker")
        next_bookmark = paging.get("Bookmark")
        if not isinstance(next_bookmark, str) or not next_bookmark:
            raise A2LError("enrolment discovery advertised more pages without a bookmark")
        if next_bookmark in seen_bookmarks:
            raise A2LError("enrolment discovery pagination repeated a bookmark")
        seen_bookmarks.add(next_bookmark)
        bookmark = next_bookmark
    else:
        raise A2LError("enrolment discovery exceeded the pagination limit")

    return sorted(courses, key=lambda course: (course.code.casefold(), course.org_unit_id))


def _course_from_item(client: Client, raw: object) -> CourseRef | None:
    if not isinstance(raw, dict):
        raise A2LError("enrolment item is invalid")
    org_unit = raw.get("OrgUnit")
    if not isinstance(org_unit, dict):
        raise A2LError("enrolment item has no organization unit")
    type_info = org_unit.get("Type")
    type_code = type_info.get("Code") if isinstance(type_info, dict) else None
    if not isinstance(type_code, str) or type_code.casefold() != "course offering":
        return None

    org_unit_id = org_unit.get("Id")
    code = org_unit.get("Code")
    name = org_unit.get("Name")
    if isinstance(org_unit_id, bool) or not isinstance(org_unit_id, int):
        raise A2LError("course offering has an invalid organization-unit ID")
    if not isinstance(code, str) or not code or not isinstance(name, str) or not name:
        raise A2LError("course offering has invalid metadata")

    access = raw.get("Access")
    if not isinstance(access, dict):
        raise A2LError("course offering has invalid access metadata")
    is_active = access.get("IsActive")
    if not isinstance(is_active, bool):
        raise A2LError("course offering has invalid active metadata")
    start_date = _optional_string(access.get("StartDate"))
    end_date = _optional_string(access.get("EndDate"))
    term = client.school.term_from_offering(code)
    return CourseRef(
        org_unit_id=org_unit_id,
        code=code,
        name=name,
        term=term,
        is_active=is_active,
        start_date=start_date,
        end_date=end_date,
    )


def _previous_template() -> str | None:
    destination = config.state_dir() / _CALIBRATION_FILENAME
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    template = raw.get("download_template")
    return template if isinstance(template, str) and template else None


def _write(value: Calibration) -> None:
    payload = {
        "calibrated_at": value.calibrated_at,
        "courses": [
            {
                "code": course.code,
                "end_date": course.end_date,
                "is_active": course.is_active,
                "name": course.name,
                "org_unit_id": course.org_unit_id,
                "start_date": course.start_date,
                "term": course.term,
            }
            for course in value.courses
        ],
        "download_template": value.download_template,
        "le": value.le,
        "lp": value.lp,
        "schema_version": _SCHEMA_VERSION,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    paths.atomic_write_text(config.state_dir() / _CALIBRATION_FILENAME, text)


def _decode(raw: Any) -> Calibration:
    if not isinstance(raw, dict) or set(raw) != {
        "calibrated_at",
        "courses",
        "download_template",
        "le",
        "lp",
        "schema_version",
    }:
        raise ValueError("calibration schema is invalid")
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("calibration schema is unsupported")
    lp = raw["lp"]
    le = raw["le"]
    template = raw["download_template"]
    calibrated_at = raw["calibrated_at"]
    courses_raw = raw["courses"]
    if (
        not isinstance(lp, str)
        or not lp
        or not isinstance(le, str)
        or not le
        or template is not None
        and not isinstance(template, str)
        or calibrated_at is not None
        and not isinstance(calibrated_at, str)
        or not isinstance(courses_raw, list)
    ):
        raise ValueError("calibration schema is invalid")
    courses = [_decode_course(value) for value in courses_raw]
    return Calibration(
        lp=lp,
        le=le,
        download_template=template,
        courses=courses,
        calibrated_at=calibrated_at,
    )


def _decode_course(raw: Any) -> CourseRef:
    if not isinstance(raw, dict) or set(raw) != {
        "code",
        "end_date",
        "is_active",
        "name",
        "org_unit_id",
        "start_date",
        "term",
    }:
        raise ValueError("calibration course schema is invalid")
    org_unit_id = raw["org_unit_id"]
    code = raw["code"]
    name = raw["name"]
    is_active = raw["is_active"]
    if (
        isinstance(org_unit_id, bool)
        or not isinstance(org_unit_id, int)
        or not isinstance(code, str)
        or not code
        or not isinstance(name, str)
        or not name
        or not isinstance(is_active, bool)
    ):
        raise ValueError("calibration course schema is invalid")
    return CourseRef(
        org_unit_id=org_unit_id,
        code=code,
        name=name,
        term=_optional_string(raw["term"]),
        is_active=is_active,
        start_date=_optional_string(raw["start_date"]),
        end_date=_optional_string(raw["end_date"]),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2LError("calibration metadata contains a non-string optional value")
    return value


__all__ = ["Calibration", "CourseRef", "calibrate", "display_courses", "load_calibration"]
