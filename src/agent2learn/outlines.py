"""Bounded outline rendering through an already-owned local CDP connection.

This module never launches a browser and never reads the everyday browser profile.  The caller
hands it the dedicated-profile CDP transport established by authentication.  Every top-level and
subresource URL is checked at the request boundary; a blocked dependency makes the outline
unavailable instead of producing a false "no policy" conclusion.
"""

from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from agent2learn import aipolicy, clock, paths
from agent2learn import index as course_index
from agent2learn.ingest import (
    CourseMetadata,
    MetadataReport,
    OutlineReport,
    TopicRecord,
    _content_directory,
    _sanitize_richtext,
    _topic_from_row,
    _write_content_map,
    _write_index,
)
from agent2learn.schools import School, hostname_matches_suffix
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

OUTLINE_TIMEOUT_SECONDS = 30.0
OUTLINE_TOOL_VERSION = "1"
_OUTLINE_WORDS = re.compile(r"\b(?:outline|syllabus|course\s+schedule)\b", re.IGNORECASE)
_LOGIN_MARKERS = (
    re.compile(r"<title[^>]*>\s*(?:sign\s*in|log\s*in|login)", re.IGNORECASE),
    re.compile(r"<form[^>]+(?:action|id|class)=[^>]*(?:login|signin|d2l)", re.IGNORECASE),
)


@dataclass(frozen=True)
class OutlinePage:
    """A rendered DOM and the request audit returned by a CDP transport."""

    html: str
    canonical_url: str
    pdf: bytes | None = None
    subresources: tuple[str, ...] = ()
    top_level_requests: tuple[str, ...] = ()
    popups: tuple[str, ...] = ()


class OutlineBrowser(Protocol):
    """The narrow browser capability required by :func:`ingest_outlines`."""

    def render_outline(
        self,
        url: str,
        *,
        allowed_hosts: Sequence[str],
        timeout: float,
    ) -> OutlinePage | Mapping[str, object]:
        """Render one target and return the final DOM plus its request audit."""

    def close_target(self) -> None:
        """Close the one outline target before the next one is processed."""


def ingest_outlines(
    browser: OutlineBrowser,
    vault: Vault,
    school: School,
    metadata: MetadataReport,
) -> OutlineReport:
    """Render discovered outline topics after the metadata summary is available."""

    rendered = 0
    unavailable = 0
    errors: list[str] = []
    for course_metadata in metadata.courses:
        status_rows: list[dict[str, object]] = []
        for topic in _outline_topics(course_metadata.topics):
            url = _topic_outline_url(topic, school)
            if url is None:
                unavailable += 1
                status_rows.append(_status(topic, "outline_unavailable", "unsafe URL"))
                continue
            try:
                page = _render(browser, url, school)
                _validate_page(page, school)
                source_path, markdown_path = _install_outline(
                    vault, school, course_metadata, topic, page
                )
            except Exception as exc:
                unavailable += 1
                errors.append(f"outline: {type(exc).__name__}")
                status_rows.append(_status(topic, "outline_unavailable", type(exc).__name__))
                continue
            else:
                rendered += 1
                status_rows.append(
                    {
                        "source_key": topic.source_key,
                        "url": page.canonical_url,
                        "status": "rendered",
                        "source_path": source_path,
                        "path": markdown_path,
                    }
                )
            finally:
                _close_target(browser)
        _write_json(course_metadata.directory / "_meta" / "outlines.json", status_rows)
        rendered_paths = [
            vault.root / path
            for row in status_rows
            if row.get("status") == "rendered" and isinstance((path := row.get("path")), str)
        ]
        aipolicy.surface_course_ai_policy(course_metadata.directory, rendered_paths)

    return OutlineReport(rendered=rendered, unavailable=unavailable, errors=tuple(errors))


def _outline_topics(topics: Sequence[TopicRecord]) -> list[TopicRecord]:
    return sorted(
        (
            topic
            for topic in topics
            if topic.availability != "external_link"
            and (_OUTLINE_WORDS.search(topic.title) or topic.outline_url)
        ),
        key=lambda topic: topic.source_key,
    )


def _topic_outline_url(topic: TopicRecord, school: School) -> str | None:
    if topic.outline_url:
        return _normalize_allowed_url(topic.outline_url, school)
    if topic.url_path:
        return _normalize_allowed_url(
            f"{school.base_url.rstrip('/')}/{topic.url_path.lstrip('/')}", school
        )
    return _normalize_allowed_url(topic.view_url, school)


def _normalize_allowed_url(value: str, school: School) -> str | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
        ):
            return None
        if not _host_allowed(value, school):
            return None
        host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        port = parsed.port
        netloc = host if port is None else f"{host}:{port}"
        return urlunsplit(("https", netloc, parsed.path or "/", "", ""))
    except (TypeError, UnicodeError, ValueError):
        return None


def _host_allowed(value: str, school: School) -> bool:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    base = urlsplit(school.base_url)
    base_host = base.hostname
    if hostname is None or base_host is None:
        return False
    try:
        normalized_host = hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        normalized_base = base_host.encode("idna").decode("ascii").casefold().rstrip(".")
        port = parsed.port or 443
        base_port = base.port or 443
    except (UnicodeError, ValueError):
        return False
    if normalized_host == normalized_base and port == base_port:
        return True
    return hostname_matches_suffix(value, school.outline_hosts())


def _render(browser: OutlineBrowser, url: str, school: School) -> OutlinePage:
    result = browser.render_outline(
        url,
        allowed_hosts=tuple([urlsplit(school.base_url).hostname or "", *school.outline_hosts()]),
        timeout=OUTLINE_TIMEOUT_SECONDS,
    )
    return _coerce_page(result)


def _coerce_page(value: OutlinePage | Mapping[str, object]) -> OutlinePage:
    if isinstance(value, OutlinePage):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("browser returned an invalid outline page")
    body = value.get("html")
    canonical_url = value.get("canonical_url", value.get("url"))
    if not isinstance(body, str) or not isinstance(canonical_url, str):
        raise ValueError("browser returned an incomplete outline page")
    pdf = value.get("pdf")
    if pdf is not None and not isinstance(pdf, bytes):
        raise ValueError("browser returned an invalid outline PDF")
    return OutlinePage(
        html=body,
        canonical_url=canonical_url,
        pdf=pdf,
        subresources=_string_tuple(value.get("subresources")),
        top_level_requests=_string_tuple(value.get("top_level_requests")),
        popups=_string_tuple(value.get("popups")),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _validate_page(page: OutlinePage, school: School) -> None:
    if _normalize_allowed_url(page.canonical_url, school) is None:
        raise ValueError("outline redirected to an undeclared origin")
    requests = (*page.subresources, *page.top_level_requests)
    if any(_normalize_allowed_url(value, school) is None for value in requests):
        raise ValueError("outline requested an undeclared dependency")
    if page.popups:
        raise ValueError("outline opened a popup")
    if any(marker.search(page.html) for marker in _LOGIN_MARKERS):
        raise ValueError("outline reached the sign-in wall")
    if not page.html.strip() and page.pdf is None:
        raise ValueError("outline render was empty")


def _install_outline(
    vault: Vault,
    school: School,
    metadata: CourseMetadata,
    topic: TopicRecord,
    page: OutlinePage,
) -> tuple[str, str]:
    manifest = vault.manifest()
    prior = manifest.get(topic.source_key)
    if page.pdf is None:
        # A rendered outline is untrusted course HTML. Persist the inert canonical form, not
        # scripts, event handlers, remote-image loads, credentials, or signed query strings.
        page = replace(page, html=_sanitize_richtext(page.html, school.base_url))
    source_bytes = page.pdf if page.pdf is not None else page.html.encode("utf-8")
    source_hash = sha256(source_bytes).hexdigest()
    source_destination = _source_destination(vault, metadata, topic, prior, page)
    markdown_destination = _markdown_destination(vault, source_destination, prior)
    markdown_bytes = _outline_markdown(topic.title, page)
    if prior is not None and source_hash != prior.sha256:
        preserved = vault.preserve_revision(key=topic.source_key, changed_at=clock.now())
        if preserved is None and vault.materialized(prior).exists():
            raise ValueError("current outline source could not be preserved")

    _install_bytes(source_destination, source_bytes)
    _install_bytes(markdown_destination, markdown_bytes)
    derived = DerivedArtifact(
        path=paths.rel_posix(markdown_destination, vault.root),
        sha256=sha256(markdown_bytes).hexdigest(),
        source_sha256=source_hash,
        tool="outline-renderer",
        tool_version=OUTLINE_TOOL_VERSION,
        created_at=_now(),
    )
    entry = ManifestEntry(
        path=paths.rel_posix(source_destination, vault.root),
        sha256=source_hash,
        source_id=topic.source_id,
        etag=None,
        last_modified=None,
        size=len(source_bytes),
        fetched_at=_now(),
        derived={"markdown": derived},
    )
    vault.mark(topic.source_key, entry)
    vault.save_manifest()
    _update_topic_map(vault, metadata, topic, entry, school)
    return entry.path, derived.path


def _source_destination(
    vault: Vault,
    metadata: CourseMetadata,
    topic: TopicRecord,
    prior: ManifestEntry | None,
    page: OutlinePage,
) -> Path:
    if prior is not None:
        return vault.materialized(prior)
    suffix = ".pdf" if page.pdf is not None else ".html"
    candidate = _content_directory(metadata.directory, ("Outlines",)) / (
        f"{paths.safe_name(topic.title)}{suffix}"
    )
    return paths.unique_path(paths.long_path(candidate))


def _markdown_destination(vault: Vault, source: Path, prior: ManifestEntry | None) -> Path:
    if prior is not None:
        artifact = prior.derived.get("markdown")
        if artifact is not None:
            # Resolve the already-validated manifest artifact through the vault boundary instead
            # of treating a persisted relative path as an untrusted filesystem path.
            return vault.materialized(
                ManifestEntry(
                    path=artifact.path,
                    sha256=artifact.sha256,
                    source_id="derived",
                    etag=None,
                    last_modified=None,
                    size=0,
                    fetched_at=_now(),
                )
            )
    return source.with_suffix(".md")


def _outline_markdown(title: str, page: OutlinePage) -> bytes:
    if page.pdf is not None:
        text = f"# {title}\n\nRendered outline source: `{paths.safe_name(title)}.pdf`\n"
    else:
        body = re.sub(r"(?is)<(script|style|iframe|object|embed).*?</\1\s*>", " ", page.html)
        body = re.sub(r"(?s)<[^>]+>", "\n", body)
        body = html.unescape(body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        text = f"# {title}\n\n{body}\n"
    return text.encode("utf-8")


def _install_bytes(destination: Path, data: bytes) -> None:
    # Outline bytes are generated locally and cheap to recreate.  The generated-writer cleanup
    # semantics are therefore intentional; downloaded course .part files use ingest's
    # atomic_install_temp path and survive a failed install.
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write_bytes(paths.long_path(destination), data)


def _update_topic_map(
    vault: Vault,
    metadata: CourseMetadata,
    topic: TopicRecord,
    entry: ManifestEntry,
    school: School,
) -> None:
    rows = course_index.read_content_map(metadata.directory).get("topics")
    if not isinstance(rows, list):
        return
    derived = entry.derived.get("markdown")
    for row in rows:
        if isinstance(row, dict) and row.get("source_key") == topic.source_key:
            row.update(
                {
                    "availability": "markdown_ready",
                    "source_path": entry.path,
                    "path": derived.path if derived else None,
                    "sha256": entry.sha256,
                    "source_sha256": entry.sha256,
                    "size": entry.size,
                    "next_action": "ready for citation",
                }
            )
    rows = course_index.reconcile_content_map(vault, rows)
    _write_content_map(metadata.directory, rows)
    topics = tuple(
        _topic_from_row(row, course=metadata.course) for row in rows if isinstance(row, dict)
    )
    _write_index(metadata.directory, school=school, course=metadata.course, topics=topics)


def _status(topic: TopicRecord, status: str, reason: str) -> dict[str, object]:
    return {"source_key": topic.source_key, "status": status, "reason": reason}


def _close_target(browser: OutlineBrowser) -> None:
    try:
        browser.close_target()
    except Exception:
        return


def _now() -> str:
    return clock.stamp()


def _write_json(destination: Path, payload: object) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )
    paths.atomic_write_text(paths.long_path(destination), text)


class CDPOutlineBrowser:
    """Render through an existing CDP connection without launching or owning a browser."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self._blocked: str | None = None
        self._popup: str | None = None

    def render_outline(
        self,
        url: str,
        *,
        allowed_hosts: Sequence[str],
        timeout: float,
    ) -> OutlinePage:
        gate = _CDPGate(self.connection, allowed_hosts)
        self.connection.call("Page.enable", event_handler=gate.handle)
        self.connection.call("Network.enable", event_handler=gate.handle)
        self.connection.call(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
            event_handler=gate.handle,
        )
        self.connection.call("Page.navigate", {"url": url}, event_handler=gate.handle)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            gate.raise_if_blocked()
            result = self.connection.call(
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
                event_handler=gate.handle,
            )
            value = result.get("result") if isinstance(result, dict) else None
            if isinstance(value, dict) and value.get("value") in {"interactive", "complete"}:
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("outline render timed out")
        gate.raise_if_blocked()
        result = self.connection.call(
            "Runtime.evaluate",
            {
                "expression": "({html: document.documentElement.outerHTML, url: location.href})",
                "returnByValue": True,
            },
            event_handler=gate.handle,
        )
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise ValueError("browser returned no outline DOM")
        return OutlinePage(
            html=cast(str, value.get("html", "")),
            canonical_url=cast(str, value.get("url", url)),
        )

    def close_target(self) -> None:
        self.connection.call("Page.close")


class _CDPGate:
    def __init__(self, connection: Any, allowed_hosts: Sequence[str]) -> None:
        self.connection = connection
        self.allowed_hosts = tuple(allowed_hosts)
        self.blocked: str | None = None
        self.popup: str | None = None

    def handle(self, message: dict[str, Any]) -> None:
        if message.get("method") == "Fetch.requestPaused":
            params = message.get("params")
            request = params.get("request") if isinstance(params, dict) else None
            request_id = params.get("requestId") if isinstance(params, dict) else None
            target = request.get("url") if isinstance(request, dict) else None
            if not isinstance(request_id, str) or not isinstance(target, str):
                return
            if _allowed_host_from_list(target, self.allowed_hosts):
                self.connection.send_without_wait(
                    "Fetch.continueRequest", {"requestId": request_id}
                )
            else:
                self.blocked = target
                self.connection.send_without_wait(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "BlockedByClient"},
                )
        elif message.get("method") == "Target.targetCreated":
            params = message.get("params")
            info = params.get("targetInfo") if isinstance(params, dict) else None
            if isinstance(info, dict) and info.get("type") == "page":
                url = info.get("url")
                if isinstance(url, str):
                    self.popup = url

    def raise_if_blocked(self) -> None:
        if self.blocked is not None:
            raise ValueError("outline requested an undeclared dependency")
        if self.popup is not None:
            raise ValueError("outline opened a popup")


def _allowed_host_from_list(value: str, allowed_hosts: Sequence[str]) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
        return False
    return any(hostname_matches_suffix(value, [allowed]) for allowed in allowed_hosts if allowed)


__all__ = [
    "CDPOutlineBrowser",
    "OUTLINE_TIMEOUT_SECONDS",
    "OutlineBrowser",
    "OutlinePage",
    "ingest_outlines",
]
