# ruff: noqa: E501
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from agent2learn.index import reconcile_content_map, write_course_index, write_submission_readme
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


def test_content_map_represents_each_coverage_state_without_offering_external_fetch(
    tmp_path: Path,
) -> None:
    """Collapsing coverage to missing or offering a fetch for an external link is a bug."""
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
    assert resolved["12"]["availability"] == "unsupported_format"
    assert resolved["13"]["availability"] == "integrity_gap"
    assert resolved["14"]["availability"] == "external_link"
    assert "fetch" not in str(resolved["14"]["next_action"]).casefold()


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
