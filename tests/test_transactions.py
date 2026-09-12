from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from agent2learn import paths, transactions
from agent2learn.errors import A2LError
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

KEY = "uwaterloo:101:topic:1"
STAMP = "2026-08-25T12:00:00Z"


def _entry(source: bytes, markdown: bytes) -> ManifestEntry:
    digest = sha256(source).hexdigest()
    return ManifestEntry(
        path="Term/COURSE101/content/outline.html",
        sha256=digest,
        source_id="1",
        etag=None,
        last_modified=None,
        size=len(source),
        fetched_at=STAMP,
        derived={
            "markdown": DerivedArtifact(
                path="Term/COURSE101/content/outline.md",
                sha256=sha256(markdown).hexdigest(),
                source_sha256=digest,
                tool="outline-renderer",
                tool_version="1",
                created_at=STAMP,
            )
        },
    )


@pytest.fixture
def interrupted_generated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Vault, ManifestEntry, ManifestEntry]:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    before = _entry(b"first source", b"first markdown")
    transactions.install_generated(
        vault, KEY, before, b"first source", {"markdown": b"first markdown"}, preserve=False
    )
    after = _entry(b"second source", b"second markdown")
    install = paths.atomic_install_temp

    def fail_markdown(destination: Path, temporary: Path, *, root: Path | None = None) -> None:
        if destination == vault.root / before.derived["markdown"].path:
            raise OSError("synthetic second-file failure")
        install(destination, temporary, root=root)

    with monkeypatch.context() as fault:
        fault.setattr(paths, "atomic_install_temp", fail_markdown)
        with pytest.raises(OSError, match="second-file"):
            transactions.install_generated(
                vault, KEY, after, b"second source", {"markdown": b"second markdown"}, preserve=True
            )
    assert vault.materialized(before).read_bytes() == b"second source"
    assert (vault.root / before.derived["markdown"].path).read_bytes() == b"first markdown"
    assert Vault(vault.root).entry(KEY) == before
    return vault, before, after


def test_partial_generated_install_recovers_as_one_verified_revision(
    interrupted_generated: tuple[Vault, ManifestEntry, ManifestEntry],
) -> None:
    vault, before, after = interrupted_generated
    restarted = Vault(vault.root)

    transactions.recover_generated(restarted, KEY)

    assert restarted.entry(KEY) == after
    assert restarted.materialized(after).read_bytes() == b"second source"
    assert (restarted.root / after.derived["markdown"].path).read_bytes() == b"second markdown"
    assert not list((vault.state() / "pending-generated").glob("*/entry.json"))
    assert any(
        path.read_bytes() == b"first source"
        for path in restarted.history_bucket(KEY).rglob("*.html")
    )


def test_recovery_preserves_student_edits_made_after_interruption(
    interrupted_generated: tuple[Vault, ManifestEntry, ManifestEntry],
) -> None:
    vault, before, _after = interrupted_generated
    markdown = vault.root / before.derived["markdown"].path
    markdown.write_bytes(b"Student changes after the crash")

    with pytest.raises(A2LError, match="locally modified"):
        transactions.recover_generated(Vault(vault.root), KEY)

    assert markdown.read_bytes() == b"Student changes after the crash"
    assert Vault(vault.root).entry(KEY) == before


def test_corrupt_staged_generated_bytes_cannot_be_committed(
    interrupted_generated: tuple[Vault, ManifestEntry, ManifestEntry],
) -> None:
    vault, before, _after = interrupted_generated
    staged = next((vault.state() / "pending-generated").glob("*/1.part"))
    staged.write_bytes(b"corrupt staged content")

    with pytest.raises(A2LError, match="integrity"):
        transactions.recover_generated(Vault(vault.root), KEY)

    assert Vault(vault.root).entry(KEY) == before
    assert (vault.root / before.derived["markdown"].path).read_bytes() == b"first markdown"
