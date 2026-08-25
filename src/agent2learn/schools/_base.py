"""Shared school-adapter contracts, policy matching, and time handling."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TopicExclusionPolicy:
    """Structured rules for topics that must remain link stubs."""

    kinds: frozenset[str]
    host_suffixes: frozenset[str]
    url_markers: frozenset[str]


@runtime_checkable
class School(Protocol):
    """Institution-specific rules used by the portable sync engine."""

    id: str
    name: str
    base_url: str
    timezone: str
    auth_hint: str

    def term_from_offering(self, code: str) -> str | None:
        """Return the institution's term code when an offering contains one."""

    def term_label(self, term: str) -> str:
        """Return the stable display label for a term code."""

    def auth_hosts(self) -> list[str]:
        """Return reviewed identity hosts allowed only during interactive auth."""

    def outline_hosts(self) -> list[str]:
        """Return reviewed first-party hosts allowed for outline rendering."""

    def topic_exclusion_policy(self) -> TopicExclusionPolicy:
        """Return structured licensed/external-topic exclusion rules."""


CONSERVATIVE_TOPIC_EXCLUSION_POLICY = TopicExclusionPolicy(
    kinds=frozenset({"lti"}),
    host_suffixes=frozenset({"vitalsource.com"}),
    url_markers=frozenset({"quicklink.d2l", "type=lti"}),
)


def normalize_topic_kind(kind: str) -> str:
    """Normalize the small topic-kind vocabulary used by policy matching."""

    return re.sub(r"[\s_-]+", "", kind.casefold().strip())


def hostname_matches_suffix(host_or_url: str, suffixes: Iterable[str]) -> bool:
    """Match a hostname or URL only at a DNS-label boundary.

    ``example.vitalsource.com`` matches ``vitalsource.com``; neither
    ``notvitalsource.com`` nor ``vitalsource.com.example`` does.  Parsing the URL before
    matching also prevents a lookalike value in a path or query from being treated as a host.
    """

    hostname = _hostname(host_or_url)
    if hostname is None:
        return False

    for suffix in suffixes:
        normalized_suffix = _hostname(suffix)
        if normalized_suffix is None:
            continue
        normalized_suffix = normalized_suffix.lstrip(".")
        if hostname == normalized_suffix or hostname.endswith(f".{normalized_suffix}"):
            return True
    return False


def topic_is_excluded(
    kind: str,
    url: str | None,
    policy: TopicExclusionPolicy,
) -> bool:
    """Return whether a topic is excluded by normalized kind, host, or URL marker."""

    normalized_kinds = {normalize_topic_kind(value) for value in policy.kinds}
    if normalize_topic_kind(kind) in normalized_kinds:
        return True

    if not url:
        return False
    if hostname_matches_suffix(url, policy.host_suffixes):
        return True

    return any(_url_marker_matches(url, marker) for marker in policy.url_markers)


def parse_api_timestamp(value: str) -> datetime:
    """Parse an API ISO-8601 timestamp and return an aware UTC instant."""

    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO 8601 string")

    candidate = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("timestamp must be a valid ISO 8601 value") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def utc_timestamp(value: str | datetime) -> str:
    """Serialize an API timestamp as a canonical UTC ISO-8601 value."""

    instant = _as_utc(value)
    return instant.isoformat().replace("+00:00", "Z")


def render_timestamp(value: str | datetime, school_or_timezone: School | str) -> str:
    """Render a UTC instant in an explicit school IANA timezone.

    No ambient process timezone or locale is consulted.  Passing a school object keeps the
    rendering rule attached to the adapter; a timezone string is useful for lower-level tests.
    """

    timezone_name = (
        school_or_timezone if isinstance(school_or_timezone, str) else school_or_timezone.timezone
    )
    return _as_utc(value).astimezone(ZoneInfo(timezone_name)).isoformat()


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        return parse_api_timestamp(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _hostname(value: str) -> str | None:
    candidate = value if "://" in value else f"//{value}"
    try:
        hostname = urlsplit(candidate).hostname
    except ValueError:
        return None
    if hostname is None:
        return None
    return hostname.rstrip(".").casefold()


def _url_marker_matches(url: str, marker: str) -> bool:
    """Match a URL marker without treating arbitrary hostname substrings as evidence."""

    folded_marker = marker.casefold().strip()
    if not folded_marker:
        return False

    candidate = url if "://" in url else f"//{url}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False

    hostname = _hostname(url)
    if hostname is not None and (
        hostname == folded_marker
        or hostname.startswith(f"{folded_marker}.")
        or hostname.endswith(f".{folded_marker}")
    ):
        return True

    non_host_url = f"{parsed.path}?{parsed.query}#{parsed.fragment}".casefold()
    pattern = rf"(?<![a-z0-9]){re.escape(folded_marker)}(?![a-z0-9])"
    return re.search(pattern, non_host_url) is not None


__all__ = [
    "CONSERVATIVE_TOPIC_EXCLUSION_POLICY",
    "School",
    "TopicExclusionPolicy",
    "hostname_matches_suffix",
    "normalize_topic_kind",
    "parse_api_timestamp",
    "render_timestamp",
    "topic_is_excluded",
    "utc_timestamp",
]
