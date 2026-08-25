"""Cross-platform path naming and durable atomic filesystem primitives.

All vault component naming, collision allocation, and state-file replacement lives here.
Callers keep ordinary ``Path`` objects; ``long_path`` is applied only at the syscall
boundary because Windows' ``\\?\\`` paths are not safe to join or compare with pathlib.
"""

from __future__ import annotations

import errno
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

WINDOWS = sys.platform == "win32"
DEFAULT_MAXLEN = 60

RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{digit}" for digit in "123456789"}
    | {f"COM{digit}" for digit in "¹²³"}
    | {f"LPT{digit}" for digit in "123456789"}
    | {f"LPT{digit}" for digit in "¹²³"}
)

_RESERVED_CASEFOLD = frozenset(name.casefold() for name in RESERVED)
_RESERVED_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
_WHITESPACE = re.compile(r"\s+")
_SIMPLE_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,15}$")
_WINDOWS_EXTENDED_PREFIX = "\\\\?\\"
_WINDOWS_UNC_PREFIX = "\\\\?\\UNC\\"
_UNSUPPORTED_DIRECTORY_FSYNC = frozenset(
    {errno.EBADF, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
)


def safe_name(name: str, *, maxlen: int | None = None) -> str:
    """Return a deterministic, Windows-safe filename component.

    The operation order is part of the vault contract: normalize, sanitize, collapse
    whitespace, trim, truncate, then repair a reserved device name. The same rules run on
    every platform so a vault has identical names after moving between operating systems.
    """
    budget = DEFAULT_MAXLEN if maxlen is None else _positive_budget(maxlen)
    value = unicodedata.normalize("NFC", name)
    value = _RESERVED_CHARACTERS.sub("_", value)
    value = "".join("_" if unicodedata.category(char) == "Cc" else char for char in value)
    value = _WHITESPACE.sub(" ", value).rstrip(" .")
    if not value:
        value = "untitled"

    value = _truncate_component(value, budget)
    value = value.rstrip(" .") or "untitled"
    if len(value) > budget:
        value = value[:budget].rstrip(" .") or "untitled"[:budget]

    return _repair_reserved_name(value, budget)


def long_path(path: Path) -> Path:
    """Return a Windows extended-length path when the resolved path needs one."""
    if not WINDOWS:
        return path

    raw = os.fspath(path)
    if raw.startswith(_WINDOWS_EXTENDED_PREFIX):
        return path

    resolved = path.resolve()
    resolved_raw = os.fspath(resolved)
    if resolved_raw.startswith(_WINDOWS_EXTENDED_PREFIX):
        return resolved
    if len(resolved_raw) <= 240:
        return path
    if resolved_raw.startswith(r"\\"):
        return Path(_WINDOWS_UNC_PREFIX + resolved_raw[2:])
    return Path(_WINDOWS_EXTENDED_PREFIX + resolved_raw)


def collides(destination: Path) -> bool:
    """Return whether a normalized, case-folded sibling already has this name."""
    try:
        entries = tuple(destination.parent.iterdir())
    except FileNotFoundError:
        return False

    wanted = _canonical_component(destination.name)
    return any(_canonical_component(entry.name) == wanted for entry in entries)


def unique_path(destination: Path) -> Path:
    """Return ``destination`` or the next available ``_2``/``_3`` sibling."""
    candidate_name = _truncate_component(destination.name, DEFAULT_MAXLEN).rstrip(" .")
    if not candidate_name:
        candidate_name = "untitled"
    candidate = destination.with_name(candidate_name)
    if not collides(candidate):
        return candidate

    stem, extension = _split_extension(candidate.name)
    for number in range(2, 100_000):
        suffix = f"_{number}"
        available_stem_length = DEFAULT_MAXLEN - len(extension) - len(suffix)
        if available_stem_length < 1:
            raise ValueError("filename budget cannot fit a collision suffix")
        candidate_name = f"{stem[:available_stem_length]}{suffix}{extension}"
        candidate = destination.with_name(candidate_name)
        if not collides(candidate):
            return candidate
    raise RuntimeError("could not allocate a unique path")


def reveal(path: Path) -> None:
    """Ask the platform file manager to reveal a path, swallowing launcher failures."""
    try:
        if WINDOWS:
            command = ["explorer", os.fspath(long_path(path))]
        elif sys.platform == "darwin":
            command = ["open", os.fspath(long_path(path))]
        else:
            command = ["xdg-open", os.fspath(long_path(path))]
        subprocess.Popen(command)  # noqa: S603 - fixed executable, no shell
    except OSError:
        return


def atomic_write_text(destination: Path, text: str, *, retries: int = 5) -> None:
    """Write UTF-8 LF text and atomically install it at ``destination``."""
    _validate_retries(retries)
    temporary = _create_temporary(destination, suffix=".tmp")
    try:
        with open(os.fspath(long_path(temporary)), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _tighten_permissions(temporary)
        _replace_with_retries(temporary, destination, retries)
    finally:
        _remove_quietly(temporary)


def atomic_write_bytes(destination: Path, data: bytes, *, retries: int = 5) -> None:
    """Write exact bytes and atomically install them at ``destination``."""
    _validate_retries(retries)
    temporary = _create_temporary(destination, suffix=".tmp")
    try:
        with open(os.fspath(long_path(temporary)), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _tighten_permissions(temporary)
        _replace_with_retries(temporary, destination, retries)
    finally:
        _remove_quietly(temporary)


def atomic_install_temp(destination: Path, temporary: Path, *, retries: int = 5) -> None:
    """Fsync and atomically install a validated sibling download ``.part`` file."""
    _validate_retries(retries)
    _validate_part_file(destination, temporary)
    try:
        _fsync_file(temporary)
        _tighten_permissions(temporary)
        _replace_with_retries(temporary, destination, retries)
    finally:
        _remove_quietly(temporary)


def rel_posix(path: Path, root: Path) -> str:
    """Return a non-escaping vault-relative path using forward slashes."""
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("path is not relative to root") from exc
    return relative.as_posix()


def _positive_budget(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("maxlen must be a positive integer")
    return value


def _truncate_component(value: str, budget: int) -> str:
    match = _SIMPLE_EXTENSION.search(value)
    if match is None:
        return value[:budget]

    extension = match.group(0)
    stem = value[: -len(extension)]
    if stem and budget > len(extension):
        return stem[: budget - len(extension)] + extension
    return value[:budget]


def _repair_reserved_name(value: str, budget: int) -> str:
    reserved_stem = value.split(".", 1)[0]
    if reserved_stem.casefold() not in _RESERVED_CASEFOLD:
        return value[:budget]

    remainder = value[len(reserved_stem) :]
    if len(reserved_stem) >= budget:
        if budget == 1:
            return "_"
        return reserved_stem[: budget - 1] + "_"

    repaired = f"{reserved_stem}_{remainder[: budget - len(reserved_stem) - 1]}".rstrip(" .")
    if not repaired:
        return "untitled"[:budget]
    return repaired[:budget]


def _split_extension(name: str) -> tuple[str, str]:
    first_dot = name.find(".")
    if first_dot <= 0:
        return name, ""
    extension_match = _SIMPLE_EXTENSION.search(name)
    if extension_match is None:
        return name, ""
    return name[: -len(extension_match.group(0))], extension_match.group(0)


def _canonical_component(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _validate_retries(retries: int) -> None:
    if isinstance(retries, bool) or not isinstance(retries, int) or retries <= 0:
        raise ValueError("retries must be a positive integer")


def _create_temporary(destination: Path, *, suffix: str) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=suffix,
        dir=os.fspath(long_path(destination.parent)),
    )
    os.close(file_descriptor)
    return _plain_path(Path(raw_path))


def _plain_path(path: Path) -> Path:
    if not WINDOWS:
        return path
    raw = os.fspath(path)
    if raw.startswith(_WINDOWS_UNC_PREFIX):
        return Path("\\\\" + raw[len(_WINDOWS_UNC_PREFIX) :])
    if raw.startswith(_WINDOWS_EXTENDED_PREFIX):
        return Path(raw[4:])
    return path


def _tighten_permissions(path: Path) -> None:
    if not WINDOWS:
        os.chmod(os.fspath(long_path(path)), 0o600)


def _fsync_file(path: Path) -> None:
    with open(os.fspath(long_path(path)), "rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    if WINDOWS:
        return
    try:
        file_descriptor = os.open(os.fspath(long_path(directory)), os.O_RDONLY)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC:
            return
        raise
    try:
        try:
            os.fsync(file_descriptor)
        except OSError as exc:
            if exc.errno not in _UNSUPPORTED_DIRECTORY_FSYNC:
                raise
    finally:
        os.close(file_descriptor)


def _replace_with_retries(temporary: Path, destination: Path, retries: int) -> None:
    for attempt in range(retries):
        try:
            os.replace(
                os.fspath(long_path(temporary)),
                os.fspath(long_path(destination)),
            )
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(0.01 * (2**attempt))
        else:
            _fsync_directory(destination.parent)
            return


def _validate_part_file(destination: Path, temporary: Path) -> None:
    if temporary.parent.resolve() != destination.parent.resolve():
        raise ValueError("temporary file must be a sibling of destination")
    if not temporary.name.endswith(".part"):
        raise ValueError("temporary download must end with .part")
    if temporary.is_symlink():
        raise ValueError("temporary download must not be a symlink")
    file_stat = temporary.stat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("temporary download must be a regular file")


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(os.fspath(long_path(path)))
    except FileNotFoundError:
        return


__all__ = [
    "DEFAULT_MAXLEN",
    "RESERVED",
    "WINDOWS",
    "atomic_install_temp",
    "atomic_write_bytes",
    "atomic_write_text",
    "collides",
    "long_path",
    "rel_posix",
    "reveal",
    "safe_name",
    "unique_path",
]
