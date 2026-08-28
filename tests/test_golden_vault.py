"""The cross-platform tripwire: one full pipeline run, hashed file by file.

Every other test asserts something a human decided to check. This one asserts that the
*entire* vault — every filename and every byte — is identical on Windows, macOS, and Linux.
It is the only test that can catch a defect nobody thought to look for: a path separator in
a Markdown link, a CRLF in a generated twin, a locale-dependent sort, an unsorted ``rglob``,
a normalization difference in a filename.

**Never regenerate ``golden_vault.json`` to make an unexplained diff go green.** A changed
hash means either the output genuinely changed for a reason you can state, or a regression
just got caught. Regenerating without an explanation converts the second case into silence,
which defeats the only test in the repository that is watching for the unknown.

To regenerate deliberately, after explaining the diff:

    A2L_REGENERATE_GOLDEN=1 uv run pytest tests/test_golden_vault.py

then re-run on all three operating systems and confirm the committed map matches everywhere.
"""

from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

import golden_support
import pytest
from golden_support import frozen_clock, hash_tree, run_full_pipeline  # noqa: F401

GOLDEN = Path(__file__).parent / "fixtures" / "golden_vault.json"


def _write_golden(tree: dict[str, str]) -> None:
    GOLDEN.write_text(
        json.dumps(tree, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_golden_harness_delegates_to_production_pipeline(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_pipeline(*args: object, **_kwargs: object) -> object:
        calls.append(args)
        return object()

    monkeypatch.setattr(golden_support, "run_pipeline", fake_pipeline, raising=False)

    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)  # type: ignore[attr-defined]

    assert vault.root == (tmp_path / "vault").resolve()
    assert len(calls) == 1
    assert calls[0][1] is vault


def test_vault_is_byte_identical_across_platforms(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)  # type: ignore[attr-defined]
    actual = hash_tree(vault.root)

    if os.environ.get("A2L_REGENERATE_GOLDEN") == "1":
        _write_golden(actual)
        pytest.skip("regenerated golden_vault.json; re-run on all three platforms to confirm")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    # Compare the path sets first: a naming defect is more legible as a missing or extra
    # key than as a wall of differing digests.
    assert sorted(actual) == sorted(expected), (
        "vault file set differs from the golden tree\n"
        f"  only here:   {sorted(set(actual) - set(expected))}\n"
        f"  only golden: {sorted(set(expected) - set(actual))}"
    )
    differing = {path for path, digest in actual.items() if expected[path] != digest}
    assert not differing, f"bytes differ from the golden tree for: {sorted(differing)}"


def test_two_runs_in_different_directories_agree(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    """Determinism within one platform, which must hold before parity across three can."""
    first = hash_tree(
        run_full_pipeline(tmp_path / "one", synthetic_api.base_url, monkeypatch).root  # type: ignore[attr-defined]
    )
    second = hash_tree(
        run_full_pipeline(tmp_path / "two", synthetic_api.base_url, monkeypatch).root  # type: ignore[attr-defined]
    )

    assert first == second


def test_golden_tree_covers_every_adversarial_case(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    """The golden map is only as good as what it contains, so pin the hazards explicitly.

    Without this, a future fixture edit could quietly drop the reserved device name or the
    case-collision pair and the golden test would keep passing against a weaker corpus.
    """
    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)  # type: ignore[attr-defined]
    tree = hash_tree(vault.root)
    names = sorted(tree)
    components = {part for path in names for part in path.split("/")}

    # A reserved Windows device name became a directory and was repaired.
    assert "CON_" in components, "reserved device-name module missing from the tree"
    assert "CON" not in components

    # A trailing dot never survives as the final character of a path component.
    assert not [part for part in components if part.endswith(".")]

    # The case-only collision pair produced two distinct files.
    lowered = [name.casefold() for name in names]
    assert len(lowered) == len(set(lowered)), "a case-only collision survived into the tree"
    assert any("lab notes_2" in name for name in lowered), "collision suffix missing"

    # Every component is NFC and within the 60-character budget.
    for part in components:
        assert unicodedata.normalize("NFC", part) == part, f"{part!r} is not NFC"
        assert len(part) <= 60, f"{part!r} exceeds the universal 60-character budget"

    # The NFD-titled topic landed, normalized.
    assert any("Café" in name for name in names), "NFD-titled topic missing from the tree"

    # Licensed and LTI targets are stubs, never downloaded bodies.
    assert any(name.endswith("Publisher eText.url.txt") for name in names)
    assert any(name.endswith("External Tool.url.txt") for name in names)
    assert not [name for name in names if name.endswith(("Publisher eText.pdf", "External Tool"))]

    # A topic of unknown length stays metadata-only rather than being fetched blind.
    assert not [name for name in names if "Unsized Handout" in name]

    # Converted twins exist for each supported source format.
    for twin in ("Lecture Slides.md", "Notebook.md", "R Notes.md", "Site Archive.md"):
        assert any(name.endswith(twin) for name in names), f"missing twin {twin}"

    # The vault carries its own state, and the audit is part of the reproducible output.
    for state_file in (".a2l/manifest.json", ".a2l/VERSION", ".a2l/AUDIT.md"):
        assert state_file in tree, f"missing {state_file}"


def test_generated_text_uses_lf_and_utf8_everywhere(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    """A single CRLF would change a digest on Windows and nowhere else."""
    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)  # type: ignore[attr-defined]

    for path in sorted(vault.root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in {".md", ".json", ".txt"}:
            continue
        raw = path.read_bytes()
        assert b"\r\n" not in raw, f"{path.name} contains CRLF"
        raw.decode("utf-8")


def test_markdown_links_never_contain_a_backslash(
    tmp_path: Path,
    synthetic_api: object,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,  # noqa: F811
) -> None:
    """A Windows separator inside a link silently breaks every citation on that platform."""
    vault = run_full_pipeline(tmp_path / "vault", synthetic_api.base_url, monkeypatch)  # type: ignore[attr-defined]

    for path in sorted(vault.root.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "](" in line:
                target = line.split("](", 1)[1].split(")", 1)[0]
                assert "\\" not in target, f"{path.name}:{number} link uses a backslash: {target}"
