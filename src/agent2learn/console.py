"""Terminal presentation and privacy-preserving local diagnostics."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, TextIO

from rich.console import Console

from agent2learn import __version__, config

_UNICODE_GLYPH = {"ok": "✓", "warn": "⚠", "fail": "✗", "info": "ℹ"}
_ASCII_GLYPH = {"ok": "[ok]", "warn": "[!]", "fail": "[x]", "info": "[-]"}
_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_LOGGER_NAME = "agent2learn"
_HANDLER_MARKER = "_agent2learn_allowlisted_handler"
_MAX_BYTES = 1_048_576
_BACKUP_COUNT = 4


def _glyphs_for(stream: TextIO) -> dict[str, str]:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return dict(_ASCII_GLYPH)
    try:
        "✓".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return dict(_ASCII_GLYPH)
    return dict(_UNICODE_GLYPH)


GLYPH = _glyphs_for(sys.stdout)


def out() -> Console:
    """Return a Rich console with color disabled for non-TTY and ``NO_COLOR`` output."""

    stream = sys.stdout
    terminal = _is_tty(stream)
    no_color = "NO_COLOR" in os.environ or not terminal
    supports_unicode = _glyphs_for(stream) == _UNICODE_GLYPH
    return Console(
        file=stream,
        force_terminal=terminal,
        no_color=no_color,
        emoji=supports_unicode,
    )


def get_logger() -> logging.Logger:
    """Return the package logger; handlers are installed by ``configure_logging``."""

    return logging.getLogger(_LOGGER_NAME)


def configure_logging(*, verbose: bool = False) -> logging.Logger:
    """Install a bounded handler that writes only structured allowlisted events.

    ``verbose`` changes diagnostic level, never the data schema. Ordinary logger calls without
    the private structured payload are rejected by the handler filter, so a future traceback or
    request debug string cannot accidentally become a local log record.
    """

    logger = get_logger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        os.fspath(config.log_path()),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_AllowlistedFilter())
    logger.addHandler(handler)
    return logger


def log_event(
    event: str,
    *,
    diagnostic_code: str | None = None,
    stage_ms: int | float | None = None,
    status: str | None = None,
    exception: BaseException | type[BaseException] | None = None,
    **context: object,
) -> None:
    """Write a safe event and deliberately discard all arbitrary context.

    ``context`` exists so callers can pass rich operation context without making it part of the
    persistence contract. URLs, headers, bodies, cookies, identities, course data, filenames,
    grades, discussions, drafts, and confirmation phrases are never serialized.
    """

    del context
    if not _CODE.fullmatch(event):
        raise ValueError("event must be a short diagnostic code")
    payload: dict[str, object] = {"event": event, "package_version": __version__}
    if diagnostic_code is not None:
        payload["diagnostic_code"] = _validated_code(diagnostic_code, "diagnostic_code")
    if stage_ms is not None:
        if isinstance(stage_ms, bool) or not isinstance(stage_ms, (int, float)):
            raise ValueError("stage_ms must be a finite non-negative number")
        if not math.isfinite(stage_ms) or stage_ms < 0:
            raise ValueError("stage_ms must be a finite non-negative number")
        payload["stage_ms"] = stage_ms
    if status is not None:
        payload["status"] = _validated_code(status, "status")
    if exception is not None:
        payload["exception_class"] = (
            exception.__name__ if isinstance(exception, type) else type(exception).__name__
        )

    logger = get_logger()
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        logger = configure_logging()
    logger.info("structured event", extra={"_a2l_payload": payload})


class _AllowlistedFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        payload: Any = getattr(record, "_a2l_payload", None)
        if not isinstance(payload, dict):
            return False
        record.msg = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record.args = ()
        return True


def _validated_code(value: str, field: str) -> str:
    if not _CODE.fullmatch(value):
        raise ValueError(f"{field} must be a short diagnostic code")
    return value


def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


__all__ = ["GLYPH", "configure_logging", "get_logger", "log_event", "out"]
