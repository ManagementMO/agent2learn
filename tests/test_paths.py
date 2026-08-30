"""Cross-platform filesystem naming and atomic-write contracts.

These tests deliberately exercise the public boundary rather than implementation details.
The same inputs must produce the same names on every supported operating system, and a
failed replacement must never damage an existing destination or leave temporary debris.
"""

from __future__ import annotations

import builtins
import os
import stat
import sys
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent2learn import paths


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
        ("tab\there", "tab_here"),
        ("bell\x07here", "bell_here"),
        ("del\x7fhere", "del_here"),
        ("c1\x85here", "c1_here"),
        ("Trailing dots...", "Trailing dots"),
        ("Trailing space   ", "Trailing space"),
        ("  ", "untitled"),
        (" CON", "CON_"),
        ("\xa0nbsp", "nbsp"),
        ("Week 1  Intro", "Week 1 Intro"),
        ("CON", "CON_"),
        ("nul.txt", "nul_.txt"),
        ("COM1", "COM1_"),
        ("LPT9.pdf", "LPT9_.pdf"),
        ("CONIN$", "CONIN$_"),
        ("CONOUT$", "CONOUT$_"),
        ("COM\u00b9", "COM\u00b9_"),
        ("LPT\u00b3.pdf", "LPT\u00b3_.pdf"),
        ("COM0", "COM0"),
        ("LPT0", "LPT0"),
        ("CONFIG", "CONFIG"),
        ("AUXILIARY", "AUXILIARY"),
    ],
)
def test_safe_name_applies_the_cross_platform_contract(raw: str, expected: str) -> None:
    assert paths.safe_name(raw) == expected


def test_reserved_device_set_is_exactly_the_documented_windows_set() -> None:
    expected = frozenset(
        {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        | {f"COM{digit}" for digit in "123456789"}
        | {f"COM{digit}" for digit in "¹²³"}
        | {f"LPT{digit}" for digit in "123456789"}
        | {f"LPT{digit}" for digit in "¹²³"}
    )

    assert expected == paths.RESERVED


@pytest.mark.skipif(os.name == "nt", reason="symlink creation may require elevation")
def test_root_bound_writers_refuse_linked_parent_components(tmp_path: Path) -> None:
    """Vault writers must fail closed instead of following a pre-existing symlink."""
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = root / "Winter 2026"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="link component"):
        paths.ensure_dir(linked / "COURSE101_1261", root=root)
    with pytest.raises(ValueError, match="link component"):
        paths.atomic_write_text(linked / "outside.json", "secret\n", root=root)

    assert not (outside / "COURSE101_1261").exists()
    assert not (outside / "outside.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink perturbation")
def test_root_bound_atomic_write_rechecks_a_temporary_parent_before_opening(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = root / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    fd, raw_holder = tempfile.mkstemp(dir=tmp_path)
    os.close(fd)
    holder = Path(raw_holder)
    monkeypatch.setattr(
        paths,
        "_create_temporary_file",
        lambda _destination, *, suffix: (linked / f"payload{suffix}", os.open(holder, os.O_RDWR)),
    )

    with pytest.raises(ValueError, match="link component"):
        paths.atomic_write_text(root / "safe" / "state.json", "secret\n", root=root)

    assert not (outside / "payload.tmp").exists()
    assert not (root / "safe" / "state.json").exists()
    holder.unlink()


def test_root_bound_tree_replacement_refuses_lexical_escape(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "sub").mkdir()
    parent = root / "sub" / ".."
    staged = parent / ".staged"
    staged.mkdir()

    with pytest.raises(ValueError, match="outside|trusted root"):
        paths.replace_tree(parent / "..", staged, root=root)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NUL.tar.gz", "NUL_.tar.gz"),
        ("con.PDF", "con_.PDF"),
        ("ConIn$.txt", "ConIn$_.txt"),
        ("lpt².doc", "lpt²_.doc"),
    ],
)
def test_safe_name_repairs_reserved_stems_before_multiple_extensions(
    raw: str, expected: str
) -> None:
    assert paths.safe_name(raw) == expected


def test_safe_name_collapses_unicode_whitespace() -> None:
    assert paths.safe_name("Week\u00a01\u2003Intro") == "Week 1 Intro"


def test_safe_name_replaces_invisible_unicode_format_characters() -> None:
    assert paths.safe_name("\u200bzwsp\u200d") == "_zwsp_"


def test_safe_name_normalizes_nfc_before_returning() -> None:
    nfd = "Cafe\u0301.pdf"
    nfc = "Caf\u00e9.pdf"

    assert paths.safe_name(nfd) == paths.safe_name(nfc) == unicodedata.normalize("NFC", nfc)


def test_safe_name_truncates_before_repairing_reserved_names() -> None:
    assert paths.safe_name("CONfiguration", maxlen=3) == "CO_"


def test_safe_name_preserves_a_simple_extension_within_the_budget() -> None:
    result = paths.safe_name("x" * 300 + ".pdf")

    assert len(result) == 60
    assert result.endswith(".pdf")


def test_safe_name_treats_an_extension_as_part_of_the_name_when_no_stem_fits() -> None:
    assert paths.safe_name("basename.pdf", maxlen=3) == "bas"


def test_safe_name_can_repair_a_reserved_name_at_the_smallest_budget() -> None:
    assert paths.safe_name("CON", maxlen=1) == "C"


@pytest.mark.parametrize("maxlen", [0, -1])
def test_safe_name_rejects_nonpositive_length_budgets(maxlen: int) -> None:
    with pytest.raises(ValueError, match="maxlen"):
        paths.safe_name("name", maxlen=maxlen)


def test_long_path_is_unchanged_off_windows(tmp_path: Path) -> None:
    if paths.WINDOWS:
        pytest.skip("the plain-path branch is not used on Windows")

    destination = tmp_path / ("x" * 250)

    assert paths.long_path(destination) == destination


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path-prefix behavior")
def test_long_path_prefixes_a_nonexistent_local_path(tmp_path: Path) -> None:
    destination = tmp_path / ("x" * 250)

    result = paths.long_path(destination)

    assert os.fspath(result).startswith("\\\\?\\")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path-prefix behavior")
def test_long_path_uses_the_unc_prefix_for_long_unc_paths() -> None:
    destination = Path(r"\\server\share") / ("x" * 250)

    assert os.fspath(paths.long_path(destination)).startswith("\\\\?\\UNC\\server\\share\\")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path-prefix behavior")
def test_long_path_does_not_rewrite_an_already_prefixed_path() -> None:
    destination = Path(r"\\?\C:\already\prefixed\path")

    assert paths.long_path(destination) == destination


def test_long_path_does_not_follow_a_symlink_to_measure_the_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path
    for index in range(8):
        target /= f"target-{index}-" + "x" * 30
        target.mkdir()
    link = tmp_path / "short-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(paths, "WINDOWS", True)

    assert paths.long_path(link) == link


def test_plain_path_strips_an_inherited_windows_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths, "WINDOWS", True)

    assert paths.plain_path(Path(r"\\?\C:\vault\.source.part")) == Path(r"C:\vault\.source.part")


def test_link_metadata_errors_are_not_treated_as_a_safe_regular_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "candidate"

    def fail_lstat(_path: str) -> os.stat_result:
        raise PermissionError("metadata unavailable")

    monkeypatch.setattr(paths.os, "lstat", fail_lstat)

    with pytest.raises(PermissionError, match="metadata unavailable"):
        paths.is_link(target)


@pytest.mark.skipif(os.name == "nt", reason="directory symlinks require Windows privileges")
def test_remove_tree_unlinks_a_directory_symlink_without_touching_its_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "outside-link").symlink_to(outside, target_is_directory=True)

    paths.remove_tree(root)

    assert not root.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_collides_is_case_insensitive_on_every_platform(tmp_path: Path) -> None:
    existing = tmp_path / "Lab1.pdf"
    existing.write_text("fixture", encoding="utf-8")

    assert paths.collides(tmp_path / "lab1.pdf")
    assert not paths.collides(tmp_path / "lab2.pdf")


def test_collides_compares_nfc_normalized_names(tmp_path: Path) -> None:
    existing = tmp_path / "Caf\u00e9.pdf"
    existing.write_text("fixture", encoding="utf-8")

    assert paths.collides(tmp_path / "Cafe\u0301.pdf")


def test_collides_treats_a_directory_as_a_collision(tmp_path: Path) -> None:
    (tmp_path / "module").mkdir()

    assert paths.collides(tmp_path / "MODULE")


def test_collides_returns_false_when_the_parent_does_not_exist(tmp_path: Path) -> None:
    assert not paths.collides(tmp_path / "missing" / "file.md")


def test_unique_path_adds_a_case_insensitive_suffix(tmp_path: Path) -> None:
    (tmp_path / "Lab1.pdf").write_text("fixture", encoding="utf-8")

    assert paths.unique_path(tmp_path / "lab1.pdf").name == "lab1_2.pdf"


def test_unique_path_skips_occupied_suffixes(tmp_path: Path) -> None:
    for name in ("report.pdf", "report_2.pdf", "report_3.pdf"):
        (tmp_path / name).write_text("fixture", encoding="utf-8")

    assert paths.unique_path(tmp_path / "report.pdf").name == "report_4.pdf"


def test_unique_path_accepts_a_missing_parent(tmp_path: Path) -> None:
    candidate = tmp_path / "missing" / "file.md"

    assert paths.unique_path(candidate) == candidate


def test_unique_path_adds_a_suffix_after_nfc_normalization(tmp_path: Path) -> None:
    (tmp_path / "Caf\u00e9.pdf").write_text("fixture", encoding="utf-8")

    candidate = tmp_path / paths.safe_name("Cafe\u0301.pdf")
    assert paths.unique_path(candidate).name == "Caf\u00e9_2.pdf"


def test_unique_path_keeps_collision_suffixes_within_the_component_budget(tmp_path: Path) -> None:
    first = "x" * 56 + ".pdf"
    (tmp_path / first).write_text("fixture", encoding="utf-8")

    result = paths.unique_path(tmp_path / first)

    assert len(result.name) <= 60
    assert result.name.endswith(".pdf")


def test_rel_posix_uses_forward_slashes(tmp_path: Path) -> None:
    destination = tmp_path / "a" / "b" / "c.md"

    assert paths.rel_posix(destination, tmp_path) == "a/b/c.md"


def test_rel_posix_rejects_a_path_outside_the_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relative"):
        paths.rel_posix(tmp_path.parent / "outside.md", tmp_path)


def test_reveal_never_raises_when_the_platform_launcher_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_to_launch(*args: object, **kwargs: object) -> None:
        raise OSError("launcher unavailable")

    monkeypatch.setattr(paths.subprocess, "Popen", fail_to_launch)

    paths.reveal(tmp_path)


def _assert_no_temporary_files(directory: Path) -> None:
    assert not list(directory.glob("*.tmp"))
    assert not list(directory.glob("*.part"))


def test_atomic_write_text_writes_utf8_and_retries_transient_replacement_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "manifest.json"
    real_replace = paths.os.replace
    calls = 0

    def flaky_replace(
        source: str | bytes | os.PathLike[str], target: str | bytes | os.PathLike[str]
    ) -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError(5, "Access is denied")
        real_replace(source, target)

    monkeypatch.setattr(paths.os, "replace", flaky_replace)
    monkeypatch.setattr(paths.time, "sleep", lambda _seconds: None)

    paths.atomic_write_text(destination, "Café\nline\n")

    assert calls == 3
    assert destination.read_text(encoding="utf-8") == "Café\nline\n"
    _assert_no_temporary_files(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not portable to Windows")
def test_atomic_write_text_tightens_destination_permissions(tmp_path: Path) -> None:
    destination = tmp_path / "session.json"

    paths.atomic_write_text(destination, "{}")

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_atomic_write_bytes_installs_exact_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "source.bin"
    payload = b"\x00\xff\x10\n"

    paths.atomic_write_bytes(destination, payload)

    assert destination.read_bytes() == payload
    _assert_no_temporary_files(tmp_path)


def test_atomic_write_preserves_an_existing_destination_after_exhausted_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "manifest.json"
    destination.write_text("old", encoding="utf-8")

    def always_fail(*args: object, **kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(paths.os, "replace", always_fail)
    monkeypatch.setattr(paths.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        paths.atomic_write_text(destination, "new", retries=3)

    assert destination.read_text(encoding="utf-8") == "old"
    _assert_no_temporary_files(tmp_path)


def test_atomic_write_does_not_retry_unrelated_replacement_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "manifest.json"
    calls = 0

    def fail_with_io_error(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise OSError("different filesystem failure")

    monkeypatch.setattr(paths.os, "replace", fail_with_io_error)

    with pytest.raises(OSError, match="different filesystem"):
        paths.atomic_write_text(destination, "new")

    assert calls == 1
    assert not destination.exists()
    _assert_no_temporary_files(tmp_path)


@pytest.mark.parametrize("retries", [0, -1])
def test_atomic_write_rejects_nonpositive_retry_counts(tmp_path: Path, retries: int) -> None:
    with pytest.raises(ValueError, match="retries"):
        paths.atomic_write_text(tmp_path / "manifest.json", "{}", retries=retries)


def test_atomic_install_temp_requires_a_sibling_part_file(tmp_path: Path) -> None:
    destination = tmp_path / "source.pdf"
    part = tmp_path / "source.pdf.part"
    part.write_bytes(b"downloaded")

    paths.atomic_install_temp(destination, part)

    assert destination.read_bytes() == b"downloaded"
    assert not part.exists()
    _assert_no_temporary_files(tmp_path)


def test_failed_install_preserves_the_downloaded_part_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "source.pdf"
    part = tmp_path / "source.pdf.part"
    original_bytes = b"downloaded and validated"
    part.write_bytes(original_bytes)

    def always_fail(*args: object, **kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(paths.os, "replace", always_fail)
    monkeypatch.setattr(paths.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        paths.atomic_install_temp(destination, part, retries=2)

    assert part.read_bytes() == original_bytes
    assert not destination.exists()


def test_atomic_write_cleanup_failure_does_not_mask_the_primary_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "manifest.json"

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("primary replacement failure")

    def fail_cleanup(*args: object, **kwargs: object) -> None:
        raise PermissionError("secondary cleanup failure")

    monkeypatch.setattr(paths.os, "replace", fail_replace)
    monkeypatch.setattr(paths.os, "unlink", fail_cleanup)

    with pytest.raises(OSError, match="primary replacement failure"):
        paths.atomic_write_text(destination, "new")


def test_fsync_file_uses_a_windows_compatible_handle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.part"
    source.write_bytes(b"downloaded")
    opened_modes: list[str] = []
    real_open = builtins.open

    def recording_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ) -> object:
        opened_modes.append(mode)
        del args, kwargs
        return real_open(file, mode)

    monkeypatch.setattr(builtins, "open", recording_open)
    paths._fsync_file(source)

    assert opened_modes == ["r+b" if paths.WINDOWS else "rb"]


def test_atomic_install_temp_rejects_a_non_part_source(tmp_path: Path) -> None:
    destination = tmp_path / "source.pdf"
    source = tmp_path / "source.download"
    source.write_bytes(b"downloaded")

    with pytest.raises(ValueError, match="part"):
        paths.atomic_install_temp(destination, source)


def test_atomic_install_temp_rejects_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        paths.atomic_install_temp(tmp_path / "source.pdf", tmp_path / "source.pdf.part")


def test_atomic_install_temp_rejects_a_part_file_from_another_directory(tmp_path: Path) -> None:
    destination = tmp_path / "source.pdf"
    other = tmp_path / "other"
    other.mkdir()
    part = other / "source.pdf.part"
    part.write_bytes(b"downloaded")

    with pytest.raises(ValueError, match="sibling"):
        paths.atomic_install_temp(destination, part)


def test_atomic_writes_use_unique_temporary_names_for_concurrent_writers(tmp_path: Path) -> None:
    destination = tmp_path / "manifest.json"

    def write_value(value: int) -> None:
        paths.atomic_write_text(destination, f"value-{value}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_value, range(4)))

    assert destination.read_text(encoding="utf-8").startswith("value-")
    _assert_no_temporary_files(tmp_path)
