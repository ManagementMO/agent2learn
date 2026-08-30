# Agent2Learn — implementation context

Agent2Learn is a local-first, open-source tool for University of Waterloo students. It turns the
courses available through a student's own LEARN (D2L Brightspace) account into a durable,
revision-safe, Markdown-twinned vault that coding agents can navigate and cite. Its product promise
is inspectability: course sources remain local, citations resolve to ordinary files, missing
coverage is explicit, and lexical similarity is never presented as proof that coursework is
correct.

## Read first

These documents are authoritative, in this order:

1. [`docs/superpowers/specs/2026-08-24-agent2learn-public-release-design.md`](docs/superpowers/specs/2026-08-24-agent2learn-public-release-design.md)
   — product, safety, data, UX, and architecture contract.
2. [`docs/superpowers/plans/2026-08-24-agent2learn-public-release.md`](docs/superpowers/plans/2026-08-24-agent2learn-public-release.md)
   — executable TDD implementation sequence and definition of done.
3. [`docs/superpowers/specs/2026-08-25-algorithm-reference.md`](docs/superpowers/specs/2026-08-25-algorithm-reference.md)
   — the tokeniser, `GENERIC` stopwords, lecture ranking, download routes, and HTTP constants that
   the design spec references but does not define. **Required for Tasks 8, 10, 11, 18, and 19**; a
   cold-read audit put those tasks at 30–70% buildable without it.
4. [`docs/LAUNCH.md`](docs/LAUNCH.md) — release gates and truthful public positioning.

If prose here conflicts with the design spec, the spec wins. If implementation evidence invalidates
the spec, stop, preserve the evidence, and update the spec and plan together before changing the
architecture.

## Current state — 2026-08-30

- Public Git repository on `main`. **Not** a package release: nothing is published to PyPI.
- **Tasks 0 through 23 are complete as automated implementations. The v0.1 command surface is
  finished; what remains is manual and publication gating, not coding.** Task 9's real-browser
  same-device validation and the supervised upload test remain release gates.
  - **Tasks 18–23 landed on the `v0-1-completion` branch** (`89848b3`, `b9a2aa0`, `5de52c4`,
    `5290a8b`, `8405cbc`, `5b24796`), taking the suite from 637 to 832 passing tests.
  - **Task 18** — `ground.py` and `a2l ground`. A file becomes citable only when the manifest and
    the course content map agree it came from a LEARN source ID **and** both the archived original
    and its Markdown twin still hash to their recorded digests. Drafts, downloaded solutions,
    untracked siblings, and generated reports are therefore unreachable. Lecture ranking sorts
    `(-score, path)`, not `rglob` order, so packs are byte-identical across platforms. `--solve`
    does not exist.
  - **Task 19** — `check.py` and `a2l check`. Reuses Task 18's source set, so a claim can never
    cite the draft itself or another student-authored answer. Scores are exact integer basis
    points; `score_bp` is provably the floored rational form and a parametrised test pins it to
    `exact_score`. `possible_conflict` fires only for two allowlisted templates whose token
    sequences are otherwise identical, and a differing number never qualifies.
    **The mandated benchmark caught a real defect:** the first implementation took 19.95 s for 100
    claims over 50,000 lines against a 2 s target, because it built a `Citation` per scored line
    and used `Fraction` in the hot loop. Counting overlap off the postings lists and materialising
    only kept spans brought it to 1.77 s.
  - **Task 20** — `submit.py`, `_release.py`, `a2l enable-submit`, `a2l submit`.
    `SUBMISSION_AVAILABLE` is **False**, so this build refuses uploads; tests reach the path only
    through an injected `SubmissionCapability`, never by monkeypatching the production check. Two
    independent gates precede any POST, the exact bytes are staged before the preview so replacing
    the original cannot change what is sent, only the documented `mysubmissions` route is used with
    no fallback, a group Dropbox is named then refused, and read-back must match folder, filename,
    size, and a timestamp after confirmation or the outcome is reported as unknown. The
    confirmation code is consumed whether the POST succeeds or fails, so nothing can be retried by
    re-confirming.
  - **Task 21** — `install.sh` and `install.ps1`. One reviewed constants block pins uv 0.12.5 and
    agent2learn 0.1.0; an equal-or-newer uv is reused, an older one is replaced after disclosure,
    and an unparseable version is a hard refusal rather than a guess. Neither script accepts a
    package, index, or URL override, needs administrator rights, or writes agent or browser state.
    CI smokes both against the candidate build staged as a `UV_FIND_LINKS` source.
  - **Task 22** — public documentation, written **after** Task 23 so it describes the final command
    surface. `tests/test_docs.py` enforces the claims rather than trusting them: forbidden phrases,
    the evidence scan never described as verification, exactly three advertised install options,
    every documented command *and flag* existing, every implemented command documented, and no link
    to a file that does not exist.
  - **Task 23** — `upgrade.py`, `a2l upgrade`, `a2l completions`, and `.github/workflows/release.yml`.
    `upgrade` is the only command that contacts the network on its own behalf; a network-sourced
    version is validated against a narrow PEP 440 subset before becoming a subprocess argument, and
    no call uses a shell string. The release workflow runs only on a `v*` tag, refuses a tag that
    disagrees with the packaged version, refuses to publish a build with uploads enabled unless the
    supervised gate was recorded, builds exactly once, and promotes those same bytes through
    attestation, TestPyPI, and a protected PyPI environment using Trusted Publishing.
- **The review-remediation checkpoint is committed and pushed to `main` as `276bda3`.** A fresh
  local run on that exact tree reports 858 passing tests and 4 skipped. The exact-SHA remote
  acceptance run is [33291418755](https://github.com/ManagementMO/agent2learn/actions/runs/33291418755);
  check its final result before calling the 17-job matrix green.
- **ATTENTION: CI grew from 14 to 17 jobs** (`installer · ubuntu-latest|macos-latest|windows-latest`).
  Branch protection on `main` now requires all 17 named checks. The existing `strict: false` and
  `enforce_admins: false` settings are unchanged; the three installer contexts were added to the
  required-checks list after the release review.
- **Real CI found three Windows defects that a green macOS run could not.** Worth reading before
  trusting a local pass on this repository again:
  1. `tests/test_installers.py` was **uncollectable on Windows** (`import pty` →
     `ModuleNotFoundError: No module named 'termios'`). Pytest exited 2 during collection, so all
     five Windows matrix jobs and the Windows installer job failed and **not one installer test ran
     there**. `pty` is now imported inside the single test that needs a terminal, the bash-driven
     behaviour tests are gated on a POSIX shell, and the nine platform-independent contract tests
     run on Windows for the first time.
  2. The release guards were **not CRLF-safe**: `uv run python` returns CRLF under git-bash, so
     `declared="0.1.0\r"` never equalled `tag="0.1.0"`. Both guards failed *closed*, so it was never
     a security hole, but a correct tag would have been refused. Both command substitutions now
     strip carriage returns.
  3. Two of my own tests were **over-generalised**: they execute step scripts from `release.yml`,
     whose job is `runs-on: ubuntu-latest`, so running them under git-bash tested an environment the
     workflow never sees. They are now gated to a POSIX shell while the text assertions that pin
     each guard's decision still run everywhere.
- **Tasks 18–23 were implemented by the controller directly, without reviewer subagents**, at the
  user's instruction. Reviews are controller self-reviews plus scripted perturbation harnesses in
  `.superpowers/sdd/2026-08-24-agent2learn-public-release/`; that is weaker than an independent
  fresh-context review and is recorded as such in `progress.md`.
- **Task 20 deviated from TDD:** `submit.py` was written before its tests. Compensated with a
  12-gate perturbation harness, but recorded as a deviation rather than presented as compliance.
- **The golden vault now exists and is the repository's regression tripwire.**
  `tests/fixtures/golden_vault.json` pins 49 files by SHA-256 after one full production
  metadata → explicit outline state → download → convert → index → snapshot → audit run against the
  synthetic API.
  **Never regenerate it to make an unexplained diff green** — a changed hash is either an
  output change you can state a reason for, or a regression that was just caught.
  Regenerate deliberately with `A2L_REGENERATE_GOLDEN=1 uv run pytest tests/test_golden_vault.py`,
  then confirm the same map on all three operating systems.
  - **Task 0** — packaging, licence, safety baseline. `pyproject.toml` declares the full runtime
    stack; `uv.lock` is committed; `a2l --version` works; Apache-2.0 is proven present in the built
    wheel and sdist as a PEP 639 `License-Expression`.
  - **Task 1** — 20 synthetic fixtures (13 JSON, 3 non-JSON, 4 binary) plus an offline
    `synthetic_api` harness over `pytest-httpserver`. `tools/generate_fixtures.py --check` enforces
    byte-exact reproducibility.
  - **Task 2** — CI across Windows/macOS/Linux × Python 3.11–3.14, plus the three installer jobs,
    17 jobs total, all green. `main` is branch-protected with all 17 as required checks.
  - **Task 3** — cross-platform path naming and atomic filesystem primitives, including the
    completed-download preservation rule for failed `.part` installs and the safe-name edge cases.
  - **Task 4** — platform-correct config paths, console output, expected error taxonomy, and
    privacy-bounded logging.
  - **Task 5** — structured portable manifests, revision preservation, and transactional schema
    migrations that stage `.a2l/` state and leave the original vault untouched on callback failure.
  - **Task 6** — `School` protocol, Waterloo adapter, explicit timezone rendering, conservative
    licensed-topic policy, boundary-aware matching, and a warned generic adapter. Waterloo host
    allowlists remain empty until redacted same-device host evidence is reviewed.
  - **Task 7** — strict scoped session projection with silent keyring-to-file fallback, atomic
    protected persistence, dual-backend clearing, and no unrelated cookie attachment.
  - **Task 8** — calibrated D2L API transport with explicit timeout/redirect/egress controls,
    bounded idempotent retries, conditional streaming downloads, disk/size validation, and
    session-expiry detection; mutating redirects are never replayed, `Retry-After` covers 429/503,
    and calibration persists only discovered versions and enrolment metadata while `a2l courses`
    remains a deterministic offline view over that state.
  - **Task 9 implementation** — persistent dedicated Chrome/Edge CDP authentication, explicit
    interactive egress interception, `Storage.getCookies` filtering, authoritative `whoami`
    verification, hidden cross-platform cookie paste, and TTY-confirmed profile clearing. Live
    same-device auth on Windows, macOS, and Linux is intentionally not represented as complete
    until manually run and recorded without retaining session material.
  - **Task 10** — metadata-first, merge-not-replace course ingestion; revision-safe resumable
    downloads; excluded-host link stubs; sanitized Dropbox RichText and first-party attachments;
    opt-in pseudonymized discussions; explicit path-null fetch repair; and bounded outline
    rendering through the existing dedicated CDP connection.
  - **Task 11** — backend-isolated PDF conversion with pinned pdf-oxide, explicit external-Tesseract
    OCR gaps, named PDFium fallback, deterministic notebook/HTML/archive renderers, hash-linked
    derived metadata with threshold/page coverage, and local-twin history preservation.
  - **Task 12** — deterministic course index, provenance-checked `content_map.json`, AI-policy
    surfacing, and sync snapshots.
  - **Task 13** — `clock.py`, `audit.py`, and the golden-vault test.
    - **`clock.py` is the single wall-clock seam for anything that reaches the vault.** Vault
      writers must call `clock.now()`/`clock.stamp()`; `test_no_forbidden_calls` fails the build
      on a direct `datetime.now` outside the exempt auth/transport modules. Without one seam a
      frozen-clock test is impossible and byte parity cannot be asserted.
    - **`audit.py`** reports coverage honestly: it floors the citable percentage so a partial
      archive never rounds up to 100%, inventories links by kind without ever offering to fetch
      them, and lists assignments sharing no distinguishing term with any topic as a prompt to
      look rather than as a finding.
    - Two fixture defects surfaced only under an end-to-end run and are fixed: TOC topics carried
      no `Size`, so a full sync downloaded nothing and produced an empty vault; and the alternate
      download routes plus Course B's collection endpoints were unregistered, so the server
      answered 500 — a *transient* status the client correctly retries five times with backoff.
      Together those cost 351 s per run; a realistic fixture brings it to about 5 s. When adding a
      route, return what a real instance returns: 404 for a route that does not serve a topic, and
      200 with an empty collection for a category a course does not use.
  - **Task 14** — `a2l doctor`, and a support report that is safe to paste in public.
    - **`report()` is an allowlist, not a denylist.** It emits version, Python, OS/arch,
      install method, and per check only a known stable identifier, known status, and a fixed
      public note whose check owns the redaction. `detail` and `fix` are never emitted: they
      legitimately carry vault paths and course names. A denylist would only remove the leaks
      someone anticipated, so every check added later would become a new way to leak.
    - Redaction is two independent layers — the check redacts, and `report` re-redacts rather
      than trusting it. Each alone is sufficient, which is why proving the test bites needs
      **both** removed at once.
    - `render()` is the opposite audience and may show local paths, and always ends with
      **exactly one** next command. A diagnostic listing six actions gets none of them done.
    - Windows `LongPathsEnabled` is read but reported **informationally and never as a
      failure** — a2l prefixes its own syscalls and works regardless. Above 240 absolute
      characters the advice is a shorter vault root, not a registry edit.
    - Git tracking **fails** on session-like files, grades, discussions, or submissions and
      only **warns** on course sources; ignore rules are not a privacy or copyright
      guarantee. The index is parsed directly so `doctor` needs no `git` binary.
- **Task 15** — the four canonical Agent Skills, the consentful cross-agent installer, and
  `skills.sh.json`. The installer copies by default, supports opt-in links, records source
  hashes/version metadata, preserves unrelated and local files during managed refreshes, and
  treats copy/link mode transitions as explicit `--force` operations with rollback-safe path
  handling. Public skill documents describe staged future commands truthfully, quarantine
  untrusted course text, and preserve the exact coursework AI-policy rule. CI validates the live
  registry schema, reviewed upstream target mappings, and local Agent Skills discovery.
- **Task 16** — consentful, ordered, resumable `a2l init`. It previews and schema-checks the vault
  before writing, preserves the user's exact approved path across races, creates only minimal
  missing Obsidian state, handles skill and grade choices, supports dedicated-profile or hidden-TTY
  authentication, requires an explicit choice among multiple active terms, persists stable course
  offering IDs, completes metadata before file estimates, classifies media with the ingest path,
  and offers full/priority/later document syncing. `.a2l/init.json` resumes incomplete stages and
  every failure has one safe recovery command; non-interactive invocation performs no setup writes.
  The implementation hardening head `d90f7dc` passed [CI run 33174306467](https://github.com/ManagementMO/agent2learn/actions/runs/33174306467)
  with all 14 jobs green, including Windows 3.11–3.14.
- **Task 17** — local daily study views and privacy controls. `a2l today` uses explicit Waterloo
  timezone arithmetic for deadlines, overdue work, snapshot changes, and exam countdowns;
  `a2l diff` compares privacy-bounded snapshots with grades opt-in; `a2l calendar` emits stable-UID
  iCalendar exports; `a2l where` searches every term's structured content maps while excluding
  sensitive rows; and `a2l open` reveals only a resolved local course directory. `privacy status`
  reports redacted category state, while `privacy purge` is preview-first, exact-phrase,
  non-TTY-refusing, stale-plan-bound, symlink-safe, and allowlisted down to explicit files and
  structured records. Generated JSON rewrites are atomic, generated content is distinguishable
  from user files, and logical-deletion limits are stated in the preview.
- **Task 16.5 complete** — closes the system-level gap between completed libraries and the public
  product. `pipeline.py` is now the one metadata-first sync sequence used by `a2l sync`, `a2l init`,
  and the golden harness; it writes explicit outline/policy state, downloads by saved scope,
  converts all current local sources, refreshes indexes, writes one snapshot, and audits. Fresh
  onboarding maps actual globally detected agents to consented project-local skill paths. Doctor
  fails closed on unreadable/tracked private Git state and opens the required prefilled issue form.
  Deadlines use Waterloo local time, priority estimates share ingest's 200,000,000-byte planner,
  declined new terms are remembered without changing selection, notebook cells have deterministic
  IDs, and installed-wheel skill discovery is a matrix smoke. Final evidence: 637 passed / 4
  skipped / zero warnings locally; independent whole-branch review clean; all 14 jobs passed in
  [CI run 33226466258](https://github.com/ManagementMO/agent2learn/actions/runs/33226466258), including
  the 49-entry golden vault and installed-wheel smoke on Windows, macOS, and Linux.
- **Post-Task 14 hardening — 2026-08-26:** a repository-wide review closed the remaining
  exception-safety, report-redaction, long-path, and cross-platform edges found after the first
  green Task 14 CI run. This includes same-origin API probes, malformed-session containment,
  linked-worktree Git inspection, per-term/empty-twin/last-sync coverage, strict public report
  fields, truthful `--open` disclosure, allowlisted structured logs, canonical redirect metadata,
  bounded archive inspection, safe snapshot timestamps, scoped cookies, symlink/hard-link-safe
  download parts, no-follow link metadata, executable and temporary-file long-path probes, and
  long-path syscall boundaries across vault writers and migration staging. The regression tests
  cover the discovered failures; they do not waive Task 9 live validation or any later release
  gate.
- **Run the gates before believing a change is done:** `uv sync --frozen --all-extras --dev` then
  `uv run ruff check .`, `uv run ruff format --check src tests tools`, `uv run mypy src`, `uv run pytest -q`,
  `uv run python tools/generate_fixtures.py --check`, `uv run python tools/check_notices.py`.
- **Verify a new gate by making it fail.** Every safety check added so far was confirmed by
  perturbation — seven fixture mutations, a notices-drift injection, a deliberately-broken offline
  guard, a `datetime.now` smuggled into a vault writer, a filename budget changed from 60 to 55,
  and a CRLF forced into every generated file. Three defects in these tasks were hidden *behind a
  passing job*, so a green badge is not evidence on its own.
- Known open items, none of them coding work: Task 9's live same-device auth still needs pass/fail
  records on Windows and Linux (macOS passed 2026-08-25); the supervised non-graded upload must
  pass for the exact release candidate before `SUBMISSION_AVAILABLE` may be flipped; the README's
  walkthrough recording has not been made and is deliberately not linked; PyPI Trusted Publishing
  still needs owner-side setup, while the GitHub `testpypi` and `pypi` environments now exist with
  required owner review and administrator bypass disabled; `mypy` covers `src/` only (`tests/` and
  `tools/` have unresolved annotations); there is no coverage measurement yet; three Dependabot PRs
  propose versions past the declared caps and each needs a human decision.
- Do not publish a package, create a GitHub release, or register a production domain yet.
- **Prerequisites P1 and P2 both PASSED on 2026-08-25 (macOS).** Do not re-litigate either.
  - **P1:** a browser-harvested LEARN session authenticates a plain `requests` call on the same
    device (`whoami` 200/JSON). **Build `api.py` on `requests`.** Windows and Linux still need the
    same check before release.
  - **P2:** the documented `…/submissions/mysubmissions/` route returned 200 for a supervised
    non-graded upload and API read-back matched filename, size, and timestamp. `X-Csrf-Token` is
    required. **`mypost` is unnecessary — do not implement it.** Group submissions, closed folders,
    large files, and non-Waterloo instances remain unproven, so every submission safety control
    stays exactly as specified.
  - Live instance versions are **`lp 1.62` / `le 1.96`**, and `GET /d2l/api/versions/` is
    unauthenticated. Never hardcode versions; unauthenticated API calls return 403 `text/html`,
    which is the login-HTML shape the expiry detector must catch.

## Frozen v0.1 decisions

- Package/import name: `agent2learn`; console command: `a2l`; public project name: Agent2Learn.
- Python 3.11–3.14; `uv` for development/install; one Python engine and one canonical `skills/`
  source. No vendor plugin, MCP server, or npm runtime in v0.1.
- Licence: Apache-2.0. Use the unmodified Apache 2.0 `LICENSE`, PEP 639
  `license = "Apache-2.0"`, `license-files = ["LICENSE"]`, and no deprecated `License ::` classifier.
- PDF conversion is core: exact-pin `pdf-oxide==0.3.77`; use external Tesseract through
  `pytesseract`; keep `pypdfium2` behind `convert.ConverterBackend` as the named degraded fallback.
  pdf-oxide renders default OCR pages itself. Never invoke its built-in OCR/model-download path.
- OCR threshold: configurable, default 80 whitespace-delimited words per page. Mixed documents use
  structured pdf-oxide Markdown for healthy pages and Tesseract text for thin pages exactly once in
  source order—never append whole-document Markdown and duplicate the OCR pages.
- **The all-262-PDF acceptance run is COMPLETE. Read this before touching the converter.**
  Result at threshold 80: **96.4% of baseline words, zero failures** on either backend
  (`pdf-oxide` 397,104 words / 6,633 headings; prior baseline 412,082 / 4,745).
  This **fails the original "≥100% aggregate words" gate, and that gate was wrong.** Raw word count
  rewarded the prior backend's measured **31–46% duplicate lines** on OCR'd documents; on the eight
  worst files C/A was 52.6% by raw words but **92.0% by unique vocabulary**. Excluding one course
  whose instructor posted image-only slides, the result is **99.9% content with +59% headings**, and
  `pdf-oxide` is faster on the 213 healthy-text-layer PDFs. The residual gap is hybrid slides plus a
  whole-page OCR threshold, not extraction quality.
  **Decision: keep `pdf-oxide`. Do not revert to the prior AGPL converter on the strength of the
  96.4% number.** The earlier 105% figure came from a stratified sample that over-weighted
  image-only documents ~8× and from a harness that double-counted; both are superseded.
  **Revised Task 11 gate: zero conversion failures and ≥95% aggregate baseline words, with any
  shortfall attributed to identified documents.** Converter choice is reversible by design —
  original source bytes are archived permanently, `ConverterBackend` isolates the library, and a
  changed `tool_version` regenerates twins — so this is not a one-way door.
- Office extra: `markitdown[pptx,docx,xlsx]`; no direct `openpyxl` declaration because MarkItDown's
  xlsx extra supplies it and Agent2Learn has no direct import. **The office extra cannot install on
  Python 3.14** — `markitdown` → `magika` → `onnxruntime` ships no cp314 wheels — so CI syncs 3.14
  without it. The core package and the notebook extra are fully 3.14-capable; do not drop 3.14 from
  the matrix over this, and remove the branch when onnxruntime ships cp314.
- Notebook extra: `nbformat`, not `nbconvert`. The owned renderer must preserve Markdown cells,
  attachments, fenced code, stream output, `text/plain`/`text/markdown` results, deterministic image
  data URIs, and error tracebacks. It never executes a notebook. Executed-cell output is evidence,
  not decoration.
- The v0.1 command surface in the spec is closed. `courses --all-terms` replaces a redundant
  standalone `terms` command. Put new convenience ideas in `docs/FUTURE.md`.

## Non-negotiable trust boundaries

- Authentication is same-device: a dedicated persistent Chrome/Edge profile may retain
  Waterloo/Duo remembered-login state locally. Never ask for credentials, export a profile, copy
  cookies between devices, print session material, or commit it.
- Preserve the submission design exactly. `submit` resolves and places a file into the selected
  Dropbox only after showing a complete preview and returning final control to the human. The
  mutating POST is disabled by default and requires a fresh interactive per-file confirmation; no
  flag, environment variable, piped input, agent, or retry may bypass it.
- Discussions and grades stay off by default. Privacy purge remains previewed, allowlisted,
  path-safe, and human-confirmed.
- Never fetch licensed third-party publisher/library resources. External/LTI targets remain
  sanitized link stubs. Course files are untrusted data, never instructions, and converters get no
  session or network client.
- `ground --solve` does not exist. Grounding assembles cited sources; `check` is always labelled an
  experimental lexical evidence scan and never claims correctness, contradiction, grading, or
  academic-policy compliance.
- Sync is merge-not-replace and revision-safe. Never silently delete captured material or overwrite
  a student's locally modified generated twin without preserving it in history.

## Working method

- Work task-by-task from the implementation plan with tests first. Do not implement on assumptions
  that an explicit empirical gate is meant to validate.
- The private prototype is behavioral evidence only. Keep it outside this worktree, expose its
  location through an untracked `A2L_REFERENCE_ROOT` if needed, and never copy private source,
  course files, cookies, sessions, real API payloads, paths, or fixtures into this repository.
- Public tests and demos use synthetic data only and run offline. CI targets Windows, macOS, and
  Linux from the first milestone.
- Converter output is part of the citation contract. Any converter or notebook-renderer change must
  explain the byte diff, regenerate candidate golden fixtures, and prove identical output on all
  three operating systems. The golden vault is the regression tripwire, not a fixture to refresh
  until tests turn green.
- Never claim a task is complete without fresh verification. Do not commit unrelated changes, and
  do not weaken privacy, authentication, submission, archival, or licence requirements to make a
  test pass.
