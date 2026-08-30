# Dependabot review

Reviewed 2026-08-30. These are recommendations only: no Dependabot pull request was merged and
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
