"""Agent2Learn command-line entry point.

Every command is a thin wrapper: argument parsing and presentation live here, all
behaviour lives in the module that owns it. The few local probes needed for command
confirmation use the shared path boundary; network and browser behaviour stay in their
owning modules.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from agent2learn import __version__, config, paths
from agent2learn import doctor as doctor_module
from agent2learn import session as session_store
from agent2learn import skills as skills_module
from agent2learn.api import Client
from agent2learn.auth import authenticate
from agent2learn.auth import clear_profile as remove_profile
from agent2learn.auth import verify as verify_session
from agent2learn.calibrate import CourseRef, display_courses, load_calibration
from agent2learn.errors import A2LError, AuthenticationError, NotConfigured, SessionExpired
from agent2learn.ingest import fetch_topic
from agent2learn.schools import UWaterloo
from agent2learn.vault import Vault

app = typer.Typer(
    name="a2l",
    help="Turn your LEARN courses into a local vault your AI agent can read and cite.",
    add_completion=True,
    no_args_is_help=True,
)

skills_app = typer.Typer(
    name="skills",
    help="Install or refresh Agent2Learn's canonical agent skills.",
    no_args_is_help=True,
)
app.add_typer(skills_app, name="skills")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agent2learn {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the installed version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Agent2Learn."""


@app.command()
def courses(
    all_terms: bool = typer.Option(
        False,
        "--all-terms",
        help="Show every discovered academic offering, grouped by term.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit stable machine-readable course metadata.",
    ),
) -> None:
    """List calibrated course offerings without downloading course content."""

    try:
        calibration = load_calibration()
    except NotConfigured as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from exc

    selected = display_courses(calibration, all_terms=all_terms)
    if json_output:
        typer.echo(_courses_json(selected, all_terms=all_terms))
        return
    _print_courses(selected, all_terms=all_terms)


@app.command()
def auth(
    paste: bool = typer.Option(
        False,
        "--paste",
        help="Read a manually exported cookie blob from a controlling hidden-input TTY.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Verify the saved session without opening a browser or asking for cookies.",
    ),
    clear_profile: bool = typer.Option(
        False,
        "--clear-profile",
        help=(
            "Clear the saved API session and remove the dedicated browser profile "
            "after confirmation."
        ),
    ),
) -> None:
    """Establish, verify, or deliberately clear the same-device LEARN session."""

    selected = sum((paste, check, clear_profile))
    if selected > 1:
        raise typer.BadParameter("--paste, --check, and --clear-profile are mutually exclusive")

    school = UWaterloo()
    try:
        if clear_profile:
            remove_profile()
            typer.echo("dedicated browser profile removed; saved API session cleared")
            return

        if check:
            try:
                saved = session_store.load()
            except (OSError, ValueError) as exc:
                raise AuthenticationError("stored session is unreadable · run: a2l auth") from exc
            if saved is None:
                typer.echo("no saved session · run: a2l auth", err=True)
                raise typer.Exit(code=3)
            if verify_session(saved, school) is None:
                typer.echo("session expired · run: a2l auth", err=True)
                raise typer.Exit(code=SessionExpired.exit_code)
            typer.echo("authentication verified")
            return

        authenticate(school, backend="paste" if paste else "auto")
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None

    if paste:
        typer.echo(
            "authentication verified; clear your clipboard if it still contains session cookies"
        )
    else:
        typer.echo("authentication verified")


@app.command()
def fetch(
    topic: str = typer.Argument(..., help="Stable topic ID, source key, title, or vault path."),
    allow_large: bool = typer.Option(
        False,
        "--allow-large",
        help="Permit this one oversized or unknown-length source after confirmation.",
    ),
) -> None:
    """Fetch one known topic and print its verified citation path."""

    try:
        try:
            cfg = config.load()
        except (OSError, ValueError) as exc:
            raise NotConfigured("configuration is unreadable · run: a2l init") from exc
        try:
            saved = session_store.load()
        except (OSError, ValueError) as exc:
            raise AuthenticationError("stored session is unreadable · run: a2l auth") from exc
        if saved is None:
            raise NotConfigured("no saved session · run: a2l auth")
        school = UWaterloo()
        vault = Vault(Path(cfg.vault))

        def confirm_large(size: int | None) -> bool:
            try:
                free = shutil.disk_usage(paths.long_path(vault.root)).free
            except OSError as exc:
                raise A2LError(
                    "free disk space is unavailable; check the vault permissions"
                ) from exc
            advertised = "unknown size" if size is None else f"{size:,} bytes"
            typer.echo(f"large-file override: {advertised}; free space: {free:,} bytes")
            return typer.confirm("Fetch this one source?", default=False)

        result = fetch_topic(
            Client(school, saved),
            vault,
            school,
            topic,
            allow_large=allow_large,
            confirm=confirm_large if allow_large else None,
        )
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except OSError as exc:
        typer.echo("fetch failed because local filesystem access is unavailable", err=True)
        raise typer.Exit(code=1) from exc

    citation = result.citation_path or result.source_path
    if citation is None:
        typer.echo("source fetched, but no verified citation twin is available", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"verified citation: {citation}")


@skills_app.command("install")
def skills_install(
    global_install: Annotated[
        bool,
        typer.Option(
            "--global",
            help="Install into detected user-level agent skill directories.",
        ),
    ] = False,
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            help="Install into detected project-local agent skill directories under PATH.",
        ),
    ] = None,
    link: Annotated[
        bool,
        typer.Option(
            "--link",
            help="Symlink to the canonical source instead of copying skill directories.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Refresh recognized Agent2Learn skill directories after previewing the change.",
        ),
    ] = False,
) -> None:
    """Install or refresh the four canonical Agent2Learn skills."""

    if global_install and project is not None:
        raise typer.BadParameter("--global and --project are mutually exclusive")
    try:
        skills_module.ensure_interactive_scope(
            explicit_project=project is not None,
            global_install=global_install,
            stdin_is_tty=sys.stdin.isatty(),
        )
        resolved_project = Path.cwd() if global_install else skills_module.resolve_project(project)
        scope: skills_module.Scope = "global" if global_install else "project"

        def confirm(preview: str) -> bool:
            typer.echo(preview, nl=False)
            return typer.confirm("Install Agent2Learn skills?", default=False)

        result = skills_module.install(
            scope=scope,
            project=resolved_project,
            force=force,
            link=link,
            confirm=confirm,
        )
    except skills_module.SkillsInstallError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    if result.cancelled:
        typer.echo("skills install cancelled")
        raise typer.Exit(code=1)
    typer.echo("skills installed")


@app.command()
def doctor(
    report: bool = typer.Option(
        False,
        "--report",
        help="Print a redacted markdown block that is safe to paste into a public issue.",
    ),
    open_issue: bool = typer.Option(
        False,
        "--open",
        help="Show the redacted report and the exact GitHub destination, then offer to open it.",
    ),
) -> None:
    """Diagnose the installation and end with exactly one next command."""

    config_failure: doctor_module.Check | None = None
    try:
        cfg = config.load()
    except (OSError, ValueError) as exc:
        # Doctor must be useful precisely when its own config is broken.  Do not echo the
        # parser's path or raw value; those can contain a user's home, course, or token-like text.
        cfg = config.Config()
        config_failure = doctor_module.Check(
            "Environment",
            "config.load",
            "fail",
            f"configuration is unreadable ({type(exc).__name__})",
            "run: a2l init",
        )

    root = Path(cfg.vault)
    try:
        vault = Vault(root) if Vault.is_vault(root) else None
    except (OSError, RuntimeError, ValueError):
        vault = None

    client = None
    try:
        saved = session_store.load()
        if saved is not None and cfg.school == "uwaterloo":
            client = Client(UWaterloo(), saved)
    except Exception:
        # _session() reports the redacted storage failure; client construction is only an
        # optional live probe and must never prevent the rest of doctor from rendering.
        client = None

    checks = doctor_module.run_checks(cfg, vault, client=client)
    if config_failure is not None:
        checks.insert(0, config_failure)

    if open_issue:
        # The body is shown before the browser opens. Opening the page itself sends the
        # displayed redacted body to GitHub; the user still reviews and submits manually.
        typer.echo(doctor_module.open_notice(checks))
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            typer.echo("refusing to open a report without an interactive terminal", err=True)
            raise typer.Exit(code=max(1, doctor_module.exit_code(checks)))
        if typer.confirm("Open this pre-filled issue in your browser?", default=False):
            typer.launch(doctor_module.issue_url(checks))
        raise typer.Exit(code=doctor_module.exit_code(checks))

    typer.echo(doctor_module.report(checks) if report else doctor_module.render(checks))
    raise typer.Exit(code=doctor_module.exit_code(checks))


def _courses_json(courses: list[CourseRef], *, all_terms: bool) -> str:
    """Serialize only typed calibration fields; no live response or hidden API data is emitted."""

    rows = [
        {
            "code": course.code,
            "is_active": course.is_active,
            "name": course.name,
            "org_unit_id": course.org_unit_id,
            "term": course.term,
        }
        for course in courses
    ]
    terms_set: set[str] = set()
    for course in courses:
        if course.term is not None:
            terms_set.add(course.term)
    terms = sorted(terms_set)
    return json.dumps(
        {"all_terms": all_terms, "courses": rows, "distinct_terms": terms},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def _print_courses(courses: list[CourseRef], *, all_terms: bool) -> None:
    if not courses:
        typer.echo("No calibrated academic course offerings found.")
        return

    school = UWaterloo()
    if all_terms:
        terms: list[str | None] = sorted(
            {course.term for course in courses}, key=lambda term: (term is None, term or "")
        )
        typer.echo(f"Distinct terms: {len(terms)}")
        for term in terms:
            label = "unclassified" if term is None else school.term_label(term)
            typer.echo(f"\n{label} ({term or 'none'})")
            for course in courses:
                if course.term == term:
                    typer.echo(_course_line(course))
        return

    typer.echo(f"Active academic offerings: {len(courses)}")
    for course in courses:
        typer.echo(_course_line(course))


def _course_line(course: CourseRef) -> str:
    return f"  {course.code} [{course.org_unit_id}] — {course.name}"


if __name__ == "__main__":  # pragma: no cover
    app()
