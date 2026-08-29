"""Shared pytest fixtures.

Every test in this suite runs offline. No test may reach the network, and no test may
write outside the ``tmp_path`` fixture.

``synthetic_api`` serves the authored fixture corpus over a real local HTTP server
rather than monkeypatching ``requests``. That distinction matters: it exercises the
status codes, headers, content types, streaming, and redirect handling the client
actually depends on, none of which a stubbed function would test.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
API = FIXTURES / "api"
NONJSON = API / "nonjson"
FILES = FIXTURES / "files"

LE = "1.96"
LP = "1.62"
COURSE_A_OU = 111111
COURSE_B_OU = 222222

_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE.sub("", value)


def flatten_help(value: str) -> str:
    """Normalize Rich help output so a wrapped sentence can be asserted as one string.

    Typer renders option help inside a bordered panel, so a long sentence arrives split across
    lines with ``│`` gutters interleaved. Asserting on the raw text silently depends on terminal
    width; flattening keeps the assertion about wording.
    """

    plain = strip_ansi(value)
    for border in "│┃|╭╮╰╯─━":
        plain = plain.replace(border, " ")
    return re.sub(r"\s+", " ", plain).strip()


def fixture_json(name: str) -> Any:
    return json.loads((API / name).read_text(encoding="utf-8"))


def fixture_bytes(name: str) -> bytes:
    return (FILES / name).read_bytes()


class SyntheticAPI:
    """A configured local D2L stand-in.

    Attributes:
        base_url: the origin to point a client at.
        server: the underlying ``pytest_httpserver.HTTPServer``, for tests that need to
            add a one-off route such as a 429 or a malformed body.
    """

    def __init__(self, server: Any) -> None:
        self.server = server
        self.base_url = server.url_for("").rstrip("/")

    # -- helpers for tests that need a specific failure mode ---------------------------
    def expect_login_html(self, path: str) -> None:
        """Serve the SSO login page with a 200, which is how an expired session presents."""
        self.server.expect_request(path).respond_with_data(
            (NONJSON / "login.html").read_text(encoding="utf-8"),
            status=200,
            content_type="text/html; charset=utf-8",
        )

    def expect_rate_limited(self, path: str, retry_after: str = "1") -> None:
        self.server.expect_request(path).respond_with_data(
            (NONJSON / "rate_limited.html").read_text(encoding="utf-8"),
            status=429,
            headers={"Retry-After": retry_after},
            content_type="text/html; charset=utf-8",
        )

    def expect_malformed_json(self, path: str) -> None:
        self.server.expect_request(path).respond_with_data(
            (NONJSON / "malformed_body.txt").read_text(encoding="utf-8"),
            status=200,
            content_type="application/json",
        )


@pytest.fixture
def synthetic_api(httpserver: Any) -> Iterator[SyntheticAPI]:
    """A local server preloaded with the documented happy-path routes.

    Only the routes the adapters actually call are registered. Anything else 500s, so a
    test that reaches an unplanned endpoint fails loudly instead of silently passing.
    """
    j = fixture_json

    # Version discovery is unauthenticated in practice, so it is registered first.
    httpserver.expect_request("/d2l/api/versions/").respond_with_json(j("versions.json"))
    httpserver.expect_request(f"/d2l/api/lp/{LP}/users/whoami").respond_with_json(j("whoami.json"))

    # Enrolments paginate: page 1 advertises more, page 2 terminates.
    httpserver.expect_request(
        f"/d2l/api/lp/{LP}/enrollments/myenrollments/",
        query_string={},
    ).respond_with_json(j("myenrollments_page1.json"))
    httpserver.expect_request(
        f"/d2l/api/lp/{LP}/enrollments/myenrollments/",
        query_string={"bookmark": "SYNTHETIC-BOOKMARK-0001"},
    ).respond_with_json(j("myenrollments_page2.json"))

    for ou, toc in (
        (COURSE_A_OU, "content_toc_course101.json"),
        (COURSE_B_OU, "content_toc_course202.json"),
    ):
        httpserver.expect_request(f"/d2l/api/le/{LE}/{ou}/content/toc").respond_with_json(j(toc))

    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_A_OU}/dropbox/folders/").respond_with_json(
        j("dropbox_folders_course101.json")
    )
    httpserver.expect_request(
        f"/d2l/api/le/{LE}/{COURSE_A_OU}/dropbox/folders/700002/submissions/"
    ).respond_with_json(j("submissions_readback_course101.json"))
    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_A_OU}/news/").respond_with_json(
        j("news_course101.json")
    )
    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_A_OU}/quizzes/").respond_with_json(
        j("quizzes_course101.json")
    )
    # Course B is a deliberately sparse course: it has a TOC but no assignments, news, or
    # quizzes. A real instance answers those with an empty collection and a 200. They must
    # be registered rather than left to 500, which the client would treat as transient and
    # retry five times with backoff, costing 45 seconds of sleeping per sync.
    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_B_OU}/dropbox/folders/").respond_with_json(
        []
    )
    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_B_OU}/news/").respond_with_json([])
    httpserver.expect_request(f"/d2l/api/le/{LE}/{COURSE_B_OU}/quizzes/").respond_with_json(
        {"Next": None, "Objects": []}
    )

    # Opt-in categories. Registered so tests can assert they are NOT called by default.
    httpserver.expect_request(
        f"/d2l/api/le/{LE}/{COURSE_A_OU}/grades/values/myGradeValues/"
    ).respond_with_json(j("grades_myvalues_course101.json"))
    httpserver.expect_request(
        f"/d2l/api/le/{LE}/{COURSE_A_OU}/discussions/forums/"
    ).respond_with_json(j("discussions_forums_course101.json"))

    # First-party file downloads.
    for name, ctype in (
        ("lecture01.pdf", "application/pdf"),
        ("analysis.ipynb", "application/json"),
        ("notes.Rmd", "text/plain; charset=utf-8"),
        ("site.html.zip", "application/zip"),
    ):
        httpserver.expect_request(
            f"/content/enforced/{COURSE_A_OU}-COURSE101/{name}"
        ).respond_with_data(fixture_bytes(name), content_type=ctype)

    # The client tries four download routes in order and takes the first that works. On a
    # real instance the two API routes answer 404 for a topic they do not serve, and 404 is
    # terminal. Leaving them unregistered would make this server answer 500 instead, which
    # is a *transient* status the client correctly retries five times with backoff — about
    # 30 seconds per file of pure sleeping, for a fallback that is supposed to be instant.
    httpserver.expect_request(
        re.compile(r"^/d2l/le/content/\d+/topics/files/download/\d+/DirectFileTopicDownload$")
    ).respond_with_data("not found", status=404, content_type="text/plain")
    httpserver.expect_request(
        re.compile(r"^/d2l/api/le/[\d.]+/\d+/content/topics/\d+/file$")
    ).respond_with_data("not found", status=404, content_type="text/plain")

    # The adversarially-named topics — trailing dot, NFD, the case-collision pair, and the
    # over-length title — must actually land on disk for the golden vault to prove anything
    # about naming. They share one PDF body: what is under test is the filename each
    # produces, and identical bytes under different names also exercise the per-entry twin.
    for name in ("reading.pdf", "cafe-notes.pdf", "lab-notes-a.pdf", "lab-notes-b.pdf", "long.pdf"):
        httpserver.expect_request(
            f"/content/enforced/{COURSE_A_OU}-COURSE101/{name}"
        ).respond_with_data(fixture_bytes("lecture01.pdf"), content_type="application/pdf")
    httpserver.expect_request(
        f"/content/enforced/{COURSE_B_OU}-COURSE202/outline.pdf"
    ).respond_with_data(fixture_bytes("lecture01.pdf"), content_type="application/pdf")

    yield SyntheticAPI(httpserver)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any connection to a non-loopback address raise.

    ``synthetic_api`` binds to localhost, so loopback stays permitted; anything reaching
    for the real internet fails the test rather than quietly succeeding in CI.
    """
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"network access attempted to {host!r}; tests must be offline")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
