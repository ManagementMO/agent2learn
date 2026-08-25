"""School adapters and shared institution-specific policy helpers."""

from ._base import (
    CONSERVATIVE_TOPIC_EXCLUSION_POLICY,
    School,
    TopicExclusionPolicy,
    hostname_matches_suffix,
    normalize_topic_kind,
    parse_api_timestamp,
    render_timestamp,
    topic_is_excluded,
    utc_timestamp,
)
from .generic import GenericSchool
from .uwaterloo import UWaterloo

__all__ = [
    "CONSERVATIVE_TOPIC_EXCLUSION_POLICY",
    "GenericSchool",
    "School",
    "TopicExclusionPolicy",
    "UWaterloo",
    "hostname_matches_suffix",
    "normalize_topic_kind",
    "parse_api_timestamp",
    "render_timestamp",
    "topic_is_excluded",
    "utc_timestamp",
]
