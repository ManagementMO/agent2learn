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

    process = FakeProcess()

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
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

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
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

    process = FakeProcess()
    monkeypatch.setattr(cdp, "_CDPConnection", FakeConnection)

    cdp._close_owned_browser(endpoint, process)  # type: ignore[arg-type]

    assert process.terminated is True
    assert process.wait_calls == 2


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
