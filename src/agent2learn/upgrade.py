"""Check for and install a newer Agent2Learn, only when the user asks.

Agent2Learn makes no passive network requests. There is no background version check, no
telemetry, and therefore no opt-out flag or environment variable to disable one — a switch that
turns something off implies it was on. ``a2l upgrade`` is the single command that talks to PyPI,
it names the URL it will read in its own help, and ``--check`` reports without changing anything.

Two things here are load-bearing:

**The version is untrusted input.** It arrives over the network and would otherwise be handed to a
package installer, so it is validated against a strict PEP 440 subset before it becomes an
argument, and every subprocess call passes an argument list — never a shell string. A version like
``0.2.0; rm -rf /`` is refused, not escaped.

**A failure is never a guess.** An unreachable index, a malformed answer, or a missing version
field is reported as "could not determine", not silently treated as "you are up to date". The
underlying exception text is deliberately not echoed, because it can carry local network detail.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import Request, urlopen

# Typer generates completion scripts here but does not re-export the helper, so mypy cannot see
# it. The narrow ignore is backed by a test that renders a script for every supported shell, which
# fails loudly if a Typer upgrade moves or removes this function.
from typer.completion import get_completion_script  # type: ignore[attr-defined]

from agent2learn import __version__
from agent2learn.errors import A2LError

PYPI_METADATA_URL = "https://pypi.org/pypi/agent2learn/json"
REQUEST_TIMEOUT = 15.0
PACKAGE_NAME = "agent2learn"

# A deliberately narrow PEP 440 subset: release segments, optional pre/post/dev suffixes. Local
# versions and arbitrary text are refused rather than sanitised.
_VERSION = re.compile(
    r"^(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*"
    r"(?:(?:a|b|rc)[0-9]+)?"
    r"(?:\.post[0-9]+)?"
    r"(?:\.dev[0-9]+)?$"
)

MetadataFetcher = Callable[[str], object]


@dataclass(frozen=True)
class UpgradePlan:
    """What an upgrade would do, described before anything is installed."""

    installed: str
    latest: str
    needed: bool

    @property
    def requirement(self) -> str:
        return f"{PACKAGE_NAME}=={self.latest}"


def latest_version(*, fetch: MetadataFetcher | None = None) -> str:
    """Return the newest published version, or raise rather than assume."""

    reader = fetch or _read_metadata
    try:
        payload = reader(PYPI_METADATA_URL)
    except A2LError:
        raise
    except Exception:
        # The exception text can name local hosts, proxies, and paths; the user needs the
        # actionable part only.
        raise A2LError(
            f"could not reach {PYPI_METADATA_URL} to check for a newer version"
        ) from None
    if not isinstance(payload, dict):
        raise A2LError("the package index returned an unexpected answer")
    info = payload.get("info")
    if not isinstance(info, dict):
        raise A2LError("the package index answer had no version information")
    value = info.get("version")
    if not isinstance(value, str) or not _VERSION.match(value):
        raise A2LError("the package index reported an unreadable version")
    return value


def resolve_target(version: str) -> str:
    """Validate a network-sourced version and return one exact pinned requirement."""

    if not isinstance(version, str) or not _VERSION.match(version):
        raise A2LError("refusing to install an unrecognised version string")
    return f"{PACKAGE_NAME}=={version}"


def plan_upgrade(*, installed: str, latest: str) -> UpgradePlan:
    """Describe the upgrade without performing it."""

    resolve_target(latest)
    return UpgradePlan(installed=installed, latest=latest, needed=_is_newer(latest, installed))


def render_plan(plan: UpgradePlan) -> str:
    """Render the plan, always naming both versions."""

    lines = [
        f"installed: {plan.installed}",
        f"latest:    {plan.latest}  (from {PYPI_METADATA_URL})",
        "",
    ]
    if not plan.needed:
        lines.append("Already up to date. Nothing to do.")
    else:
        lines.extend(
            [
                f"An upgrade is available: {plan.installed} -> {plan.latest}",
                f"This would run: uv tool install --force {plan.requirement}",
            ]
        )
    return "\n".join(lines) + "\n"


def apply_upgrade(plan: UpgradePlan) -> None:
    """Install the exact pinned target through uv, using an argument list only."""

    if not plan.needed:
        return
    requirement = resolve_target(plan.latest)
    command = ["uv", "tool", "install", "--force", requirement]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        raise A2LError(
            "uv was not found; reinstall with the Agent2Learn installer or run: "
            f"uv tool install --force {requirement}"
        ) from None
    except OSError:
        raise A2LError("the upgrade could not be started") from None
    if completed.returncode != 0:
        raise A2LError(
            f"upgrade to {plan.latest} failed; run this yourself to see why: "
            f"uv tool install --force {requirement}"
        )


def current_version() -> str:
    """Return the running version."""

    return __version__


def _is_newer(candidate: str, installed: str) -> bool:
    return _sort_key(candidate) > _sort_key(installed)


def _sort_key(version: str) -> tuple[object, ...]:
    """Order versions well enough to answer "is this newer", without a packaging dependency.

    Pre-release suffixes sort below the matching final release, which is the only ordering
    subtlety that affects the answer in practice.
    """

    head = version.split("!")[-1]
    epoch = int(version.split("!")[0]) if "!" in version else 0
    core, _, suffix = head.partition("a") if "a" in head else (head, "", "")
    for marker in ("rc", "b", ".post", ".dev"):
        if marker in head and not suffix:
            core, _, suffix = head.partition(marker)
    release = tuple(int(part) for part in re.findall(r"[0-9]+", core))
    stage = 0 if suffix else 1
    suffix_numbers = tuple(int(part) for part in re.findall(r"[0-9]+", suffix))
    return (epoch, release, stage, suffix_numbers)


def _read_metadata(url: str) -> object:
    request = Request(  # noqa: S310 - the URL is a module constant, never user input
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"agent2learn/{__version__} (+https://github.com/ManagementMO/agent2learn)",
        },
        method="GET",
    )
    if not url.startswith("https://pypi.org/"):
        raise A2LError("refusing to read package metadata from an unexpected host")
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 - constant https URL
        if response.status != 200:
            raise A2LError("the package index did not answer with metadata")
        raw = response.read(2 * 1024 * 1024)
    return json.loads(raw.decode("utf-8"))


def completion_shells() -> tuple[str, ...]:
    """Return the shells ``a2l completions`` can emit for."""

    return ("bash", "zsh", "fish", "powershell", "pwsh")


def completion_script(shell: str, *, prog_name: str = "a2l") -> str:
    """Return the completion script for one shell without installing anything.

    This goes through Typer's own generator rather than Click's registry: Typer vendors its Click
    and registers the PowerShell completer only there, and Windows is a first-class target.
    """

    if shell not in completion_shells():
        raise A2LError(
            f"unsupported shell: {shell}; choose one of {', '.join(completion_shells())}"
        )
    try:
        return get_completion_script(
            prog_name=prog_name,
            complete_var="_A2L_COMPLETE",
            shell=shell,
        )
    except Exception:
        raise A2LError(f"no completion support is available for {shell}") from None


__all__ = [
    "PACKAGE_NAME",
    "PYPI_METADATA_URL",
    "REQUEST_TIMEOUT",
    "UpgradePlan",
    "apply_upgrade",
    "completion_script",
    "completion_shells",
    "current_version",
    "latest_version",
    "plan_upgrade",
    "render_plan",
    "resolve_target",
]
