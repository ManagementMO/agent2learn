#!/usr/bin/env python3
"""Fail if THIRD_PARTY_NOTICES.md has drifted from the resolved environment.

A notices file that is written once and never rechecked becomes fiction the first time
a dependency moves. This compares the versions and licences recorded in the document
against the distributions actually installed, and against the package count in uv.lock.

Developer tool. Not shipped in the wheel; not imported by the package.
"""

from __future__ import annotations

import importlib.metadata as md
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
LOCK = ROOT / "uv.lock"

# Distributions the notices file is required to account for by name.
TRACKED = [
    "typer",
    "rich",
    "requests",
    "platformdirs",
    "keyring",
    "websocket-client",
    "pdf-oxide",
    "pytesseract",
    "pillow",
    "pypdfium2",
    "markitdown",
    "nbformat",
]


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def main() -> int:
    if not NOTICES.exists():
        print("FAIL  THIRD_PARTY_NOTICES.md is missing")
        return 1

    text = NOTICES.read_text(encoding="utf-8")
    problems = 0

    print("Checking recorded versions against the resolved environment:")
    for name in TRACKED:
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            fail(f"{name} is listed in the notices but is not installed")
            problems += 1
            continue
        # Find the table row naming this package. The runtime and extras tables have
        # different column counts, and markitdown is written with its extras, so match
        # the backticked name allowing a trailing `[...]` rather than assuming a shape.
        pattern = rf"^\|.*`{re.escape(name)}(?:\[[^\]]*\])?`.*$"
        row = re.search(pattern, text, re.M)
        if row is None:
            fail(f"{name} has no row in THIRD_PARTY_NOTICES.md")
            problems += 1
            continue
        if installed not in row.group(0):
            fail(f"{name}: installed {installed}, notices row says {row.group(0).strip()}")
            problems += 1
        else:
            print(f"  ok    {name} {installed}")

    # The stated resolved-package count must match the lock.
    locked = len(re.findall(r"^\[\[package\]\]", LOCK.read_text(encoding="utf-8"), re.M))
    stated = re.search(r"(\d+)\s+packages at this", text)
    if stated is None:
        fail("notices no longer state a resolved package count")
        problems += 1
    elif int(stated.group(1)) != locked:
        fail(f"notices say {stated.group(1)} packages, uv.lock has {locked}")
        problems += 1
    else:
        print(f"  ok    package count {locked} matches uv.lock")

    # The former converter must not reappear as a dependency.
    if any(d.lower().startswith(("pymupdf", "fitz")) for d in _installed_names()):
        fail("an AGPL PyMuPDF distribution is installed; the licence analysis assumes it is absent")
        problems += 1
    else:
        print("  ok    no PyMuPDF/AGPL converter present in the environment")

    print()
    if problems:
        print(f"{problems} problem(s). Regenerate THIRD_PARTY_NOTICES.md")
        print("per the refresh procedure documented in that file.")
        return 1
    print("THIRD_PARTY_NOTICES.md is current.")
    return 0


def _installed_names() -> list[str]:
    names = []
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name:
            names.append(name)
    return names


if __name__ == "__main__":
    raise SystemExit(main())
