"""Tests for institution-specific rules and timestamp rendering."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import pytest

from agent2learn.schools._base import (
    hostname_matches_suffix,
    parse_api_timestamp,
    render_timestamp,
    topic_is_excluded,
    utc_timestamp,
)
from agent2learn.schools.generic import GenericSchool
from agent2learn.schools.uwaterloo import UWaterloo


def test_term_parsing() -> None:
    uw = UWaterloo()
    assert uw.term_from_offering("COURSE101_section_1265") == "1265"
    assert uw.term_from_offering("COURSE202_081_section_1265") == "1265"
    assert uw.term_from_offering("ENGWellness") is None
    assert uw.term_from_offering("Course 2024 thing") is None


def test_term_parsing_uses_the_last_valid_four_digit_run() -> None:
    uw = UWaterloo()
    assert uw.term_from_offering("2024_COURSE101_section_1265") == "1265"
    assert uw.term_from_offering("COURSE101_section_9999") is None
    assert uw.term_from_offering("COURSE101_section_11265") is None


def test_term_label() -> None:
    uw = UWaterloo()
    assert uw.term_label("1265") == "Spring 2026"
    assert uw.term_label("1261") == "Winter 2026"
    assert uw.term_label("1269") == "Fall 2026"


def test_unknown_waterloo_term_labels_are_rejected() -> None:
    uw = UWaterloo()
    with pytest.raises(ValueError, match="term"):
        uw.term_label("1262")
    with pytest.raises(ValueError, match="term"):
        uw.term_label("not-a-term")


def test_waterloo_identity_and_timezone_are_explicit() -> None:
    uw = UWaterloo()
    assert uw.id == "uwaterloo"
    assert uw.name == "University of Waterloo"
    assert uw.base_url == "https://learn.uwaterloo.ca"
    assert uw.timezone == "America/Toronto"
    assert uw.auth_hint == "WatIAM + Duo"


def test_waterloo_does_not_guess_unreviewed_hosts() -> None:
    uw = UWaterloo()
    assert uw.auth_hosts() == []
    assert uw.outline_hosts() == []


def test_exclusion_policy_covers_licensed_content() -> None:
    policy = UWaterloo().topic_exclusion_policy()
    assert "lti" in policy.kinds
    assert "quicklink.d2l" in policy.url_markers
    assert any("vitalsource" in host for host in policy.host_suffixes)


def test_topic_exclusion_normalizes_kinds_and_url_markers() -> None:
    policy = UWaterloo().topic_exclusion_policy()
    assert topic_is_excluded(" LTI ", "https://learn.uwaterloo.ca/topic", policy)
    assert topic_is_excluded("content", "https://QUICKLINK.D2L.invalid/topic", policy)
    assert topic_is_excluded("content", "https://WWW.VITALSOURCE.COM/book", policy)
    assert topic_is_excluded("content", "https://learn.uwaterloo.ca/path?type=LTI", policy)
    assert not topic_is_excluded("content", "https://evilquicklink.d2l.invalid/topic", policy)


def test_hostname_suffix_matching_is_boundary_aware() -> None:
    suffixes = frozenset({"vitalsource.com"})
    assert hostname_matches_suffix("vitalsource.com", suffixes)
    assert hostname_matches_suffix("www.vitalsource.com", suffixes)
    assert hostname_matches_suffix("HTTPS://WWW.VITALSOURCE.COM/book", suffixes)
    assert not hostname_matches_suffix("notvitalsource.com", suffixes)
    assert not hostname_matches_suffix("vitalsource.com.evil.example", suffixes)


def test_lookalike_host_is_not_excluded_by_a_host_suffix_alone() -> None:
    policy = UWaterloo().topic_exclusion_policy()
    host_only_policy = type(policy)(
        kinds=frozenset(),
        host_suffixes=policy.host_suffixes,
        url_markers=frozenset(),
    )
    assert not topic_is_excluded(
        "content", "https://vitalsource.com.evil.example/book", host_only_policy
    )
    assert not topic_is_excluded("content", "https://vitalsource.com.evil.example/book", policy)


def test_generic_school_requires_an_explicit_host_and_warns() -> None:
    with pytest.raises(TypeError):
        GenericSchool()  # type: ignore[call-arg]

    with pytest.warns(UserWarning, match="untested school"):
        school = GenericSchool("courses.example")
    assert school.base_url == "https://courses.example"
    with pytest.warns(UserWarning, match="untested school"):
        assert school.auth_hosts() == []
    with pytest.warns(UserWarning, match="untested school"):
        assert school.outline_hosts() == []
    with pytest.warns(UserWarning, match="untested school"):
        assert school.term_from_offering("COURSE_section_1265") is None


def test_generic_school_uses_the_conservative_exclusion_policy() -> None:
    with pytest.warns(UserWarning, match="untested school"):
        policy = GenericSchool("courses.example").topic_exclusion_policy()
    assert "lti" in policy.kinds
    assert "quicklink.d2l" in policy.url_markers
    assert any("vitalsource" in host for host in policy.host_suffixes)


def test_api_timestamps_are_aware_and_stored_as_utc() -> None:
    parsed = parse_api_timestamp("2026-03-08T01:30:00-05:00")
    assert parsed == datetime(2026, 3, 8, 6, 30, tzinfo=UTC)
    assert parsed.tzinfo is UTC
    assert utc_timestamp("2026-03-08T01:30:00-05:00") == "2026-03-08T06:30:00Z"

    with pytest.raises(ValueError, match="aware"):
        parse_api_timestamp("2026-03-08T01:30:00")


def test_waterloo_timestamp_rendering_handles_the_dst_boundary() -> None:
    assert render_timestamp("2026-03-08T06:30:00Z", UWaterloo()) == "2026-03-08T01:30:00-05:00"
    assert render_timestamp("2026-03-08T07:30:00Z", UWaterloo()) == "2026-03-08T03:30:00-04:00"


def test_timestamp_bytes_do_not_depend_on_the_machine_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_tz = os.environ.get("TZ")
    serialized: list[bytes] = []
    try:
        for machine_tz in ("UTC", "Pacific/Auckland"):
            monkeypatch.setenv("TZ", machine_tz)
            if hasattr(time, "tzset"):
                time.tzset()
            payload = {
                "fetched_at": utc_timestamp("2026-03-08T07:30:00Z"),
                "displayed_at": render_timestamp("2026-03-08T07:30:00Z", UWaterloo()),
            }
            serialized.append(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        if hasattr(time, "tzset"):
            time.tzset()

    assert serialized[0] == serialized[1]
