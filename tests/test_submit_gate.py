"""Submission is disabled, previewed first, and never mutates without a fresh typed phrase."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from conftest import flatten_help
from typer.testing import CliRunner

from agent2learn import _release, clock, config, submit
from agent2learn.cli import app
from agent2learn.index import write_content_map
from agent2learn.submit import (
    CONFIRMATION_TTL_SECONDS,
    SubmissionCapability,
    SubmissionRefused,
    SubmissionUnverified,
    build_submission_body,
    cleanup_staging,
    confirm_and_upload,
    prepare,
    render_preview,
    safe_filename,
)
from agent2learn.vault import Vault

ENABLED = SubmissionCapability(available=True, reason="test capability")
LE = "1.96"
FOLDER_ID = 700002


class RecordingTransport:
    """Records every request so a test can prove no mutating call was made."""

    def __init__(
        self,
        *,
        folders: object | None = None,
        readback: object | None = None,
        status: int = 200,
        readback_error: Exception | None = None,
    ) -> None:
        self.folders = (
            folders
            if folders is not None
            else [{"Id": FOLDER_ID, "Name": "Lab 4", "GroupTypeId": None}]
        )
        self.readback = readback
        self.status = status
        self.readback_error = readback_error
        self.gets: list[str] = []
        self.posts: list[tuple[str, bytes, str]] = []

    def get_json(self, path: str) -> object:
        self.gets.append(path)
        if path.endswith("/dropbox/folders/"):
            return self.folders
        if self.readback_error is not None:
            raise self.readback_error
        return self.readback if self.readback is not None else []

    def post_once(self, path: str, body: bytes, *, content_type: str) -> object:
        self.posts.append((path, body, content_type))

        class _Response:
            status_code = self.status

        return _Response()


def _vault(tmp_path: Path) -> tuple[Vault, Path]:
    root = Vault.claim(tmp_path / "vault")
    vault = Vault(root)
    course = root / "Spring 2026" / "COURSE101_1265"
    write_content_map(
        course,
        [
            {
                "source_key": "uwaterloo:111111:topic:1",
                "source_id": "1",
                "course_code": "COURSE101",
                "course_name": "Synthetic Course",
                "course_org_unit_id": 111111,
                "term": "1265",
                "title": "Reading",
                "kind": "File",
                "availability": "metadata_only",
                "path": None,
            }
        ],
    )
    return vault, course


def _payload(tmp_path: Path, *, name: str = "report.pdf", text: str = "final answer\n") -> Path:
    destination = tmp_path / name
    destination.write_text(text, encoding="utf-8", newline="\n")
    return destination


def _enabled_config(vault: Vault) -> config.Config:
    return config.Config(vault=vault.root, submit_enabled=True)


def _preview(
    tmp_path: Path, transport: RecordingTransport
) -> tuple[Vault, submit.SubmissionPreview]:
    vault, _course = _vault(tmp_path)
    return vault, prepare(
        vault,
        transport,
        _enabled_config(vault),
        course="COURSE101",
        item="Lab4",
        file=_payload(tmp_path),
        le_version=LE,
        capability=ENABLED,
    )


def test_the_shipped_build_disables_submission() -> None:
    assert _release.SUBMISSION_AVAILABLE is False
    assert submit.release_capability().available is False


def test_enable_submit_refuses_in_a_disabled_build(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)

    with pytest.raises(SubmissionRefused):
        submit.enable_submit(config.Config(vault=vault.root))


def test_prepare_refuses_in_a_disabled_build_and_sends_nothing(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)
    transport = RecordingTransport()

    with pytest.raises(SubmissionRefused):
        prepare(
            vault,
            transport,
            _enabled_config(vault),
            course="COURSE101",
            item="Lab4",
            file=_payload(tmp_path),
            le_version=LE,
        )

    assert transport.posts == []
    assert transport.gets == []


def test_submit_without_acknowledgement_sends_nothing(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)
    transport = RecordingTransport()

    with pytest.raises(SubmissionRefused, match="enable-submit"):
        prepare(
            vault,
            transport,
            config.Config(vault=vault.root, submit_enabled=False),
            course="COURSE101",
            item="Lab4",
            file=_payload(tmp_path),
            le_version=LE,
            capability=ENABLED,
        )

    assert transport.posts == []


def test_preview_is_complete_and_names_the_exact_phrase(tmp_path: Path) -> None:
    transport = RecordingTransport()
    _vault_obj, preview = _preview(tmp_path, transport)

    text = render_preview(preview)

    assert transport.posts == []
    assert "nothing has been uploaded yet" in text
    assert "COURSE101" in text
    assert "Lab 4" in text
    assert f"id {FOLDER_ID}" in text
    assert preview.staged.sha256 in text
    assert f"{preview.staged.size} bytes" in text
    assert "submissions/mysubmissions/" in text
    assert "resolved, not upload-verified" in text
    assert preview.phrase in text
    assert preview.code in preview.phrase
    assert preview.staged.filename in preview.phrase
    assert "return control to the student" in text


@pytest.mark.parametrize(
    "phrase",
    ["", "   ", "UPLOAD", "UPLOAD WRONGCD report.pdf", "yes", "y", "UPLOAD {code} other.pdf"],
)
def test_a_wrong_phrase_uploads_nothing(tmp_path: Path, phrase: str) -> None:
    transport = RecordingTransport()
    vault, preview = _preview(tmp_path, transport)

    with pytest.raises(SubmissionRefused):
        confirm_and_upload(
            vault,
            transport,
            preview,
            phrase=phrase.format(code=preview.code),
            interactive=True,
            capability=ENABLED,
        )

    assert transport.posts == []
    assert not preview.staged.path.exists()


def test_a_non_interactive_process_stops_at_the_preview(tmp_path: Path) -> None:
    transport = RecordingTransport()
    vault, preview = _preview(tmp_path, transport)

    with pytest.raises(SubmissionRefused, match="controlling terminal"):
        confirm_and_upload(
            vault,
            transport,
            preview,
            phrase=preview.phrase,
            interactive=False,
            capability=ENABLED,
        )

    assert transport.posts == []


def test_a_second_attempt_with_the_same_code_uploads_nothing(tmp_path: Path) -> None:
    transport = RecordingTransport(
        readback=[
            {
                "SubmissionDate": "2999-01-01T00:00:00Z",
                "Files": [{"FileName": "report.pdf", "Size": 13}],
            }
        ]
    )
    vault, preview = _preview(tmp_path, transport)
    phrase = preview.phrase

    confirm_and_upload(
        vault, transport, preview, phrase=phrase, interactive=True, capability=ENABLED
    )

    with pytest.raises(SubmissionRefused, match="already used"):
        confirm_and_upload(
            vault, transport, preview, phrase=phrase, interactive=True, capability=ENABLED
        )

    assert len(transport.posts) == 1


def test_an_expired_confirmation_uploads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = RecordingTransport()
    vault, preview = _preview(tmp_path, transport)
    later = clock.now().timestamp() + CONFIRMATION_TTL_SECONDS + 1
    monkeypatch.setattr(
        submit.clock, "now", lambda: clock.datetime.fromtimestamp(later, tz=clock.UTC)
    )

    with pytest.raises(SubmissionRefused, match="expired"):
        confirm_and_upload(
            vault, transport, preview, phrase=preview.phrase, interactive=True, capability=ENABLED
        )

    assert transport.posts == []


def test_editing_the_original_after_the_preview_cannot_change_the_sent_bytes(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport(
        readback=[
            {
                "SubmissionDate": "2999-01-01T00:00:00Z",
                "Files": [{"FileName": "report.pdf", "Size": 13}],
            }
        ]
    )
    vault, preview = _preview(tmp_path, transport)
    (tmp_path / "report.pdf").write_text("swapped hostile content\n", encoding="utf-8")

    confirm_and_upload(
        vault, transport, preview, phrase=preview.phrase, interactive=True, capability=ENABLED
    )

    _path, body, _content_type = transport.posts[0]
    assert b"final answer" in body
    assert b"swapped hostile content" not in body


def test_a_group_dropbox_is_named_then_refused_with_no_post(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)
    transport = RecordingTransport(folders=[{"Id": FOLDER_ID, "Name": "Lab 4", "GroupTypeId": 42}])

    with pytest.raises(SubmissionRefused) as raised:
        prepare(
            vault,
            transport,
            _enabled_config(vault),
            course="COURSE101",
            item="Lab4",
            file=_payload(tmp_path),
            le_version=LE,
            capability=ENABLED,
        )

    assert "group" in str(raised.value)
    assert "42" in str(raised.value)
    assert transport.posts == []


def test_an_unsupported_le_version_keeps_submission_disabled(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)
    transport = RecordingTransport()

    for version in (None, "", "1.81"):
        with pytest.raises(SubmissionRefused):
            prepare(
                vault,
                transport,
                _enabled_config(vault),
                course="COURSE101",
                item="Lab4",
                file=_payload(tmp_path),
                le_version=version,
                capability=ENABLED,
            )

    assert transport.posts == []


def test_read_back_failures_are_unverified_and_never_retry(tmp_path: Path) -> None:
    cases: list[tuple[str, RecordingTransport]] = [
        ("missing", RecordingTransport(readback=[])),
        (
            "stale",
            RecordingTransport(
                readback=[
                    {
                        "SubmissionDate": "1999-01-01T00:00:00Z",
                        "Files": [{"FileName": "report.pdf", "Size": 13}],
                    }
                ]
            ),
        ),
        (
            "ambiguous",
            RecordingTransport(
                readback=[
                    {
                        "SubmissionDate": "2999-01-01T00:00:00Z",
                        "Files": [
                            {"FileName": "report.pdf", "Size": 13},
                            {"FileName": "report.pdf", "Size": 13},
                        ],
                    }
                ]
            ),
        ),
        (
            "size mismatch",
            RecordingTransport(
                readback=[
                    {
                        "SubmissionDate": "2999-01-01T00:00:00Z",
                        "Files": [{"FileName": "report.pdf", "Size": 999}],
                    }
                ]
            ),
        ),
        ("unreadable", RecordingTransport(readback_error=OSError("network down"))),
    ]

    for label, transport in cases:
        workspace = tmp_path / label.replace(" ", "-")
        workspace.mkdir()
        vault, preview = _preview(workspace, transport)
        with pytest.raises(SubmissionUnverified):
            confirm_and_upload(
                vault,
                transport,
                preview,
                phrase=preview.phrase,
                interactive=True,
                capability=ENABLED,
            )
        assert len(transport.posts) == 1, label
        receipts = sorted((vault.state() / "submissions").glob("*.json"))
        assert len(receipts) == 1, label
        payload = json.loads(receipts[0].read_text(encoding="utf-8"))
        assert payload["status"] == "unknown", label


def test_a_receipt_records_the_outcome_without_leaking_anything(tmp_path: Path) -> None:
    transport = RecordingTransport(
        readback=[
            {
                "SubmissionDate": "2999-01-01T00:00:00Z",
                "Files": [{"FileName": "report.pdf", "Size": 13}],
            }
        ]
    )
    vault, preview = _preview(tmp_path, transport)
    phrase = preview.phrase

    receipt = confirm_and_upload(
        vault, transport, preview, phrase=phrase, interactive=True, capability=ENABLED
    )

    stored = sorted((vault.state() / "submissions").glob("*.json"))
    payload = json.loads(stored[0].read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert receipt.status == "verified"
    assert payload["location"] == "external"
    assert payload["selected_path"] is None
    assert payload["filename"] == "report.pdf"
    assert preview.code not in serialized
    assert phrase not in serialized
    assert str(tmp_path) not in serialized
    assert "Cookie" not in serialized
    assert set(payload) == {
        "completed_at",
        "confirmed_at",
        "course",
        "filename",
        "folder_id",
        "location",
        "outcome",
        "receipt_version",
        "selected_path",
        "sha256",
        "size",
        "status",
    }


def test_the_multipart_body_puts_the_json_part_first_and_escapes_the_filename() -> None:
    body = build_submission_body('we"ird\\name.pdf', b"bytes", boundary="BOUND")

    text = body.decode("utf-8", errors="replace")
    assert text.index('name=""\r\nContent-Type: application/json') < text.index("filename=")
    assert 'filename="we%22ird%5Cname.pdf"' in text
    assert text.startswith("--BOUND\r\n")
    assert text.endswith("--BOUND--\r\n")


@pytest.mark.parametrize("filename", ["nul\x00.pdf", "line\nbreak.pdf", "tab\tted.pdf", "", "   "])
def test_a_hostile_filename_is_refused(filename: str) -> None:
    with pytest.raises(SubmissionRefused):
        safe_filename(filename)


def test_staged_files_are_private_and_removed(tmp_path: Path) -> None:
    transport = RecordingTransport()
    vault, preview = _preview(tmp_path, transport)
    staged = preview.staged.path

    assert staged.is_file()
    assert staged.name.endswith(".part")
    assert "report" not in staged.name
    if os.name != "nt":
        assert stat.S_IMODE(staged.stat().st_mode) == 0o600

    with pytest.raises(SubmissionRefused):
        confirm_and_upload(
            vault, transport, preview, phrase="wrong", interactive=True, capability=ENABLED
        )

    assert not staged.exists()


def test_stale_staging_cleanup_never_leaves_its_own_directory(tmp_path: Path) -> None:
    vault, _course = _vault(tmp_path)
    staging = vault.state() / submit.STAGING_DIRNAME
    staging.mkdir(parents=True)
    stale = staging / "old.part"
    stale.write_bytes(b"stale")
    os.utime(stale, (0, 0))
    # Both bystanders are made just as old as the stale staged file, so only the directory bound
    # can save them. With a fresh mtime the age rule would spare them and prove nothing.
    outsider = vault.state() / "keep-me.json"
    outsider.write_text("{}\n", encoding="utf-8")
    os.utime(outsider, (0, 0))
    sibling = vault.root / "Spring 2026" / "keep-me-too.md"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("course material\n", encoding="utf-8")
    os.utime(sibling, (0, 0))

    removed = cleanup_staging(vault)

    assert removed == 1
    assert not stale.exists()
    assert outsider.is_file()
    assert sibling.is_file()


def test_no_bypass_flag_or_environment_variable_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _course = _vault(tmp_path)
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=vault.root))
    for name in (
        "A2L_YES",
        "A2L_FORCE",
        "A2L_CONFIRM",
        "A2L_SUBMIT",
        "A2L_ASSUME_YES",
        "A2L_NON_INTERACTIVE",
    ):
        monkeypatch.setenv(name, "1")
    runner = CliRunner()

    help_text = flatten_help(runner.invoke(app, ["submit", "--help"]).output)
    abbreviated = runner.invoke(app, ["submit", "--con", "COURSE101", "Lab4", "x.pdf"])

    for forbidden in ("--yes", "--force", "--assume-yes", "--no-confirm", "--non-interactive"):
        assert forbidden not in help_text
    assert abbreviated.exit_code == 2
    assert "No such option" in flatten_help(abbreviated.output)


def test_the_public_cli_refuses_because_the_build_disables_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production path must refuse without any injected capability."""
    vault, _course = _vault(tmp_path)
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=vault.root))
    runner = CliRunner()

    result = runner.invoke(app, ["enable-submit"])

    assert result.exit_code != 0
    assert "disabled in this build" in flatten_help(result.output)
