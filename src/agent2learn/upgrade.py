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

# Typer's completion helper is intentionally imported from its public completion module. The
# completion tests render every supported shell, so a Typer change that removes it fails loudly.
from typer.completion import get_completion_script

from agent2learn import __version__
from agent2learn.errors import A2LError

PYPI_METADATA_URL = "https://pypi.org/pypi/agent2learn/json"
REQUEST_TIMEOUT = 15.0
PACKAGE_NAME = "agent2learn"

# A deliberately narrow PEP 440 subset: release segments, optional pre/post/dev suffixes. Local
# versions and arbitrary text are refused rather than sanitised.
_VERSION = re.compile(
    r"^(?:(?P<epoch>[0-9]+)!)?"
    r"(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:(?P<pre_kind>a|b|rc)(?P<pre_number>[0-9]+))?"
    r"(?:\.post(?P<post_number>[0-9]+))?"
    r"(?:\.dev(?P<dev_number>[0-9]+))?$"
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
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise A2LError("the package index reported an unreadable version")
    return value


def resolve_target(version: str) -> str:
    """Validate a network-sourced version and return one exact pinned requirement."""

    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
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


def verify_installation(version: str) -> None:
    """Verify the command and public command surface after a tool replacement.

    ``uv tool install`` can succeed while an old executable remains earlier on ``PATH`` or while
    a broken entry point is selected.  Running the installed command as a child process catches
    both cases without importing the current development checkout.  The help probe is a small
    schema check for the v0.1 command surface; it prevents reporting success for a package whose
    entry point exists but no longer exposes the commands the installer promises.
    """

    resolve_target(version)
    try:
        version_result = subprocess.run(
            ["a2l", "--version"], check=False, capture_output=True, text=True
        )
    except FileNotFoundError:
        raise A2LError("upgrade installed no runnable a2l command; run a2l --version") from None
    except OSError:
        raise A2LError("could not verify the installed a2l command") from None
    version_output = f"{version_result.stdout}\n{version_result.stderr}"
    version_pattern = rf"(?<![0-9A-Za-z]){re.escape(version)}(?![0-9A-Za-z])"
    if version_result.returncode != 0 or re.search(version_pattern, version_output) is None:
        raise A2LError(
            f"installed a2l did not report version {version}; run a2l --version to inspect it"
        )

    try:
        help_result = subprocess.run(["a2l", "--help"], check=False, capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        raise A2LError("could not verify the installed a2l command surface") from None
    help_output = f"{help_result.stdout}\n{help_result.stderr}".casefold()
    if help_result.returncode != 0 or not all(
        marker in help_output for marker in ("courses", "sync", "skills")
    ):
        raise A2LError("installed a2l command surface is incompatible; run a2l --help")


def current_version() -> str:
    """Return the running version."""

    return __version__


def _is_newer(candidate: str, installed: str) -> bool:
    return _sort_key(candidate) > _sort_key(installed)


def _sort_key(version: str) -> tuple[object, ...]:
    """Return a PEP 440 ordering key for the accepted version subset.

    The sentinel ranks mirror the relevant PEP 440 rules without making ``packaging`` a runtime
    dependency: development-only releases precede alpha/beta/rc releases, final releases follow
    all pre-releases, post releases follow the final release, and a post-development release is
    below the corresponding post release.  Trailing release zeros are insignificant (``1.0`` and
    ``1.0.0`` therefore compare equal).
    """

    match = _VERSION.fullmatch(version)
    if match is None:
        raise A2LError("refusing to compare an unrecognised version string")
    groups = match.groupdict()
    release_parts = [int(part) for part in groups["release"].split(".")]
    while len(release_parts) > 1 and release_parts[-1] == 0:
        release_parts.pop()
    release = tuple(release_parts)
    pre_kind = groups["pre_kind"]
    if pre_kind is None and groups["post_number"] is None and groups["dev_number"] is not None:
        # A dev-only release is earlier than any named pre-release.  A post-development release
        # (``1.0.post1.dev1``) is different: PEP 440 places it after the corresponding final.
        pre = (-1, 0, 0)
    elif pre_kind is None:
        # Final releases sort after alpha, beta, and release candidates.
        pre = (1, 0, 0)
    else:
        pre = (0, {"a": 0, "b": 1, "rc": 2}[pre_kind], int(groups["pre_number"]))
    post = -1 if groups["post_number"] is None else int(groups["post_number"])
    dev = (1, 0) if groups["dev_number"] is None else (0, int(groups["dev_number"]))
    return (int(groups["epoch"] or 0), release, pre, post, dev)


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
    "verify_installation",
]
