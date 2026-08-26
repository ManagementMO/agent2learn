"""The single wall-clock seam for everything that reaches the vault.

Vault bytes must be reproducible: the golden-vault test hashes every generated file and
compares the map across Windows, macOS, and Linux.  A module that reads the clock directly
is therefore untestable for byte parity, because two runs can never agree.  Every writer
that stamps a timestamp into a manifest, twin, index, snapshot, or audit calls through here
so a test can freeze time in exactly one place.

``tests/test_no_forbidden_calls.py`` enforces this: ``datetime.now`` may only appear in this
module and in the authentication and transport paths, which never write vault content.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """Return the current instant as an aware UTC ``datetime``."""
    return datetime.now(UTC)


def stamp() -> str:
    """Return the current instant as the vault's canonical ``Z``-suffixed ISO-8601 string.

    The vault stores ``2026-08-25T12:00:00Z`` rather than ``+00:00`` so timestamps compare
    as plain strings and sort lexicographically in the same order as chronologically.
    """
    return to_stamp(now())


def to_stamp(value: datetime) -> str:
    """Render an aware UTC ``datetime`` in the vault's canonical timestamp form."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["now", "stamp", "to_stamp"]
