"""Exercise an installed wheel's CLI without login, course requests, or setup writes."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from typer.main import get_command
from typer.testing import CliRunner

import agent2learn
from agent2learn.cli import app


def _command_paths() -> list[list[str]]:
    result: list[list[str]] = [[]]
    pending: list[tuple[list[str], object]] = [([], get_command(app))]
    while pending:
        prefix, command = pending.pop()
        children = getattr(command, "commands", None)
        if not isinstance(children, dict):
            continue
        for name, child in sorted(children.items()):
            assert isinstance(name, str)
            path = [*prefix, name]
            result.append(path)
            pending.append((path, child))
    return result


def main() -> None:
    assert Path(agent2learn.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    executable = Path(sys.executable).with_name("a2l.exe" if os.name == "nt" else "a2l")
    reported = subprocess.run(
        [str(executable), "--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    assert reported.stdout.strip() == f"agent2learn {version('agent2learn')}"

    runner = CliRunner()
    command_paths = _command_paths()
    for path in command_paths:
        result = runner.invoke(app, [*path, "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
        assert result.exit_code == 0 and result.output.strip(), (
            f"help failed for {' '.join(path) or 'root'}: exit {result.exit_code}, "
            f"exception {type(result.exception).__name__}"
        )
    for shell in ("bash", "zsh", "fish", "powershell"):
        result = runner.invoke(app, ["completions", shell])
        assert result.exit_code == 0 and result.output.strip(), f"completion failed: {shell}"
    assert runner.invoke(app, ["--not-a-real-option"]).exit_code == 2

    with TemporaryDirectory(prefix="a2l-cli-refusal-") as temporary:
        vault = Path(temporary) / "must-not-be-created"
        result = runner.invoke(app, ["init", "--vault", str(vault)])
        assert result.exit_code == 3, "non-interactive init did not refuse setup"
        assert not vault.exists(), "non-interactive init created a vault"

    print(
        f"Installed CLI: {len(command_paths)} help paths, four completions, "
        "invalid-option rejection, and write-free non-interactive init passed."
    )


if __name__ == "__main__":
    main()
