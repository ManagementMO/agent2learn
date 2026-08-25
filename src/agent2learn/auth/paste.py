"""Pure cookie-blob parsing plus a cross-platform hidden multiline TTY reader."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from io import StringIO
from typing import Any, TextIO
from urllib.parse import urlsplit

from agent2learn.errors import AuthenticationError
from agent2learn.session import Session, SessionCookie

try:
    import termios as _termios
except ImportError:  # pragma: no cover - only Windows lacks termios
    termios: Any = None
else:
    termios = _termios

try:
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - only POSIX lacks msvcrt
    msvcrt: Any = None
else:
    msvcrt = _msvcrt

REQUIRED_COOKIE_NAMES = ("d2lSessionVal", "d2lSecureSessionVal")
_ALLOWED_COOKIE_NAMES = frozenset(
    {
        "d2lsessionval",
        "d2lsecuresessionval",
        "xsrf-token",
        "xsrf_token",
        "d2lxsrf-token",
    }
)
_SESSION_COOKIE_NAMES = frozenset({"d2lsessionval", "d2lsecuresessionval"})
_XSRF_COOKIE_NAMES = frozenset({"xsrf-token", "xsrf_token", "d2lxsrf-token"})
_SESSION_PATH = "/d2l"
_DEFAULT_PATH = "/"


class PasteError(AuthenticationError):
    """A pasted cookie blob was unavailable, malformed, or incomplete."""


def session_from_blob(
    blob: str,
    *,
    base_url: str,
    harvested_at: datetime | None = None,
) -> Session:
    """Parse one supported export shape into the same minimal session projection."""

    host = _configured_host(base_url)
    records = _records_from_blob(blob, host)
    return _session_from_records(records, base_url=base_url, host=host, harvested_at=harvested_at)


def session_from_cookie_records(
    records: Iterable[Mapping[str, object]],
    *,
    base_url: str,
    harvested_at: datetime,
    user_id: str | None = None,
) -> Session:
    """Reduce CDP's full profile cookie list to the same paste-session projection."""

    host = _configured_host(base_url)
    return _session_from_records(
        records,
        base_url=base_url,
        host=host,
        harvested_at=harvested_at,
        user_id=user_id,
    )


def _session_from_records(
    records: Iterable[Mapping[str, object]],
    *,
    base_url: str,
    host: str,
    harvested_at: datetime | None,
    user_id: str | None = None,
) -> Session:
    cookies = _filter_records(records, host)
    _require_minimum(cookies)
    xsrf = next(
        (cookie.value for cookie in cookies if cookie.name.casefold() in _XSRF_COOKIE_NAMES),
        None,
    )
    return Session(
        base_url=base_url,
        cookies=tuple(cookies),
        xsrf=xsrf,
        harvested_at=harvested_at or datetime.now(UTC),
        user_id=user_id,
    )


def read_hidden_multiline(
    *, input_stream: TextIO | None = None, output_stream: TextIO | None = None
) -> str:
    """Read pasted secrets only from a controlling TTY with terminal echo disabled."""

    input_value = sys.stdin if input_stream is None else input_stream
    output_value = sys.stderr if output_stream is None else output_stream
    if not _is_tty(input_value) or not _is_tty(output_value):
        raise PasteError("cookie paste requires a controlling TTY; piped input is refused")

    if os.name == "nt":
        return _read_windows_hidden(output_value)
    if termios is None:  # pragma: no cover - defensive platform branch
        raise PasteError("hidden cookie input is unavailable on this platform")
    return _read_posix_hidden(input_value, output_value)


def _read_posix_hidden(input_stream: TextIO, output_stream: TextIO) -> str:
    if termios is None:  # pragma: no cover - guarded by read_hidden_multiline
        raise PasteError("hidden cookie input is unavailable on this platform")
    try:
        fd = input_stream.fileno()
        original = termios.tcgetattr(fd)
    except (AttributeError, OSError, termios.error) as exc:
        raise PasteError("cookie paste requires a usable controlling TTY") from exc

    hidden = original.copy()
    hidden[3] &= ~termios.ECHO
    changed = False
    try:
        termios.tcsetattr(fd, termios.TCSANOW, hidden)
        changed = True
        output_stream.write("Paste cookies, then press Ctrl-D to finish:\n")
        output_stream.flush()
        return input_stream.read()
    finally:
        if changed:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        output_stream.write("\n")
        output_stream.flush()


def _read_windows_hidden(output_stream: TextIO) -> str:
    if msvcrt is None:  # pragma: no cover - defensive platform branch
        raise PasteError("hidden cookie input is unavailable on this platform")

    output_stream.write("Paste cookies, then press Ctrl-Z and Enter to finish:\n")
    output_stream.flush()
    characters: list[str] = []
    while True:
        character = msvcrt.getwch()
        if character in {"\x03"}:
            raise KeyboardInterrupt
        if character in {"\x1a", "\x04"}:
            output_stream.write("\n")
            output_stream.flush()
            return "".join(characters)
        if character in {"\r", "\n"}:
            if not characters or characters[-1] != "\n":
                characters.append("\n")
            continue
        if character == "\b":
            if characters and characters[-1] != "\n":
                characters.pop()
            continue
        characters.append(character)


def _records_from_blob(blob: str, host: str) -> list[dict[str, object]]:
    if not isinstance(blob, str) or not blob.strip():
        raise PasteError("cookie paste is empty")

    stripped = blob.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _records_from_json(stripped)
    if _looks_like_table(stripped):
        return _records_from_table(stripped)
    return _records_from_lines(stripped, host)


def _records_from_json(blob: str) -> list[dict[str, object]]:
    try:
        raw: Any = json.loads(blob)
    except json.JSONDecodeError:
        raise PasteError("cookie JSON export is malformed") from None

    raw_records = raw.get("cookies") if isinstance(raw, dict) else raw
    if not isinstance(raw_records, list):
        raise PasteError("cookie JSON export has no cookie list")

    records: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        records.append({str(key): value for key, value in record.items()})
    return records


def _records_from_table(blob: str) -> list[dict[str, object]]:
    lines = [line for line in blob.splitlines() if line.strip()]
    delimiter = "\t" if any("\t" in line for line in lines) else None
    if delimiter is None:
        rows = [re.split(r"\s{2,}", line.strip()) for line in lines]
    else:
        rows = list(csv.reader(StringIO("\n".join(lines)), delimiter=delimiter))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if {cell.strip().casefold() for cell in row} >= {"name", "value"}
        ),
        None,
    )
    if header_index is None:
        raise PasteError("cookie table must contain Name and Value columns")
    header = [cell.strip().casefold() for cell in rows[header_index]]
    records: list[dict[str, object]] = []
    for row in rows[header_index + 1 :]:
        if len(row) < 2:
            continue
        record: dict[str, object] = {}
        for key in ("name", "value", "domain", "path", "secure"):
            if key in header:
                position = header.index(key)
                record[key] = row[position].strip() if position < len(row) else ""
        records.append(record)
    return records


def _records_from_lines(blob: str, host: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in blob.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.casefold().startswith("cookie:"):
            candidate = candidate.split(":", 1)[1].strip()
        pieces = candidate.split(";") if ";" in candidate else [candidate]
        for piece in pieces:
            if "=" not in piece:
                continue
            name, value = piece.split("=", 1)
            name = name.strip()
            if not name:
                continue
            records.append(
                {
                    "name": name,
                    "value": value.strip(),
                    "domain": f".{host}",
                    "path": (
                        _SESSION_PATH if name.casefold() in _SESSION_COOKIE_NAMES else _DEFAULT_PATH
                    ),
                    "secure": True,
                }
            )
    return records


def _filter_records(records: Iterable[Mapping[str, object]], host: str) -> list[SessionCookie]:
    selected: dict[str, SessionCookie] = {}
    for record in records:
        name_value = record.get("name")
        value = record.get("value")
        domain_value = record.get("domain")
        path_value = record.get("path")
        if not isinstance(name_value, str) or not isinstance(value, str):
            continue
        folded_name = name_value.casefold()
        if folded_name not in _ALLOWED_COOKIE_NAMES:
            continue
        if not isinstance(domain_value, str) or not _same_host(domain_value, host):
            continue
        path = (
            path_value
            if isinstance(path_value, str) and path_value.startswith("/")
            else (_SESSION_PATH if folded_name in _SESSION_COOKIE_NAMES else _DEFAULT_PATH)
        )
        selected[folded_name] = SessionCookie(
            name=_canonical_cookie_name(name_value),
            value=value,
            domain=_canonical_domain(domain_value),
            path=path,
            secure=_as_bool(record.get("secure"), default=True),
        )

    ordered: list[SessionCookie] = []
    for name in (*REQUIRED_COOKIE_NAMES, "XSRF-TOKEN", "XSRF_TOKEN", "d2lXSRF-Token"):
        cookie = selected.get(name.casefold())
        if cookie is not None:
            ordered.append(cookie)
    return ordered


def _require_minimum(cookies: Iterable[SessionCookie]) -> None:
    names = {cookie.name.casefold() for cookie in cookies}
    missing = [name for name in REQUIRED_COOKIE_NAMES if name.casefold() not in names]
    if missing:
        raise PasteError("missing required LEARN cookies: " + ", ".join(missing))


def _configured_host(value: str) -> str:
    try:
        parsed = urlsplit(value if "://" in value else f"https://{value}")
    except ValueError as exc:
        raise PasteError("configured LEARN host is invalid") from exc
    if parsed.hostname is None:
        raise PasteError("configured LEARN host is invalid")
    return _canonical_hostname(parsed.hostname)


def _same_host(domain: str, host: str) -> bool:
    candidate = domain.lstrip(".").rstrip(".")
    try:
        return _canonical_hostname(candidate) == host
    except ValueError:
        return False


def _canonical_hostname(value: str) -> str:
    return value.encode("idna").decode("ascii").casefold().rstrip(".")


def _canonical_domain(value: str) -> str:
    prefix = "." if value.startswith(".") else ""
    return prefix + _canonical_hostname(value.lstrip(".").rstrip("."))


def _canonical_cookie_name(value: str) -> str:
    folded = value.casefold()
    if folded == "d2lxsrf-token":
        return "d2lXSRF-Token"
    if folded == "xsrf_token":
        return "XSRF_TOKEN"
    if folded == "xsrf-token":
        return "XSRF-TOKEN"
    if folded == "d2lsessionval":
        return "d2lSessionVal"
    if folded == "d2lsecuresessionval":
        return "d2lSecureSessionVal"
    return value


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "✓", "secure"}
    return default


def _looks_like_table(blob: str) -> bool:
    first_lines = blob.splitlines()[:3]
    return any(
        {cell.strip().casefold() for cell in re.split(r"\t|\s{2,}", line)} >= {"name", "value"}
        for line in first_lines
    )


def _is_tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


__all__ = [
    "PasteError",
    "REQUIRED_COOKIE_NAMES",
    "read_hidden_multiline",
    "session_from_blob",
    "session_from_cookie_records",
]
