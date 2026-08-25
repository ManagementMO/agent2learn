"""Agent2Learn command-line entry point.

Every command is a thin wrapper: argument parsing and presentation live here, all
behaviour lives in the module that owns it. Nothing in this file talks to the network,
the filesystem, or a browser directly.
"""

from __future__ import annotations

import typer

from agent2learn import __version__

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


if __name__ == "__main__":  # pragma: no cover
    app()
