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
from typing import Any
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
POLL_SECONDS = 0.5

_CHROMIUM_BASENAMES = ("Google Chrome", "Microsoft Edge", "Chromium")
_LOCK_MARKERS = ("SingletonLock", "SingletonSocket")
_AUTH_EXPRESSION = r"""
(async () => {
  try {
    const versionsResponse = await fetch("/d2l/api/versions/", {credentials: "include"});
    if (!versionsResponse.ok) return {ok: false};
    const products = await versionsResponse.json();
    const product = products.find((entry) => entry.ProductCode === "lp");
    if (!product) return {ok: false};
    const candidates = [product.LatestVersion, ...(product.SupportedVersions || [])]
      .filter(
        (value, index, values) => typeof value === "string" && values.indexOf(value) === index
      );
    for (const version of candidates) {
      const response = await fetch(`/d2l/api/lp/${version}/users/whoami`, {
        credentials: "include"
      });
      if (!response.ok) continue;
      const payload = await response.json();
      if (typeof payload.Identifier === "string" && payload.Identifier.length > 0) {
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
                    raise AuthenticationError(f"browser DevTools command failed: {method}")
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


class _AuthGate:
    def __init__(self, connection: _CDPConnection, school: School) -> None:
        self.connection = connection
        self.school = school
        self.blocked_host: str | None = None

    def handle(self, message: dict[str, Any]) -> None:
        if message.get("method") != "Fetch.requestPaused":
            return
        params = message.get("params")
        if not isinstance(params, dict):
            return
        request_id = params.get("requestId")
        request = params.get("request")
        if not isinstance(request_id, str) or not isinstance(request, dict):
            return
        target = request.get("url")
        if not isinstance(target, str):
            self.connection.send_without_wait(
                "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
            )
            self.blocked_host = "unknown-host"
            return

        if _auth_url_allowed(target, self.school):
            self.connection.send_without_wait("Fetch.continueRequest", {"requestId": request_id})
            return

        self.blocked_host = _safe_hostname(target)
        self.connection.send_without_wait(
            "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
        )

    def raise_if_blocked(self) -> None:
        if self.blocked_host is not None:
            raise AuthenticationError(
                f"authentication stopped at undeclared host {self.blocked_host}; "
                "fallback: a2l auth --paste"
            )


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
        page_connection.call(
            "Page.navigate",
            {"url": target},
            event_handler=gate.handle,
        )
        gate.raise_if_blocked()

        identifier = _wait_for_authenticated_page(page_connection, gate)
        cookies_result = page_connection.call("Storage.getCookies", event_handler=gate.handle)
        gate.raise_if_blocked()
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
        if page_connection is not None:
            page_connection.close()
        if owned:
            _close_owned_browser(endpoint, process)


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
            for name in _CHROMIUM_BASENAMES[:2]
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


def _acquire_endpoint(profile: Path) -> tuple[DebugEndpoint, subprocess.Popen[bytes] | None, bool]:
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
    try:
        with open(os.fspath(paths.long_path(active_port)), encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
        port = int(lines[0])
    except (OSError, ValueError, IndexError) as exc:
        raise AuthenticationError(
            "DevToolsActivePort is stale or invalid; close the dedicated browser normally: "
            f"{active_port}"
        ) from exc
    if not 1 <= port <= 65535:
        raise AuthenticationError(
            "DevToolsActivePort is stale or invalid; close the dedicated browser normally: "
            f"{active_port}"
        )

    metadata = _get_json(port, "/json/version")
    browser = metadata.get("Browser")
    websocket_url = metadata.get("webSocketDebuggerUrl")
    if not isinstance(browser, str) or not any(
        name.casefold() in browser.casefold() for name in _CHROMIUM_BASENAMES
    ):
        raise AuthenticationError("DevTools endpoint is not the expected Chrome/Edge process")
    if not isinstance(websocket_url, str) or not _loopback_url(websocket_url, port):
        raise AuthenticationError("DevTools endpoint is not a validated loopback browser endpoint")
    if process is None and not _process_owns_profile(profile, port):
        raise AuthenticationError("DevTools endpoint is not owned by the dedicated profile")
    return DebugEndpoint(port=port, browser_websocket_url=websocket_url)


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


def _wait_for_authenticated_page(connection: _CDPConnection, gate: _AuthGate) -> str:
    deadline = time.monotonic() + AUTH_WAIT_SECONDS
    while time.monotonic() < deadline:
        result = connection.call(
            "Runtime.evaluate",
            {
                "expression": _AUTH_EXPRESSION,
                "awaitPromise": True,
                "returnByValue": True,
            },
            event_handler=gate.handle,
        )
        gate.raise_if_blocked()
        identifier = _evaluated_identifier(result)
        if identifier is not None:
            return identifier
        time.sleep(POLL_SECONDS)
    raise AuthenticationError("LEARN login was not verified before the authentication timeout")


def _evaluated_identifier(result: dict[str, Any]) -> str | None:
    outer = result.get("result")
    if not isinstance(outer, dict):
        return None
    value = outer.get("value")
    if not isinstance(value, dict) or value.get("ok") is not True:
        return None
    identifier = value.get("identifier")
    return identifier if isinstance(identifier, str) and identifier else None


def _close_owned_browser(endpoint: DebugEndpoint, process: subprocess.Popen[bytes] | None) -> None:
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


def _terminate_owned_process(process: subprocess.Popen[bytes]) -> None:
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
    if parsed.scheme.casefold() not in {"http", "ws"} or parsed.hostname is None:
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
        return any(
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
    "authenticate_browser",
    "locate_browser",
    "profile_path",
]
