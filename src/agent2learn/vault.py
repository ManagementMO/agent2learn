"""Portable vault state, structured manifests, and revision-safe storage.

The manifest is the source of truth for course identity and provenance.  It stores only
vault-relative POSIX paths, and every path is resolved against the current vault root when it is
used.  A filename or display title is never treated as a source identity.

Revision preservation is deliberately a separate operation from installing a new source.  The
caller verifies and preserves the old revision first, then performs its own atomic materialized
file replacement and manifest update.  This keeps a failed history write from pretending that a
revision was safely archived.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, cast

from agent2learn import paths
from agent2learn.errors import A2LError

SCHEMA_VERSION = 1
MIGRATIONS: dict[int, Callable[[Vault], None]] = {}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_KEY_PART = re.compile(r"^[^:\\/:\s]+$")
_MANIFEST_KEYS = frozenset(
    {"path", "sha256", "source_id", "etag", "last_modified", "size", "fetched_at", "derived"}
)
_DERIVED_KEYS = frozenset({"path", "sha256", "source_sha256", "tool", "tool_version", "created_at"})
_GIT_CONFIRMATION = "I UNDERSTAND THIS VAULT IS IN A GIT WORKTREE"
_COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DerivedArtifact:
    """A generated artifact tied to one exact source revision."""

    path: str
    sha256: str
    source_sha256: str
    tool: str
    tool_version: str
    created_at: str


@dataclass(frozen=True)
class ManifestEntry:
    """A structured record for one stable remote source identity."""

    path: str
    sha256: str
    source_id: str
    etag: str | None
    last_modified: str | None
    size: int
    fetched_at: str
    derived: Mapping[str, DerivedArtifact] = field(default_factory=dict)


class Vault:
    """Access a portable Agent2Learn vault rooted at ``root``."""

    root: Path
    _entries: dict[str, ManifestEntry]
    _loaded: bool

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self._entries = {}
        self._loaded = False

    def state(self) -> Path:
        """Return the vault-scoped state directory."""

        return self.root / ".a2l"

    def history_bucket(self, source_key: str) -> Path:
        """Return and create the opaque history bucket for a canonical source key."""

        _validate_source_key(source_key)
        check_schema(self)
        bucket = self.state() / "history" / sha256(source_key.encode("utf-8")).hexdigest()
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket

    def manifest(self) -> dict[str, ManifestEntry]:
        """Load, validate, and return a copy of the structured manifest."""

        check_schema(self)
        if self._loaded:
            return dict(self._entries)

        destination = self.state() / "manifest.json"
        if not destination.is_file():
            self._entries = {}
            self._loaded = True
            return {}

        raw = _read_json_object(destination, "manifest")
        schema_version = raw.get("schema_version")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise A2LError("manifest schema_version must be an integer")
        if schema_version != SCHEMA_VERSION:
            raise A2LError(
                f"manifest schema version {schema_version} does not match tool schema "
                f"{SCHEMA_VERSION}"
            )

        entries_raw = raw.get("entries")
        if not isinstance(entries_raw, dict):
            raise A2LError("manifest entries must be an object")

        entries: dict[str, ManifestEntry] = {}
        for key, raw_entry in entries_raw.items():
            if not isinstance(key, str):
                raise A2LError("manifest entry keys must be canonical source keys")
            entries[key] = _entry_from_json(key, raw_entry)

        unknown = set(raw) - {"schema_version", "entries"}
        if unknown:
            raise A2LError(f"manifest contains unknown top-level fields: {sorted(unknown)!r}")

        self._entries = entries
        self._loaded = True
        return dict(entries)

    def entry(self, key: str) -> ManifestEntry | None:
        """Return one manifest entry by canonical source key."""

        _validate_source_key(key)
        return self.manifest().get(key)

    def materialized(self, entry: ManifestEntry) -> Path:
        """Resolve a validated manifest path against this vault's current root."""

        validated = _validate_entry(entry)
        return self._materialized_path(validated.path)

    def mark(self, key: str, entry: ManifestEntry) -> None:
        """Validate and stage a manifest entry for the next atomic save."""

        _validate_source_key(key)
        if not self._loaded:
            self.manifest()
        checked = _validate_entry(entry)
        _validate_source_id(key, checked.source_id)
        self._entries[key] = checked

    def preserve_revision(self, key: str, *, changed_at: datetime) -> Path | None:
        """Atomically preserve the verified current source before replacing its bytes.

        ``None`` means the source is not materialized yet.  A materialized source whose bytes no
        longer match the manifest raises an integrity gap instead of inventing a revision from
        untrusted local data.
        """

        _validate_source_key(key)
        changed_utc = _utc_datetime(changed_at, "changed_at")
        current = self.entry(key)
        if current is None:
            return None

        source = self.materialized(current)
        revision_source = _allocate_revision_directory(
            self.history_bucket(key), changed_utc.strftime("%Y%m%dT%H%M%SZ")
        )
        try:
            saved_source = revision_source / PurePosixPath(current.path).name
            if not _copy_verified(
                source,
                saved_source,
                expected_sha256=current.sha256,
                expected_size=current.size,
            ):
                shutil.rmtree(revision_source)
                return None

            derived_metadata: dict[str, dict[str, object]] = {}
            for name, artifact in current.derived.items():
                artifact_path = self._materialized_path(artifact.path)
                artifact_destination = (
                    revision_source / "derived" / PurePosixPath(artifact.path).name
                )
                if not _copy_verified(
                    artifact_path,
                    artifact_destination,
                    expected_sha256=None,
                    expected_size=None,
                ):
                    derived_metadata[name] = {
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                        "source_sha256": artifact.source_sha256,
                        "tool": artifact.tool,
                        "tool_version": artifact.tool_version,
                        "created_at": artifact.created_at,
                        "status": "missing",
                    }
                    continue

                actual_sha256, actual_size = _hash_file(artifact_path)
                derived_metadata[name] = {
                    "path": artifact.path,
                    "sha256": artifact.sha256,
                    "source_sha256": artifact.source_sha256,
                    "tool": artifact.tool,
                    "tool_version": artifact.tool_version,
                    "created_at": artifact.created_at,
                    "actual_sha256": actual_sha256,
                    "size": actual_size,
                    "status": (
                        "verified" if actual_sha256 == artifact.sha256 else "local-modification"
                    ),
                }

            metadata = {
                "canonical_key": key,
                "fetched_at": current.fetched_at,
                "new_sha256": None,
                "old_sha256": current.sha256,
                "path": current.path,
                "preserved_at": changed_utc.isoformat().replace("+00:00", "Z"),
                "size": current.size,
                "source_key": key,
                "derived": derived_metadata,
            }
            paths.atomic_write_text(revision_source / "revision.json", _canonical_json(metadata))
            return saved_source
        except BaseException:
            shutil.rmtree(revision_source, ignore_errors=True)
            raise

    def save_manifest(self) -> None:
        """Atomically save the canonical manifest and current schema marker."""

        check_schema(self)
        if not self._loaded:
            self.manifest()

        payload = {
            "entries": {
                key: _entry_to_json(_validate_source_entry(key, entry))
                for key, entry in sorted(self._entries.items(), key=lambda item: item[0])
            },
            "schema_version": SCHEMA_VERSION,
        }
        paths.atomic_write_text(self.state() / "manifest.json", _canonical_json(payload))

    def semesters(self) -> list[Path]:
        """Return direct child term directories that carry semester metadata."""

        if not self.root.is_dir():
            return []
        return sorted(
            (
                child
                for child in self.root.iterdir()
                if child.is_dir() and (child / "_SEMESTER_METADATA.json").is_file()
            ),
            key=lambda path: path.name,
        )

    @staticmethod
    def is_vault(p: Path) -> bool:
        """Return whether ``p`` has an Agent2Learn marker."""

        candidate = Path(p)
        return (candidate / ".a2l").is_dir() or (candidate / "_SEMESTER_METADATA.json").is_file()

    @classmethod
    def claim(cls, p: Path) -> Path:
        """Claim a new vault root without adopting an unrelated directory."""

        requested = Path(p).expanduser().resolve()
        _refuse_agent2learn_checkout(requested)
        _require_git_confirmation_if_needed(requested)

        candidate = requested
        suffix = 2
        while True:
            if cls.is_vault(candidate):
                return candidate
            if not _occupied(candidate):
                try:
                    candidate.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    candidate = requested.with_name(f"{requested.name}-{suffix}")
                    suffix += 1
                    continue
                _write_vault_gitignore(candidate)
                (candidate / ".a2l").mkdir()
                check_schema(cls(candidate))
                return candidate
            candidate = requested.with_name(f"{requested.name}-{suffix}")
            suffix += 1

    def _materialized_path(self, relative: str) -> Path:
        _validate_relative_posix(relative, field="path")
        candidate = (self.root / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise A2LError("manifest path escapes the vault root") from exc
        return candidate


def check_schema(v: Vault) -> None:
    """Check or migrate a vault schema, refusing to write newer vaults."""

    state = v.state()
    state.mkdir(parents=True, exist_ok=True)
    version_path = state / "VERSION"
    if not version_path.is_file():
        paths.atomic_write_text(version_path, f"{SCHEMA_VERSION}\n")
        return

    raw_version = _read_text(version_path).strip()
    try:
        version = int(raw_version)
    except ValueError as exc:
        raise A2LError("vault VERSION must contain one integer") from exc
    if version < 0 or str(version) != raw_version:
        raise A2LError("vault VERSION must contain one non-negative integer")
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise A2LError(
            f"vault schema {version} is newer than this tool's schema {SCHEMA_VERSION}; "
            "run a2l upgrade"
        )

    backup = _backup_state(state, version)
    del backup  # The path is useful in a debugger; migration errors retain the backup.
    current = version
    while current < SCHEMA_VERSION:
        migration = MIGRATIONS.get(current)
        if migration is None:
            raise A2LError(
                f"vault schema {version} is older than {SCHEMA_VERSION} and has no "
                f"registered migration from {current}"
            )
        migration(v)
        current += 1
    paths.atomic_write_text(version_path, f"{SCHEMA_VERSION}\n")


def _entry_from_json(key: str, raw: object) -> ManifestEntry:
    _validate_source_key(key)
    if not isinstance(raw, dict):
        raise A2LError(f"manifest entry for {key!r} must be an object")
    unknown = set(raw) - _MANIFEST_KEYS
    if unknown:
        raise A2LError(f"manifest entry for {key!r} has unknown fields: {sorted(unknown)!r}")

    required = _required_fields(raw, _MANIFEST_KEYS - {"derived"}, f"entry {key!r}")
    source_id = _as_str(required["source_id"], "source_id")
    _validate_source_id(key, source_id)

    derived_raw = raw.get("derived", {})
    if not isinstance(derived_raw, dict):
        raise A2LError(f"derived artifacts for {key!r} must be an object")
    derived: dict[str, DerivedArtifact] = {}
    for name, artifact in derived_raw.items():
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise A2LError("derived artifact names must be simple non-empty strings")
        derived[name] = _artifact_from_json(name, artifact, required["sha256"])

    return _validate_entry(
        ManifestEntry(
            path=_as_str(required["path"], "path"),
            sha256=_as_str(required["sha256"], "sha256"),
            source_id=source_id,
            etag=_as_optional_str(required["etag"], "etag"),
            last_modified=_as_optional_str(required["last_modified"], "last_modified"),
            size=_as_nonnegative_int(required["size"], "size"),
            fetched_at=_as_str(required["fetched_at"], "fetched_at"),
            derived=derived,
        )
    )


def _artifact_from_json(name: str, raw: object, source_sha256: object) -> DerivedArtifact:
    if not isinstance(raw, dict):
        raise A2LError(f"derived artifact {name!r} must be an object")
    unknown = set(raw) - _DERIVED_KEYS
    if unknown:
        raise A2LError(f"derived artifact {name!r} has unknown fields: {sorted(unknown)!r}")
    required = _required_fields(raw, _DERIVED_KEYS, f"derived artifact {name!r}")
    if required["source_sha256"] != source_sha256:
        raise A2LError(f"derived artifact {name!r} source_sha256 does not match parent")
    return _validate_artifact(
        DerivedArtifact(
            path=_as_str(required["path"], "derived path"),
            sha256=_as_str(required["sha256"], "derived sha256"),
            source_sha256=_as_str(required["source_sha256"], "source_sha256"),
            tool=_as_str(required["tool"], "tool"),
            tool_version=_as_str(required["tool_version"], "tool_version"),
            created_at=_as_str(required["created_at"], "created_at"),
        )
    )


def _validate_entry(entry: ManifestEntry) -> ManifestEntry:
    if not isinstance(entry, ManifestEntry):
        raise A2LError("manifest entries must be ManifestEntry values")
    _validate_relative_posix(entry.path, field="relative POSIX path")
    _validate_hash(entry.sha256, "sha256")
    if not isinstance(entry.source_id, str) or not entry.source_id:
        raise A2LError("source_id must be a non-empty string")
    if entry.etag is not None and not isinstance(entry.etag, str):
        raise A2LError("etag must be a string or null")
    if entry.last_modified is not None and not isinstance(entry.last_modified, str):
        raise A2LError("last_modified must be a string or null")
    if isinstance(entry.size, bool) or not isinstance(entry.size, int) or entry.size < 0:
        raise A2LError("size must be a non-negative integer")
    fetched_at = _manifest_timestamp(entry.fetched_at, "fetched_at")
    derived: dict[str, DerivedArtifact] = {}
    if not isinstance(entry.derived, Mapping):
        raise A2LError("derived artifacts must be a mapping")
    derived_paths: set[str] = set()
    for name, artifact in entry.derived.items():
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise A2LError("derived artifact names must be simple non-empty strings")
        checked = _validate_artifact(artifact)
        if checked.source_sha256 != entry.sha256:
            raise A2LError(f"derived artifact {name!r} source_sha256 does not match parent")
        if checked.path == entry.path:
            raise A2LError(f"derived artifact {name!r} path must differ from source path")
        if checked.path in derived_paths:
            raise A2LError(f"derived artifact {name!r} duplicates another artifact path")
        derived_paths.add(checked.path)
        derived[name] = checked
    return ManifestEntry(
        path=entry.path,
        sha256=entry.sha256,
        source_id=entry.source_id,
        etag=entry.etag,
        last_modified=entry.last_modified,
        size=entry.size,
        fetched_at=fetched_at,
        derived=derived,
    )


def _validate_source_entry(key: str, entry: ManifestEntry) -> ManifestEntry:
    _validate_source_key(key)
    checked = _validate_entry(entry)
    _validate_source_id(key, checked.source_id)
    return checked


def _validate_source_id(key: str, source_id: str) -> None:
    if source_id != key.rsplit(":", 1)[1]:
        raise A2LError(f"source_id for {key!r} does not match its canonical entity ID")


def _validate_artifact(artifact: DerivedArtifact) -> DerivedArtifact:
    if not isinstance(artifact, DerivedArtifact):
        raise A2LError("derived artifacts must be DerivedArtifact values")
    _validate_relative_posix(artifact.path, field="derived relative POSIX path")
    _validate_hash(artifact.sha256, "derived sha256")
    _validate_hash(artifact.source_sha256, "source_sha256")
    for field_name in ("tool", "tool_version"):
        value = getattr(artifact, field_name)
        if not isinstance(value, str) or not value:
            raise A2LError(f"{field_name} must be a non-empty string")
    return DerivedArtifact(
        path=artifact.path,
        sha256=artifact.sha256,
        source_sha256=artifact.source_sha256,
        tool=artifact.tool,
        tool_version=artifact.tool_version,
        created_at=_manifest_timestamp(artifact.created_at, "created_at"),
    )


def _entry_to_json(entry: ManifestEntry) -> dict[str, object]:
    checked = _validate_entry(entry)
    return {
        "derived": {
            name: {
                "created_at": artifact.created_at,
                "path": artifact.path,
                "sha256": artifact.sha256,
                "source_sha256": artifact.source_sha256,
                "tool": artifact.tool,
                "tool_version": artifact.tool_version,
            }
            for name, artifact in sorted(checked.derived.items(), key=lambda item: item[0])
        },
        "etag": checked.etag,
        "fetched_at": checked.fetched_at,
        "last_modified": checked.last_modified,
        "path": checked.path,
        "sha256": checked.sha256,
        "size": checked.size,
        "source_id": checked.source_id,
    }


def _validate_source_key(key: str) -> None:
    if not isinstance(key, str):
        raise A2LError("canonical source key must be a string")
    parts = key.split(":")
    if len(parts) != 4 or any(not _KEY_PART.fullmatch(part) for part in parts):
        raise A2LError("canonical source key must be school:course_org_unit:entity_kind:entity_id")


def _validate_relative_posix(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise A2LError(f"{field} must be a non-empty relative POSIX path")
    if "\\" in value or value.startswith("/") or _WINDOWS_ABSOLUTE.match(value):
        raise A2LError(f"{field} must be relative POSIX")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise A2LError(f"{field} must be relative POSIX and cannot escape the root")
    if pure.as_posix() != value:
        raise A2LError(f"{field} must be normalized relative POSIX")


def _validate_hash(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise A2LError(f"{field} must be a lowercase 64-character SHA-256")


def _manifest_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise A2LError(f"{field} must be a timezone-aware ISO 8601 UTC timestamp")
    parsed = _parse_timestamp(value, field)
    if parsed.utcoffset() != timedelta(0):
        raise A2LError(f"{field} must be a timezone-aware ISO 8601 UTC timestamp")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise A2LError(f"{field} must be a timezone-aware ISO 8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise A2LError(f"{field} must be timezone-aware")
    return parsed


def _utc_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise A2LError(f"{field} must be timezone-aware UTC")
    return value.astimezone(UTC)


def _required_fields(
    raw: Mapping[str, object], fields: Collection[str], context: str
) -> dict[str, object]:
    missing = set(fields) - raw.keys()
    if missing:
        raise A2LError(f"{context} is missing fields: {sorted(missing)!r}")
    return {key: raw[key] for key in fields}


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise A2LError(f"{field} must be a string")
    return value


def _as_optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2LError(f"{field} must be a string or null")
    return value


def _as_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise A2LError(f"{field} must be a non-negative integer")
    return value


def _read_json_object(destination: Path, label: str) -> dict[str, object]:
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise A2LError(f"{label} is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise A2LError(f"{label} root must be an object")
    return cast(dict[str, object], raw)


def _read_text(destination: Path) -> str:
    with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
        return handle.read()


def _canonical_json(payload: object) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )


def _hash_file(source: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    try:
        with open(os.fspath(paths.long_path(source)), "rb") as handle:
            while chunk := handle.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    except (FileNotFoundError, IsADirectoryError):
        return "", -1
    return digest.hexdigest(), size


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None,
) -> bool:
    """Stream a source into a sibling ``.part`` and atomically install it if valid."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=os.fspath(paths.long_path(destination.parent)),
    )
    os.close(file_descriptor)
    temporary = Path(raw_temporary)
    digest = sha256()
    size = 0
    try:
        with (
            open(os.fspath(paths.long_path(source)), "rb") as input_handle,
            open(os.fspath(paths.long_path(temporary)), "wb") as output_handle,
        ):
            while chunk := input_handle.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        actual_sha256 = digest.hexdigest()
        if expected_sha256 is not None and (
            actual_sha256 != expected_sha256
            or (expected_size is not None and size != expected_size)
        ):
            raise A2LError("manifest source hash mismatch: integrity gap")
        paths.atomic_install_temp(destination, temporary)
        return True
    except (FileNotFoundError, IsADirectoryError):
        return False
    finally:
        with suppress(FileNotFoundError):
            os.unlink(os.fspath(paths.long_path(temporary)))


def _allocate_revision_directory(bucket: Path, timestamp: str) -> Path:
    for number in range(1, 100_000):
        suffix = "" if number == 1 else f"_{number}"
        candidate = bucket / f"{timestamp}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise A2LError("could not allocate a collision-safe revision directory")


def _backup_state(state: Path, version: int) -> Path:
    base = state.parent / f".a2l-backup-v{version}"
    candidate = base
    number = 2
    while candidate.exists():
        candidate = state.parent / f".a2l-backup-v{version}-{number}"
        number += 1
    shutil.copytree(state, candidate, symlinks=True)
    return candidate


def _occupied(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _write_vault_gitignore(root: Path) -> None:
    paths.atomic_write_text(
        root / ".gitignore",
        ".a2l/\n**/_meta/my_grades.json\n**/discussions/\n**/.a2l/submissions/\n",
    )


def _refuse_agent2learn_checkout(path: Path) -> None:
    source_root = _agent2learn_source_root()
    if source_root is None:
        return
    try:
        path.relative_to(source_root)
    except ValueError:
        return
    raise A2LError("refusing to place a vault inside the Agent2Learn source checkout")


def _require_git_confirmation_if_needed(path: Path) -> None:
    repository_root = _git_root(path)
    if repository_root is None:
        return
    if not sys.stdin.isatty():
        raise A2LError(
            f"selected vault is inside Git worktree {repository_root}; explicit TTY confirmation "
            "is required"
        )
    try:
        answer = input(
            f"Selected vault is inside Git worktree {repository_root}. "
            f"Type {_GIT_CONFIRMATION!r} to continue: "
        )
    except EOFError as exc:
        raise A2LError("vault claim cancelled: no TTY confirmation") from exc
    if answer.strip() != _GIT_CONFIRMATION:
        raise A2LError("vault claim cancelled: explicit Git worktree confirmation did not match")


def _agent2learn_source_root() -> Path | None:
    package_root = Path(__file__).resolve().parents[2]
    repository_root = _git_root(package_root)
    if repository_root is None:
        return None
    if (repository_root / "pyproject.toml").is_file() and (
        repository_root / "src" / "agent2learn"
    ).is_dir():
        return repository_root
    return None


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(probe), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


__all__ = [
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "DerivedArtifact",
    "ManifestEntry",
    "Vault",
    "check_schema",
]
