"""Tests for the universal hidden-TTY authentication fallback."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agent2learn import cli as cli_module
from agent2learn import session
from agent2learn.auth import paste
from agent2learn.cli import app

try:
    import termios
except ImportError:  # pragma: no cover - only Windows lacks termios
    termios = None  # type: ignore[assignment]

BASE_URL = "https://learn.example.invalid"
HARVESTED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _expected_session() -> session.Session:
    return session.Session(
        base_url=BASE_URL,
        cookies=(
            session.SessionCookie(
                name="d2lSessionVal",
                value="session-token",
                domain=".learn.example.invalid",
                path="/d2l",
                secure=True,
            ),
            session.SessionCookie(
                name="d2lSecureSessionVal",
                value="secure-token",
                domain=".learn.example.invalid",
                path="/d2l",
                secure=True,
            ),
            session.SessionCookie(
                name="XSRF-TOKEN",
                value="xsrf-token",
                domain=".learn.example.invalid",
                path="/",
                secure=True,
            ),
        ),
        xsrf="xsrf-token",
        harvested_at=HARVESTED_AT,
        user_id=None,
    )


def _cookie_shapes() -> list[str]:
    return [
        "\n".join(
            (
                "d2lSessionVal=session-token",
                "d2lSecureSessionVal=secure-token",
                "XSRF-TOKEN=xsrf-token",
                "DuoTrust=duo-must-stay-in-browser-profile",
            )
        ),
        "\n".join(
            (
                "Name\tValue\tDomain\tPath\tExpires\tSize\tHttpOnly\tSecure\tSameSite",
                "d2lSessionVal\tsession-token\t.learn.example.invalid\t/d2l\t\t0\t✓\t✓\tLax",
                "d2lSecureSessionVal\tsecure-token\t.learn.example.invalid\t/d2l\t\t0\t✓\t✓\tLax",
                "XSRF-TOKEN\txsrf-token\t.learn.example.invalid\t/\t\t0\t\t✓\tLax",
                "DuoTrust\tduo-must-stay-in-browser-profile\tduo.example.invalid\t/\t\t0\t✓\t✓\tNone",
                "GoogleAuth\tgoogle-must-stay-in-browser-profile\taccounts.google.com\t/\t\t0\t✓\t✓\tNone",
                "analytics\tignore-me\t.learn.example.invalid\t/\t\t0\t\t✓\tLax",
            )
        ),
        json.dumps(
            {
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
                    {
                        "name": "XSRF-TOKEN",
                        "value": "xsrf-token",
                        "domain": ".learn.example.invalid",
                        "path": "/",
                        "secure": True,
                    },
                    {
                        "name": "DuoTrust",
                        "value": "duo-must-stay-in-browser-profile",
                        "domain": "duo.example.invalid",
                        "path": "/",
                        "secure": True,
                    },
                    {
                        "name": "GoogleAuth",
                        "value": "google-must-stay-in-browser-profile",
                        "domain": "accounts.google.com",
                        "path": "/",
                        "secure": True,
                    },
                    {
                        "name": "analytics",
                        "value": "ignore-me",
                        "domain": ".learn.example.invalid",
                        "path": "/",
                        "secure": True,
                    },
                ]
            },
            separators=(",", ":"),
        ),
    ]


@pytest.mark.parametrize("blob", _cookie_shapes())
def test_cookie_blob_shapes_produce_the_same_scoped_session(blob: str) -> None:
    actual = paste.session_from_blob(
        blob,
        base_url=BASE_URL,
        harvested_at=HARVESTED_AT,
    )

    assert actual == _expected_session()
    assert {cookie.name for cookie in actual.cookies} == {
        "d2lSessionVal",
        "d2lSecureSessionVal",
        "XSRF-TOKEN",
    }
    assert all("must-stay" not in cookie.value for cookie in actual.cookies)


def test_missing_minimum_cookie_names_are_reported_without_echoing_the_blob() -> None:
    blob = "d2lSessionVal=super-secret-session-value"

    with pytest.raises(paste.PasteError, match="d2lSecureSessionVal") as raised:
        paste.session_from_blob(blob, base_url=BASE_URL, harvested_at=HARVESTED_AT)

    assert blob not in str(raised.value)
    assert "super-secret" not in str(raised.value)


def test_cookie_scope_uses_exact_configured_host_and_allowlisted_names() -> None:
    blob = json.dumps(
        {
            "cookies": [
                {
                    "name": "d2lSessionVal",
                    "value": "session-token",
                    "domain": "child.learn.example.invalid",
                    "path": "/d2l",
                    "secure": True,
                },
                {
                    "name": "d2lSecureSessionVal",
                    "value": "secure-token",
                    "domain": ".learn.example.invalid.evil.invalid",
                    "path": "/d2l",
                    "secure": True,
                },
                {
                    "name": "d2lSessionVal",
                    "value": "valid-session",
                    "domain": ".LEARN.EXAMPLE.INVALID.",
                    "path": "/d2l",
                    "secure": True,
                },
                {
                    "name": "d2lSecureSessionVal",
                    "value": "valid-secure",
                    "domain": ".learn.example.invalid",
                    "path": "/d2l",
                    "secure": True,
                },
            ]
        }
    )

    actual = paste.session_from_blob(blob, base_url=BASE_URL, harvested_at=HARVESTED_AT)

    assert [cookie.value for cookie in actual.cookies] == ["valid-session", "valid-secure"]


def test_hidden_reader_refuses_piped_stdin_without_reading_it() -> None:
    class Piped:
        def isatty(self) -> bool:
            return False

        def read(self) -> str:
            raise AssertionError("piped input must not be read")

    with pytest.raises(paste.PasteError, match="controlling TTY"):
        paste.read_hidden_multiline(input_stream=Piped(), output_stream=Piped())


@pytest.mark.skipif(termios is None, reason="POSIX terminal API is unavailable on Windows")
def test_posix_hidden_reader_disables_and_restores_echo_even_on_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInput:
        def fileno(self) -> int:
            return 17

        def read(self) -> str:
            raise KeyboardInterrupt

    original = [0, 0, 0, termios.ECHO | termios.ICANON, 0, 0, 0]
    calls: list[tuple[int, int, list[int]]] = []
    monkeypatch.setattr(paste.termios, "tcgetattr", lambda _fd: original.copy())
    monkeypatch.setattr(
        paste.termios,
        "tcsetattr",
        lambda fd, when, attrs: calls.append((fd, when, attrs.copy())),
    )

    with pytest.raises(KeyboardInterrupt):
        paste._read_posix_hidden(
            FakeInput(), SimpleNamespace(write=lambda _value: None, flush=lambda: None)
        )

    assert len(calls) == 2
    assert calls[0][2][3] & termios.ECHO == 0
    assert calls[1][2] == original


def test_windows_hidden_reader_collects_input_without_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    characters = iter(["s", "e", "c", "r", "e", "t", "\r", "\x1a"])
    fake_msvcrt = SimpleNamespace(getwch=lambda: next(characters))
    monkeypatch.setattr(paste, "msvcrt", fake_msvcrt)

    output = SimpleNamespace(write=lambda _value: None, flush=lambda: None)
    assert paste._read_windows_hidden(output) == "secret\n"


def test_cli_paste_cannot_consume_runner_stdin_or_echo_a_cookie() -> None:
    secret = "d2lSessionVal=secret-that-must-not-appear"

    result = CliRunner().invoke(app, ["auth", "--paste"], input=secret + "\n")

    assert result.exit_code != 0
    assert "controlling TTY" in result.output
    assert secret not in result.output


def test_cli_paste_success_reminds_user_to_clear_clipboard_without_echoing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "d2lSessionVal=secret-that-must-not-appear"
    monkeypatch.setattr(cli_module, "authenticate", lambda _school, *, backend: _expected_session())

    result = CliRunner().invoke(app, ["auth", "--paste"])

    assert result.exit_code == 0
    assert "clear your clipboard" in result.stdout
    assert secret not in result.output
