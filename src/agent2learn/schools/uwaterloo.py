"""University of Waterloo school adapter."""

from __future__ import annotations

import re

from ._base import CONSERVATIVE_TOPIC_EXCLUSION_POLICY, TopicExclusionPolicy

_TERM_RUN = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_SEASONS = {1: "Winter", 5: "Spring", 9: "Fall"}


class UWaterloo:
    """Rules for Waterloo's LEARN instance and academic term codes."""

    id: str = "uwaterloo"
    name: str = "University of Waterloo"
    base_url: str = "https://learn.uwaterloo.ca"
    timezone: str = "America/Toronto"
    auth_hint: str = "WatIAM + Duo"

    def term_from_offering(self, code: str) -> str | None:
        """Return the last four-digit Waterloo term code in the offering string."""

        valid = [
            match.group(1)
            for match in _TERM_RUN.finditer(code)
            if 1000 <= int(match.group(1)) <= 1999
        ]
        return valid[-1] if valid else None

    def term_label(self, term: str) -> str:
        """Convert a Waterloo term code such as ``1265`` to ``Spring 2026``."""

        if not re.fullmatch(r"\d{4}", term):
            raise ValueError(f"invalid Waterloo term code: {term!r}")
        term_code = int(term)
        if not 1000 <= term_code <= 1999:
            raise ValueError(f"invalid Waterloo term code: {term!r}")
        season = _SEASONS.get(term_code % 10)
        if season is None:
            raise ValueError(f"unknown Waterloo term season: {term!r}")
        year = 1900 + term_code // 10
        return f"{season} {year}"

    def auth_hosts(self) -> list[str]:
        """Return only identity hosts backed by reviewed same-device release evidence.

        P1 established same-device LEARN API replay but did not record a redacted host allowlist.
        An empty list is therefore safer and more truthful than guessing at a redirect target.
        """

        return []

    def outline_hosts(self) -> list[str]:
        """Return reviewed first-party outline hosts beyond the configured LEARN origin."""

        return []

    def topic_exclusion_policy(self) -> TopicExclusionPolicy:
        """Return Waterloo's licensed-topic exclusion policy."""

        return CONSERVATIVE_TOPIC_EXCLUSION_POLICY


__all__ = ["UWaterloo"]
