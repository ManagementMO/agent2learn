"""Smoke tests: the package imports and the console entry point is wired."""

from __future__ import annotations

import json
import re
from pathlib import Path


def test_version_is_importable() -> None:
    from agent2learn import __version__

    assert __version__


def test_cli_app_is_importable() -> None:
    """The `a2l` console script resolves to this object; a rename must fail loudly."""
    from agent2learn.cli import app

    assert app is not None


def test_detect_secrets_baseline_excludes_only_the_intended_repository_paths() -> None:
    baseline = json.loads(
        (Path(__file__).parents[1] / ".secrets.baseline").read_text(encoding="utf-8")
    )
    filters = baseline["filters_used"]
    regex_filter = next(
        item
        for item in filters
        if item["path"] == "detect_secrets.filters.regex.should_exclude_file"
    )
    pattern = re.compile(regex_filter["pattern"][0])

    for path in (
        ".venv/site.py",
        ".pytest_cache/lastfailed",
        "dist/build.whl",
        "uv.lock",
        ".git/HEAD",
    ):
        assert pattern.match(path), path
    assert not pattern.match("src/agent2learn/cli.py")
