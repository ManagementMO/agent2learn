"""Tests for the portable vault manifest and revision store."""

from __future__ import annotations

import builtins
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from agent2learn import paths
from agent2learn import vault as vault_module
from agent2learn.errors import A2LError
from agent2learn.vault import (
    MIGRATIONS,
    SCHEMA_VERSION,
    DerivedArtifact,
    ManifestEntry,
    Vault,
    check_schema,
)

KEY = "uwaterloo:1:topic:2"
FETCHED_AT = "2026-08-24T12:00:00Z"


def _entry(payload: bytes = b"portable") -> ManifestEntry:
    return ManifestEntry(
        path="T/C/a.pdf",
        sha256=sha256(payload).hexdigest(),
        source_id="2",
        etag='"v1"',
        last_modified=None,
        size=len(payload),
        fetched_at=FETCHED_AT,
    )


def _write_manifest(root: Path, entries: dict[str, object], *, schema_version: int = 1) -> None:
    state = root / ".a2l"
    state.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(
        state / "manifest.json",
        json.dumps(
            {"schema_version": schema_version, "entries": entries},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    paths.atomic_write_text(state / "VERSION", f"{schema_version}\n")


def test_manifest_entries_are_structured_and_relative(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")

    entry = ManifestEntry(
        path="T/C/a.pdf",
        sha256=sha256(b"x").hexdigest(),
        source_id="2",
        etag=None,
        last_modified=None,
        size=1,
        fetched_at=FETCHED_AT,
    )
    vault.mark(KEY, entry)
    vault.save_manifest()

    raw = json.loads((tmp_path / ".a2l" / "manifest.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["entries"][KEY]["path"] == "T/C/a.pdf"
    assert raw["entries"][KEY]["sha256"] == sha256(b"x").hexdigest()
    assert not Path(raw["entries"][KEY]["path"]).is_absolute()
    assert "\\" not in raw["entries"][KEY]["path"]


def test_vault_is_portable(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    source = first / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"portable")

    vault = Vault(first)
    vault.mark(KEY, _entry())
    vault.save_manifest()
    shutil.copytree(first, second)

    moved = Vault(second)
    entry = moved.entry(KEY)
    assert entry is not None
    assert moved.materialized(entry) == second / "T" / "C" / "a.pdf"
    assert moved.materialized(entry).read_bytes() == b"portable"


def test_manifest_round_trip_reconstructs_derived_artifact(tmp_path: Path) -> None:
    source_hash = sha256(b"source").hexdigest()
    derived = DerivedArtifact(
        path="T/C/a.md",
        sha256=sha256(b"markdown").hexdigest(),
        source_sha256=source_hash,
        tool="synthetic-converter",
        tool_version="1.0",
        created_at=FETCHED_AT,
    )
    entry = ManifestEntry(
        path="T/C/a.pdf",
        sha256=source_hash,
        source_id="2",
        etag=None,
        last_modified="2026-08-24T11:59:00Z",
        size=6,
        fetched_at=FETCHED_AT,
        derived={"markdown": derived},
    )
    vault = Vault(tmp_path)
    vault.mark(KEY, entry)
    vault.save_manifest()

    loaded = vault.entry(KEY)
    assert loaded == entry
    assert loaded is not None
    assert loaded.derived["markdown"] == derived


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("path", "../escape.pdf", "relative POSIX"),
        ("path", "/absolute.pdf", "relative POSIX"),
        ("path", "T\\C\\escape.pdf", "relative POSIX"),
        ("path", "C:/absolute.pdf", "relative POSIX"),
        ("sha256", "A" * 64, "lowercase"),
        ("sha256", "0" * 63, "SHA-256"),
        ("size", -1, "non-negative"),
        ("fetched_at", "2026-08-24T12:00:00", "timezone-aware"),
        ("fetched_at", "2026-08-24T12:00:00-04:00", "UTC"),
    ],
)
def test_manifest_rejects_invalid_entry_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    payload = {
        "path": "T/C/a.pdf",
        "sha256": "0" * 64,
        "source_id": "2",
        "etag": None,
        "last_modified": None,
        "size": 0,
        "fetched_at": FETCHED_AT,
    }
    payload[field] = value
    _write_manifest(tmp_path, {KEY: payload})

    with pytest.raises(A2LError, match=message):
        Vault(tmp_path).manifest()


def test_manifest_rejects_bad_keys_and_unknown_entry_fields(tmp_path: Path) -> None:
    payload = {
        "path": "T/C/a.pdf",
        "sha256": "0" * 64,
        "source_id": "2",
        "etag": None,
        "last_modified": None,
        "size": 0,
        "fetched_at": FETCHED_AT,
        "unexpected": True,
    }
    _write_manifest(tmp_path, {"uwaterloo:1:topic": payload})

    with pytest.raises(A2LError, match="canonical source key"):
        Vault(tmp_path).manifest()


def test_manifest_requires_source_id_to_match_canonical_key(tmp_path: Path) -> None:
    payload = {
        "path": "T/C/a.pdf",
        "sha256": "0" * 64,
        "source_id": "different-id",
        "etag": None,
        "last_modified": None,
        "size": 0,
        "fetched_at": FETCHED_AT,
    }
    _write_manifest(tmp_path, {KEY: payload})

    with pytest.raises(A2LError, match="entity ID"):
        Vault(tmp_path).manifest()


def test_manifest_rejects_non_object_and_unknown_schema(tmp_path: Path) -> None:
    state = tmp_path / ".a2l"
    state.mkdir()
    paths.atomic_write_text(state / "manifest.json", "[]\n")
    paths.atomic_write_text(state / "VERSION", "1\n")
    with pytest.raises(A2LError, match="object"):
        Vault(tmp_path).manifest()

    _write_manifest(tmp_path, {}, schema_version=99)
    with pytest.raises(A2LError, match="schema"):
        Vault(tmp_path).manifest()


def test_manifest_reports_malformed_utf8_as_a2l_error(tmp_path: Path) -> None:
    state = tmp_path / ".a2l"
    state.mkdir()
    (state / "manifest.json").write_bytes(b"{\xff")
    paths.atomic_write_text(state / "VERSION", "1\n")

    with pytest.raises(A2LError, match="manifest is not valid JSON"):
        Vault(tmp_path).manifest()


def test_manifest_reports_filesystem_read_failure_as_a2l_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".a2l"
    state.mkdir()
    (state / "manifest.json").write_text("{}\n", encoding="utf-8")
    paths.atomic_write_text(state / "VERSION", "1\n")

    def denied(*args: object, **kwargs: object) -> object:
        if args and str(args[0]).endswith("manifest.json"):
            raise PermissionError("manifest denied")
        return builtins.open(*args, **kwargs)

    monkeypatch.setattr(vault_module, "open", denied, raising=False)

    with pytest.raises(A2LError, match="manifest is unreadable"):
        Vault(tmp_path).manifest()


def test_derived_artifact_requires_matching_source_hash_and_safe_metadata(tmp_path: Path) -> None:
    entry = _entry()
    raw = {
        "path": entry.path,
        "sha256": entry.sha256,
        "source_id": entry.source_id,
        "etag": entry.etag,
        "last_modified": entry.last_modified,
        "size": entry.size,
        "fetched_at": entry.fetched_at,
        "derived": {
            "markdown": {
                "path": "T/C/a.md",
                "sha256": "0" * 64,
                "source_sha256": "1" * 64,
                "tool": "converter",
                "tool_version": "1.0",
                "created_at": FETCHED_AT,
            }
        },
    }
    _write_manifest(tmp_path, {KEY: raw})

    with pytest.raises(A2LError, match="source_sha256"):
        Vault(tmp_path).manifest()


def test_derived_artifact_rejects_unsafe_path_and_hash(tmp_path: Path) -> None:
    entry = _entry()
    raw = {
        "path": entry.path,
        "sha256": entry.sha256,
        "source_id": entry.source_id,
        "etag": entry.etag,
        "last_modified": entry.last_modified,
        "size": entry.size,
        "fetched_at": entry.fetched_at,
        "derived": {
            "markdown": {
                "path": "../a.md",
                "sha256": "not-a-hash",
                "source_sha256": entry.sha256,
                "tool": "converter",
                "tool_version": "1.0",
                "created_at": FETCHED_AT,
            }
        },
    }
    _write_manifest(tmp_path, {KEY: raw})

    with pytest.raises(A2LError, match="relative POSIX"):
        Vault(tmp_path).manifest()


def test_manifest_rejects_non_mapping_derived_data(tmp_path: Path) -> None:
    entry = _entry()
    raw = {
        "path": entry.path,
        "sha256": entry.sha256,
        "source_id": entry.source_id,
        "etag": entry.etag,
        "last_modified": entry.last_modified,
        "size": entry.size,
        "fetched_at": entry.fetched_at,
        "derived": [],
    }
    _write_manifest(tmp_path, {KEY: raw})

    with pytest.raises(A2LError, match="derived artifacts"):
        Vault(tmp_path).manifest()


def test_materialized_path_is_always_resolved_from_current_root(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    entry = _entry()
    first.mkdir()
    second.mkdir()

    assert Vault(first).materialized(entry) == first / "T" / "C" / "a.pdf"
    assert Vault(second).materialized(entry) == second / "T" / "C" / "a.pdf"


def test_changed_source_preserves_previous_revision_and_full_key(tmp_path: Path) -> None:
    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"old")

    vault = Vault(tmp_path)
    vault.mark(KEY, _entry(b"old"))
    vault.save_manifest()
    saved = vault.preserve_revision(
        KEY,
        changed_at=datetime(2026, 8, 24, 12, 5, tzinfo=UTC),
    )

    assert saved is not None
    assert saved.read_bytes() == b"old"
    bucket = sha256(KEY.encode("utf-8")).hexdigest()
    assert saved.is_relative_to(tmp_path / ".a2l" / "history" / bucket)
    metadata = json.loads(saved.parent.joinpath("revision.json").read_text(encoding="utf-8"))
    assert metadata["source_key"] == KEY
    assert metadata["old_sha256"] == sha256(b"old").hexdigest()
    assert metadata["path"] == "T/C/a.pdf"


def test_revision_directories_are_collision_safe(tmp_path: Path) -> None:
    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"old")
    vault = Vault(tmp_path)
    vault.mark(KEY, _entry(b"old"))
    vault.save_manifest()
    changed_at = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)

    first = vault.preserve_revision(KEY, changed_at=changed_at)
    second = vault.preserve_revision(KEY, changed_at=changed_at)

    assert first is not None
    assert second is not None
    assert first != second
    assert first.read_bytes() == second.read_bytes() == b"old"


def test_preserve_revision_reports_missing_and_mismatched_sources(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.mark(KEY, _entry(b"old"))
    vault.save_manifest()
    changed_at = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)

    assert vault.preserve_revision(KEY, changed_at=changed_at) is None

    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"different")
    with pytest.raises(A2LError, match="integrity gap"):
        vault.preserve_revision(KEY, changed_at=changed_at)


def test_preserve_revision_requires_aware_utc_timestamp(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.mark(KEY, _entry(b"old"))
    vault.save_manifest()
    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"old")

    with pytest.raises(A2LError, match="UTC"):
        vault.preserve_revision(KEY, changed_at=datetime(2026, 8, 24, 12, 5))


def test_interrupted_history_write_leaves_no_partial_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "T" / "C" / "a.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"old")
    vault = Vault(tmp_path)
    vault.mark(KEY, _entry(b"old"))
    vault.save_manifest()

    def fail_metadata(*args: object, **kwargs: object) -> None:
        raise OSError("simulated interrupted history write")

    monkeypatch.setattr(paths, "atomic_write_text", fail_metadata)
    with pytest.raises(OSError, match="interrupted"):
        vault.preserve_revision(
            KEY,
            changed_at=datetime(2026, 8, 24, 12, 5, tzinfo=UTC),
        )

    bucket = tmp_path / ".a2l" / "history" / sha256(KEY.encode("utf-8")).hexdigest()
    assert list(bucket.iterdir()) == []
    assert source.read_bytes() == b"old"
    assert not list(tmp_path.rglob("*.part"))


def test_schema_current_version_is_created_and_newer_version_is_read_only_refusal(
    tmp_path: Path,
) -> None:
    vault = Vault(tmp_path)
    check_schema(vault)
    assert (tmp_path / ".a2l" / "VERSION").read_text(encoding="utf-8") == "1\n"

    paths.atomic_write_text(tmp_path / ".a2l" / "VERSION", "99\n")
    with pytest.raises(A2LError, match="newer"):
        check_schema(vault)
    with pytest.raises(A2LError, match="newer"):
        vault.save_manifest()


def test_schema_does_not_invent_version_for_existing_state(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {KEY: _entry().__dict__})
    version_path = tmp_path / ".a2l" / "VERSION"
    version_path.unlink()
    manifest_path = tmp_path / ".a2l" / "manifest.json"
    original_manifest = manifest_path.read_bytes()

    with pytest.raises(A2LError, match="VERSION is missing"):
        check_schema(Vault(tmp_path))

    assert not version_path.exists()
    assert manifest_path.read_bytes() == original_manifest


@pytest.mark.skipif(os.name == "nt", reason="file symlinks require Windows privileges")
def test_schema_refuses_a_symlinked_version(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    check_schema(vault)
    version_path = tmp_path / ".a2l" / "VERSION"
    outside = tmp_path / "outside-version"
    outside.write_text("99\n", encoding="utf-8")
    version_path.unlink()
    version_path.symlink_to(outside)

    with pytest.raises(A2LError, match="VERSION.*symlink"):
        check_schema(vault)

    assert outside.read_text(encoding="utf-8") == "99\n"


def test_schema_older_version_requires_a_registered_migration(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    (tmp_path / ".a2l").mkdir()
    paths.atomic_write_text(tmp_path / ".a2l" / "VERSION", "0\n")

    with pytest.raises(A2LError, match="migration"):
        check_schema(vault)


def test_schema_migration_runs_once_and_commits_the_new_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_manifest(tmp_path, {KEY: _entry().__dict__})
    paths.atomic_write_text(tmp_path / ".a2l" / "VERSION", "0\n")
    calls = 0

    def migrate(vault: Vault) -> None:
        nonlocal calls
        calls += 1
        manifest_path = vault.state() / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["entries"][KEY]["path"] = "T/C/migrated.pdf"
        paths.atomic_write_text(
            manifest_path,
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
        )

    monkeypatch.setitem(MIGRATIONS, 0, migrate)

    assert Vault(tmp_path).manifest()[KEY].path == "T/C/migrated.pdf"
    assert calls == 1
    assert (tmp_path / ".a2l" / "VERSION").read_text(encoding="utf-8") == "1\n"

    assert Vault(tmp_path).manifest()[KEY].path == "T/C/migrated.pdf"
    assert calls == 1


def test_failed_schema_migration_preserves_original_version_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_manifest(tmp_path, {KEY: _entry().__dict__})
    manifest_path = tmp_path / ".a2l" / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    paths.atomic_write_text(tmp_path / ".a2l" / "VERSION", "0\n")

    def fail_after_writing_manifest(vault: Vault) -> None:
        payload = json.loads(vault.state().joinpath("manifest.json").read_text(encoding="utf-8"))
        payload["entries"][KEY]["path"] = "T/C/half-migrated.pdf"
        paths.atomic_write_text(
            vault.state() / "manifest.json",
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
        )
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setitem(MIGRATIONS, 0, fail_after_writing_manifest)

    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        Vault(tmp_path).manifest()

    assert (tmp_path / ".a2l" / "VERSION").read_text(encoding="utf-8") == "0\n"
    assert manifest_path.read_bytes() == original_manifest


def test_schema_migration_stages_under_the_long_path_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_manifest(tmp_path, {KEY: _entry().__dict__})
    state = tmp_path / ".a2l"
    paths.atomic_write_text(state / "VERSION", "0\n")
    extended_parent = tmp_path / "extended-parent"
    extended_parent.mkdir()
    real_mkdtemp = vault_module.tempfile.mkdtemp
    staging_dirs: list[str | None] = []

    def fake_long_path(path: Path) -> Path:
        return extended_parent if path == state.parent else path

    def capture_mkdtemp(*, prefix: str, dir: str | None = None) -> str:
        staging_dirs.append(dir)
        return real_mkdtemp(prefix=prefix, dir=dir)

    monkeypatch.setattr(paths, "long_path", fake_long_path)
    monkeypatch.setattr(vault_module.tempfile, "mkdtemp", capture_mkdtemp)
    monkeypatch.setitem(MIGRATIONS, 0, lambda _vault: None)

    check_schema(Vault(tmp_path))

    assert staging_dirs == [os.fspath(extended_parent)]


@pytest.mark.skipif(os.name == "nt", reason="directory symlinks require Windows privileges")
def test_schema_backup_does_not_follow_a_dangling_backup_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_manifest(tmp_path, {KEY: _entry().__dict__})
    state = tmp_path / ".a2l"
    paths.atomic_write_text(state / "VERSION", "0\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".a2l-backup-v0").symlink_to(outside, target_is_directory=True)
    monkeypatch.setitem(MIGRATIONS, 0, lambda _vault: None)

    check_schema(Vault(tmp_path))

    assert not (outside / "VERSION").exists()
    assert (tmp_path / ".a2l-backup-v0").is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="directory symlinks require Windows privileges")
def test_vault_refuses_a_symlinked_state_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside-state"
    outside.mkdir()
    (tmp_path / ".a2l").symlink_to(outside, target_is_directory=True)

    assert Vault.is_vault(tmp_path) is False
    with pytest.raises(A2LError, match="symlink"):
        check_schema(Vault(tmp_path))
    assert not (outside / "VERSION").exists()


def test_remove_state_path_uses_long_path_for_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state" / "obsolete.json"
    target.parent.mkdir()
    target.write_bytes(b"obsolete")
    extended = tmp_path / "extended" / "obsolete.json"
    calls: list[str] = []

    monkeypatch.setattr(paths, "long_path", lambda path: extended)
    monkeypatch.setattr(vault_module.os, "unlink", lambda raw: calls.append(raw))

    vault_module._remove_state_path(target)

    assert calls == [os.fspath(extended)]


def test_claim_refuses_when_git_status_cannot_be_established(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "other-project"
    (worktree / ".git").mkdir(parents=True)

    def unavailable(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(vault_module.subprocess, "run", unavailable)

    with pytest.raises(A2LError, match="Git"):
        Vault.claim(worktree / "vault")

    assert not (worktree / "vault").exists()


def test_semesters_and_vault_markers_are_conservative(tmp_path: Path) -> None:
    first = tmp_path / "Spring 2026"
    second = tmp_path / "Winter 2026"
    first.mkdir()
    second.mkdir()
    (first / "_SEMESTER_METADATA.json").write_text("{}\n", encoding="utf-8")
    (second / "_SEMESTER_METADATA.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "not-a-semester").mkdir()

    assert Vault.is_vault(tmp_path) is False
    assert Vault.is_vault(first) is True
    assert Vault.is_vault(tmp_path / "not-a-semester") is False
    assert Vault(tmp_path).semesters() == [first, second]

    (tmp_path / ".a2l").mkdir()
    assert Vault.is_vault(tmp_path) is True


def test_claim_does_not_adopt_a_foreign_directory_and_writes_narrow_ignore_file(
    tmp_path: Path,
) -> None:
    occupied = tmp_path / "agent2learn"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("mine", encoding="utf-8")

    claimed = Vault.claim(occupied)

    assert claimed.name == "agent2learn-2"
    assert Vault.is_vault(claimed)
    assert (claimed / ".gitignore").read_text(encoding="utf-8") == (
        ".a2l/\n**/_meta/my_grades.json\n**/discussions/\n**/.a2l/submissions/\n"
    )
    assert (occupied / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_claim_refuses_source_checkout_descendants(tmp_path: Path) -> None:
    del tmp_path
    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(A2LError, match="source checkout"):
        Vault.claim(repository_root / "test-vault-that-must-not-be-created")


def test_claim_requires_tty_for_an_unrelated_git_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "other-project"
    worktree.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(worktree)],
        check=True,
        capture_output=True,
    )
    selected = worktree / "vault"

    class _NotTTY:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _NotTTY())
    with pytest.raises(A2LError, match="TTY"):
        Vault.claim(selected)
    assert not selected.exists()


def test_claim_accepts_explicit_tty_confirmation_for_unrelated_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "other-project"
    worktree.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(worktree)],
        check=True,
        capture_output=True,
    )
    selected = worktree / "vault"

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt: "I UNDERSTAND THIS VAULT IS IN A GIT WORKTREE",
    )

    assert Vault.claim(selected) == selected
    assert Vault.is_vault(selected)
