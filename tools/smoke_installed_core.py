from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, reset_tzpath

from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

import agent2learn
from agent2learn import _release, audit, calendar, doctor
from agent2learn.api import DEFAULT_MAX_BYTES, Client, DownloadResult
from agent2learn.calibrate import CourseRef
from agent2learn.check import check
from agent2learn.ground import write_grounding_pack
from agent2learn.pipeline import run_pipeline
from agent2learn.schools import UWaterloo, render_timestamp
from agent2learn.session import Session
from agent2learn.vault import ManifestEntry, Vault

BODY = b"# Network model\r\nThe network flow capacity bound is 10 units.\r\n\r\n"


class _NoNetwork(HTTPAdapter):
    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> Response:
        raise AssertionError("installed-core smoke attempted an unexpected network request")


class _FixtureClient(Client):
    def __init__(self, *, quiz_forbidden: bool = False) -> None:
        self.quiz_forbidden = quiz_forbidden
        school = UWaterloo()
        super().__init__(
            school, Session(school.base_url, (), None, datetime(2026, 1, 1, tzinfo=UTC), None)
        )
        self._transport.mount("https://", _NoNetwork())
        self._transport.mount("http://", _NoNetwork())
        self.courses = [CourseRef(111111, "COURSE101", "Synthetic Network Models", "1261", True)]
        self.le_version = "1.96"
        self.lp_version = "1.62"

    def get_json(self, path: str) -> Any:
        if path.endswith("/content/toc"):
            return {
                "Modules": [
                    {
                        "ModuleId": 1,
                        "Title": "Lectures",
                        "Modules": [],
                        "Topics": [
                            {
                                "TopicId": 1,
                                "Title": "Network notes.md",
                                "TypeIdentifier": "File",
                                "Url": "/content/notes.md",
                                "ETag": '"v1"',
                                "Size": len(BODY),
                            }
                        ],
                    }
                ]
            }
        if path.endswith("/dropbox/folders/"):
            return [
                {
                    "Id": 700001,
                    "Name": "Network Assignment 1",
                    "CustomInstructions": {"Html": "<p>Use the class network flow model.</p>"},
                }
            ]
        if path.endswith("/news/"):
            return []
        if path.endswith("/quizzes/"):
            if self.quiz_forbidden:
                response = Response()
                response.status_code = 403
                response.headers["Content-Type"] = "application/problem+json; charset=UTF-8"
                response._content = json.dumps(
                    {
                        "type": "http://docs.valence.desire2learn.com/res/apiprop.html#not-authorized",
                        "title": "Not Authorized",
                        "status": 403,
                        "detail": (
                            "Not authorized for [ orgUnitId: 111111, "
                            "securityVariableName: Quizzing.SeeQuizzing ]"
                        ),
                    }
                ).encode()
                response._content_consumed = True
                return self._decode_json_response(response)
            return {"Objects": [], "Next": None}
        raise AssertionError("unexpected metadata endpoint in installed-core smoke")

    def download(
        self,
        url: str,
        temp: Path,
        *,
        prior: ManifestEntry | None = None,
        max_bytes: int | None = DEFAULT_MAX_BYTES,
        is_html_topic: bool = False,
        root: Path | None = None,
    ) -> DownloadResult:
        assert url.startswith(self.school.base_url + "/d2l/")
        assert max_bytes is not None and max_bytes >= len(BODY)
        temp.write_bytes(BODY)
        return DownloadResult(temp, sha256(BODY).hexdigest(), len(BODY), '"v1"', None, False)


def main() -> None:
    assert Path(agent2learn.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert not _release.SUBMISSION_AVAILABLE
    reset_tzpath(())
    ZoneInfo.clear_cache()
    school = UWaterloo()
    assert render_timestamp("2026-01-05T12:00:00Z", school) == "2026-01-05T07:00:00-05:00"
    assert render_timestamp("2026-07-05T12:00:00Z", school) == "2026-07-05T08:00:00-04:00"
    with tempfile.TemporaryDirectory(prefix="a2l-installed-core-") as temporary:
        root = Path(temporary)
        vault = Vault(Vault.claim(root / "vault"))
        client = _FixtureClient()
        pipeline = run_pipeline(client, vault, school, render_outlines=False)
        assert pipeline.exit_code == 0
        entry = vault.entry("uwaterloo:111111:topic:1")
        assert entry is not None and (vault.root / entry.path).read_bytes() == BODY
        assert entry.derived["markdown"].path != entry.path
        pack = write_grounding_pack(vault, "COURSE101", "700001")
        assert {source.role for source in pack.sources} >= {"assignment_prompt", "lecture"}
        draft = root / "draft.md"
        draft.write_text("The network flow capacity bound is 10 units.\n", encoding="utf-8")
        report = check(draft, pipeline.metadata.courses[0].directory, assignment="700001")
        assert report.findings[0].status == "evidence_found"
        assert not list(vault.root.rglob("*.part"))

        restricted = Vault(Vault.claim(root / "restricted-vault"))
        denied = run_pipeline(
            _FixtureClient(quiz_forbidden=True), restricted, school, render_outlines=False
        )
        assert denied.files.downloaded == 1, (
            "quiz denial blocked accessible installed-wheel content"
        )
        assert denied.exit_code == 0 and any("403" in gap for gap in denied.gaps)
        entry = restricted.entry("uwaterloo:111111:topic:1")
        assert entry is not None and (restricted.root / entry.path).read_bytes() == BODY
        assert (restricted.root / entry.derived["markdown"].path).is_file()
        assert any("403" in gap for gap in audit.audit_vault(restricted)[0].metadata_gaps)
        today = calendar.render_today(calendar.build_today(restricted, school))
        assert "Quizzing.SeeQuizzing" in today
        diagnostics = doctor.report(doctor._vault(restricted))
        assert "403" in diagnostics and "111111" not in diagnostics
    print(
        "Installed base-wheel timezone, sync, permission-gap, preservation, grounding, "
        "and evidence checks passed."
    )


if __name__ == "__main__":
    main()
