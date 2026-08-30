"""Regression tests for metadata-first, revision-safe ingest."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from ingest_support import DownloadHandler, FakeClient, course

from agent2learn import ingest as ingest_module
from agent2learn.api import DownloadError, DownloadResult
from agent2learn.errors import A2LError
from agent2learn.ingest import fetch_topic, ingest_files, ingest_metadata
from agent2learn.vault import Vault


def _toc(*topics: dict[str, object]) -> dict[str, object]:
    return {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Week 1",
                "Modules": [],
                "Topics": list(topics),
            }
        ]
    }


def _topic(
    topic_id: int,
    title: str,
    *,
    filename: str | None = None,
    modified: str = "2026-01-05T14:00:00.000Z",
    kind: str = "File",
) -> dict[str, object]:
    name = filename or f"topic-{topic_id}.pdf"
    return {
        "TopicId": topic_id,
        "Title": title,
        "TypeIdentifier": kind,
        "Url": f"/content/enforced/111111-COURSE101/{name}",
        "LastModifiedDate": modified,
        "IsBroken": False,
        "Size": 1024,
    }


def _map_files(root: Path) -> list[Path]:
    return sorted(root.rglob("content_map.json"))


def _map(root: Path) -> dict[str, object]:
    paths = _map_files(root)
    assert len(paths) == 1
    raw = json.loads(paths[0].read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _topic_rows(root: Path) -> list[dict[str, object]]:
    raw = _map(root)
    rows = raw["topics"]
    assert isinstance(rows, list)
    return rows


def test_external_stub_keeps_plain_paths_at_long_path_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extended Windows path must never become a value that callers join or store."""
    vault = Vault(tmp_path)
    course_dir = vault.root / "Term 1261" / "COURSE101_1261"
    stub = course_dir / "content" / "external.url.txt"
    rows: list[dict[str, object]] = [
        {
            "source_key": "uwaterloo:111111:topic:1",
            "source_id": "1",
            "topic_id": 1,
            "course_code": "COURSE101",
            "course_name": "Synthetic Course",
            "title": "External",
            "kind": "Link",
            "module_path": [],
            "availability": "external_link",
            "view_url": "https://example.test/topic/1",
            "stub_path": "Term 1261/COURSE101_1261/content/external.url.txt",
        }
    ]
    calls: list[Path] = []

    def fake_long_path(path: Path) -> Path:
        return path.parent / "__extended__" / path.name

    monkeypatch.setattr(ingest_module.paths, "long_path", fake_long_path)
    monkeypatch.setattr(
        ingest_module.paths,
        "atomic_write_text",
        lambda destination, text, **_kwargs: calls.append(destination),
    )

    ingest_module._materialize_external_stubs(
        rows,
        course_dir=course_dir,
        vault=vault,
        school=FakeClient([]).school,
        course=course(),
    )

    assert calls == [stub]


@pytest.mark.skipif(os.name == "nt", reason="symlink creation may require elevation")
def test_metadata_refuses_a_linked_course_directory_without_writing_outside_vault(
    tmp_path: Path,
) -> None:
    root = Vault.claim(tmp_path / "vault")
    outside = tmp_path / "outside"
    outside.mkdir()
    term_dir = root / "Winter 2026"
    term_dir.mkdir()
    (term_dir / "COURSE101_1261").symlink_to(outside, target_is_directory=True)
    fake_client = FakeClient([course()])

    with pytest.raises(A2LError, match="link component"):
        ingest_metadata(fake_client, Vault(root), fake_client.school)

    assert not list(outside.rglob("*"))


def _handler_for(
    payloads: dict[str, bytes], *, last_modified: str | None = None
) -> DownloadHandler:
    def download(url: str, temp: Path, prior: object | None) -> DownloadResult:
        del prior
        key = urlsplit(url).path.rsplit("/", 1)[-1]
        if key not in payloads:
            key = next((name for name in payloads if name in urlsplit(url).path), key)
        if key not in payloads and len(payloads) == 1:
            key = next(iter(payloads))
        payload = payloads[key]
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(payload)
        return DownloadResult(
            temp=temp,
            sha256=sha256(payload).hexdigest(),
            size=len(payload),
            etag=None,
            last_modified=last_modified,
            not_modified=False,
        )

    return download


def test_unchanged_fingerprint_and_matching_local_hash_skip_download(tmp_path: Path) -> None:
    topic = _topic(1, "Lecture", modified="2026-01-05T14:00:00.000Z")
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        download_handler=_handler_for(
            {"topic-1.pdf": b"same bytes"}, last_modified="2026-01-05T14:00:00.000Z"
        ),
    )
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)
    first_count = len(fake_client.download_calls)

    ingest_metadata(fake_client, vault, fake_client.school)
    report = ingest_files(fake_client, vault, fake_client.school)

    assert first_count == 1
    assert len(fake_client.download_calls) == first_count
    assert report.skipped >= 1


def test_changed_bytes_preserve_previous_revision_before_install(tmp_path: Path) -> None:
    topic = _topic(1, "Lecture", modified="2026-01-05T14:00:00.000Z")
    payload = {"topic-1.pdf": b"old bytes"}
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        download_handler=_handler_for(payload, last_modified="2026-01-05T14:00:00.000Z"),
    )
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)
    old_hash = sha256(payload["topic-1.pdf"]).hexdigest()

    payload["topic-1.pdf"] = b"new bytes"
    topic["LastModifiedDate"] = "2026-01-12T14:00:00.000Z"
    fake_client.download_handler = _handler_for(payload, last_modified="2026-01-12T14:00:00.000Z")
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)

    key = "uwaterloo:111111:topic:1"
    current = vault.entry(key)
    assert current is not None
    assert current.sha256 == sha256(b"new bytes").hexdigest()
    history = vault.history_bucket(key)
    revisions = [
        path for path in history.rglob("*") if path.is_file() and path.name != "revision.json"
    ]
    assert revisions
    assert any(path.read_bytes() == b"old bytes" for path in revisions)
    assert old_hash != current.sha256


def test_same_named_topics_get_stable_collision_suffixes(tmp_path: Path) -> None:
    topics = (
        _topic(1, "Lab Notes", filename="a.pdf"),
        _topic(2, "lab notes", filename="b.pdf"),
    )
    fake_client = FakeClient([course()], tocs={111111: _toc(*topics)})
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)

    paths = sorted(entry.path for entry in vault.manifest().values())
    assert len(paths) == 2
    assert paths[0].endswith("Lab Notes.pdf")
    assert paths[1].casefold().endswith("lab notes_2.pdf")


def test_office_lock_file_is_recorded_without_download(tmp_path: Path) -> None:
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "~$Draft.docx", filename="~$Draft.docx"))},
    )
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    report = ingest_files(fake_client, vault, fake_client.school)

    assert fake_client.download_calls == []
    assert report.metadata_only >= 1
    row = _topic_rows(tmp_path)[0]
    assert row["availability"] == "metadata_only"
    assert row["next_action"] == "office lock file skipped"


def test_interrupted_stream_preserves_previous_file_and_manifest(tmp_path: Path) -> None:
    topic = _topic(1, "Lecture")
    first = True

    def download(url: str, temp: Path, prior: object | None) -> DownloadResult:
        nonlocal first
        del url, prior
        if first:
            payload = b"complete old source"
            first = False
            temp.write_bytes(payload)
            return DownloadResult(
                temp, sha256(payload).hexdigest(), len(payload), None, None, False
            )
        temp.write_bytes(b"partial new source")
        raise RuntimeError("stream interrupted")

    fake_client = FakeClient([course()], tocs={111111: _toc(topic)}, download_handler=download)
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)
    before = vault.entry("uwaterloo:111111:topic:1")
    assert before is not None
    before_bytes = vault.materialized(before).read_bytes()

    topic["LastModifiedDate"] = "2026-01-12T14:00:00.000Z"
    ingest_metadata(fake_client, vault, fake_client.school)

    with pytest.raises(RuntimeError, match="interrupted"):
        ingest_files(fake_client, vault, fake_client.school)

    after = Vault(tmp_path).entry("uwaterloo:111111:topic:1")
    assert after == before
    assert Vault(tmp_path).materialized(after).read_bytes() == before_bytes
    assert not list(tmp_path.rglob("*.part"))


def test_failed_install_retries_the_retained_part_without_redownloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(1, "Lecture")
    payload = b"downloaded once"
    topic["Size"] = len(payload)
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        download_handler=_handler_for({"topic-1.pdf": payload}),
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    def refuse_install(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    real_install = ingest_module.paths.atomic_install_temp
    monkeypatch.setattr(ingest_module.paths, "atomic_install_temp", refuse_install)
    with pytest.raises(PermissionError):
        ingest_files(fake_client, vault, fake_client.school)

    assert len(fake_client.download_calls) == 1
    assert list(tmp_path.rglob("*.part"))
    assert next(tmp_path.rglob("*.part")).read_bytes() == payload
    assert list(tmp_path.rglob("*.part.meta.json"))

    monkeypatch.setattr(ingest_module.paths, "atomic_install_temp", real_install)
    report = ingest_files(fake_client, vault, fake_client.school)

    assert len(fake_client.download_calls) == 1
    assert report.downloaded == 1
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.part.meta.json"))


def test_retained_part_without_remote_fingerprint_is_revalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = _topic(1, "Lecture")
    topic["LastModifiedDate"] = None
    payload = b"downloaded once"
    topic["Size"] = len(payload)
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        download_handler=_handler_for({"topic-1.pdf": payload}),
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    real_install = ingest_module.paths.atomic_install_temp

    def refuse_install(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(
        ingest_module.paths,
        "atomic_install_temp",
        refuse_install,
    )
    with pytest.raises(PermissionError):
        ingest_files(fake_client, vault, fake_client.school)

    monkeypatch.setattr(ingest_module.paths, "atomic_install_temp", real_install)
    ingest_files(fake_client, vault, fake_client.school)

    assert len(fake_client.download_calls) == 2


def test_keyboard_interrupt_checkpoints_completed_entries(tmp_path: Path) -> None:
    topics = (_topic(1, "First", filename="first.pdf"), _topic(2, "Second", filename="second.pdf"))
    calls = 0

    def download(url: str, temp: Path, prior: object | None) -> DownloadResult:
        nonlocal calls
        del prior
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        payload = urlsplit(url).path.encode("utf-8")
        temp.write_bytes(payload)
        return DownloadResult(temp, sha256(payload).hexdigest(), len(payload), None, None, False)

    fake_client = FakeClient([course()], tocs={111111: _toc(*topics)}, download_handler=download)
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    report = ingest_files(fake_client, vault, fake_client.school)

    assert report.interrupted is True
    assert report.exit_code == 130
    assert "uwaterloo:111111:topic:1" in Vault(tmp_path).manifest()
    assert "uwaterloo:111111:topic:2" not in Vault(tmp_path).manifest()


def test_metadata_phase_writes_typed_projections_and_grades_are_opt_in(tmp_path: Path) -> None:
    topic = _topic(1, "Lecture")
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        responses={
            "/dropbox/folders/": [
                {
                    "Id": 20,
                    "Name": "Problem Set",
                    "DueDate": "2026-02-06T04:59:00.000Z",
                    "Availability": {"StartDate": "2026-01-05T14:00:00.000Z", "EndDate": None},
                    "GradeItemId": 1,
                    "GroupTypeId": None,
                }
            ],
            "/news/": [
                {
                    "Id": 30,
                    "Title": "Welcome",
                    "Body": {"Text": "Read the outline.", "Html": None},
                    "StartDate": "2026-01-05T14:00:00.000Z",
                    "EndDate": None,
                    "IsPublished": True,
                }
            ],
            "/quizzes/": {"Next": None, "Objects": []},
            "/grades/values/myGradeValues/": [
                {
                    "GradeObjectIdentifier": "1",
                    "GradeObjectName": "Problem Set",
                    "GradeObjectType": "Numeric",
                    "PointsNumerator": 5,
                    "PointsDenominator": 5,
                    "DisplayedGrade": "100%",
                }
            ],
        },
    )
    vault = Vault(tmp_path)

    report = ingest_metadata(fake_client, vault, fake_client.school)
    course_dir = report.courses[0].directory
    assert report.deadline_count == 1
    assert (course_dir / "INDEX.md").is_file()
    assert not (course_dir / "_meta" / "my_grades.json").exists()
    assert not any("/grades/" in path for path in fake_client.json_calls)
    assert json.loads((course_dir / "_meta" / "assignments.json").read_text())

    ingest_metadata(fake_client, vault, fake_client.school, include_grades=True)
    assert (course_dir / "_meta" / "my_grades.json").is_file()
    assert any("/grades/" in path for path in fake_client.json_calls)


def test_unexpected_calibration_load_error_is_not_replaced_by_recalibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeClient([])
    del fake_client.courses

    def fail_load() -> object:
        raise RuntimeError("calibration parser regression")

    def should_not_recalibrate(_client: object) -> object:
        raise AssertionError("unexpected calibration errors must not trigger network work")

    monkeypatch.setattr(ingest_module, "load_calibration", fail_load)
    monkeypatch.setattr(ingest_module, "calibrate", should_not_recalibrate)

    with pytest.raises(RuntimeError, match="parser regression"):
        ingest_module._selected_courses(fake_client, term=None, only=None)


def test_metadata_list_with_wrong_root_shape_is_not_treated_as_empty(tmp_path: Path) -> None:
    destination = tmp_path / "assignments.json"
    destination.write_text(json.dumps({"items": []}), encoding="utf-8")

    with pytest.raises(A2LError, match="assignments.json"):
        ingest_module._read_list(destination)


def test_metadata_list_with_malformed_utf8_is_not_treated_as_empty(tmp_path: Path) -> None:
    destination = tmp_path / "assignments.json"
    destination.write_bytes(b"[\xff")

    with pytest.raises(A2LError, match="assignments.json"):
        ingest_module._read_list(destination)


def test_metadata_list_with_invalid_items_is_not_silently_filtered(tmp_path: Path) -> None:
    destination = tmp_path / "assignments.json"
    destination.write_text(json.dumps([{"id": 1}, "lost row"]), encoding="utf-8")

    with pytest.raises(A2LError, match="invalid item"):
        ingest_module._read_list(destination)


def test_malformed_collection_response_cannot_mark_existing_rows_missing(
    tmp_path: Path,
) -> None:
    assignment = {
        "Id": 20,
        "Name": "Problem Set",
        "DueDate": "2026-02-06T04:59:00.000Z",
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc()},
        responses={"/dropbox/folders/": [assignment]},
    )
    vault = Vault(tmp_path)
    first = ingest_metadata(fake_client, vault, fake_client.school)
    assignments_path = first.courses[0].directory / "_meta" / "assignments.json"
    assert json.loads(assignments_path.read_text(encoding="utf-8"))[0]["id"] == 20

    fake_client.responses["/dropbox/folders/"] = ["malformed row"]
    second = ingest_metadata(fake_client, vault, fake_client.school)

    row = json.loads(assignments_path.read_text(encoding="utf-8"))[0]
    assert row["missing_since"] is None
    assert row["withdrawn_at"] is None
    assert "assignments: A2LError" in second.errors


def test_incomplete_grade_response_preserves_previous_values(tmp_path: Path) -> None:
    grade = {
        "GradeObjectIdentifier": "1",
        "GradeObjectName": "Problem Set",
        "GradeObjectType": "Numeric",
        "PointsNumerator": 5,
        "PointsDenominator": 5,
        "DisplayedGrade": "100%",
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc()},
        responses={"/grades/values/myGradeValues/": [grade]},
    )
    vault = Vault(tmp_path)
    first = ingest_metadata(fake_client, vault, fake_client.school, include_grades=True)
    grades_path = first.courses[0].directory / "_meta" / "my_grades.json"
    original_bytes = grades_path.read_bytes()

    fake_client.responses["/grades/values/myGradeValues/"] = ["malformed row"]
    second = ingest_metadata(fake_client, vault, fake_client.school, include_grades=True)

    assert grades_path.read_bytes() == original_bytes
    assert "grades: A2LError" in second.errors


def test_malformed_assignment_attachments_cannot_mark_existing_topics_missing(
    tmp_path: Path,
) -> None:
    assignment = {
        "Id": 20,
        "Name": "Problem Set",
        "Attachments": [
            {
                "Id": 900001,
                "FileName": "starter.pdf",
                "Url": "/content/enforced/111111-COURSE101/starter.pdf",
                "Size": 4,
            }
        ],
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc()},
        responses={"/dropbox/folders/": [assignment]},
    )
    vault = Vault(tmp_path)
    first = ingest_metadata(fake_client, vault, fake_client.school)
    map_path = first.courses[0].directory / "_meta" / "content_map.json"
    original = next(
        row
        for row in json.loads(map_path.read_text(encoding="utf-8"))["topics"]
        if row["source_id"] == "20-900001"
    )
    assert original["missing_since"] is None

    fake_client.responses["/dropbox/folders/"] = [
        {"Id": 20, "Name": "Problem Set", "Attachments": ["malformed attachment"]}
    ]
    second = ingest_metadata(fake_client, vault, fake_client.school)

    current = next(
        row
        for row in json.loads(map_path.read_text(encoding="utf-8"))["topics"]
        if row["source_id"] == "20-900001"
    )
    assert current["missing_since"] is None
    assert current["withdrawn_at"] is None
    assert "assignments: A2LError" in second.errors


def test_cached_toc_with_malformed_utf8_is_reported_as_a_metadata_gap(tmp_path: Path) -> None:
    course_dir = tmp_path / "Term" / "COURSE101"
    destination = course_dir / "_meta" / "toc.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"{\xff")

    with pytest.raises(A2LError, match="toc.json"):
        ingest_module._read_toc_modules(course_dir)


def test_assignment_richtext_is_sanitized_and_attachments_use_file_pipeline(
    tmp_path: Path,
) -> None:
    assignment = {
        "Id": 700001,
        "Name": "Problem Set 1",
        "DueDate": "2026-02-06T04:59:00.000Z",
        "Description": {
            "Html": (
                '<p>Read <a href="https://learn.example.test/instructions?signature=secret#frag">'
                "the prompt</a>.</p><script>alert('ignore')</script>"
                '<img src="https://evil.example/pixel?token=secret" onerror="steal()">'
            )
        },
        "Attachments": [
            {
                "Id": 900001,
                "FileName": "starter.pdf",
                "Url": "/content/enforced/111111-COURSE101/starter.pdf?signature=secret#frag",
                "Size": 17,
            },
            {
                "Id": 900002,
                "FileName": "publisher.pdf",
                "Url": "https://publisher.example/book.pdf?token=secret",
            },
        ],
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Assignment link", kind="Link"))},
        responses={"/dropbox/folders/": [assignment]},
    )
    vault = Vault(tmp_path)

    metadata = ingest_metadata(fake_client, vault, fake_client.school)
    course_dir = metadata.courses[0].directory
    instructions = course_dir / "assignments" / "Problem Set 1" / "instructions.html"
    instructions_md = instructions.with_suffix(".md")
    html = instructions.read_text(encoding="utf-8")
    assert "alert" not in html
    assert "onerror" not in html
    assert "secret" not in html
    assert "the prompt" in html
    assert instructions_md.is_file()
    assert (instructions.parent / "README.md").is_file()
    assert not any(
        "secret" in path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "discussion-hmac.key"
    )

    assignment_row = next(
        row
        for row in json.loads(
            (course_dir / "_meta" / "assignments.json").read_text(encoding="utf-8")
        )
        if row["id"] == 700001
    )
    assert assignment_row["instructions_html"].endswith("instructions.html")
    assert "secret" not in json.dumps(assignment_row)
    attachment_row = next(
        row for row in _topic_rows(tmp_path) if row["source_id"] == "700001-900001"
    )
    assert attachment_row["url_path"] == "/content/enforced/111111-COURSE101/starter.pdf"

    report = ingest_files(fake_client, vault, fake_client.school)
    assert report.downloaded == 1
    assert len(fake_client.download_calls) == 1
    index = (course_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "(content/Assignments/Problem Set 1/starter.pdf)" in index
    assert "(Winter 2026/COURSE101_1261/" not in index


def test_same_named_assignments_get_distinct_instruction_directories(tmp_path: Path) -> None:
    assignments = [
        {
            "Id": 700001,
            "Name": "Problem Set",
            "Description": {"Html": "<p>First prompt</p>"},
        },
        {
            "Id": 700002,
            "Name": "Problem Set",
            "Description": {"Html": "<p>Second prompt</p>"},
        },
    ]
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc()},
        responses={"/dropbox/folders/": assignments},
    )
    metadata = ingest_metadata(fake_client, Vault(tmp_path), fake_client.school)

    assignment_root = metadata.courses[0].directory / "assignments"
    instruction_paths = sorted(assignment_root.glob("*/instructions.html"))
    assert [path.parent.name for path in instruction_paths] == ["Problem Set", "Problem Set_2"]
    assert instruction_paths[0].read_text(encoding="utf-8") != instruction_paths[1].read_text(
        encoding="utf-8"
    )


def test_discussion_pseudonyms_are_vault_local_stable_and_permission_restricted(
    tmp_path: Path,
) -> None:
    forum = {
        "ForumId": 50001,
        "Name": "General Discussion",
        "Topics": [
            {
                "Posts": [
                    {
                        "PostId": 1,
                        "Author": {"Identifier": "student-1", "DisplayName": "Alice Example"},
                        "Body": {"Html": "<p>Hello from Alice Example</p>"},
                    },
                    {
                        "PostId": 2,
                        "Author": {"DisplayName": "Bob Example"},
                        "Body": {"Text": "Bob's post"},
                    },
                ]
            }
        ],
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Discussion link", kind="Link"))},
        responses={"/discussions/forums/": [forum]},
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)

    course_dir = next(tmp_path.rglob("content_map.json")).parent.parent
    discussion_path = course_dir / "_meta" / "discussions.json"
    first = discussion_path.read_text(encoding="utf-8")
    discussion_rows = json.loads(first)
    authors = [
        post["author"] for forum_row in discussion_rows for post in forum_row.get("posts", [])
    ]
    assert "student-1" not in first
    assert "Alice Example" not in authors
    assert "Bob Example" not in authors
    assert "author-" in first
    key_path = tmp_path / ".a2l" / "private" / "discussion-hmac.key"
    assert key_path.stat().st_size == 32
    if os.name != "nt":
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)
    assert discussion_path.read_text(encoding="utf-8") == first

    other_root = tmp_path / "other-vault"
    other_vault = Vault(other_root)
    ingest_metadata(fake_client, other_vault, fake_client.school)
    ingest_files(fake_client, other_vault, fake_client.school, include_discussions=True)
    other_discussion = next(other_root.rglob("discussions.json")).read_text(encoding="utf-8")
    assert other_discussion != first


def test_malformed_discussion_topics_preserve_previous_capture(tmp_path: Path) -> None:
    forum = {
        "ForumId": 50001,
        "Name": "General Discussion",
        "Topics": [{"Posts": [{"PostId": 1, "Body": {"Text": "Keep me"}}]}],
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Discussion link", kind="Link"))},
        responses={"/discussions/forums/": [forum]},
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)

    course_dir = next(tmp_path.rglob("content_map.json")).parent.parent
    discussion_path = course_dir / "_meta" / "discussions.json"
    original_bytes = discussion_path.read_bytes()

    fake_client.responses["/discussions/forums/"] = [
        {"ForumId": 50001, "Name": "General Discussion", "Topics": ["malformed topic"]}
    ]
    report = ingest_files(fake_client, vault, fake_client.school, include_discussions=True)

    assert discussion_path.read_bytes() == original_bytes
    assert "discussions: A2LError" in report.errors


def test_complete_discussion_refresh_merges_removed_posts_and_forums(tmp_path: Path) -> None:
    first_forum = {
        "ForumId": 50001,
        "Name": "General Discussion",
        "Topics": [
            {
                "Posts": [
                    {"PostId": 1, "Body": {"Text": "Keep this post"}},
                    {"PostId": 2, "Body": {"Text": "This one is still present"}},
                ]
            }
        ],
    }
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Discussion link", kind="Link"))},
        responses={"/discussions/forums/": [first_forum]},
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)

    course_dir = next(tmp_path.rglob("content_map.json")).parent.parent
    discussion_path = course_dir / "_meta" / "discussions.json"

    fake_client.responses["/discussions/forums/"] = [
        {
            "ForumId": 50001,
            "Name": "General Discussion",
            "Topics": [{"Posts": [{"PostId": 2, "Body": {"Text": "This one is still present"}}]}],
        }
    ]
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)
    rows = json.loads(discussion_path.read_text(encoding="utf-8"))
    posts = rows[0]["posts"]
    assert {post["id"] for post in posts} == {1, 2}
    removed = next(post for post in posts if post["id"] == 1)
    assert removed["missing_since"] is not None
    assert removed["withdrawn_at"] is None

    fake_client.responses["/discussions/forums/"] = []
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)
    ingest_files(fake_client, vault, fake_client.school, include_discussions=True)
    rows = json.loads(discussion_path.read_text(encoding="utf-8"))
    assert rows[0]["withdrawn_at"] is not None
    assert {post["id"] for post in rows[0]["posts"]} == {1, 2}


def test_discussion_pseudonym_collision_gets_deterministic_disambiguators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SameDigest:
        def hexdigest(self) -> str:
            return "a" * 64

    monkeypatch.setattr(ingest_module.hmac, "new", lambda *_args, **_kwargs: SameDigest())

    first = ingest_module._discussion_pseudonyms(b"k" * 32, {"id:one", "id:two"})
    second = ingest_module._discussion_pseudonyms(b"k" * 32, {"id:two", "id:one"})

    assert first == second
    assert len(set(first.values())) == 2
    assert all(value.startswith("author-aaaaaaaaaaaaaaaaaaaa-") for value in first.values())


def test_expired_news_is_retained_and_withdrawn_after_two_complete_absences(
    tmp_path: Path,
) -> None:
    topic = _topic(1, "Lecture")
    news = [
        {"Id": 1, "Title": "A", "Body": {"Text": "a"}, "StartDate": "2026-01-05T14:00:00.000Z"},
        {"Id": 2, "Title": "B", "Body": {"Text": "b"}, "StartDate": "2026-01-12T14:00:00.000Z"},
        {"Id": 3, "Title": "C", "Body": {"Text": "c"}, "StartDate": "2026-01-19T14:00:00.000Z"},
    ]
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(topic)},
        responses={"/news/": news, "/quizzes/": {"Next": None, "Objects": []}},
    )
    vault = Vault(tmp_path)
    report = ingest_metadata(fake_client, vault, fake_client.school)
    news_path = report.courses[0].directory / "_meta" / "news.json"
    fake_client.responses["/news/"] = [news[0], news[2]]

    ingest_metadata(fake_client, vault, fake_client.school)
    first_absence = json.loads(news_path.read_text())
    retained = next(row for row in first_absence if row["id"] == 2)
    assert retained["missing_since"]
    assert retained["withdrawn_at"] is None

    ingest_metadata(fake_client, vault, fake_client.school)
    second_absence = json.loads(news_path.read_text())
    retained = next(row for row in second_absence if row["id"] == 2)
    assert {row["id"] for row in second_absence} == {1, 2, 3}
    assert retained["withdrawn_at"]
    assert (
        "No longer posted"
        in (report.courses[0].directory / "announcements" / "announcements.md").read_text()
    )


def test_reversed_toc_order_allocates_new_siblings_by_source_key(tmp_path: Path) -> None:
    topics = [_topic(2, "Same", filename="two.pdf"), _topic(1, "Same", filename="one.pdf")]
    fake_client = FakeClient([course()], tocs={111111: _toc(*topics)})
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)

    entries = vault.manifest()
    assert entries["uwaterloo:111111:topic:1"].path.casefold().endswith("same.pdf")
    assert entries["uwaterloo:111111:topic:2"].path.casefold().endswith("same_2.pdf")


def test_fetch_resolves_stable_id_and_repairs_a_path_null_topic(tmp_path: Path) -> None:
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Lecture"))},
        download_handler=_handler_for({"topic-1.pdf": b"fetched bytes"}),
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    result = fetch_topic(fake_client, vault, fake_client.school, "1")

    assert result.source_key == "uwaterloo:111111:topic:1"
    assert result.source_path is not None
    assert result.citation_path is None
    assert Vault(tmp_path).entry(result.source_key) is not None
    assert not list(tmp_path.rglob("*.part"))


def test_unknown_size_stays_metadata_only_until_confirmed_one_file_fetch(tmp_path: Path) -> None:
    unknown_size_topic = _topic(1, "Unknown size")
    unknown_size_topic.pop("Size")
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(unknown_size_topic)},
        download_handler=_handler_for({"topic-1.pdf": b"explicitly fetched"}),
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    report = ingest_files(fake_client, vault, fake_client.school)
    assert report.metadata_only == 1
    assert fake_client.download_calls == []

    with pytest.raises(Exception, match="unknown"):
        fetch_topic(fake_client, vault, fake_client.school, "1")

    confirmations: list[int | None] = []

    def confirm_large(size: int | None) -> bool:
        confirmations.append(size)
        return True

    result = fetch_topic(
        fake_client,
        vault,
        fake_client.school,
        "1",
        allow_large=True,
        confirm=confirm_large,
    )
    assert confirmations == [None]
    assert result.source_path is not None
    assert len(fake_client.download_calls) == 1


def test_allow_large_does_not_remove_ceiling_for_a_known_small_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Small source"))},
        download_handler=_handler_for({"topic-1.pdf": b"small bytes"}),
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    observed: list[int | None] = []
    real_ingest = ingest_module._ingest_one_topic

    def capture(*args: object, **kwargs: object) -> str:
        observed.append(kwargs.get("max_bytes"))  # type: ignore[arg-type]
        return real_ingest(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module, "_ingest_one_topic", capture)
    fetch_topic(
        fake_client,
        vault,
        fake_client.school,
        "1",
        allow_large=True,
        confirm=lambda _size: pytest.fail("small source must not ask for an override"),
    )

    assert observed == [2_147_483_648]


def test_fetch_rejects_licensed_topic_and_ambiguous_title(tmp_path: Path) -> None:
    external = {
        "TopicId": 8,
        "Title": "Publisher",
        "TypeIdentifier": "Link",
        "Url": "https://reader.vitalsource.com/book/8",
        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
        "IsBroken": False,
    }
    fake_client = FakeClient(
        [course(), course(222222, code="COURSE202")],
        tocs={111111: _toc(external, _topic(10, "Same")), 222222: _toc(_topic(9, "Same"))},
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)

    with pytest.raises(Exception, match="cannot be fetched"):
        fetch_topic(fake_client, vault, fake_client.school, "8")
    with pytest.raises(Exception, match="ambiguous"):
        fetch_topic(fake_client, vault, fake_client.school, "Same")


def test_download_route_candidates_fall_through_in_documented_order(tmp_path: Path) -> None:
    calls: list[str] = []

    def download(url: str, temp: Path, prior: object | None) -> DownloadResult:
        del prior
        calls.append(url)
        if len(calls) < 3:
            raise DownloadError("candidate unavailable")
        payload = b"route success"
        temp.write_bytes(payload)
        return DownloadResult(temp, sha256(payload).hexdigest(), len(payload), None, None, False)

    fake_client = FakeClient(
        [course()],
        tocs={111111: _toc(_topic(1, "Lecture"))},
        download_handler=download,
    )
    vault = Vault(tmp_path)
    ingest_metadata(fake_client, vault, fake_client.school)
    ingest_files(fake_client, vault, fake_client.school)

    assert len(calls) == 3
    assert "/topics/files/download/1/DirectFileTopicDownload" in calls[0]
    assert "/content/topics/1/file" in calls[1]


def test_trailing_dot_title_keeps_its_extension_on_every_python_version() -> None:
    """Python 3.14 reports '.' as the suffix of 'Reading list.'; 3.11 reports ''.

    Taken literally the lone dot looks like an extension, so the URL's real extension is
    never applied and the file lands with none at all. That produced a different vault on
    3.14 than on 3.11 — caught by the golden tree, invisible to every unit test here.
    """
    record = ingest_module.TopicRecord(
        source_key="uwaterloo:1:topic:2",
        source_id="2",
        topic_id=2,
        course_org_unit_id=1,
        course_code="C",
        course_name="C",
        term="1261",
        title="Reading list.",
        kind="File",
        module_path=("Week 1",),
        module_ids=(9,),
        view_url="https://learn.example.test/d2l/x",
        url_path="/content/enforced/1-C/reading.pdf",
        outline_url=None,
        external_host=None,
        etag=None,
        last_modified=None,
        is_broken=False,
    )

    assert ingest_module._topic_filename(record) == "Reading list..pdf"


def test_public_priority_planner_applies_the_same_200mb_budget_as_ingest() -> None:
    selected = course()
    rows = [
        ingest_module.TopicRecord(
            source_key=f"uwaterloo:111111:topic:{index}",
            source_id=str(index),
            topic_id=index,
            course_org_unit_id=111111,
            course_code=selected.code,
            course_name=selected.name,
            term=selected.term,
            title=title,
            kind="File",
            module_path=("Week 1",),
            module_ids=(1,),
            view_url="https://learn.example.test/d2l/home",
            outline_url=None,
            url_path=f"/content/{index}.pdf",
            external_host=None,
            etag=None,
            last_modified="2026-01-01T00:00:00Z",
            is_broken=False,
            remote_size=size,
        )
        for index, title, size in (
            (1, "Assignment brief", 120_000_000),
            (2, "Lecture notes", 100_000_000),
        )
    ]

    planned = ingest_module.select_priority_topics(rows)

    assert [topic.topic_id for topic in planned] == [1]
    assert sum(topic.remote_size or 0 for topic in planned) <= 200_000_000


def test_priority_planner_excludes_media_before_applying_document_budget() -> None:
    selected = course()

    def topic(index: int, title: str, size: int) -> ingest_module.TopicRecord:
        return ingest_module.TopicRecord(
            source_key=f"uwaterloo:111111:topic:{index}",
            source_id=str(index),
            topic_id=index,
            course_org_unit_id=111111,
            course_code=selected.code,
            course_name=selected.name,
            term=selected.term,
            title=title,
            kind="File",
            module_path=(),
            module_ids=(),
            view_url="https://learn.example.test/d2l/home",
            outline_url=None,
            url_path=f"/content/{title}",
            external_host=None,
            etag=None,
            last_modified="2026-01-01T00:00:00Z",
            is_broken=False,
            remote_size=size,
        )

    planned = ingest_module.select_priority_topics(
        [topic(1, "Assignment recording.mp4", 150_000_000), topic(2, "Notes.pdf", 100_000_000)],
        include_media=False,
    )

    assert [item.topic_id for item in planned] == [2]


def test_priority_planner_and_estimator_share_one_downloadable_predicate() -> None:
    selected = course()
    valid = ingest_module.TopicRecord(
        source_key="uwaterloo:111111:topic:1",
        source_id="1",
        topic_id=1,
        course_org_unit_id=111111,
        course_code=selected.code,
        course_name=selected.name,
        term=selected.term,
        title="Notes.pdf",
        kind="File",
        module_path=(),
        module_ids=(),
        view_url="https://learn.example.test/d2l/home",
        outline_url=None,
        url_path="/content/notes.pdf",
        external_host=None,
        etag=None,
        last_modified="2026-01-01T00:00:00Z",
        is_broken=False,
        remote_size=100,
    )
    rows = [
        valid,
        replace(valid, source_key="k:2", source_id="2", topic_id=2, availability="external_link"),
        replace(valid, source_key="k:3", source_id="3", topic_id=3, url_path=None),
        replace(valid, source_key="k:4", source_id="4", topic_id=4, kind="Link"),
        replace(valid, source_key="k:5", source_id="5", topic_id=5, is_broken=True),
        replace(valid, source_key="k:6", source_id="6", topic_id=6, title="~$draft.docx"),
        replace(valid, source_key="k:7", source_id="7", topic_id=7, title="recording.mp4"),
    ]

    planned = ingest_module.select_priority_topics(rows, include_media=False)

    assert planned == (valid,)
    assert [ingest_module.is_downloadable_topic(row, include_media=False) for row in rows] == [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    ]


def test_load_metadata_report_reconstructs_completed_local_metadata_without_network(
    tmp_path: Path,
) -> None:
    selected = course()
    client = FakeClient([selected], tocs={111111: _toc(_topic(1, "Reading"))})
    vault = Vault(tmp_path)
    original = ingest_metadata(client, vault, client.school)
    client.json_calls.clear()

    loaded = ingest_module.load_metadata_report(vault, client.school, [selected])

    assert client.json_calls == []
    assert loaded.topic_count == original.topic_count
    assert loaded.deadline_count == original.deadline_count
    assert [item.course.org_unit_id for item in loaded.courses] == [111111]
    assert loaded.courses[0].topics == original.courses[0].topics


def test_split_name_inserts_a_collision_suffix_before_the_real_extension() -> None:
    assert ingest_module._split_name("Reading list..pdf") == ("Reading list.", ".pdf")
    assert ingest_module._split_name("Reading list.") == ("Reading list.", "")
    assert ingest_module._split_name("plain") == ("plain", "")
