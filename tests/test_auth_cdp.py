"""Security and lifecycle tests for the dedicated Chromium authentication path."""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from agent2learn import auth, config
from agent2learn.auth import cdp
from agent2learn.errors import AuthenticationError
from agent2learn.schools import UWaterloo
from agent2learn.session import Session


def _session() -> Session:
    from agent2learn.session import SessionCookie

    return Session(
        base_url="https://learn.example.invalid",
        cookies=(
            SessionCookie(
                name="d2lSessionVal",
                value="session-token",
                domain=".learn.example.invalid",
                path="/d2l",
                secure=True,
            ),
            SessionCookie(
                name="d2lSecureSessionVal",
                value="secure-token",
                domain=".learn.example.invalid",
                path="/d2l",
                secure=True,
            ),
        ),
        xsrf=None,
        harvested_at=datetime(2026, 8, 25, tzinfo=UTC),
        user_id=None,
    )


def test_auth_url_allowlist_is_exact_and_boundary_aware() -> None:
    school = SimpleNamespace(
        base_url="https://learn.example.invalid",
        auth_hosts=lambda: ["login.example.invalid", "xn--bcher-kva.example"],
    )

    assert cdp._auth_url_allowed("https://learn.example.invalid/d2l/home", school)
    assert cdp._auth_url_allowed("https://sso.login.example.invalid/path", school)
    assert cdp._auth_url_allowed("https://BÜCHER.EXAMPLE/identity", school)
    assert not cdp._auth_url_allowed("https://learn.example.invalid.evil/path", school)
    assert not cdp._auth_url_allowed("https://notlogin.example.invalid/path", school)
    assert not cdp._auth_url_allowed("http://login.example.invalid/path", school)


def test_waterloo_auth_allowlist_accepts_observed_duo_host_only_at_https_default_port() -> None:
    school = UWaterloo()

    assert cdp._auth_url_allowed("https://sso-tenant.sso.duosecurity.com/frame", school)
    assert cdp._auth_url_allowed("https://api-tenant.duosecurity.com/frame", school)
    assert cdp._auth_url_allowed("https://ux-asset-commercial.duosecurity.com/frame", school)
    assert cdp._auth_url_allowed("https://uwaterloo.login.duosecurity.com/frame", school)
    assert cdp._auth_url_allowed("https://adfs.uwaterloo.ca/adfs/login", school)
    assert not cdp._auth_url_allowed(
        "https://sso-tenant.sso.duosecurity.com.evil.invalid/frame", school
    )
    assert not cdp._auth_url_allowed("http://sso-tenant.sso.duosecurity.com/frame", school)
    assert not cdp._auth_url_allowed("https://sso-tenant.sso.duosecurity.com:8443/frame", school)
    assert not cdp._auth_url_allowed(
        "https://uwaterloo.login.duosecurity.com.evil.invalid/frame", school
    )
    assert not cdp._auth_url_allowed(
        "https://api-tenant.duosecurity.com.evil.invalid/frame", school
    )
    assert not cdp._auth_url_allowed("https://api-tenant.duosecurity.com:8443/frame", school)
    assert not cdp._auth_url_allowed("https://notduosecurity.com/frame", school)
    assert not cdp._auth_url_allowed("https://adfs.uwaterloo.ca.evil.invalid/adfs/login", school)
    assert not cdp._auth_url_allowed("http://adfs.uwaterloo.ca/adfs/login", school)
    assert not cdp._auth_url_allowed("https://adfs.uwaterloo.ca:8443/adfs/login", school)


@pytest.mark.parametrize(
    ("browser", "accepted"),
    [
        ("Chrome/151.0.7922.174", True),
        ("Google Chrome/136.0.0.0", True),
        ("Chromium/136.0.0.0", True),
        ("Microsoft Edge/136.0.0.0", True),
        ("Edg/136.0.0.0", True),
        ("Not Google Chrome/136.0.0.0", False),
        ("Google Chrome Evil/136.0.0.0", False),
        ("ChromeEvil/136.0.0.0", False),
        ("Chrome/", False),
        ("Chrome/not-a-version", False),
    ],
)
def test_browser_metadata_accepts_real_products_without_lookalikes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    browser: str,
    accepted: bool,
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43123\n/devtools/browser/synthetic\n", encoding="utf-8")
    monkeypatch.setattr(
        cdp,
        "_get_json",
        lambda _port, _route: {
            "Browser": browser,
            "webSocketDebuggerUrl": "ws://127.0.0.1:43123/devtools/browser/synthetic",
        },
    )
    monkeypatch.setattr(cdp, "_process_owns_profile", lambda _profile, _port: True)

    if accepted:
        assert cdp._read_valid_endpoint(active, profile=profile).port == 43123
    else:
        with pytest.raises(AuthenticationError, match="expected Chrome/Edge"):
            cdp._read_valid_endpoint(active, profile=profile)


def test_auth_gate_fails_external_request_and_reports_only_sanitized_host() -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    class FakeConnection:
        def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
            sent.append((method, params or {}))

    gate = cdp._AuthGate(FakeConnection(), UWaterloo())
    gate.handle(
        {
            "method": "Fetch.requestPaused",
            "params": {
                "requestId": "request-1",
                "resourceType": "Document",
                "request": {
                    "url": "https://evil.example.invalid/login?token=secret-value",
                },
            },
        }
    )

    with pytest.raises(AuthenticationError, match="evil.example.invalid") as raised:
        gate.raise_if_blocked()
    assert "secret-value" not in str(raised.value)
    assert sent == [
        (
            "Fetch.failRequest",
            {"requestId": "request-1", "errorReason": "BlockedByClient"},
        )
    ]


def test_auth_gate_continues_or_fails_each_paused_request_exactly_once() -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    class FakeConnection:
        def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
            sent.append((method, params or {}))

    school = SimpleNamespace(
        base_url="https://learn.example.invalid",
        auth_hosts=lambda: ["login.example.invalid"],
    )
    gate = cdp._AuthGate(FakeConnection(), school)

    allowed = {
        "method": "Fetch.requestPaused",
        "params": {
            "requestId": "allowed-1",
            "request": {"url": "https://login.example.invalid/sso"},
        },
    }
    blocked = {
        "method": "Fetch.requestPaused",
        "params": {
            "requestId": "blocked-1",
            "request": {"url": "https://evil.example.invalid/sso?token=secret"},
        },
    }
    malformed = {
        "method": "Fetch.requestPaused",
        "params": {"requestId": "malformed-1"},
    }

    for event in (allowed, allowed, blocked, blocked, malformed, malformed):
        gate.handle(event)

    assert sent == [
        ("Fetch.continueRequest", {"requestId": "allowed-1"}),
        ("Fetch.failRequest", {"requestId": "blocked-1", "errorReason": "BlockedByClient"}),
        ("Fetch.failRequest", {"requestId": "malformed-1", "errorReason": "BlockedByClient"}),
    ]
    with pytest.raises(AuthenticationError, match="evil.example.invalid") as raised:
        gate.raise_if_blocked()
    assert "secret" not in str(raised.value)


def test_auth_gate_blocks_optional_subresource_without_aborting_navigation() -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    class FakeConnection:
        def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
            sent.append((method, params or {}))

    gate = cdp._AuthGate(
        FakeConnection(),
        SimpleNamespace(base_url="https://learn.example.invalid", auth_hosts=lambda: []),
    )
    gate.handle(
        {
            "method": "Fetch.requestPaused",
            "params": {
                "requestId": "analytics-ping",
                "resourceType": "XHR",
                "request": {"url": "https://analytics.example.invalid/beacon"},
            },
        }
    )

    gate.raise_if_blocked()
    with pytest.raises(AuthenticationError, match="analytics.example.invalid"):
        gate.raise_if_any_blocked()
    assert sent == [
        (
            "Fetch.failRequest",
            {"requestId": "analytics-ping", "errorReason": "BlockedByClient"},
        )
    ]


def test_new_browser_uses_persistent_loopback_profile_and_ephemeral_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    executable = tmp_path / "chrome"
    executable.write_bytes(b"synthetic executable")
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            return

        def kill(self) -> None:
            return

    process: cdp._OwnedProcess = FakeProcess()

    def fake_popen(args: list[str], **kwargs: object) -> cdp._OwnedProcess:
        calls.append((args, kwargs))
        (profile / "DevToolsActivePort").write_text("43123\n/devtools/browser/synthetic\n")
        return process

    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    monkeypatch.setattr(cdp, "locate_browser", lambda: executable)
    monkeypatch.setattr(cdp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cdp, "_read_valid_endpoint", lambda _path, **_kwargs: endpoint)
    monkeypatch.setattr(cdp, "POLL_SECONDS", 0)

    actual, owner, owned = cdp._acquire_endpoint(profile)

    assert actual == endpoint
    assert owner is process
    assert owned is True
    assert calls[0][0] == [
        str(executable),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    assert calls[0][1]["stdin"] is cdp.subprocess.DEVNULL


def test_owned_browser_is_terminated_when_endpoint_acquisition_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    executable = tmp_path / "chrome"
    executable.write_bytes(b"synthetic executable")

    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.wait_calls = 0

        def terminate(self) -> None:
            self.terminated = True

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.wait_calls += 1
            return 0

    process = FakeProcess()
    monkeypatch.setattr(cdp, "locate_browser", lambda: executable)
    monkeypatch.setattr(cdp.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(cdp, "ENDPOINT_WAIT_SECONDS", 0)

    with pytest.raises(AuthenticationError, match="DevTools endpoint"):
        cdp._acquire_endpoint(profile)

    assert process.terminated is True
    assert process.wait_calls == 1


def test_dedicated_page_factory_creates_a_fresh_target_per_outline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    acquired: list[Path] = []
    events: list[str] = []

    def acquire(profile: Path) -> tuple[cdp.DebugEndpoint, None, bool]:
        acquired.append(profile)
        return endpoint, None, False

    class FakeConnection:
        def __init__(self, url: str) -> None:
            self.url = url
            events.append(f"connect:{url}")

        def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
            if method == "Target.createTarget":
                number = sum(event.startswith("create:") for event in events) + 1
                target_id = f"target-{number}"
                events.append(f"create:{target_id}")
                return {"targetId": target_id}
            if method == "Target.closeTarget":
                assert params is not None
                events.append(f"close-target:{params['targetId']}")
                return {"success": True}
            events.append(method)
            return {}

        def close(self) -> None:
            events.append(f"close:{self.url}")

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cdp, "_acquire_endpoint", acquire)
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)
    monkeypatch.setattr(
        cdp,
        "_wait_for_target",
        lambda port, target_id: f"ws://127.0.0.1:{port}/devtools/page/{target_id}",
    )

    factory = cdp.DedicatedPageFactory()
    first = factory.open_page()
    first.close_target()
    second = factory.open_page()
    second.close_target()
    factory.close()

    assert acquired == [tmp_path / "browser-profile"]
    assert first is not second
    assert events.count("create:target-1") == 1
    assert events.count("create:target-2") == 1
    assert events.count("close-target:target-1") == 1
    assert events.count("close-target:target-2") == 1
    assert events.index("close-target:target-1") < events.index("create:target-2")


def test_existing_valid_endpoint_is_reused_without_launching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43123\n/devtools/browser/synthetic\n")
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    monkeypatch.setattr(cdp, "_read_valid_endpoint", lambda _path, **_kwargs: endpoint)

    def fail_launch(**_kwargs: object) -> None:
        raise AssertionError("a valid dedicated endpoint must be reused")

    monkeypatch.setattr(cdp.subprocess, "Popen", fail_launch)
    actual, owner, owned = cdp._acquire_endpoint(profile)

    assert actual == endpoint
    assert owner is None
    assert owned is False


def test_owned_browser_is_terminated_when_cdp_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")

    class FakeConnection:
        def __init__(self, _url: str) -> None:
            pass

        def call(self, _method: str) -> dict[str, object]:
            raise AuthenticationError("synthetic CDP failure")

        def close(self) -> None:
            return

    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.wait_calls = 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.wait_calls += 1
            if not self.terminated:
                raise cdp.subprocess.TimeoutExpired("browser", 1)
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            self.terminated = True

    process = FakeProcess()
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    cdp._close_owned_browser(endpoint, process)

    assert process.terminated is True
    assert process.wait_calls == 2


def test_owned_browser_removes_only_its_matching_active_port_after_shutdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43123\n/devtools/browser/synthetic\n", encoding="utf-8")
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    calls: list[str] = []

    class FakeConnection:
        def __init__(self, _url: str) -> None:
            return

        def call(self, method: str) -> dict[str, object]:
            calls.append(method)
            return {}

        def close(self) -> None:
            calls.append("socket.close")

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            raise AssertionError("a browser closed through CDP should not be terminated")

        def kill(self) -> None:
            raise AssertionError("a browser closed through CDP should not be killed")

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    cdp._close_owned_browser(endpoint, FakeProcess(), profile=profile)

    assert not active.exists()
    assert calls == ["Browser.close", "socket.close"]


def test_owned_browser_does_not_remove_a_mismatched_active_port_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43124\n/devtools/browser/foreign\n", encoding="utf-8")
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")

    class FakeConnection:
        def __init__(self, _url: str) -> None:
            return

        def call(self, _method: str) -> dict[str, object]:
            return {}

        def close(self) -> None:
            return

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            return

        def kill(self) -> None:
            return

        def poll(self) -> int | None:
            return 0

    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    cdp._close_owned_browser(endpoint, FakeProcess(), profile=profile)

    assert active.read_text(encoding="utf-8") == "43124\n/devtools/browser/foreign\n"


def test_repeated_owned_acquisitions_do_not_hit_a_stale_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    executable = tmp_path / "chrome"
    executable.write_bytes(b"synthetic executable")
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    launches = 0

    class FakeConnection:
        def __init__(self, _url: str) -> None:
            return

        def call(self, _method: str) -> dict[str, object]:
            return {}

        def close(self) -> None:
            return

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            raise AssertionError("CDP close should be sufficient")

        def kill(self) -> None:
            raise AssertionError("CDP close should be sufficient")

        def poll(self) -> int | None:
            return None

    def fake_popen(_args: list[str], **_kwargs: object) -> FakeProcess:
        nonlocal launches
        launches += 1
        active.write_text("43123\n/devtools/browser/synthetic\n", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(cdp, "locate_browser", lambda: executable)
    monkeypatch.setattr(cdp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cdp, "_read_valid_endpoint", lambda *_args, **_kwargs: endpoint)
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)
    monkeypatch.setattr(cdp, "POLL_SECONDS", 0)

    for _ in range(2):
        acquired, process, owned = cdp._acquire_endpoint(profile)
        assert acquired == endpoint
        assert owned is True
        cdp._close_owned_browser(acquired, process, profile=profile)

    assert launches == 2
    assert not active.exists()


def test_stale_foreign_endpoint_is_refused_without_cleanup_or_relaunch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43123\n/devtools/browser/foreign\n", encoding="utf-8")
    monkeypatch.setattr(
        cdp,
        "_read_valid_endpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AuthenticationError("stale endpoint")),
    )
    monkeypatch.setattr(
        cdp,
        "locate_browser",
        lambda: (_ for _ in ()).throw(AssertionError("foreign marker must not relaunch")),
    )

    with pytest.raises(AuthenticationError, match="stale endpoint"):
        cdp._acquire_endpoint(profile)

    assert active.exists()


@pytest.mark.parametrize("marker", cdp._LOCK_MARKERS)
def test_profile_lock_without_endpoint_is_refused_without_relaunch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, marker: str
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / marker).write_text("foreign-lock", encoding="utf-8")
    monkeypatch.setattr(
        cdp,
        "locate_browser",
        lambda: (_ for _ in ()).throw(AssertionError("locked profile must not relaunch")),
    )

    with pytest.raises(AuthenticationError, match="locked"):
        cdp._acquire_endpoint(profile)


def test_authenticate_browser_uses_ordered_domains_and_closes_everything_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text(
        "43123\n/devtools/browser/synthetic\n", encoding="utf-8"
    )
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    page_url = "ws://127.0.0.1:43123/devtools/page/page-1"
    calls: list[str] = []
    decisions: list[tuple[str, str]] = []

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            raise AssertionError("CDP close should be sufficient")

        def kill(self) -> None:
            raise AssertionError("CDP close should be sufficient")

        def poll(self) -> int | None:
            return 0

    class FakeConnection:
        def __init__(self, url: str) -> None:
            self.url = url

        def call(
            self,
            method: str,
            params: dict[str, object] | None = None,
            *,
            event_handler: object = None,
        ) -> dict[str, object]:
            calls.append(method)
            if method == "Page.navigate":
                assert callable(event_handler)
                event_handler(
                    {
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": "navigate",
                            "request": {"url": "https://learn.example.invalid/d2l/home"},
                        },
                    }
                )
            elif method == "Runtime.evaluate":
                assert params is not None
                assert params["awaitPromise"] is True
                assert params["returnByValue"] is True
                assert callable(event_handler)
                event_handler(
                    {
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": "whoami",
                            "request": {
                                "url": "https://learn.example.invalid/d2l/api/lp/1.62/users/whoami"
                            },
                        },
                    }
                )
                event_handler(
                    {
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": "analytics",
                            "resourceType": "XHR",
                            "request": {"url": "https://analytics.example.invalid/beacon"},
                        },
                    }
                )
                return {"result": {"value": {"ok": True, "identifier": "stable-id"}}}
            elif method == "Storage.getCookies":
                return {
                    "cookies": [
                        {
                            "name": "d2lSessionVal",
                            "value": "session-token",
                            "domain": ".learn.example.invalid",
                            "path": "/d2l",
                            "secure": True,
                        },
                        {
                            "name": "d2lSecureSessionVal",
                            "value": "secure-token",
                            "domain": ".learn.example.invalid",
                            "path": "/d2l",
                            "secure": True,
                        },
                    ]
                }
            elif method == "Browser.close":
                assert self.url == endpoint.browser_websocket_url
            return {}

        def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
            decisions.append((method, str((params or {}).get("requestId"))))

        def close(self) -> None:
            calls.append("socket.close")

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cdp, "_acquire_endpoint", lambda _profile: (endpoint, FakeProcess(), True))
    monkeypatch.setattr(cdp, "_wait_for_page", lambda _port: page_url)
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    school = SimpleNamespace(
        base_url="https://learn.example.invalid",
        auth_hosts=lambda: [],
    )
    actual = cdp.authenticate_browser(school)

    assert actual.user_id == "stable-id"
    assert calls[:6] == [
        "Page.enable",
        "Network.enable",
        "Fetch.enable",
        "Page.navigate",
        "Runtime.evaluate",
        "Storage.getCookies",
    ]
    assert decisions == [
        ("Fetch.continueRequest", "navigate"),
        ("Fetch.continueRequest", "whoami"),
        ("Fetch.failRequest", "analytics"),
    ]
    assert calls[-2:] == ["Browser.close", "socket.close"]
    assert not (profile / "DevToolsActivePort").exists()


def test_authenticate_browser_closes_page_and_owned_process_after_runtime_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text(
        "43123\n/devtools/browser/synthetic\n", encoding="utf-8"
    )
    endpoint = cdp.DebugEndpoint(43123, "ws://127.0.0.1:43123/devtools/browser/synthetic")
    events: list[str] = []

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            del timeout
            events.append("process.wait")
            return 0

        def terminate(self) -> None:
            events.append("process.terminate")

        def kill(self) -> None:
            events.append("process.kill")

        def poll(self) -> int | None:
            return 0

    class FakeConnection:
        def __init__(self, url: str) -> None:
            self.url = url

        def call(
            self,
            method: str,
            _params: dict[str, object] | None = None,
            *,
            event_handler: object = None,
        ) -> dict[str, object]:
            del event_handler
            events.append(method)
            if method == "Runtime.evaluate":
                raise AuthenticationError("browser DevTools command failed: Runtime.evaluate")
            return {}

        def close(self) -> None:
            events.append("socket.close")

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cdp, "_acquire_endpoint", lambda _profile: (endpoint, FakeProcess(), True))
    monkeypatch.setattr(cdp, "_wait_for_page", lambda _port: "ws://127.0.0.1:43123/devtools/page/1")
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    with pytest.raises(AuthenticationError, match="Runtime.evaluate"):
        cdp.authenticate_browser(
            SimpleNamespace(base_url="https://learn.example.invalid", auth_hosts=lambda: [])
        )

    assert events.index("Runtime.evaluate") < events.index("socket.close")
    assert events.count("Browser.close") == 1
    assert events.count("process.wait") == 1
    assert not (profile / "DevToolsActivePort").exists()


def test_blocked_fetch_during_runtime_evaluate_is_reported_as_host_not_cdp_failure() -> None:
    class FakeConnection:
        def send_without_wait(self, _method: str, _params: dict[str, object] | None = None) -> None:
            return

        def call(
            self,
            method: str,
            _params: dict[str, object] | None = None,
            *,
            event_handler: object = None,
        ) -> dict[str, object]:
            assert method == "Runtime.evaluate"
            assert callable(event_handler)
            event_handler(
                {
                    "method": "Fetch.requestPaused",
                    "params": {
                        "requestId": "duo-request",
                        "request": {
                            "url": "https://sso-123.sso.duosecurity.com/frame?token=secret"
                        },
                    },
                }
            )
            raise AuthenticationError("browser DevTools command failed: Runtime.evaluate")

    gate = cdp._AuthGate(
        FakeConnection(),
        SimpleNamespace(base_url="https://learn.example.invalid", auth_hosts=lambda: []),
    )

    with pytest.raises(AuthenticationError, match="sso-123.sso.duosecurity.com") as raised:
        cdp._wait_for_authenticated_page(FakeConnection(), gate)
    assert "secret" not in str(raised.value)


def test_blocked_fetch_during_page_navigate_is_reported_as_host_not_cdp_failure() -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    class FakeConnection:
        def send_without_wait(self, method: str, params: dict[str, object] | None = None) -> None:
            sent.append((method, params or {}))

        def call(
            self,
            _method: str,
            _params: dict[str, object] | None = None,
            *,
            event_handler: object = None,
        ) -> dict[str, object]:
            assert callable(event_handler)
            event_handler(
                {
                    "method": "Fetch.requestPaused",
                    "params": {
                        "requestId": "duo-navigation",
                        "request": {"url": "https://duo.example.invalid/login"},
                    },
                }
            )
            raise AuthenticationError("browser DevTools command failed: Page.navigate")

    gate = cdp._AuthGate(
        FakeConnection(),
        SimpleNamespace(base_url="https://learn.example.invalid", auth_hosts=lambda: []),
    )

    with pytest.raises(AuthenticationError, match="duo.example.invalid"):
        cdp._call_with_gate(
            FakeConnection(), "Page.navigate", {"url": "https://learn.example.invalid"}, gate
        )
    assert sent == [
        (
            "Fetch.failRequest",
            {"requestId": "duo-navigation", "errorReason": "BlockedByClient"},
        )
    ]


def test_runtime_evaluate_retries_a_transient_navigation_context_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeConnection:
        def send_without_wait(self, _method: str, _params: dict[str, object] | None = None) -> None:
            return

        def call(
            self,
            method: str,
            _params: dict[str, object] | None = None,
            *,
            event_handler: object = None,
        ) -> dict[str, object]:
            calls.append(method)
            if method == "Runtime.evaluate" and calls.count(method) == 1:
                raise cdp._CDPCommandError(method, retryable=True)
            return {"result": {"value": {"ok": True, "identifier": "stable-id"}}}

    monkeypatch.setattr(cdp, "POLL_SECONDS", 0)
    gate = cdp._AuthGate(
        FakeConnection(),
        SimpleNamespace(base_url="https://learn.example.invalid", auth_hosts=lambda: []),
    )

    assert cdp._wait_for_authenticated_page(FakeConnection(), gate) == "stable-id"
    assert calls == ["Runtime.evaluate", "Runtime.evaluate"]


def test_existing_endpoint_requires_the_expected_profile_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    active = profile / "DevToolsActivePort"
    active.write_text("43123\n/devtools/browser/synthetic\n")
    monkeypatch.setattr(
        cdp,
        "_get_json",
        lambda _port, _route: {
            "Browser": "Google Chrome/136.0",
            "webSocketDebuggerUrl": "ws://127.0.0.1:43123/devtools/browser/synthetic",
        },
    )
    monkeypatch.setattr(
        cdp,
        "_running_process_commands",
        lambda: [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            "--user-data-dir=/other-profile --remote-debugging-port=0"
        ],
    )

    with pytest.raises(AuthenticationError, match="profile"):
        cdp._read_valid_endpoint(active, profile=profile)


def test_profile_process_matching_rejects_lookalike_profile_and_port_values(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "browser-profile"
    lookalike_profile = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        f"--user-data-dir={profile}-evil --remote-debugging-port=431230"
    )
    lookalike_port = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        f"--user-data-dir={profile} --remote-debugging-port=431230"
    )

    assert not cdp._command_matches_profile(lookalike_profile, profile, 43123)
    assert not cdp._command_matches_profile(lookalike_port, profile, 43123)


@pytest.mark.skipif(os.name == "nt", reason="directory symlinks require Windows privileges")
def test_acquire_endpoint_refuses_a_symlinked_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-profile"
    outside.mkdir()
    profile = tmp_path / "browser-profile"
    profile.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(cdp, "locate_browser", lambda: Path("chrome"))

    with pytest.raises(AuthenticationError, match="symlink"):
        cdp._acquire_endpoint(profile)


def test_verify_uses_discovered_versions_and_returns_only_stable_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Response:
        def __init__(self, payload: object) -> None:
            self.status_code = 200
            self.headers = {"Content-Type": "application/json"}
            self._payload = payload

        def json(self) -> object:
            return self._payload

        def close(self) -> None:
            return

    class Transport:
        def __init__(self) -> None:
            self.trust_env = True
            self.cookies = requests.cookies.RequestsCookieJar()

        def get(self, url: str, **_kwargs: object) -> Response:
            calls.append(url)
            if url.endswith("/d2l/api/versions/"):
                return Response(
                    [
                        {
                            "ProductCode": "lp",
                            "LatestVersion": "1.62",
                            "SupportedVersions": ["1.60", "1.61"],
                        }
                    ]
                )
            return Response(
                {
                    "FirstName": "Do not return me",
                    "Identifier": "stable-123",
                    "LastName": "Do not return me",
                }
            )

    monkeypatch.setattr(auth.requests, "Session", Transport)
    identifier = auth.verify(_session(), SimpleNamespace(base_url="https://learn.example.invalid"))

    assert identifier == "stable-123"
    assert calls == [
        "https://learn.example.invalid/d2l/api/versions/",
        "https://learn.example.invalid/d2l/api/lp/1.62/users/whoami",
    ]


def test_authentication_orchestration_redacts_untrusted_cdp_errors_and_controls_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent2learn.auth import cdp as cdp_module

    monkeypatch.setattr(
        cdp_module,
        "authenticate_browser",
        lambda _school: (_ for _ in ()).throw(
            AuthenticationError("Runtime.evaluate response body=secret-session-value")
        ),
    )

    with pytest.raises(AuthenticationError) as auto_error:
        auth.authenticate(UWaterloo(), backend="auto")
    assert str(auto_error.value) == (
        "dedicated browser authentication failed; fallback: a2l auth --paste"
    )
    assert "secret-session-value" not in str(auto_error.value)

    with pytest.raises(AuthenticationError) as cdp_error:
        auth.authenticate(UWaterloo(), backend="cdp")
    assert str(cdp_error.value) == "dedicated browser authentication failed"


def test_authentication_orchestration_preserves_only_a_sanitized_blocked_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent2learn.auth import cdp as cdp_module

    monkeypatch.setattr(
        cdp_module,
        "authenticate_browser",
        lambda _school: (_ for _ in ()).throw(
            AuthenticationError(
                "authentication stopped at undeclared host sso.example.invalid; "
                "request=https://sso.example.invalid/path?token=secret"
            )
        ),
    )

    with pytest.raises(AuthenticationError) as raised:
        auth.authenticate(UWaterloo(), backend="cdp")

    assert str(raised.value) == "authentication stopped at undeclared host sso.example.invalid"
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "content_type", "payload", "whoami"),
    [
        (403, "text/html", "<html>login</html>", None),
        (200, "application/json", {"not": "a list"}, None),
        (
            200,
            "application/json",
            [{"ProductCode": "lp", "LatestVersion": "1.62"}],
            (500, {}, None),
        ),
        (
            200,
            "application/json",
            [{"ProductCode": "lp", "LatestVersion": "1.62"}],
            (200, {}, ValueError()),
        ),
        (
            200,
            "application/json",
            [{"ProductCode": "lp", "LatestVersion": "1.62"}],
            (200, {}, {"Identifier": ""}),
        ),
    ],
)
def test_verify_rejects_unauthenticated_errors_and_malformed_whoami(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    content_type: str,
    payload: object,
    whoami: tuple[int, dict[str, str], object] | None,
) -> None:
    class Response:
        def __init__(self, response_status: int, headers: dict[str, str], value: object) -> None:
            self.status_code = response_status
            self.headers = headers
            self._value = value

        def json(self) -> object:
            if isinstance(self._value, BaseException):
                raise self._value
            return self._value

        def close(self) -> None:
            return

    class Transport:
        def __init__(self) -> None:
            self.trust_env = True
            self.cookies = requests.cookies.RequestsCookieJar()
            self.calls = 0

        def get(self, _url: str, **_kwargs: object) -> Response:
            self.calls += 1
            if self.calls == 1:
                return Response(status, {"Content-Type": content_type}, payload)
            if whoami is None:
                raise AssertionError("whoami must not be requested after invalid versions")
            return Response(whoami[0], whoami[1], whoami[2])

    monkeypatch.setattr(auth.requests, "Session", Transport)

    assert (
        auth.verify(_session(), SimpleNamespace(base_url="https://learn.example.invalid")) is None
    )


def test_clear_profile_refuses_non_tty_without_deleting_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    cleared: list[bool] = []
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(auth.session, "clear", lambda: cleared.append(True))
    monkeypatch.setattr(auth.sys, "stdin", io.StringIO("yes\n"))
    monkeypatch.setattr(auth.sys, "stdout", io.StringIO())

    with pytest.raises(AuthenticationError, match="interactive confirmation"):
        auth.clear_profile()

    assert cleared == [True]
    assert profile.is_dir()


def test_clear_profile_reports_a_saved_session_removal_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)

    def refuse_clear() -> None:
        raise PermissionError("synthetic refusal")

    monkeypatch.setattr(auth.session, "clear", refuse_clear)

    with pytest.raises(AuthenticationError, match="saved API session could not be cleared"):
        auth.clear_profile()


def test_clear_profile_requires_yes_and_removes_only_dedicated_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "DuoTrust").write_text("synthetic", encoding="utf-8")

    class TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(auth.session, "clear", lambda: None)
    monkeypatch.setattr(auth.sys, "stdin", TTY("yes\n"))
    monkeypatch.setattr(auth.sys, "stdout", TTY())
    monkeypatch.setattr(auth.sys, "stderr", TTY())

    auth.clear_profile()

    assert not profile.exists()
