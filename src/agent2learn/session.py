"""Validated local session storage with a keyring-or-file fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.cookies import RequestsCookieJar

from agent2learn import config, paths

try:
    import keyring as _keyring
except Exception:  # pragma: no cover - exercised by environments without keyring installed
    keyring: Any = None
else:
    keyring = _keyring

_KEYRING_SERVICE = "agent2learn"
_KEYRING_USERNAME = "session"
_SESSION_FILENAME = "session.json"
_SCHEMA_KEYS = frozenset({"base_url", "cookies", "harvested_at", "user_id", "xsrf"})
_COOKIE_KEYS = frozenset({"domain", "name", "path", "secure", "value"})
_last_backend: str | None = None


@dataclass(frozen=True)
class SessionCookie:
    """One browser-exported cookie with its original scope retained."""

    name: str
    value: str
    domain: str
    path: str
    secure: bool


@dataclass
class Session:
    """The minimum local API session projection.

    Browser identity-provider cookies and display names are intentionally absent.  Cookies are
    filtered to the configured LEARN host at construction and again when a request jar is made,
    so later mutation of this non-frozen dataclass cannot widen the request scope accidentally.
    """

    base_url: str
    cookies: tuple[SessionCookie, ...]
    xsrf: str | None
    harvested_at: datetime
    user_id: str | None

    def __post_init__(self) -> None:
        self.base_url = _normalize_base_url(self.base_url)
        self.cookies = tuple(self.cookies)
        if self.xsrf is not None and not isinstance(self.xsrf, str):
            raise ValueError("session xsrf must be a string or null")
        if self.user_id is not None and not isinstance(self.user_id, str):
            raise ValueError("session user_id must be a string or null")
        if not isinstance(self.harvested_at, datetime):
            raise ValueError("session harvested_at must be a datetime")
        if self.harvested_at.tzinfo is None or self.harvested_at.utcoffset() is None:
            raise ValueError("session harvested_at must be timezone-aware")
        self.harvested_at = self.harvested_at.astimezone(UTC)

        host = _base_host(self.base_url)
        scoped: list[SessionCookie] = []
        for cookie in self.cookies:
            _validate_cookie(cookie)
            if _cookie_belongs_to_host(cookie.domain, host):
                scoped.append(cookie)
        self.cookies = tuple(scoped)

    def age(self) -> timedelta:
        """Return the age of the harvest as measured by the current UTC clock."""

        return datetime.now(UTC) - self.harvested_at

    def requests_cookies(self) -> RequestsCookieJar:
        """Return a requests jar containing only cookies scoped to this session's host."""

        jar = requests.cookies.RequestsCookieJar()
        host = _base_host(self.base_url)
        for cookie in self.cookies:
            _validate_cookie(cookie)
            if not _cookie_belongs_to_host(cookie.domain, host):
                continue
            jar.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain,
                path=cookie.path,
                secure=cookie.secure,
            )
        return jar


def store(value: Session) -> str:
    """Persist a validated session and return the backend that accepted it."""

    global _last_backend
    if not isinstance(value, Session):
        raise ValueError("session value has an invalid schema")
    validated = Session(
        base_url=value.base_url,
        cookies=value.cookies,
        xsrf=value.xsrf,
        harvested_at=value.harvested_at,
        user_id=value.user_id,
    )
    blob = _encode(validated)

    if keyring is not None:
        try:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, blob)
        except Exception:
            # Keyring backends commonly fail because SecretService/D-Bus is unavailable.  This
            # is an expected storage choice, not an error to surface or log.  Remove a stale
            # keyring value when possible so a later process cannot prefer it over the fallback.
            _delete_keyring_quietly()
        else:
            _remove_file_quietly(_session_path())
            _last_backend = "keyring"
            return _last_backend

    paths.atomic_write_text(_session_path(), blob)
    _last_backend = "file"
    return _last_backend


def load() -> Session | None:
    """Load the keyring session, then the protected local-file fallback."""

    global _last_backend
    if keyring is not None:
        try:
            blob = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        except Exception:
            blob = None
        if blob is not None:
            loaded = _decode(blob)
            _last_backend = "keyring"
            return loaded

    blob = _read_file()
    if blob is None:
        _last_backend = "file"
        return None
    loaded = _decode(blob)
    _last_backend = "file"
    return loaded


def clear() -> None:
    """Remove the exported session from both storage backends without surfacing keyring errors."""

    global _last_backend
    _delete_keyring_quietly()
    _remove_file_quietly(_session_path())
    _last_backend = None


def backend_name() -> str:
    """Return only the active storage backend name, never its contents."""

    if _last_backend is not None:
        return _last_backend

    if _file_is_present():
        return "file"
    if keyring is None:
        return "file"
    try:
        keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return "file"
    return "keyring"


def _encode(value: Session) -> str:
    payload: dict[str, object] = {
        "base_url": value.base_url,
        "cookies": [
            {
                "domain": cookie.domain,
                "name": cookie.name,
                "path": cookie.path,
                "secure": cookie.secure,
                "value": cookie.value,
            }
            for cookie in value.cookies
        ],
        "harvested_at": value.harvested_at.isoformat().replace("+00:00", "Z"),
        "user_id": value.user_id,
        "xsrf": value.xsrf,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _decode(blob: object) -> Session:
    if not isinstance(blob, str):
        raise ValueError("stored session schema is not text")
    try:
        raw: Any = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise ValueError("stored session is not valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _SCHEMA_KEYS:
        raise ValueError("stored session schema is invalid")

    base_url = raw["base_url"]
    cookies_raw = raw["cookies"]
    harvested_at = raw["harvested_at"]
    user_id = raw["user_id"]
    xsrf = raw["xsrf"]
    if not isinstance(base_url, str) or not isinstance(cookies_raw, list):
        raise ValueError("stored session schema is invalid")
    if not isinstance(harvested_at, str):
        raise ValueError("stored session schema is invalid")
    if user_id is not None and not isinstance(user_id, str):
        raise ValueError("stored session schema is invalid")
    if xsrf is not None and not isinstance(xsrf, str):
        raise ValueError("stored session schema is invalid")

    cookies: list[SessionCookie] = []
    for raw_cookie in cookies_raw:
        if not isinstance(raw_cookie, dict) or set(raw_cookie) != _COOKIE_KEYS:
            raise ValueError("stored session cookie schema is invalid")
        cookie = SessionCookie(
            name=raw_cookie["name"],
            value=raw_cookie["value"],
            domain=raw_cookie["domain"],
            path=raw_cookie["path"],
            secure=raw_cookie["secure"],
        )
        cookies.append(cookie)

    parsed_at = _parse_harvested_at(harvested_at)
    return Session(
        base_url=base_url,
        cookies=tuple(cookies),
        xsrf=xsrf,
        harvested_at=parsed_at,
        user_id=user_id,
    )


def _parse_harvested_at(value: str) -> datetime:
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("stored session harvested_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored session harvested_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _normalize_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("session base_url must be a string")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("session base_url has an invalid host") from exc
    if parsed.scheme.casefold() != "https":
        raise ValueError("session base_url must use HTTPS")
    if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
        raise ValueError("session base_url must contain a host without credentials")
    if parsed.query or parsed.fragment or port is None and ":" in parsed.netloc:
        raise ValueError("session base_url must be a plain configured host")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _base_host(base_url: str) -> str:
    hostname = urlsplit(base_url).hostname
    if hostname is None:  # pragma: no cover - _normalize_base_url rejects this first
        raise ValueError("session base_url must contain a host")
    return hostname.rstrip(".").casefold()


def _validate_cookie(cookie: SessionCookie) -> None:
    if not isinstance(cookie, SessionCookie):
        raise ValueError("session cookie schema is invalid")
    if not isinstance(cookie.name, str) or not cookie.name:
        raise ValueError("session cookie schema is invalid")
    if not isinstance(cookie.value, str):
        raise ValueError("session cookie schema is invalid")
    if not isinstance(cookie.domain, str) or not cookie.domain.strip():
        raise ValueError("session cookie schema is invalid")
    if not isinstance(cookie.path, str) or not cookie.path.startswith("/"):
        raise ValueError("session cookie schema is invalid")
    if not isinstance(cookie.secure, bool):
        raise ValueError("session cookie schema is invalid")


def _cookie_belongs_to_host(domain: str, host: str) -> bool:
    normalized = domain.lstrip(".").rstrip(".").casefold()
    return normalized == host


def _session_path() -> Path:
    return config.state_dir() / _SESSION_FILENAME


def _read_file() -> str | None:
    try:
        with open(
            os.fspath(paths.long_path(_session_path())), encoding="utf-8", newline=""
        ) as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def _file_is_present() -> bool:
    try:
        os.stat(os.fspath(paths.long_path(_session_path())))
    except FileNotFoundError:
        return False
    return True


def _remove_file_quietly(path: Path) -> None:
    try:
        os.unlink(os.fspath(paths.long_path(path)))
    except FileNotFoundError:
        return


def _delete_keyring_quietly() -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return


__all__ = [
    "Session",
    "SessionCookie",
    "backend_name",
    "clear",
    "load",
    "store",
]
