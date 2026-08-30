"""Upload one finished local file to a selected LEARN Dropbox, after the human confirms it.

This is the only mutating LEARN action in Agent2Learn, and it is disabled in this build. Two
independent gates stand in front of it, and neither is sufficient alone:

1. ``a2l enable-submit`` — a one-time local acknowledgement that stores ``submit_enabled`` and
   uploads nothing.
2. A fresh, per-file confirmation typed at a controlling terminal, containing a random code shown
   only in that preview and the exact filename.

On top of both, :data:`agent2learn._release.SUBMISSION_AVAILABLE` gates the whole feature at build
time. Nothing here reads an environment variable, accepts a ``--yes``/``--force`` style flag, or
consumes piped input as consent, and there is no automatic retry: one confirmation authorises at
most one POST, and the code is consumed whether that POST succeeds or fails.

**What the terminal gate does and does not prove.** A controlling TTY proves interactivity, not
human identity. Hostile software that already controls the terminal can synthesise keystrokes.
The gate prevents accidental and ordinary unattended mutation; what keeps an *agent* from
submitting on the student's behalf is the skill contract requiring it to stop at the preview and
hand back control. This is not cryptographic proof of a human action, and must never be described
as one.

**Only a proven route.** v0.1 uses the documented individual-student route
``…/dropbox/folders/{folder}/submissions/mysubmissions/`` and nothing else. There is no
``mypost``, and no fallback between mutating endpoints: an instance whose LE version does not
support the route family keeps submission disabled. A group Dropbox is recognised only so the
preview can name it and refuse before any confirmation.

**Verification, not optimism.** After the single POST the submissions list is read back and must
contain exactly one record matching the folder, filename, byte size, and a timestamp after the
confirmation. A stale prior file, a duplicate name, a size mismatch, an ambiguous list, or an
unreadable read-back is a failed verification that reports uncertainty and sends the student to
LEARN — it never retries.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import string
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from agent2learn import _release, clock, config, paths
from agent2learn import index as course_index
from agent2learn.errors import A2LError
from agent2learn.vault import Vault

SUBMISSION_RECEIPT_VERSION = 1
CONFIRMATION_TTL_SECONDS = 300
# Built from its intent rather than written out: the ambiguous glyphs are excluded so a user
# reading a code aloud or off a screen cannot confuse I/1 or O/0. Writing the 32 characters as
# a literal also reads as a high-entropy secret to scanners, which it is not.
CODE_ALPHABET = "".join(
    character for character in string.ascii_uppercase + string.digits if character not in "IO01"
)
CODE_LENGTH = 6
MIN_LE_VERSION = (1, 82)
STAGING_DIRNAME = "submit-staging"
RECEIPTS_DIRNAME = "submissions"

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FILENAME_ESCAPE = {'"': "%22", "\\": "%5C", "\r": "", "\n": ""}


class SubmissionRefused(A2LError):
    """A submission was refused before any mutating request was attempted."""


class SubmissionUnverified(A2LError):
    """A POST was attempted but read-back could not prove the exact expected record."""


@dataclass(frozen=True)
class SubmissionCapability:
    """Explicit permission for this process to attempt a mutating upload."""

    available: bool
    reason: str


def release_capability() -> SubmissionCapability:
    """Return the capability this build ships with."""

    return SubmissionCapability(
        available=_release.SUBMISSION_AVAILABLE,
        reason="upload is disabled in this build until the supervised release gate passes",
    )


class SubmissionTransport(Protocol):
    """The narrow transport surface a submission needs."""

    def get_json(self, path: str) -> object: ...

    def post_once(
        self, path: str, body: bytes | SubmissionBody, *, content_type: str
    ) -> object: ...


@dataclass(frozen=True)
class SubmissionBody:
    """A repeatable multipart body streamed from the private staging file.

    The body exposes its exact byte length for the API client's explicit ``Content-Length`` while
    keeping the potentially large file payload out of memory.  Iteration is repeatable so a test
    transport can inspect it and Requests can consume it once for the actual POST.
    """

    path: Path
    filename: str
    size: int
    boundary: str
    root: Path | None = None

    @property
    def content_length(self) -> int:
        return len(self._prefix()) + self.size + len(self._suffix())

    def __iter__(self) -> Iterator[bytes]:
        yield self._prefix()
        if self.root is not None and paths.has_link_component(self.path, root=self.root):
            raise SubmissionRefused("the staged path contains a symlink or junction")
        if paths.is_link(self.path):
            raise SubmissionRefused("the staged path contains a symlink or junction")
        descriptor = os.open(
            os.fspath(paths.long_path(self.path)), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or getattr(file_stat, "st_nlink", 1) != 1:
                raise SubmissionRefused("the staged file is no longer a private regular file")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                yield from iter(lambda: handle.read(1024 * 1024), b"")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        yield self._suffix()

    def _prefix(self) -> bytes:
        safe = safe_filename(self.filename)
        descriptor = json.dumps({"Text": "", "HTML": None}, separators=(",", ":"))
        marker = f"--{self.boundary}".encode()
        return (
            b"\r\n".join(
                [
                    marker,
                    b'Content-Disposition: form-data; name=""',
                    b"Content-Type: application/json",
                    b"",
                    descriptor.encode("utf-8"),
                    marker,
                    f'Content-Disposition: form-data; name=""; filename="{safe}"'.encode(),
                    b"Content-Type: application/octet-stream",
                    b"",
                ]
            )
            + b"\r\n"
        )

    def _suffix(self) -> bytes:
        return f"\r\n--{self.boundary}--\r\n".encode()


@dataclass(frozen=True)
class SubmissionTarget:
    """A resolved Dropbox folder and the exact routes that would be used."""

    course: str
    course_code: str
    org_unit_id: int
    folder_id: int
    folder_name: str
    endpoint: str
    readback: str
    group_submission: bool
    group_note: str | None
    upload_verified: bool


@dataclass(frozen=True)
class StagedFile:
    """A private copy of the exact bytes that would be sent."""

    path: Path
    filename: str
    sha256: str
    size: int
    staged_at: str
    expires_at: str
    selected_display: str


@dataclass
class SubmissionPreview:
    """A complete preview plus the one-shot confirmation it authorises."""

    target: SubmissionTarget
    staged: StagedFile
    code: str
    consumed: bool = False

    @property
    def phrase(self) -> str:
        """The exact phrase the human must type: the shown code and the exact filename."""
        return f"UPLOAD {self.code} {self.staged.filename}"


@dataclass(frozen=True)
class SubmissionReceipt:
    """A minimal, privacy-bounded record of one attempt, verified or not."""

    course: str
    folder_id: int
    filename: str
    sha256: str
    size: int
    location: str
    selected_path: str | None
    confirmed_at: str
    post_attempted: bool
    post_at: str | None
    readback_at: str | None
    http_status_class: str
    completed_at: str
    status: str
    outcome: str
    receipt_version: int = SUBMISSION_RECEIPT_VERSION


def require_available(
    cfg: config.Config | None = None, *, capability: SubmissionCapability | None = None
) -> None:
    """Refuse an upload before anything else happens, including authentication.

    Checked first so a build with uploads disabled never sends the user through a sign-in flow for
    a feature it will refuse anyway: "run: a2l auth" would be a false next action.
    """

    permission = capability or release_capability()
    if not permission.available:
        raise SubmissionRefused(permission.reason)
    if cfg is not None and not cfg.submit_enabled:
        raise SubmissionRefused("submission is not acknowledged · run: a2l enable-submit")


def enable_submit(
    cfg: config.Config, *, capability: SubmissionCapability | None = None
) -> config.Config:
    """Record the one-time local acknowledgement. This never uploads anything."""

    require_available(capability=capability)
    updated = replace(cfg, submit_enabled=True)
    config.save(updated)
    return updated


def build_submission_body(filename: str, payload: bytes, *, boundary: str) -> bytes:
    """Build the documented ``multipart/mixed`` body: JSON RichText part first, then the file.

    The empty ``name=""`` on the file part is what D2L documents, not an oversight. A filename
    containing a quote or a backslash is percent-escaped rather than passed through, and a control
    character is refused outright: a header a server parses must never be attacker-shaped by a
    filename on disk.
    """

    if not isinstance(payload, bytes):
        raise ValueError("submission payload must be bytes")
    # Reuse the streaming framing so the legacy helper and the production upload have byte-for-byte
    # identical multipart syntax.  ``SubmissionBody`` only opens its path during iteration; this
    # in-memory compatibility helper supplies a temporary one-shot payload instead.
    descriptor = json.dumps({"Text": "", "HTML": None}, separators=(",", ":"))
    marker = f"--{boundary}".encode()
    safe_name = safe_filename(filename)
    prefix = b"\r\n".join(
        [
            marker,
            b'Content-Disposition: form-data; name=""',
            b"Content-Type: application/json",
            b"",
            descriptor.encode("utf-8"),
            marker,
            (f'Content-Disposition: form-data; name=""; filename="{safe_name}"'.encode()),
            b"Content-Type: application/octet-stream",
            b"",
        ]
    )
    return prefix + b"\r\n" + payload + f"\r\n--{boundary}--\r\n".encode()


def safe_filename(filename: str) -> str:
    """Return a filename safe to place in a multipart header, refusing control characters."""

    if not isinstance(filename, str) or not filename.strip():
        raise SubmissionRefused("submission filename must not be empty")
    if _CONTROL.search(filename):
        raise SubmissionRefused("submission filename contains a control character")
    escaped = filename
    for character, replacement in _FILENAME_ESCAPE.items():
        escaped = escaped.replace(character, replacement)
    return escaped


def prepare(
    vault: Vault,
    client: SubmissionTransport,
    cfg: config.Config,
    *,
    course: str,
    item: str,
    file: Path,
    le_version: str | None,
    capability: SubmissionCapability | None = None,
) -> SubmissionPreview:
    """Resolve the exact target, stage the exact bytes, and build the complete preview.

    Staging happens before the preview so the bytes a human approves are the bytes that would be
    sent. Replacing or editing the original afterwards cannot change them.
    """

    require_available(cfg, capability=capability)
    # Preparation is a lifecycle boundary: stale opaque parts are removed before a new preview,
    # and a linked staging directory fails closed instead of redirecting bytes outside the vault.
    cleanup_staging(vault)

    selected = Path(file).expanduser()
    if not paths.long_path(selected).is_file():
        raise SubmissionRefused("the file to submit does not exist")
    if paths.is_link(selected):
        raise SubmissionRefused("refusing to submit through a symlink")
    # Validate the header identity before creating any staging bytes; a control character in a
    # local filename must be a pre-upload refusal, not an attempted request that later fails while
    # the multipart body is being streamed.
    safe_filename(selected.name)

    course_dir = course_index.resolve_course(vault, course)
    if paths.has_link_component(course_dir, root=vault.root):
        raise SubmissionRefused("course path contains a symlink or junction")
    target = _resolve_target(client, vault, course_dir, item, le_version)
    if target.group_submission:
        raise SubmissionRefused(
            f"{target.group_note} · group submission is unsupported in v0.1; submit in LEARN"
        )
    staged = _stage(vault, selected)
    try:
        return SubmissionPreview(target=target, staged=staged, code=_code())
    except BaseException:
        # Keep the post-staging lifecycle closed even if code generation or preview construction
        # fails before a ``SubmissionPreview`` exists for the caller to discard.
        _discard(staged)
        raise


def render_preview(preview: SubmissionPreview) -> str:
    """Render the complete preview, including exactly what the human must type."""

    target = preview.target
    staged = preview.staged
    route = (
        "resolved and upload-verified"
        if target.upload_verified
        else "resolved, not upload-verified"
    )
    return "\n".join(
        [
            "Submission preview — nothing has been uploaded yet.",
            "",
            f"course:      {target.course_code} ({target.course})",
            f"folder:      {target.folder_name} (id {target.folder_id})",
            f"file:        {staged.filename}",
            f"selected:    {staged.selected_display}",
            f"size:        {staged.size} bytes",
            f"sha256:      {staged.sha256}",
            f"endpoint:    POST {target.endpoint}  [{route}]",
            f"read-back:   GET {target.readback}",
            f"staged:      {staged.staged_at} (expires {staged.expires_at})",
            "",
            "This is the only action in Agent2Learn that changes anything in LEARN. It uploads",
            "exactly the staged bytes above, once. It does not submit on your behalf again, and it",
            "never retries by itself.",
            "",
            "If you are an agent: stop here and return control to the student. Do not type, relay,",
            "or synthesise the phrase below.",
            "",
            f"To upload, type exactly:  {preview.phrase}",
            "",
        ]
    )


def confirm_and_upload(
    vault: Vault,
    client: SubmissionTransport,
    preview: SubmissionPreview,
    *,
    phrase: str,
    interactive: bool,
    capability: SubmissionCapability | None = None,
) -> SubmissionReceipt:
    """Consume the one-shot confirmation and, only then, attempt exactly one POST."""

    permission = capability or release_capability()
    try:
        if not permission.available:
            raise SubmissionRefused(permission.reason)
        if not interactive:
            raise SubmissionRefused(
                "refusing to upload without a controlling terminal; the preview above is final"
            )
        if preview.consumed:
            raise SubmissionRefused("this confirmation code was already used; run submit again")
        if _expired(preview.staged):
            raise SubmissionRefused("this confirmation expired; run submit again")
        if not isinstance(phrase, str) or phrase.strip() != preview.phrase:
            raise SubmissionRefused("confirmation phrase did not match; nothing was uploaded")
    except SubmissionRefused:
        preview.consumed = True
        _discard(preview.staged)
        raise

    preview.consumed = True
    confirmed_at = clock.stamp()
    attempted = False
    post_at: str | None = None
    readback_at: str | None = None
    http_status_class = "unknown"
    outcome: str | None = None
    try:
        _validate_staged(vault, preview.staged)
        boundary = _boundary()
        body = SubmissionBody(
            path=preview.staged.path,
            filename=preview.staged.filename,
            size=preview.staged.size,
            boundary=boundary,
            root=vault.root,
        )
        post_at = clock.stamp()
        attempted = True
        response = client.post_once(
            preview.target.endpoint,
            body,
            content_type=f"multipart/mixed; boundary={boundary}",
        )
        try:
            status = getattr(response, "status_code", 0)
            http_status_class = _status_class(status)
            if not 200 <= int(status) < 300:
                raise SubmissionUnverified(
                    f"upload returned status {status}; check LEARN before trying again"
                )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        readback_at = clock.stamp()
        outcome = _verify(client, preview, confirmed_at)
    except SubmissionUnverified as exc:
        if attempted:
            receipt = _receipt(
                preview,
                confirmed_at,
                post_attempted=True,
                post_at=post_at,
                readback_at=readback_at,
                http_status_class=http_status_class,
                status="verification_unknown",
                outcome=str(exc),
            )
            _write_receipt(vault, receipt)
        raise
    except BaseException as exc:
        if attempted:
            receipt = _receipt(
                preview,
                confirmed_at,
                post_attempted=True,
                post_at=post_at,
                readback_at=readback_at,
                http_status_class=http_status_class,
                status="verification_unknown",
                outcome=(
                    "upload attempt outcome could not be verified; inspect LEARN before "
                    "resubmitting"
                ),
            )
            _write_receipt(vault, receipt)
            raise SubmissionUnverified(
                "upload was attempted but could not verify the outcome; inspect LEARN before "
                "resubmitting"
            ) from exc
        raise
    finally:
        _discard(preview.staged)

    assert outcome is not None
    receipt = _receipt(
        preview,
        confirmed_at,
        post_attempted=True,
        post_at=post_at,
        readback_at=readback_at,
        http_status_class=http_status_class,
        status="verified",
        outcome=outcome,
    )
    _write_receipt(vault, receipt)
    return receipt


def cleanup_staging(vault: Vault, *, now: datetime | None = None) -> int:
    """Remove expired staged files, scanning only the exact staging directory."""

    directory = _staging_dir(vault)
    if paths.has_link_component(directory, root=vault.root):
        raise A2LError("submission staging path contains a symlink or junction")
    moment = now or clock.now()
    removed = 0
    try:
        entries = sorted(paths.long_path(directory).iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return 0
    except OSError as exc:
        raise A2LError("submission staging is unreadable") from exc
    for entry in entries:
        if entry.parent != paths.long_path(directory) or entry.is_dir():
            continue
        if paths.is_link(entry):
            continue
        try:
            age = moment.timestamp() - entry.stat().st_mtime
        except OSError:
            continue
        if age >= CONFIRMATION_TTL_SECONDS:
            _remove(entry)
            removed += 1
    return removed


def _resolve_target(
    client: SubmissionTransport,
    vault: Vault,
    course_dir: Path,
    item: str,
    le_version: str | None,
) -> SubmissionTarget:
    org_unit_id = _org_unit(course_dir)
    _require_supported_le(le_version)
    folders = client.get_json(f"/d2l/api/le/{le_version}/{org_unit_id}/dropbox/folders/")
    if not isinstance(folders, list):
        raise SubmissionRefused("the Dropbox folder list was not readable")
    wanted = _compact(item)
    matches = [
        folder
        for folder in folders
        if isinstance(folder, dict) and _compact(str(folder.get("Name") or "")) == wanted
    ]
    if len(matches) != 1:
        raise SubmissionRefused(
            "name the Dropbox folder exactly; it did not match exactly one folder"
        )
    folder = matches[0]
    folder_id = folder.get("Id")
    if isinstance(folder_id, bool) or not isinstance(folder_id, int):
        raise SubmissionRefused("the Dropbox folder has no usable id")
    group_type = folder.get("GroupTypeId")
    group = group_type is not None
    code, _name = _course_identity(course_dir)
    return SubmissionTarget(
        course=paths.rel_posix(course_dir, vault.root),
        course_code=code,
        org_unit_id=org_unit_id,
        folder_id=folder_id,
        folder_name=str(folder.get("Name") or f"folder {folder_id}"),
        endpoint=(
            f"/d2l/api/le/{le_version}/{org_unit_id}/dropbox/folders/{folder_id}"
            "/submissions/mysubmissions/"
        ),
        # The ``mysubmissions`` projection is the only route that proves the current user's
        # upload.  The unqualified ``submissions`` route enumerates entities and is not sufficient
        # for attribution.
        readback=(
            f"/d2l/api/le/{le_version}/{org_unit_id}/dropbox/folders/{folder_id}"
            "/submissions/mysubmissions/"
        ),
        group_submission=group,
        group_note=(
            f"group Dropbox (group type {group_type}), visible to your group" if group else None
        ),
        upload_verified=False,
    )


def _require_supported_le(le_version: str | None) -> None:
    if not isinstance(le_version, str) or not le_version:
        raise SubmissionRefused("calibration is required before submission · run: a2l courses")
    try:
        parts = tuple(int(part) for part in le_version.split(".")[:2])
    except ValueError:
        raise SubmissionRefused("the discovered LE version is unreadable") from None
    if len(parts) < 2 or parts < MIN_LE_VERSION:
        raise SubmissionRefused(
            "this LEARN instance does not advertise a supported submission route"
        )


def _stage(vault: Vault, selected: Path) -> StagedFile:
    directory = _staging_dir(vault)
    try:
        paths.ensure_dir(directory, root=vault.root)
    except ValueError as exc:
        raise SubmissionRefused("submission staging path contains a symlink or junction") from exc
    if paths.has_link_component(directory, root=vault.root):
        raise SubmissionRefused("submission staging path contains a symlink or junction")
    file_descriptor, raw_destination = tempfile.mkstemp(
        prefix=".a2l-", suffix=".part", dir=os.fspath(paths.long_path(directory))
    )
    destination = paths.plain_path(Path(raw_destination))
    try:
        if paths.has_link_component(destination, root=vault.root):
            raise SubmissionRefused("submission staging path contains a symlink or junction")
    except BaseException:
        os.close(file_descriptor)
        _remove(destination)
        raise
    digest = sha256()
    size = 0
    descriptor_open = True
    try:
        with os.fdopen(file_descriptor, "wb") as staged:
            descriptor_open = False
            with open(os.fspath(paths.long_path(selected)), "rb") as source:
                # ``mkstemp`` creates the part as 0600 before this copy starts.  Keep the explicit
                # tightening for platforms/filesystems that apply a different inherited mode.
                _tighten(destination)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())
    except BaseException:
        if descriptor_open:
            os.close(file_descriptor)
        _remove(destination)
        raise
    _tighten(destination)
    staged_at = clock.now()
    return StagedFile(
        path=destination,
        filename=selected.name,
        sha256=digest.hexdigest(),
        size=size,
        staged_at=clock.stamp(),
        expires_at=(staged_at + timedelta(seconds=CONFIRMATION_TTL_SECONDS))
        .isoformat()
        .replace("+00:00", "Z"),
        selected_display=_selected_display(vault, selected),
    )


def _verify(client: SubmissionTransport, preview: SubmissionPreview, confirmed_at: str) -> str:
    try:
        records = client.get_json(preview.target.readback)
    except Exception as exc:  # noqa: BLE001 - any read-back failure is unverified, never a retry
        raise SubmissionUnverified(
            "upload was sent but read-back failed; open LEARN to confirm before resubmitting"
        ) from exc
    if not isinstance(records, list):
        raise SubmissionUnverified("read-back was not a submission list; confirm in LEARN")

    matches = []
    for entry in _iter_files(records):
        filename = entry.get("FileName")
        if (
            isinstance(filename, str)
            and filename == preview.staged.filename
            and _folder_matches(entry, preview.target.folder_id)
        ):
            matches.append(entry)
    if not matches:
        raise SubmissionUnverified("read-back did not list the uploaded file; confirm in LEARN")
    confirmed = _parse_instant(confirmed_at)
    if confirmed is None:
        raise SubmissionUnverified("confirmation timestamp was unreadable; confirm in LEARN")
    fresh = []
    for entry in matches:
        submitted = _parse_instant(entry.get("SubmissionDate"))
        if submitted is not None and submitted > confirmed:
            fresh.append(entry)
    if len(fresh) != 1:
        raise SubmissionUnverified(
            "read-back was ambiguous or matched an earlier upload; confirm in LEARN"
        )
    reported = fresh[0].get("Size")
    if (
        isinstance(reported, bool)
        or not isinstance(reported, int)
        or reported != preview.staged.size
    ):
        raise SubmissionUnverified(
            "read-back size did not match the staged bytes; confirm in LEARN"
        )
    return "read-back matched folder, filename, size, and a timestamp after confirmation"


def _iter_files(records: list[object]) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        entity = record.get("Entity")
        if entity is not None and (
            not isinstance(entity, dict) or entity.get("EntityType") not in (None, "User")
        ):
            # The current-user projection should never contain a group/entity submission.  Keep
            # this check even though the route scopes it, so a route or server-shape regression
            # cannot silently attribute a teammate's file.
            continue
        # D2L has returned both an outer Entity -> Submissions -> Files collection and a direct
        # submission object in older compatible projections.  Accept only these two documented
        # shapes; do not recursively walk arbitrary response data.
        submissions: object = record.get("Submissions") if "Submissions" in record else [record]
        if not isinstance(submissions, list):
            continue
        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            candidates = submission.get("Files")
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if isinstance(candidate, dict):
                    merged = dict(candidate)
                    merged.setdefault("SubmissionDate", submission.get("SubmissionDate"))
                    folder_values = [
                        container[key]
                        for container in (record, submission, candidate)
                        for key in ("FolderId", "DropboxFolderId")
                        if key in container
                    ]
                    valid_folder_values = [
                        value
                        for value in folder_values
                        if isinstance(value, int) and not isinstance(value, bool)
                    ]
                    if len(valid_folder_values) != len(folder_values):
                        merged["_a2l_invalid_folder_identifier"] = True
                    if len(set(valid_folder_values)) > 1:
                        merged["_a2l_conflicting_folder_identifiers"] = True
                    for key in ("FolderId", "DropboxFolderId"):
                        if key not in merged:
                            if key in submission:
                                merged[key] = submission[key]
                            elif key in record:
                                merged[key] = record[key]
                    files.append(merged)
    return files


def _folder_matches(entry: dict[str, object], folder_id: int) -> bool:
    """Accept an omitted folder field only because the current-user route scopes it."""

    if entry.get("_a2l_invalid_folder_identifier") or entry.get(
        "_a2l_conflicting_folder_identifiers"
    ):
        return False
    supplied: list[int] = []
    for key in ("FolderId", "DropboxFolderId"):
        value = entry.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        supplied.append(value)
    return not supplied or all(value == folder_id for value in supplied)


def _receipt(
    preview: SubmissionPreview,
    confirmed_at: str,
    *,
    post_attempted: bool,
    post_at: str | None,
    readback_at: str | None,
    http_status_class: str,
    status: str,
    outcome: str,
) -> SubmissionReceipt:
    staged = preview.staged
    inside = staged.selected_display != "external"
    return SubmissionReceipt(
        course=preview.target.course,
        folder_id=preview.target.folder_id,
        filename=staged.filename,
        sha256=staged.sha256,
        size=staged.size,
        location="vault" if inside else "external",
        selected_path=staged.selected_display if inside else None,
        confirmed_at=confirmed_at,
        post_attempted=post_attempted,
        post_at=post_at,
        readback_at=readback_at,
        http_status_class=http_status_class,
        completed_at=clock.stamp(),
        status=status,
        outcome=outcome,
    )


def _write_receipt(vault: Vault, receipt: SubmissionReceipt) -> Path:
    directory = vault.state() / RECEIPTS_DIRNAME
    try:
        paths.ensure_dir(directory, root=vault.root)
    except ValueError as exc:
        raise A2LError("submission receipt path contains a symlink or junction") from exc
    name = f"{receipt.completed_at.replace(':', '').replace('-', '')}-{receipt.folder_id}.json"
    payload = {
        "receipt_version": receipt.receipt_version,
        "course": receipt.course,
        "folder_id": receipt.folder_id,
        "filename": receipt.filename,
        "sha256": receipt.sha256,
        "size": receipt.size,
        "location": receipt.location,
        "selected_path": receipt.selected_path,
        "confirmed_at": receipt.confirmed_at,
        "post_attempted": receipt.post_attempted,
        "post_at": receipt.post_at,
        "readback_at": receipt.readback_at,
        "http_status_class": receipt.http_status_class,
        "completed_at": receipt.completed_at,
        "status": receipt.status,
        "outcome": receipt.outcome,
    }
    destination = directory / name
    paths.atomic_write_text(
        destination,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        root=vault.root,
    )
    return destination


def _staging_dir(vault: Vault) -> Path:
    return vault.state() / STAGING_DIRNAME


def _selected_display(vault: Vault, selected: Path) -> str:
    try:
        return paths.rel_posix(selected, vault.root)
    except (ValueError, OSError):
        return "external"


def _course_identity(course_dir: Path) -> tuple[str, str]:
    rows = course_index.read_content_map(course_dir)["topics"]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = row.get("course_code")
            if isinstance(code, str) and code:
                name = row.get("course_name")
                return code, name if isinstance(name, str) and name else code
    return course_dir.name, course_dir.name


def _org_unit(course_dir: Path) -> int:
    rows = course_index.read_content_map(course_dir)["topics"]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("course_org_unit_id")
            if isinstance(value, int):
                return value
            source_key = row.get("source_key")
            if isinstance(source_key, str):
                parts = source_key.split(":")
                if len(parts) > 1 and parts[1].isdigit():
                    return int(parts[1])
    raise SubmissionRefused("this course has no known LEARN org unit; run: a2l sync")


def _code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _boundary() -> str:
    return f"a2l{secrets.token_hex(16)}"


def _validate_staged(vault: Vault, staged: StagedFile) -> None:
    """Validate staged metadata without materialising the file in memory."""

    if paths.has_link_component(staged.path, root=vault.root):
        raise SubmissionRefused("the staged path contains a symlink or junction")
    try:
        file_stat = os.lstat(os.fspath(paths.long_path(staged.path)))
    except OSError as exc:
        raise SubmissionRefused("the staged file is no longer readable") from exc
    if not stat.S_ISREG(file_stat.st_mode) or getattr(file_stat, "st_nlink", 1) != 1:
        raise SubmissionRefused("the staged file is no longer a private regular file")
    digest = sha256()
    size = 0
    try:
        with open(os.fspath(paths.long_path(staged.path)), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise SubmissionRefused("the staged file is no longer readable") from exc
    if size != staged.size or digest.hexdigest() != staged.sha256:
        raise SubmissionRefused("the staged bytes changed after the preview; run submit again")


def _expired(staged: StagedFile) -> bool:
    try:
        deadline = datetime.fromisoformat(staged.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return clock.now() >= deadline


def _discard(staged: StagedFile) -> None:
    _remove(staged.path)


def discard_preview(preview: SubmissionPreview) -> None:
    """Discard an unconfirmed preview and its staged bytes."""

    preview.consumed = True
    _discard(preview.staged)


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _status_class(status: object) -> str:
    if isinstance(status, bool) or not isinstance(status, int):
        return "unknown"
    if 200 <= status < 300:
        return "2xx"
    if 300 <= status < 400:
        return "3xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status < 600:
        return "5xx"
    return "unknown"


def _remove(path: Path) -> None:
    try:
        paths.long_path(path).unlink()
    except (FileNotFoundError, IsADirectoryError, OSError):
        return


def _tighten(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - POSIX permission bits only
        return
    try:
        paths.long_path(path).chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return


def _compact(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.casefold()))


__all__ = [
    "CODE_LENGTH",
    "CONFIRMATION_TTL_SECONDS",
    "MIN_LE_VERSION",
    "SUBMISSION_RECEIPT_VERSION",
    "StagedFile",
    "SubmissionBody",
    "SubmissionCapability",
    "SubmissionPreview",
    "SubmissionReceipt",
    "SubmissionRefused",
    "SubmissionTarget",
    "SubmissionTransport",
    "SubmissionUnverified",
    "build_submission_body",
    "cleanup_staging",
    "confirm_and_upload",
    "discard_preview",
    "enable_submit",
    "prepare",
    "release_capability",
    "require_available",
    "render_preview",
    "safe_filename",
]
