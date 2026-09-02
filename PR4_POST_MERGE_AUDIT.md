# PR #4 post-merge audit handoff

Date: 2026-09-01 (America/Toronto)

Repository: `/Users/mo/Downloads/agent2learn`

Reviewed commits:

- Feature commit: `ccd3a879d65522b125d0805c19aa8e5f3f530f4f`
- Merge commit/current `main`: `bc62d10156bb5e0891d75a89ee2c8c1be1928163`
- First-parent review baseline: `ce16edc7e30ba7087796f23cc6e845655560b46b`
- Pull request: <https://github.com/ManagementMO/agent2learn/pull/4>
- Exact merge-SHA CI run: <https://github.com/ManagementMO/agent2learn/actions/runs/33367071748>

## Bottom line

The merge was not perfect at the time of review, but the actionable defects found here have now
been fixed in the working tree and covered by regression tests. The pre-remediation exact merge-SHA
CI run was green across all 17 jobs; the fresh post-fix local suite is also green. Automated health
is now strong, while the separately documented live-auth, supervised-upload, and publication gates
remain open.

The remediation is intentionally uncommitted and unpublished. This Markdown report remains the
complete audit trail for a later agent or reviewer.

## Continuation evidence

This report was continued on 2026-08-31 at 18:25 America/Toronto from a clean clone pinned to
`bc62d10156bb5e0891d75a89ee2c8c1be1928163`. The exact merge-SHA push run `33367071748` had
finished successfully across all 17 jobs. The additional checks below strengthen the evidence
boundary but do not change the findings or constitute fixes.

Four temporary, audit-only regression assertions were run against the clone and intentionally
removed afterward. All four failed on the current implementation in the expected way, directly
reproducing the oversized-route fallback, unknown-size priority-budget, source-less
`conversion_gap`, and detect-secrets-filter findings. No temporary test file remains in the
repository or in the clone.

## Commit topology

`bc62d10` is a normal two-parent merge of `ccd3a87` into `ce16edc`; the merge itself introduces no
additional content beyond the feature commit. Both local `main` and `origin/main` resolved to
`bc62d10156bb5e0891d75a89ee2c8c1be1928163` at audit start.

The PR changes 17 files, with 386 insertions and 63 deletions. Its three advertised behavior areas
are:

1. downloading files whose D2L metadata omits `Size`;
2. distinguishing conversion failures from source-integrity failures;
3. reporting metadata coverage gaps during `a2l init` and reusing saved sessions.

## Findings

### P1 — `FileTooLarge` is swallowed by download-route fallback — resolved

Relevant code:

- `src/agent2learn/api.py:67` introduces `FileTooLarge(DownloadError)`.
- `src/agent2learn/api.py:224` and `:238` raise it when the advertised or streamed body crosses the
  per-file ceiling.
- `src/agent2learn/ingest.py:1936-1967` catches every `DownloadError` while trying alternate routes.
- `src/agent2learn/ingest.py:618-628` expects `FileTooLarge` to escape so it can leave the topic
  `metadata_only` with `a2l fetch --allow-large <id>`.

Because `FileTooLarge` is a `DownloadError`, `_download_with_candidates()` catches it, deletes the
part, and continues trying the other candidate routes. Two bad consequences follow:

1. A source can be streamed up to the 2 GiB ceiling repeatedly on multiple routes.
2. A later 404/unusable-route error overwrites the earlier `FileTooLarge`, so the outer bulk-sync
   handler sees a generic `DownloadError`. The topic is counted as a failed download instead of an
   intentional bounded skip with the documented one-file override.

Direct reproduction run during this audit:

```text
DownloadError
fallback route unavailable
download_calls=3
```

The fake client raised `FileTooLarge` on the first/real route and `DownloadError` on later fallback
routes. The final exception was the fallback error after three network attempts.

Required correction:

- Re-raise `FileTooLarge` immediately in `_download_with_candidates()`, before the generic
  `DownloadError` catch.
- Add a red-green regression test where the first route raises `FileTooLarge` and later routes would
  return 404/unusable responses. Assert exactly one transfer attempt and the final
  `metadata_only`/`--allow-large` state.

### P1 — unknown-size files bypass the priority byte budget — resolved

Relevant code:

- `src/agent2learn/ingest.py:572-628` now admits unknown-size sources into bulk sync.
- `src/agent2learn/ingest.py:1571-1593` counts only known `remote_size` values against the priority
  budget and treats every unknown-size topic as consuming zero bytes.
- `src/agent2learn/cli.py:1905-1919` still labels the resulting selection as a `200 MB budget`.

This means `a2l sync --priority` can select an unlimited number of unknown-size files, each of which
may stream up to the 2 GiB per-file ceiling. That violates the design/plan promise that the priority
set is byte-bounded and makes the displayed 200 MB budget untrue.

Direct reproduction run during this audit:

```text
unknown_rows_selected=100 with_budget_bytes=1
```

One hundred unknown-size topics were selected under a one-byte priority budget.

Required correction:

- Define an explicit, documented priority policy for unknown sizes. Safe options include excluding
  unknown-size non-priority topics from the bounded set, reserving a conservative charge per
  unknown topic, or placing them behind a separate explicit choice. Do not silently count them as
  zero.
- Add planner, initializer-estimate, and real ingest tests proving the selected set obeys the stated
  budget policy.

### P1 — partial metadata is marked complete, then the real pipeline stops and never retries it — resolved

Relevant code:

- `src/agent2learn/cli.py:1189-1208` warns on `MetadataReport.errors` with `exit_code == 0` and then
  writes `metadata_complete=True`.
- `src/agent2learn/pipeline.py:196-218` treats any metadata error as incomplete and therefore skips
  outlines, files, and conversion.
- `src/agent2learn/pipeline.py:341-364` returns exit code 1 whenever metadata errors exist.
- `src/agent2learn/cli.py:1267-1274` turns that report into an `init ... incomplete` failure.
- `tests/test_init_flow.py` replaces the production pipeline with a fake that ignores metadata
  errors, so its new partial-metadata test cannot expose the production interaction.

Direct production-status reproduction:

```text
errors=('metadata incomplete',)
exit_code=1
```

The actual behavior is therefore:

1. print that partial metadata can continue;
2. persist `metadata_complete=True`;
3. pass the errored report into the real pipeline;
4. skip file/conversion work and exit incomplete;
5. on the next `a2l init`, skip metadata retrieval because it was marked complete;
6. reconstruct a local `MetadataReport` without the original endpoint errors, permanently losing
   the retry signal.

The new FAQ claim at `docs/FAQ.md:49-54` is consequently false: rerunning `a2l init` does not retry
the failed metadata categories. The warning that the category gaps are recorded in
`.a2l/AUDIT.md` is also unsupported: the endpoint-error tuple is returned in memory and is not
persisted as an audit input.

Required correction:

- Decide the contract explicitly: either partial endpoint failures are resumable blockers, or they
  are accepted partial success. Then make CLI state, pipeline gating, persisted error state, audit
  output, and FAQ wording agree.
- Do not set `metadata_complete=True` while retryable endpoint categories remain incomplete unless
  the exact incompleteness is durably persisted and the next sync is guaranteed to retry it.
- Replace/augment the fake-pipeline unit test with a production `run_pipeline()` interaction test.

### P1 — the full local suite fails when a real saved session exists — resolved

Relevant code:

- `src/agent2learn/cli.py:1049-1054` now calls `session_store.load()` unconditionally.
- Before this PR, loading occurred only when the current initializer state recorded
  `authenticated=True`.
- `tests/test_init_pipeline_e2e.py:55-92` isolates filesystem directories and monkeypatches
  `authenticate`, but does not isolate the keyring-backed session store.

On this machine, a real saved Waterloo session exists in the local session store. The production
E2E test uses a synthetic LEARN origin. The newly unconditional load selected the real saved session
instead of the test's synthetic authentication result, then `Client` rejected the school/session
origin mismatch during course discovery.

Fresh full-suite evidence:

```text
FAILED tests/test_init_pipeline_e2e.py::test_full_init_through_public_cli_produces_verified_twins_and_audit
1 failed, 906 passed, 4 skipped in 32.56s
```

The command output showed:

```text
signed in (saved local session)
init stopped during course discovery (ValueError).
run: a2l init
```

The coverage run reproduced the same failure. Coverage itself reached 78.64%, above the 77.5%
floor, but a coverage percentage does not make a failing suite acceptable.

CI runners are clean and therefore do not expose this environmental interaction, which explains
why the PR-head jobs passed.

Required correction:

- Scope saved-session reuse to an explicitly compatible origin/school and verify it before treating
  the user as signed in.
- Preserve the intended convenience for a valid Waterloo session without allowing unrelated or
  stale stored state to bypass the selected authentication path.
- Make every auth/init test isolate both the file backend and keyring backend. Add a regression test
  with a pre-existing session for a different origin.

### P2 — `conversion_gap` changes the durable content-map contract without updating the authorities — resolved

The PR adds a seventh availability value, `conversion_gap`, across `convert.py`, `index.py`,
`audit.py`, `check.py`, `doctor.py`, and `ingest.py`. However:

- `docs/superpowers/specs/2026-08-24-agent2learn-public-release-design.md:884-902` still defines the
  complete allowed set as only `metadata_only`, `source_only`, `markdown_ready`, `external_link`,
  `unsupported_format`, and `integrity_gap`.
- `docs/superpowers/plans/2026-08-24-agent2learn-public-release.md:1482-1489` still describes failed
  conversion as `source_only` or `unsupported_format`.
- `CONTENT_MAP_VERSION` remains `1`; there is no compatibility/migration decision.
- `AGENTS.md` says the design spec wins and architecture changes require coordinated spec and plan
  updates.

The distinction itself is sensible: intact source bytes with a failed converter should not be
called an integrity failure. The problem is introducing it as an undeclared durable schema value.

Required correction:

- Update the design spec and implementation plan together, explicitly define every state's
  invariants and next actions, and decide whether the schema/version needs to change before keeping
  this implementation.
- Add contract tests that enumerate all allowed availability values and every consumer.

### P2 — `conversion_gap` can survive after its source proof disappears — resolved

`src/agent2learn/index.py:323-365` preserves `conversion_gap` even when the manifest has no entry for
the source. The reconciled row then has `source_path=None` but continues to say, for example, that
Tesseract should be installed. The audit label says the file was fetched and conversion failed,
although no manifest-backed source remains.

Direct reproduction:

```text
{
  'availability': 'conversion_gap',
  'source_path': None,
  'path': None,
  'next_action': "install Tesseract with the 'eng' language pack, then rerun: a2l sync"
}
```

Required correction:

- Preserve `conversion_gap` only when the current manifest entry and source bytes still validate.
  Otherwise degrade to the appropriate metadata/integrity state.
- Add a test for a conversion-gap row whose manifest entry or source bytes disappear.

### P2 — the committed detect-secrets exclusion regex was accidentally corrupted — resolved

`.secrets.baseline` changed this reviewed filter:

```text
^\.venv/|^\.pytest_cache/|^dist/|^uv\.lock$|^\.git/
```

to:

```text
^/.venv/|^/.pytest_cache/|^dist/|^uv/.lock$|^/.git/
```

The new pattern fails to match `.venv/`, `.pytest_cache/`, `uv.lock`, and `.git/` relative paths.
A direct regex probe confirmed all four are false; only `dist/` still matches.

The current tracked-file `detect-secrets-hook` still exits 0, and CI's separate full-history
gitleaks scan is unaffected. This is nevertheless an unintended security-tool configuration drift
that can make direct/all-scope detect-secrets runs noisy, slow, or environment-dependent.

Required correction:

- Restore the reviewed regex exactly while retaining only the legitimate golden-hash/line-number
  baseline updates.
- Add a tiny test or verification script that compiles the baseline filter and checks the intended
  paths.

### P3 — golden-vault and authoritative status documentation is stale — resolved

The PR adds `Unsized Handout.pdf` and `Unsized Handout.md`, taking
`tests/fixtures/golden_vault.json` from 49 to 51 entries. The following still claim 49:

- `AGENTS.md:139`
- `AGENTS.md:258`
- `docs/superpowers/plans/2026-08-24-agent2learn-public-release.md:2144`

`tests/test_fixture_contract.py:145-146` also still says an unknown-length topic remains
`metadata_only` until explicit one-file fetch, contradicting the new behavior and golden test.

`AGENTS.md` current-state text ends at `9876c57` and does not record this PR, its changed contracts,
its new test count, or its exact-SHA CI status.

Required correction:

- Update the exact golden count and stale fixture comment.
- Once fixes settle and exact-SHA CI is final, add a truthful current-state entry with fresh local
  and remote evidence.

## Remediation completed — 2026-09-01

The user authorized implementation of every actionable finding. The following changes are now in
the working tree:

- `ingest._download_with_candidates()` re-raises `FileTooLarge` before generic route fallback, so
  a size refusal reaches the existing `metadata_only`/`a2l fetch --allow-large` path without trying
  another route.
- The priority planner excludes topics with unknown remote size from its hard byte-bounded set.
  Unknown-size topics remain eligible for the full plan's streaming per-file ceiling and for an
  explicit one-file fetch; they are no longer charged as zero bytes.
- `a2l init` now treats any metadata error tuple as an incomplete metadata phase, regardless of its
  numeric exit code. It stops before the file pipeline and does not persist `metadata_complete`.
  The existing resume path retries metadata while reusing a valid saved session.
- Saved sessions are accepted by init only when their normalized `base_url` matches the selected
  school origin. Synthetic init tests now carry an origin, and a different-origin saved-session
  regression proves re-authentication occurs.
- Content-map reconciliation now requires a manifest entry for every source-backed gap state. A
  source-less `unsupported_format`, `conversion_gap`, or `integrity_gap` becomes `metadata_only`
  with an `a2l fetch` action rather than retaining an unsupported conversion/integrity claim.
- The detect-secrets filter was restored to the reviewed relative-path regex. A smoke test checks
  the five intended excluded path shapes and confirms source files are not excluded.
- The submission-transport perturbation harness now gives each source mutation a fresh Python
  bytecode cache. This removes a same-second timestamp/size cache collision that could reuse the
  previous same-length mutation and make the redirect gate appear intermittently silent.
- The authoritative design spec, implementation plan, FAQ, fixture-contract comment, and
  `AGENTS.md` now describe the seven availability states, schema-version-1 additive decision,
  unknown-size behavior, metadata stop/retry behavior, and the 51-entry golden tree.

Regression coverage added or strengthened:

- oversized first-route refusal cannot fall through to a successful later route;
- unknown-size priority selection cannot exceed or evade its byte budget;
- partial metadata stops init before the pipeline and leaves state incomplete;
- saved sessions from another school are not reused;
- source-less coverage gaps reconcile to a fetchable metadata-only row; and
- the detect-secrets baseline regex matches the intended repository-relative paths; and
- the transport perturbation harness remains deterministic across repeated same-second runs.

## Verification completed after remediation

Fresh post-fix local results:

- `uv run pytest -q` — **912 passed, 4 skipped**.
- `uv run pytest --cov=agent2learn --cov-branch --cov-report=term-missing` — **912 passed, 4
  skipped**, **78.72%** total branch-aware coverage against the 77.5% configured floor.
- `uv run ruff check .` — passed.
- `uv run ruff format --check src tests tools` — passed; 88 files already formatted.
- `uv run mypy src` — passed with no issues in 35 source files.
- `uv run python tools/generate_fixtures.py --check` — 20 fixtures reproduced byte-for-byte.
- `uv run python tools/check_notices.py` — passed; recorded versions and package count match.
- `uv run detect-secrets scan --baseline .secrets.baseline` — passed.
- `git diff --check` — passed.
- `uv run pre-commit run --all-files` — all six hooks passed after staging the modified baseline
  as required by the detect-secrets hook; the baseline was then returned to the uncommitted
  working-tree state.
- All four current working-tree perturbation harnesses passed: 14 submission gates, 2 one-shot
  read-back transport gates, 6 installer gates, and 12 upgrade/release gates (34 total). The
  transport harness also passed five consecutive runs after the fresh-cache hardening.
- `uv build --force-pep517` — current wheel and sdist built; `uvx --from twine twine check --strict
  dist/*` passed. A second current build was byte-identical: wheel
  `cc6919029cb42b003993e5ad52c66525c85e7a1505ab9363ebf9e057117edb5b`, sdist
  `591b8b95f7441b959cd6ec196d95a399966aaf1a5f976cddf381db1991bba0e6`.
- The current wheel installed into a fresh Python 3.11 environment; `a2l --version`, CLI help,
  version metadata, and the Apache-2.0 `License-Expression` smoke all passed.
- `uv run pip-audit --progress-spinner off` found no known vulnerabilities; it explicitly skipped
  the unpublished local `agent2learn==0.1.0` package because it is not on PyPI. The frozen
  CycloneDX 1.5 SBOM export also completed successfully.

The golden fixture was not regenerated: it was already the committed 51-entry candidate, and the
post-fix golden test passed without changing its hashes. No package was published, no GitHub
release was created, no remote branch was pushed, and no live account/session material was
collected.

## Verification completed in the original audit

The following preserves the evidence collected before remediation; the four failures below are now
resolved and the fresh post-fix evidence is recorded above.

### Passed

- `git diff --check`
- `uv sync --frozen --all-extras --dev`
- `uv run ruff check .`
- `uv run ruff format --check src tests tools`
- `uv run mypy src tests tools`
- Focused changed-area suite covering API, ingest, convert, index, audit, check, doctor, init-flow,
  golden-vault, fixture-contract, and docs tests
- `uv run python tools/generate_fixtures.py --check` — 20 fixtures reproduced byte-for-byte
- `uv run python tools/check_notices.py`
- `uv lock --check`
- `detect-secrets-hook --baseline .secrets.baseline` over tracked files
- At that time, the source checkout remained unchanged except for this untracked report
- All six pre-commit hooks passed in an isolated clean clone:
  `detect-secrets`, `check-added-large-files`, `check-merge-conflict`, `end-of-file-fixer`,
  `trailing-whitespace`, and `mixed-line-ending`
- All four tracked perturbation harnesses passed in that clone: 14 submission gates, 2 one-shot
  read-back transport gates, 6 installer gates, and 12 upgrade/release gates (34 total)
- `uv build --force-pep517` produced the wheel and sdist; `uvx --from twine twine check --strict
  dist/*` passed
- A second local build produced byte-identical wheel and sdist artifacts. Hashes were:
  `b0f02fa045d36b44648208f29426ed205997774b66b5fe73f07ef121c0678870` for the wheel and
  `224b7ab0c099a870c55367bae5ce86cb13ef8600fc6e9cf84389ae909b667a2f` for the sdist
- The wheel installed into a fresh Python 3.11 environment outside the source tree. Installed
  `a2l --version`, help, Apache-2.0 metadata, and the four-skill no-write smoke all passed
- `uv run pip-audit --progress-spinner off` found no known vulnerabilities. It explicitly skipped
  the unpublished local `agent2learn==0.1.0` package because it is not on PyPI
- `uv export --frozen --no-dev --format cyclonedx1.5` generated the release SBOM successfully
- An isolated-clone rerun of Ruff, formatting, mypy, fixture reproducibility, and notices passed;
  the isolated-clone full pytest result was recorded below as failed for the same one test

### Failed

- `uv run pytest -q`
  - one failure: `test_full_init_through_public_cli_produces_verified_twins_and_audit`
  - the isolated-clone rerun reproduced the same failure: a pre-existing saved local session is
    selected for the synthetic origin, and course discovery stops with `ValueError`
- `uv run pytest --cov=agent2learn --cov-branch --cov-report=term-missing`
  - same one failure
  - `906 passed, 4 skipped`
  - total branch-aware coverage `78.64%`, above the floor but not a substitute for a green suite
  - a fresh isolated-clone coverage rerun reproduced the same failure and the same `78.64%` total

### Remote evidence

- PR-head run `33365951206` completed successfully across the 17 required CI jobs.
- The exact merge-SHA push run `33367071748` completed successfully on
  `bc62d10156bb5e0891d75a89ee2c8c1be1928163`; all 17 jobs passed, including Windows 3.11–3.14,
  all installer jobs, dependency/SBOM/notices, and the full-history secret scan.
- Branch protection currently lists all 17 expected contexts, with `strict: false` and admin
  enforcement disabled as previously documented.
- This remote result proves the CI workflow boundary only; it does not cover the local saved-session
  interaction or the untested behavioral combinations described above.

## Remaining release gates

No automated code fix from this audit remains open. The following release work is intentionally
outside the local remediation and still needs its own evidence:

- Live same-device authentication must still be run and recorded on Windows, macOS, and Linux.
- The exact release candidate must pass the supervised non-graded upload/read-back gate before
  `SUBMISSION_AVAILABLE` can be enabled.
- PyPI Trusted Publishing environments and TestPyPI/PyPI approvals remain publication setup work.
- The README walkthrough recording remains outstanding and deliberately unlinked.
- The remediation is uncommitted on `main`; a separate review/commit decision remains with the
  repository owner.

## Historical fix order

1. Stop `FileTooLarge` at the route-fallback boundary.
2. Define and enforce unknown-size priority-budget semantics.
3. Repair partial-metadata persistence/retry/pipeline behavior and its FAQ wording.
4. Scope saved-session reuse and isolate session backends in E2E tests.
5. Coordinate the `conversion_gap` schema/spec/plan decision and source-proof invariant.
6. Restore the detect-secrets regex.
7. Update golden count, fixture comment, coverage/current-state documentation.
8. Run perturbation and full local/remote acceptance from a clean exact SHA.

## Independent-review note

Four focused read-only subagent reviews were attempted, but three immediately failed because the
selected model was at capacity and the fourth had not returned before the handoff deadline. No
subagent result was treated as evidence. All findings above were independently reproduced by the
controller with source tracing and direct commands.
