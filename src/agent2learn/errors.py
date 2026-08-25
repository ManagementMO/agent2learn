"""Stable user-facing error types and process exit codes."""

from __future__ import annotations

from typing import ClassVar


class A2LError(Exception):
    """Base class for expected Agent2Learn failures."""

    exit_code: ClassVar[int] = 1


class SessionExpired(A2LError):
    """The user must re-authenticate before retrying a network operation."""

    exit_code: ClassVar[int] = 75


class NotConfigured(A2LError):
    """The requested operation needs first-run configuration."""

    exit_code: ClassVar[int] = 3


__all__ = ["A2LError", "NotConfigured", "SessionExpired"]
