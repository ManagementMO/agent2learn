"""Diagnostics, and a support report that is safe to paste in public.

Two audiences, two functions, deliberately not shared.

``render`` writes for the person at the keyboard. It may show their vault path, because
that is exactly what they need to see, and it always ends with **one** next command — a
diagnostic that lists six problems and no action is a diagnostic that gets ignored.

``report`` writes for a stranger reading a GitHub issue. It is built from an **allowlist**:
each field is named and rendered individually, and anything not named is dropped. A denylist
would only remove the leaks someone anticipated, and every check added later would silently
become a new way to leak a name, a course code, or a home directory.

``doctor`` contacts only the configured LEARN host. It performs no version check against
PyPI or GitHub, because a diagnostic command should not be a phone-home.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.parse import quote

import requests

from agent2learn import __version__, console, paths
from agent2learn import config as config_module
from agent2learn import session as session_module
from agent2learn.auth import cdp
from agent2learn.errors import A2LError, SessionExpired
from agent2learn.index import read_content_map
from agent2learn.vault import Vault

Status = Literal["ok", "warn", "fail"]

ISSUE_URL = "https://github.com/ManagementMO/agent2learn/issues/new"
LONG_PATH_ADVISORY = 240
_MAX_REPORT_BODY = 6_000

_STATUS_GLYPH: dict[Status, str] = {"ok": "ok", "warn": "warn", "fail": "fail"}
_GROUP_ORDER = (
    "Environment",
    "Filesystem",
    "Session",
    "Optional tools",
    "Skills",
    "Vault",
)


class DoctorClient(Protocol):
    """The small live-session surface that diagnostics need from the API client."""

    def get_json(self, path: str) -> object:
        """Fetch one same-origin JSON endpoint through the bounded API transport."""


_COURSE_SOURCE_DIRECTORIES = frozenset(
    {"announcements", "assignments", "content", "quizzes", "outlines"}
)
_SAFE_PUBLIC_NOTES = {"fs.vault": "vault root `~`"}
_PUBLIC_CHECK_NAMES = frozenset(
    {
        "config.load",
        "env.encoding",
        "env.platform",
        "env.python",
        "env.unavailable",
        "env.uv",
        "env.version",
        "fs.disk",
        "fs.git",
        "fs.long_paths",
        "fs.longest_path",
        "fs.unavailable",
        "fs.vault",
        "session.age",
        "session.api_versions",
        "session.backend",
        "session.present",
        "session.unavailable",
        "session.whoami",
        "skills.installed",
        "skills.unavailable",
        "tools.browser",
        "tools.tesseract",
        "tools.unavailable",
        "vault.citable",
        "vault.courses",
        "vault.empty_twins",
        "vault.gaps",
        "vault.last_sync",
        "vault.present",
        "vault.terms",
        "vault.unavailable",
    }
)
_PUBLIC_STATUSES = frozenset({"ok", "warn", "fail"})


@dataclass(frozen=True)
class Check:
    """One diagnostic result.

    ``detail`` and ``fix`` are written for the user's own terminal and legitimately contain
    vault paths and course names, so ``report`` never emits them.

    ``public`` is a marker for a check that has something genuinely useful to contribute to a
    support report. ``report`` still maps it through a fixed note allowlist, so a check added
    later cannot leak arbitrary text by default.
    """

    group: str
    name: str
    status: Status
    detail: str
    fix: str | None = None
    public: str | None = None


def run_checks(
    cfg: config_module.Config, vault: Vault | None, *, client: DoctorClient | None = None
) -> list[Check]:
    """Collect every diagnostic. Never raises: a failed check is itself a result."""
    checks: list[Check] = []
    checks.extend(_safe_group("Environment", "env.unavailable", _environment))
    checks.extend(_safe_group("Filesystem", "fs.unavailable", lambda: _filesystem(cfg, vault)))
    checks.extend(_safe_group("Session", "session.unavailable", lambda: _session(client)))
    checks.extend(_safe_group("Optional tools", "tools.unavailable", _optional_tools))
    checks.extend(_safe_group("Skills", "skills.unavailable", _skills))
    checks.extend(_safe_group("Vault", "vault.unavailable", lambda: _vault(vault)))
    return checks


def _safe_group(group: str, name: str, callback: Callable[[], list[Check]]) -> list[Check]:
    """Turn an unexpected diagnostic implementation error into a safe result."""
    try:
        result = callback()
    except Exception as exc:
        return [
            Check(
                group,
                name,
                "fail",
                f"{group.casefold()} check unavailable ({_exception_class(exc)})",
                "run: a2l doctor",
            )
        ]
    return (
        result
        if isinstance(result, list)
        else [
            Check(group, name, "fail", f"{group.casefold()} check unavailable", "run: a2l doctor")
        ]
    )


# ----------------------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------------------
def _environment() -> list[Check]:
    encoding = (getattr(sys.stdout, "encoding", None) or "unknown").casefold()
    encodable = console.GLYPH["ok"].isascii() or _can_encode(encoding)
    return [
        Check("Environment", "env.version", "ok", f"agent2learn {__version__}"),
        Check("Environment", "env.python", "ok", platform.python_version()),
        Check("Environment", "env.platform", "ok", f"{platform.system()} {platform.machine()}"),
        Check(
            "Environment",
            "env.uv",
            "ok" if shutil.which("uv") else "warn",
            "uv found" if shutil.which("uv") else "uv not on PATH",
            None if shutil.which("uv") else "install uv: https://docs.astral.sh/uv/",
        ),
        Check(
            "Environment",
            "env.encoding",
            "ok" if encodable else "warn",
            f"console encoding {encoding}",
            None if encodable else "output falls back to ASCII glyphs",
        ),
    ]


def _filesystem(cfg: config_module.Config, vault: Vault | None) -> list[Check]:
    checks: list[Check] = []
    root = cfg.vault
    exists = paths.long_path(root).is_dir()
    writable = exists and os.access(os.fspath(paths.long_path(root)), os.W_OK)
    checks.append(
        Check(
            "Filesystem",
            "fs.vault",
            "ok" if writable else ("fail" if exists else "warn"),
            f"{root}" if exists else f"{root} does not exist yet",
            None if writable else ("check folder permissions" if exists else "run: a2l init"),
            # The public report deliberately emits only this fixed, home-redacted shape.  The
            # terminal detail above remains useful locally without becoming a future leak.
            public=_SAFE_PUBLIC_NOTES["fs.vault"],
        )
    )

    if exists:
        try:
            free_gib = shutil.disk_usage(os.fspath(paths.long_path(root))).free / (1024**3)
        except OSError as exc:
            checks.append(
                Check(
                    "Filesystem",
                    "fs.disk",
                    "warn",
                    f"free space unavailable ({_exception_class(exc)})",
                    "check free disk space before the next sync",
                )
            )
        else:
            checks.append(
                Check(
                    "Filesystem",
                    "fs.disk",
                    "ok" if free_gib >= 2 else "warn",
                    f"{free_gib:.1f} GiB free",
                    None if free_gib >= 2 else "free disk space before the next sync",
                )
            )
        checks.append(_longest_path(root))

    checks.append(_long_paths_enabled())
    if vault is not None:
        checks.append(_git_tracking(vault))
    return checks


def _longest_path(root: Path) -> Check:
    longest_relative = 0
    longest_absolute = 0
    try:
        for path in paths.walk(root):
            longest_relative = max(longest_relative, len(path.relative_to(root).as_posix()))
            longest_absolute = max(longest_absolute, len(str(path)))
    except (OSError, RuntimeError, ValueError) as exc:
        return Check(
            "Filesystem",
            "fs.longest_path",
            "warn",
            f"longest path unavailable ({_exception_class(exc)})",
            "check vault permissions before the next sync",
        )

    over = longest_absolute > LONG_PATH_ADVISORY
    return Check(
        "Filesystem",
        "fs.longest_path",
        "warn" if over else "ok",
        f"longest path {longest_absolute} absolute / {longest_relative} vault-relative",
        # Agent2Learn itself handles long paths; the risk is other software touching the
        # same files, so the advice is to move the vault rather than to edit the registry.
        "some editors and sync clients struggle past 260 characters; a shorter vault root avoids it"
        if over
        else None,
    )


def _long_paths_enabled() -> Check:
    """Report the Windows long-path registry flag, informationally and never as a failure.

    Agent2Learn prefixes its own syscalls with ``\\\\?\\`` and works regardless, so this is
    context for a user debugging another tool — not something to fix on our account.
    """
    if os.name != "nt":
        return Check("Filesystem", "fs.long_paths", "ok", "not applicable on this platform")
    # winreg exists only on Windows, so mypy on a POSIX host cannot see its attributes.
    # The import is guarded by os.name above and every failure mode collapses to
    # "unreadable" — this flag is informational and must never break a diagnostic run.
    try:
        import winreg  # type: ignore[import-not-found,unused-ignore]

        with winreg.OpenKey(  # type: ignore[attr-defined,unused-ignore]
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined,unused-ignore]
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")  # type: ignore[attr-defined,unused-ignore]
        state = "enabled" if int(value) == 1 else "disabled"
    except Exception:
        state = "unreadable"
    return Check(
        "Filesystem",
        "fs.long_paths",
        "ok",
        f"Windows LongPathsEnabled: {state} (informational; a2l handles long paths itself)",
    )


def _git_tracking(vault: Vault) -> Check:
    """Fail when private material is tracked by Git; warn when course sources are.

    Ignore rules are not a privacy or copyright guarantee. A student who committed their
    vault before adding a `.gitignore` still has the files in history, and a public push
    would publish someone else's course material along with their own session state.
    """
    try:
        inside_worktree = _inside_git_worktree(vault.root)
        if not inside_worktree:
            return Check("Filesystem", "fs.git", "ok", "vault is not inside a Git repository")
        tracked = _tracked_files(vault.root)
    except (OSError, UnicodeError, RuntimeError):
        return Check("Filesystem", "fs.git", "warn", "Git metadata is unreadable")
    if tracked is None:
        return Check("Filesystem", "fs.git", "warn", "inside Git, but the file list is unreadable")

    normalized = [(entry, _git_entry_parts(entry)) for entry in tracked]
    private = sorted({entry for entry, parts in normalized if _is_private_git_entry(parts)})
    if private:
        return Check(
            "Filesystem",
            "fs.git",
            "fail",
            f"{len(private)} private file(s) are tracked by Git",
            "untrack them and rewrite history before pushing anywhere",
        )

    sources = [entry for entry, parts in normalized if _is_course_source_entry(parts)]
    if sources:
        return Check(
            "Filesystem",
            "fs.git",
            "warn",
            f"{len(sources)} course source file(s) are tracked by Git",
            "course material is not yours to redistribute; keep the vault out of a pushed repo",
        )
    return Check("Filesystem", "fs.git", "ok", "no private or course files are tracked")


def _session(client: DoctorClient | None) -> list[Check]:
    try:
        backend = session_module.backend_name()
    except Exception as exc:
        backend = "unavailable"
        backend_detail = f"backend unavailable ({_exception_class(exc)})"
    else:
        backend_detail = {
            "keyring": "OS credential store",
            "file": "permission-restricted local file (not encrypted)",
        }.get(backend, backend)

    try:
        current = session_module.load()
    except Exception as exc:
        return [
            Check("Session", "session.backend", "warn", backend_detail),
            Check(
                "Session",
                "session.present",
                "fail",
                f"stored session is unreadable ({_exception_class(exc)})",
                "run: a2l auth",
            ),
            *_unavailable_api_checks(),
        ]

    if current is None:
        return [
            Check("Session", "session.backend", "ok", backend_detail),
            Check("Session", "session.present", "warn", "no stored session", "run: a2l auth"),
            *_unavailable_api_checks(),
        ]

    hours = current.age().total_seconds() / 3600
    stale = hours > 24
    checks = [
        Check("Session", "session.backend", "ok", backend_detail),
        Check(
            "Session",
            "session.age",
            "warn" if stale else "ok",
            f"harvested {hours:.1f} hours ago",
            "run: a2l auth" if stale else None,
        ),
    ]
    checks.extend(_session_api_checks(client))
    return checks


def _unavailable_api_checks() -> list[Check]:
    return [
        Check(
            "Session",
            "session.api_versions",
            "warn",
            "API versions not checked; no usable session",
            "run: a2l auth",
        ),
        Check(
            "Session",
            "session.whoami",
            "warn",
            "whoami not checked; no usable session",
            "run: a2l auth",
        ),
    ]


def _session_api_checks(client: DoctorClient | None) -> list[Check]:
    if client is None:
        return _unavailable_api_checks()

    try:
        versions = client.get_json("/d2l/api/versions/")
        lp_version = _latest_product_version(versions, "lp")
    except Exception as exc:
        return [
            Check(
                "Session",
                "session.api_versions",
                "fail",
                f"API versions failed ({_api_failure_class(exc)})",
                "run: a2l auth",
            ),
            Check(
                "Session",
                "session.whoami",
                "fail",
                "whoami not checked because API versions failed",
                "run: a2l auth",
            ),
        ]

    try:
        payload = client.get_json(f"/d2l/api/lp/{lp_version}/users/whoami")
        if not isinstance(payload, dict) or not isinstance(payload.get("Identifier"), str):
            raise A2LError("whoami response was invalid")
    except Exception as exc:
        whoami = Check(
            "Session",
            "session.whoami",
            "fail",
            f"whoami failed ({_api_failure_class(exc)})",
            "run: a2l auth",
        )
    else:
        whoami = Check("Session", "session.whoami", "ok", "whoami reachable (2xx)")
    return [
        Check("Session", "session.api_versions", "ok", "API versions reachable (2xx)"),
        whoami,
    ]


def _latest_product_version(payload: object, product_code: str) -> str:
    if not isinstance(payload, list):
        raise A2LError("API versions response was invalid")
    for item in payload:
        if not isinstance(item, dict):
            continue
        version = item.get("LatestVersion")
        if item.get("ProductCode") == product_code and isinstance(version, str) and version:
            return version
    raise A2LError("API versions response omitted the required product")


def _optional_tools() -> list[Check]:
    tesseract = shutil.which("tesseract")
    browser = _cdp_browser()
    return [
        Check(
            "Optional tools",
            "tools.tesseract",
            "ok" if tesseract else "warn",
            "tesseract found" if tesseract else "tesseract not installed",
            None if tesseract else "OCR is skipped for image-only PDFs without it",
        ),
        Check(
            "Optional tools",
            "tools.browser",
            "ok" if browser else "warn",
            f"{browser} found" if browser else "no Chrome/Edge/Chromium found",
            None if browser else "browser sign-in needs one; a2l auth --paste works without it",
        ),
    ]


def _skills() -> list[Check]:
    # Skills arrive in Task 15. Reporting "not installed" is truthful now and becomes a real
    # count without changing the check identifier, so a support report stays comparable.
    return [
        Check(
            "Skills",
            "skills.installed",
            "warn",
            "skill diagnostics are unavailable until the skills command is installed",
        )
    ]


def _vault(vault: Vault | None) -> list[Check]:
    if vault is None or not paths.long_path(vault.root).is_dir():
        return [Check("Vault", "vault.present", "warn", "no vault yet", "run: a2l sync")]

    courses = 0
    topics = 0
    citable = 0
    gaps = 0
    empty_twins = 0
    unreadable_maps = 0
    term_stats: dict[str, list[int]] = {}
    try:
        map_paths = sorted(
            path for path in paths.walk(vault.root) if path.name == "content_map.json"
        )
    except (OSError, RuntimeError) as exc:
        return [
            Check("Vault", "vault.present", "fail", f"vault scan failed ({_exception_class(exc)})")
        ]

    for map_path in map_paths:
        try:
            rows = read_content_map(map_path.parent.parent)["topics"]
        except (A2LError, OSError, UnicodeError):
            unreadable_maps += 1
            continue
        if not isinstance(rows, list):
            unreadable_maps += 1
            continue
        courses += 1
        term = map_path.parent.parent.parent.name
        stats = term_stats.setdefault(term, [0, 0, 0, 0, 0])
        stats[0] += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            topics += 1
            stats[2] += 1
            availability = str(row.get("availability", ""))
            if availability == "markdown_ready":
                citable += 1
                stats[1] += 1
                path = row.get("path")
                if isinstance(path, str) and _is_empty_vault_file(vault, path):
                    empty_twins += 1
                    stats[4] += 1
            elif availability in {"unsupported_format", "integrity_gap"}:
                gaps += 1
                stats[3] += 1

    if courses == 0:
        if unreadable_maps:
            present_detail = (
                f"vault has no readable courses; {unreadable_maps} unreadable content map(s)"
            )
            terms_detail = (
                f"no readable term/course coverage; {unreadable_maps} unreadable content map(s)"
            )
        else:
            present_detail = "vault has no courses yet"
            terms_detail = "no term/course coverage yet"
        return [
            Check("Vault", "vault.present", "warn", present_detail, "run: a2l sync"),
            Check("Vault", "vault.terms", "warn", terms_detail, "run: a2l sync"),
            Check("Vault", "vault.empty_twins", "ok", "0 empty markdown twin(s)"),
            _last_sync_check(vault),
        ]

    term_detail = "; ".join(
        f"{term}: {course_count} course(s), {resolved}/{total} topic(s) resolved, "
        f"{term_gaps} conversion gap(s), {term_empty} empty twin(s)"
        for term, (course_count, resolved, total, term_gaps, term_empty) in sorted(
            term_stats.items()
        )
    )
    checks = [
        Check(
            "Vault",
            "vault.courses",
            "warn" if unreadable_maps else "ok",
            f"{courses} course(s), {topics} topic(s)"
            + (f", {unreadable_maps} unreadable content map(s)" if unreadable_maps else ""),
        ),
        Check(
            "Vault",
            "vault.terms",
            "ok" if citable == topics else "warn",
            term_detail,
            None if citable == topics else "run: a2l sync",
        ),
        Check(
            "Vault",
            "vault.citable",
            "ok" if topics and citable == topics else "warn",
            f"{citable} of {topics} topic(s) citable",
            None if citable == topics else "run: a2l sync",
        ),
        Check(
            "Vault",
            "vault.gaps",
            "ok" if gaps == 0 else "warn",
            f"{gaps} conversion gap(s)",
            None if gaps == 0 else "see .a2l/AUDIT.md",
        ),
    ]
    checks.append(
        Check(
            "Vault",
            "vault.empty_twins",
            "warn" if empty_twins else "ok",
            f"{empty_twins} empty markdown twin(s)",
            None if empty_twins == 0 else "run: a2l sync",
        )
    )
    checks.append(_last_sync_check(vault))
    return checks


def _is_empty_vault_file(vault: Vault, value: str) -> bool:
    try:
        parts = PurePosixPath(value).parts
        if (
            not parts
            or "\\" in value
            or (len(value) >= 3 and value[1] == ":" and value[2] in "/\\")
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            return False
        candidate = (vault.root / Path(*parts)).resolve()
        candidate.relative_to(vault.root)
        return (
            paths.long_path(candidate).is_file() and paths.long_path(candidate).stat().st_size == 0
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _last_sync_check(vault: Vault) -> Check:
    snapshot_dir = vault.state() / "snapshots"
    try:
        candidates = sorted(
            path for path in paths.walk(snapshot_dir) if path.suffix.casefold() == ".json"
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return Check(
            "Vault",
            "vault.last_sync",
            "warn",
            f"last sync unavailable ({_exception_class(exc)})",
            "run: a2l sync",
        )
    timestamps: list[datetime] = []
    unreadable = 0
    for candidate in candidates:
        try:
            with open(
                os.fspath(paths.long_path(candidate)), encoding="utf-8", newline=""
            ) as handle:
                raw = json.load(handle)
            value = raw.get("created_at") if isinstance(raw, dict) else None
            if isinstance(value, str):
                timestamps.append(_parse_timestamp(value))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            unreadable += 1
            continue
    if not timestamps:
        detail = "no completed sync recorded"
        if unreadable:
            detail += f"; {unreadable} unreadable snapshot(s)"
        return Check("Vault", "vault.last_sync", "warn", detail, "run: a2l sync")
    latest = max(timestamps).astimezone(UTC).isoformat().replace("+00:00", "Z")
    detail = f"last sync {latest}"
    if unreadable:
        detail += f"; {unreadable} unreadable snapshot(s)"
    return Check("Vault", "vault.last_sync", "warn" if unreadable else "ok", detail)


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed


# ----------------------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------------------
def render(checks: Sequence[Check]) -> str:
    """Render a grouped checklist for the user's own terminal, with one next command."""
    lines: list[str] = []
    for group in _ordered_groups(checks):
        lines.append(f"{group}")
        for check in [item for item in checks if item.group == group]:
            glyph = console.GLYPH[_STATUS_GLYPH[check.status]]
            lines.append(f"  {glyph} {check.detail}")
        lines.append("")

    failures = [item for item in checks if item.status == "fail"]
    warnings = [item for item in checks if item.status == "warn"]
    if failures:
        summary = f"{len(failures)} failure(s), {len(warnings)} warning(s)"
    elif warnings:
        summary = f"{len(warnings)} warning(s)"
    else:
        summary = "all clear"
    lines.append(summary)

    action = next_command(checks)
    if action is not None:
        # Fixes are stored as "run: a2l auth" so they read correctly inside a check's own
        # line; the summary already says "Next", so the prefix would stutter here.
        lines.append(f"Next: {action.removeprefix('run: ')}")
    return "\n".join(lines) + "\n"


def next_command(checks: Sequence[Check]) -> str | None:
    """Return the single most urgent suggested command, or ``None`` when all is well.

    Exactly one. A diagnostic that emits a list of six things to do is one the user closes
    without doing any of them, so failures outrank warnings and the first wins.
    """
    for status in ("fail", "warn"):
        for check in checks:
            if check.status == status and check.fix:
                return check.fix
    # Keep the output contract literal even on a healthy installation: there is still one
    # useful, reversible next action for a student who ran doctor during onboarding.
    return "run: a2l sync"


def exit_code(checks: Sequence[Check]) -> int:
    """0 all clear, 1 warnings only, 2 at least one failure."""
    if any(check.status == "fail" for check in checks):
        return 2
    return 1 if any(check.status == "warn" for check in checks) else 0


# ----------------------------------------------------------------------------------------
# Public support report
# ----------------------------------------------------------------------------------------
def report(checks: Sequence[Check]) -> str:
    """Render a redacted markdown block that is safe to paste into a public issue.

    Only these fields are emitted, each rendered individually rather than copied through:
    package version, Python version, OS and architecture, install method, and — per check —
    its stable identifier, its status, and any ``public`` note the check opted into.
    ``detail`` and ``fix`` are excluded outright because they legitimately contain vault
    paths and course names, and ``public`` is re-redacted here rather than trusted.
    """
    lines = [
        "### Agent2Learn diagnostics",
        "",
        f"- version: `{_safe_token(__version__)}`",
        f"- python: `{_safe_token(platform.python_version())}`",
        f"- platform: `{_safe_token(platform.system())} {_safe_token(platform.machine())}`",
        f"- install: `{_safe_token(_install_method())}`",
        "",
        "| check | status | note |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        note = _safe_public_note(check)
        lines.append(
            f"| `{_public_check_name(check.name)}` | {_public_status(check.status)} | {note} |"
        )

    failures = [check.name for check in checks if check.status == "fail"]
    if failures:
        lines.extend(
            ["", "Failing checks: " + ", ".join(f"`{_public_check_name(n)}`" for n in failures)]
        )
    lines.extend(
        [
            "",
            "_Generated by `a2l doctor --report`. Names, student IDs, course codes, org-unit "
            "IDs, absolute paths, cookies, tokens, and grades are excluded by construction._",
        ]
    )
    return "\n".join(lines) + "\n"


def issue_url(checks: Sequence[Check]) -> str:
    """Build a pre-filled issue URL. The user still reviews and submits it themselves."""
    body = report(checks)
    if len(body) > _MAX_REPORT_BODY:
        body = body[:_MAX_REPORT_BODY].rsplit("\n", 1)[0] + "\n_(truncated)_\n"
    return f"{ISSUE_URL}?labels=bug&body={quote(body, safe='')}"


def open_notice(checks: Sequence[Check]) -> str:
    """Show the body and explain that opening the prefilled page sends it to GitHub."""
    return (
        f"This opens {ISSUE_URL} in your browser with the block below pre-filled.\n"
        "Opening this page sends the displayed redacted body to GitHub; review it there before "
        "submitting.\n\n"
        f"{report(checks)}"
    )


# ----------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------
def _safe_token(value: object) -> str:
    """Reduce any value to a short, inert token.

    Applied even to values that look obviously safe. ``platform.machine()`` and a version
    string are attacker-influenced in principle and formatting-hostile in practice, and a
    single uniform rule is easier to keep correct than a set of judgement calls.
    """
    text = "".join(char for char in str(value) if char.isalnum() or char in "._- +")
    return text.strip()[:64] or "unknown"


def _public_check_name(value: object) -> str:
    if isinstance(value, str) and value in _PUBLIC_CHECK_NAMES:
        return value
    return "unknown-check"


def _public_status(value: object) -> str:
    if isinstance(value, str) and value in _PUBLIC_STATUSES:
        return value
    return "unknown"


def _safe_public_note(check: Check) -> str:
    """Allow only fixed notes whose redaction does not depend on caller-supplied text.

    ``Check.public`` is convenient inside the implementation, but it is not a security type:
    tests, plugins, or a future check can construct it with arbitrary text.  A strict note
    allowlist makes the report safe even when a caller violates the convention in the docstring.
    """
    if check.public is None:
        return ""
    return _SAFE_PUBLIC_NOTES.get(check.name, "")


def _install_method() -> str:
    executable = str(Path(sys.executable)).casefold()
    if "uv" in executable or "uv" in str(Path(sys.prefix)).casefold():
        return "uv tool"
    if hasattr(sys, "real_prefix") or sys.prefix != sys.base_prefix:
        return "virtualenv"
    return "system"


def _can_encode(encoding: str) -> bool:
    try:
        "✓".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _cdp_browser() -> str | None:
    try:
        return cdp.locate_browser().name
    except Exception:
        return None


def _inside_git_worktree(root: Path) -> bool:
    return _git_metadata(root) is not None


def _tracked_files(root: Path) -> list[str] | None:
    """List Git-tracked paths without shelling out to `git`.

    Reading the index directly keeps `doctor` from depending on a `git` binary being on
    PATH, and avoids spawning a subprocess inside a diagnostic. Only the filename table is
    needed, so the index is parsed only far enough to recover it.
    """
    metadata = _git_metadata(root)
    if metadata is None:
        return None
    repo, git_directory = metadata
    index = git_directory / "index"
    try:
        with open(os.fspath(paths.long_path(index)), "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    return _parse_git_index(raw, root, repo)


def _git_metadata(root: Path) -> tuple[Path, Path] | None:
    """Return worktree root and git dir, including linked-worktree ``.git`` files."""
    for directory in [root, *root.parents]:
        marker = directory / ".git"
        try:
            if paths.long_path(marker).is_dir():
                return directory, marker
            if not paths.long_path(marker).is_file():
                continue
            with open(os.fspath(paths.long_path(marker)), encoding="utf-8", newline="") as handle:
                line = handle.readline().strip()
            prefix = "gitdir:"
            if not line.casefold().startswith(prefix):
                return None
            git_directory = Path(line[len(prefix) :].strip())
            if not git_directory.is_absolute():
                git_directory = directory / git_directory
            return directory, git_directory.resolve()
        except (OSError, UnicodeError, RuntimeError):
            raise
    return None


def _parse_git_index(raw: bytes, root: Path, repo: Path) -> list[str] | None:
    if not raw.startswith(b"DIRC") or len(raw) < 12:
        return None
    version = int.from_bytes(raw[4:8], "big")
    if version not in {2, 3}:
        return None
    count = int.from_bytes(raw[8:12], "big")
    entries: list[str] = []
    offset = 12
    prefix = ""
    try:
        relative = root.resolve().relative_to(repo.resolve()).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
    except ValueError:
        prefix = ""

    try:
        for _ in range(count):
            if offset + 62 > len(raw):
                return None
            flags = int.from_bytes(raw[offset + 60 : offset + 62], "big")
            name_start = offset + 62 + (2 if flags & 0x4000 else 0)
            end = raw.index(b"\x00", name_start)
            name = raw[name_start:end].decode("utf-8", "replace")
            if not prefix or name.startswith(prefix):
                entries.append(name[len(prefix) :] if prefix else name)
            offset = (end + 8) & ~7
    except (ValueError, UnicodeDecodeError):
        return None
    return entries


def _git_entry_parts(entry: str) -> tuple[str, ...]:
    normalized = entry.replace("\\", "/").lstrip("./")
    return tuple(part.casefold() for part in PurePosixPath(normalized).parts)


def _is_private_git_entry(parts: tuple[str, ...]) -> bool:
    if "session" in "".join(parts):
        return True
    if "discussions" in parts or "discussions.json" in parts:
        return True
    if "my_grades.json" in parts:
        return True
    for index, part in enumerate(parts[:-1]):
        if part == ".a2l" and parts[index + 1] in {"private", "submissions"}:
            return True
    return False


def _is_course_source_entry(parts: tuple[str, ...]) -> bool:
    return bool(set(parts) & _COURSE_SOURCE_DIRECTORIES)


def _exception_class(exc: BaseException) -> str:
    return _safe_token(type(exc).__name__)


def _api_failure_class(exc: BaseException) -> str:
    if isinstance(exc, SessionExpired):
        return "authentication failure"
    if isinstance(exc, requests.RequestException):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 100 <= status_code <= 599:
            return f"HTTP {status_code // 100}xx"
        return "network failure"
    return _exception_class(exc)


def _ordered_groups(checks: Iterable[Check]) -> list[str]:
    present = {check.group for check in checks}
    ordered = [group for group in _GROUP_ORDER if group in present]
    return ordered + sorted(present - set(ordered))


__all__ = [
    "Check",
    "ISSUE_URL",
    "exit_code",
    "issue_url",
    "next_command",
    "open_notice",
    "render",
    "report",
    "run_checks",
]
