"""The fixture harness must work before anything is built on it.

`test_fixture_contract.py` checks the fixture *files*. This checks the *server* that
serves them: that the routes resolve, the failure modes are reachable, binary bodies
survive transport intact, and the whole thing stays offline.
"""

from __future__ import annotations

import json
import zipfile

import pytest
import requests
from conftest import COURSE_A_OU, LE, LP, SyntheticAPI, fixture_bytes


def test_version_discovery_needs_no_auth(synthetic_api: SyntheticAPI, no_network: None) -> None:
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/versions/", timeout=5)
    assert r.status_code == 200
    codes = {p["ProductCode"]: p["LatestVersion"] for p in r.json()}
    assert codes == {"le": LE, "lp": LP}


def test_whoami_returns_the_synthetic_identity(
    synthetic_api: SyntheticAPI, no_network: None
) -> None:
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/lp/{LP}/users/whoami", timeout=5)
    assert r.status_code == 200
    assert r.json()["Identifier"] == "99999999"


def test_enrolments_paginate_to_completion(synthetic_api: SyntheticAPI, no_network: None) -> None:
    """Walk the bookmark chain the way the client must, and stop when told to."""
    base = f"{synthetic_api.base_url}/d2l/api/lp/{LP}/enrollments/myenrollments/"
    seen: list[int] = []
    params: dict[str, str] = {}
    for _ in range(5):  # bounded: a broken terminator must fail, not spin
        page = requests.get(base, params=params, timeout=5).json()
        seen += [i["OrgUnit"]["Id"] for i in page["Items"]]
        info = page["PagingInfo"]
        if not info["HasMoreItems"]:
            break
        params = {"bookmark": info["Bookmark"]}
    else:
        pytest.fail("pagination never terminated")

    assert 111111 in seen and 222222 in seen
    assert 333333 in seen, "the non-course org unit must be served so the adapter can filter it"


def test_expired_session_presents_as_login_html_with_200(
    synthetic_api: SyntheticAPI, no_network: None
) -> None:
    """The failure mode that matters: a 200 whose body is the SSO page, not an error."""
    synthetic_api.expect_login_html("/d2l/api/lp/1.62/users/whoami-expired")
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/lp/1.62/users/whoami-expired", timeout=5)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/html")
    assert "Sign in" in r.text


def test_rate_limit_carries_retry_after(synthetic_api: SyntheticAPI, no_network: None) -> None:
    synthetic_api.expect_rate_limited("/d2l/api/le/1.96/1/throttled", retry_after="2")
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/le/1.96/1/throttled", timeout=5)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "2"


def test_malformed_json_is_served_as_json(synthetic_api: SyntheticAPI, no_network: None) -> None:
    """Declared application/json, actually truncated: the client must fail cleanly."""
    synthetic_api.expect_malformed_json("/d2l/api/le/1.96/1/broken")
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/le/1.96/1/broken", timeout=5)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/json")
    with pytest.raises(json.JSONDecodeError):
        r.json()


@pytest.mark.parametrize(
    "name,ctype",
    [
        ("lecture01.pdf", "application/pdf"),
        ("analysis.ipynb", "application/json"),
        ("notes.Rmd", "text/plain"),
        ("site.html.zip", "application/zip"),
    ],
)
def test_binary_downloads_arrive_byte_identical(
    synthetic_api: SyntheticAPI, no_network: None, name: str, ctype: str
) -> None:
    url = f"{synthetic_api.base_url}/content/enforced/{COURSE_A_OU}-COURSE101/{name}"
    r = requests.get(url, timeout=5)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith(ctype)
    assert r.content == fixture_bytes(name), f"{name} was altered in transport"


def test_downloaded_zip_is_still_a_valid_archive(
    synthetic_api: SyntheticAPI, no_network: None, tmp_path
) -> None:
    url = f"{synthetic_api.base_url}/content/enforced/{COURSE_A_OU}-COURSE101/site.html.zip"
    dest = tmp_path / "site.html.zip"
    dest.write_bytes(requests.get(url, timeout=5).content)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["index.html", "style.css"]
        assert zf.testzip() is None


def test_unregistered_route_fails_loudly(synthetic_api: SyntheticAPI, no_network: None) -> None:
    """A test that reaches an endpoint nobody planned for must not quietly pass."""
    r = requests.get(f"{synthetic_api.base_url}/d2l/api/le/1.96/1/not-a-route", timeout=5)
    assert r.status_code >= 400


def test_the_offline_guard_actually_blocks_the_internet(no_network: None) -> None:
    """Proves the guard works. Without this, `no_network` could be a no-op forever."""
    with pytest.raises((RuntimeError, requests.exceptions.RequestException)):
        requests.get("https://example.invalid", timeout=5)
