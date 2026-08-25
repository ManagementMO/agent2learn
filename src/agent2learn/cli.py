"""Agent2Learn command-line entry point.

Every command is a thin wrapper: argument parsing and presentation live here, all
behaviour lives in the module that owns it. Nothing in this file talks to the network,
the filesystem, or a browser directly.
"""

from __future__ import annotations

import json

import typer

from agent2learn import __version__
from agent2learn.calibrate import CourseRef, display_courses, load_calibration
from agent2learn.errors import NotConfigured
from agent2learn.schools import UWaterloo

app = typer.Typer(
    name="a2l",
    help="Turn your LEARN courses into a local vault your AI agent can read and cite.",
    add_completion=True,
    no_args_is_help=True,
)


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
