"""Public documentation must match the implementation and overclaim nothing.

These are contract tests, not style checks. Every assertion here corresponds to a promise the
project makes to a student reading the README: that the commands exist, that the privacy defaults
are stated accurately, and that no page claims correctness, verification, or total isolation that
the code does not deliver.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import strip_ansi
from typer.testing import CliRunner

from agent2learn import __version__
from agent2learn.cli import app
from agent2learn.schools import School

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

REQUIRED_PAGES = (
    ROOT / "README.md",
    ROOT / "llms.txt",
    ROOT / "DISCLAIMER.md",
    ROOT / "SECURITY.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    DOCS / "install.md",
    DOCS / "FAQ.md",
    DOCS / "PORTING.md",
    DOCS / "PRIVACY.md",
    DOCS / "AUTHENTICATION.md",
    DOCS / "FUTURE.md",
)

# Public pages only. The internal specs and plans describe unbuilt work by design.
PUBLIC_PAGES = REQUIRED_PAGES


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _public_text() -> str:
    return "\n".join(_read(path) for path in PUBLIC_PAGES if path.is_file())


def _cli_commands() -> set[str]:
    output = strip_ansi(CliRunner().invoke(app, ["--help"]).output)
    body = output.split("Commands", 1)[-1]
    return {
        match.group(1)
        for match in re.finditer(r"^\s*│?\s*([a-z][a-z-]*)\s{2,}", body, re.MULTILINE)
    }


# --------------------------------------------------------------------------------------
# Presence
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", REQUIRED_PAGES, ids=lambda p: p.name)
def test_every_required_public_page_exists_and_is_not_a_stub(path: Path) -> None:
    assert path.is_file(), f"missing {path.relative_to(ROOT)}"
    assert len(_read(path).strip()) > 400, f"{path.name} is a stub"


# --------------------------------------------------------------------------------------
# Claims the project must never make
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "nothing leaves your computer",
        "nothing ever leaves",
        "no data ever leaves",
        "fully offline",
        "completely private",
        "verifies correctness",
        "verifies that your work",
        "proves your work",
        "proof that your work",
        "guarantees your answer",
        "checks your answers",
        "grades your work",
        "plagiarism",
        "100% accurate",
        "bank-grade",
        "military-grade",
        "unhackable",
    ],
)
def test_no_public_page_makes_a_forbidden_claim(claim: str) -> None:
    haystack = _public_text().casefold()

    assert claim not in haystack, f"a public page claims: {claim!r}"


def test_the_evidence_scan_is_never_described_as_verification() -> None:
    for path in PUBLIC_PAGES:
        if not path.is_file():
            continue
        text = _read(path)
        for line in text.splitlines():
            lowered = line.casefold()
            if "a2l check" not in lowered and "evidence scan" not in lowered:
                continue
            for forbidden in ("verifies", "verified", "confirms", "proves", "validates"):
                assert forbidden not in lowered, f"{path.name}: {line.strip()}"


def test_upload_is_never_described_as_available_or_route_verified() -> None:
    haystack = _public_text().casefold()

    assert "disabled" in haystack
    for claim in (
        "upload is verified",
        "upload-verified route",
        "submission is enabled by default",
        "submits for you",
    ):
        assert claim not in haystack, claim


def test_the_readme_states_the_non_affiliation_and_licensed_material_limits() -> None:
    readme = _read(ROOT / "README.md")
    lowered = readme.casefold()

    assert "not affiliated with" in lowered
    assert "university of waterloo" in lowered
    assert "d2l" in lowered
    for phrase in ("etextbook", "library e-resource"):
        assert phrase in lowered, phrase
    assert "never" in lowered


def test_the_readme_states_the_privacy_defaults_accurately() -> None:
    lowered = _read(ROOT / "README.md").casefold()

    assert "off by default" in lowered
    assert "discussions" in lowered
    assert "grades" in lowered
    assert "telemetry" in lowered
    assert "your own account" in lowered
    assert "get request" in lowered or "read-mostly" in lowered


# --------------------------------------------------------------------------------------
# Install surface
# --------------------------------------------------------------------------------------


def test_the_readme_advertises_exactly_three_install_options() -> None:
    readme = _read(ROOT / "README.md")
    # Only the install options themselves. The skills-only npx route is deliberately a separate
    # subsection, because it does not install the engine.
    block = readme.split("## Install", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]

    assert "install.sh" in block
    assert "install.ps1" in block
    assert "uv tool install agent2learn" in block
    # A fourth advertised path would make the trusted surface ambiguous.
    assert "npx skills add" not in block
    assert "pipx" not in block
    assert "pip install" not in block


def test_the_readme_says_the_scripts_continue_into_onboarding() -> None:
    readme = _read(ROOT / "README.md")
    block = readme.split("## Install", 1)[1].split("\n## ", 1)[0].casefold()
    assert "install.sh" in block

    assert "a2l init" in block
    assert "continue" in block or "straight into" in block


def test_the_readme_separates_the_skills_only_npx_route_and_its_limit() -> None:
    readme = _read(ROOT / "README.md")
    lowered = readme.casefold()

    assert "npx skills add managementmo/agent2learn" in lowered
    assert "a2l skills install" in lowered
    section = lowered.split("npx skills add managementmo/agent2learn", 1)[1][:400]
    assert "does not install" in section
    assert "engine" in section


def test_the_install_page_is_written_for_an_agent_to_execute() -> None:
    text = _read(DOCS / "install.md")
    lowered = text.casefold()

    assert "agent" in lowered
    assert "a2l init" in lowered
    assert "do not" in lowered


# --------------------------------------------------------------------------------------
# The documented command surface is the real one
# --------------------------------------------------------------------------------------


def test_every_documented_command_exists() -> None:
    commands = _cli_commands()
    assert commands, "could not read the command list from --help"
    # FUTURE.md deliberately records commands that were considered and cut, so it is not a
    # claim that they exist.
    shipped_pages = "\n".join(
        _read(path) for path in PUBLIC_PAGES if path.is_file() and path.name != "FUTURE.md"
    )
    documented = set(re.findall(r"`a2l ([a-z][a-z-]*)", shipped_pages))
    documented -= {"tool"}  # `uv tool install` fragments

    unknown = sorted(name for name in documented if name not in commands)
    assert unknown == [], f"documented but not implemented: {unknown}"


def test_every_implemented_command_is_documented_somewhere() -> None:
    text = _public_text()
    missing = sorted(name for name in _cli_commands() if f"a2l {name}" not in text)

    assert missing == [], f"implemented but undocumented: {missing}"


def test_the_readme_names_the_version_it_documents() -> None:
    assert __version__ in _read(ROOT / "README.md") or __version__ in _read(DOCS / "install.md")


# --------------------------------------------------------------------------------------
# Privacy page
# --------------------------------------------------------------------------------------


def test_the_privacy_page_lists_every_external_network_action() -> None:
    lowered = _read(DOCS / "PRIVACY.md").casefold()

    for actor in (
        "learn",
        "duo",
        "astral",
        "pypi",
        "github",
        "npm",
    ):
        assert actor in lowered, actor
    assert "no passive version check" in lowered or "no background version check" in lowered
    assert "telemetry" in lowered
    assert "request logs" in lowered or "hosting" in lowered


def test_the_privacy_page_states_what_is_stored_and_how_to_delete_it() -> None:
    text = _read(DOCS / "PRIVACY.md")
    lowered = text.casefold()

    assert "| " in text, "the data-flow table is required"
    assert "a2l privacy purge" in lowered
    assert "a2l auth --clear-profile" in lowered
    assert "logical" in lowered  # purge is a logical deletion, and says so


def test_the_privacy_page_does_not_promise_isolation_it_cannot_keep() -> None:
    lowered = _read(DOCS / "PRIVACY.md").casefold()

    assert "local-first" in lowered or "stays on your computer" in lowered
    assert "learn" in lowered
    # The honest framing names the requests that do happen.
    assert "your own account" in lowered


# --------------------------------------------------------------------------------------
# Authentication page
# --------------------------------------------------------------------------------------


def test_the_authentication_page_covers_the_documented_recovery_paths() -> None:
    lowered = _read(DOCS / "AUTHENTICATION.md").casefold()

    for topic in (
        "dedicated",
        "same device",
        "duo",
        "keyring",
        "75",
        "--paste",
        "--clear-profile",
    ):
        assert topic in lowered, topic
    assert "never" in lowered and "copy" in lowered
    # Support must never ask for credentials.
    assert "do not send" in lowered or "never send" in lowered


# --------------------------------------------------------------------------------------
# Porting page
# --------------------------------------------------------------------------------------


def test_the_porting_page_documents_every_school_protocol_member() -> None:
    text = _read(DOCS / "PORTING.md")
    members = [name for name in dir(School) if not name.startswith("_") and name not in {"mro"}]
    annotations = list(getattr(School, "__annotations__", {}))

    for member in sorted(set(members) | set(annotations)):
        assert member in text, f"PORTING.md does not document School.{member}"
    assert "uwaterloo" in text.casefold()
    assert "synthetic" in text.casefold() or "fixture" in text.casefold()


# --------------------------------------------------------------------------------------
# llms.txt
# --------------------------------------------------------------------------------------


def test_llms_txt_follows_the_convention_and_every_link_resolves() -> None:
    text = _read(ROOT / "llms.txt")
    lines = [line for line in text.splitlines()]

    assert lines[0].startswith("# "), "llms.txt needs an H1 title"
    assert any(line.startswith("> ") for line in lines[:6]), "llms.txt needs a blockquote summary"
    assert any(line.startswith("## ") for line in lines), "llms.txt needs sections"

    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    assert links, "llms.txt must link to the docs"
    for link in links:
        if link.startswith("http"):
            continue
        assert link.endswith(".md"), f"{link} must be a markdown twin"
        assert (ROOT / link).is_file(), f"llms.txt links to a missing file: {link}"


# --------------------------------------------------------------------------------------
# No real data in public pages
# --------------------------------------------------------------------------------------


def test_no_public_page_contains_real_looking_personal_or_session_data() -> None:
    text = _public_text()

    # The university's own institutional help desk is a legitimate published address; a
    # personal-looking one is not.
    institutional = {"learnhelp@uwaterloo.ca"}
    found = set(re.findall(r"\b[A-Za-z0-9._%+-]+@uwaterloo\.ca\b", text))
    assert found <= institutional, f"personal-looking address(es): {sorted(found - institutional)}"
    assert not re.search(r"\bd2lSessionVal\b|\bd2lSecureSessionVal\b", text), "cookie name"
    assert not re.search(r"\b2[0-9]{7}\b", text), "student-number-shaped value"
    for marker in ("Bearer ", "X-Csrf-Token:"):
        assert marker not in text, marker


def test_the_future_page_records_deferrals_with_reasons() -> None:
    lowered = _read(DOCS / "FUTURE.md").casefold()

    for topic in ("claude code", "mcp", "brightspace", "one python engine"):
        assert topic in lowered, topic
    assert "pymupdf4llm" in lowered
    assert "agpl" in lowered
    assert "does not ship" in lowered or "not shipped" in lowered


def test_no_public_page_links_or_embeds_a_missing_local_file() -> None:
    """A README that advertises an asset it does not ship is making a false claim."""
    broken: list[str] = []
    for path in PUBLIC_PAGES:
        if not path.is_file():
            continue
        text = _read(path)
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                broken.append(f"{path.name} -> {target}")
    assert broken == [], f"links to missing files: {broken}"


def _documented_a2l_flags() -> set[str]:
    """Long flags documented on lines that invoke a2l, ignoring uv and curl examples."""
    flags: set[str] = set()
    for path in PUBLIC_PAGES:
        if not path.is_file() or path.name == "FUTURE.md":
            continue
        for line in _read(path).splitlines():
            if "a2l " not in line or "uv " in line or "curl " in line:
                continue
            flags.update(re.findall(r"(--[a-z][a-z-]*)", line))
    return flags


def test_every_documented_flag_exists_in_the_cli() -> None:
    """`ground --solve` must never appear in documentation, and neither must any other invention."""
    runner = CliRunner()
    available = strip_ansi(runner.invoke(app, ["--help"]).output)
    for command in sorted(_cli_commands()):
        available += strip_ansi(runner.invoke(app, [command, "--help"]).output)

    unknown = sorted(flag for flag in _documented_a2l_flags() if flag not in available)

    assert unknown == [], f"documented but not implemented: {unknown}"


def test_solve_is_only_ever_mentioned_as_permanently_absent() -> None:
    """The tool assembles cited sources; it does not answer. No page may imply otherwise."""
    for path in PUBLIC_PAGES:
        if not path.is_file() or path.name == "FUTURE.md":
            continue
        assert "--solve" not in _read(path), f"{path.name} documents a nonexistent solving mode"

    future = _read(DOCS / "FUTURE.md")
    assert "--solve" in future, "the cut surface must stay on the record"
    line = next(line for line in future.splitlines() if "--solve" in line)
    assert "absent" in line.casefold() or "never" in line.casefold(), line
