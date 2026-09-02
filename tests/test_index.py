# ruff: noqa: E501
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from agent2learn import ingest
from agent2learn.errors import A2LError
from agent2learn.index import (
    read_content_map,
    reconcile_content_map,
    write_course_index,
    write_submission_readme,
)
from agent2learn.schools.uwaterloo import UWaterloo
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault


def _entry(source: Path, twin: Path, key_id: str) -> ManifestEntry:
    source_bytes = b"source bytes"
    twin_bytes = b"# Current twin\n"
    source.write_bytes(source_bytes)
    twin.write_bytes(twin_bytes)
    source_hash = sha256(source_bytes).hexdigest()
    return ManifestEntry(
        path=source.relative_to(source.parents[4]).as_posix(),
        sha256=source_hash,
        source_id=key_id,
        etag=None,
        last_modified=None,
        size=len(source_bytes),
        fetched_at="2026-08-25T00:00:00Z",
        derived={
            "markdown": DerivedArtifact(
                path=twin.relative_to(twin.parents[4]).as_posix(),
                sha256=sha256(twin_bytes).hexdigest(),
                source_sha256=source_hash,
                tool="synthetic",
                tool_version="1",
                created_at="2026-08-25T00:00:00Z",
            )
        },
    )


def test_content_map_resolves_only_the_current_hash_verified_manifest_twin(tmp_path: Path) -> None:
    """Removing source-key/hash verification must make this fail, despite matching titles/files."""
    vault = Vault(tmp_path)
    course = tmp_path / "Spring 2026" / "CS101_1265"
    source = course / "content" / "Module" / "lecture.pdf"
    twin = source.with_suffix(".md")
    source.parent.mkdir(parents=True)
    entry = _entry(source, twin, "1")
    vault.mark("waterloo:1:topic:1", entry)
    vault.save_manifest()

    rows = [
        {
            "source_key": "waterloo:1:topic:1",
            "source_id": "1",
            "topic_id": 1,
            "title": "Lecture",
            "availability": "metadata_only",
            "source_path": None,
            "path": None,
        },
        {
            "source_key": "waterloo:1:topic:2",
            "source_id": "2",
            "topic_id": 2,
            "title": "Lecture",
            "availability": "metadata_only",
            "source_path": None,
            "path": None,
        },
    ]

    resolved = reconcile_content_map(vault, rows)

    assert resolved[0]["availability"] == "markdown_ready"
    assert resolved[0]["path"] == "Spring 2026/CS101_1265/content/Module/lecture.md"
    assert resolved[1]["availability"] == "metadata_only"
    assert resolved[1]["path"] is None
    assert resolved[1]["next_action"] == "a2l fetch 2"


def test_content_map_reports_malformed_utf8_as_a2l_error(tmp_path: Path) -> None:
    course = tmp_path / "Term" / "COURSE_1"
    metadata = course / "_meta"
    metadata.mkdir(parents=True)
    (metadata / "content_map.json").write_bytes(b"{\xff")

    with pytest.raises(A2LError, match="content_map.json is unreadable"):
        read_content_map(course)


def test_content_map_does_not_silently_drop_invalid_topic_items(tmp_path: Path) -> None:
    course = tmp_path / "Term" / "COURSE_1"
    metadata = course / "_meta"
    metadata.mkdir(parents=True)
    (metadata / "content_map.json").write_text(
        '{"schema_version": 1, "topics": [{"source_key": "ok"}, "lost row"]}',
        encoding="utf-8",
    )

    with pytest.raises(A2LError, match="invalid topic"):
        read_content_map(course)


def test_content_map_represents_each_coverage_state_without_offering_external_fetch(
    tmp_path: Path,
) -> None:
    """Only manifest-backed source states survive reconciliation; external links stay non-fetchable."""
    vault = Vault(tmp_path)
    source = tmp_path / "Term" / "COURSE_1" / "content" / "source.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    source_hash = sha256(b"source").hexdigest()
    vault.mark(
        "waterloo:1:topic:10",
        ManifestEntry(
            "Term/COURSE_1/content/source.pdf",
            source_hash,
            "10",
            None,
            None,
            6,
            "2026-08-25T00:00:00Z",
        ),
    )
    vault.save_manifest()
    rows = [
        {
            "source_key": "waterloo:1:topic:10",
            "source_id": "10",
            "topic_id": 10,
            "availability": "source_only",
        },
        {
            "source_key": "waterloo:1:topic:11",
            "source_id": "11",
            "topic_id": 11,
            "availability": "metadata_only",
        },
        {
            "source_key": "waterloo:1:topic:12",
            "source_id": "12",
            "topic_id": 12,
            "availability": "unsupported_format",
        },
        {
            "source_key": "waterloo:1:topic:13",
            "source_id": "13",
            "topic_id": 13,
            "availability": "integrity_gap",
        },
        {
            "source_key": "waterloo:1:topic:14",
            "source_id": "14",
            "topic_id": 14,
            "availability": "external_link",
            "stub_path": "Term/COURSE_1/content/link.url.txt",
        },
    ]

    resolved = {str(row["source_id"]): row for row in reconcile_content_map(vault, rows)}

    assert resolved["10"]["availability"] == "source_only"
    assert resolved["10"]["source_path"] == "Term/COURSE_1/content/source.pdf"
    assert resolved["11"]["availability"] == "metadata_only"
    assert resolved["11"]["next_action"] == "a2l fetch 11"
    assert resolved["12"]["availability"] == "metadata_only"
    assert resolved["12"]["next_action"] == "a2l fetch 12"
    assert resolved["13"]["availability"] == "metadata_only"
    assert resolved["13"]["next_action"] == "a2l fetch 13"
    assert resolved["14"]["availability"] == "external_link"
    assert "fetch" not in str(resolved["14"]["next_action"]).casefold()


def test_source_less_conversion_gap_is_reconciled_to_metadata_only(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    rows = [
        {
            "source_key": "waterloo:1:topic:15",
            "source_id": "15",
            "topic_id": 15,
            "availability": "conversion_gap",
            "source_path": "Term/COURSE_1/content/missing.pdf",
            "path": "Term/COURSE_1/content/missing.md",
            "next_action": "install Tesseract and retry conversion",
        }
    ]

    resolved = reconcile_content_map(vault, rows)

    assert resolved[0]["availability"] == "metadata_only"
    assert resolved[0]["source_path"] is None
    assert resolved[0]["path"] is None
    assert resolved[0]["next_action"] == "a2l fetch 15"


def test_download_gap_with_a_stale_manifest_revision_is_not_promoted(tmp_path: Path) -> None:
    """An older downloaded revision is not citation evidence for the revision that failed."""
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    source = course / "content" / "Module" / "notes.pdf"
    twin = source.with_suffix(".md")
    source.parent.mkdir(parents=True)
    entry = _entry(source, twin, "1")
    stale = ManifestEntry(
        path=entry.path,
        sha256=entry.sha256,
        source_id=entry.source_id,
        etag="old-revision",
        last_modified="Mon, 05 Jan 2026 14:00:00 GMT",
        size=entry.size,
        fetched_at=entry.fetched_at,
        derived=entry.derived,
    )
    vault.mark("waterloo:1:topic:1", stale)
    vault.save_manifest()
    rows = [
        {
            "source_key": "waterloo:1:topic:1",
            "source_id": "1",
            "topic_id": 1,
            "title": "Notes",
            "availability": "download_gap",
            "etag": "new-revision",
            "last_modified": "Tue, 06 Jan 2026 09:00:00 GMT",
            "next_action": "download failed (DownloadError); retry: a2l fetch 1",
        }
    ]

    resolved = reconcile_content_map(vault, rows)

    assert resolved[0]["availability"] == "download_gap"
    assert resolved[0]["path"] is None
    assert resolved[0]["next_action"] == "download failed (DownloadError); retry: a2l fetch 1"


def test_download_gap_for_the_current_manifest_revision_is_reconciled(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    course = tmp_path / "Term" / "COURSE_1"
    source = course / "content" / "Module" / "notes.pdf"
    twin = source.with_suffix(".md")
    source.parent.mkdir(parents=True)
    entry = _entry(source, twin, "1")
    vault.mark("waterloo:1:topic:1", entry)
    vault.save_manifest()
    rows = [
        {
            "source_key": "waterloo:1:topic:1",
            "source_id": "1",
            "topic_id": 1,
            "title": "Notes",
            "availability": "download_gap",
            "etag": None,
            "last_modified": None,
            "next_action": "download failed (DownloadError); retry: a2l fetch 1",
        }
    ]

    resolved = reconcile_content_map(vault, rows)

    assert resolved[0]["availability"] == "markdown_ready"
    assert resolved[0]["path"] == "Term/COURSE_1/content/Module/notes.md"


def test_index_and_submission_readme_use_vault_relative_posix_links_and_remove_empty_stub(
    tmp_path: Path,
) -> None:
    """Absolute/backslash links or a retained empty instruction stub break portable navigation."""
    course = tmp_path / "Term" / "COURSE_1"
    assignment = course / "assignments" / "Upload only"
    assignment.mkdir(parents=True)
    stub = assignment / "instructions.html"
    stub.write_text(" <br> \n", encoding="utf-8", newline="\n")
    write_submission_readme(
        assignment, title="Upload only", content_links=[("1", "content/Week 1/guide.md")]
    )
    write_course_index(
        course,
        course_code="COURSE",
        course_name="Course",
        term_label="Term",
        term_code="1",
        topics=[
            {
                "source_id": "1",
                "title": "Guide",
                "path": "Term/COURSE_1/content/Week 1/guide.md",
                "availability": "markdown_ready",
            }
        ],
    )

    assert not stub.is_file()
    readme = (assignment / "README.md").read_text(encoding="utf-8")
    assert "../../content/Week 1/guide.md" in readme
    index = (course / "INDEX.md").read_text(encoding="utf-8")
    assert "(content/Week 1/guide.md)" in index
    assert str(tmp_path) not in index
    assert "\\" not in index


def test_unchanged_source_path_never_retrusts_a_modified_markdown_twin(tmp_path: Path) -> None:
    """A manifest artifact record is not proof that the current twin bytes are still trusted."""
    vault = Vault(tmp_path)
    course_dir = tmp_path / "Term" / "COURSE_1"
    source = course_dir / "content" / "source.pdf"
    twin = course_dir / "content" / "source.md"
    source.parent.mkdir(parents=True)
    entry = _entry(source, twin, "1")
    vault.mark("waterloo:1:topic:1", entry)
    vault.save_manifest()
    twin.write_bytes(b"locally modified")
    (course_dir / "_meta").mkdir(parents=True)
    (course_dir / "_meta" / "content_map.json").write_text(
        '{"schema_version": 1, "topics": [{"source_key": "waterloo:1:topic:1", '
        '"source_id": "1", "topic_id": 1, "title": "Source", '
        '"availability": "source_only", "source_path": "Term/COURSE_1/content/source.pdf"}]}',
        encoding="utf-8",
        newline="\n",
    )
    topic = ingest.TopicRecord(
        source_key="waterloo:1:topic:1",
        source_id="1",
        topic_id=1,
        course_org_unit_id=1,
        course_code="COURSE_1",
        course_name="Course",
        term="1261",
        title="Source",
        kind="File",
        module_path=(),
        module_ids=(),
        view_url="https://learn.uwaterloo.ca/d2l/home/1",
        outline_url=None,
        url_path="/source.pdf",
        external_host=None,
        etag="etag",
        last_modified=None,
        is_broken=False,
    )

    ingest._mark_topic_source_only(vault, course_dir, topic, UWaterloo())

    rows = ingest._map_topics(ingest._read_content_map(course_dir))
    row = rows[0]
    assert isinstance(row, dict)
    assert row["availability"] == "integrity_gap"
    assert row["path"] is None
    assert row["next_action"] == "verify or re-fetch the source"


def test_unsupported_format_survives_a_complete_metadata_refresh() -> None:
    """A conversion gap must not become an ordinary source-only row on the next sync."""
    topic = ingest.TopicRecord(
        source_key="waterloo:1:topic:1",
        source_id="1",
        topic_id=1,
        course_org_unit_id=1,
        course_code="COURSE_1",
        course_name="Course",
        term="1261",
        title="Unsupported",
        kind="File",
        module_path=(),
        module_ids=(),
        view_url="https://learn.uwaterloo.ca/d2l/home/1",
        outline_url=None,
        url_path="/unsupported.xyz",
        external_host=None,
        etag=None,
        last_modified=None,
        is_broken=False,
    )
    merged = ingest._merge_topic_records(
        [
            {
                "source_key": topic.source_key,
                "source_id": "1",
                "topic_id": 1,
                "availability": "unsupported_format",
                "source_path": "Term/COURSE_1/content/unsupported.xyz",
                "next_action": "retry conversion",
            }
        ],
        [topic],
        complete=True,
    )

    assert merged[0]["availability"] == "unsupported_format"
    assert merged[0]["source_path"] == "Term/COURSE_1/content/unsupported.xyz"
    assert merged[0]["next_action"] == "retry conversion"
