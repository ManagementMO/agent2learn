"""Regression tests for allowlisted, preview-first sensitive-category deletion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent2learn import config, privacy
from agent2learn.vault import Vault


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base_vault(root: Path) -> tuple[Vault, Path]:
    Vault.claim(root)
    course = root / "Spring 2026" / "COURSE101_1265"
    meta = course / "_meta"
    _write_json(
        meta / "content_map.json",
        {
            "schema_version": 1,
            "topics": [
                {
                    "source_key": "uwaterloo:101:topic:1",
                    "source_id": "1",
                    "topic_id": 1,
                    "course_code": "COURSE101_1265",
                    "course_name": "Synthetic Course",
                    "title": "Keep this lecture",
                    "kind": "File",
                }
            ],
        },
    )
    (course / "INDEX.md").write_text(
        "# Course\n\n- Deadline: Friday\n- Grade: 97%\n", encoding="utf-8"
    )
    (course / "content").mkdir(parents=True)
    (course / "content" / "keep.pdf").write_bytes(b"unrelated source")
    return Vault(root), course


def _write_snapshot(root: Path, *, grades: bool = True) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "created_at": "2026-08-28T12:00:00Z",
        "courses": [
            {
                "course": "Spring 2026/COURSE101_1265",
                "topic_ids": [1],
                "due_dates": ["2026-09-01T23:59:00Z"],
                "announcement_ids": ["a1"],
            }
        ],
    }
    if grades:
        courses = payload["courses"]
        assert isinstance(courses, list)
        assert isinstance(courses[0], dict)
        courses[0]["grades"] = [{"id": "g1", "displayed": "97%"}]
    destination = root / ".a2l" / "snapshots" / "20260828T120000Z.json"
    _write_json(destination, payload)
    return destination


def test_privacy_status_only_reports_category_state_and_redacted_locations(
    tmp_path: Path,
) -> None:
    vault, _course = _base_vault(tmp_path)
    cfg = config.Config(
        vault=tmp_path,
        include_grades=True,
        include_discussions=False,
    )

    status = privacy.status(vault, cfg)
    rendered = privacy.render_status(status)

    assert "grades: enabled" in rendered
    assert "discussions: disabled" in rendered
    assert "logs:" in rendered
    assert str(tmp_path) not in rendered
    assert "<vault>" in rendered


def test_confirmed_grade_purge_is_narrow_and_removes_snapshot_fields(tmp_path: Path) -> None:
    vault, course = _base_vault(tmp_path)
    grade_path = course / "_meta" / "my_grades.json"
    _write_json(grade_path, [{"id": "g1", "displayed": "97%"}])
    snapshot_path = _write_snapshot(tmp_path)

    history = tmp_path / ".a2l" / "history" / "grade-bucket" / "revision"
    _write_json(history / "revision.json", {"category": "grades", "value": "97%"})
    (history / "old-grade.json").write_text("97%\n", encoding="utf-8")
    backup = tmp_path / ".a2l-backup-v1" / "snapshots" / "old.json"
    _write_json(
        backup,
        {
            "schema_version": 1,
            "courses": [{"course": "x", "grades": [{"displayed": "97%"}]}],
        },
    )

    plan = privacy.plan_purge(vault, "grades")
    assert plan.category == "grades"
    assert any("my_grades.json" in target.display for target in plan.targets)
    assert any("grades field" in target.action for target in plan.targets)
    assert grade_path.exists()  # preview has no side effect

    privacy.execute_purge(vault, plan, phrase="PURGE GRADES", interactive=True)

    assert not grade_path.exists()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    course_snapshot = snapshot["courses"][0]
    assert course_snapshot["due_dates"] == ["2026-09-01T23:59:00Z"]
    assert "grades" not in course_snapshot
    assert "Grade:" not in (course / "INDEX.md").read_text(encoding="utf-8")
    assert "Deadline: Friday" in (course / "INDEX.md").read_text(encoding="utf-8")
    assert not history.exists()
    backup_payload = json.loads(backup.read_text(encoding="utf-8"))
    assert backup_payload["schema_version"] == 1
    assert backup_payload["courses"] == [{"course": "x"}]
    assert (course / "content" / "keep.pdf").read_bytes() == b"unrelated source"


def test_confirmed_discussion_purge_removes_category_artifacts_only(tmp_path: Path) -> None:
    vault, course = _base_vault(tmp_path)
    meta = course / "_meta"
    discussion_key = "uwaterloo:101:discussion:7"
    discussion_row = {
        "source_key": discussion_key,
        "source_id": "7",
        "topic_id": 7,
        "course_code": "COURSE101_1265",
        "course_name": "Synthetic Course",
        "title": "Discussion post",
        "kind": "Discussion",
        "path": "Spring 2026/COURSE101_1265/discussions/nested/post.md",
        "derived": {
            "markdown": {"path": "Spring 2026/COURSE101_1265/discussions/nested/post-twin.md"}
        },
    }
    content = json.loads((meta / "content_map.json").read_text(encoding="utf-8"))
    content["topics"].append(discussion_row)
    _write_json(meta / "content_map.json", content)
    _write_json(meta / "discussions.json", [{"id": 7, "posts": [{"id": 9}]}])
    discussion_dir = course / "discussions"
    discussion_dir.mkdir(parents=True)
    (discussion_dir / "discussions.md").write_text("private discussion", encoding="utf-8")
    (discussion_dir / "user-notes.md").write_text("keep this unrelated note", encoding="utf-8")
    (discussion_dir / "nested").mkdir()
    (discussion_dir / "nested" / "post.md").write_text("private source", encoding="utf-8")
    (discussion_dir / "nested" / "post-twin.md").write_text(
        "private derived twin", encoding="utf-8"
    )
    (course / "INDEX.md").write_text(
        "# Course\n\n- Deadline: Friday\n- Discussion post (discussions/post.md)\n",
        encoding="utf-8",
    )
    private_key = tmp_path / ".a2l" / "private" / "discussion-hmac.key"
    private_key.parent.mkdir(parents=True)
    private_key.write_bytes(b"k" * 32)
    manifest = {
        "schema_version": 1,
        "entries": {
            discussion_key: {
                "path": "Spring 2026/COURSE101_1265/discussions/post.html",
                "sha256": "0" * 64,
                "source_id": "7",
                "etag": None,
                "last_modified": None,
                "size": 1,
                "fetched_at": "2026-08-28T12:00:00Z",
                "derived": {},
            }
        },
    }
    _write_json(tmp_path / ".a2l" / "manifest.json", manifest)
    history = tmp_path / ".a2l" / "history" / "discussion-bucket" / "revision"
    _write_json(history / "revision.json", {"canonical_key": discussion_key})
    (history / "post.md").write_text("private history", encoding="utf-8")

    plan = privacy.plan_purge(vault, "discussions")
    privacy.execute_purge(vault, plan, phrase="PURGE DISCUSSIONS", interactive=True)

    assert discussion_dir.exists()
    assert not (discussion_dir / "discussions.md").exists()
    assert not (discussion_dir / "nested").exists()
    assert (discussion_dir / "user-notes.md").read_text(
        encoding="utf-8"
    ) == "keep this unrelated note"
    assert not (meta / "discussions.json").exists()
    remaining_topics = json.loads((meta / "content_map.json").read_text(encoding="utf-8"))["topics"]
    assert [row["source_key"] for row in remaining_topics] == ["uwaterloo:101:topic:1"]
    index = (course / "INDEX.md").read_text(encoding="utf-8")
    assert "Discussion" not in index
    assert "Deadline: Friday" in index
    assert "discussion" not in json.dumps(
        json.loads((tmp_path / ".a2l" / "manifest.json").read_text())
    )
    assert not private_key.exists()
    assert not history.exists()
    assert (course / "content" / "keep.pdf").exists()


def test_log_purge_removes_only_the_five_known_rotating_files(tmp_path: Path) -> None:
    vault, _course = _base_vault(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for suffix in ("", ".1", ".2", ".3", ".4"):
        (log_dir / f"a2l.log{suffix}").write_text("safe event", encoding="utf-8")
    (log_dir / "a2l.log.5").write_text("must remain", encoding="utf-8")
    (log_dir / "other.log").write_text("must remain", encoding="utf-8")

    cfg = config.Config(vault=tmp_path)
    plan = privacy.plan_purge(vault, "logs", log_directory=log_dir)
    assert len(plan.targets) == 5
    privacy.execute_purge(vault, plan, phrase="PURGE LOGS", interactive=True)

    assert not list(log_dir.glob("a2l.log"))
    assert not list(log_dir.glob("a2l.log.[1-4]"))
    assert (log_dir / "a2l.log.5").exists()
    assert (log_dir / "other.log").exists()
    del cfg


def test_sensitive_projection_is_found_without_a_content_map(tmp_path: Path) -> None:
    root = Vault.claim(tmp_path)
    vault = Vault(root)
    grade_path = root / "Spring 2026" / "COURSE101_1265" / "_meta" / "my_grades.json"
    _write_json(grade_path, [{"id": "g1", "displayed": "97%"}])

    plan = privacy.plan_purge(vault, "grades")

    assert any(target.path == grade_path for target in plan.targets)


def test_grade_purge_refuses_a_malformed_snapshot_instead_of_skipping_it(
    tmp_path: Path,
) -> None:
    vault, _course = _base_vault(tmp_path)
    _write_json(
        tmp_path / ".a2l" / "snapshots" / "broken.json",
        {"schema_version": 1, "created_at": "2026-08-28T12:00:00Z"},
    )

    with pytest.raises(Exception, match="snapshot courses"):
        privacy.plan_purge(vault, "grades")


def test_preview_and_noninteractive_boundaries_do_not_write(tmp_path: Path) -> None:
    vault, course = _base_vault(tmp_path)
    grade_path = course / "_meta" / "my_grades.json"
    _write_json(grade_path, [{"id": "g1", "displayed": "97%"}])
    plan = privacy.plan_purge(vault, "grades")

    with pytest.raises(Exception, match="interactive"):
        privacy.execute_purge(vault, plan, phrase="PURGE GRADES", interactive=False)
    assert grade_path.exists()

    grade_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(Exception, match="stale"):
        privacy.execute_purge(vault, plan, phrase="PURGE GRADES", interactive=True)
    assert grade_path.exists()


def test_unknown_category_and_symlinked_target_are_refused(tmp_path: Path) -> None:
    vault, course = _base_vault(tmp_path)
    with pytest.raises(Exception, match="category"):
        privacy.plan_purge(vault, "everything")

    outside = tmp_path / "outside.json"
    outside.write_text("private", encoding="utf-8")
    grade_path = course / "_meta" / "my_grades.json"
    try:
        grade_path.symlink_to(outside)
    except OSError:
        pytest.skip("the test environment cannot create symlinks")
    with pytest.raises(Exception, match="symlink"):
        privacy.plan_purge(vault, "grades")
