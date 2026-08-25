"""Spec-critical tests for licensed and external topic handling."""

from __future__ import annotations

import json
from pathlib import Path

from ingest_support import FakeClient, course

from agent2learn.ingest import ingest_files, ingest_metadata
from agent2learn.vault import Vault


def _toc_with_excluded_topics() -> dict[str, object]:
    return {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Reading links",
                "Modules": [],
                "Topics": [
                    {
                        "TopicId": 10,
                        "Title": "Quicklink",
                        "TypeIdentifier": "Link",
                        "Url": (
                            "https://student:secret@QUICKLINK.D2L.invalid/topic/10"
                            "?signed=do-not-persist#fragment"
                        ),
                        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
                        "IsBroken": False,
                    },
                    {
                        "TopicId": 11,
                        "Title": "External tool",
                        "TypeIdentifier": "lti",
                        "Url": (
                            "https://launch:payload@example.invalid/lti/11"
                            "?issuer=do-not-persist#launch"
                        ),
                        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
                        "IsBroken": False,
                    },
                    {
                        "TopicId": 12,
                        "Title": "Publisher text",
                        "TypeIdentifier": "Link",
                        "Url": (
                            "https://reader:token@WWW.VITALSOURCE.COM/book/12"
                            "?jwt=do-not-persist#chapter"
                        ),
                        "LastModifiedDate": "2026-01-05T14:00:00.000Z",
                        "IsBroken": False,
                    },
                ],
            }
        ]
    }


def test_licensed_topics_are_never_downloaded(tmp_path: Path) -> None:
    fake_client = FakeClient([course()], tocs={111111: _toc_with_excluded_topics()})
    vault = Vault(tmp_path)

    ingest_metadata(fake_client, vault, fake_client.school)
    report = ingest_files(fake_client, vault, fake_client.school)

    assert report.downloaded == 0
    assert fake_client.download_calls == []
    stubs = sorted(tmp_path.rglob("*.url.txt"))
    assert len(stubs) == 3

    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file()
    )
    for forbidden in ("secret", "payload", "do-not-persist", "fragment", "jwt", "token"):
        assert forbidden not in persisted

    for stub in stubs:
        text = stub.read_text(encoding="utf-8")
        assert "?" not in text
        assert "#" not in text
        assert "https://learn.uwaterloo.ca/d2l/le/content/111111/viewContent/" in text
        assert "destination host:" in text

    report_text = json.dumps(report.__dict__, default=str)
    assert "do-not-persist" not in report_text
