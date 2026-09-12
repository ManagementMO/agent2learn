from __future__ import annotations

import json
import os
import unicodedata
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from agent2learn import paths
from agent2learn.calibrate import CourseRef
from agent2learn.errors import A2LError
from agent2learn.schools import School
from agent2learn.vault import Vault


@dataclass(frozen=True)
class CourseIdentity:
    school: str
    org_unit_id: int
    code: str
    name: str
    term: str | None


def read_course_identity(course_dir: Path) -> CourseIdentity | None:
    path = course_dir / "_meta" / "course.json"
    raw = _read_json(path, course_dir.parent.parent)
    if raw is None:
        if paths.long_path(path).exists():
            raise A2LError("course directory ownership is invalid")
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "school",
        "org_unit_id",
        "code",
        "name",
        "term",
    }:
        raise A2LError("course directory ownership is invalid")
    identifier = raw.get("org_unit_id")
    if (
        isinstance(raw.get("schema_version"), bool)
        or not isinstance(raw.get("schema_version"), int)
        or raw.get("schema_version") != 1
        or not isinstance(raw.get("school"), str)
        or not raw["school"]
        or isinstance(identifier, bool)
        or not isinstance(identifier, int)
        or identifier <= 0
        or not isinstance(raw.get("code"), str)
        or not isinstance(raw.get("name"), str)
        or raw.get("term") is not None
        and not isinstance(raw.get("term"), str)
    ):
        raise A2LError("course directory ownership is invalid")
    return CourseIdentity(raw["school"], identifier, raw["code"], raw["name"], raw["term"])


def course_directory(vault: Vault, school: School, course: CourseRef, preferred: Path) -> Path:
    from agent2learn.index import read_content_map

    wanted = (school.id, course.org_unit_id)
    owners: dict[Path, set[tuple[str, int]]] = {}
    for key, entry in vault.manifest().items():
        parts = PurePosixPath(entry.path).parts
        owner = _source_owner(key)
        if owner is not None and len(parts) >= 3 and not parts[0].startswith("."):
            directory = vault.root / parts[0] / parts[1]
            owners.setdefault(directory, set()).add(owner)
    candidates = set(owners)
    for term in _directories(vault.root):
        for directory in _directories(term):
            if paths.long_path(directory / "_meta").is_dir():
                candidates.add(directory)
    matches: list[Path] = []
    empty_legacy: set[Path] = set()
    for directory in sorted(candidates):
        if paths.has_link_component(directory, root=vault.root):
            raise A2LError("course directory ownership contains a link component")
        identity = read_course_identity(directory)
        known = set(owners.get(directory, set()))
        if identity is not None:
            known.add((identity.school, identity.org_unit_id))
        content_map = directory / "_meta" / "content_map.json"
        if paths.has_link_component(content_map, root=vault.root):
            raise A2LError("course metadata contains a link component")
        if paths.long_path(content_map).is_file():
            topics = read_content_map(directory)["topics"]
            assert isinstance(topics, list)
            for row in topics:
                if isinstance(row, Mapping):
                    owner = _source_owner(row.get("source_key"))
                    if owner is not None:
                        known.add(owner)
            if not topics and identity is None and not known:
                empty_legacy.add(directory)
        if wanted in known:
            if known != {wanted}:
                raise A2LError("ambiguous course directory ownership")
            matches.append(directory)
    if len(matches) > 1:
        raise A2LError("ambiguous course directory ownership")
    if matches:
        destination = matches[0]
    elif preferred in empty_legacy:
        destination = preferred
    else:
        if paths.has_link_component(preferred, root=vault.root):
            raise A2LError("course directory contains a link component")
        paths.ensure_dir(preferred.parent, root=vault.root)
        destination = paths.unique_path(preferred)
    identity = CourseIdentity(school.id, course.org_unit_id, course.code, course.name, course.term)
    destination_file = destination / "_meta" / "course.json"
    payload = {"schema_version": 1, **asdict(identity)}
    if _read_json(destination_file, vault.root) != payload:
        paths.ensure_dir(destination_file.parent, root=vault.root)
        paths.atomic_write_text(
            destination_file,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            root=vault.root,
        )
    return destination


def assignment_row_directory(course_dir: Path, row: Mapping[str, object]) -> Path | None:
    value = row.get("directory")
    if value is None:
        instructions = row.get("instructions_html")
        if isinstance(instructions, str):
            value = PurePosixPath(instructions).parent.as_posix()
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise A2LError("assignment directory ownership is invalid")
    root = course_dir.parent.parent
    destination = root / PurePosixPath(value)
    if destination.parent != course_dir / "assignments" or paths.has_link_component(
        destination, root=root
    ):
        raise A2LError("assignment directory ownership escapes its course")
    return destination


def assignment_directories(
    vault: Vault,
    course_dir: Path,
    school: School,
    course: CourseRef,
    rows: Sequence[dict[str, object]],
    previous: Sequence[Mapping[str, object]],
    active: Collection[str],
) -> dict[str, Path]:
    old = {str(row.get("id")): row for row in previous}
    claimed: dict[str, str] = {}
    reserved: list[Path] = []
    for row in previous:
        directory = assignment_row_directory(course_dir, row)
        if directory is not None:
            name = _path_key(directory)
            identifier = str(row.get("id"))
            if name in claimed and claimed[name] != identifier:
                raise A2LError("ambiguous assignment directory ownership")
            claimed[name] = identifier
            reserved.append(directory)
    result: dict[str, Path] = {}
    for row in sorted(rows, key=lambda value: str(value.get("id"))):
        identifier = str(row.get("id"))
        if identifier not in active:
            continue
        directory = assignment_row_directory(course_dir, row)
        entry = vault.entry(f"{school.id}:{course.org_unit_id}:dropbox:{identifier}")
        if entry is not None:
            source_directory = vault.materialized(entry).parent
            if directory is not None and directory != source_directory:
                raise A2LError("assignment directory disagrees with its source manifest")
            directory = source_directory
        if directory is None and identifier in old:
            title = str(old[identifier].get("title") or f"Assignment {identifier}")
            for name in (f"{title} {identifier}", title):
                candidate = course_dir / "assignments" / paths.safe_name(name)
                if paths.is_link(candidate):
                    raise A2LError("assignment directory contains a link component")
                if paths.long_path(candidate).is_dir():
                    directory = candidate
                    break
        if directory is None:
            title = str(row.get("title") or f"Assignment {identifier}")
            preferred = course_dir / "assignments" / paths.safe_name(f"{title} {identifier}")
            directory = paths.unique_path(preferred, reserved=reserved)
        relative = paths.rel_posix(directory, vault.root)
        checked = assignment_row_directory(course_dir, {"directory": relative})
        assert checked is not None
        name = _path_key(checked)
        if name in claimed and claimed[name] != identifier:
            raise A2LError("ambiguous assignment directory ownership")
        claimed[name] = identifier
        reserved.append(checked)
        paths.ensure_dir(checked, root=vault.root)
        row["directory"] = relative
        result[identifier] = checked
    return result


def _source_owner(value: object) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) == 4 and parts[0] and parts[1].isdigit() and int(parts[1]) > 0:
        return parts[0], int(parts[1])
    return None


def _directories(parent: Path) -> Iterator[Path]:
    if not paths.long_path(parent).is_dir():
        return
    for child in sorted(paths.long_path(parent).iterdir()):
        candidate = parent / child.name
        if (
            not candidate.name.startswith(".")
            and not paths.is_link(candidate)
            and paths.long_path(candidate).is_dir()
        ):
            yield candidate


def _read_json(path: Path, root: Path) -> object:
    if paths.has_link_component(path, root=root):
        raise A2LError("directory ownership metadata contains a link component")
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise A2LError("directory ownership metadata is unreadable") from exc


def _path_key(path: Path) -> str:
    return unicodedata.normalize("NFC", path.as_posix()).casefold()
