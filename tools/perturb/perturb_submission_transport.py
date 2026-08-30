"""Prove the submission read-back transport remains a one-shot JSON GET.

The general D2L client correctly retries ordinary idempotent GETs. A submission read-back is
different: it is evidence for an already-attempted mutation, so a transient response or redirect
must remain an explicit ``verification_unknown`` outcome. This harness removes each one-shot
control, runs the focused offline API contract test, and restores the source immediately.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "agent2learn" / "api.py"
TESTS = "tests/test_api.py"

CASES: list[tuple[str, str, str, str]] = [
    (
        "one-shot read-back retry refusal",
        "            retries=False,\n",
        "            retries=True,\n",
        "test_get_json_once_refuses_a_transient_readback_without_retrying",
    ),
    (
        "one-shot read-back redirect refusal",
        "            follow_redirects=False,\n",
        "            follow_redirects=True,\n",
        "test_get_json_once_refuses_a_redirect_without_following_it",
    ),
]


def _run(selector: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "pytest", f"{TESTS}::{selector}", "-q", "--no-header"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    original = SOURCE.read_text(encoding="utf-8")
    failures: list[str] = []
    for label, old, new, selector in CASES:
        if old not in original:
            print(f"SKIP  {label}: fragment not found")
            failures.append(label)
            continue
        SOURCE.write_text(original.replace(old, new, 1), encoding="utf-8", newline="\n")
        try:
            result = _run(selector)
        finally:
            SOURCE.write_text(original, encoding="utf-8", newline="\n")
        bit = result.returncode != 0
        print(f"{'BITES' if bit else 'SILENT'}  {label}")
        if not bit:
            failures.append(label)

    print()
    if failures:
        print(f"{len(failures)} gate(s) NOT proven: {failures}")
        return 1
    print(f"all {len(CASES)} submission transport gates proven load-bearing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
