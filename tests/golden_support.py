"""One deterministic end-to-end pipeline run, shared by the golden-vault test.

Every other test exercises a module in isolation.  This one drives the real transport, the
real ingester, the real converter, and the real index and audit writers against the
synthetic API, so the artifacts it produces are the artifacts a student would get.

Determinism is the whole point, so three sources of variation are pinned:

* **the clock** — frozen through ``agent2learn.clock``, the single seam every vault writer
  uses (enforced by ``test_no_forbidden_calls``);
* **the converter** — the real backend at the locked version. ``pdf-oxide`` is exact-pinned
  in ``pyproject.toml``, so a bump is a deliberate edit that *should* require regenerating
  this map with an explained diff, exactly as ``AGENTS.md`` requires;
* **jitter** — the download stagger is removed so runs do not differ in wall time.

Anything still varying after that is a real portability defect, which is exactly what the
golden map is built to catch.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

if TYPE_CHECKING:
    from requests._types import CertType, TimeoutType, VerifyType

from agent2learn import clock
from agent2learn.api import Client
from agent2learn.pipeline import run_pipeline
from agent2learn.schools._base import CONSERVATIVE_TOPIC_EXCLUSION_POLICY, TopicExclusionPolicy
from agent2learn.vault import Vault

FROZEN_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
FROZEN_STAMP = "2026-08-25T12:00:00Z"

# The vault records ``view_url`` for every topic, so the origin ends up in the bytes. The
# test server binds an ephemeral port, which would make the golden map differ on every run
# for a reason that has nothing to do with portability. The pipeline is therefore pointed
# at a stable canonical origin and only the final hop is rewritten, below — egress
# validation still runs against the canonical host, which is the behaviour under test.
CANONICAL_ORIGIN = "https://learn.golden.test"


class _CanonicalOriginAdapter(HTTPAdapter):
    """Send requests addressed to the canonical origin to the live test server."""

    def __init__(self, canonical: str, actual: str) -> None:
        self._canonical = canonical
        self._actual = actual
        super().__init__()

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: TimeoutType = None,
        verify: VerifyType = True,
        cert: CertType = None,
        proxies: dict[str, str] | None = None,
    ) -> Response:
        if request.url and request.url.startswith(self._canonical):
            request.url = self._actual + request.url[len(self._canonical) :]
        return super().send(request, stream, timeout, verify, cert, proxies)


@dataclass
class GoldenSchool:
    """A school pointed at the synthetic server, with Waterloo's real exclusion policy.

    The policy matters: it is what turns the publisher eText and the LTI tool into
    sanitized link stubs instead of downloads, and the golden tree must prove that.
    """

    base_url: str
    id: str = "synthetic"
    name: str = "Synthetic School"
    timezone: str = "UTC"
    auth_hint: str = "synthetic"

    def term_from_offering(self, code: str) -> str | None:
        tail = code.rsplit("_", 1)[-1]
        return tail if tail.isdigit() else None

    def term_label(self, term: str) -> str:
        return f"Term {term}"

    def auth_hosts(self) -> list[str]:
        return []

    def outline_hosts(self) -> list[str]:
        return []

    def topic_exclusion_policy(self) -> TopicExclusionPolicy:
        return CONSERVATIVE_TOPIC_EXCLUSION_POLICY


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """Freeze the shared clock seam so every generated timestamp is reproducible."""
    monkeypatch.setattr(clock, "now", lambda: FROZEN_NOW)
    monkeypatch.setattr(clock, "stamp", lambda: FROZEN_STAMP)
    yield FROZEN_NOW


def run_full_pipeline(
    root: Path,
    base_url: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_media: bool = False,
) -> Vault:
    """Ingest, download, convert, index, snapshot, and audit into a fresh vault at ``root``."""
    # The stagger only exists to be polite to a real server; it adds nothing offline and
    # would make two runs take different amounts of time.
    monkeypatch.setattr("agent2learn.api.JITTER_MAX", 0.0)

    school = GoldenSchool(CANONICAL_ORIGIN)
    from agent2learn.session import Session

    client = Client(school, Session(CANONICAL_ORIGIN, (), None, FROZEN_NOW, None), workers=1)
    client._transport.mount(CANONICAL_ORIGIN, _CanonicalOriginAdapter(CANONICAL_ORIGIN, base_url))

    Vault.claim(root)
    vault = Vault(root)

    from agent2learn.calibrate import calibrate

    calibration = calibrate(client)
    client.courses = calibration.courses  # type: ignore[attr-defined]

    # This is the exact production sequence. The synthetic run records outline coverage as
    # unavailable without opening a browser, because no profile consent exists in this
    # isolated fixture; every deterministic local phase, including post-conversion INDEX
    # reconciliation, remains enabled and hashed.
    run_pipeline(
        client,
        vault,
        school,
        scope="all",
        include_media=include_media,
        profile_consent=False,
    )
    return vault


def hash_tree(root: Path) -> dict[str, str]:
    """Map every file to its digest, keyed by forward-slash relative path.

    Keys are compared as well as values: a filename that differs by case, normalization
    form, or separator is a portability defect even when the bytes match.
    """
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
