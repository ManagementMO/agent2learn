"""A green notices gate must cover every declared runtime dependency."""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_notices", Path(__file__).parents[1] / "tools" / "check_notices.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_notices = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_notices)


def test_notices_gate_covers_all_declared_runtime_dependencies() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    names = {
        re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
        for requirement in project["project"]["dependencies"]
    }
    assert names <= set(check_notices.TRACKED)


@pytest.mark.parametrize("omitted", [None, "click", "tzdata"])
def test_notices_gate_rejects_missing_runtime_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, omitted: str | None
) -> None:
    # A controlled distribution inventory avoids depending on the runner's optional extras.
    names = (
        "typer",
        "click",
        "rich",
        "requests",
        "platformdirs",
        "keyring",
        "websocket-client",
        "pdf-oxide",
        "pytesseract",
        "pillow",
        "pypdfium2",
        "tzdata",
        "markitdown",
        "nbformat",
    )
    versions = dict.fromkeys(names, "1.0.0")
    notices = tmp_path / "THIRD_PARTY_NOTICES.md"
    notices.write_text(
        "1 packages at this baseline\n"
        + "\n".join(f"| `{name}` | 1.0.0 | MIT |" for name in names if name != omitted),
        encoding="utf-8",
        newline="\n",
    )
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "synthetic"\n', encoding="utf-8", newline="\n")
    monkeypatch.setattr(check_notices, "NOTICES", notices)
    monkeypatch.setattr(check_notices, "LOCK", lock)
    monkeypatch.setattr(check_notices.md, "version", versions.__getitem__)
    monkeypatch.setattr(check_notices.md, "distributions", lambda: [])

    assert check_notices.main() == (0 if omitted is None else 1)
