# Agent2Learn 0.1.7 validation scope

This patch release repairs defects reproduced while using the production 0.1.5 and 0.1.6 wheels. Source, local
candidate, CI, and registry publication are separate evidence: a passing source checkout does
not prove that a released package contains the fixes. Publication must still pass the protected
one-build TestPyPI-to-PyPI workflow and exact-artifact verification.

## Release decision

On 2026-09-14, the owner approved proceeding with the current frozen private PDF baseline and
an explicitly limited, macOS-validated 0.1.7 release scope after the remaining executable checks.
This records a replacement-baseline decision, **not reproduction of the lost historical
benchmark**. Windows/Linux graphical login and the outstanding human visual/semantic comparison
remain unverified; they are not converted into passing results by this decision.

This is an early read-only archive/study release, not a claim of universal course or platform
coverage. The automated three-OS matrix remains required. No authentication, privacy, download,
submission, artifact-source, or branch-protection safeguard is relaxed for publication.

## Reproduced defects repaired

- HTML File topics could use the resource-bundle route, downloading ZIPs (including media) under
  HTML filenames. The repaired same-origin source route archives HTML itself; the existing
  archive guards remain intact. Upgrade repair preserves the old containers in private history.
- An unchanged-cache path could retain a legacy HTML ZIP. Its repair now reaches sync, direct
  fetch, reconciliation, and citation eligibility, with integrity and preservation regressions.
- Error output could suppress quiz-permission coverage, and an empty byte-bounded priority plan
  did not explain that unknown sizes prevented topic downloads.
- Empty OCR output could suggest installing a tool that had already run. Unresolved pages now
  retain an accurate gap instead of implying successful text recovery.
- Calendar exports omitted quiz uncertainty, including when there were no cached quiz events.
  Exports now carry a coverage warning; affected cached quiz dates are not presented as freshly
  confirmed. Complete-course events retain their normal status and stable identifiers.
- Calendar stdout could double carriage returns on Windows and fail to encode Unicode titles
  with a legacy text-stream encoding. Raw UTF-8 output now preserves exact CRLF bytes; both
  cross-platform stream regressions and installed-wheel checks exercise the CLI output boundary.
- Doctor could recommend a futile repeat sync for deliberately excluded links. It now separates
  informational restrictions from repairable gaps; missing or unusable local twins still receive
  actionable recovery. Redacted support reports retain their allowlisted category/status format.
- Optional D2L collections can be absent on a course or installation. HTTP 404 for assignments,
  news, quizzes, opt-in grades, or opt-in discussions is now recorded as unavailable coverage;
  independent course content still downloads, converts, indexes, and audits. Unexpected response
  shapes, authentication failures, server failures, and local integrity failures remain fatal.

These fixes do not modify the immutable 0.1.5 package or authorize access to denied resources.

## Evidence and boundaries

| Area | Evidence | Limit |
| --- | --- | --- |
| Same-machine macOS student workflow | One selected course; real quiz denial retained; accessible HTML topics and assignment prompts captured; repeated sync preserves originals/twins and stable topic IDs | One account/course, not all courses or an unaided fresh-OS install |
| Permissions and exclusions | Quiz access remains unavailable rather than a successful empty collection; external resources remain links | Does not grant quiz permission or crawl external/licensed resources |
| Navigation and evidence | Assignment title/ID lookup succeeds; cited excerpts match their local lines; private draft/report/answer canaries are not course sources | Lexical evidence is not correctness, semantic verification, or a predicted grade |
| Calendar and diagnostics | Live exports disclose quiz uncertainty; doctor retains coverage warnings and one useful next command; synthetic tests cover cached/known-empty/restored states | External calendar-client import and naturally restored live permissions are untested |
| Installed base package | Isolated macOS and persistent Docker Linux installs, installed CLI/core/skills checks, container restart, and default-disabled sensitive capabilities | Docker is not graphical Linux authentication or a full desktop reboot |
| Source regression suite | Stdout-corrected source: 1,312 passed, six explicit skips, 80.99% branch-aware coverage; independent review found an additional missing-twin case before finalization | Local tests do not replace required exact-head CI or published-wheel checks |

Windows CI has also exposed timing failures: one PowerShell fixture subprocess exceeded its
20-second bound and a separate Python 3.14 job exceeded the 30-minute job limit on a post-merge
run. Preserve these failed-run records even if an unchanged retry passes. Do not call them
application failures without a reproduced functional boundary, or hide them by skipping tests.

## Private PDF acceptance baseline

The frozen current corpus contains 262 primary PDFs and two alternate source revisions. Its
existing Markdown baselines total 495,454 whitespace-delimited words under the recorded current
harness; they do not reproduce the historical 412,082-word denominator.

The measured candidate completed all 264 converter invocations without a process/conversion
exception and preserved every input and baseline. Across 3,783 primary pages, 2,169 used native
Markdown and 1,606 used OCR; **eight pages in eight documents remained explicitly unresolved**.
The output contained 579,505 whitespace-delimited words (116.96% of the current baseline).
Markup and tokenization affect that ratio: it is a regression signal, not an accuracy score.

For this patch, acceptance uses the preserved current inputs/baselines, no conversion exceptions,
at least 95% of the current aggregate baseline words, attributed output differences, and explicit
unresolved-page counts. It does **not** require pretending the eight gaps are complete, nor does
it replace later human checks of figures, equations, layout, or meaning. Future converter changes
must rerun this frozen corpus and compare against the recorded outputs without silently
regenerating the baseline. Corpus files, source names, and private reports stay outside Git.

The full 264-file run belongs to unpublished wheel
`5d56b8de65356999f8fee8abda0033a2cb9d82bbfaf6d99fc42ad30a76fa4887`.
The later reporting-only wheel
`a197900eb221860ce61ea165af74519d5ff59567fd18a597f90a5231bc528daa`
changes calendar/CLI/doctor code; all 38 installed package files match its wheel and source,
and converter bytes plus all 30 resolved runtime distributions match the corpus-tested wheel.
Live reporting/repeat and Docker install/restart evidence at that checkpoint belongs to `a197…`,
not implicitly to the subsequent stdout correction. Its earlier local suite was 1,308 passed
with six skips; the corrected source result is recorded separately above.

The subsequent stdout-corrected local wheel
`343df19d273baac3ac238bb013c508a0f74420c53e9d1994db2a221ef5f9d233`
passed installed CLI/core/skills checks on macOS with the installer's normally selected Python
3.13.13, using only base dependencies. Its new raw-output smoke first failed against the earlier
`a197…` wheel. No Linux live, new corpus, or published-artifact result is inferred from that pass.

The protected-workflow artifact still requires its own installed-wheel checks.
Any retained corpus evidence must name the artifact binding instead of claiming a new invocation.
Release-artifact checks must independently confirm the promoted wheel's identity before
publication; public GitHub release assets and provenance are the final artifact records.

## Still not verified

- Graphical same-device Windows and Linux WatIAM/Duo login; macOS Intel live use.
- A human comparison of the selected course's visible LEARN inventory and representative rendered
  originals/twins, including figures, equations and linked resources.
- The cause of an initial generic authentication/onboarding error that did not reproduce after
  retry/resume; it is not attributed to quizzes without evidence.
- Full recovery of the eight unresolved PDF pages, external calendar-client behavior, actual
  coding-agent adherence, and a full desktop-machine restart.

Grades and discussions remain off. Submission capability remains disabled. No live upload or
permission bypass was attempted, and no private authentication state was exported or transferred.
