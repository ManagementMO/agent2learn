"""Version queries happen only when asked, and the release pipeline promotes exact artifacts."""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import flatten_help, strip_ansi
from typer.testing import CliRunner

from agent2learn import __version__, config, upgrade
from agent2learn.cli import app
from agent2learn.errors import A2LError
from agent2learn.upgrade import (
    PYPI_METADATA_URL,
    UpgradePlan,
    latest_version,
    plan_upgrade,
    render_plan,
    resolve_target,
)
from agent2learn.vault import Vault

ROOT = Path(__file__).parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SRC = ROOT / "src" / "agent2learn"

# The release job is defined `runs-on: ubuntu-latest`, so its shell steps are executed here only
# on a POSIX shell. Running them under git-bash on a Windows runner would test an environment the
# workflow never sees. The text assertions that pin each guard's decision run everywhere.
posix_release_shell = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="release workflow steps run on ubuntu-latest",
)


class FakeMetadata:
    """A recording stand-in for the single PyPI metadata request."""

    def __init__(self, payload: object, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[str] = []

    def __call__(self, url: str) -> object:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.payload


def _released(version: str) -> dict[str, object]:
    return {"info": {"version": version}}


# --------------------------------------------------------------------------------------
# The version query is explicit, disclosed, and singular
# --------------------------------------------------------------------------------------


def test_latest_version_reads_only_the_declared_pypi_metadata_url() -> None:
    fetch = FakeMetadata(_released("0.2.0"))

    assert latest_version(fetch=fetch) == "0.2.0"
    assert fetch.calls == [PYPI_METADATA_URL]
    assert PYPI_METADATA_URL.startswith("https://pypi.org/pypi/agent2learn/")


@pytest.mark.parametrize(
    "payload",
    [{}, {"info": {}}, {"info": {"version": ""}}, {"info": {"version": "not a version"}}, []],
)
def test_an_unusable_pypi_answer_is_an_error_not_a_guess(payload: object) -> None:
    with pytest.raises(A2LError):
        latest_version(fetch=FakeMetadata(payload))


def test_a_network_failure_is_reported_without_leaking_the_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fetch = FakeMetadata(None, error=OSError("connect to 10.0.0.1 failed"))

    with pytest.raises(A2LError) as raised:
        latest_version(fetch=fetch)

    assert "10.0.0.1" not in str(raised.value)


def test_check_reports_both_versions_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Vault.claim(tmp_path / "vault")
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=root))
    fetch = FakeMetadata(_released("9.9.9"))
    monkeypatch.setattr(upgrade, "latest_version", lambda **_kwargs: "9.9.9")
    installed_before = (SRC / "__init__.py").read_text(encoding="utf-8")

    result = CliRunner().invoke(app, ["upgrade", "--check"])
    output = strip_ansi(result.stdout)

    assert result.exit_code == 0
    assert __version__ in output
    assert "9.9.9" in output
    assert "pypi.org" in output
    assert (SRC / "__init__.py").read_text(encoding="utf-8") == installed_before
    assert fetch.calls == []


def test_plan_is_a_no_op_when_already_current() -> None:
    plan = plan_upgrade(installed=__version__, latest=__version__)

    assert isinstance(plan, UpgradePlan)
    assert plan.needed is False
    assert __version__ in render_plan(plan)


def test_plan_names_the_exact_target_when_an_upgrade_exists() -> None:
    plan = plan_upgrade(installed="0.1.0", latest="0.2.0")

    assert plan.needed is True
    rendered = render_plan(plan)
    assert "0.1.0" in rendered
    assert "0.2.0" in rendered
    assert "agent2learn==0.2.0" in rendered


@pytest.mark.parametrize(
    "value",
    ["0.2.0; rm -rf /", "0.2.0 && echo hi", "$(whoami)", "`id`", "0.2.0\nmalicious", "--upgrade"],
)
def test_a_pypi_version_is_validated_before_it_becomes_a_subprocess_argument(value: str) -> None:
    with pytest.raises(A2LError):
        resolve_target(value)


def test_a_valid_version_resolves_to_one_pinned_requirement() -> None:
    assert resolve_target("1.2.3") == "agent2learn==1.2.3"
    assert resolve_target("1.2.3rc1") == "agent2learn==1.2.3rc1"


def test_upgrade_never_shells_out_through_a_string() -> None:
    """The version comes from the network, so it must never be interpolated into a shell."""
    tree = ast.parse((SRC / "upgrade.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name in {"run", "call", "check_call", "check_output", "Popen"}:
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert not (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                    ), "subprocess must never use shell=True"
        assert name not in {"system", "popen"}, f"{name} must not be used"


# --------------------------------------------------------------------------------------
# No passive traffic
# --------------------------------------------------------------------------------------


def test_only_upgrade_reaches_for_pypi() -> None:
    """`upgrade` must be the single place PyPI appears, apart from its own disclosure in help."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "upgrade.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "pypi.org" not in text:
            continue
        if path.name == "cli.py":
            # The upgrade command's own help must name the URL it will read. Every mention has to
            # sit inside that command, so no other command can be quietly contacting the index.
            body = text.split("def upgrade(", 1)[1].split("@app.command()", 1)[0]
            remainder = text.replace(body, "")
            if "pypi.org" in remainder:
                offenders.append(path.name)
            continue
        offenders.append(path.name)
    assert offenders == []


def test_the_removed_opt_outs_do_not_exist_anywhere() -> None:
    """There is no background check, so there is nothing to disable."""
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "--no-version-check" not in text, path.name
        assert "A2L_NO_UPDATE_CHECK" not in text, path.name


def test_upgrade_help_discloses_the_request_and_completions_are_offered() -> None:
    runner = CliRunner()

    upgrade_help = flatten_help(runner.invoke(app, ["upgrade", "--help"]).output)
    root_help = flatten_help(runner.invoke(app, ["--help"]).output)

    assert "pypi.org" in upgrade_help
    assert " completions " in root_help


# --------------------------------------------------------------------------------------
# Completions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
def test_completions_emit_a_script_for_every_supported_shell(shell: str) -> None:
    result = CliRunner().invoke(app, ["completions", shell])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip()
    assert "a2l" in result.stdout


def test_completions_reject_an_unknown_shell() -> None:
    """An unknown shell is a usage error that lists the real choices, not a generic failure."""
    result = CliRunner().invoke(app, ["completions", "tcsh"])

    message = flatten_help(result.output)
    assert result.exit_code == 2, message
    assert "tcsh" in message
    for shell in ("bash", "zsh", "fish", "powershell"):
        assert shell in message


# --------------------------------------------------------------------------------------
# Release workflow
# --------------------------------------------------------------------------------------


def _release_text() -> str:
    return (WORKFLOWS / "release.yml").read_text(encoding="utf-8")


def _release_job(name: str) -> str:
    """Return one top-level release job so dependency guards test the real workflow shape."""
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        _release_text(),
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"release job is missing: {name}"
    return match.group(0)


def test_the_final_pypi_gate_precedes_public_github_release() -> None:
    """PyPI approval must happen before a public GitHub release is created."""
    pypi = _release_job("pypi")
    github_release = _release_job("github-release")
    pypi_needs = next(line for line in pypi.splitlines() if line.strip().startswith("needs:"))
    github_release_needs = next(
        line for line in github_release.splitlines() if line.strip().startswith("needs:")
    )
    pypi_dependencies = set(re.findall(r"[a-z][a-z0-9-]*", pypi_needs.partition(":")[2]))
    github_release_dependencies = set(
        re.findall(r"[a-z][a-z0-9-]*", github_release_needs.partition(":")[2])
    )

    assert "environment: pypi" in pypi
    assert "github-release" not in pypi_dependencies
    assert "pypi" in github_release_dependencies


def test_testpypi_smoke_verifies_the_published_hashes_before_install() -> None:
    """A retry must not smoke-test a different artifact that merely has the same version."""
    smoke = _release_job("testpypi-smoke")

    assert "actions/download-artifact" in smoke
    assert "SHA256SUMS.txt" in smoke
    assert "test.pypi.org/pypi/agent2learn/" in smoke
    assert "digests" in smoke
    assert "artifact hash mismatch" in smoke


def test_the_release_workflow_triggers_only_on_a_version_tag() -> None:
    text = _release_text()

    assert "on:\n  push:\n    tags:" in text
    assert '"v*"' in text or "'v*'" in text
    for forbidden in ("pull_request:", "schedule:", "workflow_dispatch:"):
        assert forbidden not in text, forbidden


def test_every_release_action_is_pinned_to_a_full_commit_sha() -> None:
    text = _release_text()
    uses = [line.split("uses:", 1)[1].strip() for line in text.splitlines() if "uses:" in line]

    assert uses, "the release workflow must use actions"
    for reference in uses:
        _repo, _, ref = reference.partition("@")
        pinned = ref.split()[0]
        assert len(pinned) == 40, reference
        assert all(character in "0123456789abcdef" for character in pinned), reference


def test_publishing_uses_trusted_publishing_with_job_level_id_token() -> None:
    text = _release_text()

    assert "pypa/gh-action-pypi-publish" in text
    # Job-level permissions are indented six spaces; a top-level grant would be two.
    assert "      id-token: write" in text
    assert "\npermissions:\n  contents: read\n" in text
    assert "id-token" not in text.split("jobs:", 1)[0].split("permissions:", 1)[1].split("\n\n")[0]
    assert "environment:" in text
    for forbidden in ("password:", "PYPI_TOKEN", "PYPI_API_TOKEN", "username:"):
        assert forbidden not in text, forbidden


def test_the_release_builds_once_and_promotes_the_same_hashes() -> None:
    text = _release_text()

    assert text.count("uv build") == 1, "build exactly once, then promote the same artifacts"
    assert "twine check" in text
    assert "upload-artifact" in text
    assert "download-artifact" in text
    assert "attest" in text
    assert "sbom" in text.casefold()
    assert "testpypi" in text.casefold()
    assert "sha256" in text.casefold()
    assert "pip-audit" in text
    assert "cyclonedx1.5" in text
    assert "gh release create" in text
    assert "UV_FIND_LINKS" in text
    assert text.count("testpypi-smoke") >= 2


def _step_script(name: str) -> str:
    """Extract one workflow step's shell script so it can actually be run."""
    text = _release_text()
    marker = f"- name: {name}"
    body = text.split(marker, 1)[1].split("run: |", 1)[1]
    lines: list[str] = []
    for line in body.splitlines()[1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    return "\n".join(lines)


@posix_release_shell
@pytest.mark.parametrize(
    ("tag", "expected_ok"), [(f"v{__version__}", True), ("v9.9.9", False), ("not-a-tag", False)]
)
def test_the_release_actually_refuses_a_tag_that_disagrees_with_the_version(
    tmp_path: Path, tag: str, expected_ok: bool
) -> None:
    """Run the workflow's own guard rather than asserting that its text mentions a variable.

    A text check cannot tell a working comparison from a defeated one.
    """
    script = _step_script("The tag must match the declared version")
    assert "GITHUB_REF_NAME" in script

    outputs = tmp_path / "outputs"
    outputs.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={
            **os.environ,
            "GITHUB_REF_NAME": tag,
            "GITHUB_OUTPUT": str(outputs),
        },
    )

    assert (result.returncode == 0) is expected_ok, result.stderr
    if expected_ok:
        assert f"version={__version__}" in outputs.read_text(encoding="utf-8")


def test_the_release_refuses_to_publish_an_enabled_submission_build_by_default() -> None:
    script = _step_script("Uploads must be disabled unless the release gate authorised them")

    # Pin the decision, not just the name: a rename or a dropped exit would otherwise pass.
    assert "_release.SUBMISSION_AVAILABLE" in script
    assert 'if [ "$enabled" != "False" ]' in script
    assert 'if [ "${A2L_SUBMISSION_RELEASE_SHA:-}" != "$GITHUB_SHA" ]' in script
    assert "A2L_SUBMISSION_RELEASE_AUTHORISED" not in script
    assert "gh api --method DELETE" in script
    assert script.count("exit 1") == 1


@posix_release_shell
def test_the_submission_guard_passes_for_this_disabled_build() -> None:
    script = _step_script("Uploads must be disabled unless the release gate authorised them")

    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, cwd=ROOT, env=dict(os.environ)
    )

    assert result.returncode == 0, result.stderr


def test_the_ci_workflow_still_guards_every_pull_request() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in ci
    assert "tags:" not in ci


@pytest.mark.parametrize(
    ("latest", "installed", "needed"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("1.0.0", "0.9.9", True),
        # 0.10.0 is newer than 0.9.0; a string comparison would get this backwards.
        ("0.10.0", "0.9.0", True),
        # A release supersedes its own candidate, and a candidate never supersedes the release.
        ("0.2.0", "0.2.0rc1", True),
        ("0.2.0rc1", "0.2.0", False),
        ("0.2.0rc1", "0.1.0", True),
        ("1.0.post1", "1.0", True),
        ("1.0b1", "1.0a1", True),
        ("1.0rc1", "1.0b1", True),
        ("1.0.0", "1.0", False),
        ("1.0.post1.dev1", "1.0rc1", True),
        ("1.0.post1.dev1", "1.0", True),
        ("1.0.post1", "1.0.post1.dev1", True),
    ],
)
def test_version_ordering_answers_is_this_newer(latest: str, installed: str, needed: bool) -> None:
    assert plan_upgrade(installed=installed, latest=latest).needed is needed


def test_plain_upgrade_requires_a_controlling_confirmation_before_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upgrade, "latest_version", lambda **_kwargs: "9.9.9")
    calls: list[UpgradePlan] = []
    monkeypatch.setattr(upgrade, "apply_upgrade", calls.append)

    result = CliRunner().invoke(app, ["upgrade"], input="n\n")

    assert result.exit_code != 0
    assert calls == []


def test_post_install_verification_checks_version_and_command_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="a2l 9.9.9\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="sync  courses  skills\n", stderr="")

    monkeypatch.setattr(upgrade.subprocess, "run", run)

    upgrade.verify_installation("9.9.9")

    assert calls == [["a2l", "--version"], ["a2l", "--help"]]


def test_every_mypy_gate_targets_the_interpreter_it_runs_under() -> None:
    """A mypy gate must parse dependencies with the grammar of the Python it actually runs on.

    The lock resolves a different numpy for 3.12+ than for 3.11, and the newer one's stubs use
    PEP 695 ``type`` statements. A job on 3.12 that lets mypy fall back to the project's 3.11
    target therefore fails on ``numpy/__init__.pyi`` before checking a single project file. CI got
    ``--python-version`` for exactly this reason; the release workflow's first real run (tag
    v0.1.0, 2026-09-02) failed because it had not.
    """

    for workflow in ("ci.yml", "release.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "uv run mypy" in line:
                assert "--python-version" in line, (workflow, line.strip())

    build = _release_job("build")
    python = re.search(r'python-version:\s*"([0-9.]+)"', build)
    assert python is not None, "the release build job must pin its Python"
    mypy_lines = [line for line in build.splitlines() if "uv run mypy" in line]
    assert mypy_lines, "the release build job must run mypy"
    for line in mypy_lines:
        assert f"--python-version {python.group(1)}" in line, line.strip()
