"""Prove each submission safety guard is load-bearing.

The harness mutates one guard at a time in a temporary checkout of the current source file,
runs the named focused test, and restores the file immediately.  It is deliberately offline:
the focused suite uses only the synthetic transport and an injected submission capability.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "agent2learn" / "submit.py"
TESTS = "tests/test_submit_gate.py"

CASES: list[tuple[str, list[tuple[str, str]], str]] = [
    (
        "release capability (prepare and CLI pre-flight)",
        [
            (
                "    permission = capability or release_capability()\n"
                "    if not permission.available:\n"
                "        raise SubmissionRefused(permission.reason)\n"
                "    if cfg is not None and not cfg.submit_enabled:",
                "    if cfg is not None and not cfg.submit_enabled:",
            )
        ],
        "test_prepare_refuses_in_a_disabled_build_and_sends_nothing",
    ),
    (
        "enable-submit acknowledgement",
        [
            (
                "    if cfg is not None and not cfg.submit_enabled:\n"
                '        raise SubmissionRefused("submission is not acknowledged · '
                'run: a2l enable-submit")\n',
                "",
            )
        ],
        "test_submit_without_acknowledgement_sends_nothing",
    ),
    (
        "controlling terminal requirement",
        [
            (
                "        if not interactive:\n"
                "            raise SubmissionRefused(\n"
                '                "refusing to upload without a controlling terminal; the '
                'preview above is final"\n'
                "            )\n",
                "",
            )
        ],
        "test_a_non_interactive_process_stops_at_the_preview",
    ),
    (
        "confirmation phrase equality",
        [
            (
                "        if not isinstance(phrase, str) or phrase.strip() != preview.phrase:\n"
                '            raise SubmissionRefused("confirmation phrase did not match; '
                'nothing was uploaded")\n',
                "",
            )
        ],
        "test_a_wrong_phrase_uploads_nothing",
    ),
    (
        "one-shot code consumption",
        [
            (
                "        if preview.consumed:\n"
                '            raise SubmissionRefused("this confirmation code was already used; '
                'run submit again")\n',
                "",
            )
        ],
        "test_a_second_attempt_with_the_same_code_uploads_nothing",
    ),
    (
        "confirmation expiry",
        [
            (
                "        if _expired(preview.staged):\n"
                '            raise SubmissionRefused("this confirmation expired; '
                'run submit again")\n',
                "",
            )
        ],
        "test_an_expired_confirmation_uploads_nothing",
    ),
    (
        "group dropbox refusal",
        [
            (
                "    if target.group_submission:\n"
                "        raise SubmissionRefused(\n"
                '            f"{target.group_note} · group submission is unsupported in v0.1; '
                'submit in LEARN"\n'
                "        )\n",
                "",
            )
        ],
        "test_a_group_dropbox_is_named_then_refused_with_no_post",
    ),
    (
        "supported LE version requirement",
        [("    _require_supported_le(le_version)\n", "")],
        "test_an_unsupported_le_version_keeps_submission_disabled",
    ),
    (
        "read-back response shape boundary",
        [
            (
                "    if not isinstance(records, list):\n"
                '        raise SubmissionUnverified("read-back was not a submission list; '
                'confirm in LEARN")\n',
                "",
            )
        ],
        "test_non_list_readback_is_rejected_at_shape_boundary",
    ),
    (
        "documented EntityDropbox current-user envelope",
        [
            (
                '        if not isinstance(entity, dict) or entity.get("EntityType") != "User":\n'
                "            continue\n",
                "        if entity is None:\n"
                '            entity = {"EntityId": 99999999, "EntityType": "User"}\n',
            ),
            (
                '        submissions: object = record.get("Submissions")\n',
                '        submissions: object = record.get("Submissions") '
                'if "Submissions" in record else [record]\n',
            ),
            (
                '            submitted_by = submission.get("SubmittedBy")\n',
                '            submitted_by = submission.get("SubmittedBy") or '
                '{"Id": entity_user_id}\n',
            ),
        ],
        "test_readback_rejects_an_undocumented_flat_shape_even_when_it_matches",
    ),
    (
        "staged-bytes integrity (TOCTOU)",
        [
            (
                "            path=preview.staged.path,\n",
                "            path=Path(preview.staged.selected_display),\n",
            )
        ],
        "test_editing_the_original_after_the_preview_cannot_change_the_sent_bytes",
    ),
    (
        "control character rejection in filenames",
        [
            (
                "    if _CONTROL.search(filename):\n"
                '        raise SubmissionRefused("submission filename contains a control '
                'character")\n',
                "",
            )
        ],
        "test_a_hostile_filename_is_refused",
    ),
    (
        "staging cleanup bounds (both layers)",
        [
            (
                "        entries = sorted(paths.long_path(directory).iterdir())",
                "        entries = sorted(paths.walk(vault.state()))",
            ),
            (
                "        if entry.parent != paths.long_path(directory) or entry.is_dir():",
                "        if entry.is_dir():",
            ),
        ],
        "test_stale_staging_cleanup_never_leaves_its_own_directory",
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
    with tempfile.TemporaryDirectory(prefix="a2l-perturb-submit-"):
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
                result = _run(selector)
            finally:
                SOURCE.write_text(original, encoding="utf-8", newline="\n")
            bit = result.returncode != 0
            print(f"{'BITES' if bit else 'SILENT'}  {label}")
            if not bit:
                failures.append(label)
    SOURCE.write_text(original, encoding="utf-8", newline="\n")
    print()
    if failures:
        print(f"{len(failures)} gate(s) NOT proven: {failures}")
        return 1
    print(f"all {len(CASES)} submission gates proven load-bearing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
