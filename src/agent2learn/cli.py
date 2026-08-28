"""Agent2Learn command-line entry point.

Every command is a thin wrapper: argument parsing and presentation live here, all
behaviour lives in the module that owns it. The few local probes needed for command
confirmation use the shared path boundary; network and browser behaviour stay in their
owning modules.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer

from agent2learn import __version__, config, console, paths
from agent2learn import calendar as calendar_module
from agent2learn import doctor as doctor_module
from agent2learn import index as index_module
from agent2learn import privacy as privacy_module
from agent2learn import session as session_store
from agent2learn import skills as skills_module
from agent2learn import snapshot as snapshot_module
from agent2learn.api import Client
from agent2learn.auth import authenticate
from agent2learn.auth import clear_profile as remove_profile
from agent2learn.auth import verify as verify_session
from agent2learn.calibrate import (
    Calibration,
    CourseRef,
    calibrate,
    display_courses,
    load_calibration,
)
from agent2learn.errors import A2LError, AuthenticationError, NotConfigured, SessionExpired
from agent2learn.ingest import (
    FileReport,
    MetadataReport,
    TopicRecord,
    fetch_topic,
    ingest_files,
    ingest_metadata,
    is_media_topic,
    load_metadata_topics,
)
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

privacy_app = typer.Typer(
    name="privacy",
    help="Inspect or deliberately remove locally retained sensitive categories.",
    no_args_is_help=True,
)
app.add_typer(privacy_app, name="privacy")


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


class _InitFailure(Exception):
    """A sanitized, single-recovery failure from the interactive initializer."""

    def __init__(self, stage: str, next_command: str, *, exit_code: int = 1, detail: str) -> None:
        super().__init__(stage)
        self.stage = stage
        self.next_command = next_command
        self.exit_code = exit_code
        self.detail = detail


_T = TypeVar("_T")
_INIT_SCHEMA_VERSION = 1
_INIT_STATE_FILENAME = "init.json"
_INIT_FILE_SCOPES = frozenset({"full", "priority", "later"})
_INIT_SKILL_STATUSES = frozenset({"installed", "declined", "unavailable"})
_INIT_AUTH_BACKENDS = frozenset({"auto", "paste"})


def _interactive_terminal() -> bool:
    """Return whether onboarding has both halves of a controlling terminal."""

    return _stream_is_tty(sys.stdin) and _stream_is_tty(sys.stdout)


def _stream_is_tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(callable(isatty) and isatty())
    except (AttributeError, OSError):
        return False


def _local_vault() -> tuple[config.Config, Vault, UWaterloo]:
    """Load the configured local vault without opening a network or browser session."""

    try:
        cfg = config.load()
    except (OSError, ValueError) as exc:
        raise NotConfigured("configuration is unreadable · run: a2l init") from exc
    root = Path(cfg.vault).expanduser()
    try:
        if not Vault.is_vault(root):
            raise NotConfigured("local vault is unavailable · run: a2l init")
        vault = Vault(root)
    except NotConfigured:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise NotConfigured("local vault is unavailable · run: a2l init") from exc
    if cfg.school != UWaterloo.id:
        raise A2LError("configured school adapter is unavailable")
    return cfg, vault, UWaterloo()


@app.command()
def init(
    vault: Annotated[
        Path | None,
        typer.Option(
            "--vault",
            help="Use PATH as the local vault root instead of the configured default.",
        ),
    ] = None,
) -> None:
    """Create or resume a consentful local vault onboarding session."""

    if not _interactive_terminal():
        # This check must precede config.load(), Vault.claim(), skill detection, and auth: each
        # may create local state, and a piped installer must never turn into an implicit setup.
        typer.echo("run: a2l init", err=True)
        raise typer.Exit(code=NotConfigured.exit_code)

    try:
        _run_init(vault)
    except _InitFailure as exc:
        _render_init_failure(exc)
    except KeyboardInterrupt:
        _render_init_failure(
            _InitFailure("onboarding", "a2l init", exit_code=130, detail="KeyboardInterrupt")
        )
    except Exception as exc:
        # Interactive setup is a public boundary.  Never expose an arbitrary exception string,
        # which can contain a home path, response body, cookie, or other local secret.
        _render_init_failure(_InitFailure("onboarding", "a2l init", detail=type(exc).__name__))


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
def today() -> None:
    """Show local deadlines, overdue work, changes, and the next exam countdown."""

    try:
        cfg, vault, school = _local_vault()
        report = calendar_module.build_today(
            vault,
            school,
            include_grades=cfg.include_grades,
        )
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except OSError:
        typer.echo("today failed because local vault metadata is unavailable", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(calendar_module.render_today(report, include_grades=cfg.include_grades), nl=False)


@app.command()
def diff(
    since: Annotated[
        str | None,
        typer.Option("--since", help="Compare with one exact earlier snapshot identifier."),
    ] = None,
) -> None:
    """Show structured changes between local vault snapshots."""

    try:
        cfg, vault, _school = _local_vault()
        result = snapshot_module.diff_vault(
            vault,
            since=since,
            include_grades=cfg.include_grades,
        )
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except (OSError, ValueError) as exc:
        typer.echo(f"diff failed ({type(exc).__name__}); run: a2l sync", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        snapshot_module.render_diff(result, include_grades=cfg.include_grades),
        nl=False,
    )


@app.command()
def calendar(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the calendar atomically to FILE."),
    ] = None,
) -> None:
    """Export local deadlines, exams, and office hours as an iCalendar file."""

    try:
        _cfg, vault, school = _local_vault()
        if output is None:
            typer.echo(calendar_module.render_ics(vault, school), nl=False)
        else:
            written = calendar_module.write_ics(vault, school, output)
            typer.echo(f"calendar exported: {_display_path(written)}")
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except OSError:
        typer.echo("calendar failed because local vault metadata is unavailable", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def where(
    query: str = typer.Argument(..., help="Words to find in local course content metadata."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit stable machine-readable matches instead of terminal lines.",
    ),
) -> None:
    """Fuzzy-find a non-sensitive topic across every local course and term."""

    try:
        _cfg, vault, _school = _local_vault()
        matches = index_module.search_topics(vault, query)
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except OSError:
        typer.echo("where failed because local content maps are unavailable", err=True)
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(
            json.dumps([asdict(match) for match in matches], ensure_ascii=False, sort_keys=True)
        )
        return
    if not matches:
        typer.echo("No matching topics found.")
        return
    for match in matches:
        locations = [
            f"twin={match.path}" if match.path else None,
            f"source={match.source_path}" if match.source_path else None,
            f"stub={match.stub_path}" if match.stub_path else None,
        ]
        target = ", ".join(value for value in locations if value) or "metadata only"
        typer.echo(f"{match.course} · {match.title} [{match.kind}] · {target}")


@app.command("open")
def open_course(
    course: str = typer.Argument(
        ..., help="Course code, course folder, name, or term-qualified selector."
    ),
) -> None:
    """Ask the operating system to reveal one known local course folder."""

    try:
        _cfg, vault, _school = _local_vault()
        course_dir = index_module.resolve_course(vault, course)
        paths.reveal(course_dir)
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except OSError:
        typer.echo("open failed because local course metadata is unavailable", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"requested opening: {_display_path(course_dir)}")


@privacy_app.command("status")
def privacy_status() -> None:
    """Show sensitive-category collection flags and redacted local locations."""

    try:
        cfg, vault, _school = _local_vault()
        value = privacy_module.status(vault, cfg)
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except (OSError, ValueError):
        typer.echo("privacy status failed because local state is unavailable", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(privacy_module.render_status(value), nl=False)


@privacy_app.command("purge")
def privacy_purge(
    category: str = typer.Argument(..., help="Exactly one of: grades, discussions, logs."),
) -> None:
    """Preview an exact privacy purge and require a fresh controlling-terminal phrase."""

    try:
        _cfg, vault, _school = _local_vault()
        plan = privacy_module.plan_purge(vault, category)
        typer.echo(privacy_module.render_plan(plan), nl=False)
        if not plan.targets:
            return
        if not _interactive_terminal():
            typer.echo("refusing to purge without an interactive terminal", err=True)
            raise typer.Exit(code=1)
        phrase = typer.prompt(f"Type PURGE {plan.category.upper()} to continue", default="")
        privacy_module.execute_purge(
            vault,
            plan,
            phrase=phrase,
            interactive=True,
        )
    except A2LError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except (OSError, ValueError):
        typer.echo("privacy purge failed because local state is unavailable", err=True)
        raise typer.Exit(code=1) from None
    typer.echo("privacy purge complete (logical deletion only)")


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


def _run_init(requested_vault: Path | None) -> None:
    """Run the ordered, resumable onboarding state machine."""

    cfg = _init_stage("configuration", "a2l init", config.load)
    if cfg.school.casefold() != UWaterloo.id:
        raise _InitFailure("school selection", "a2l init", detail="unsupported school")

    school = UWaterloo()
    requested = _init_stage("vault", "a2l init", lambda: _resolve_init_vault(requested_vault, cfg))
    if _agent2learn_checkout(requested):
        raise _InitFailure("vault", "a2l init", detail="source checkout selected")

    candidate, already_vault = _init_stage("vault", "a2l init", lambda: _preview_vault(requested))
    state = _init_stage("vault", "a2l init", lambda: _read_init_state(candidate))

    if (not already_vault or state.get("vault_confirmed") is not True) and not typer.confirm(
        _vault_prompt(requested, candidate, already_vault), default=True
    ):
        raise _InitFailure("vault", "a2l init", detail="cancelled")

    claimed = _init_stage("vault", "a2l init", lambda: Vault.claim(candidate, allow_suffix=False))
    if claimed != candidate:
        raise _InitFailure("vault", "a2l init", detail="vault location changed")
    _init_stage("vault", "a2l init", lambda: Vault(claimed).manifest())
    state = _init_stage(
        "vault",
        "a2l init",
        lambda: _update_init_state(claimed, state, school=school.id, vault_confirmed=True),
    )
    _init_stage("vault", "a2l init", lambda: _ensure_obsidian_config(claimed))

    typer.echo(f"{console.GLYPH['ok']} vault           {_display_path(claimed)}")
    typer.echo(f"{console.GLYPH['ok']} school          {school.name} ({school.base_url})")

    state = _init_stage("agent skills", "a2l init", lambda: _configure_init_skills(claimed, state))
    state, include_grades = _init_stage(
        "grade preference", "a2l init", lambda: _configure_init_grades(claimed, state, cfg)
    )
    cfg = _init_stage(
        "configuration", "a2l init", lambda: _save_init_config(cfg, claimed, include_grades)
    )

    state, backend = _init_stage(
        "browser profile", "a2l init", lambda: _configure_init_auth(claimed, state)
    )
    session_value: Any = None
    if state.get("authenticated") is True:
        try:
            session_value = session_store.load()
        except (OSError, ValueError):
            # A stale or malformed local projection is recoverable by authenticating again.  Do
            # not echo its path or contents and do not let it bypass the explicit profile choice.
            session_value = None

    if session_value is None:
        if backend == "auto":
            typer.echo("→ opening your browser — sign in to LEARN (WatIAM + Duo)…")
        else:
            typer.echo("→ waiting for hidden-TTY cookie paste…")
        session_value = _init_stage(
            "authentication",
            "a2l auth",
            lambda: authenticate(school, backend=backend),
        )
        if session_value is None:
            raise _InitFailure("authentication", "a2l auth", detail="no verified session")
        state = _init_stage(
            "authentication",
            "a2l auth",
            lambda: _update_init_state(
                claimed,
                state,
                authenticated=True,
                auth_backend=backend,
            ),
        )
        typer.echo(f"{console.GLYPH['ok']} signed in")
    else:
        typer.echo(f"{console.GLYPH['ok']} signed in (saved local session)")

    client = _init_stage("course discovery", "a2l init", lambda: Client(school, session_value))
    calibration = _init_stage("course discovery", "a2l init", lambda: calibrate(client))
    courses = _init_stage("course discovery", "a2l init", lambda: _calibration_courses(calibration))
    active = [course for course in courses if course.is_active and course.term is not None]
    state_term = state.get("term")
    preferred_term = state_term if isinstance(state_term, str) else None
    term = _init_stage(
        "course discovery",
        "a2l init",
        lambda: _choose_active_term(active, school, preferred_term=preferred_term),
    )
    if term is None:
        raise _InitFailure(
            "course discovery",
            "a2l courses --all-terms",
            exit_code=NotConfigured.exit_code,
            detail="no active academic term",
        )

    active_for_term = _sort_courses(course for course in active if course.term == term)
    previous_term = state.get("term") if isinstance(state.get("term"), str) else None
    if previous_term is not None and previous_term != term:
        if not typer.confirm(
            f"New term detected: {len(active_for_term)} courses. Sync?", default=True
        ):
            typer.echo("new term skipped; run: a2l init")
            return
        state = dict(state)
        state.pop("selected_offering_ids", None)
        state.pop("file_scope", None)
        state.pop("file_complete", None)
        state["metadata_complete"] = False
        state["term"] = term
        state = _init_stage(
            "course selection", "a2l init", lambda: _save_init_state(claimed, state)
        )

    selection_is_persisted = state.get("term") == term and "selected_offering_ids" in state
    if selection_is_persisted:
        selected_ids = _state_offering_ids(state)
        by_id = {course.org_unit_id: course for course in active_for_term}
        selected = [by_id[offering_id] for offering_id in selected_ids if offering_id in by_id]
        _print_course_selection(term, active_for_term, selected, school, persisted=True)
    else:
        selected = _init_stage(
            "course selection",
            "a2l init",
            lambda: _prompt_course_selection(term, active_for_term, school),
        )
        state = dict(state)
        state.update(
            {
                "term": term,
                "selected_offering_ids": [course.org_unit_id for course in selected],
                "metadata_complete": False,
                "file_complete": False,
            }
        )
        state = _init_stage(
            "course selection", "a2l init", lambda: _save_init_state(claimed, state)
        )

    selected_ids = [course.org_unit_id for course in selected]
    metadata: MetadataReport | None = None
    if state.get("metadata_complete") is not True:
        typer.echo(
            f"→ reading {len(selected)} courses…                          (metadata only — seconds)"
        )
        metadata = _init_stage(
            "metadata sync",
            "a2l init",
            lambda: ingest_metadata(
                client,
                Vault(claimed),
                school,
                term=term,
                only=selected_ids,
                include_grades=include_grades,
            ),
        )
        if _report_has_errors(metadata):
            raise _InitFailure("metadata sync", "a2l init", detail="coverage gap")
        state = _init_stage(
            "metadata sync",
            "a2l init",
            lambda: _update_init_state(
                claimed,
                state,
                metadata_complete=True,
                last_seen_term=term,
            ),
        )
    else:
        typer.echo(f"{console.GLYPH['ok']} metadata already synced")

    _init_stage(
        "summary",
        "a2l init",
        lambda: _print_metadata_summary(
            metadata,
            claimed,
            school,
            term=term,
            selected_count=len(selected),
            include_grades=include_grades,
        ),
    )

    if state.get("file_complete") is not True:
        estimate_topics: Iterable[object]
        if metadata is None:
            estimate_topics = _init_stage(
                "file estimate",
                "a2l init",
                lambda: load_metadata_topics(Vault(claimed), school, selected),
            )
        else:
            estimate_topics = _iter_report_topics(metadata)
        _init_stage("file estimate", "a2l init", lambda: _print_file_estimates(estimate_topics))
        stored_scope = state.get("file_scope")
        if stored_scope in _INIT_FILE_SCOPES:
            scope_choice = str(stored_scope)
        else:
            scope_choice = _init_stage("file choice", "a2l init", _prompt_file_scope)
            state = _init_stage(
                "file choice",
                "a2l init",
                lambda: _update_init_state(claimed, state, file_scope=scope_choice),
            )

        if scope_choice == "later":
            state = _init_stage(
                "file choice",
                "a2l init",
                lambda: _update_init_state(claimed, state, file_complete=True),
            )
            typer.echo("files deferred; metadata and deadlines are ready locally")
        else:
            file_report = _init_stage(
                "file sync",
                "a2l init",
                lambda: ingest_files(
                    client,
                    Vault(claimed),
                    school,
                    term=term,
                    only=selected_ids,
                    scope="priority" if scope_choice == "priority" else "all",
                    include_media=False,
                    include_discussions=False,
                ),
            )
            if _file_report_has_errors(file_report):
                exit_code = 130 if file_report.interrupted else 1
                raise _InitFailure(
                    "file sync", "a2l init", exit_code=exit_code, detail="incomplete"
                )
            state = _init_stage(
                "file sync",
                "a2l init",
                lambda: _update_init_state(claimed, state, file_complete=True),
            )
            typer.echo(
                f"{console.GLYPH['ok']} files · {file_report.downloaded} downloaded · "
                f"{file_report.skipped} skipped"
            )
    else:
        typer.echo(
            f"{console.GLYPH['ok']} files already handled ({state.get('file_scope', 'later')})"
        )

    typer.echo(
        "\nTry:  a2l today\n"
        '      or ask your agent: "quiz me on COURSE 101 using only my lecture slides"\n'
        "      include large media later: a2l sync --all --include-media"
    )


def _init_stage(stage: str, next_command: str, operation: Callable[[], _T]) -> _T:
    """Run one stage and collapse all expected failures to one safe recovery command."""

    try:
        return operation()
    except _InitFailure:
        raise
    except SessionExpired as exc:
        raise _InitFailure(
            stage, "a2l auth", exit_code=SessionExpired.exit_code, detail=type(exc).__name__
        ) from None
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        raise _InitFailure(stage, next_command, detail=type(exc).__name__) from None


def _render_init_failure(failure: _InitFailure) -> None:
    """Render a sanitized initializer failure and exactly one actionable command."""

    typer.echo(f"init stopped during {failure.stage} ({failure.detail}).", err=True)
    typer.echo(f"run: {failure.next_command}", err=True)
    raise typer.Exit(code=failure.exit_code)


def _resolve_init_vault(requested_vault: Path | None, cfg: config.Config) -> Path:
    value = cfg.vault if requested_vault is None else requested_vault
    return Path(value).expanduser().resolve()


def _agent2learn_checkout(path: Path) -> bool:
    source_root = Path(__file__).resolve().parents[2]
    if not (
        paths.long_path(source_root / "pyproject.toml").is_file()
        and paths.long_path(source_root / "src" / "agent2learn").is_dir()
    ):
        return False
    try:
        path.relative_to(source_root)
    except ValueError:
        return False
    return True


def _preview_vault(requested: Path) -> tuple[Path, bool]:
    """Return the existing vault or first safe candidate without writing anything."""

    candidate = requested
    for suffix in range(2, 1002):
        if paths.is_link(candidate):
            candidate = requested.with_name(f"{requested.name}-{suffix}")
            continue
        if Vault.is_vault(candidate):
            return candidate, True
        if not paths.collides(candidate):
            return candidate, False
        candidate = requested.with_name(f"{requested.name}-{suffix}")
    raise ValueError("could not allocate a safe vault name")


def _vault_prompt(requested: Path, candidate: Path, already_vault: bool) -> str:
    if already_vault:
        return (
            "Agent2Learn will use the existing local vault at "
            f"{_display_path(candidate)}. Continue?"
        )
    if candidate != requested:
        return (
            f"{_display_path(requested)} is occupied and is not an Agent2Learn vault. "
            f"Agent2Learn will create {_display_path(candidate)} instead. Continue?"
        )
    return f"Agent2Learn will create a local vault at {_display_path(candidate)}. Continue?"


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _ensure_obsidian_config(root: Path) -> None:
    destination = root / ".obsidian"
    if paths.is_link(destination):
        raise ValueError("Obsidian configuration directory is a symlink")
    if paths.long_path(destination).is_dir():
        return
    if paths.long_path(destination).is_file():
        raise ValueError("Obsidian configuration path is not a directory")
    paths.long_path(destination).mkdir(parents=True, exist_ok=False)
    paths.atomic_write_text(destination / "app.json", '{"showLineNumber":true}\n')


def _read_init_state(root: Path) -> dict[str, object]:
    state_dir = root / ".a2l"
    if paths.is_link(state_dir):
        raise ValueError("initializer state directory must not be a symlink")
    if paths.long_path(state_dir).is_file():
        raise ValueError("initializer state path is not a directory")
    if not paths.long_path(state_dir).is_dir():
        return {}
    destination = state_dir / _INIT_STATE_FILENAME
    if paths.is_link(destination):
        raise ValueError("initializer state must not be a symlink")
    if not paths.long_path(destination).is_file():
        return {}
    try:
        with open(os.fspath(paths.long_path(destination)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("initializer state is unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("initializer state must be an object")
    state = {str(key): value for key, value in raw.items()}
    _validate_init_state(state)
    return state


def _validate_init_state(state: dict[str, object]) -> None:
    version = state.get("schema_version", _INIT_SCHEMA_VERSION)
    if isinstance(version, bool) or version != _INIT_SCHEMA_VERSION:
        raise ValueError("initializer state schema is unsupported")
    for key in (
        "vault_confirmed",
        "grades_configured",
        "include_grades",
        "profile_consent",
        "authenticated",
        "metadata_complete",
        "file_complete",
    ):
        if key in state and not isinstance(state[key], bool):
            raise ValueError(f"initializer state field {key} is invalid")
    for key in ("school", "term", "last_seen_term"):
        if key in state and not isinstance(state[key], str):
            raise ValueError(f"initializer state field {key} is invalid")
    for key in ("file_scope", "skills_status", "auth_backend"):
        if key in state and not isinstance(state[key], str):
            raise ValueError(f"initializer state field {key} is invalid")
    if state.get("file_scope") not in (None, *_INIT_FILE_SCOPES):
        raise ValueError("initializer state file scope is invalid")
    if state.get("skills_status") not in (None, *_INIT_SKILL_STATUSES):
        raise ValueError("initializer state skill status is invalid")
    if state.get("auth_backend") not in (None, *_INIT_AUTH_BACKENDS):
        raise ValueError("initializer state authentication backend is invalid")
    offering_ids = state.get("selected_offering_ids")
    if offering_ids is not None and (
        not isinstance(offering_ids, list)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in offering_ids
        )
        or len(set(offering_ids)) != len(offering_ids)
    ):
        raise ValueError("initializer state offering IDs are invalid")


def _save_init_state(root: Path, state: dict[str, object]) -> dict[str, object]:
    _validate_init_state(state)
    state_dir = root / ".a2l"
    if paths.is_link(state_dir):
        raise ValueError("initializer state directory must not be a symlink")
    if not paths.long_path(state_dir).is_dir():
        raise ValueError("initializer state directory is unavailable")
    payload = {"schema_version": _INIT_SCHEMA_VERSION, **state}
    paths.atomic_write_text(
        state_dir / _INIT_STATE_FILENAME,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    return payload


def _update_init_state(
    root: Path, state: dict[str, object], **updates: object
) -> dict[str, object]:
    updated = dict(state)
    updated.update(updates)
    return _save_init_state(root, updated)


def _configure_init_skills(root: Path, state: dict[str, object]) -> dict[str, object]:
    if state.get("skills_status") in {"installed", "declined"}:
        return state
    destinations = skills_module.detect_destinations(scope="project", project=root)
    if not destinations:
        typer.echo("No detected agent skill destinations; skipping project-local skills.")
        return _update_init_state(root, state, skills_status="unavailable")

    agents = sorted({agent for destination in destinations for agent in destination.agents})
    typer.echo(f"Found {_join_words(agents)}.")

    def confirm(preview: str) -> bool:
        typer.echo(preview, nl=False)
        return typer.confirm(
            f"Install {len(skills_module.SKILL_SLUGS)} skills into this project?", default=True
        )

    result = skills_module.install(
        scope="project",
        project=root,
        force=False,
        link=False,
        confirm=confirm,
    )
    if result.cancelled:
        typer.echo("agent skills skipped")
        return _update_init_state(root, state, skills_status="declined")
    typer.echo(
        f"{console.GLYPH['ok']} agent skills    "
        f"{len(skills_module.SKILL_SLUGS)} installed project-locally"
    )
    return _update_init_state(root, state, skills_status="installed")


def _configure_init_grades(
    root: Path, state: dict[str, object], cfg: config.Config
) -> tuple[dict[str, object], bool]:
    if state.get("grades_configured") is True:
        return state, state.get("include_grades") is True
    include_grades = typer.confirm(
        "Include private grade values in local syncs?", default=cfg.include_grades
    )
    return (
        _update_init_state(
            root,
            state,
            grades_configured=True,
            include_grades=include_grades,
        ),
        include_grades,
    )


def _save_init_config(cfg: config.Config, root: Path, include_grades: bool) -> config.Config:
    updated = replace(
        cfg,
        vault=root,
        school=UWaterloo.id,
        include_grades=include_grades,
    )
    if updated != cfg:
        config.save(updated)
    return updated


def _configure_init_auth(root: Path, state: dict[str, object]) -> tuple[dict[str, object], str]:
    if "profile_consent" not in state:
        typer.echo(
            "Agent2Learn will open a dedicated local browser profile. It keeps Waterloo/Duo\n"
            "remembered sign-in state on this device. Clear it later with: a2l auth --clear-profile"
        )
        profile_consent = typer.confirm("Continue?", default=True)
        state = dict(state)
        state["profile_consent"] = profile_consent
        state = _save_init_state(root, state)
    else:
        profile_consent = state.get("profile_consent") is True

    if profile_consent:
        backend = "auto"
    else:
        stored_backend = state.get("auth_backend")
        if stored_backend == "paste":
            backend = "paste"
        else:
            typer.echo("Dedicated profile skipped; the hidden-TTY paste path is still available.")
            if not typer.confirm("Use hidden-TTY cookie paste now?", default=True):
                raise _InitFailure("authentication", "a2l auth --paste", detail="cancelled")
            backend = "paste"
    state = dict(state)
    state["auth_backend"] = backend
    return _save_init_state(root, state), backend


def _calibration_courses(calibration: Calibration) -> list[CourseRef]:
    courses = calibration.courses
    if not isinstance(courses, Sequence):
        raise ValueError("calibration courses are invalid")
    if any(not isinstance(course, CourseRef) for course in courses):
        raise ValueError("calibration courses are invalid")
    return list(courses)


def _sort_courses(courses: Iterable[CourseRef]) -> list[CourseRef]:
    return sorted(courses, key=lambda course: (course.code.casefold(), course.org_unit_id))


def _infer_active_term(courses: Sequence[CourseRef]) -> str | None:
    terms = {course.term for course in courses if course.term is not None}
    if not terms:
        return None
    return max(terms, key=_term_sort_key)


def _choose_active_term(
    courses: Sequence[CourseRef], school: UWaterloo, *, preferred_term: str | None = None
) -> str | None:
    """Require an explicit term choice when the enrollment projection is ambiguous."""

    terms = sorted(
        {course.term for course in courses if course.term is not None},
        key=_term_sort_key,
    )
    if not terms:
        return None
    if len(terms) == 1:
        return terms[0]

    default = preferred_term if preferred_term in terms else _infer_active_term(courses)
    typer.echo("Multiple active academic terms found; choose which term to sync:")
    for term in terms:
        count = sum(1 for course in courses if course.term == term)
        typer.echo(f"  {_term_label(school, term)} [{term}] · {count} courses")
    choices = {term.casefold(): term for term in terms}
    while True:
        selected = str(typer.prompt("Choose an active term code", default=default)).strip()
        resolved = choices.get(selected.casefold())
        if resolved is not None:
            return resolved
        typer.echo(f"Choose one of: {', '.join(terms)}.")


def _term_sort_key(term: str) -> tuple[int, str]:
    return (int(term), term) if term.isdigit() else (0, term.casefold())


def _term_label(school: UWaterloo, term: str) -> str:
    try:
        return school.term_label(term)
    except ValueError:
        return f"Term {term}"


def _prompt_course_selection(
    term: str, courses: Sequence[CourseRef], school: UWaterloo
) -> list[CourseRef]:
    label = _term_label(school, term)
    typer.echo(f"{label} · {len(courses)} academic courses found.")
    for index, course in enumerate(courses, start=1):
        typer.echo(f"  {index}. {course.code} [{course.org_unit_id}] — {course.name}")
    if typer.confirm(f"{label} · {len(courses)} academic courses found. Sync all?", default=True):
        return list(courses)
    while True:
        value = typer.prompt(
            "Select courses by number, code, or stable offering ID "
            "(comma-separated; empty for none)",
            default="none",
        )
        try:
            return _parse_course_selection(value, courses)
        except ValueError:
            typer.echo("Selection did not match a known course; try again.")


def _parse_course_selection(value: str, courses: Sequence[CourseRef]) -> list[CourseRef]:
    tokens = [token for token in re.split(r"[,\s]+", value.strip()) if token]
    if not tokens or tokens == ["none"]:
        return []
    if len(tokens) == 1 and tokens[0].casefold() == "all":
        return list(courses)
    selected: list[CourseRef] = []
    for token in tokens:
        match: CourseRef | None = None
        if token.isdigit():
            match = next((course for course in courses if str(course.org_unit_id) == token), None)
            if match is None:
                position = int(token)
                if 1 <= position <= len(courses):
                    match = courses[position - 1]
        else:
            match = next(
                (course for course in courses if course.code.casefold() == token.casefold()), None
            )
        if match is None:
            raise ValueError("course selection contains an unknown offering")
        if match not in selected:
            selected.append(match)
    return selected


def _print_course_selection(
    term: str,
    available: Sequence[CourseRef],
    selected: Sequence[CourseRef],
    school: UWaterloo,
    *,
    persisted: bool,
) -> None:
    label = _term_label(school, term)
    suffix = " (saved selection)" if persisted else ""
    typer.echo(f"{label} · {len(available)} academic courses found{suffix}.")
    typer.echo(f"{console.GLYPH['ok']} {len(selected)} academic offerings selected")


def _state_offering_ids(state: dict[str, object]) -> list[int]:
    value = state.get("selected_offering_ids", [])
    if not isinstance(value, list):
        raise ValueError("initializer state offering IDs are invalid")
    return [value for value in value if isinstance(value, int) and not isinstance(value, bool)]


def _report_has_errors(report: MetadataReport) -> bool:
    errors = getattr(report, "errors", ())
    exit_code = getattr(report, "exit_code", 0)
    return bool(errors) or (isinstance(exit_code, int) and exit_code != 0)


def _file_report_has_errors(report: FileReport) -> bool:
    errors = getattr(report, "errors", ())
    exit_code = getattr(report, "exit_code", 0)
    failed = getattr(report, "failed", 0)
    interrupted = getattr(report, "interrupted", False)
    return (
        bool(errors)
        or failed != 0
        or interrupted
        or (isinstance(exit_code, int) and exit_code != 0)
    )


def _read_metadata_rows(path: Path) -> list[dict[str, object]]:
    if paths.is_link(path) or not paths.long_path(path).is_file():
        return []
    try:
        with open(os.fspath(paths.long_path(path)), encoding="utf-8", newline="") as handle:
            raw: Any = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _print_metadata_summary(
    report: MetadataReport | None,
    root: Path,
    school: UWaterloo,
    *,
    term: str,
    selected_count: int,
    include_grades: bool,
) -> None:
    if report is None:
        typer.echo(f"{console.GLYPH['ok']} metadata is ready for {_term_label(school, term)}")
        return
    reports = getattr(report, "courses", ())
    course_count = len(reports) if isinstance(reports, Sequence) else selected_count
    topic_count = getattr(report, "topic_count", 0)
    deadline_count = getattr(report, "deadline_count", 0)
    if not isinstance(topic_count, int):
        topic_count = 0
    if not isinstance(deadline_count, int):
        deadline_count = 0

    assignment_count = 0
    quiz_count = 0
    deadlines: list[tuple[str, str, str]] = []
    if isinstance(reports, Sequence):
        for course_report in reports:
            directory = getattr(course_report, "directory", None)
            course = getattr(course_report, "course", None)
            if not isinstance(directory, Path):
                continue
            code = str(getattr(course, "code", "course"))
            assignments = _read_metadata_rows(directory / "_meta" / "assignments.json")
            quizzes = _read_metadata_rows(directory / "_meta" / "quizzes.json")
            assignment_count += len(assignments)
            quiz_count += len(quizzes)
            for row in [*assignments, *quizzes]:
                due = row.get("due_date")
                title = row.get("title")
                if isinstance(due, str) and due and isinstance(title, str) and title:
                    deadlines.append((due, title, code))

    grade_text = "grades synced" if include_grades else "grades not synced"
    detail = f"{deadline_count} deadlines"
    if assignment_count or quiz_count:
        detail = f"{assignment_count} assignments · {quiz_count} quizzes · {detail}"
    typer.echo(
        f"{console.GLYPH['ok']} {course_count} courses · {topic_count} topics · "
        f"{detail} · {grade_text}"
    )
    for due, title, code in sorted(deadlines)[:5]:
        typer.echo(f"  {code} · {title} — due {due}")
    if not deadlines:
        typer.echo(f"  No upcoming deadlines recorded in {_term_label(school, term)} metadata.")
    del root


def _iter_report_topics(value: MetadataReport | Iterable[object] | None) -> Iterable[object]:
    if value is None:
        return ()
    if not isinstance(value, MetadataReport):
        return value
    reports = value.courses
    topics: list[object] = []
    for course_report in reports:
        values = getattr(course_report, "topics", ())
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            topics.extend(values)
    return topics


def _topic_is_media(topic: object) -> bool:
    return isinstance(topic, TopicRecord) and is_media_topic(topic)


def _topic_is_downloadable(topic: object) -> bool:
    availability = getattr(topic, "availability", "metadata_only")
    kind = getattr(topic, "kind", "")
    url_path = getattr(topic, "url_path", None)
    return (
        availability != "external_link"
        and isinstance(kind, str)
        and kind.casefold() in {"file", "html", "htmlfile"}
        and isinstance(url_path, str)
        and bool(url_path)
        and getattr(topic, "is_broken", False) is not True
    )


def _print_file_estimates(topics: Iterable[object]) -> None:
    document_size = 0
    media_size = 0
    document_unknown = False
    media_unknown = False
    document_count = media_count = 0
    for topic in topics:
        if not _topic_is_downloadable(topic):
            continue
        remote_size = getattr(topic, "remote_size", None)
        is_media = _topic_is_media(topic)
        if is_media:
            media_count += 1
            if (
                isinstance(remote_size, int)
                and not isinstance(remote_size, bool)
                and remote_size >= 0
            ):
                media_size += remote_size
            else:
                media_unknown = True
        else:
            document_count += 1
            if (
                isinstance(remote_size, int)
                and not isinstance(remote_size, bool)
                and remote_size >= 0
            ):
                document_size += remote_size
            else:
                document_unknown = True

    full = _size_estimate(document_size, document_unknown, document_count)
    priority = "unknown" if document_unknown else f"up to {full}"
    duration = _duration_estimate(document_size, document_unknown)
    typer.echo("Files:")
    typer.echo(f"  full document archive {full} ({duration}; recommended; media excluded)")
    typer.echo(f"  priority set {priority} ({_duration_estimate(document_size, document_unknown)})")
    typer.echo("  or download later")
    if media_count:
        media_label = _size_estimate(media_size, media_unknown, media_count)
        typer.echo(f"  audio/video {media_label} excluded; opt in later with --include-media")


def _size_estimate(size: int, unknown: bool, count: int) -> str:
    if unknown:
        return "unknown"
    if count == 0:
        return "0 B"
    if size >= 1024 * 1024:
        return f"~{size / (1024 * 1024):.0f} MB"
    if size >= 1024:
        return f"~{size / 1024:.0f} KB"
    return f"~{size} B"


def _duration_estimate(size: int, unknown: bool) -> str:
    if unknown:
        return "duration unknown"
    seconds = max(1, (size + (5 * 1024 * 1024) - 1) // (5 * 1024 * 1024))
    minutes = max(1, (seconds + 59) // 60)
    return f"~{minutes} min"


def _prompt_file_scope() -> str:
    while True:
        choice = str(typer.prompt("Choose [full/priority/later]", default="full"))
        choice = choice.strip().casefold()
        if choice in _INIT_FILE_SCOPES:
            return choice
        typer.echo("Choose one of: full, priority, later.")


def _join_words(values: Sequence[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


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
