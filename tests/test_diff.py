"""Regression tests for snapshot comparison and sensitive-value boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent2learn import paths, snapshot
from agent2learn.vault import Vault


def _snapshot(root: Path, filename: str, payload: dict[str, object]) -> None:
    destination = root / ".a2l" / "snapshots" / filename
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    paths.atomic_write_text(destination, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _payload(
    created_at: str,
    *,
    topic_ids: list[int],
    due_dates: list[str],
    announcement_ids: list[str],
    grades: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    course: dict[str, object] = {
        "course": "Spring 2026/COURSE101_1265",
        "topic_ids": topic_ids,
        "due_dates": due_dates,
        "announcement_ids": announcement_ids,
    }
    if grades is not None:
        course["grades"] = grades
    return {"schema_version": 1, "created_at": created_at, "courses": [course]}


def test_diff_reports_new_content_announcements_and_changed_due_dates(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    _snapshot(
        tmp_path,
        "20260827T120000Z.json",
        _payload(
            "2026-08-27T12:00:00Z",
            topic_ids=[1],
            due_dates=["2026-09-01T23:59:00Z"],
            announcement_ids=["a1"],
        ),
    )
    _snapshot(
        tmp_path,
        "20260828T120000Z.json",
        _payload(
            "2026-08-28T12:00:00Z",
            topic_ids=[1, 2],
            due_dates=["2026-09-02T23:59:00Z"],
            announcement_ids=["a1", "a2"],
        ),
    )

    result = snapshot.diff_vault(Vault(tmp_path))

    assert result.previous_timestamp == "2026-08-27T12:00:00Z"
    assert result.current_timestamp == "2026-08-28T12:00:00Z"
    assert result.new_content == ({"course": "Spring 2026/COURSE101_1265", "topic_id": 2},)
    assert result.new_announcements == (
        {"course": "Spring 2026/COURSE101_1265", "announcement_id": "a2"},
    )
    assert result.changed_due_dates == (
        {
            "course": "Spring 2026/COURSE101_1265",
            "previous": ("2026-09-01T23:59:00Z",),
            "current": ("2026-09-02T23:59:00Z",),
        },
    )

    rendered = snapshot.render_diff(result)
    assert "New content" in rendered
    assert "New announcements" in rendered
    assert "Changed due dates" in rendered


def test_diff_never_renders_grades_without_explicit_opt_in(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    _snapshot(
        tmp_path,
        "20260827T120000Z.json",
        _payload(
            "2026-08-27T12:00:00Z",
            topic_ids=[1],
            due_dates=[],
            announcement_ids=[],
            grades=[],
        ),
    )
    _snapshot(
        tmp_path,
        "20260828T120000Z.json",
        _payload(
            "2026-08-28T12:00:00Z",
            topic_ids=[1],
            due_dates=[],
            announcement_ids=[],
            grades=[
                {
                    "id": "grade-1",
                    "name": "Private assignment",
                    "displayed": "97%",
                }
            ],
        ),
    )

    default = snapshot.diff_vault(Vault(tmp_path))
    assert default.new_grades == ()
    assert "97%" not in snapshot.render_diff(default)
    assert "No changes recorded." in snapshot.render_diff(default)

    opted_in = snapshot.diff_vault(Vault(tmp_path), include_grades=True)
    assert "No changes recorded." in snapshot.render_diff(opted_in)
    assert opted_in.new_grades == (
        {
            "course": "Spring 2026/COURSE101_1265",
            "grade": {"displayed": "97%", "id": "grade-1", "name": "Private assignment"},
        },
    )
    assert "97%" in snapshot.render_diff(opted_in, include_grades=True)


def test_diff_with_one_snapshot_is_honest_about_missing_baseline(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    _snapshot(
        tmp_path,
        "20260828T120000Z.json",
        _payload(
            "2026-08-28T12:00:00Z",
            topic_ids=[1],
            due_dates=[],
            announcement_ids=[],
        ),
    )

    result = snapshot.diff_vault(Vault(tmp_path))

    assert result.previous_timestamp is None
    assert not result.has_baseline
    assert "No previous sync snapshot" in snapshot.render_diff(result)


def test_diff_preserves_microsecond_snapshot_identity(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    _snapshot(
        tmp_path,
        "20260828T120000123456Z.json",
        _payload(
            "2026-08-28T12:00:00.123456Z",
            topic_ids=[1],
            due_dates=[],
            announcement_ids=[],
        ),
    )
    _snapshot(
        tmp_path,
        "20260828T120001123456Z.json",
        _payload(
            "2026-08-28T12:00:01.123456Z",
            topic_ids=[1, 2],
            due_dates=[],
            announcement_ids=[],
        ),
    )

    result = snapshot.diff_vault(Vault(tmp_path), since="20260828T120000123456Z")

    assert result.previous_timestamp == "2026-08-28T12:00:00.123456Z"
    assert result.current_timestamp == "2026-08-28T12:00:01.123456Z"
    assert result.new_content == ({"course": "Spring 2026/COURSE101_1265", "topic_id": 2},)


def test_malformed_snapshot_is_not_silently_treated_as_empty(tmp_path: Path) -> None:
    Vault.claim(tmp_path)
    destination = tmp_path / ".a2l" / "snapshots" / "20260828T120000Z.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"not json")

    with pytest.raises(ValueError, match="snapshot"):
        snapshot.diff_vault(Vault(tmp_path))
