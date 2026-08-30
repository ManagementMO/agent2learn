"""Bounded, first-party D2L HTTP transport.

The client is intentionally smaller than a general-purpose HTTP wrapper.  It only performs
same-origin requests, disables automatic redirects, retries idempotent GETs a bounded number of
times, and leaves completed downloads in the caller's sibling ``.part`` file for the ingest layer
to validate and install atomically.
"""

from __future__ import annotations

import email.utils
import ipaddress
import os
import random
import re
import shutil
import stat
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from requests import Response

from agent2learn import __version__, paths
from agent2learn.errors import A2LError, SessionExpired
from agent2learn.schools import School
from agent2learn.session import Session
from agent2learn.vault import ManifestEntry

THROTTLE = 0.05
MAX_RETRIES = 5
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 90.0
BACKOFF_BASE = 1.0
MAX_RETRY_AFTER = 60.0
JITTER_MAX = 0.5
FREE_DISK_RESERVE = 1 * 1024 * 1024 * 1024
DEFAULT_MAX_BYTES = 2_147_483_648
CHUNK_SIZE = 64 * 1024
DISK_CHECK_EVERY_CHUNKS = 16
MAX_REDIRECTS = 5

_LOGIN_MARKERS = (
    re.compile(r"<title[^>]*>\s*(?:sign\s*in|log\s*in|login)", re.IGNORECASE),
    re.compile(r"<form[^>]+(?:action|id|class)=[^>]*(?:login|signin|d2l)", re.IGNORECASE),
)


class EgressBlocked(A2LError):
    """A URL or redirect is outside the configured first-party origin."""


class DownloadError(A2LError):
    """A first-party response could not be accepted as a complete source file."""


class DiskSpaceExhausted(DownloadError):
    """Streaming would consume the configured free-space reserve."""


@dataclass(frozen=True)
class DownloadResult:
    """A validated response staged in ``temp`` or a conditional not-modified result."""

    temp: Path | None
    sha256: str | None
    size: int | None
    etag: str | None
    last_modified: str | None
    not_modified: bool


class Client:
    """A same-origin D2L client carrying one already-harvested local session."""

    def __init__(self, school: School, session: Session, *, workers: int = 2) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be a positive integer")

        self.school = school
        self.session = session
        self.workers = workers
        self._base_url = _base_url(school.base_url)
        if _origin(self._base_url) != _origin(session.base_url):
            raise ValueError("school and session must use the same origin")

        self.lp_version: str | None = None
        self.le_version: str | None = None
        self.download_template: str | None = None
        self._transport = requests.Session()
        # Authenticated LEARN requests must not inherit ambient proxy, netrc, or certificate
        # settings.  A caller that wants a proxy must configure an explicit transport rather than
        # silently forwarding session cookies through process-wide environment state.
        self._transport.trust_env = False
        self._transport.cookies.update(session.requests_cookies())

    def get_json(self, path: str) -> Any:
        """Perform a JSON GET, translating an HTML login page into ``SessionExpired``."""

        response = self._request("GET", self._resolve_url(path), stream=False)
        return self._decode_json_response(response)

    def get_json_once(self, path: str) -> Any:
        """Perform exactly one JSON GET without following a redirect or retrying a failure.

        Submission read-back is evidence for an already-attempted mutation, not a best-effort
        fetch. A transient response must therefore remain visible to the caller as unknown rather
        than being retried or redirected into a response that looks successful.
        """

        response = self._request(
            "GET",
            self._resolve_url(path),
            stream=False,
            retries=False,
            follow_redirects=False,
        )
        return self._decode_json_response(response)

    @staticmethod
    def _decode_json_response(response: Response) -> Any:
        """Decode one owned response and always close it."""

        try:
            if _is_login_response(response):
                raise SessionExpired("session expired · run: a2l auth")
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise DownloadError("response was not valid JSON") from exc
        finally:
            response.close()

    def download(
        self,
        url: str,
        temp: Path,
        *,
        prior: ManifestEntry | None = None,
        max_bytes: int | None = DEFAULT_MAX_BYTES,
        is_html_topic: bool = False,
        root: Path | None = None,
    ) -> DownloadResult:
        """Stream one first-party source into ``temp`` and validate it before returning.

        ``temp`` is deliberately the caller's unique sibling ``.part`` path.  This layer never
        installs it into a materialized destination or writes a manifest entry.  Failed or
        incomplete transfers remove the part; a successful transfer leaves it for the ingest
        layer to fsync/install through the shared atomic primitive.
        """

        if max_bytes is not None and (
            isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0
        ):
            raise ValueError("max_bytes must be a positive integer or None")
        _validate_part_path(temp)
        paths.ensure_dir(temp.parent, root=root)
        if root is not None and paths.has_link_component(temp.parent, root=root):
            raise ValueError("download temp parent contains a link component")

        request_headers: dict[str, str] = {}
        if prior is not None:
            if prior.etag:
                request_headers["If-None-Match"] = prior.etag
            if prior.last_modified:
                request_headers["If-Modified-Since"] = prior.last_modified

        response: Response | None = None
        try:
            # Jitter staggers the start of concurrent download workers.  The shared throttle in
            # _request applies after each successful response as well.
            time.sleep(random.uniform(0.0, JITTER_MAX))
            response = self._request(
                "GET",
                self._resolve_url(url),
                headers=request_headers,
                stream=True,
            )

            if response.status_code == 304:
                if prior is None:
                    raise DownloadError("304 response has no prior manifest entry")
                _remove_part(temp, root=root)
                return DownloadResult(
                    temp=None,
                    sha256=prior.sha256,
                    size=prior.size,
                    etag=response.headers.get("ETag") or prior.etag,
                    last_modified=response.headers.get("Last-Modified") or prior.last_modified,
                    not_modified=True,
                )

            content_type = response.headers.get("Content-Type", "").casefold()
            html_response = "text/html" in content_type
            # _is_login_response inspects response.text, which buffers a streamed response.  A
            # legitimate HTML topic is allowed through here and checked from the bounded probe
            # below instead, so a large HTML topic is not read into memory twice.
            if not (
                is_html_topic and html_response and response.status_code not in {401, 403}
            ) and _is_login_response(response):
                raise SessionExpired("session expired · run: a2l auth")
            response.raise_for_status()

            if html_response and not is_html_topic:
                raise SessionExpired("session expired · run: a2l auth")

            advertised_size = _content_length(response)
            if (
                max_bytes is not None
                and advertised_size is not None
                and advertised_size > max_bytes
            ):
                raise DownloadError("response exceeds the per-file ceiling")
            if advertised_size is not None:
                _ensure_disk_space(temp, advertised_size)

            digest = sha256()
            size = 0
            chunks_since_disk_check = 0
            html_probe = bytearray()
            with _open_download_part(temp, root=root) as handle:
                try:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        if max_bytes is not None and size + len(chunk) > max_bytes:
                            raise DownloadError("response exceeds the per-file ceiling")
                        if chunks_since_disk_check == 0:
                            _ensure_disk_space(temp, len(chunk))
                        if html_response and len(html_probe) < 64 * 1024:
                            html_probe.extend(chunk[: 64 * 1024 - len(html_probe)])
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        chunks_since_disk_check += 1
                        if chunks_since_disk_check == DISK_CHECK_EVERY_CHUNKS:
                            chunks_since_disk_check = 0
                except requests.RequestException as exc:
                    detail = (
                        "size validation failed" if advertised_size is not None else "stream failed"
                    )
                    raise DownloadError(f"download {detail}") from exc

                if html_response and _looks_like_login(html_probe.decode("utf-8", "ignore")):
                    raise SessionExpired("session expired · run: a2l auth")
                if size == 0:
                    raise DownloadError("response body is empty")
                if advertised_size is not None and size != advertised_size:
                    raise DownloadError(
                        f"response size mismatch: advertised {advertised_size}, received {size}"
                    )
                handle.flush()
                os.fsync(handle.fileno())

            return DownloadResult(
                temp=temp,
                sha256=digest.hexdigest(),
                size=size,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                not_modified=False,
            )
        except BaseException:
            _remove_part(temp, root=root)
            raise
        finally:
            if response is not None:
                response.close()

    def post_once(
        self,
        path: str,
        body: bytes | Iterable[bytes],
        *,
        content_type: str,
    ) -> Response:
        """Send exactly one mutating POST with an explicit length and no transport retry.

        The caller owns the decision to mutate anything on LEARN, so this deliberately exposes no
        retry, no redirect replay, and no endpoint fallback: a transient failure returns to the
        caller with the request having been attempted exactly once.
        """

        content_length: int
        if isinstance(body, bytes):
            content_length = len(body)
        else:
            candidate: object = getattr(body, "content_length", None)
            if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
                raise ValueError(
                    "streaming submission body must expose a non-negative content_length"
                )
            content_length = candidate
        return self._request(
            "POST",
            path,
            headers={"Content-Type": content_type, "Content-Length": str(content_length)},
            stream=False,
            mutating=True,
            data=body,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        stream: bool,
        mutating: bool = False,
        data: bytes | Iterable[bytes] | None = None,
        retries: bool = True,
        follow_redirects: bool = True,
    ) -> Response:
        """Issue a request with explicit redirects, retry, timeout, and egress policy."""

        method = method.upper()
        target = self._resolve_url(url)
        merged_headers = {
            "User-Agent": f"agent2learn/{__version__} (+https://github.com/ManagementMO/agent2learn)",
        }
        if self.session.xsrf:
            merged_headers["X-Csrf-Token"] = self.session.xsrf
        if headers:
            merged_headers.update(headers)

        request_is_mutating = mutating or method in {"POST", "PUT", "PATCH", "DELETE"}
        retryable = retries and method == "GET" and not request_is_mutating
        attempt = 1
        redirects = 0
        backoff = BACKOFF_BASE
        visited = {target}
        while True:
            response = self._transport.request(
                method=method,
                url=target,
                headers=merged_headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=False,
                stream=stream,
                data=data,
            )

            if response.status_code == 304:
                time.sleep(THROTTLE)
                return response

            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DownloadError("redirect response has no Location")
                if request_is_mutating:
                    # Never replay a submission body automatically.  The caller must inspect the
                    # redirect and decide explicitly; this avoids a silent second POST to D2L.
                    raise EgressBlocked("mutating request redirect requires caller decision")
                if not follow_redirects:
                    # A one-shot read-back must prove the named endpoint responded. Treat a
                    # redirect as unknown instead of silently substituting a different route.
                    raise EgressBlocked("one-shot GET redirect requires caller decision")
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise EgressBlocked("redirect limit exceeded")
                next_target = self._resolve_url(urljoin(target, location))
                if next_target in visited:
                    raise EgressBlocked("redirect loop rejected")
                visited.add(next_target)
                target = next_target
                continue

            is_transient = response.status_code == 429 or 500 <= response.status_code <= 599
            if retryable and is_transient and attempt < MAX_RETRIES:
                delay = _retry_delay(response, backoff)
                response.close()
                time.sleep(delay)
                backoff = min(backoff * 2.0, MAX_RETRY_AFTER)
                attempt += 1
                continue

            if 200 <= response.status_code < 300:
                time.sleep(THROTTLE)
            return response

    def _resolve_url(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise EgressBlocked("request URL must be a non-empty string")
        candidate = urljoin(self._base_url.rstrip("/") + "/", value)
        normalized = _request_url(candidate)
        if _origin(normalized) != _origin(self._base_url):
            raise EgressBlocked("request target is outside the configured LEARN origin")
        return normalized


def _base_url(value: str) -> str:
    normalized = _request_url(value)
    parsed = urlsplit(normalized)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _request_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"}:
            raise ValueError
        if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
            raise ValueError
        port = parsed.port  # Access validates malformed ports before a request reaches requests.
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise EgressBlocked("request URL is not a safe HTTP origin") from exc
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, path, parsed.query, ""))


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if hostname is None:
        raise EgressBlocked("request URL has no hostname")
    try:
        try:
            host = ipaddress.ip_address(hostname).compressed.casefold()
        except ValueError:
            host = hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except (UnicodeError, ValueError) as exc:
        raise EgressBlocked("request URL has an invalid origin") from exc
    return parsed.scheme.casefold(), host, port


def _content_length(response: Response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise DownloadError("response Content-Length is invalid") from exc
    if length < 0:
        raise DownloadError("response Content-Length is invalid")
    return length


def _ensure_disk_space(path: Path, required: int) -> None:
    usage = shutil.disk_usage(os.fspath(paths.long_path(path.parent)))
    if usage.free < FREE_DISK_RESERVE + required:
        raise DiskSpaceExhausted("free disk space would cross the configured reserve")


def _retry_delay(response: Response, backoff: float) -> float:
    value = response.headers.get("Retry-After") if response.status_code in {429, 503} else None
    delay: float
    if value is not None:
        try:
            delay = max(0.0, float(value))
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                delay = backoff
            else:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
    else:
        delay = backoff
    return min(delay, MAX_RETRY_AFTER)


def _is_login_response(response: Response) -> bool:
    content_type = response.headers.get("Content-Type", "").casefold()
    if "text/html" not in content_type:
        return False
    if response.status_code in {401, 403}:
        return True
    return _looks_like_login(response.text)


def _looks_like_login(text: str) -> bool:
    return any(marker.search(text) for marker in _LOGIN_MARKERS)


def _validate_part_path(temp: Path) -> None:
    if not isinstance(temp, Path):
        raise TypeError("temp must be a pathlib.Path")
    if not temp.name.endswith(".part"):
        raise ValueError("download temp must be a sibling .part path")
    try:
        file_stat = os.lstat(os.fspath(paths.long_path(temp)))
    except FileNotFoundError:
        return
    if paths.is_link(temp) or stat.S_ISLNK(file_stat.st_mode):
        raise ValueError("download temp must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("download temp must be a regular file")
    if getattr(file_stat, "st_nlink", 1) != 1:
        raise ValueError("download temp must not be a hard link")


def _open_download_part(temp: Path, *, root: Path | None = None) -> BinaryIO:
    """Open a unique part without following a replacement symlink or hard link."""
    # The caller checks the parent before starting the request, but network latency leaves a
    # window in which a trusted parent can be replaced.  Revalidate at the actual open boundary;
    # O_NOFOLLOW protects the final component while this check protects the path leading to it.
    if root is not None and paths.has_link_component(temp, root=root):
        raise ValueError("download temp path contains a link component")
    raw_path = os.fspath(paths.long_path(temp))
    try:
        prior_stat = os.lstat(raw_path)
    except FileNotFoundError:
        prior_stat = None

    flags = os.O_WRONLY | os.O_CREAT
    if prior_stat is None:
        flags |= os.O_EXCL
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(raw_path, flags | no_follow, 0o600)
    except FileExistsError:
        # A caller may have reserved the sibling with mkstemp().  Re-check its identity after
        # the race rather than truncating an object that appeared under the requested name.
        prior_stat = os.lstat(raw_path)
        if paths.is_link(temp) or not stat.S_ISREG(prior_stat.st_mode):
            raise ValueError("download temp must be a regular file") from None
        file_descriptor = os.open(raw_path, os.O_WRONLY | no_follow)

    try:
        opened_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError("download temp must be a regular file")
        if getattr(opened_stat, "st_nlink", 1) != 1:
            raise ValueError("download temp must not be a hard link")
        if prior_stat is not None and (
            opened_stat.st_dev != prior_stat.st_dev or opened_stat.st_ino != prior_stat.st_ino
        ):
            raise ValueError("download temp changed while it was being opened")
        os.ftruncate(file_descriptor, 0)
        return os.fdopen(file_descriptor, "wb")
    except BaseException:
        os.close(file_descriptor)
        raise


def _remove_part(temp: Path, *, root: Path | None = None) -> None:
    if root is not None:
        try:
            if paths.has_link_component(temp, root=root):
                return
        except (OSError, ValueError):
            return
    try:
        os.unlink(os.fspath(paths.long_path(temp)))
    except OSError:
        return


__all__ = [
    "BACKOFF_BASE",
    "CHUNK_SIZE",
    "Client",
    "CONNECT_TIMEOUT",
    "DEFAULT_MAX_BYTES",
    "DISK_CHECK_EVERY_CHUNKS",
    "DiskSpaceExhausted",
    "DownloadError",
    "DownloadResult",
    "EgressBlocked",
    "FREE_DISK_RESERVE",
    "JITTER_MAX",
    "MAX_REDIRECTS",
    "MAX_RETRIES",
    "MAX_RETRY_AFTER",
    "READ_TIMEOUT",
    "THROTTLE",
]
