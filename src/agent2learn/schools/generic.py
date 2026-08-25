"""Conservative, explicitly opt-in adapter for an untested school."""

from __future__ import annotations

import warnings
from urllib.parse import urlsplit

from ._base import CONSERVATIVE_TOPIC_EXCLUSION_POLICY, TopicExclusionPolicy


class GenericSchool:
    """Represent a user-supplied host without pretending it is validated.

    The command layer must supply ``--host`` explicitly.  This adapter intentionally has no
    authentication or outline egress allowlist and emits a warning whenever it is constructed or
    used, so an untested institution cannot look like a supported integration.
    """

    id = "generic"
    name = "Untested school"
    timezone = "UTC"
    auth_hint = "Explicit host only; authentication is untested"

    def __init__(self, host: str) -> None:
        self.host = _validate_host(host)
        self.base_url = f"https://{self.host}"
        self._warn()

    def term_from_offering(self, code: str) -> str | None:
        self._warn()
        return None

    def term_label(self, term: str) -> str:
        self._warn()
        return f"Term {term}"

    def auth_hosts(self) -> list[str]:
        self._warn()
        return []

    def outline_hosts(self) -> list[str]:
        self._warn()
        return []

    def topic_exclusion_policy(self) -> TopicExclusionPolicy:
        self._warn()
        return CONSERVATIVE_TOPIC_EXCLUSION_POLICY

    def _warn(self) -> None:
        warnings.warn(
            "WARNING: untested school adapter; no authentication or outline hosts are approved",
            UserWarning,
            stacklevel=3,
        )


def _validate_host(host: str) -> str:
    if not isinstance(host, str) or not host.strip():
        raise ValueError("generic school requires a non-empty --host")
    raw = host.strip()
    if "://" in raw or any(character in raw for character in "/?#@"):
        raise ValueError("generic school --host must be a hostname, not a URL or path")

    parsed = urlsplit(f"//{raw}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("generic school --host has an invalid port") from exc
    if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
        raise ValueError("generic school --host must contain a hostname")

    hostname = parsed.hostname.rstrip(".").casefold()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"{hostname}:{port}" if port is not None else hostname


__all__ = ["GenericSchool"]
