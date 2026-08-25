"""Tests for the bounded, first-party D2L transport and calibration flow."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import requests
from conftest import COURSE_A_OU, LE, LP, SyntheticAPI, fixture_bytes
from werkzeug.wrappers import Response as WerkzeugResponse

from agent2learn import api, config
from agent2learn.calibrate import Calibration, calibrate, load_calibration
from agent2learn.errors import A2LError, NotConfigured, SessionExpired
from agent2learn.vault import ManifestEntry


@dataclass
class LocalSchool:
    base_url: str
    id: str = "synthetic"
    name: str = "Synthetic School"
    timezone: str = "UTC"
    auth_hint: str = "synthetic"

    def term_from_offering(self, code: str) -> str | None:
        return code.rsplit("_", 1)[-1] if code.rsplit("_", 1)[-1].isdigit() else None

    def term_label(self, term: str) -> str:
        return f"Term {term}"

    def auth_hosts(self) -> list[str]:
        return []

    def outline_hosts(self) -> list[str]:
        return []

    def topic_exclusion_policy(self) -> Any:
        return None


@dataclass
class LocalSession:
    base_url: str
    xsrf: str | None = None

    def requests_cookies(self) -> requests.cookies.RequestsCookieJar:
        return requests.cookies.RequestsCookieJar()


def _client(synthetic_api: SyntheticAPI) -> api.Client:
    school = LocalSchool(synthetic_api.base_url)
    session = LocalSession(synthetic_api.base_url)
    return api.Client(school, session)


def _prior() -> ManifestEntry:
    return ManifestEntry(
        path="COURSE/file.pdf",
        sha256="0" * 64,
        source_id="file",
        etag='"old"',
        last_modified="Tue, 25 Aug 2026 12:00:00 GMT",
        size=3,
        fetched_at="2026-08-25T12:00:00Z",
    )


def test_client_defaults_to_two_workers(synthetic_api: SyntheticAPI) -> None:
    assert _client(synthetic_api).workers == 2


def test_get_json_login_html_raises_session_expired(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    synthetic_api.expect_login_html("/expired")
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)

    with pytest.raises(SessionExpired, match="session expired"):
        _client(synthetic_api).get_json("/expired")


def test_get_json_retries_429_and_honours_retry_after(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    waits: list[float] = []

    def respond(request: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return WerkzeugResponse(
                "busy",
                status=429,
                headers={"Retry-After": "2", "Content-Type": "text/plain"},
            )
        return WerkzeugResponse('{"ok": true}', status=200, content_type="application/json")

    synthetic_api.server.expect_request("/throttled").respond_with_handler(respond)
    monkeypatch.setattr(api.time, "sleep", waits.append)

    assert _client(synthetic_api).get_json("/throttled") == {"ok": True}
    assert attempts == 2
    assert waits == [2.0, api.THROTTLE]


def test_html_binary_download_is_session_expiry_and_leaves_no_part(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.expect_login_html("/file.pdf")
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "file.pdf.part"

    with pytest.raises(SessionExpired):
        _client(synthetic_api).download(synthetic_api.base_url + "/file.pdf", part)

    assert not part.exists()


def test_zero_byte_download_leaves_no_part(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/empty").respond_with_data(
        b"", content_type="application/pdf"
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "empty.pdf.part"

    with pytest.raises(A2LError, match="empty"):
        _client(synthetic_api).download(synthetic_api.base_url + "/empty", part)

    assert not part.exists()


def test_valid_download_hashes_stream_and_fsyncs(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = fixture_bytes("lecture01.pdf")
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "lecture01.pdf.part"

    result = _client(synthetic_api).download(
        synthetic_api.base_url + f"/content/enforced/{COURSE_A_OU}-COURSE101/lecture01.pdf",
        part,
    )

    assert result.temp == part
    assert result.sha256 == __import__("hashlib").sha256(payload).hexdigest()
    assert result.size == len(payload)
    assert result.not_modified is False
    assert part.read_bytes() == payload


def test_conditional_download_uses_fingerprints_and_accepts_304(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, str] = {}

    def respond(request: Any) -> Any:
        seen["etag"] = request.headers.get("If-None-Match", "")
        seen["modified"] = request.headers.get("If-Modified-Since", "")
        return WerkzeugResponse(
            b"",
            status=304,
            headers={"ETag": '"old"', "Last-Modified": seen["modified"]},
        )

    synthetic_api.server.expect_request("/conditional").respond_with_handler(respond)
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "conditional.pdf.part"

    result = _client(synthetic_api).download(
        synthetic_api.base_url + "/conditional", part, prior=_prior()
    )

    assert seen == {
        "etag": '"old"',
        "modified": "Tue, 25 Aug 2026 12:00:00 GMT",
    }
    assert result == api.DownloadResult(
        temp=None,
        sha256="0" * 64,
        size=3,
        etag='"old"',
        last_modified="Tue, 25 Aug 2026 12:00:00 GMT",
        not_modified=True,
    )
    assert not part.exists()


def test_advertised_size_mismatch_leaves_no_part(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/wrong-size").respond_with_handler(
        lambda _request: WerkzeugResponse(
            iter([b"12345"]),
            headers={"Content-Length": "9", "Content-Type": "application/pdf"},
            direct_passthrough=True,
        )
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "wrong-size.pdf.part"

    with pytest.raises(A2LError, match="size"):
        _client(synthetic_api).download(synthetic_api.base_url + "/wrong-size", part)

    assert not part.exists()


def test_requests_use_explicit_connect_and_read_timeouts(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    response = requests.Response()
    response.status_code = 200
    response.url = synthetic_api.base_url + "/timeout"
    response.headers["Content-Type"] = "application/json"
    response._content = b'{"ok": true}'

    client = _client(synthetic_api)

    def request(**kwargs: Any) -> requests.Response:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(client._transport, "request", request)
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)

    assert client.get_json("/timeout") == {"ok": True}
    assert calls[0]["timeout"] == (api.CONNECT_TIMEOUT, api.READ_TIMEOUT)
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["headers"]["User-Agent"].startswith("agent2learn/0.1.0 ")


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retry_budget_is_five_attempts_and_retry_after_is_capped(
    synthetic_api: SyntheticAPI,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    attempts = 0
    waits: list[float] = []

    def respond(request: Any) -> Any:
        nonlocal attempts
        attempts += 1
        headers = {"Retry-After": "9999"} if status == 429 else {}
        return request.make_response("failure", status=status, headers=headers)

    synthetic_api.server.expect_request(f"/retry-{status}").respond_with_handler(respond)
    monkeypatch.setattr(api.time, "sleep", waits.append)

    with pytest.raises(requests.HTTPError):
        _client(synthetic_api).get_json(f"/retry-{status}")

    assert attempts == api.MAX_RETRIES
    assert waits
    assert max(waits) <= api.MAX_RETRY_AFTER


def test_body_ceiling_is_enforced_before_install(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/too-large").respond_with_data(
        b"0123456789", content_type="application/octet-stream"
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "too-large.bin.part"

    with pytest.raises(A2LError, match="ceiling"):
        _client(synthetic_api).download(synthetic_api.base_url + "/too-large", part, max_bytes=4)

    assert not part.exists()


def test_free_disk_reserve_is_enforced_before_stream(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/disk-full").respond_with_data(
        b"0123456789", content_type="application/octet-stream"
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(api, "FREE_DISK_RESERVE", 20)
    monkeypatch.setattr(
        api.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=100, used=95, free=5),
    )
    part = tmp_path / "disk-full.bin.part"

    with pytest.raises(A2LError, match="free disk"):
        _client(synthetic_api).download(synthetic_api.base_url + "/disk-full", part)

    assert not part.exists()


def test_mutating_request_does_not_enter_get_retry_loop(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    waits: list[float] = []

    def respond(request: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return WerkzeugResponse("failure", status=503)

    synthetic_api.server.expect_request("/mutating", method="POST").respond_with_handler(respond)
    monkeypatch.setattr(api.time, "sleep", waits.append)
    client = _client(synthetic_api)

    response = client._request(
        "POST", synthetic_api.base_url + "/mutating", mutating=True, stream=False
    )
    try:
        assert response.status_code == 503
    finally:
        response.close()
    assert attempts == 1
    assert waits == []


def test_external_url_is_rejected_before_any_request(
    synthetic_api: SyntheticAPI, tmp_path: Path
) -> None:
    client = _client(synthetic_api)
    part = tmp_path / "external.bin.part"

    with pytest.raises(api.EgressBlocked):
        client.download("https://example.invalid/course.pdf", part)

    assert not part.exists()


def test_allowed_redirect_is_followed_one_hop_at_a_time(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/start").respond_with_data(
        b"", status=302, headers={"Location": "/final"}
    )
    synthetic_api.server.expect_request("/final").respond_with_data(
        b"redirected", content_type="application/octet-stream"
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "redirected.bin.part"

    result = _client(synthetic_api).download(synthetic_api.base_url + "/start", part)

    assert result.size == len(b"redirected")
    assert part.read_bytes() == b"redirected"


def test_off_origin_redirect_is_rejected_before_target_request(
    synthetic_api: SyntheticAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic_api.server.expect_request("/off-origin").respond_with_data(
        b"", status=302, headers={"Location": "https://example.invalid/target"}
    )
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    part = tmp_path / "off-origin.bin.part"

    with pytest.raises(api.EgressBlocked):
        _client(synthetic_api).download(synthetic_api.base_url + "/off-origin", part)

    assert not part.exists()


def test_lookalike_and_mixed_case_idn_origins_are_not_confused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def request(self, **kwargs: Any) -> requests.Response:
            self.calls.append(kwargs["url"])
            response = requests.Response()
            response.status_code = 200
            response.url = kwargs["url"]
            response.headers["Content-Type"] = "application/json"
            response._content = b"{}"
            return response

    base = "https://Learn.Exämple"
    school = LocalSchool(base)
    session = LocalSession(base)
    client = api.Client(school, session)
    transport = FakeTransport()
    monkeypatch.setattr(client, "_transport", transport)

    assert client.get_json("https://LEARN.XN--EXMPLE-CUA/ok") == {}
    with pytest.raises(api.EgressBlocked):
        client.get_json("https://learn.exämple.evil/ok")
    with pytest.raises(api.EgressBlocked):
        client.get_json("https://learn.exämple@evil.example/ok")
    assert transport.calls == ["https://LEARN.XN--EXMPLE-CUA/ok"]


def test_calibration_discovers_versions_and_paginates_metadata_only(
    synthetic_api: SyntheticAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    result = calibrate(_client(synthetic_api))

    assert isinstance(result, Calibration)
    assert result.lp == LP
    assert result.le == LE
    assert result.download_template is None
    assert [(course.org_unit_id, course.code) for course in result.courses] == [
        (111111, "COURSE101_sec01_1261"),
        (222222, "COURSE202_sec02_1261"),
    ]
    assert (tmp_path / "calibration.json").is_file()
    raw = json.loads((tmp_path / "calibration.json").read_text(encoding="utf-8"))
    assert raw["lp"] == LP
    assert raw["le"] == LE
    assert "download_template" in raw
    assert "Identifier" not in raw


def test_unreadable_calibration_requires_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)

    with pytest.raises(NotConfigured, match="a2l auth"):
        load_calibration()
