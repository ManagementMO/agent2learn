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
from collections.abc import Iterator
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
    whitespace, trim leading/trailing whitespace, truncate, then repair a reserved device
    name. The same rules run on every platform so a vault has identical names after moving
    between operating systems.
    """
    budget = DEFAULT_MAXLEN if maxlen is None else _positive_budget(maxlen)
    value = unicodedata.normalize("NFC", name)
    value = _RESERVED_CHARACTERS.sub("_", value)
    value = "".join("_" if unicodedata.category(char) in {"Cc", "Cf"} else char for char in value)
    value = _WHITESPACE.sub(" ", value).lstrip().rstrip(" .")
    if not value:
        value = "untitled"

    value = _truncate_component(value, budget)
    value = value.rstrip(" .") or "untitled"
    if len(value) > budget:
        value = value[:budget].rstrip(" .") or "untitled"[:budget]

    return _repair_reserved_name(value, budget)


def long_path(path: Path) -> Path:
    """Return a Windows extended-length path without following symlinks.

    ``resolve()`` is deliberately not used here.  It follows a symlink before the caller
    reaches the syscall, which can turn a safe identity check or an atomic replacement into an
    operation on the symlink target.  ``abspath`` normalizes the lexical path and preserves the
    final component as the object the caller actually named.
    """
    if not WINDOWS:
        return path

    raw = os.fspath(path)
    if raw.startswith(_WINDOWS_EXTENDED_PREFIX):
        return path

    absolute_raw = os.path.abspath(raw)
    if absolute_raw.startswith(_WINDOWS_EXTENDED_PREFIX):
        return Path(absolute_raw)
    if len(absolute_raw) <= 240:
        return path
    if absolute_raw.startswith(r"\\"):
        return Path(_WINDOWS_UNC_PREFIX + absolute_raw[2:])
    return Path(_WINDOWS_EXTENDED_PREFIX + absolute_raw)


def is_link(path: Path) -> bool:
    """Return whether ``path`` is a symlink or Windows reparse-point link."""
    candidate = long_path(path)
    try:
        if candidate.is_symlink():
            return True
        file_stat = os.lstat(os.fspath(candidate))
    except FileNotFoundError:
        return False
    return bool(getattr(file_stat, "st_file_attributes", 0) & 0x400)


def collides(destination: Path) -> bool:
    """Return whether a normalized, case-folded sibling already has this name."""
    try:
        with os.scandir(os.fspath(long_path(destination.parent))) as iterator:
            entries = tuple(entry.name for entry in iterator)
    except FileNotFoundError:
        return False

    wanted = _canonical_component(destination.name)
    return any(_canonical_component(entry) == wanted for entry in entries)


def walk(root: Path) -> Iterator[Path]:
    """Yield ordinary paths from a tree while applying ``long_path`` at each scan boundary."""

    def visit(directory: Path) -> Iterator[Path]:
        with os.scandir(os.fspath(long_path(directory))) as iterator:
            for entry in iterator:
                child = directory / entry.name
                yield child
                if not is_link(child) and entry.is_dir(follow_symlinks=False):
                    yield from visit(child)

    yield from visit(root)


def remove_tree(root: Path, *, ignore_errors: bool = False) -> None:
    """Remove a tree while applying ``long_path`` to each filesystem operation."""
    try:
        if is_link(root):
            _remove_link(root)
            return
        if not long_path(root).is_dir():
            os.unlink(os.fspath(long_path(root)))
            return
        candidates = list(walk(root))
        for candidate in sorted(
            candidates,
            key=lambda value: len(value.relative_to(root).parts),
            reverse=True,
        ):
            if is_link(candidate):
                _remove_link(candidate)
            elif not long_path(candidate).is_dir():
                os.unlink(os.fspath(long_path(candidate)))
            else:
                os.rmdir(os.fspath(long_path(candidate)))
        os.rmdir(os.fspath(long_path(root)))
    except OSError:
        if not ignore_errors:
            raise


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


def ensure_dir(directory: Path) -> None:
    """Create a directory tree at a syscall boundary."""

    long_path(directory).mkdir(parents=True, exist_ok=True)


def temporary_directory(parent: Path, *, prefix: str) -> Path:
    """Create a sibling temporary directory at a syscall boundary."""

    ensure_dir(parent)
    raw_path = tempfile.mkdtemp(prefix=prefix, dir=os.fspath(long_path(parent)))
    return plain_path(Path(raw_path))


def has_link_component(path: Path, *, root: Path | None = None) -> bool:
    """Return whether ``path`` has a link component inside the trusted root."""

    absolute_path = Path(os.path.abspath(os.fspath(path)))
    if root is None:
        parts = absolute_path.parts
        if not parts:
            return False
        trusted_root = Path(parts[0])
        relative_parts = parts[1:]
    else:
        trusted_root = Path(os.path.abspath(os.fspath(root)))
        try:
            relative_parts = absolute_path.relative_to(trusted_root).parts
        except ValueError:
            return True

    candidate = trusted_root
    if is_link(candidate):
        return True
    for part in relative_parts:
        if not long_path(candidate).exists():
            return False
        candidate = candidate / part
        if is_link(candidate):
            return True
    return False


def symlink_dir(source: Path, destination: Path) -> None:
    """Create an opt-in directory symlink at a syscall boundary."""

    ensure_dir(destination.parent)
    os.symlink(
        os.fspath(long_path(source)),
        os.fspath(long_path(destination)),
        target_is_directory=True,
    )
    _fsync_directory(destination.parent)


def replace_link(
    destination: Path,
    source: Path,
    *,
    root: Path | None = None,
    retries: int = 5,
) -> None:
    """Atomically install a directory link while retaining the old object on failure.

    A directory cannot be replaced in place by ``os.replace`` on every supported platform.
    The old object is therefore moved to a sibling backup before the staged link is installed;
    a failed install rolls that backup back into place. ``source`` is trusted by the caller and
    must be an ordinary directory, while ``root`` protects the destination parent.
    """

    _validate_retries(retries)
    if not long_path(source).is_dir() or is_link(source):
        raise ValueError("link source must be an ordinary directory")
    if root is not None and has_link_component(destination.parent, root=root):
        raise ValueError("link destination path contains a link component")

    temporary = _create_temporary_link(destination, source)
    try:
        backup = _backup_path(destination)
        had_destination = long_path(destination).exists() or is_link(destination)
        if had_destination:
            _replace_with_retries(destination, backup, retries)
        try:
            _replace_with_retries(temporary, destination, retries)
        except OSError:
            if had_destination and not (long_path(destination).exists() or is_link(destination)):
                _replace_with_retries(backup, destination, retries)
            raise
        if had_destination:
            remove_tree(backup, ignore_errors=True)
    finally:
        _remove_quietly(temporary)


def atomic_write_text(destination: Path, text: str, *, retries: int = 5) -> None:
    """Write UTF-8 LF text and atomically install it at ``destination``."""
    _validate_retries(retries)
    temporary = _create_temporary(destination, suffix=".tmp")
    # This temporary contains content generated by this call and is cheap to recreate;
    # unlike atomic_install_temp, it is correct to remove it when installation fails.
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
    # This temporary contains content generated by this call and is cheap to recreate;
    # unlike atomic_install_temp, it is correct to remove it when installation fails.
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
    # This .part is a completed download, so retain it when fsync or installation fails;
    # the next sync can retry the expensive download instead of fetching it again.
    _fsync_file(temporary)
    _tighten_permissions(temporary)
    _replace_with_retries(temporary, destination, retries)


def replace_tree(
    destination: Path, staged: Path, *, root: Path | None = None, retries: int = 5
) -> None:
    """Atomically move a staged tree into place and restore the old tree on failure."""

    _validate_retries(retries)
    if _plain_absolute(staged.parent) != _plain_absolute(destination.parent):
        raise ValueError("staged tree must be a sibling of destination")
    if root is not None and (
        has_link_component(destination.parent, root=root) or has_link_component(staged, root=root)
    ):
        raise ValueError("staged tree path contains a link component")
    backup = _backup_path(destination)
    had_destination = long_path(destination).exists() or is_link(destination)
    if had_destination:
        _replace_with_retries(destination, backup, retries)
    try:
        _replace_with_retries(staged, destination, retries)
    except OSError:
        if had_destination and not long_path(destination).exists():
            _replace_with_retries(backup, destination, retries)
        raise
    if had_destination:
        remove_tree(backup, ignore_errors=True)


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
    return plain_path(Path(raw_path))


def _create_temporary_link(destination: Path, source: Path) -> Path:
    """Create a private sibling link without exposing a partially written destination."""

    temporary = _create_temporary(destination, suffix=".link")
    try:
        os.unlink(os.fspath(long_path(temporary)))
        os.symlink(
            os.fspath(long_path(source)),
            os.fspath(long_path(temporary)),
            target_is_directory=True,
        )
    except BaseException:
        # Do not unlink an unexpected object that another local process inserted after the
        # placeholder was removed; the hidden name is harmless debris and data safety wins.
        if is_link(temporary):
            _remove_quietly(temporary)
        raise
    return temporary


def _backup_path(destination: Path) -> Path:
    for index in range(1, 100_000):
        backup = destination.parent / f".{destination.name}.backup.{index}"
        if not long_path(backup).exists() and not is_link(backup):
            return backup
    raise RuntimeError("could not allocate a backup path")


def _plain_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def plain_path(path: Path) -> Path:
    """Remove an inherited Windows extended prefix before a path returns to application code."""
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
    # Windows requires a writable handle for fsync; POSIX accepts a read-only one.
    mode = "r+b" if WINDOWS else "rb"
    with open(os.fspath(long_path(path)), mode) as handle:
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
    try:
        file_stat = os.lstat(os.fspath(long_path(temporary)))
    except FileNotFoundError:
        raise
    if is_link(temporary) or stat.S_ISLNK(file_stat.st_mode):
        raise ValueError("temporary download must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("temporary download must be a regular file")
    if getattr(file_stat, "st_nlink", 1) != 1:
        raise ValueError("temporary download must not be a hard link")


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(os.fspath(long_path(path)))
    except OSError:
        return


def _remove_link(path: Path) -> None:
    """Remove a link itself, using directory removal for Windows junctions."""
    if WINDOWS and long_path(path).is_dir():
        os.rmdir(os.fspath(long_path(path)))
    else:
        os.unlink(os.fspath(long_path(path)))


__all__ = [
    "DEFAULT_MAXLEN",
    "RESERVED",
    "WINDOWS",
    "atomic_install_temp",
    "atomic_write_bytes",
    "atomic_write_text",
    "collides",
    "ensure_dir",
    "has_link_component",
    "is_link",
    "long_path",
    "plain_path",
    "remove_tree",
    "replace_link",
    "replace_tree",
    "rel_posix",
    "walk",
    "reveal",
    "safe_name",
    "symlink_dir",
    "temporary_directory",
    "unique_path",
]
