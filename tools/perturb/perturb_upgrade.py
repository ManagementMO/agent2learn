"""Prove each upgrade/release guard is load-bearing by perturbing it offline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = "tests/test_upgrade_release.py"

CASES: list[tuple[str, Path, list[tuple[str, str]], str]] = [
    (
        "network version validation",
        ROOT / "src/agent2learn/upgrade.py",
        [
            (
                "    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:\n"
                '        raise A2LError("the package index reported an unreadable version")\n'
                "    return value",
                "    return str(value)",
            )
        ],
        "test_an_unusable_pypi_answer_is_an_error_not_a_guess",
    ),
    (
        "subprocess argument validation",
        ROOT / "src/agent2learn/upgrade.py",
        [
            (
                "    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:\n"
                '        raise A2LError("refusing to install an unrecognised version string")\n'
                '    return f"{PACKAGE_NAME}=={version}"',
                '    return f"{PACKAGE_NAME}=={version}"',
            )
        ],
        "test_a_pypi_version_is_validated_before_it_becomes_a_subprocess_argument",
    ),
    (
        "network failure is not a guess",
        ROOT / "src/agent2learn/upgrade.py",
        [
            (
                "    except Exception:\n"
                "        # The exception text can name local hosts, proxies, and paths; the user "
                "needs the\n"
                "        # actionable part only.\n"
                "        raise A2LError(\n"
                '            f"could not reach {PYPI_METADATA_URL} to check for a newer version"\n'
                "        ) from None",
                "    except Exception as exc:\n        raise A2LError(str(exc)) from None",
            )
        ],
        "test_a_network_failure_is_reported_without_leaking_the_exception",
    ),
    (
        "version ordering (0.10.0 > 0.9.0)",
        ROOT / "src/agent2learn/upgrade.py",
        [
            (
                "    return _sort_key(candidate) > _sort_key(installed)",
                "    return candidate > installed",
            )
        ],
        "test_version_ordering_answers_is_this_newer",
    ),
    (
        "unknown shell usage error",
        ROOT / "src/agent2learn/cli.py",
        [
            (
                "    if shell not in shells:\n"
                '        typer.echo(f"unsupported shell: {shell}; choose one of '
                "{', '.join(shells)}\", err=True)\n"
                "        raise typer.Exit(code=2)\n",
                "",
            )
        ],
        "test_completions_reject_an_unknown_shell",
    ),
    (
        "release tag/version agreement",
        ROOT / ".github/workflows/release.yml",
        [('          tag="${GITHUB_REF_NAME#v}"', '          tag="$declared"')],
        "test_the_release_actually_refuses_a_tag_that_disagrees_with_the_version",
    ),
    (
        "release tag comparison",
        ROOT / ".github/workflows/release.yml",
        [('          if [ "$declared" != "$tag" ]; then', "          if false; then")],
        "test_the_release_actually_refuses_a_tag_that_disagrees_with_the_version",
    ),
    (
        "release builds exactly once",
        ROOT / ".github/workflows/release.yml",
        [
            (
                "      - name: Metadata must render on PyPI",
                "      - run: uv build\n      - name: Metadata must render on PyPI",
            )
        ],
        "test_the_release_builds_once_and_promotes_the_same_hashes",
    ),
    (
        "trusted publishing without tokens",
        ROOT / ".github/workflows/release.yml",
        [("          skip-existing: true", "          password: ${{ secrets.PYPI_TOKEN }}")],
        "test_publishing_uses_trusted_publishing_with_job_level_id_token",
    ),
    (
        "release actions pinned to a commit sha",
        ROOT / ".github/workflows/release.yml",
        [
            (
                "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1",
                "actions/download-artifact@v8 # v8.0.1",
            )
        ],
        "test_every_release_action_is_pinned_to_a_full_commit_sha",
    ),
    (
        "release triggers only on a tag",
        ROOT / ".github/workflows/release.yml",
        [
            (
                'on:\n  push:\n    tags: ["v*"]',
                'on:\n  push:\n    tags: ["v*"]\n  workflow_dispatch:',
            )
        ],
        "test_the_release_workflow_triggers_only_on_a_version_tag",
    ),
    (
        "submission-disabled publish guard",
        ROOT / ".github/workflows/release.yml",
        [
            (
                '          if [ "$enabled" != "False" ]; then',
                "            if false; then",
            )
        ],
        "test_the_release_refuses_to_publish_an_enabled_submission_build_by_default",
    ),
]


def main() -> int:
    originals = {path: path.read_text(encoding="utf-8") for _, path, _, _ in CASES}
    failures: list[str] = []
    try:
        for label, path, edits, selector in CASES:
            mutated = originals[path]
            missing = [old for old, _new in edits if old not in mutated]
            if missing:
                print(f"SKIP  {label}: fragment not found")
                failures.append(label)
                continue
            for old, new in edits:
                mutated = mutated.replace(old, new, 1)
            path.write_text(mutated, encoding="utf-8", newline="\n")
            try:
                result = subprocess.run(
                    ["uv", "run", "pytest", f"{TESTS}::{selector}", "-q", "--no-header"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                path.write_text(originals[path], encoding="utf-8", newline="\n")
            bit = result.returncode != 0
            print(f"{'BITES' if bit else 'SILENT'}  {label}")
            if not bit:
                failures.append(label)
    finally:
        for path, original in originals.items():
            path.write_text(original, encoding="utf-8", newline="\n")
    print()
    if failures:
        print(f"{len(failures)} gate(s) NOT proven: {failures}")
        return 1
    print(f"all {len(CASES)} upgrade/release gates proven load-bearing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
