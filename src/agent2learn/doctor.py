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

import os
import platform
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from agent2learn import __version__, console
from agent2learn import config as config_module
from agent2learn import session as session_module
from agent2learn.errors import A2LError
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


@dataclass(frozen=True)
class Check:
    """One diagnostic result.

    ``detail`` and ``fix`` are written for the user's own terminal and legitimately contain
    vault paths and course names, so ``report`` never emits them.

    ``public`` is the opt-in escape hatch: a check that has something genuinely useful and
    already redacted to contribute to a support report puts it here, and owns the claim
    that it is safe. A check that says nothing contributes only its name and status, so a
    check added later cannot leak by default.
    """

    group: str
    name: str
    status: Status
    detail: str
    fix: str | None = None
    public: str | None = None


def run_checks(
    cfg: config_module.Config, vault: Vault | None, *, client: object | None = None
) -> list[Check]:
    """Collect every diagnostic. Never raises: a failed check is itself a result."""
    checks: list[Check] = []
    checks.extend(_environment())
    checks.extend(_filesystem(cfg, vault))
    checks.extend(_session())
    checks.extend(_optional_tools())
    checks.extend(_skills())
    checks.extend(_vault(vault))
    return checks


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
    exists = root.is_dir()
    writable = exists and os.access(root, os.W_OK)
    checks.append(
        Check(
            "Filesystem",
            "fs.vault",
            "ok" if writable else ("fail" if exists else "warn"),
            f"{root}" if exists else f"{root} does not exist yet",
            None if writable else ("check folder permissions" if exists else "run: a2l init"),
            public=f"vault root `{_redact_path(str(root))}`",
        )
    )

    if exists:
        free_gib = shutil.disk_usage(root).free / (1024**3)
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
    for path in root.rglob("*"):
        longest_relative = max(longest_relative, len(path.relative_to(root).as_posix()))
        longest_absolute = max(longest_absolute, len(str(path)))

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
    if not _inside_git_worktree(vault.root):
        return Check("Filesystem", "fs.git", "ok", "vault is not inside a Git repository")

    tracked = _tracked_files(vault.root)
    if tracked is None:
        return Check("Filesystem", "fs.git", "warn", "inside Git, but the file list is unreadable")

    private = sorted(
        {
            entry
            for entry in tracked
            if entry.startswith(".a2l/private")
            or "session" in entry.casefold()
            or entry.endswith(("my_grades.json", "discussions.json"))
            or "/submissions/" in entry
        }
    )
    if private:
        return Check(
            "Filesystem",
            "fs.git",
            "fail",
            f"{len(private)} private file(s) are tracked by Git",
            "untrack them and rewrite history before pushing anywhere",
        )

    sources = [entry for entry in tracked if "/content/" in entry]
    if sources:
        return Check(
            "Filesystem",
            "fs.git",
            "warn",
            f"{len(sources)} course source file(s) are tracked by Git",
            "course material is not yours to redistribute; keep the vault out of a pushed repo",
        )
    return Check("Filesystem", "fs.git", "ok", "no private or course files are tracked")


def _session() -> list[Check]:
    backend = session_module.backend_name()
    readable = {
        "keyring": "OS credential store",
        "file": "permission-restricted local file (not encrypted)",
    }.get(backend, backend)

    try:
        current = session_module.load()
    except A2LError:
        current = None

    if current is None:
        return [
            Check("Session", "session.backend", "ok", readable),
            Check("Session", "session.present", "warn", "no stored session", "run: a2l auth"),
        ]

    hours = current.age().total_seconds() / 3600
    stale = hours > 24
    return [
        Check("Session", "session.backend", "ok", readable),
        Check(
            "Session",
            "session.age",
            "warn" if stale else "ok",
            f"harvested {hours:.1f} hours ago",
            "run: a2l auth" if stale else None,
        ),
    ]


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
        Check("Skills", "skills.installed", "warn", "no agent skills installed", "run: a2l skills")
    ]


def _vault(vault: Vault | None) -> list[Check]:
    if vault is None or not vault.root.is_dir():
        return [Check("Vault", "vault.present", "warn", "no vault yet", "run: a2l sync")]

    courses = 0
    topics = 0
    citable = 0
    gaps = 0
    for map_path in sorted(vault.root.rglob("content_map.json")):
        try:
            rows = read_content_map(map_path.parent.parent)["topics"]
        except A2LError:
            continue
        if not isinstance(rows, list):
            continue
        courses += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            topics += 1
            availability = str(row.get("availability", ""))
            if availability == "markdown_ready":
                citable += 1
            elif availability in {"unsupported_format", "integrity_gap"}:
                gaps += 1

    if courses == 0:
        return [
            Check("Vault", "vault.present", "warn", "vault has no courses yet", "run: a2l sync")
        ]

    return [
        Check("Vault", "vault.courses", "ok", f"{courses} course(s), {topics} topic(s)"),
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
    return None


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
        note = _redact_path(check.public) if check.public else ""
        lines.append(f"| `{_safe_token(check.name)}` | {_safe_token(check.status)} | {note} |")

    failures = [check.name for check in checks if check.status == "fail"]
    if failures:
        lines.extend(["", "Failing checks: " + ", ".join(f"`{_safe_token(n)}`" for n in failures)])
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
    """The text shown before anything leaves the device, so consent is informed."""
    return (
        f"This opens {ISSUE_URL} in your browser with the block below pre-filled.\n"
        "It leaves your device only when you press submit there.\n\n"
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


def _redact_path(value: str) -> str:
    home = str(Path.home())
    text = value.replace(home, "~") if home and home in value else value
    if text == value and (text.startswith("/") or ":\\" in text):
        # Not under home, so the shape is all that can safely be reported.
        return f"<path depth {len(Path(text).parts)}>"
    return text.replace("\\", "/")


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
    for candidate in ("google-chrome", "chromium", "chrome", "msedge", "microsoft-edge"):
        if shutil.which(candidate):
            return candidate
    for path in (
        Path("/Applications/Google Chrome.app"),
        Path("/Applications/Microsoft Edge.app"),
        Path("/Applications/Chromium.app"),
    ):
        if path.exists():
            return path.stem
    return None


def _inside_git_worktree(root: Path) -> bool:
    return any((directory / ".git").exists() for directory in [root, *root.parents])


def _tracked_files(root: Path) -> list[str] | None:
    """List Git-tracked paths without shelling out to `git`.

    Reading the index directly keeps `doctor` from depending on a `git` binary being on
    PATH, and avoids spawning a subprocess inside a diagnostic. Only the filename table is
    needed, so the index is parsed only far enough to recover it.
    """
    for directory in [root, *root.parents]:
        index = directory / ".git" / "index"
        if not index.is_file():
            continue
        try:
            raw = index.read_bytes()
        except OSError:
            return None
        return _parse_git_index(raw, root, directory)
    return None


def _parse_git_index(raw: bytes, root: Path, repo: Path) -> list[str] | None:
    if not raw.startswith(b"DIRC") or len(raw) < 12:
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

    for _ in range(count):
        if offset + 62 > len(raw):
            return None
        end = raw.index(b"\x00", offset + 62)
        name = raw[offset + 62 : end].decode("utf-8", "replace")
        if not prefix or name.startswith(prefix):
            entries.append(name[len(prefix) :] if prefix else name)
        offset = end + 1
        offset += (-offset) % 8 or 0
        while offset < len(raw) and raw[offset : offset + 1] == b"\x00":
            offset += 1
    return entries


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
