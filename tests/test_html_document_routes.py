"""HTML topics archive their source document, without downloading asset bundles.

Only authored metadata, an empty in-memory cookie jar, a loopback HTTP server, and temporary
machine/vault state are used. No live course data or saved session is needed.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import shutil
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit

import pytest
import requests
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from agent2learn import api, config
from agent2learn.calibrate import CourseRef
from agent2learn.convert import convert_vault
from agent2learn.errors import A2LError, SessionExpired
from agent2learn.ingest import fetch_topic, ingest_files, ingest_metadata
from agent2learn.schools.uwaterloo import UWaterloo
from agent2learn.session import Session
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

SOURCE = "/content/enforced/111111-COURSE101/lesson.html"
UI_ROUTE = "/d2l/le/content/111111/topics/files/download/1/DirectFileTopicDownload"
API_ROUTE = "/d2l/api/le/1.96/111111/content/topics/1/file"
CALIBRATED_ROUTE = "/calibrated/111111/1"
KEY = "uwaterloo:111111:topic:1"
HTML = (
    b"<!doctype html><html><body><h1>Synthetic lesson</h1>"
    b"<p>Use the source document.</p><p><a href='reference.pdf'>Reference PDF</a></p>"
    b"<video src='recording.mp4'></video><img src='figure.png'>"
    b"<script src='active.js'></script></body></html>"
)
MARKDOWN = b"# Synthetic lesson\n\nUse the source document.\n\n[Reference PDF](reference.pdf)\n"
MODIFIED = "2026-01-12T14:00:00Z"
ANNOTATION = b"My local annotation on the old bundle\n"


@dataclass
class _LocalSession:
    """The real client gets no saved authentication, even if isolation fixtures change."""

    base_url: str
    xsrf: str | None = None

    def requests_cookies(self) -> requests.cookies.RequestsCookieJar:
        return requests.cookies.RequestsCookieJar()


class _LocalClient(api.Client):
    courses = [CourseRef(111111, "COURSE101", "Synthetic Course", "1261", True)]


@dataclass
class _HtmlCourse:
    server: HTTPServer
    client: _LocalClient
    vault: Vault
    bundle: bytes
    source_path: str = SOURCE
    source_bytes: bytes = HTML
    source_status: int = 200
    source_headers: dict[str, str] = field(default_factory=dict)
    source_type: str = "text/html"
    conditional_304: bool = False
    route_responses: dict[str, tuple[bytes, int, str]] = field(default_factory=dict)
    topic: dict[str, object] = field(
        default_factory=lambda: {
            "TopicId": 1,
            "Title": "Synthetic lesson",
            "TypeIdentifier": "File",
            "Url": SOURCE,
            "IsBroken": False,
            # Size and remote validators are deliberately absent, as permitted by the API.
        }
    )

    def serve(self, request: Request) -> Response:
        if request.path in self.route_responses:
            payload, status, content_type = self.route_responses[request.path]
            return Response(payload, status=status, content_type=content_type)
        if request.path == "/d2l/api/le/1.96/111111/content/toc":
            return Response(
                json.dumps(
                    {
                        "Modules": [
                            {
                                "ModuleId": 1,
                                "Title": "Week 1",
                                "Modules": [],
                                "Topics": [self.topic],
                            }
                        ]
                    }
                ),
                content_type="application/json",
            )
        if request.path in {
            "/d2l/api/le/1.96/111111/dropbox/folders/",
            "/d2l/api/le/1.96/111111/news/",
            "/d2l/api/le/1.96/111111/quizzes/",
        }:
            return Response("[]", content_type="application/json")
        if request.path == self.source_path:
            if self.conditional_304 and (
                "If-Modified-Since" in request.headers or "If-None-Match" in request.headers
            ):
                return Response(status=304)
            return Response(
                self.source_bytes,
                status=self.source_status,
                headers=self.source_headers,
                content_type=self.source_type,
            )
        if request.path in {UI_ROUTE, API_ROUTE, CALIBRATED_ROUTE}:
            return Response(self.bundle, content_type="application/zip")
        return Response("unregistered synthetic resource", status=404, content_type="text/plain")

    def prepare(self) -> None:
        report = ingest_metadata(self.client, self.vault, self.client.school)
        assert report.errors == ()
        assert report.topic_count == 1
        self.server.clear_log()

    def rows(self) -> list[dict[str, object]]:
        maps = list(self.vault.root.rglob("content_map.json"))
        assert len(maps) == 1
        return cast(
            list[dict[str, object]], json.loads(maps[0].read_text(encoding="utf-8"))["topics"]
        )

    def requests(self) -> list[str]:
        return [request.path for request, _response in self.server.log]

    def rewrite_row(self, **changes: object) -> None:
        """Simulate malformed/stale cached metadata without changing the live TOC."""
        map_path = next(self.vault.root.rglob("content_map.json"))
        raw = json.loads(map_path.read_text(encoding="utf-8"))
        raw["topics"][0].update(changes)
        map_path.write_text(json.dumps(raw), encoding="utf-8")


@pytest.fixture
def html_course(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_HtmlCourse]:
    monkeypatch.setattr(
        config,
        "DIRS",
        SimpleNamespace(
            user_config_path=tmp_path / "config",
            user_state_path=tmp_path / "state",
            user_data_path=tmp_path / "data",
            user_log_path=tmp_path / "logs",
        ),
    )
    monkeypatch.setattr(api, "THROTTLE", 0)
    monkeypatch.setattr(api, "JITTER_MAX", 0)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("index.html", HTML)
        archive.writestr("reference.pdf", b"synthetic embedded PDF resource")
        archive.writestr("recording.mp4", b"synthetic embedded media" * 16)
    with HTTPServer(host="127.0.0.1") as server:
        school = UWaterloo()
        school.base_url = server.url_for("").rstrip("/")
        client = _LocalClient(school, cast(Session, _LocalSession(school.base_url)))
        client.lp_version, client.le_version = "1.62", "1.96"
        fixture = _HtmlCourse(server, client, Vault(tmp_path / "vault"), payload.getvalue())
        server.expect_request(re.compile(".*")).respond_with_handler(fixture.serve)
        try:
            yield fixture
        finally:
            client._transport.close()


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize("calibrated", [False, True])
def test_html_archives_exact_document_and_twin_without_bundle_or_asset_requests(
    html_course: _HtmlCourse, operation: str, calibrated: bool
) -> None:
    """Preferring a download route would archive ZIP/media bytes as the HTML source."""
    h = html_course
    if calibrated:
        h.client.download_template = "{base}/calibrated/{ou}/{tid}"
    h.prepare()
    assert h.rows()[0]["remote_size"] is None

    if operation == "bulk":
        report = ingest_files(h.client, h.vault, h.client.school, include_media=False)
        assert report.downloaded == 1
        assert report.download_gaps == 0
    else:
        fetched = fetch_topic(h.client, h.vault, h.client.school, "1")
        assert fetched.availability == "markdown_ready"
    entry = h.vault.entry(KEY)
    assert entry is not None
    assert h.vault.materialized(entry).read_bytes() == HTML
    assert entry.sha256 == sha256(HTML).hexdigest()
    assert entry.size == len(HTML)
    if operation == "bulk":
        assert convert_vault(h.vault).converted == 1
    entry = h.vault.entry(KEY)
    assert entry is not None
    twin = entry.derived["markdown"]
    assert (h.vault.root / twin.path).read_bytes() == MARKDOWN
    assert twin.source_sha256 == entry.sha256
    assert twin.sha256 == sha256(MARKDOWN).hexdigest()
    assert h.rows()[0]["availability"] == "markdown_ready"
    assert set(h.vault.manifest()) == {KEY}
    assert h.requests() == [SOURCE]
    assert not list(h.vault.root.rglob("*.mp4"))
    assert not list(h.vault.root.rglob("*.pdf"))


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize(
    "kind,source",
    [
        ("File", "/content/enforced/111111-COURSE101/lesson.HTML?download=1#part"),
        ("File", "/content/enforced/111111-COURSE101/lesson.HtM?download=1"),
        ("HTML", "/content/enforced/111111-COURSE101/document"),
        ("HTMLFile", "/content/enforced/111111-COURSE101/document"),
    ],
)
def test_html_path_and_type_recognition_survive_cached_queries(
    html_course: _HtmlCourse, operation: str, kind: str, source: str
) -> None:
    """A suffix check on the whole URL would choose ZIP or mistake HTML for a login page."""
    h = html_course
    h.source_path = urlsplit(source).path
    h.topic.update(TypeIdentifier=kind, Url=h.client.school.base_url + source)
    h.prepare()
    assert h.rows()[0]["url_path"] == h.source_path
    h.rewrite_row(url_path=source)
    if operation == "bulk":
        assert ingest_files(h.client, h.vault, h.client.school).downloaded == 1
    else:
        assert fetch_topic(h.client, h.vault, h.client.school, "1").availability == "markdown_ready"
    entry = h.vault.entry(KEY)
    assert entry is not None
    assert h.vault.materialized(entry).read_bytes() == HTML
    assert h.requests() == [h.source_path]
    assert all(not request.query_string for request, _response in h.server.log)


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize(
    "status,content_type,body,expired",
    [
        (403, "application/problem+json", b'{"title":"Not Authorized"}', False),
        (404, "text/plain", b"not found", False),
        (403, "text/html", b"<html>Forbidden</html>", True),
        (
            200,
            "text/html",
            b"<html><title>Sign in</title><form action='/login'></form></html>",
            True,
        ),
    ],
)
def test_denied_or_expired_html_never_tries_an_alternate_bundle_route(
    html_course: _HtmlCourse,
    operation: str,
    status: int,
    content_type: str,
    body: bytes,
    expired: bool,
) -> None:
    """Even a successful alternate ZIP must never conceal a denied or expired source."""
    h = html_course
    h.source_status, h.source_type, h.source_bytes = status, content_type, body
    h.client.download_template = "{base}/calibrated/{ou}/{tid}"
    h.prepare()

    if operation == "bulk" and not expired:
        report = ingest_files(h.client, h.vault, h.client.school)
        assert report.downloaded == 0
        assert report.download_gaps == 1
        assert h.rows()[0]["availability"] == "download_gap"
    else:
        with pytest.raises(SessionExpired if expired else api.DownloadError):
            if operation == "bulk":
                ingest_files(h.client, h.vault, h.client.school)
            else:
                fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.requests() == [SOURCE]
    assert h.vault.manifest() == {}
    assert not list(h.vault.root.rglob("*.part"))
    assert h.rows()[0]["path"] is None


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        None,
        "",
        "https://external.invalid/lesson.html",
        "//external.invalid/lesson.html",
        "https://[malformed/lesson.html",
        "{base}/bad\\lesson.html",
        "{base}/bad\nlesson.html",
        "{base}/lesson.html\x00",
        "http://name:password@127.0.0.1/lesson.html",  # pragma: allowlist secret - synthetic URL
        "javascript:lesson.html",
        "{base}:invalid/lesson.html",
        "{base}/d2l/lms/quicklink/quicklink.d2l?file=lesson.html",
    ],
)
def test_unusable_html_sources_fail_closed_even_in_cached_maps(
    html_course: _HtmlCourse,
    operation: str,
    cached: bool,
    source: str | None,
) -> None:
    """A missing/unvetted source must not be laundered into a first-party ZIP fallback."""
    h = html_course
    value = source.replace("{base}", h.client.school.base_url) if source is not None else None
    h.topic["TypeIdentifier"] = "HTML"
    if not cached:
        h.topic["Url"] = value
    h.prepare()
    if cached:
        h.rewrite_row(url_path=value)
    if operation == "bulk":
        try:
            report = ingest_files(h.client, h.vault, h.client.school)
        except A2LError:
            # Invalid cached structure can refuse the operation rather than a single source.
            pass
        else:
            assert report.downloaded == 0
            assert h.rows()[0]["availability"] in {"metadata_only", "external_link", "download_gap"}
    else:
        with pytest.raises(A2LError):
            fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.requests() == []
    assert h.vault.manifest() == {}
    assert not list(h.vault.root.rglob("*.part"))


@pytest.mark.parametrize("success_at", [0, 1, 2, 3])
def test_non_html_routes_keep_calibrated_ui_api_source_fallback(
    html_course: _HtmlCourse,
    success_at: int,
) -> None:
    """The HTML correction must not change the documented four-route binary/text order."""
    h = html_course
    h.topic["Url"] = "/content/enforced/111111-COURSE101/notes.txt?name=lesson.html"
    h.source_path = "/content/enforced/111111-COURSE101/notes.txt"
    h.client.download_template = "{base}/calibrated/{ou}/{tid}"
    routes = [CALIBRATED_ROUTE, UI_ROUTE, API_ROUTE, h.source_path]
    for position, route in enumerate(routes):
        h.route_responses[route] = (
            (b"first successful source", 200, "text/plain")
            if position == success_at
            else (b"not found", 404, "text/plain")
        )
    h.prepare()
    report = ingest_files(h.client, h.vault, h.client.school)
    assert report.downloaded == 1
    entry = h.vault.entry(KEY)
    assert entry is not None
    assert h.vault.materialized(entry).read_bytes() == b"first successful source"
    assert h.requests() == routes[: success_at + 1]


def test_html_repeat_keeps_source_identity_and_preserves_replaced_bytes(
    html_course: _HtmlCourse,
) -> None:
    """Changing the source URL/title for the same ID must not discard old source/twin bytes."""
    h = html_course
    h.prepare()
    fetch_topic(h.client, h.vault, h.client.school, "1")
    original = h.vault.entry(KEY)
    assert original is not None
    assert h.vault.materialized(original).read_bytes() == HTML
    twin = original.derived["markdown"]
    twin_path = h.vault.root / twin.path
    twin_time = twin_path.stat().st_mtime_ns
    h.server.clear_log()
    fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.requests() == [SOURCE]  # No validators: revalidate through the document route.
    assert twin_path.stat().st_mtime_ns == twin_time
    assert twin_path.read_bytes() == MARKDOWN

    twin_path.write_bytes(b"My local annotation\n")
    h.source_path = "/content/enforced/111111-COURSE101/revised.html"
    h.source_bytes = b"<html><h1>Revised lesson</h1></html>"
    h.topic.update(Url=h.source_path, Title="Renamed lesson")
    h.prepare()
    fetch_topic(h.client, h.vault, h.client.school, "1")
    current = h.vault.entry(KEY)
    assert current is not None
    assert current.path == original.path
    assert h.vault.materialized(current).read_bytes() == h.source_bytes
    assert (h.vault.root / current.derived["markdown"].path).read_bytes() == b"# Revised lesson\n"
    history = [p.read_bytes() for p in h.vault.history_bucket(KEY).rglob("*") if p.is_file()]
    assert HTML in history
    assert b"My local annotation\n" in history
    assert set(h.vault.manifest()) == {KEY}
    assert h.requests() == [h.source_path]


@pytest.mark.parametrize("cached", [False, True])
def test_html_source_must_keep_the_configured_origin_scheme(
    html_course: _HtmlCourse,
    cached: bool,
) -> None:
    """Projecting an off-origin URL to a local path must not launder a different scheme."""
    h = html_course
    foreign = h.client.school.base_url.replace("http://", "https://") + SOURCE
    if not cached:
        h.topic["Url"] = foreign
    h.prepare()
    if cached:
        h.rewrite_row(url_path=foreign)
    report = ingest_files(h.client, h.vault, h.client.school)
    assert report.downloaded == 0
    assert h.requests() == []
    assert h.vault.manifest() == {}


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
def test_html_streaming_ceiling_cannot_fall_back_or_be_implicitly_unbounded(
    html_course: _HtmlCourse,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Exercise the real byte ceiling with a small test cap while checking caller consent."""
    h = html_course
    # The wire body fits the cap; decoded HTML crosses it during iteration. This catches a
    # missing streaming check even when the advertised Content-Length preflight still works.
    h.source_bytes = gzip.compress(b"<html><p>" + b"x" * 1024 + b"</p></html>")
    h.source_headers = {"Content-Encoding": "gzip"}
    assert len(h.source_bytes) < 64
    h.prepare()
    limits: list[int | None] = []
    real_download = api.Client.download

    def small_ceiling(
        client: api.Client,
        url: str,
        temp: Path,
        *,
        prior: ManifestEntry | None = None,
        max_bytes: int | None = api.DEFAULT_MAX_BYTES,
        is_html_topic: bool = False,
        root: Path | None = None,
    ) -> api.DownloadResult:
        limits.append(max_bytes)
        return real_download(
            client,
            url,
            temp,
            prior=prior,
            max_bytes=64 if max_bytes is not None else None,
            is_html_topic=is_html_topic,
            root=root,
        )

    monkeypatch.setattr(_LocalClient, "download", small_ceiling)
    if operation == "bulk":
        report = ingest_files(h.client, h.vault, h.client.school)
        assert report.downloaded == 0
        assert report.metadata_only == 1
        assert h.rows()[0]["next_action"] == "a2l fetch --allow-large 1"
    else:
        with pytest.raises(api.FileTooLarge):
            fetch_topic(h.client, h.vault, h.client.school, "1")
    assert limits == [2_147_483_648]
    assert h.requests() == [SOURCE]
    assert h.vault.manifest() == {}
    assert not list(h.vault.root.rglob("*.part"))


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
def test_html_download_retains_the_disk_reserve_stop(
    html_course: _HtmlCourse,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A successful bundle endpoint cannot bypass the document's disk refusal."""
    h = html_course
    h.prepare()
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    if operation == "bulk":
        report = ingest_files(h.client, h.vault, h.client.school)
        assert report.downloaded == 0
        assert report.failed == 1
        assert report.errors == ("download: DiskSpaceExhausted",)
    else:
        with pytest.raises(api.DiskSpaceExhausted):
            fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.requests() == [SOURCE]
    assert h.vault.manifest() == {}
    assert not list(h.vault.root.rglob("*.part"))


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
def test_denied_html_refresh_preserves_the_previous_source_and_twin(
    html_course: _HtmlCourse,
    operation: str,
) -> None:
    """An unavailable revision cannot replace the previously archived document with a ZIP."""
    h = html_course
    h.prepare()
    fetch_topic(h.client, h.vault, h.client.school, "1")
    old = h.vault.entry(KEY)
    assert old is not None
    h.source_status = 403
    h.source_type = "application/problem+json"
    h.source_bytes = b'{"title":"Not Authorized"}'
    h.server.clear_log()
    if operation == "bulk":
        assert ingest_files(h.client, h.vault, h.client.school).download_gaps == 1
    else:
        with pytest.raises(api.DownloadError):
            fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.vault.entry(KEY) == old
    assert h.vault.materialized(old).read_bytes() == HTML
    assert (h.vault.root / old.derived["markdown"].path).read_bytes() == MARKDOWN
    assert h.requests() == [SOURCE]
    assert not list(h.vault.root.rglob("*.part"))


def test_html_conditional_304_preserves_exact_source_and_twin(html_course: _HtmlCourse) -> None:
    """A repeated source with validators must retain its files through the real 304 path."""
    h = html_course
    h.source_headers = {"ETag": '"document-v1"'}
    h.prepare()
    fetch_topic(h.client, h.vault, h.client.school, "1")
    original = h.vault.entry(KEY)
    assert original is not None
    source_time = h.vault.materialized(original).stat().st_mtime_ns
    twin_path = h.vault.root / original.derived["markdown"].path
    twin_time = twin_path.stat().st_mtime_ns
    h.source_status = 304
    h.server.clear_log()
    result = fetch_topic(h.client, h.vault, h.client.school, "1")
    assert not result.changed
    assert h.vault.entry(KEY) == original
    assert h.vault.materialized(original).read_bytes() == HTML
    assert h.vault.materialized(original).stat().st_mtime_ns == source_time
    assert twin_path.read_bytes() == MARKDOWN
    assert twin_path.stat().st_mtime_ns == twin_time
    assert h.requests() == [SOURCE]
    assert h.server.log[0][0].headers["If-None-Match"] == '"document-v1"'


def _seed_owned_source(h: _HtmlCourse, payload: bytes, *, edited: bool = True) -> ManifestEntry:
    """Author installed-0.1.5 source/twin state without invoking the new repair policy."""
    h.topic["LastModifiedDate"] = MODIFIED
    h.prepare()
    course_dir = next(h.vault.root.rglob("content_map.json")).parent.parent
    source = course_dir / "content" / "Week 1" / Path(h.source_path).name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    twin = source.with_suffix(".md")
    twin.write_bytes(MARKDOWN)
    h.vault.mark(
        KEY,
        ManifestEntry(
            path=source.relative_to(h.vault.root).as_posix(),
            sha256=sha256(payload).hexdigest(),
            source_id="1",
            etag=None,
            last_modified=MODIFIED,
            size=len(payload),
            fetched_at=MODIFIED,
            derived={
                "markdown": DerivedArtifact(
                    path=twin.relative_to(h.vault.root).as_posix(),
                    sha256=sha256(MARKDOWN).hexdigest(),
                    source_sha256=sha256(payload).hexdigest(),
                    tool="html-sanitizer",
                    tool_version="1",
                    created_at=MODIFIED,
                    page_coverage=({"page": 1, "mode": "html", "words": 9, "warning": None},),
                )
            },
        ),
    )
    h.vault.save_manifest()
    original = h.vault.entry(KEY)
    assert original is not None
    assert original.last_modified == h.rows()[0]["last_modified"] == MODIFIED
    assert original.etag is None
    twin = h.vault.root / original.derived["markdown"].path
    assert twin.read_bytes() == MARKDOWN
    if edited:
        twin.write_bytes(ANNOTATION)
    h.conditional_304 = True
    h.server.clear_log()
    return original


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
def test_legacy_html_zip_upgrade_replaces_matching_cache_revision_safely(
    html_course: _HtmlCourse, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Either unchanged-local or inherited conditionals would leave the old bundle installed."""
    h = html_course
    original = _seed_owned_source(h, h.bundle)

    def refuse_archive_inspection(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repair must not inspect or extract archive members")

    monkeypatch.setattr(zipfile, "ZipFile", refuse_archive_inspection)
    if operation == "bulk":
        ingest_files(h.client, h.vault, h.client.school, scope="all", include_media=False)
        convert_vault(h.vault)
    else:
        fetch_topic(h.client, h.vault, h.client.school, "1")

    current = h.vault.entry(KEY)
    assert current is not None
    assert h.vault.materialized(current).read_bytes() == HTML
    assert current.path == original.path
    assert current.sha256 == sha256(HTML).hexdigest()
    assert current.size == len(HTML)
    twin = current.derived["markdown"]
    assert (h.vault.root / twin.path).read_bytes() == MARKDOWN
    assert twin.source_sha256 == current.sha256
    assert set(h.vault.manifest()) == {KEY}
    assert h.requests() == [SOURCE]
    request = h.server.log[0][0]
    assert "If-Modified-Since" not in request.headers
    assert "If-None-Match" not in request.headers
    history = {p.read_bytes() for p in h.vault.history_bucket(KEY).rglob("*") if p.is_file()}
    assert h.bundle in history
    assert ANNOTATION in history
    revisions = list(h.vault.history_bucket(KEY).glob("*/revision.json"))
    assert len(revisions) == 1
    assert json.loads(revisions[0].read_bytes())["derived"]["markdown"]["status"] == (
        "local-modification"
    )
    h.server.clear_log()
    assert not fetch_topic(h.client, h.vault, h.client.school, "1").changed
    assert h.requests() == []
    assert len(list(h.vault.history_bucket(KEY).glob("*/revision.json"))) == 1


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize("failure", ["denied", "expired", "size", "disk", "bundle"])
def test_legacy_html_zip_failed_repair_keeps_source_and_edited_twin(
    html_course: _HtmlCourse, monkeypatch: pytest.MonkeyPatch, operation: str, failure: str
) -> None:
    """A repair refusal must neither claim the old ZIP is current nor overwrite its artifacts."""
    h = html_course
    original = _seed_owned_source(h, h.bundle)
    source = h.vault.materialized(original)
    twin = h.vault.root / original.derived["markdown"].path
    times = source.stat().st_mtime_ns, twin.stat().st_mtime_ns
    error: type[A2LError] = api.DownloadError
    if failure == "denied":
        h.source_status, h.source_type = 403, "application/problem+json"
        h.source_bytes = b'{"title":"Not Authorized"}'
    elif failure == "expired":
        h.source_status = 403
        h.source_bytes = b"<html>Forbidden</html>"
        error = SessionExpired
    elif failure == "size":
        h.source_bytes = gzip.compress(b"<html><p>" + b"x" * 1024 + b"</p></html>")
        h.source_headers = {"Content-Encoding": "gzip"}
        real_download = h.client.download

        def small_ceiling(
            url: str,
            temp: Path,
            *,
            prior: ManifestEntry | None = None,
            max_bytes: int | None = api.DEFAULT_MAX_BYTES,
            is_html_topic: bool = False,
            root: Path | None = None,
        ) -> api.DownloadResult:
            assert max_bytes == 2_147_483_648
            return real_download(
                url, temp, prior=prior, max_bytes=64, is_html_topic=is_html_topic, root=root
            )

        monkeypatch.setattr(h.client, "download", small_ceiling)
        error = api.FileTooLarge
    elif failure == "disk":
        monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
        error = api.DiskSpaceExhausted
    else:
        h.source_bytes = h.bundle  # Even a text/html MIME label must not conceal a ZIP.

    if operation == "bulk" and failure != "expired":
        report = ingest_files(h.client, h.vault, h.client.school)
        assert report.downloaded == 0
        if failure == "size":
            assert report.metadata_only == 1
        elif failure == "disk":
            assert report.errors == ("download: DiskSpaceExhausted",)
        else:
            assert report.download_gaps == 1
            assert h.rows()[0]["availability"] == "download_gap"
    else:
        with pytest.raises(error):
            if operation == "bulk":
                ingest_files(h.client, h.vault, h.client.school)
            else:
                fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.vault.entry(KEY) == original
    assert source.read_bytes() == h.bundle
    assert twin.read_bytes() == ANNOTATION
    assert (source.stat().st_mtime_ns, twin.stat().st_mtime_ns) == times
    assert h.requests() == [SOURCE]
    assert not list(h.vault.history_bucket(KEY).glob("*/revision.json"))
    assert not list(h.vault.root.rglob("*.part*"))


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize("html", [False, True])
def test_matching_validator_keeps_healthy_html_and_non_html_zip_source_shortcuts(
    html_course: _HtmlCourse, operation: str, html: bool
) -> None:
    """Neither all ZIPs nor all HTML topics should be forced through a repair download."""
    h = html_course
    if not html:
        h.source_path = "/content/enforced/111111-COURSE101/resource.zip"
        h.topic["Url"] = h.source_path
    payload = HTML if html else h.bundle
    original = _seed_owned_source(h, payload, edited=False)
    source = h.vault.materialized(original)
    source_time = source.stat().st_mtime_ns
    h.source_status = 403
    if operation == "bulk":
        report = ingest_files(h.client, h.vault, h.client.school)
        assert report.skipped == 1
        assert report.downloaded == 0
    else:
        fetch_topic(h.client, h.vault, h.client.school, "1")
    assert source.read_bytes() == payload
    assert source.stat().st_mtime_ns == source_time
    assert h.requests() == []


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
def test_fresh_html_source_returning_zip_is_a_gap_before_install(
    html_course: _HtmlCourse, operation: str
) -> None:
    """The document endpoint is not permission to install a newly returned bundle."""
    h = html_course
    h.source_bytes = h.bundle
    h.prepare()
    if operation == "bulk":
        assert ingest_files(h.client, h.vault, h.client.school).download_gaps == 1
        assert h.rows()[0]["availability"] == "download_gap"
    else:
        with pytest.raises(api.DownloadError, match="bundle"):
            fetch_topic(h.client, h.vault, h.client.school, "1")
    assert h.vault.manifest() == {}
    assert h.requests() == [SOURCE]
    assert not list(h.vault.root.rglob("*.part*"))
    assert not list(h.vault.root.rglob("*.html"))


@pytest.mark.parametrize("operation", ["bulk", "fetch"])
@pytest.mark.parametrize("installed", [False, True])
def test_legacy_html_zip_pending_recovery_still_fetches_document(
    html_course: _HtmlCourse, operation: str, installed: bool
) -> None:
    """Neither a completed part nor a pre-manifest installed ZIP may return before repair."""
    h = html_course
    original = _seed_owned_source(h, h.bundle)
    destination = h.vault.materialized(original)
    # A real legacy journal, authored independently of the production journal writer.
    part = destination.with_name(f".{destination.name}.interrupted.part")
    if installed:
        # Initial install reached disk, but its manifest commit did not complete.
        manifest = h.vault.root / ".a2l" / "manifest.json"
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        raw["entries"] = {}
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        h.vault = Vault(h.vault.root)
    else:
        part.write_bytes(h.bundle)
    marker = part.with_name(part.name + ".meta.json")
    marker.write_text(
        json.dumps(
            {
                "version": 2,
                "source_key": KEY,
                "destination": original.path,
                "sha256": sha256(h.bundle).hexdigest(),
                "size": len(h.bundle),
                "etag": None,
                "last_modified": MODIFIED,
                "prior_sha256": None,
                "revision_preserved": True,
                "fetched_at": MODIFIED,
            }
        ),
        encoding="utf-8",
    )

    if operation == "bulk":
        ingest_files(h.client, h.vault, h.client.school)
        convert_vault(h.vault)
    else:
        fetch_topic(h.client, h.vault, h.client.school, "1")
    current = h.vault.entry(KEY)
    assert current is not None
    assert h.vault.materialized(current).read_bytes() == HTML
    assert current.path == original.path
    assert h.requests() == [SOURCE]
    assert h.bundle in {
        p.read_bytes() for p in h.vault.history_bucket(KEY).rglob("*") if p.is_file()
    }
    assert not list(h.vault.root.rglob("*.part*"))
