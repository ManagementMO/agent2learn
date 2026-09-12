from __future__ import annotations

import json
import os
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from agent2learn import clock, paths
from agent2learn.errors import A2LError
from agent2learn.vault import (
    ManifestEntry,
    Vault,
    _copy_verified,
    _entry_from_json,
    _entry_to_json,
    _hash_file,
    _validate_source_entry,
    _validate_source_key,
)


def _directory(vault: Vault, key: str) -> Path:
    _validate_source_key(key)
    result = vault.state() / "pending-generated" / sha256(key.encode()).hexdigest()
    if paths.has_link_component(result, root=vault.root):
        raise A2LError("generated revision state contains a link component")
    return result


def _files(entry: ManifestEntry) -> list[tuple[str, str]]:
    return [
        (entry.path, entry.sha256),
        *((artifact.path, artifact.sha256) for _, artifact in sorted(entry.derived.items())),
    ]


def _fingerprint(path: Path) -> str | None:
    fingerprint, size = _hash_file(path)
    if size < 0:
        if paths.collides(path):
            raise A2LError("generated revision destination is unreadable")
        return None
    return fingerprint


def recover_generated(vault: Vault, key: str) -> None:
    directory = _directory(vault, key)
    if not paths.long_path(directory).exists():
        return
    journal = directory / "entry.json"
    if not paths.long_path(journal).exists():
        for child in paths.long_path(directory).iterdir():
            if (
                child.suffix != ".part"
                or not child.stem.isdigit()
                or paths.is_link(child)
                or not paths.long_path(child).is_file()
            ):
                raise A2LError("unrecognized pending generated revision")
        paths.remove_tree(directory)
        return
    if paths.has_link_component(journal, root=vault.root):
        raise A2LError("generated revision journal contains a link component")
    with open(os.fspath(paths.long_path(journal)), encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or set(raw) != {"version", "key", "prior", "entry", "before"}:
        raise A2LError("generated revision journal is invalid")
    if type(raw["version"]) is not int or raw["version"] != 1 or raw["key"] != key:
        raise A2LError("generated revision journal is invalid")
    entry = _entry_from_json(key, raw["entry"])
    prior = _entry_from_json(key, raw["prior"]) if raw["prior"] is not None else None
    current = Vault(vault.root).entry(key)
    if current not in (prior, entry):
        raise A2LError("generated revision conflicts with the current manifest")
    files = _files(entry)
    before = raw["before"]
    if not isinstance(before, dict) or set(before) != {path for path, _ in files}:
        raise A2LError("generated revision journal paths are invalid")
    for fingerprint in before.values():
        if fingerprint is not None and (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            raise A2LError("generated revision journal digests are invalid")
    staged: list[tuple[Path, Path, str, str | None]] = []
    for index, (relative, fingerprint) in enumerate(files):
        destination = vault._materialized_path(relative)
        part = directory / f"{index}.part"
        if paths.has_link_component(part, root=vault.root):
            raise A2LError("generated revision part contains a link component")
        actual = _fingerprint(destination)
        if actual not in (before[relative], fingerprint):
            raise A2LError("pending generated revision has locally modified destination bytes")
        if paths.long_path(part).exists():
            if _fingerprint(part) != fingerprint:
                raise A2LError("pending generated revision part failed integrity validation")
            if actual != fingerprint:
                staged.append((destination, part, fingerprint, before[relative]))
        elif actual != fingerprint:
            raise A2LError("pending generated revision has missing bytes")
    for destination, part, fingerprint, previous in staged:
        if _fingerprint(destination) not in (previous, fingerprint):
            raise A2LError("pending generated revision changed during recovery")
        if not _copy_verified(
            part, destination, root=vault.root, expected_sha256=fingerprint, expected_size=None
        ):
            raise A2LError("pending generated revision could not be installed")
    vault.mark(key, entry)
    vault.save_manifest()
    paths.remove_tree(directory)


def install_generated(
    vault: Vault,
    key: str,
    entry: ManifestEntry,
    source: bytes,
    derived: Mapping[str, bytes],
    *,
    preserve: bool,
) -> None:
    recover_generated(vault, key)
    entry = _validate_source_entry(key, entry)
    if set(derived) != set(entry.derived) or len(source) != entry.size:
        raise A2LError("generated revision content does not match its manifest")
    contents = [source, *(derived[name] for name in sorted(derived))]
    files = _files(entry)
    if any(
        sha256(content).hexdigest() != fingerprint
        for content, (_, fingerprint) in zip(contents, files, strict=True)
    ):
        raise A2LError("generated revision content failed integrity validation")
    before = {relative: _fingerprint(vault._materialized_path(relative)) for relative, _ in files}
    prior = vault.entry(key)
    if preserve and prior is not None:
        saved = vault.preserve_revision(key, changed_at=clock.now())
        if saved is None and any(value is not None for value in before.values()):
            raise A2LError("current generated revision could not be preserved")
    directory = _directory(vault, key)
    paths.ensure_dir(directory, root=vault.root)
    for index, content in enumerate(contents):
        paths.atomic_write_bytes(directory / f"{index}.part", content, root=vault.root)
    journal = {
        "version": 1,
        "key": key,
        "prior": _entry_to_json(prior) if prior is not None else None,
        "entry": _entry_to_json(entry),
        "before": before,
    }
    paths.atomic_write_text(
        directory / "entry.json",
        json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n",
        root=vault.root,
    )
    recover_generated(vault, key)
