"""Bounded outline rendering through Agent2Learn's dedicated local CDP profile.

The production factory may acquire or launch only the persistent Agent2Learn browser profile; it
never reads or attaches to an everyday profile. Every outline gets a fresh page target and CDP
connection. Top-level and subresource URLs are checked at the request boundary, and a blocked
dependency makes the outline unavailable instead of producing a false "no policy" conclusion.
"""

from __future__ import annotations

import html
import json
import os
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
from agent2learn.schools import School
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
    """The narrow one-target browser capability required by :func:`ingest_outlines`."""

    def render_outline(
        self,
        url: str,
        *,
        allowed_hosts: Sequence[str],
        timeout: float,
    ) -> OutlinePage | Mapping[str, object]:
        """Render one target and return the final DOM plus its request audit."""

    def close_target(self) -> None:
        """Close this target and its page connection before another target is opened."""


class OutlineBrowserFactory(Protocol):
    """Create a new one-target browser connection for every discovered outline."""

    def open_browser(self) -> OutlineBrowser:
        """Return a browser backed by a newly-created page target."""

    def close(self) -> None:
        """Release factory-owned dedicated-profile resources after all targets are closed."""


def ingest_outlines(
    browser: OutlineBrowser | OutlineBrowserFactory,
    vault: Vault,
    school: School,
    metadata: MetadataReport,
) -> OutlineReport:
    """Render discovered outlines after metadata, using a fresh target for every attempt."""

    factory = _as_factory(browser)
    rendered = 0
    unavailable = 0
    errors: list[str] = []
    stop_after_cleanup_failure = False
    try:
        for course_metadata in metadata.courses:
            status_rows: list[dict[str, object]] = []
            for topic in _outline_topics(course_metadata.topics):
                if stop_after_cleanup_failure:
                    unavailable += 1
                    status_rows.append(
                        _status(
                            topic,
                            "outline_unavailable",
                            "previous target cleanup failed",
                        )
                    )
                    continue

                url = _topic_outline_url(topic, school)
                if url is None:
                    unavailable += 1
                    status_rows.append(_status(topic, "outline_unavailable", "unsafe URL"))
                    continue

                target: OutlineBrowser | None = None
                status: dict[str, object]
                try:
                    target = factory.open_browser()
                    page = _render(target, url, school)
                    page = _validate_page(page, school)
                    source_path, markdown_path = _install_outline(
                        vault, school, course_metadata, topic, page
                    )
                except Exception as exc:
                    unavailable += 1
                    errors.append(f"outline: {type(exc).__name__}")
                    status = _status(topic, "outline_unavailable", type(exc).__name__)
                else:
                    rendered += 1
                    status = {
                        "source_key": topic.source_key,
                        "url": page.canonical_url,
                        "status": "rendered",
                        "source_path": source_path,
                        "path": markdown_path,
                    }
                finally:
                    close_error = _close_target(target) if target is not None else None

                if close_error is not None:
                    errors.append(f"outline: target cleanup failed ({close_error})")
                    status["cleanup_error"] = "target could not be closed"
                    stop_after_cleanup_failure = True
                status_rows.append(status)

            _write_json(course_metadata.directory / "_meta" / "outlines.json", status_rows)
            rendered_paths = [
                vault.root / path
                for row in status_rows
                if row.get("status") == "rendered" and isinstance((path := row.get("path")), str)
            ]
            aipolicy.surface_course_ai_policy(course_metadata.directory, rendered_paths)
    finally:
        factory_error = _close_factory(factory)

    if factory_error is not None:
        errors.append(f"outline: browser cleanup failed ({factory_error})")
    return OutlineReport(rendered=rendered, unavailable=unavailable, errors=tuple(errors))


class _BorrowedBrowserFactory:
    """Compatibility adapter for one-target callers; it deliberately refuses target reuse."""

    def __init__(self, browser: OutlineBrowser) -> None:
        self._browser = browser
        self._opened = False

    def open_browser(self) -> OutlineBrowser:
        if self._opened:
            raise RuntimeError("a fresh outline target factory is required")
        self._opened = True
        return self._browser

    def close(self) -> None:
        return


def _as_factory(value: OutlineBrowser | OutlineBrowserFactory) -> OutlineBrowserFactory:
    if callable(getattr(value, "open_browser", None)) and callable(getattr(value, "close", None)):
        return cast(OutlineBrowserFactory, value)
    return _BorrowedBrowserFactory(cast(OutlineBrowser, value))


def _close_factory(factory: OutlineBrowserFactory) -> str | None:
    try:
        factory.close()
    except Exception as exc:
        return type(exc).__name__
    return None


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
    return _allowed_host_from_list(value, (school.base_url, *school.outline_hosts()))


def _render(browser: OutlineBrowser, url: str, school: School) -> OutlinePage:
    result = browser.render_outline(
        url,
        allowed_hosts=(school.base_url, *school.outline_hosts()),
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
        subresources=_string_tuple(value.get("subresources"), "subresources"),
        top_level_requests=_string_tuple(value.get("top_level_requests"), "top_level_requests"),
        popups=_string_tuple(value.get("popups"), "popups"),
    )


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"browser returned invalid {label}")
    return tuple(value)


def _validate_page(page: OutlinePage, school: School) -> OutlinePage:
    canonical_url = _normalize_allowed_url(page.canonical_url, school)
    if canonical_url is None:
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
    # Persist the normalized URL, not the browser's raw location, because a same-origin redirect
    # can still carry signed query strings or fragments that are not part of the citation.
    return replace(page, canonical_url=canonical_url)


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
    markdown_hash = sha256(markdown_bytes).hexdigest()
    if prior is not None and _outline_is_current(
        vault,
        prior,
        source_destination=source_destination,
        source_hash=source_hash,
        markdown_destination=markdown_destination,
        markdown_hash=markdown_hash,
    ):
        _update_topic_map(vault, metadata, topic, prior, school)
        artifact = prior.derived["markdown"]
        return prior.path, artifact.path

    if prior is not None and _outline_needs_preservation(vault, prior, source_hash, markdown_hash):
        preserved = vault.preserve_revision(key=topic.source_key, changed_at=clock.now())
        prior_material_remains = any(
            paths.is_link(path) or paths.long_path(path).exists()
            for path in (source_destination, markdown_destination)
        )
        if preserved is None and prior_material_remains:
            raise ValueError("current outline revision could not be preserved")

    _install_bytes(source_destination, source_bytes)
    _install_bytes(markdown_destination, markdown_bytes)
    derived = DerivedArtifact(
        path=paths.rel_posix(markdown_destination, vault.root),
        sha256=markdown_hash,
        source_sha256=source_hash,
        tool="outline-renderer",
        tool_version=OUTLINE_TOOL_VERSION,
        created_at=_now(),
    )
    entry = ManifestEntry(
        path=paths.rel_posix(source_destination, vault.root),
        sha256=source_hash,
        source_id=topic.source_id,
        etag=topic.etag,
        last_modified=topic.last_modified,
        size=len(source_bytes),
        fetched_at=_now(),
        derived={"markdown": derived},
    )
    vault.mark(topic.source_key, entry)
    vault.save_manifest()
    _update_topic_map(vault, metadata, topic, entry, school)
    return entry.path, derived.path


def _outline_is_current(
    vault: Vault,
    prior: ManifestEntry,
    *,
    source_destination: Path,
    source_hash: str,
    markdown_destination: Path,
    markdown_hash: str,
) -> bool:
    """Require both generated files and their manifest provenance to match exactly."""

    artifact = prior.derived.get("markdown")
    if artifact is None:
        return False
    if (
        prior.path != paths.rel_posix(source_destination, vault.root)
        or prior.sha256 != source_hash
        or artifact.path != paths.rel_posix(markdown_destination, vault.root)
        or artifact.sha256 != markdown_hash
        or artifact.source_sha256 != source_hash
        or artifact.tool != "outline-renderer"
        or artifact.tool_version != OUTLINE_TOOL_VERSION
    ):
        return False
    source_fingerprint = _file_fingerprint(source_destination)
    markdown_fingerprint = _file_fingerprint(markdown_destination)
    return source_fingerprint == (prior.sha256, prior.size) and (
        markdown_fingerprint is not None and markdown_fingerprint[0] == artifact.sha256
    )


def _outline_needs_preservation(
    vault: Vault,
    prior: ManifestEntry,
    source_hash: str,
    markdown_hash: str,
) -> bool:
    """Preserve changed generated bytes or a locally modified current artifact before overwrite."""

    if source_hash != prior.sha256:
        return True
    source = vault.materialized(prior)
    actual_source = _file_fingerprint(source)
    if actual_source is not None and actual_source != (prior.sha256, prior.size):
        return True

    artifact = prior.derived.get("markdown")
    if artifact is None:
        return False
    if markdown_hash != artifact.sha256:
        return True
    markdown = _markdown_destination(vault, source, prior)
    actual_markdown = _file_fingerprint(markdown)
    return actual_markdown is not None and actual_markdown[0] != artifact.sha256


def _file_fingerprint(source: Path) -> tuple[str, int] | None:
    if paths.is_link(source):
        raise ValueError("outline artifact must not be a symlink")
    digest = sha256()
    size = 0
    try:
        with open(os.fspath(paths.long_path(source)), "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except FileNotFoundError:
        return None
    except IsADirectoryError as exc:
        raise ValueError("outline artifact must be a regular file") from exc
    return digest.hexdigest(), size


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
    return paths.unique_path(candidate)


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
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    paths.atomic_write_bytes(destination, data)


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


def _close_target(browser: OutlineBrowser) -> str | None:
    try:
        browser.close_target()
    except Exception as exc:
        return type(exc).__name__
    return None


def _now() -> str:
    return clock.stamp()


def _write_json(destination: Path, payload: object) -> None:
    paths.long_path(destination.parent).mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )
    paths.atomic_write_text(destination, text)


class _PageConnectionFactory(Protocol):
    def open_page(self) -> Any:
        """Return a fresh page-target CDP connection."""

    def close(self) -> None:
        """Release endpoint/process resources after all page targets are closed."""


class CDPOutlineBrowserFactory:
    """Adapt a dedicated-profile page factory to one fresh outline browser per target."""

    def __init__(self, pages: _PageConnectionFactory) -> None:
        self._pages = pages

    def open_browser(self) -> OutlineBrowser:
        return CDPOutlineBrowser(self._pages.open_page())

    def close(self) -> None:
        self._pages.close()


def dedicated_profile_outline_factory() -> OutlineBrowserFactory:
    """Build the production factory for Agent2Learn's dedicated persistent profile."""

    from agent2learn.auth.cdp import DedicatedPageFactory

    return CDPOutlineBrowserFactory(DedicatedPageFactory())


class CDPOutlineBrowser:
    """Render one outline through one newly-created dedicated-profile page connection."""

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
        force_close = getattr(self.connection, "close_target", None)
        if callable(force_close):
            force_close()
            return
        try:
            self.connection.call("Page.close")
        finally:
            self.connection.close()


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
    """Apply the exact LEARN origin plus declared-host boundary policy at request time."""

    if not allowed_hosts:
        return False
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        port = parsed.port or 443
        base_host, base_port = _declared_host(allowed_hosts[0])
        if host == base_host and port == base_port:
            return True
        for declared in allowed_hosts[1:]:
            declared_host, declared_port = _declared_host(declared)
            if port == declared_port and (
                host == declared_host or host.endswith(f".{declared_host}")
            ):
                return True
    except (TypeError, UnicodeError, ValueError):
        return False
    return False


def _declared_host(value: str) -> tuple[str, int]:
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise ValueError("outline host declaration must be HTTPS")
    host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
    return host, parsed.port or 443


__all__ = [
    "CDPOutlineBrowser",
    "CDPOutlineBrowserFactory",
    "OUTLINE_TIMEOUT_SECONDS",
    "OutlineBrowser",
    "OutlineBrowserFactory",
    "OutlinePage",
    "dedicated_profile_outline_factory",
    "ingest_outlines",
]
