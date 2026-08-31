"""Conservative Chrome DevTools Protocol authentication for a dedicated profile."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import requests
import websocket

from agent2learn import config, paths
from agent2learn.errors import AuthenticationError
from agent2learn.schools import School
from agent2learn.session import Session

from . import paste

CDP_TIMEOUT = 10.0
ENDPOINT_WAIT_SECONDS = 30.0
AUTH_WAIT_SECONDS = 300.0
RUNTIME_RETRY_SECONDS = 10.0
POLL_SECONDS = 0.5

_CHROMIUM_EXECUTABLE_BASENAMES = ("Google Chrome", "Microsoft Edge", "Chromium")
_CHROMIUM_METADATA_PRODUCTS = ("Chrome", "Google Chrome", "Chromium", "Microsoft Edge", "Edg")
_LOCK_MARKERS = ("SingletonLock", "SingletonSocket", "SingletonCookie")
_BROWSER_VERSION = r"\d+(?:\.\d+)*"
_BROWSER_METADATA_PATTERNS = tuple(
    re.compile(rf"^{re.escape(product)}/{_BROWSER_VERSION}$", re.IGNORECASE)
    for product in _CHROMIUM_METADATA_PRODUCTS
)
_AUTH_EXPRESSION = r"""
(async () => {
  try {
    const versionsResponse = await fetch("/d2l/api/versions/", {credentials: "include"});
    if (!versionsResponse.ok) return {ok: false};
    const products = await versionsResponse.json();
    if (!Array.isArray(products)) return {ok: false};
    const product = products.find(
      (entry) => entry && typeof entry === "object" && entry.ProductCode === "lp"
    );
    if (!product) return {ok: false};
    const supportedVersions = Array.isArray(product.SupportedVersions)
      ? product.SupportedVersions
      : [];
    const candidates = [product.LatestVersion, ...supportedVersions]
      .filter(
        (value, index, values) =>
          typeof value === "string" &&
          /^[0-9]+(?:\.[0-9]+)*$/.test(value) &&
          values.indexOf(value) === index
      );
    for (const version of candidates) {
      const response = await fetch(`/d2l/api/lp/${version}/users/whoami`, {
        credentials: "include"
      });
      if (!response.ok) continue;
      let payload;
      try {
        payload = await response.json();
      } catch (_) {
        continue;
      }
      if (
        payload &&
        typeof payload === "object" &&
        typeof payload.Identifier === "string" &&
        payload.Identifier.trim().length > 0
      ) {
        return {ok: true, identifier: payload.Identifier};
      }
    }
  } catch (_) {
    return {ok: false};
  }
  return {ok: false};
})()
"""


@dataclass(frozen=True)
class DebugEndpoint:
    """Validated loopback DevTools endpoint discovered from ``DevToolsActivePort``."""

    port: int
    browser_websocket_url: str


class _CDPCommandError(AuthenticationError):
    """A command-level CDP error with no unredacted browser message retained."""

    def __init__(self, method: str, *, retryable: bool = False) -> None:
        super().__init__(f"browser DevTools command failed: {method}")
        self.retryable = retryable


@dataclass(frozen=True)
class _ActivePortMarker:
    """The identity Chrome writes for one browser-level DevTools endpoint."""

    port: int
    browser_websocket_path: str


class _OwnedProcess(Protocol):
    """The bounded process lifecycle surface used for an Agent2Learn-owned browser."""

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class _CDPConnection:
    def __init__(self, websocket_url: str) -> None:
        try:
            self._socket = websocket.create_connection(
                websocket_url,
                timeout=CDP_TIMEOUT,
                suppress_origin=True,
            )
        except Exception as exc:
            raise AuthenticationError(
                "could not connect to the dedicated browser DevTools endpoint"
            ) from exc
        self._next_id = 1

    def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
        message = {"id": self._next_id, "method": method}
        self._next_id += 1
        if params:
            message["params"] = params
        self._socket.send(json.dumps(message, separators=(",", ":")))

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        message: dict[str, object] = {"id": message_id, "method": method}
        if params:
            message["params"] = params
        try:
            self._socket.send(json.dumps(message, separators=(",", ":")))
            while True:
                raw = self._socket.recv()
                if not raw:
                    raise AuthenticationError("dedicated browser DevTools connection closed")
                decoded = json.loads(raw)
                if not isinstance(decoded, dict):
                    continue
                if event_handler is not None:
                    event_handler(decoded)
                if decoded.get("id") != message_id:
                    continue
                error = decoded.get("error")
                if isinstance(error, dict):
                    raise _CDPCommandError(
                        method,
                        retryable=_runtime_error_is_transient(method, error),
                    )
                result = decoded.get("result", {})
                return result if isinstance(result, dict) else {}
        except AuthenticationError:
            raise
        except (OSError, ValueError, TypeError, websocket.WebSocketException) as exc:
            raise AuthenticationError(f"browser DevTools command failed: {method}") from exc

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            return


class _DedicatedPageConnection:
    """Pair one page socket with the browser-level handle that can force-close its target."""

    def __init__(
        self,
        page: _CDPConnection,
        browser: _CDPConnection,
        target_id: str,
    ) -> None:
        self._page = page
        self._browser = browser
        self._target_id = target_id
        self._closed = False

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self._page.call(method, params, event_handler=event_handler)

    def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
        self._page.send_without_wait(method, params)

    def close_target(self) -> None:
        """Force-close exactly this target instead of trusting page before-unload handlers."""

        if self._closed:
            return
        self._closed = True
        try:
            result = self._browser.call("Target.closeTarget", {"targetId": self._target_id})
            if result.get("success") is not True:
                raise AuthenticationError("dedicated outline target could not be closed")
        finally:
            self._page.close()
            self._browser.close()

    def close(self) -> None:
        self.close_target()


class DedicatedPageFactory:
    """Own the dedicated-profile endpoint and create one fresh page target per outline.

    The factory never inspects or attaches to an everyday profile.  It acquires only the
    Agent2Learn ``browser-profile`` endpoint, creates an inert ``about:blank`` target for each
    caller, and leaves closing that target to the returned page connection's owner.
    """

    def __init__(self) -> None:
        self._endpoint: DebugEndpoint | None = None
        self._process: _OwnedProcess | None = None
        self._profile: Path | None = None
        self._owned = False
        self._closed = False

    def open_page(self) -> _DedicatedPageConnection:
        """Create and connect to a fresh loopback page target."""

        endpoint = self._ensure_endpoint()
        browser: _CDPConnection | None = None
        page: _CDPConnection | None = None
        target_id: str | None = None
        try:
            browser = _CDPConnection(endpoint.browser_websocket_url)
            result = browser.call(
                "Target.createTarget",
                {"url": "about:blank", "background": True},
            )
            raw_target_id = result.get("targetId")
            if not isinstance(raw_target_id, str) or not raw_target_id:
                raise AuthenticationError("dedicated browser did not create an outline target")
            target_id = raw_target_id
            websocket_url = _wait_for_target(endpoint.port, target_id)
            page = _CDPConnection(websocket_url)
            return _DedicatedPageConnection(page, browser, target_id)
        except BaseException:
            if page is not None:
                page.close()
            if browser is not None and target_id is not None:
                with suppress(Exception):
                    browser.call("Target.closeTarget", {"targetId": target_id})
            if browser is not None:
                browser.close()
            raise

    def close(self) -> None:
        """Close only a browser process this factory launched, once all targets are gone."""

        if self._closed:
            return
        self._closed = True
        endpoint = self._endpoint
        process = self._process
        profile = self._profile
        self._endpoint = None
        self._process = None
        self._profile = None
        if self._owned and endpoint is not None:
            _close_owned_browser(endpoint, process, profile=profile)

    def _ensure_endpoint(self) -> DebugEndpoint:
        if self._closed:
            raise AuthenticationError("dedicated outline browser factory is closed")
        if self._endpoint is not None:
            return self._endpoint
        profile = profile_path()
        _validate_profile_path(profile)
        paths.long_path(profile).mkdir(parents=True, exist_ok=True)
        endpoint, process, owned = _acquire_endpoint(profile)
        self._endpoint = endpoint
        self._process = process
        self._profile = profile
        self._owned = owned
        return endpoint


class _CDPRequestSender(Protocol):
    """The one CDP operation needed by the request-boundary auth gate."""

    def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None: ...


class _CDPCommandConnection(Protocol):
    """The command surface used by helpers that can be driven by CDP test doubles."""

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]: ...


class _AuthGate:
    def __init__(self, connection: _CDPRequestSender, school: School) -> None:
        self.connection = connection
        self.school = school
        self.blocked_host: str | None = None
        self._fatal_blocked_host: str | None = None
        self._handled_request_ids: set[str] = set()

    def handle(self, message: dict[str, Any]) -> None:
        if message.get("method") != "Fetch.requestPaused":
            return
        params = message.get("params")
        if not isinstance(params, dict):
            return
        request_id = params.get("requestId")
        if not isinstance(request_id, str) or not request_id:
            return
        # Fetch keeps a request paused until it receives one terminal decision.  A malformed
        # event must not be left pending while Runtime.evaluate waits on this same socket, and a
        # duplicate event must not receive a second decision.
        if request_id in self._handled_request_ids:
            return
        self._handled_request_ids.add(request_id)

        request = params.get("request")
        if not isinstance(request, dict):
            self._fail(request_id, "unknown-host", fatal=True)
            return
        target = request.get("url")
        if not isinstance(target, str):
            self._fail(request_id, "unknown-host", fatal=True)
            return

        if _auth_url_allowed(target, self.school):
            self.connection.send_without_wait("Fetch.continueRequest", {"requestId": request_id})
            return

        resource_type = params.get("resourceType")
        self._fail(
            request_id,
            _safe_hostname(target),
            fatal=resource_type is None or resource_type in {"Document", "Iframe"},
        )

    def _fail(self, request_id: str, host: str, *, fatal: bool = False) -> None:
        self.blocked_host = self.blocked_host or host
        if fatal:
            self._fatal_blocked_host = self._fatal_blocked_host or host
        self.connection.send_without_wait(
            "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
        )

    def raise_if_blocked(self) -> None:
        if self._fatal_blocked_host is not None:
            raise AuthenticationError(
                f"authentication stopped at undeclared host {self._fatal_blocked_host}; "
                "fallback: a2l auth --paste"
            )

    def raise_if_any_blocked(self) -> None:
        if self.blocked_host is not None:
            raise AuthenticationError(
                f"authentication stopped at undeclared host {self.blocked_host}; "
                "fallback: a2l auth --paste"
            )


def _call_with_gate(
    connection: _CDPCommandConnection,
    method: str,
    params: dict[str, object] | None,
    gate: _AuthGate,
) -> dict[str, Any]:
    """Run one command while preserving a request-boundary failure over CDP errors."""

    try:
        result = connection.call(method, params, event_handler=gate.handle)
    except AuthenticationError:
        # A request rejected by Fetch can invalidate navigation or the page execution context
        # before Chromium sends the command response.  The hostname decision is the useful,
        # already-redacted error in that case; otherwise retain the generic CDP failure.
        gate.raise_if_blocked()
        raise
    gate.raise_if_blocked()
    return result


def authenticate_browser(school: School) -> Session:
    """Harvest a verified session from a validated dedicated Chromium profile."""

    profile = config.data_dir() / "browser-profile"
    _validate_profile_path(profile)
    paths.long_path(profile).mkdir(parents=True, exist_ok=True)
    endpoint, process, owned = _acquire_endpoint(profile)
    page_connection: _CDPConnection | None = None
    try:
        page_url = _wait_for_page(endpoint.port)
        page_connection = _CDPConnection(page_url)
        gate = _AuthGate(page_connection, school)
        page_connection.call("Page.enable", event_handler=gate.handle)
        page_connection.call("Network.enable", event_handler=gate.handle)
        page_connection.call(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
            event_handler=gate.handle,
        )
        target = urljoin(school.base_url.rstrip("/") + "/", "d2l/home")
        _call_with_gate(page_connection, "Page.navigate", {"url": target}, gate)

        identifier = _wait_for_authenticated_page(page_connection, gate)
        cookies_result = _call_with_gate(page_connection, "Storage.getCookies", None, gate)
        raw_cookies = cookies_result.get("cookies")
        if not isinstance(raw_cookies, list):
            raise AuthenticationError("dedicated browser returned no cookie collection")
        return paste.session_from_cookie_records(
            raw_cookies,
            base_url=school.base_url,
            harvested_at=datetime_now(),
            user_id=identifier,
        )
    finally:
        try:
            if page_connection is not None:
                page_connection.close()
        finally:
            if owned:
                _close_owned_browser(endpoint, process, profile=profile)


def locate_browser() -> Path:
    """Locate an installed Chrome/Edge binary without downloading or launching a shell."""

    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend(_windows_browser_paths())
        for name in ("chrome.exe", "msedge.exe", "chromium.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    elif sys.platform == "darwin":
        candidates.extend(
            Path(f"/Applications/{name}.app/Contents/MacOS/{name}")
            for name in _CHROMIUM_EXECUTABLE_BASENAMES
        )
        for name in ("google-chrome", "microsoft-edge", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    else:
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for candidate in candidates:
        if paths.long_path(candidate).is_file():
            return candidate
    raise AuthenticationError(
        "Chrome or Edge was not found; install one or use the fallback: a2l auth --paste"
    )


def profile_path() -> Path:
    """Return the persistent dedicated browser profile location."""

    return config.data_dir() / "browser-profile"


def _acquire_endpoint(profile: Path) -> tuple[DebugEndpoint, _OwnedProcess | None, bool]:
    _validate_profile_path(profile)
    active_port = profile / "DevToolsActivePort"
    if paths.is_link(active_port):
        raise AuthenticationError("DevToolsActivePort must not be a symlink")
    if paths.long_path(active_port).exists():
        return _read_valid_endpoint(active_port, profile=profile), None, False
    if any(paths.long_path(profile / marker).exists() for marker in _LOCK_MARKERS):
        raise AuthenticationError(
            f"dedicated browser profile is locked without a reachable DevTools endpoint: {profile}"
        )

    browser = locate_browser()
    try:
        process = subprocess.Popen(
            [
                os.fspath(paths.long_path(browser)),
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise AuthenticationError("could not launch the dedicated Chrome/Edge profile") from exc

    deadline = time.monotonic() + ENDPOINT_WAIT_SECONDS
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AuthenticationError(
                    "the dedicated browser exited before creating DevToolsActivePort; "
                    "use a2l auth --paste"
                )
            if paths.is_link(active_port):
                raise AuthenticationError("DevToolsActivePort must not be a symlink")
            if paths.long_path(active_port).exists():
                try:
                    return (
                        _read_valid_endpoint(active_port, profile=profile, process=process),
                        process,
                        True,
                    )
                except AuthenticationError:
                    pass
            time.sleep(POLL_SECONDS)
        raise AuthenticationError(
            "the dedicated browser did not expose a reachable loopback DevTools endpoint; "
            "use a2l auth --paste"
        )
    except BaseException:
        try:
            _terminate_owned_process(process)
        except AuthenticationError as cleanup_error:
            raise AuthenticationError(
                "dedicated browser could not be cleaned up after endpoint acquisition failed"
            ) from cleanup_error
        raise


def _read_valid_endpoint(
    active_port: Path,
    *,
    profile: Path | None = None,
    process: object | None = None,
) -> DebugEndpoint:
    if profile is None:
        raise AuthenticationError("DevTools endpoint cannot be used without a dedicated profile")
    _validate_profile_path(profile)
    marker = _read_active_port_marker(active_port)
    if marker is None:
        raise AuthenticationError(
            "DevToolsActivePort is stale or invalid; close the dedicated browser normally"
        )
    port = marker.port

    metadata = _get_json(port, "/json/version")
    browser = metadata.get("Browser")
    websocket_url = metadata.get("webSocketDebuggerUrl")
    if not isinstance(browser, str) or not _browser_metadata_allowed(browser):
        raise AuthenticationError("DevTools endpoint is not the expected Chrome/Edge process")
    if not isinstance(websocket_url, str) or not _loopback_url(websocket_url, port):
        raise AuthenticationError("DevTools endpoint is not a validated loopback browser endpoint")
    if _websocket_path(websocket_url) != marker.browser_websocket_path:
        raise AuthenticationError("DevToolsActivePort does not match the browser endpoint")
    if process is None and not _process_owns_profile(profile, port):
        raise AuthenticationError("DevTools endpoint is not owned by the dedicated profile")
    return DebugEndpoint(port=port, browser_websocket_url=websocket_url)


def _read_active_port_marker(active_port: Path) -> _ActivePortMarker | None:
    """Read Chrome's two-part endpoint marker without exposing its contents."""

    if paths.is_link(active_port):
        return None
    try:
        with open(os.fspath(paths.long_path(active_port)), encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
        port = int(lines[0].strip())
        browser_websocket_path = _marker_websocket_path(lines[1].strip(), port)
    except (OSError, ValueError, IndexError):
        return None
    if not 1 <= port <= 65535 or browser_websocket_path is None:
        return None
    return _ActivePortMarker(port=port, browser_websocket_path=browser_websocket_path)


def _marker_websocket_path(value: str, port: int) -> str | None:
    """Normalize the path-shaped or full-URL form written by Chromium."""

    if not value:
        return None
    if "://" in value:
        if not _loopback_url(value, port):
            return None
        path = _websocket_path(value)
    else:
        path = value
    if path is None or not path.startswith("/devtools/browser/"):
        return None
    return path


def _websocket_path(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError, UnicodeError):
        return None
    if parsed.scheme.casefold() not in {"ws", "wss"}:
        return None
    if parsed.query or parsed.fragment or not parsed.path:
        return None
    return parsed.path


def _browser_metadata_allowed(value: str) -> bool:
    """Accept Chromium's product tokens without substring-matching lookalikes."""

    return any(
        pattern.fullmatch(value.strip()) is not None for pattern in _BROWSER_METADATA_PATTERNS
    )


def _validate_profile_path(profile: Path) -> None:
    if paths.is_link(profile):
        raise AuthenticationError("dedicated browser profile must not be a symlink")
    if paths.long_path(profile).exists() and not paths.long_path(profile).is_dir():
        raise AuthenticationError("dedicated browser profile is not a directory")


def _process_owns_profile(profile: Path, port: int) -> bool:
    return any(
        _command_matches_profile(command, profile, port) for command in _running_process_commands()
    )


def _running_process_commands() -> list[str]:
    if os.name == "nt":
        executable = shutil.which("powershell") or shutil.which("pwsh")
        if executable is None:
            return []
        command = "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"
        args = [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        args = ["ps", "-axo", "args="]
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _command_matches_profile(command: str, profile: Path, port: int) -> bool:
    lowered = command.casefold()
    if not any(marker.casefold() in lowered for marker in ("chrome", "chromium", "msedge")):
        return False
    normalized_command = command.replace("\\", "/")
    expected_paths = {os.path.abspath(os.fspath(profile))}
    with suppress(OSError, RuntimeError):
        expected_paths.add(os.fspath(profile.resolve()))
    normalized_expected_paths = {
        expected.replace("\\", "/").casefold() for expected in expected_paths
    }
    profile_matches = any(
        _has_exact_argument(
            normalized_command.casefold(),
            f"--user-data-dir={expected}",
        )
        or _has_exact_argument(
            normalized_command.casefold(),
            f'--user-data-dir="{expected}"',
        )
        for expected in normalized_expected_paths
    )
    if not profile_matches:
        return False
    remote_match = re.search(r"(?:^|\s)--remote-debugging-port(?:=|\s+)(\d+)(?=\s|$)", lowered)
    if remote_match is None:
        return False
    return int(remote_match.group(1)) in {0, port}


def _has_exact_argument(command: str, marker: str) -> bool:
    """Match an option value without accepting a longer lookalike path/value."""
    start = 0
    while (position := command.find(marker, start)) != -1:
        before_ok = position == 0 or command[position - 1].isspace()
        end = position + len(marker)
        after_ok = end == len(command) or command[end].isspace() or command[end] in {'"', "'"}
        if before_ok and after_ok:
            return True
        start = position + 1
    return False


def _wait_for_target(port: int, target_id: str) -> str:
    """Return the validated page websocket for one newly-created target."""

    deadline = time.monotonic() + ENDPOINT_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            targets = _get_json_list(port, "/json/list")
        except AuthenticationError:
            time.sleep(POLL_SECONDS)
            continue
        for target in targets:
            if target.get("type") != "page" or target.get("id") != target_id:
                continue
            websocket_url = target.get("webSocketDebuggerUrl")
            if isinstance(websocket_url, str) and _loopback_url(websocket_url, port):
                return websocket_url
        time.sleep(POLL_SECONDS)
    raise AuthenticationError("dedicated browser outline target is not reachable")


def _wait_for_page(port: int) -> str:
    deadline = time.monotonic() + ENDPOINT_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            targets = _get_json_list(port, "/json/list")
        except AuthenticationError:
            time.sleep(POLL_SECONDS)
            continue
        for target in targets:
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            websocket_url = target.get("webSocketDebuggerUrl")
            if isinstance(websocket_url, str) and _loopback_url(websocket_url, port):
                return websocket_url
        time.sleep(POLL_SECONDS)
    raise AuthenticationError(
        "dedicated browser has no reachable page target; use a2l auth --paste"
    )


def _wait_for_authenticated_page(connection: _CDPCommandConnection, gate: _AuthGate) -> str:
    deadline = time.monotonic() + AUTH_WAIT_SECONDS
    runtime_retry_deadline = min(deadline, time.monotonic() + RUNTIME_RETRY_SECONDS)
    while time.monotonic() < deadline:
        try:
            result = _call_with_gate(
                connection,
                "Runtime.evaluate",
                {
                    "expression": _AUTH_EXPRESSION,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
                gate,
            )
        except _CDPCommandError as exc:
            gate.raise_if_blocked()
            if not exc.retryable or time.monotonic() >= runtime_retry_deadline:
                raise
            time.sleep(POLL_SECONDS)
            continue
        identifier = _evaluated_identifier(result)
        if identifier is not None:
            return identifier
        time.sleep(POLL_SECONDS)
    gate.raise_if_any_blocked()
    raise AuthenticationError("LEARN login was not verified before the authentication timeout")


def _runtime_error_is_transient(method: str, error: dict[str, Any]) -> bool:
    """Recognize only Chromium's navigation/context race for bounded evaluation retry."""

    if method != "Runtime.evaluate" or error.get("code") != -32000:
        return False
    message = error.get("message")
    if not isinstance(message, str):
        return False
    lowered = message.casefold()
    return "target" in lowered or "context" in lowered


def _evaluated_identifier(result: dict[str, Any]) -> str | None:
    outer = result.get("result")
    if not isinstance(outer, dict):
        return None
    value = outer.get("value")
    if not isinstance(value, dict) or value.get("ok") is not True:
        return None
    identifier = value.get("identifier")
    return identifier if isinstance(identifier, str) and identifier else None


def _close_owned_browser(
    endpoint: DebugEndpoint,
    process: _OwnedProcess | None,
    *,
    profile: Path | None = None,
) -> None:
    if process is None:
        return
    connection: _CDPConnection | None = None
    try:
        connection = _CDPConnection(endpoint.browser_websocket_url)
        connection.call("Browser.close")
    except AuthenticationError:
        # The DevTools connection can disappear before Browser.close reaches Chromium.  The
        # process is still ours, so always fall through to the bounded OS-level cleanup below.
        pass
    finally:
        if connection is not None:
            connection.close()
    try:
        process.wait(timeout=ENDPOINT_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_owned_process(process)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthenticationError("dedicated browser process status could not be read") from exc
    if profile is not None:
        _remove_owned_active_port(profile, endpoint)


def _remove_owned_active_port(profile: Path, endpoint: DebugEndpoint) -> None:
    """Remove only this launch's marker after its owned process has exited.

    A marker seen before a launch is never cleaned here.  This helper is reached only with an
    endpoint that was validated while this process was the owner, and it additionally compares
    both the assigned port and Chromium's browser websocket path immediately before unlinking.
    """

    active_port = profile / "DevToolsActivePort"
    if paths.is_link(active_port):
        return
    marker = _read_active_port_marker(active_port)
    endpoint_path = _websocket_path(endpoint.browser_websocket_url)
    if marker is None or endpoint_path is None:
        return
    if marker.port != endpoint.port or marker.browser_websocket_path != endpoint_path:
        return
    if paths.is_link(active_port):
        return
    try:
        os.unlink(os.fspath(paths.long_path(active_port)))
    except FileNotFoundError:
        return
    except OSError:
        # Cleanup is best-effort.  A foreign process or platform service may have replaced/opened
        # the marker after our process exited; never turn that race into a broad deletion attempt.
        return


def _terminate_owned_process(process: _OwnedProcess) -> None:
    """Bound cleanup for a browser process Agent2Learn launched itself."""
    with suppress(OSError, subprocess.SubprocessError):
        process.terminate()
    try:
        process.wait(timeout=ENDPOINT_WAIT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthenticationError("dedicated browser process status could not be read") from exc

    try:
        process.kill()
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthenticationError(
            "dedicated browser could not be terminated after session harvest"
        ) from exc
    try:
        process.wait(timeout=ENDPOINT_WAIT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise AuthenticationError("dedicated browser did not close after session harvest") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthenticationError("dedicated browser process status could not be read") from exc


def _get_json(port: int, route: str) -> dict[str, Any]:
    response = _local_request(port, route)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthenticationError("DevTools endpoint returned invalid metadata") from exc
    finally:
        response.close()
    if not isinstance(payload, dict):
        raise AuthenticationError("DevTools endpoint returned invalid metadata")
    return payload


def _get_json_list(port: int, route: str) -> list[dict[str, Any]]:
    response = _local_request(port, route)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthenticationError("DevTools endpoint returned invalid target metadata") from exc
    finally:
        response.close()
    if not isinstance(payload, list):
        raise AuthenticationError("DevTools endpoint returned invalid target metadata")
    return [item for item in payload if isinstance(item, dict)]


def _local_request(port: int, route: str) -> requests.Response:
    transport = requests.Session()
    transport.trust_env = False
    try:
        response = transport.get(
            f"http://127.0.0.1:{port}{route}",
            timeout=CDP_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise AuthenticationError("dedicated browser DevTools endpoint is unreachable") from exc
    if not 200 <= response.status_code < 300:
        response.close()
        raise AuthenticationError("dedicated browser DevTools endpoint rejected the request")
    return response


def _loopback_url(value: str, expected_port: int) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme.casefold() not in {"ws", "wss"} or parsed.hostname is None:
        return False
    if parsed.hostname.casefold() not in {"127.0.0.1", "localhost", "::1"}:
        return False
    return port == expected_port


def _auth_url_allowed(value: str, school: School) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "https" or parsed.hostname is None:
            return False
        host = _canonical_hostname(parsed.hostname)
        base = urlsplit(school.base_url)
        base_port = base.port or 443
        target_port = parsed.port or 443
        if host == _canonical_hostname(base.hostname or "") and target_port == base_port:
            return True
        return target_port == 443 and any(
            _host_boundary_match(host, _canonical_hostname(_host_from_value(item)))
            for item in school.auth_hosts()
        )
    except (TypeError, ValueError, UnicodeError):
        return False


def _host_from_value(value: str) -> str:
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlsplit(candidate)
    if parsed.hostname is None:
        raise ValueError
    return parsed.hostname


def _host_boundary_match(host: str, allowed: str) -> bool:
    return host == allowed or host.endswith(f".{allowed}")


def _safe_hostname(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.hostname is None:
            return "unknown-host"
        return _canonical_hostname(parsed.hostname)
    except (TypeError, ValueError, UnicodeError):
        return "unknown-host"


def _canonical_hostname(value: str) -> str:
    return value.rstrip(".").encode("idna").decode("ascii").casefold()


def _windows_browser_paths() -> list[Path]:
    if os.name != "nt":
        return []
    paths: list[Path] = []
    try:
        import importlib

        winreg: Any = importlib.import_module("winreg")

        for executable in ("chrome.exe", "msedge.exe"):
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for subkey in (
                    rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}",
                    rf"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"
                    f"\\{executable}",
                ):
                    try:
                        with winreg.OpenKey(root, subkey) as key:
                            value, _ = winreg.QueryValueEx(key, None)
                    except OSError:
                        continue
                    if isinstance(value, str):
                        paths.append(Path(value))
    except ImportError:  # pragma: no cover - winreg exists on Windows
        return paths
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if not root:
            continue
        paths.extend(
            Path(root) / relative
            for relative in (
                "Google/Chrome/Application/chrome.exe",
                "Microsoft/Edge/Application/msedge.exe",
            )
        )
    return paths


def datetime_now() -> datetime:
    """Keep the timestamp construction in one tiny seam for deterministic unit tests."""

    return datetime.now(UTC)


__all__ = [
    "AUTH_WAIT_SECONDS",
    "CDP_TIMEOUT",
    "ENDPOINT_WAIT_SECONDS",
    "DebugEndpoint",
    "DedicatedPageFactory",
    "authenticate_browser",
    "locate_browser",
    "profile_path",
]
