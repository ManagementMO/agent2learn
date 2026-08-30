"""Session persistence and cookie-scope contracts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from agent2learn import session

BASE_URL = "https://learn.example.invalid"


def _sample_session(*, unrelated: bool = False) -> session.Session:
    cookies: tuple[session.SessionCookie, ...] = (
        session.SessionCookie(
            name="d2lSessionVal",
            value="synthetic-session",
            domain=".learn.example.invalid",
            path="/d2l",
            secure=True,
        ),
        session.SessionCookie(
            name="XSRF-TOKEN",
            value="synthetic-xsrf",
            domain="learn.example.invalid",
            path="/",
            secure=True,
        ),
    )
    if unrelated:
        cookies += (
            session.SessionCookie(
                name="unrelated",
                value="must-not-travel",
                domain="identity.example.invalid",
                path="/",
                secure=True,
            ),
            session.SessionCookie(
                name="child-domain",
                value="must-not-travel",
                domain="child.learn.example.invalid",
                path="/",
                secure=True,
            ),
        )
    return session.Session(
        base_url=BASE_URL,
        cookies=cookies,
        xsrf="synthetic-xsrf",
        harvested_at=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
        user_id="synthetic-user",
    )


@pytest.fixture
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(session.config, "state_dir", lambda: state)
    return state


def _keyring_always_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic keyring unavailable")

    monkeypatch.setattr(session.keyring, "set_password", fail)
    monkeypatch.setattr(session.keyring, "get_password", fail)
    monkeypatch.setattr(session.keyring, "delete_password", fail)


def test_file_backend_round_trips_cookie_scope_and_metadata(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    original = _sample_session()

    assert session.store(original) == "file"
    loaded = session.load()

    assert loaded == original
    assert loaded is not None
    assert loaded.cookies[0].domain == ".learn.example.invalid"
    assert loaded.cookies[0].path == "/d2l"
    assert loaded.cookies[0].secure is True
    assert loaded.xsrf == "synthetic-xsrf"
    assert loaded.user_id == "synthetic-user"
    assert session.backend_name() == "file"


def test_keyring_failure_falls_back_silently_to_a_working_file_session(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _keyring_always_fails(monkeypatch)
    original = _sample_session()

    assert session.store(original) == "file"
    assert session.load() == original
    assert capsys.readouterr() == ("", "")


def test_stored_blob_has_no_password_key(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    session.store(_sample_session())

    raw = json.loads((isolated_state / "session.json").read_text(encoding="utf-8"))
    assert "password" not in raw
    assert "password" not in (isolated_state / "session.json").read_text(encoding="utf-8")


def test_clear_removes_the_file_and_attempts_to_clear_keyring(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    session.store(_sample_session())
    deleted: list[tuple[str, str]] = []

    def record_delete(service: str, username: str) -> None:
        deleted.append((service, username))

    monkeypatch.setattr(session.keyring, "delete_password", record_delete)
    session.clear()

    assert not (isolated_state / "session.json").is_file()
    assert deleted == [("agent2learn", "session")]
    assert session.load() is None


def test_clear_surfaces_a_session_file_removal_failure(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    session.store(_sample_session())

    def refuse_unlink(_path: str) -> None:
        raise PermissionError("synthetic refusal")

    monkeypatch.setattr(session.os, "unlink", refuse_unlink)

    with pytest.raises(PermissionError, match="synthetic refusal"):
        session.clear()


def test_unrelated_domain_cookie_is_never_loaded_or_attached(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    session.store(_sample_session(unrelated=True))
    loaded = session.load()

    assert loaded is not None
    assert [cookie.name for cookie in loaded.cookies] == ["d2lSessionVal", "XSRF-TOKEN"]
    jar = loaded.requests_cookies()
    assert jar.get_dict() == {
        "d2lSessionVal": "synthetic-session",
        "XSRF-TOKEN": "synthetic-xsrf",
    }

    prepared = requests.Request(
        "GET", f"{BASE_URL}/d2l/api/lp/1.62/users/whoami", cookies=jar
    ).prepare()
    assert "d2lSessionVal=synthetic-session" in (prepared.headers.get("Cookie") or "")
    assert "unrelated" not in (prepared.headers.get("Cookie") or "")


def test_same_host_non_session_cookies_are_removed_at_the_storage_boundary() -> None:
    original = _sample_session()
    value = session.Session(
        base_url=original.base_url,
        cookies=original.cookies
        + (
            session.SessionCookie(
                name="analytics",
                value="must-not-travel",
                domain="learn.example.invalid",
                path="/",
                secure=True,
            ),
        ),
        xsrf=original.xsrf,
        harvested_at=original.harvested_at,
        user_id=original.user_id,
    )

    assert [cookie.name for cookie in value.cookies] == ["d2lSessionVal", "XSRF-TOKEN"]


def test_session_rejects_an_unconfigured_or_unsafe_base_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        session.Session(
            base_url="http://learn.example.invalid",
            cookies=(),
            xsrf=None,
            harvested_at=datetime.now(UTC),
            user_id=None,
        )
    with pytest.raises(ValueError, match="host"):
        session.Session(
            base_url="https://user:secret@learn.example.invalid",  # pragma: allowlist secret
            cookies=(),
            xsrf=None,
            harvested_at=datetime.now(UTC),
            user_id=None,
        )


def test_session_age_is_computed_from_an_aware_utc_instant() -> None:
    harvested_at = datetime.now(UTC) - timedelta(minutes=3)
    current = session.Session(
        base_url=BASE_URL,
        cookies=(),
        xsrf=None,
        harvested_at=harvested_at,
        user_id=None,
    )

    assert current.age() >= timedelta(minutes=3)


def test_stored_schema_rejects_unknown_fields(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    isolated_state.mkdir(parents=True, exist_ok=True)
    (isolated_state / "session.json").write_text(
        json.dumps({"base_url": BASE_URL, "password": "nope"}),  # pragma: allowlist secret
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema"):
        session.load()


def test_malformed_utf8_session_file_is_reported_as_invalid(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keyring_always_fails(monkeypatch)
    (isolated_state / "session.json").write_bytes(b"{\xff")

    with pytest.raises(ValueError, match="valid JSON"):
        session.load()


@pytest.mark.skipif(os.name == "nt", reason="file symlinks require Windows privileges")
def test_session_rejects_a_symlinked_file(
    isolated_state: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _keyring_always_fails(monkeypatch)
    outside = tmp_path / "outside-session.json"
    outside.write_text("{}\n", encoding="utf-8")
    (isolated_state / "session.json").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        session.load()

    assert outside.read_text(encoding="utf-8") == "{}\n"
