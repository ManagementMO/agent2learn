"""Build-time release switches.

These are constants a release engineer sets deliberately, not user configuration and not
something a test may reach around. ``submit.py`` reads :data:`SUBMISSION_AVAILABLE` through
``submit.release_capability()``; tests exercise the upload path by passing an explicit
``SubmissionCapability`` instead, so the production check is never monkeypatched away.

``SUBMISSION_AVAILABLE`` stays ``False`` until a supervised, designated non-graded upload has
passed against a real instance for that exact release candidate. If the gate cannot pass, the
published build is rebuilt with the mutating path disabled and every artifact test is rerun.
"""

from __future__ import annotations

from typing import Final

SUBMISSION_AVAILABLE: Final[bool] = False

__all__ = ["SUBMISSION_AVAILABLE"]
