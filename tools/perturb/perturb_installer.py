"""Prove each installer guard is load-bearing by perturbing it offline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "install.sh"
TESTS = "tests/test_installers.py"

CASES: list[tuple[str, list[tuple[str, str]], str]] = [
    (
        "uv version floor (older uv replaced)",
        [
            (
                '        if version_at_least "$existing" "$UV_VERSION"; then\n'
                "            needs_uv=0\n"
                "        fi",
                "        needs_uv=0",
            )
        ],
        "test_an_older_uv_is_replaced_and_disclosed",
    ),
    (
        "uv reuse (newer uv not clobbered)",
        [
            (
                '        if version_at_least "$existing" "$UV_VERSION"; then\n'
                "            needs_uv=0\n"
                "        fi",
                "        :",
            )
        ],
        "test_an_equal_or_newer_uv_is_reused",
    ),
    (
        "unreadable uv version refusal",
        [
            (
                '        if [ -z "$existing" ]; then\n'
                '            fail "found uv but could not read its version from: '
                "${existing_raw:-<no output>}\n"
                "Install the tested version yourself, then rerun this installer:\n"
                '  curl -fsSL ${UV_INSTALLER} | sh"\n'
                "        fi",
                '        if [ -z "$existing" ]; then\n            existing="0.0.0"\n        fi',
            )
        ],
        "test_a_malformed_uv_version_fails_with_one_actionable_message",
    ),
    (
        "installed version verification",
        [
            (
                '        *) fail "expected agent2learn ${A2L_VERSION} but a2l reported: '
                '${reported}" ;;',
                "        *) : ;;",
            )
        ],
        "test_a_version_mismatch_after_install_is_an_error",
    ),
    (
        "terminal requirement before onboarding",
        [("    if [ -t 0 ] && [ -t 1 ]; then", "    if true; then")],
        "test_a_non_interactive_run_stops_after_verification",
    ),
    (
        "pinned agent2learn version",
        [('    uv tool install "agent2learn==${A2L_VERSION}"', "    uv tool install agent2learn")],
        "test_both_installers_pin_the_same_reviewed_versions",
    ),
]


def main() -> int:
    original = SOURCE.read_text(encoding="utf-8")
    failures: list[str] = []
    try:
        for label, edits, selector in CASES:
            mutated = original
            missing = [old for old, _new in edits if old not in mutated]
            if missing:
                print(f"SKIP  {label}: fragment not found")
                failures.append(label)
                continue
            for old, new in edits:
                mutated = mutated.replace(old, new, 1)
            SOURCE.write_text(mutated, encoding="utf-8", newline="\n")
            try:
                result = subprocess.run(
                    ["uv", "run", "pytest", f"{TESTS}::{selector}", "-q", "--no-header"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                SOURCE.write_text(original, encoding="utf-8", newline="\n")
                SOURCE.chmod(0o755)
            bit = result.returncode != 0
            print(f"{'BITES' if bit else 'SILENT'}  {label}")
            if not bit:
                failures.append(label)
    finally:
        SOURCE.write_text(original, encoding="utf-8", newline="\n")
        SOURCE.chmod(0o755)
    print()
    if failures:
        print(f"{len(failures)} gate(s) NOT proven: {failures}")
        return 1
    print(f"all {len(CASES)} installer gates proven load-bearing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
