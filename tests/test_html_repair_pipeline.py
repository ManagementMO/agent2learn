"""A legacy HTML bundle stays non-citable through the real pipeline until direct repair.

All sources, metadata, HTTP responses, and machine state are synthetic and local. The seed is
authored as pre-upgrade manifest/twin state, not produced by the converter under test.
"""

from __future__ import annotations

import zipfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from test_html_document_routes import ANNOTATION, HTML, KEY, MARKDOWN, MODIFIED, SOURCE, _HtmlCourse
from test_html_document_routes import html_course as html_course

from agent2learn import index as course_index
from agent2learn.api import DownloadError
from agent2learn.audit import audit_vault
from agent2learn.convert import convert_vault
from agent2learn.ground import verified_sources
from agent2learn.ingest import fetch_topic
from agent2learn.pipeline import run_pipeline
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault


def _legacy_source(
    h: _HtmlCourse,
    *,
    edited: bool,
    validators: bool,
    tool: str = "html-sanitizer",
    local_name: str | None = None,
) -> ManifestEntry:
    if validators:
        h.topic["LastModifiedDate"] = MODIFIED
    h.prepare()
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    source = course / "content" / "Week 1" / (local_name or Path(h.source_path).name)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(h.bundle)
    twin = source.with_suffix(".md")
    twin.write_bytes(ANNOTATION if edited else MARKDOWN)
    entry = ManifestEntry(
        path=source.relative_to(h.vault.root).as_posix(),
        sha256=sha256(h.bundle).hexdigest(),
        source_id="1",
        etag=None,
        last_modified=MODIFIED if validators else None,
        size=len(h.bundle),
        fetched_at=MODIFIED,
        derived={
            "markdown": DerivedArtifact(
                path=twin.relative_to(h.vault.root).as_posix(),
                sha256=sha256(MARKDOWN).hexdigest(),
                source_sha256=sha256(h.bundle).hexdigest(),
                tool=tool,
                tool_version="1",
                created_at=MODIFIED,
                page_coverage=({"page": 1, "mode": "html", "words": 9, "warning": None},),
            )
        },
    )
    h.vault.mark(KEY, entry)
    h.vault.save_manifest()
    h.rewrite_row(
        availability="markdown_ready",
        source_path=entry.path,
        path=entry.derived["markdown"].path,
        sha256=entry.sha256,
        source_sha256=entry.sha256,
        size=entry.size,
        next_action="ready for citation",
    )
    return entry


@pytest.mark.parametrize("edited", [False, True])
@pytest.mark.parametrize("validators", [False, True])
@pytest.mark.parametrize("failure", ["denied", "bundle", "304"])
@pytest.mark.parametrize("tool", ["html-sanitizer", "html-archive"])
def test_failed_html_repair_survives_full_pipeline_reload_and_later_success(
    html_course: _HtmlCourse,
    monkeypatch: pytest.MonkeyPatch,
    edited: bool,
    validators: bool,
    failure: str,
    tool: str,
) -> None:
    """Reconciliation/cache conversion must not re-admit a ZIP with matching/no validators."""
    h = html_course
    original = _legacy_source(h, edited=edited, validators=validators, tool=tool)
    source = h.vault.materialized(original)
    twin = h.vault.root / original.derived["markdown"].path
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    twin_bytes = twin.read_bytes()
    times = source.stat().st_mtime_ns, twin.stat().st_mtime_ns
    if failure == "denied":
        h.source_status, h.source_type = 403, "application/problem+json"
        h.source_bytes = b'{"title":"Not Authorized"}'
    elif failure == "bundle":
        h.source_bytes = h.bundle
    else:
        h.source_status = 304  # Unsolicited even though the repair sends no conditionals.

    archive_calls: list[str] = []
    real_probe, real_archive = zipfile.is_zipfile, zipfile.ZipFile

    def refuse_archive_inspection(*_args: object, **_kwargs: object) -> None:
        archive_calls.append("archive inspection")
        raise AssertionError("unrepaired HTML must stop before archive classification/conversion")

    monkeypatch.setattr(zipfile, "is_zipfile", refuse_archive_inspection)
    monkeypatch.setattr(zipfile, "ZipFile", refuse_archive_inspection)

    report = run_pipeline(h.client, h.vault, h.client.school, render_outlines=False)

    # First observable wrong boundary: the complete pipeline must leave this a download gap.
    assert h.rows()[0]["availability"] == "download_gap"
    assert report.metadata.courses[0].topics[0].availability == "download_gap"
    assert report.files.download_gaps == 1 and report.files.downloaded == 0
    assert report.conversion.converted == 0 and report.conversion.skipped == 0
    assert report.errors == () and report.exit_code == 0  # A recorded gap is not generally fatal.
    requests = [request for request, _response in h.server.log if request.path == SOURCE]
    assert len(requests) == 1
    assert "If-Modified-Since" not in requests[0].headers
    assert "If-None-Match" not in requests[0].headers

    def assert_unrepaired() -> None:
        row = h.rows()[0]
        assert row["availability"] == "download_gap" and row["path"] is None
        assert row["source_path"] == original.path
        assert "a2l fetch 1" in str(row["next_action"])
        assert course_index.reconcile_content_map(h.vault, [row]) == [row]
        assert verified_sources(h.vault, course) == ()
        assert audit_vault(h.vault)[0].citable == 0
        assert h.vault.entry(KEY) == original
        assert source.read_bytes() == h.bundle and twin.read_bytes() == twin_bytes
        assert (source.stat().st_mtime_ns, twin.stat().st_mtime_ns) == times
        assert not list(h.vault.history_bucket(KEY).glob("*/revision.json"))
        assert archive_calls == []

    assert_unrepaired()
    snapshot = (h.vault.root / report.snapshot_path).read_text(encoding="utf-8")
    assert "My local annotation" not in snapshot and "Use the source document" not in snapshot

    # Exercise a fresh manifest load, real metadata merge and conversion, with downloads deferred.
    h.vault = Vault(h.vault.root)
    h.server.clear_log()
    deferred = run_pipeline(
        h.client, h.vault, h.client.school, render_outlines=False, download_files=False
    )
    assert deferred.errors == () and deferred.exit_code == 0
    assert SOURCE not in h.requests()
    assert_unrepaired()

    monkeypatch.setattr(zipfile, "is_zipfile", real_probe)
    monkeypatch.setattr(zipfile, "ZipFile", real_archive)
    h.source_status, h.source_type, h.source_bytes = 200, "text/html", HTML
    if validators:
        # HTTP representation validators need not equal the topic's metadata timestamp.
        h.source_headers = {"Last-Modified": "Mon, 12 Jan 2026 14:00:00 GMT"}
    recovered = run_pipeline(h.client, h.vault, h.client.school, render_outlines=False)
    assert recovered.files.downloaded == 1 and recovered.files.download_gaps == 0
    assert recovered.errors == () and recovered.exit_code == 0
    current = h.vault.entry(KEY)
    assert current is not None and current.path == original.path
    assert source.read_bytes() == HTML
    assert (h.vault.root / current.derived["markdown"].path).read_bytes() == MARKDOWN
    assert h.rows()[0]["availability"] == "markdown_ready"
    assert len(verified_sources(Vault(h.vault.root), course)) == 1
    history = {p.read_bytes() for p in h.vault.history_bucket(KEY).rglob("*") if p.is_file()}
    assert h.bundle in history and twin_bytes in history
    row = h.rows()[0]
    assert course_index.reconcile_content_map(Vault(h.vault.root), [row]) == [row]


@pytest.mark.parametrize("reference", ["site.html.zip", "resources.zip"])
def test_actual_archive_file_topics_remain_convertible(
    html_course: _HtmlCourse, reference: str
) -> None:
    """ZIP magic alone is not an HTML-document repair policy."""
    h = html_course
    h.source_path = f"/content/enforced/111111-COURSE101/{reference}"
    h.topic["Url"] = h.source_path
    # A historical materialized filename must not override the current archive File URL.
    _legacy_source(h, edited=False, validators=True, local_name="former-title.html")

    report = run_pipeline(h.client, h.vault, h.client.school, render_outlines=False)

    assert report.files.skipped == 1 and report.files.download_gaps == 0
    assert h.rows()[0]["availability"] == "markdown_ready"
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    assert len(verified_sources(h.vault, course)) == 1


def test_disappearing_html_source_uses_existing_integrity_gap(
    html_course: _HtmlCourse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source removed after the bounded probe must not abort the conversion preflight."""
    h = html_course
    original = _legacy_source(h, edited=False, validators=True)
    source = h.vault.materialized(original)
    real_probe = course_index.has_zip_signature

    def remove_after_probe(path: Path) -> bool | None:
        result = real_probe(path)
        if result:
            source.unlink()  # Authored temporary fixture only; simulate a concurrent deletion.
        return result

    monkeypatch.setattr(course_index, "has_zip_signature", remove_after_probe)
    rows = course_index.reconcile_content_map(h.vault, h.rows())
    assert rows[0]["availability"] == "integrity_gap" and rows[0]["path"] is None


@pytest.mark.parametrize("failure", ["denied", "304", "bundle"])
@pytest.mark.parametrize("edited", [False, True])
def test_explicit_fetch_persists_repair_gap_before_a_failed_request(
    html_course: _HtmlCourse, failure: str, edited: bool
) -> None:
    """Fetch has no preceding metadata phase to revoke an old ready map."""
    h = html_course
    original = _legacy_source(h, edited=edited, validators=True)
    source = h.vault.materialized(original)
    twin = h.vault.root / original.derived["markdown"].path
    twin_bytes = twin.read_bytes()
    times = source.stat().st_mtime_ns, twin.stat().st_mtime_ns
    if failure == "bundle":
        h.source_bytes = h.bundle
    else:
        h.source_status = 304 if failure == "304" else 403
        h.source_type = "application/problem+json"
        h.source_bytes = b'{"title":"Not Authorized"}'

    with pytest.raises(DownloadError):
        fetch_topic(h.client, h.vault, h.client.school, "1")

    assert h.rows()[0]["availability"] == "download_gap" and h.rows()[0]["path"] is None
    h.vault = Vault(h.vault.root)
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    assert verified_sources(h.vault, course) == ()
    assert h.vault.entry(KEY) == original
    assert source.read_bytes() == h.bundle and twin.read_bytes() == twin_bytes
    assert (source.stat().st_mtime_ns, twin.stat().st_mtime_ns) == times


def test_grounding_rejects_legacy_ready_html_bundle_without_prior_sync(
    html_course: _HtmlCourse,
) -> None:
    """A read-only consumer must not require a prior mutating sync to apply eligibility."""
    h = html_course
    _legacy_source(h, edited=False, validators=True)
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    before = (course / "_meta" / "content_map.json").read_bytes()

    assert verified_sources(Vault(h.vault.root), course) == ()
    assert (course / "_meta" / "content_map.json").read_bytes() == before


@pytest.mark.parametrize("availability", ["markdown_ready", "download_gap"])
def test_hardlinked_html_source_cannot_clear_gap_or_write_twins(
    html_course: _HtmlCourse, availability: str
) -> None:
    """An unsafe header probe is unknown, not confirmation that the source is non-ZIP."""
    h = html_course
    original = _legacy_source(h, edited=False, validators=True)
    source = h.vault.materialized(original)
    alias = h.vault.root / "synthetic-hardlink"
    alias.hardlink_to(source)
    h.rewrite_row(availability=availability)
    twin = h.vault.root / original.derived["markdown"].path
    times = source.stat().st_mtime_ns, twin.stat().st_mtime_ns
    course = next(h.vault.root.rglob("content_map.json")).parent.parent

    rows = course_index.reconcile_content_map(h.vault, h.rows())
    assert rows[0]["availability"] == "download_gap" and rows[0]["path"] is None
    assert verified_sources(h.vault, course) == ()  # Also reject the still-unreconciled old map.
    report = convert_vault(h.vault)
    assert report.converted == report.skipped == 0
    with pytest.raises(DownloadError):
        fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.requests() == []
    assert source.read_bytes() == alias.read_bytes() == h.bundle
    assert twin.read_bytes() == MARKDOWN
    assert (source.stat().st_mtime_ns, twin.stat().st_mtime_ns) == times
    assert h.vault.entry(KEY) == original
    assert not list(h.vault.history_bucket(KEY).glob("*/revision.json"))


@pytest.mark.parametrize("consumer", ["reconcile", "ground", "convert"])
def test_recorded_size_mismatch_cannot_readmit_a_hash_verified_html_bundle(
    html_course: _HtmlCourse, consumer: str
) -> None:
    """A wrong recorded size does not turn captured ZIP bytes into an HTML document."""
    h = html_course
    original = _legacy_source(h, edited=False, validators=True)
    mismatched = replace(original, size=original.size + 1)
    h.vault.mark(KEY, mismatched)
    h.vault.save_manifest()
    h.vault = Vault(h.vault.root)
    source = h.vault.materialized(mismatched)
    twin = h.vault.root / mismatched.derived["markdown"].path
    course = next(h.vault.root.rglob("content_map.json")).parent.parent
    times = source.stat().st_mtime_ns, twin.stat().st_mtime_ns
    assert sha256(source.read_bytes()).hexdigest() == mismatched.sha256
    assert source.stat().st_size + 1 == mismatched.size

    if consumer == "reconcile":
        rows = course_index.reconcile_content_map(h.vault, h.rows())
        assert rows[0]["availability"] == "download_gap" and rows[0]["path"] is None
    elif consumer == "ground":
        assert verified_sources(h.vault, course) == ()
    else:
        report = convert_vault(h.vault)
        assert report.converted == report.skipped == 0
        assert h.rows()[0]["availability"] in {"download_gap", "integrity_gap"}
        assert h.rows()[0]["path"] is None
        assert verified_sources(h.vault, course) == ()

    assert h.vault.entry(KEY) == mismatched
    assert source.read_bytes() == h.bundle and twin.read_bytes() == MARKDOWN
    assert (source.stat().st_mtime_ns, twin.stat().st_mtime_ns) == times
    assert not list(h.vault.history_bucket(KEY).glob("*/revision.json"))
