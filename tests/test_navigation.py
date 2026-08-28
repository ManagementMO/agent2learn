"""Tests for redaction-safe local topic search and course resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent2learn import index
from agent2learn.errors import A2LError
from agent2learn.vault import Vault


def _write_map(course: Path, topics: list[dict[str, object]]) -> None:
    destination = course / "_meta" / "content_map.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"schema_version": 1, "topics": topics}) + "\n",
        encoding="utf-8",
    )


def test_search_topics_finds_all_terms_and_excludes_sensitive_rows(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    vault = Vault(tmp_path)
    _write_map(
        tmp_path / "Winter 2026" / "COURSE101_1261",
        [
            {
                "source_key": "uwaterloo:101:topic:1",
                "source_id": "1",
                "topic_id": 1,
                "course_code": "COURSE101",
                "course_name": "Materials",
                "term": "1261",
                "title": "Phase diagrams",
                "kind": "File",
                "path": "Winter 2026/COURSE101_1261/content/phase.md",
            },
            {
                "source_key": "uwaterloo:101:discussion:9",
                "source_id": "9",
                "topic_id": 9,
                "title": "Phase discussion",
                "kind": "Discussion",
            },
        ],
    )
    _write_map(
        tmp_path / "Spring 2026" / "COURSE101_1265",
        [
            {
                "source_key": "uwaterloo:101:topic:2",
                "source_id": "2",
                "topic_id": 2,
                "course_code": "COURSE101",
                "course_name": "Materials",
                "term": "1265",
                "title": "Phase transformations",
                "kind": "File",
                "path": "Spring 2026/COURSE101_1265/content/phase.md",
            },
            {
                "source_key": "uwaterloo:101:topic:3",
                "source_id": "3",
                "topic_id": 3,
                "title": "Final grades",
                "kind": "Grade",
            },
        ],
    )

    matches = index.search_topics(vault, "phase")

    assert [match.course for match in matches] == [
        "Spring 2026/COURSE101_1265",
        "Winter 2026/COURSE101_1261",
    ]
    assert all(match.kind != "Discussion" for match in matches)
    assert all(match.title != "Final grades" for match in matches)
    assert all("\\" not in (match.path or "") for match in matches)


def test_resolve_course_requires_term_when_same_code_is_ambiguous(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    vault = Vault(tmp_path)
    for term in ("Winter 2026", "Spring 2026"):
        _write_map(
            tmp_path / term / "COURSE101",
            [
                {
                    "source_key": f"uwaterloo:{term}:topic:1",
                    "source_id": "1",
                    "topic_id": 1,
                    "course_code": "COURSE101",
                    "course_name": "Materials",
                    "term": term,
                    "title": "Lecture",
                }
            ],
        )

    with pytest.raises(A2LError, match="ambiguous"):
        index.resolve_course(vault, "COURSE101")
    assert index.resolve_course(vault, "Spring 2026/COURSE101") == (
        tmp_path / "Spring 2026" / "COURSE101"
    )


def test_navigation_rejects_path_escaping_metadata(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    vault = Vault(tmp_path)
    _write_map(
        tmp_path / "Term" / "COURSE",
        [
            {
                "source_key": "uwaterloo:1:topic:1",
                "source_id": "1",
                "topic_id": 1,
                "title": "Unsafe",
                "path": "../outside.md",
            }
        ],
    )

    with pytest.raises(A2LError, match="escapes"):
        index.search_topics(vault, "unsafe")
