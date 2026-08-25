"""Same-device authentication with a CDP path and a universal hidden-TTY fallback."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from agent2learn import __version__, config, session
from agent2learn.errors import AuthenticationError
from agent2learn.schools import School

from . import paste

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0


def authenticate(school: School, *, backend: str = "auto") -> session.Session:
    """Harvest, verify, and persist a minimum same-device LEARN API session.

    ``auto`` deliberately has only one fallback: the tested hidden-TTY paste flow.  It does not
    opportunistically select another browser automation stack or copy cookies from an everyday
    browser profile.
    """

    normalized_backend = backend.casefold()
    if normalized_backend == "paste":
        return _authenticate_from_paste(school)
    if normalized_backend not in {"auto", "cdp"}:
        raise AuthenticationError(f"unknown authentication backend: {backend}")

    from . import cdp

    try:
        harvested = cdp.authenticate_browser(school)
    except AuthenticationError as exc:
        if normalized_backend == "auto":
            raise AuthenticationError(f"{exc}; fallback: a2l auth --paste") from None
        raise

    stable_id = _verified_id_from_cdp_result(harvested)
    if stable_id is None:
        raise AuthenticationError("login could not be verified; try: a2l auth --paste")
    verified = _with_user_id(harvested, stable_id)
    session.store(verified)
    return verified


def verify(value: session.Session, school: School) -> str | None:
    """Return the stable D2L identifier after an authenticated, same-origin API check.

    The response is reduced immediately to ``Identifier``.  Display names and the rest of the
    response never enter the returned value or the persisted ``Session`` projection.
    """

    if _origin(value.base_url) != _origin(school.base_url):
        raise AuthenticationError("session and school must use the same HTTPS origin")

    transport = requests.Session()
    transport.trust_env = False
    transport.cookies.update(value.requests_cookies())
    headers = {
        "User-Agent": f"agent2learn/{__version__} (+https://github.com/ManagementMO/agent2learn)",
    }
    if value.xsrf:
        headers["X-Csrf-Token"] = value.xsrf

    versions_url = urljoin(value.base_url.rstrip("/") + "/", "d2l/api/versions/")
    try:
        versions_response = transport.get(
            versions_url,
            headers=headers,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            allow_redirects=False,
        )
    except requests.RequestException:
        return None
    try:
        if not 200 <= versions_response.status_code < 300:
            return None
        if "text/html" in versions_response.headers.get("Content-Type", "").casefold():
            return None
        versions = versions_response.json()
    except (ValueError, requests.RequestException):
        return None
    finally:
        versions_response.close()

    candidates = _lp_versions(versions)
    for version in candidates:
        whoami_url = urljoin(
            value.base_url.rstrip("/") + "/",
            f"d2l/api/lp/{version}/users/whoami",
        )
        try:
            response = transport.get(
                whoami_url,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                allow_redirects=False,
            )
        except requests.RequestException:
            continue
        try:
            if not 200 <= response.status_code < 300:
                continue
            if "text/html" in response.headers.get("Content-Type", "").casefold():
                continue
            payload = response.json()
        except (ValueError, requests.RequestException):
            continue
        finally:
            response.close()

        identifier = _stable_identifier(payload)
        if identifier is not None:
            return identifier
    return None


def clear_profile() -> None:
    """Clear the exported session and remove only the dedicated browser profile after consent."""

    session.clear()
    profile = config.data_dir() / "browser-profile"
    if profile.is_symlink():
        raise AuthenticationError(f"refusing to remove symlinked profile: {profile}")
    if _profile_is_locked(profile):
        raise AuthenticationError(
            f"dedicated browser profile is in use; close it normally before removing: {profile}"
        )
    if not profile.exists():
        return
    if not profile.is_dir():
        raise AuthenticationError(f"dedicated browser profile is not a directory: {profile}")
    if not _tty(sys.stdin) or not _tty(sys.stdout):
        raise AuthenticationError(
            f"profile removal requires an interactive confirmation for: {profile}"
        )

    sys.stderr.write(
        "This removes the dedicated Agent2Learn browser profile and its Waterloo/Duo "
        "remembered state:\n"
        f"  {profile}\n"
        "Type 'yes' to continue: "
    )
    sys.stderr.flush()
    answer = sys.stdin.readline().strip().casefold()
    sys.stderr.write("\n")
    if answer != "yes":
        raise AuthenticationError("profile removal cancelled")
    shutil.rmtree(profile)


def _authenticate_from_paste(school: School) -> session.Session:
    blob = paste.read_hidden_multiline()
    pending = paste.session_from_blob(blob, base_url=school.base_url)
    stable_id = verify(pending, school)
    if stable_id is None:
        raise AuthenticationError("login could not be verified; try: a2l auth --paste")
    verified = _with_user_id(pending, stable_id)
    session.store(verified)
    return verified


def _with_user_id(value: session.Session, stable_id: str) -> session.Session:
    return session.Session(
        base_url=value.base_url,
        cookies=value.cookies,
        xsrf=value.xsrf,
        harvested_at=value.harvested_at,
        user_id=stable_id,
    )


def _verified_id_from_cdp_result(value: object) -> str | None:
    if isinstance(value, session.Session):
        return value.user_id
    if isinstance(value, str) and value:
        return value
    return None


def _lp_versions(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        return ()
    found: list[str] = []
    for product in payload:
        if not isinstance(product, dict) or product.get("ProductCode") != "lp":
            continue
        versions: list[str] = []
        latest = product.get("LatestVersion")
        if isinstance(latest, str):
            versions.append(latest)
        supported = product.get("SupportedVersions")
        if isinstance(supported, list):
            versions.extend(value for value in supported if isinstance(value, str))
        for version in versions:
            if version and version not in found:
                found.append(version)
    return tuple(found)


def _stable_identifier(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("Identifier")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise AuthenticationError("authentication requires an HTTPS school origin")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise AuthenticationError("school origin has an invalid port") from exc
    return parsed.scheme.casefold(), parsed.hostname.rstrip(".").casefold(), port


def _profile_is_locked(profile: Path) -> bool:
    return any((profile / marker).exists() for marker in ("SingletonLock", "SingletonSocket"))


def _tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


__all__ = ["authenticate", "clear_profile", "verify"]
