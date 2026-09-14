# Dependabot review

## Current combined fixes — 2026-09-14

The five open updates were re-reviewed against `25d6b3f`, not accepted from stale PR badges.
The validation-fixes branch integrates their minimal changes together so the current full matrix
tests the actual combination. The original Dependabot PRs are superseded only once those fixes
merge. The version and installer bump are held separately for a fresh 0.1.6 release; source fixes
do not alter the immutable production 0.1.5 artifact.

| Proposal | Candidate decision | Exact change |
| --- | --- | --- |
| [#1](https://github.com/ManagementMO/agent2learn/pull/1), Rich | Accept with current CI | Lock 15.0.0; widen the runtime cap to `<16`. |
| [#2](https://github.com/ManagementMO/agent2learn/pull/2), mypy | Accept with current CI | Lock 2.3.1; widen the development cap to `<3`; add development-transitive `ast-serialize` 0.8.0. |
| [#3](https://github.com/ManagementMO/agent2learn/pull/3), uv-build | Accept with artifact checks | Widen the build-backend cap to `<0.13.0`; retain the release builder at uv 0.12.13. |
| [#5](https://github.com/ManagementMO/agent2learn/pull/5), Click | Accept with current CI | Lock 8.5.0 within the existing `>=8.2,<9` range. |
| [#6](https://github.com/ManagementMO/agent2learn/pull/6), Ruff | Accept with current CI | Lock 0.16.5 within the existing `>=0.8,<1` range. |

The targeted resolution changes only those four locked versions and adds `ast-serialize`; it
retains `librt` 0.15.0 and increases the complete lock from 124 to 125 package entries. The
runtime-only release SBOM deliberately excludes development dependencies.

The older-Typer compatibility check then found a separate, pre-existing range defect: the wheel
allowed Typer 0.15.0 with Click 8.5.0, but root, init, and ground help all exited 1 with
`make_metavar` signature errors. The same installed-wheel CLI smoke fails with 0.15.0 and passes
with 0.16.0, the [upstream Click 8.2 compatibility release](https://github.com/fastapi/typer/releases/tag/0.16.0).
The candidate therefore raises only the Typer floor to `>=0.16,<1`; the lock stays at 0.27.1.
CI tests both the default installed wheel and its declared Typer floor on all three OSes, checking
all 23 help paths, four completion outputs, invalid-option rejection, and write-free headless init.
The TestPyPI promotion check also runs installed CLI, core, and skill smokes before PyPI approval.

[Rich 15's documented breaking change](https://github.com/Textualize/rich/releases/tag/v15.0.0)
is dropping Python 3.8, below this project's supported floor. The
[uv 0.12 release notes](https://github.com/astral-sh/uv/releases/tag/0.12.0) recommend the widened
backend bound without a build-configuration migration. Click and Ruff remain within existing
caps; see their [Click changes](https://click.palletsprojects.com/en/stable/changes/#version-8-5-0)
and [Ruff release notes](https://github.com/astral-sh/ruff/releases/tag/0.16.5).

The historical mypy recommendation below is not current passing evidence. The supplied PR head's
[run 33299842550](https://github.com/ManagementMO/agent2learn/actions/runs/33299842550) failed
multiple Types jobs. Current main already contains the explicit Click dependency and the
platform-safe dynamic imports those failures required. The
[mypy 2.3.1 changelog](https://github.com/python/mypy/blob/v2.3.1/CHANGELOG.md) also changes checker
defaults, so a fresh combined three-OS/Python matrix is required before merge.

Release review found Click and tzdata missing from the notices table and the checker inventory,
even though the checker reported success. Four regressions now cover completeness, a complete
synthetic inventory, and each missing row. Click, Rich, and tzdata license metadata were reviewed
directly; the checker verifies versions and completeness, not legal conclusions or license text.

Local combined-candidate evidence: 1,262 tests passed, six explicit skips, 80.86% branch-aware
coverage, clean Ruff and strict mypy, current notices, no known audited dependency vulnerabilities,
and a successful forced-PEP-517 wheel/sdist build with strict Twine metadata checks. The unreleased
Agent2Learn candidate itself is not present in PyPI's vulnerability database. Remote CI, the
historical PDF acceptance baseline, real-account acceptance, and publication remain separate gates.

## Historical recommendations — 2026-08-30

At this checkpoint these were recommendations only: no Dependabot pull request was merged and
the declared versions in `pyproject.toml` remain unchanged. The historical PR checks are useful
evidence, but they ran before the current 17-job workflow and before the repository-wide `mypy`
and coverage gates were added.

## PR #1 — Rich 14.3.4 → 15.0.0

* [Pull request #1](https://github.com/ManagementMO/agent2learn/pull/1)
* [Rich v15.0.0 release notes](https://github.com/Textualize/rich/releases/tag/v15.0.0)

Rich 15 is a major-version update, but its only listed compatibility break is dropping Python 3.8;
Agent2Learn supports Python 3.11–3.14. The release also fixes ANSI newline handling, `FileProxy`
TTY forwarding, empty-print `end` handling, and inline code in Markdown tables. The PR's platform
tests passed; its dependency-audit job failed only because `THIRD_PARTY_NOTICES.md` still recorded
Rich 14.3.4. The same job reported no known vulnerabilities before the notices check failed.

Recommendation: **hold for one small follow-up, then likely accept**. Regenerate the notices file
through its documented procedure, run the current full matrix and the console/installer smoke, and
then widen the production cap to `<16` if those checks remain green. This is a formatting/runtime
dependency, so a release candidate must still receive a fresh `pip-audit` result.

## PR #2 — mypy 1.20.2 → 2.3.1

* [Pull request #2](https://github.com/ManagementMO/agent2learn/pull/2)
* [mypy 2.3 changelog](https://raw.githubusercontent.com/python/mypy/v2.3.1/CHANGELOG.md)

mypy is a development-only tool. The 2.3 changelog describes improved free-threaded safety,
closed `TypedDict` support, Python 3.14 `TypeForm`, and crash fixes; it does not describe a runtime
change to the packaged application. The PR's platform tests passed and its dependency-audit job
also reported no known vulnerabilities before the same stale-notices failure seen in PR #1. As an
additional local compatibility probe, `uv run --with mypy==2.3.1 mypy src tests tools
--show-error-codes` completed with no issues.

Recommendation: **accept after the candidate lockfile and current CI are regenerated**. Widen the
development cap to `<3` only with a green 17-job run, because this is a major checker release and
future diagnostics can change even when the current tree is clean. It is not a production CVE fix;
the value is checker correctness and maintenance.

## PR #3 — uv-build 0.11.32 → 0.12.5

* [Pull request #3](https://github.com/ManagementMO/agent2learn/pull/3)
* [uv 0.12.5 release notes](https://github.com/astral-sh/uv/releases/tag/0.12.5)
* [uv 0.12.5 changelog](https://raw.githubusercontent.com/astral-sh/uv/0.12.5/CHANGELOG.md)

`uv-build` is used only as the PEP 517 build backend. The upstream 0.12 release notes explicitly
state that there are no breaking changes to the build-backend configuration and recommend allowing
`uv_build>=0.11.32,<0.13`; 0.12.5 additionally includes requirement-URL credential redaction and
other resolver/build fixes. The PR's complete historical CI, including dependency audit, passed.

Recommendation: **accept after a clean PEP 517 wheel/sdist build and current CI**. Widen the build
requirement to `<0.13`; do not treat this as a runtime vulnerability patch, and retain the existing
artifact metadata, license, and hash checks as the acceptance criteria.

## Security conclusion

None of the three PR checks exposed a known CVE in the candidate dependency set. That is a bounded
`pip-audit` result, not a guarantee that no vulnerability exists; rerun the audit on the exact release
candidate and keep the lockfile and notices synchronized. PR #1 is the only candidate that changes a
production dependency, so it carries the most direct user-facing compatibility risk.
