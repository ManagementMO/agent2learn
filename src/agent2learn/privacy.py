"""Preview-first, allowlisted removal of locally retained sensitive categories.

Privacy operations are intentionally more conservative than ordinary vault maintenance.  This
module discovers exact managed files or exact structured records, validates the complete target
inventory, and only then permits a fresh interactive confirmation to install the change.  It
never interprets arbitrary course text as permission to delete anything and it never delegates a
privacy purge to a recursive tree-removal helper.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from agent2learn import config, console, paths
from agent2learn.errors import A2LError
from agent2learn.vault import Vault

Category = Literal["grades", "discussions", "logs"]
_CATEGORIES = frozenset({"grades", "discussions", "logs"})
_BACKUP_NAME = re.compile(r"^\.a2l-backup-v\d+(?:-\d+)?$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_GRADE_KEYS = frozenset({"grade", "grades", "my_grade", "my_grades", "grade_fields"})
_DISCUSSION_KEYS = frozenset({"discussion", "discussions", "forum", "forums"})
_KNOWN_LOG_NAMES = ("a2l.log", "a2l.log.1", "a2l.log.2", "a2l.log.3", "a2l.log.4")
_REVISION_FILENAME = "revision.json"
_INVENTORY_NAMES = ("privacy.json", "category-inventory.json")


@dataclass(frozen=True)
class PrivacyStatus:
    """Redacted sensitive-category state suitable for terminal display."""

    grades_enabled: bool
    discussions_enabled: bool
    grades_present: bool
    discussions_present: bool
    logs_present: bool
    grade_location: str = "<vault>/<Term>/<Course>/_meta/my_grades.json and <vault>/.a2l/snapshots/"
    discussion_location: str = "<vault>/<Term>/<Course>/discussions/ and <vault>/.a2l/private/"
    log_location: str = "<configured log directory>/a2l.log[.1-.4]"


@dataclass(frozen=True)
class PurgeTarget:
    """One exact planned file, record, or managed revision operation."""

    path: Path
    display: str
    action: str


@dataclass(frozen=True)
class PurgePlan:
    """A preview inventory bound to the exact bytes observed at discovery time."""

    category: Category
    targets: tuple[PurgeTarget, ...]
    fingerprint: str
    log_directory: Path | None = field(default=None, repr=False, compare=False)
    _operations: tuple[_Operation, ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class PurgeResult:
    """Mutation summary without echoing sensitive paths or values."""

    category: Category
    target_count: int


@dataclass(frozen=True)
class _StateRoot:
    path: Path
    display: str
    trusted_root: Path


@dataclass(frozen=True)
class _Operation:
    path: Path
    action: Literal["unlink", "rewrite", "remove_tree", "rmdir"]
    display: str
    detail: str
    payload: object | None = None
    trusted_root: Path | None = None


def status(
    vault: Vault,
    cfg: config.Config,
    *,
    log_directory: Path | None = None,
) -> PrivacyStatus:
    """Return category flags and redacted retained-data locations without printing contents."""

    if not paths.long_path(vault.root).is_dir():
        return PrivacyStatus(
            grades_enabled=cfg.include_grades,
            discussions_enabled=cfg.include_discussions,
            grades_present=False,
            discussions_present=False,
            logs_present=False,
        )

    grades = plan_purge(vault, "grades", log_directory=log_directory)
    discussions = plan_purge(vault, "discussions", log_directory=log_directory)
    logs = plan_purge(vault, "logs", log_directory=log_directory)
    return PrivacyStatus(
        grades_enabled=cfg.include_grades,
        discussions_enabled=cfg.include_discussions,
        grades_present=bool(grades.targets),
        discussions_present=bool(discussions.targets),
        logs_present=bool(logs.targets),
    )


def render_status(value: PrivacyStatus) -> str:
    """Render only policy state and structural redacted locations."""

    def state(enabled: bool, present: bool) -> str:
        collection = "enabled" if enabled else "disabled"
        retained = "retained locally" if present else "not detected locally"
        return f"{collection}; {retained}"

    return "\n".join(
        [
            "Privacy status",
            f"- grades: {state(value.grades_enabled, value.grades_present)}",
            f"  location: {value.grade_location}",
            f"- discussions: {state(value.discussions_enabled, value.discussions_present)}",
            f"  location: {value.discussion_location}",
            f"- logs: {'present' if value.logs_present else 'not detected'}",
            f"  location: {value.log_location}",
            "",
        ]
    )


def plan_purge(
    vault: Vault,
    category: str,
    *,
    log_directory: Path | None = None,
) -> PurgePlan:
    """Discover and validate an exact allowlisted purge inventory without mutating anything."""

    selected = _category(category)
    _validate_vault_root(vault)
    operations: list[_Operation] = []
    if selected == "logs":
        _discover_logs(operations, log_directory)
    else:
        states = _state_roots(vault)
        _discover_course_artifacts(vault, selected, operations)
        for state in states:
            _discover_state_artifacts(vault, state, selected, operations)
    operations = _deduplicate(operations)
    return _make_plan(vault, selected, operations, log_directory=log_directory)


def execute_purge(
    vault: Vault,
    plan: PurgePlan,
    *,
    phrase: str,
    interactive: bool,
    log_directory: Path | None = None,
) -> PurgeResult:
    """Apply a preview only after an exact, action-specific interactive confirmation.

    The plan is rediscovered after confirmation.  Any changed target, including a changed JSON
    file or a newly appearing allowlisted file, invalidates the confirmation instead of widening
    the operation silently.
    """

    if not interactive:
        raise A2LError("privacy purge requires an interactive terminal")
    if not isinstance(phrase, str) or phrase != f"PURGE {plan.category.upper()}":
        raise A2LError(f"privacy purge confirmation must be exactly PURGE {plan.category.upper()}")

    refreshed = plan_purge(
        vault,
        plan.category,
        log_directory=log_directory if log_directory is not None else plan.log_directory,
    )
    if refreshed.fingerprint != plan.fingerprint:
        raise A2LError("privacy purge preview is stale; review a new preview")

    if plan.category == "logs":
        # Close only Agent2Learn's marked rotating handlers.  In particular, do not configure a
        # replacement handler after deleting the files: that would recreate a log immediately.
        console.close_owned_handlers()
    _apply(refreshed._operations)
    return PurgeResult(plan.category, len(refreshed.targets))


def purge(
    vault: Vault,
    category: str,
    *,
    phrase: str | None = None,
    interactive: bool = False,
    log_directory: Path | None = None,
) -> PurgePlan | PurgeResult:
    """Return a preview by default, or execute it with the exact fresh confirmation phrase."""

    plan = plan_purge(vault, category, log_directory=log_directory)
    if phrase is None:
        return plan
    return execute_purge(
        vault,
        plan,
        phrase=phrase,
        interactive=interactive,
        log_directory=log_directory,
    )


def render_plan(plan: PurgePlan) -> str:
    """Render an exact preview without reading or displaying target contents."""

    lines = [f"Privacy purge preview · {plan.category}"]
    if not plan.targets:
        lines.append("- No retained files or records match this category.")
    else:
        lines.extend(f"- {target.display} — {target.action}" for target in plan.targets)
    lines.extend(
        [
            "",
            (
                "Logical deletion only: filesystem snapshots, backups, and external copies "
                "may retain data."
            ),
            f"To continue in a controlling terminal, type: PURGE {plan.category.upper()}",
        ]
    )
    return "\n".join(lines) + "\n"


def _category(value: str) -> Category:
    if not isinstance(value, str) or value not in _CATEGORIES:
        raise A2LError("privacy category must be exactly grades, discussions, or logs")
    return cast(Category, value)


def _validate_vault_root(vault: Vault) -> None:
    root = vault.root
    if paths.is_link(root):
        raise A2LError("privacy purge refuses a symlinked vault root")
    if not paths.long_path(root).is_dir():
        raise A2LError("vault is unavailable; run: a2l init")
    state = root / ".a2l"
    if paths.is_link(state):
        raise A2LError("privacy purge refuses a symlinked vault state directory")


def _state_roots(vault: Vault) -> tuple[_StateRoot, ...]:
    result: list[_StateRoot] = []
    current = vault.root / ".a2l"
    if paths.long_path(current).is_dir():
        _safe_path(current, vault.root)
        result.append(_StateRoot(current, "<vault>/.a2l", vault.root))

    result.extend(_backup_state_roots(vault.root, vault.root))

    parent = vault.root.parent
    if not paths.long_path(parent).is_dir():
        return tuple(result)
    children = _directory_children(parent, "schema backup inventory")
    for child in children:
        if child == vault.root:
            continue
        result.extend(_backup_state_roots(parent, parent, only=child))
    return tuple(result)


def _backup_state_roots(
    directory: Path,
    trusted_root: Path,
    *,
    only: Path | None = None,
) -> list[_StateRoot]:
    children = (
        [only] if only is not None else _directory_children(directory, "schema backup inventory")
    )
    result: list[_StateRoot] = []
    for child in children:
        if child is None or not _BACKUP_NAME.fullmatch(child.name):
            continue
        if paths.is_link(child):
            raise A2LError("privacy purge refuses a symlinked schema backup")
        if not paths.long_path(child).is_dir():
            raise A2LError("schema backup path is not a directory")
        state = child / ".a2l" if paths.long_path(child / ".a2l").is_dir() else child
        _safe_path(child, trusted_root)
        _safe_path(state, child)
        display = "<schema backup>/.a2l" if state.name == ".a2l" else "<schema backup>"
        result.append(_StateRoot(state, display, child))
    return result


def _discover_course_artifacts(
    vault: Vault,
    category: Category,
    operations: list[_Operation],
) -> None:
    root = vault.root
    content_maps: list[Path] = []
    for candidate in _named_paths(root, "content_map.json"):
        if ".a2l" in candidate.parts:
            continue
        _safe_path(candidate, root)
        content_maps.append(candidate)
        course_dir = candidate.parent.parent
        if category == "grades":
            _add_unlink(
                vault,
                operations,
                course_dir / "_meta" / "my_grades.json",
                "remove grade projection",
            )
        else:
            _add_unlink(
                vault,
                operations,
                course_dir / "_meta" / "discussions.json",
                "remove discussion projection",
            )
            discussion_dir = course_dir / "discussions"
            if paths.is_link(discussion_dir):
                raise A2LError("privacy purge refuses a symlinked discussions directory")
            if paths.long_path(discussion_dir).is_dir():
                _add_unlink(
                    vault,
                    operations,
                    discussion_dir / "discussions.md",
                    "remove generated discussion markdown",
                )

    if category == "discussions":
        for discussion_dir in _discussion_directories(root):
            if paths.is_link(discussion_dir):
                raise A2LError("privacy purge refuses a symlinked discussions directory")
            _add_discussion_paths_from_map(vault, operations, discussion_dir, content_maps)
            _add_empty_directory_cleanup(vault, operations, discussion_dir)

    for content_map in content_maps:
        raw = _read_json(content_map, "content map")
        topics = raw.get("topics")
        if not isinstance(topics, list):
            raise A2LError("content_map.json topics must be an array")
        if category == "discussions":
            kept = [topic for topic in topics if not _owned_row(topic, "discussions")]
            if len(kept) != len(topics):
                payload = dict(raw)
                payload["topics"] = kept
                _add_rewrite(
                    vault,
                    operations,
                    content_map,
                    payload,
                    "remove discussion content-map records",
                )
        elif any(_owned_row(topic, "grades") for topic in topics):
            kept = [topic for topic in topics if not _owned_row(topic, "grades")]
            payload = dict(raw)
            payload["topics"] = kept
            _add_rewrite(
                vault, operations, content_map, payload, "remove grade content-map records"
            )

    # These projections are allowlisted by their structural location, not inferred from the
    # presence of a content map. A damaged or hand-created course can still retain sensitive
    # data, and privacy status/purge must not miss it merely because navigation metadata is absent.
    projection_name = "my_grades.json" if category == "grades" else "discussions.json"
    for projection in _named_paths(root, projection_name):
        if ".a2l" in projection.parts or projection.parent.name != "_meta":
            continue
        _safe_path(projection, root)
        _add_unlink(
            vault,
            operations,
            projection,
            "remove grade projection" if category == "grades" else "remove discussion projection",
        )

    for index_path in _named_paths(root, "INDEX.md"):
        if ".a2l" in index_path.parts:
            continue
        _safe_path(index_path, root)
        original = _read_text(index_path, "course index")
        scrubbed = _scrub_index(original, category)
        if scrubbed != original:
            _add_rewrite(vault, operations, index_path, scrubbed, f"remove {category} index block")


def _discover_state_artifacts(
    vault: Vault,
    state: _StateRoot,
    category: Category,
    operations: list[_Operation],
) -> None:
    state_path = state.path
    if paths.is_link(state_path):
        raise A2LError("privacy purge refuses a symlinked managed state directory")
    if not paths.long_path(state_path).is_dir():
        return

    if category == "grades":
        _discover_snapshot_scrubs(vault, state, operations)
    else:
        _discover_discussion_private_files(vault, state, operations)

    manifest = state_path / "manifest.json"
    if paths.long_path(manifest).exists() or paths.is_link(manifest):
        _safe_path(manifest, state.trusted_root)
        raw = _read_json(manifest, "manifest")
        _discover_manifest(vault, state, manifest, raw, category, operations)

    for inventory_name in _INVENTORY_NAMES:
        inventory = state_path / "private" / inventory_name
        if paths.long_path(inventory).exists() or paths.is_link(inventory):
            _safe_path(inventory, state.trusted_root)
            raw = _read_json(inventory, "privacy inventory")
            scrubbed = _scrub_inventory(raw, category)
            if scrubbed != raw:
                _add_rewrite(
                    vault,
                    operations,
                    inventory,
                    scrubbed,
                    f"remove {category} inventory",
                    trusted_root=state.trusted_root,
                )

    history = state_path / "history"
    if paths.is_link(history):
        raise A2LError("privacy purge refuses a symlinked managed history directory")
    if paths.long_path(history).is_dir():
        _reject_links_in_managed_directory(history, "history")
        for revision in _named_paths(history, _REVISION_FILENAME):
            _safe_path(revision, state.trusted_root)
            raw = _read_json(revision, "revision metadata")
            if _owned_record(raw, None, category):
                _add_remove_tree(
                    vault,
                    operations,
                    revision.parent,
                    state.trusted_root,
                    f"remove {category} managed revision",
                )


def _discover_snapshot_scrubs(
    vault: Vault,
    state: _StateRoot,
    operations: list[_Operation],
) -> None:
    snapshots = state.path / "snapshots"
    if paths.is_link(snapshots):
        raise A2LError("privacy purge refuses a symlinked snapshot directory")
    if not paths.long_path(snapshots).is_dir():
        return
    for snapshot_path in _json_files(snapshots):
        _safe_path(snapshot_path, state.trusted_root)
        raw = _read_json(snapshot_path, "snapshot")
        scrubbed, changed = _scrub_snapshot(raw)
        if changed:
            _add_rewrite(
                vault,
                operations,
                snapshot_path,
                scrubbed,
                "remove grades field",
                trusted_root=state.trusted_root,
            )


def _discover_discussion_private_files(
    vault: Vault,
    state: _StateRoot,
    operations: list[_Operation],
) -> None:
    private = state.path / "private"
    if paths.is_link(private):
        raise A2LError("privacy purge refuses a symlinked private state directory")
    key = private / "discussion-hmac.key"
    if paths.long_path(key).exists() or paths.is_link(key):
        _safe_path(key, state.trusted_root)
        _add_unlink(
            vault,
            operations,
            key,
            "remove discussion pseudonym key",
            trusted_root=state.trusted_root,
        )


def _discover_manifest(
    vault: Vault,
    state: _StateRoot,
    manifest: Path,
    raw: dict[str, object],
    category: Category,
    operations: list[_Operation],
) -> None:
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        raise A2LError("manifest entries must be an object")
    kept: dict[str, object] = {}
    changed = False
    for key, entry in entries.items():
        if not isinstance(key, str):
            raise A2LError("manifest entry keys must be strings")
        if _owned_record(entry, key, category):
            changed = True
            if isinstance(entry, Mapping):
                for relative in _entry_paths(entry):
                    target = _relative_target(vault.root, relative)
                    if paths.long_path(target).exists() or paths.is_link(target):
                        _add_unlink(
                            vault,
                            operations,
                            target,
                            f"remove {category} manifest artifact",
                            trusted_root=vault.root,
                        )
            continue
        kept[key] = entry
    if changed:
        payload = dict(raw)
        payload["entries"] = kept
        _add_rewrite(
            vault,
            operations,
            manifest,
            payload,
            f"remove {category} manifest records",
            trusted_root=state.trusted_root,
        )


def _discover_logs(operations: list[_Operation], log_directory: Path | None) -> None:
    directory = (
        Path(log_directory).expanduser()
        if log_directory is not None
        else Path(config.DIRS.user_log_path)
    )
    if paths.is_link(directory) or paths.has_link_component(directory):
        raise A2LError("privacy log purge refuses a symlinked log directory")
    if not paths.long_path(directory).is_dir():
        return
    for name in _KNOWN_LOG_NAMES:
        candidate = directory / name
        if paths.is_link(candidate):
            raise A2LError("privacy log purge refuses a symlinked log file")
        if paths.long_path(candidate).exists():
            if not paths.long_path(candidate).is_file():
                raise A2LError("privacy log purge found a non-file rotating log target")
            _add_operation(
                operations,
                _Operation(
                    candidate,
                    "unlink",
                    f"<configured log directory>/{name}",
                    "remove rotating log",
                    trusted_root=directory,
                ),
            )


def _discussion_directories(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for candidate in _named_paths(root, "discussions"):
        if paths.is_link(candidate):
            raise A2LError("privacy purge refuses a symlinked discussions directory")
        if candidate.parent.name == ".a2l":
            continue
        meta = candidate.parent / "_meta"
        if paths.long_path(meta).is_dir() or paths.long_path(meta / "content_map.json").exists():
            result.append(candidate)
    return tuple(result)


def _add_discussion_paths_from_map(
    vault: Vault,
    operations: list[_Operation],
    discussion_dir: Path,
    content_maps: Iterable[Path],
) -> None:
    for content_map in content_maps:
        if content_map.parent.parent != discussion_dir.parent:
            continue
        raw = _read_json(content_map, "content map")
        topics = raw.get("topics")
        if not isinstance(topics, list):
            raise A2LError("content_map.json topics must be an array")
        for topic in topics:
            if not _owned_row(topic, "discussions") or not isinstance(topic, Mapping):
                continue
            for value in _entry_paths(topic):
                if value:
                    target = _relative_target(vault.root, value)
                    _add_unlink(vault, operations, target, "remove discussion source or twin")


def _add_empty_directory_cleanup(
    vault: Vault,
    operations: list[_Operation],
    directory: Path,
) -> None:
    _safe_path(directory, vault.root)
    if not paths.long_path(directory).is_dir():
        return
    candidates = list(paths.walk(directory))
    for candidate in candidates:
        if paths.is_link(candidate):
            raise A2LError("privacy purge refuses a symlinked discussions entry")

    managed_files = {
        operation.path
        for operation in operations
        if operation.action == "unlink" and operation.path.is_relative_to(directory)
    }
    removable: set[Path] = set()
    directories = sorted(
        (candidate for candidate in candidates if paths.long_path(candidate).is_dir()),
        key=lambda value: len(value.relative_to(directory).parts),
        reverse=True,
    )
    directories.append(directory)
    for candidate in directories:
        try:
            children = _directory_children(candidate, "privacy discussions directory")
        except OSError as exc:
            raise A2LError("privacy discussions directory is unreadable") from exc
        if all(child in managed_files or child in removable for child in children):
            removable.add(candidate)
            _add_operation(
                operations,
                _Operation(
                    candidate,
                    "rmdir",
                    _vault_display(vault, candidate),
                    "remove empty generated directory",
                    trusted_root=vault.root,
                ),
            )


def _scrub_snapshot(raw: dict[str, object]) -> tuple[dict[str, object], bool]:
    courses = raw.get("courses")
    if not isinstance(courses, list):
        raise A2LError("snapshot courses must be a list")
    payload = dict(raw)
    new_courses: list[object] = []
    changed = False
    for course in courses:
        if not isinstance(course, Mapping):
            raise A2LError("snapshot courses must contain objects")
        value = dict(course)
        if "grades" in value:
            value.pop("grades")
            changed = True
        new_courses.append(value)
    if changed:
        payload["courses"] = new_courses
    return payload, changed


def _scrub_inventory(raw: dict[str, object], category: Category) -> dict[str, object]:
    payload = dict(raw)
    categories = payload.get("categories")
    if isinstance(categories, list):
        payload["categories"] = [
            value for value in categories if not (_owned_record(value, None, category))
        ]
    elif isinstance(categories, dict):
        payload["categories"] = {
            key: value
            for key, value in categories.items()
            if not _owned_record(value, key, category)
        }
    return payload


def _scrub_index(text: str, category: Category) -> str:
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    inside = False
    start_marker = f"<!-- a2l:{category}:start -->"
    end_marker = f"<!-- a2l:{category}:end -->"
    for line in lines:
        lowered = line.casefold()
        if start_marker in lowered:
            inside = True
            continue
        if inside:
            if end_marker in lowered:
                inside = False
            continue
        if category == "grades" and re.match(r"^\s*[-*]\s+grades?\s*:", line, re.IGNORECASE):
            continue
        if category == "discussions" and (
            "discussions/" in lowered
            or re.match(r"^\s*#{1,3}\s+discussions?\s*$", line, re.IGNORECASE)
        ):
            continue
        result.append(line)
    return "".join(result)


def _owned_row(value: object, category: Category) -> bool:
    if not isinstance(value, Mapping):
        return False
    return _owned_record(value, cast(str | None, value.get("source_key")), category)


def _owned_record(value: object, key: str | None, category: Category) -> bool:
    if not isinstance(value, Mapping):
        return False
    markers: list[str] = []
    for marker_key in ("category", "privacy_category", "kind", "source_key", "canonical_key"):
        marker = value.get(marker_key)
        if isinstance(marker, str):
            markers.append(marker.casefold())
    if key:
        markers.append(key.casefold())
    wanted = "grade" if category == "grades" else "discussion"
    explicit_names = _GRADE_KEYS if category == "grades" else _DISCUSSION_KEYS
    for marker in markers:
        if marker in explicit_names or f":{wanted}:" in marker or f":{wanted}s:" in marker:
            return True
    path_values = _entry_paths(value)
    if category == "grades":
        return any(
            PurePosixPath(path).name.casefold() in {"my_grades.json", "grades.json"}
            for path in path_values
        )
    return any(_is_discussion_path(path) for path in path_values)


def _entry_paths(value: Mapping[str, object]) -> tuple[str, ...]:
    result: list[str] = []
    for key in ("path", "source_path", "stub_path"):
        path = value.get(key)
        if isinstance(path, str):
            result.append(path)
    derived = value.get("derived")
    if isinstance(derived, Mapping):
        for item in derived.values():
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                result.append(cast(str, item["path"]))
    return tuple(result)


def _is_discussion_path(value: str) -> bool:
    try:
        parts = PurePosixPath(value).parts
    except (TypeError, ValueError):
        return False
    return "discussions" in {part.casefold() for part in parts}


def _relative_target(root: Path, value: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or _WINDOWS_ABSOLUTE.match(value) is not None
    ):
        raise A2LError("privacy target path must be a relative POSIX path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise A2LError("privacy target path escapes the vault")
    path = root.joinpath(*candidate.parts)
    _safe_path(path, root)
    return path


def _named_paths(root: Path, name: str) -> tuple[Path, ...]:
    if not paths.long_path(root).is_dir():
        return ()
    try:
        return tuple(
            sorted(
                (candidate for candidate in paths.walk(root) if candidate.name == name),
                key=os.fspath,
            )
        )
    except OSError as exc:
        raise A2LError("privacy target inventory is unreadable") from exc


def _json_files(root: Path) -> tuple[Path, ...]:
    try:
        candidates = list(paths.walk(root))
        for candidate in candidates:
            if paths.is_link(candidate):
                raise A2LError("privacy purge refuses a symlinked JSON target")
        return tuple(
            sorted(
                (
                    candidate
                    for candidate in candidates
                    if candidate.suffix.casefold() == ".json"
                    and not paths.long_path(candidate).is_dir()
                ),
                key=os.fspath,
            )
        )
    except OSError as exc:
        raise A2LError("privacy JSON inventory is unreadable") from exc


def _add_unlink(
    vault: Vault,
    operations: list[_Operation],
    path: Path,
    detail: str,
    *,
    trusted_root: Path | None = None,
) -> None:
    if not paths.long_path(path).exists() and not paths.is_link(path):
        return
    root = vault.root if trusted_root is None else trusted_root
    _safe_path(path, root)
    if not paths.long_path(path).is_file():
        raise A2LError("privacy purge target is not a regular file")
    _add_operation(
        operations,
        _Operation(path, "unlink", _display_path(vault, path, root), detail, trusted_root=root),
    )


def _add_rewrite(
    vault: Vault,
    operations: list[_Operation],
    path: Path,
    payload: object,
    detail: str,
    *,
    trusted_root: Path | None = None,
) -> None:
    root = vault.root if trusted_root is None else trusted_root
    _safe_path(path, root)
    if not paths.long_path(path).is_file():
        raise A2LError("privacy JSON target is not a regular file")
    _add_operation(
        operations,
        _Operation(
            path,
            "rewrite",
            _display_path(vault, path, root),
            detail,
            payload,
            root,
        ),
    )


def _add_remove_tree(
    vault: Vault,
    operations: list[_Operation],
    path: Path,
    trusted_root: Path,
    detail: str,
) -> None:
    if not paths.long_path(path).is_dir():
        raise A2LError("privacy managed revision is not a directory")
    _validate_explicit_tree(path, trusted_root)
    display = _display_path(vault, path, trusted_root)
    _add_operation(
        operations,
        _Operation(path, "remove_tree", display, detail, trusted_root=trusted_root),
    )


def _add_operation(operations: list[_Operation], operation: _Operation) -> None:
    operations.append(operation)


def _deduplicate(operations: list[_Operation]) -> list[_Operation]:
    result: list[_Operation] = []
    seen: set[tuple[str, str]] = set()
    for operation in operations:
        identity = (os.fspath(operation.path), operation.action)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(operation)
    return sorted(result, key=lambda item: (item.action, os.fspath(item.path), item.detail))


def _make_plan(
    vault: Vault,
    category: Category,
    operations: Iterable[_Operation],
    *,
    log_directory: Path | None,
) -> PurgePlan:
    selected = tuple(operations)
    targets: list[PurgeTarget] = []
    digest = hashlib.sha256()
    for operation in selected:
        trusted_root = operation.trusted_root
        if trusted_root is None:
            trusted_root = (
                Path(log_directory).expanduser()
                if category == "logs" and log_directory is not None
                else Path(config.DIRS.user_log_path)
                if category == "logs"
                else vault.root
            )
        _safe_path(operation.path, trusted_root)
        state = _object_fingerprint(operation.path)
        digest.update(os.fspath(operation.path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(operation.action.encode("utf-8"))
        digest.update(b"\0")
        digest.update(operation.detail.encode("utf-8"))
        digest.update(b"\0")
        digest.update(state.encode("ascii"))
        digest.update(b"\0")
        targets.append(PurgeTarget(operation.path, operation.display, operation.detail))
    resolved_log_directory = (
        Path(log_directory).expanduser()
        if log_directory is not None
        else Path(config.DIRS.user_log_path)
        if category == "logs"
        else None
    )
    return PurgePlan(
        category,
        tuple(targets),
        digest.hexdigest(),
        resolved_log_directory,
        selected,
    )


def _apply(operations: Iterable[_Operation]) -> None:
    selected = tuple(operations)
    rewrites = [operation for operation in selected if operation.action == "rewrite"]
    for operation in rewrites:
        trusted_root = operation.trusted_root or operation.path.parent
        _safe_path(operation.path, trusted_root)
        if not paths.long_path(operation.path).is_file():
            raise A2LError("privacy JSON target changed before rewrite")
        if isinstance(operation.payload, str):
            text = operation.payload
        else:
            text = _canonical_json(operation.payload)
        paths.atomic_write_text(operation.path, text, root=trusted_root)

    for operation in sorted(
        (item for item in selected if item.action == "remove_tree"),
        key=lambda item: (len(item.path.parts), os.fspath(item.path)),
        reverse=True,
    ):
        _remove_explicit_tree(operation.path, operation.trusted_root or operation.path.parent)
    for operation in selected:
        if operation.action == "unlink":
            _unlink_exact(operation.path, operation.trusted_root or operation.path.parent)
    for operation in sorted(
        (item for item in selected if item.action == "rmdir"),
        key=lambda item: (len(item.path.parts), os.fspath(item.path)),
        reverse=True,
    ):
        _remove_empty_directory(operation.path, operation.trusted_root or operation.path.parent)


def _unlink_exact(path: Path, trusted_root: Path) -> None:
    _safe_path(path, trusted_root)
    if not paths.long_path(path).is_file():
        raise A2LError("privacy purge target changed before removal")
    os.unlink(os.fspath(paths.long_path(path)))


def _remove_empty_directory(path: Path, trusted_root: Path) -> None:
    _safe_path(path, trusted_root)
    if not paths.long_path(path).is_dir():
        raise A2LError("privacy purge directory target changed before removal")
    try:
        os.rmdir(os.fspath(paths.long_path(path)))
    except OSError as exc:
        raise A2LError("privacy purge left an unexpected file in a managed directory") from exc


def _validate_explicit_tree(path: Path, trusted_root: Path) -> None:
    _safe_path(path, trusted_root)
    for candidate in paths.walk(path):
        _safe_path(candidate, trusted_root)
        if paths.is_link(candidate):
            raise A2LError("privacy purge refuses a symlinked managed revision")
        if not paths.long_path(candidate).is_file() and not paths.long_path(candidate).is_dir():
            raise A2LError("privacy purge found an unsupported managed revision entry")


def _remove_explicit_tree(path: Path, trusted_root: Path) -> None:
    _validate_explicit_tree(path, trusted_root)
    candidates = list(paths.walk(path))
    for candidate in sorted(
        (item for item in candidates if paths.long_path(item).is_file()),
        key=lambda item: len(item.relative_to(path).parts),
        reverse=True,
    ):
        _unlink_exact(candidate, trusted_root)
    for candidate in sorted(
        (item for item in candidates if paths.long_path(item).is_dir()),
        key=lambda item: len(item.relative_to(path).parts),
        reverse=True,
    ):
        _remove_empty_directory(candidate, trusted_root)
    _remove_empty_directory(path, trusted_root)


def _safe_path(path: Path, root: Path) -> None:
    if paths.is_link(path) or paths.has_link_component(path, root=root):
        raise A2LError("privacy purge refuses a symlinked target")
    absolute = Path(os.path.abspath(os.fspath(path)))
    trusted = Path(os.path.abspath(os.fspath(root)))
    try:
        absolute.relative_to(trusted)
    except ValueError as exc:
        raise A2LError("privacy target path escapes its trusted root") from exc


def _object_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if paths.is_link(path):
        raise A2LError("privacy purge refuses a symlinked target")
    if paths.long_path(path).is_file():
        digest.update(b"file\0")
        with open(os.fspath(paths.long_path(path)), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if paths.long_path(path).is_dir():
        digest.update(b"directory\0")
        for candidate in sorted(paths.walk(path), key=os.fspath):
            if paths.is_link(candidate):
                raise A2LError("privacy purge refuses a symlinked target")
            relative = candidate.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            if paths.long_path(candidate).is_file():
                with open(os.fspath(paths.long_path(candidate)), "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()
    raise A2LError("privacy purge target changed before preview")


def _reject_links_in_managed_directory(directory: Path, label: str) -> None:
    try:
        for candidate in paths.walk(directory):
            if paths.is_link(candidate):
                raise A2LError(f"privacy purge refuses a symlinked managed {label} entry")
    except OSError as exc:
        raise A2LError(f"privacy {label} inventory is unreadable") from exc


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A2LError(f"{label} is unreadable") from exc
    if not isinstance(raw, dict):
        raise A2LError(f"{label} must contain an object")
    return cast(dict[str, object], raw)


def _read_text(path: Path, label: str) -> str:
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeError) as exc:
        raise A2LError(f"{label} is unreadable") from exc


def _directory_children(directory: Path, label: str) -> list[Path]:
    try:
        with os.scandir(os.fspath(paths.long_path(directory))) as iterator:
            return sorted(
                (directory / entry.name for entry in iterator), key=lambda item: item.name
            )
    except OSError as exc:
        raise A2LError(f"{label} is unreadable") from exc


def _canonical_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )


def _vault_display(vault: Vault, path: Path) -> str:
    try:
        relative = path.relative_to(vault.root).as_posix()
    except ValueError:
        return "<schema backup>/managed state"
    return f"<vault>/{relative}"


def _display_path(vault: Vault, path: Path, trusted_root: Path) -> str:
    if trusted_root == vault.root:
        return _vault_display(vault, path)
    if trusted_root == Path(config.DIRS.user_log_path):
        return f"<configured log directory>/{path.name}"
    try:
        relative = path.relative_to(trusted_root).as_posix()
    except ValueError:
        relative = path.name
    return f"<schema backup>/{relative}"


__all__ = [
    "PrivacyStatus",
    "PurgePlan",
    "PurgeResult",
    "PurgeTarget",
    "execute_purge",
    "plan_purge",
    "purge",
    "render_plan",
    "render_status",
    "status",
]
