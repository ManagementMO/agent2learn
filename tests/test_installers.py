"""The one-command installers pin what they install and never widen their own trust.

The behavioural tests run ``install.sh`` against fake ``uv``, ``curl``, and ``a2l`` executables on
a throwaway ``PATH``. Nothing here reaches the network, installs anything, or touches the real
user environment. ``install.ps1`` is contract-tested everywhere and exercised on the Windows CI
runner.
"""

from __future__ import annotations

import os
import re
import selectors
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent2learn import __version__

ROOT = Path(__file__).parent.parent
SH = ROOT / "install.sh"
PS1 = ROOT / "install.ps1"

UV_VERSION = "0.12.5"
HANDOFF = "run in a terminal: a2l init"

# install.sh behaviour needs a POSIX shell and POSIX tools. Windows is covered by install.ps1,
# which the CI installer job smokes directly. The contract tests below are pure text checks and
# deliberately run everywhere, including Windows.
posix_shell_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="install.sh behaviour needs a POSIX shell",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fake_bin(
    tmp_path: Path, *, uv_version: str | None, record: Path, a2l_version: str | None = None
) -> Path:
    """Build a throwaway PATH holding only the stubs the installer may legitimately call."""
    binary = tmp_path / "bin"
    binary.mkdir(parents=True, exist_ok=True)
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    tool_bin = tmp_path / "tool-bin"
    tool_bin.mkdir(parents=True, exist_ok=True)

    def write(name: str, body: str) -> Path:
        destination = binary / name
        destination.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
        destination.chmod(0o755)
        return destination

    if uv_version is not None:
        write(
            "uv",
            f'''set -eu
echo "uv $*" >> "{record}"
case "$1" in
  --version) echo "uv {uv_version} (test stub)" ;;
  tool)
    case "$2" in
      dir) echo "{tool_bin}" ;;
      *) : ;;
    esac
    ;;
  *) : ;;
esac
''',
        )

    # The Astral installer is fetched, never piped straight into a shell, so the stub can write a
    # replacement uv exactly as the real one would.
    write(
        "curl",
        f'''set -eu
echo "curl $*" >> "{record}"
target=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then target="$arg"; fi
  prev="$arg"
done
if [ -n "$target" ]; then
  cat > "$target" <<'INNER'
#!/usr/bin/env bash
set -eu
echo "astral-installer-ran" >> "@RECORD@"
cat > "@BIN@/uv" <<'UVEOF'
#!/usr/bin/env bash
set -eu
echo "uv $*" >> "@RECORD@"
case "$1" in
  --version) echo "uv {UV_VERSION} (installed stub)" ;;
  tool)
    case "$2" in
      dir) echo "@TOOLBIN@" ;;
      *) : ;;
    esac
    ;;
  *) : ;;
esac
UVEOF
chmod 755 "@BIN@/uv"
INNER
  sed -i.bak "s#@RECORD@#{record}#g; s#@TOOLBIN@#{tool_bin}#g; s#@BIN@#{binary}#g" "$target"
  rm -f "$target.bak"
fi
''',
    )

    version_line = a2l_version if a2l_version is not None else __version__
    a2l = tool_bin / "a2l"
    a2l.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'echo "a2l $*" >> "{record}"\n'
        'if [ "${1:-}" = "--version" ]; then\n'
        f'  echo "agent2learn {version_line}"\n'
        "fi\n"
        'if [ "${1:-}" = "init" ]; then\n'
        '  echo "ONBOARDING-STARTED"\n'
        "fi\n",
        encoding="utf-8",
        newline="\n",
    )
    a2l.chmod(0o755)
    return binary


def _run(
    tmp_path: Path, *, uv_version: str | None, a2l_version: str | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    record = tmp_path / "calls.log"
    record.write_text("", encoding="utf-8")
    binary = _fake_bin(tmp_path, uv_version=uv_version, record=record, a2l_version=a2l_version)
    environment = {
        "PATH": f"{binary}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(SH)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    return result, record.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------------------


def test_both_installers_exist_and_fail_fast() -> None:
    assert SH.is_file()
    assert PS1.is_file()
    shell = _read(SH)
    assert shell.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in shell
    assert '$ErrorActionPreference = "Stop"' in _read(PS1)


def test_both_installers_pin_the_same_reviewed_versions() -> None:
    shell, powershell = _read(SH), _read(PS1)

    assert f'UV_VERSION="{UV_VERSION}"' in shell
    assert f'A2L_VERSION="{__version__}"' in shell
    assert f'$UV_VERSION = "{UV_VERSION}"' in powershell
    assert f'$A2L_VERSION = "{__version__}"' in powershell
    # Assert the install *invocation* is pinned, not merely that a pinned string appears
    # somewhere: the preview line also names the version, so a looser check would still pass if
    # the command itself installed an unpinned `agent2learn`.
    assert re.search(r'uv tool install\s+"agent2learn==\$\{A2L_VERSION\}"', shell)
    assert re.search(r'uv tool install\s+"agent2learn==\$A2L_VERSION"', powershell)
    for text in (shell, powershell):
        assert not re.search(r"uv tool install\s+\"?agent2learn\"?\s*(?:\r?\n|$)", text)


def test_both_installers_fetch_only_the_pinned_astral_installer() -> None:
    for text in (_read(SH), _read(PS1)):
        # The scripts interpolate their reviewed constant, so resolve it and check the URL the
        # script would actually fetch rather than the literal source text.
        resolved = text.replace("${UV_VERSION}", UV_VERSION).replace("$UV_VERSION", UV_VERSION)
        urls = re.findall(r"https://[^\s\"'`)]+", resolved)
        astral = [url for url in urls if "astral.sh" in url]
        assert astral, "the official uv installer must be used"
        for url in astral:
            assert f"/uv/{UV_VERSION}/" in url, url


def test_neither_installer_accepts_an_arbitrary_package_source() -> None:
    for text in (_read(SH), _read(PS1)):
        lowered = text.casefold()
        for forbidden in (
            "--index-url",
            "--extra-index-url",
            "--find-links",
            "--default-index",
            "a2l_package_url",
            "agent2learn_url",
        ):
            assert forbidden not in lowered, forbidden


def test_neither_installer_needs_administrator_rights_or_writes_agent_state() -> None:
    for text in (_read(SH), _read(PS1)):
        lowered = text.casefold()
        for forbidden in (
            "sudo ",
            "runas",
            "-verb runas",
            ".claude",
            ".codex",
            ".cursor",
            "chrome-profile",
            "user data",
        ):
            assert forbidden not in lowered, forbidden


def test_neither_installer_hardcodes_the_tool_bin_directory() -> None:
    shell, powershell = _read(SH), _read(PS1)

    assert "uv tool dir --bin" in shell
    assert "uv tool dir --bin" in powershell
    assert "uv tool update-shell" in shell
    assert "uv tool update-shell" in powershell
    assert "~/.local/bin" not in shell
    assert ".local\\bin" not in powershell
    assert "USERPROFILE" not in powershell


def test_both_installers_verify_the_command_and_name_the_handoff() -> None:
    for text in (_read(SH), _read(PS1)):
        assert "a2l --version" in text
        assert HANDOFF in text


def test_the_windows_installer_explains_reopening_an_open_terminal() -> None:
    text = _read(PS1).casefold()

    assert "reopen" in text
    assert "already open" in text


# --------------------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------------------


@posix_shell_only
def test_an_absent_uv_is_installed_from_the_pinned_installer(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, uv_version=None)

    assert result.returncode == 0, result.stderr
    assert "astral-installer-ran" in calls
    assert f"/uv/{UV_VERSION}/install.sh" in calls
    assert HANDOFF in result.stdout


@posix_shell_only
def test_an_older_uv_is_replaced_and_disclosed(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, uv_version="0.11.0")

    assert result.returncode == 0, result.stderr
    assert "astral-installer-ran" in calls
    assert "0.11.0" in result.stdout


@posix_shell_only
@pytest.mark.parametrize("version", ["0.12.5", "0.13.0", "1.0.0"])
def test_an_equal_or_newer_uv_is_reused(tmp_path: Path, version: str) -> None:
    result, calls = _run(tmp_path, uv_version=version)

    assert result.returncode == 0, result.stderr
    assert "astral-installer-ran" not in calls
    assert "curl" not in calls


@posix_shell_only
def test_a_malformed_uv_version_fails_with_one_actionable_message(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, uv_version="banana")

    assert result.returncode != 0
    assert "astral-installer-ran" not in calls
    combined = result.stdout + result.stderr
    assert "banana" in combined
    assert "uv" in combined.casefold()
    # One actionable instruction, not a guess and not a wall of alternatives.
    assert combined.casefold().count("https://astral.sh") <= 1


@posix_shell_only
def test_the_installer_previews_before_it_changes_anything(tmp_path: Path) -> None:
    result, _calls = _run(tmp_path, uv_version=None)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    preview_at = next(index for index, line in enumerate(lines) if line.strip() == "This will:")
    action_at = next(
        index for index, line in enumerate(lines) if line.startswith("installing agent2learn==")
    )
    assert preview_at < action_at
    assert any("does not create a vault" in line for line in lines[preview_at:action_at])


@posix_shell_only
def test_a_non_interactive_run_stops_after_verification(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, uv_version=UV_VERSION)

    assert result.returncode == 0, result.stderr
    assert HANDOFF in result.stdout
    assert "a2l init" not in calls
    assert "ONBOARDING-STARTED" not in result.stdout


@posix_shell_only
def test_a_version_mismatch_after_install_is_an_error(tmp_path: Path) -> None:
    result, _calls = _run(tmp_path, uv_version=UV_VERSION, a2l_version="9.9.9")

    assert result.returncode != 0
    assert "9.9.9" in result.stdout + result.stderr


@posix_shell_only
def test_running_the_installer_twice_is_idempotent(tmp_path: Path) -> None:
    first, _calls = _run(tmp_path, uv_version=UV_VERSION)
    second, _again = _run(tmp_path, uv_version=UV_VERSION)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr


@posix_shell_only
def test_an_interactive_run_proceeds_into_onboarding(tmp_path: Path) -> None:
    """With a real terminal on both ends the installer hands straight to consentful onboarding."""
    import pty  # Unix only, so it is imported inside the POSIX-gated test.

    record = tmp_path / "calls.log"
    record.write_text("", encoding="utf-8")
    binary = _fake_bin(tmp_path, uv_version=UV_VERSION, record=record)
    (tmp_path / "home").mkdir(exist_ok=True)

    primary, secondary = pty.openpty()
    process = subprocess.Popen(
        ["bash", str(SH)],
        stdin=secondary,
        stdout=secondary,
        stderr=secondary,
        env={"PATH": f"{binary}:/usr/bin:/bin", "HOME": str(tmp_path / "home"), "TERM": "dumb"},
        cwd=tmp_path,
    )
    os.close(secondary)
    transcript = b""
    selector = selectors.DefaultSelector()
    selector.register(primary, selectors.EVENT_READ)
    while True:
        if not selector.select(timeout=20):
            break
        try:
            chunk = os.read(primary, 4096)
        except OSError:
            break
        if not chunk:
            break
        transcript += chunk
    os.close(primary)
    process.wait(timeout=20)

    text = transcript.decode("utf-8", errors="replace")
    assert "ONBOARDING-STARTED" in text
    assert HANDOFF not in text


def test_ci_smokes_both_installers_against_the_candidate_build() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "installer · ${{ matrix.os }}" in workflow
    assert "bash install.sh" in workflow
    assert "./install.ps1" in workflow
    assert "UV_FIND_LINKS" in workflow
    assert "run in a terminal: a2l init" in workflow
    # The smoke must resolve agent2learn from the candidate build, never from a public index.
    assert "uv build" in workflow
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in workflow
