"""Smoke tests: the package imports and the console entry point is wired."""

from __future__ import annotations


def test_version_is_importable() -> None:
    from agent2learn import __version__

    assert __version__


def test_cli_app_is_importable() -> None:
    """The `a2l` console script resolves to this object; a rename must fail loudly."""
    from agent2learn.cli import app

    assert app is not None
