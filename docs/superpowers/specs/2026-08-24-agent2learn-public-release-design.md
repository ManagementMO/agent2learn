# Agent2Learn v0.1 — Public Release Design

- **Date:** 2026-08-24
- **Status:** approved for implementation
- **Target:** a new public repository, built from scratch from this specification and the private
  engine's observable behaviour
- **Audience:** a coding agent (Claude Code / Codex / Devin CLI) or a human engineer with zero
  prior context on this codebase

---

## Purpose

Ship the private `agentic-learn` system as **Agent2Learn**: a public, open-source tool that turns a
University of Waterloo student's LEARN (D2L Brightspace) courses into a local, markdown-twinned
vault that any AI agent can read, cite, and study from.

The private prototype has completed a full-term archive with a clean structural audit. Exact private
counts remain release evidence, not public fixtures or demo copy. The public release turns that
proven workflow into a supportable product for strangers on three operating systems, while adding
revision-safe archive semantics and one genuinely new experimental verb (`check`).

Three properties define the product, in priority order:

1. **It installs and runs correctly on Windows, macOS, and Linux.** Windows is a first-class target
   from the first commit, enforced by CI and alpha testing rather than treated as a later port.
2. **It is convenient without exporting trust.** This is a local personal tool whose LEARN session
   expires. Sessions are saved and resumed on the same device, syncs are incremental and
   restartable, and authentication is re-established with one command. The dedicated browser
   profile keeps Waterloo/Duo remembered-login state locally; passwords, profiles, and cookies are
   never sent to Agent2Learn or moved between devices.
3. **Everything it presents is inspectable.** Agent workflows cite `path.md:line` in the user's own
   vault. Missing local coverage is explicit, and the lexical evidence scan never upgrades
   similarity into a claim of correctness.

---

## Deliverables

A new public repository containing:

1. **`agent2learn`** — a Python package published to PyPI, exposing the `a2l` console script.
2. **Four canonical Agent Skills** (`SKILL.md` directories) installed during onboarding by
   `a2l skills install`, and independently installable from the same source through the open
   Agent Skills ecosystem.
3. **Two installers** — `install.sh` (macOS/Linux) and `install.ps1` (Windows) — each of which
   bootstraps `uv`, installs the package, repairs `PATH`, and runs `a2l init`.
4. **Documentation** — `README.md`, `SECURITY.md`, `THIRD_PARTY_NOTICES.md`, `docs/FAQ.md`,
   `docs/PORTING.md`, `docs/PRIVACY.md`, `docs/AUTHENTICATION.md`, `docs/install.md`,
   `DISCLAIMER.md`, and an `llms.txt` index so agents can read the docs correctly.
5. **CI** — GitHub Actions matrix across `windows-latest`, `macos-latest`, `ubuntu-latest`.

**Exactly one implementation and one canonical skill source.** The Python package is the only
engine. `skills/` is the only source of skill content. Onboarding installs those skills through
`a2l skills install`; users who already use an Agent Skills installer may install the same
directories directly from the repository. `skills.sh.json` may group the skills for discovery but
contains no duplicated instructions. There is no vendor plugin, no npm runtime, and no second
implementation in v0.1. Claude/Codex plugin manifests remain a v0.2 packaging question recorded in
`docs/FUTURE.md`.

---

## Naming and identity

| Thing | Value |
| --- | --- |
| Project / brand | **Agent2Learn** |
| PyPI package | `agent2learn` |
| Console script | `a2l` |
| GitHub | `ManagementMO/agent2learn` |
| Default vault | `~/agent2learn` (POSIX) · `%USERPROFILE%\agent2learn` (Windows) |
| License | **Apache-2.0** — permissive, with an express patent grant suitable for individual and institutional adoption. |

### License choice for the required PDF converter

The standard PDF stack is `pdf-oxide==0.3.77` (MIT OR Apache-2.0), `pytesseract` (Apache-2.0),
Pillow, and system Tesseract. `pypdfium2` (Apache-2.0 OR BSD-3-Clause, plus the bundled PDFium
notices) is the named degraded fallback backend. PDF conversion remains part of the normal install:
it is the substrate for navigation, citations, and the lexical evidence scan, not a feature whose
absence can be hidden behind an optional-extra warning.

The decision is evidence-based. On the completed 21-PDF stratified acceptance sample at the tuned
80-words-per-page OCR threshold, the permissive default recovered 105% of the prior baseline's word
count with no conversion failures and materially better Markdown structure. More importantly, its
Tesseract path preserved word boundaries where the prior OCR output fused tokens such as
`hypothesistesting`. Because `a2l check` and grounding depend on lexical overlap, that is a
correctness improvement, not cosmetic formatting. The full 262-PDF corpus remains a mandatory
acceptance gate has since **completed**: 96.4% of baseline words with **zero failures**, rising to
99.9% with +59% headings once one course's image-only slides are excluded. Raw word count proved a
poor metric because the prior backend duplicated 31–46% of lines on OCR'd documents; by unique
vocabulary the candidate reached 92% even on the eight worst files. The gate is therefore restated
as **zero failures and ≥95% aggregate baseline words with the shortfall attributed**, which the
candidate meets. `pdf-oxide` is retained.

Agent2Learn uses **Apache-2.0** rather than MIT because Apache 2.0 adds an express patent grant and
is the safer default for software a university or another institution may adopt. The resolved
standard stack is permissively licensed and introduces no converter-driven copyleft obligation.
`LICENSE` contains the unmodified Apache 2.0 text; `pyproject.toml` uses the PEP 639 expression
`Apache-2.0` and `license-files = ["LICENSE"]`; no deprecated `License ::` classifier is added.
`THIRD_PARTY_NOTICES.md`, the SBOM, the wheel contents, and upstream license files are reviewed for
every release. This is an engineering compliance record, not legal advice.

Converter output is part of the vault/citation contract. The v0.1 default is therefore exact-pinned
to `pdf-oxide==0.3.77`; its pre-1.0 API and output have changed in patch releases, including
`extract_text`/`to_markdown` artifact handling in 0.3.77. A converter bump is allowed only in an
Agent2Learn release that reruns the PDF acceptance corpus, explains the output diff, regenerates the
golden vault, and verifies the candidate bytes on Windows, macOS, and Linux. `uv.lock` records the
complete tested stack, without pretending that a project lockfile governs every later wheel install.

**Historical record:** an earlier design selected `AGPL-3.0-only` solely because
`pymupdf4llm` was then the required converter. The measured OCR word-fusion defect directly harmed
Agent2Learn's grounding contract; the permissive replacement matched or exceeded content recovery,
so retaining either that dependency or its project-wide copyleft consequence no longer served the
product. Downstream users may still choose that former backend if they prefer it and accept its
license, but Agent2Learn does not ship or support it in v0.1.

**"A2L" is the command you type, not the brand you market.** The bare token collides with two
established engineering terms — ASAM MCD-2 MC (`.a2l` ECU calibration files, which hold an
IANA-registered MIME type) and the ASHRAE A2L refrigerant safety class. It is also a visible riff
on the trademark of D2L Corporation, a publicly traded company (TSX: DTOL) headquartered in
Kitchener, fifteen minutes from campus, founded by a University of Waterloo engineering student.

Therefore:

- Public-facing name, repository, domain, and docs use **Agent2Learn**.
- The tagline does **not** mention D2L, Desire2Learn, or Brightspace as a foil. Describe what the
  tool does: *"Your courses, as a vault your agent can actually read."*
- `DISCLAIMER.md` states plainly that the project is not affiliated with, endorsed by, or connected
  to the University of Waterloo or D2L Corporation.

---

## Source authority and provenance

The public engine is a clean product implementation. The private repository supplies proven
behavioural evidence and D2L edge cases for these concerns:

| Concern | Reference |
| --- | --- |
| Session harvest, login detection | `.learn/agent_browser.py` — `harvest_session`, `_whoami`, `_parse_cookies` |
| Session shape and consumer API | `.learn/auth_harvest.py` — `load_session`, `cookies_dict` |
| Live API probing | `.learn/calibrate.py` |
| Bulk ingestion | `.learn/ingest.py` |
| Markdown conversion | `.learn/convert.py` |
| Index, cross-links, `content_map.json` | `.learn/index.py` |
| Structural audit | `.learn/audit.py` |
| Grounding packs | `.learn/ground.py` |
| Gated submission | `.learn/submit.py` |

**The approved public specification is authoritative.** Use the private implementation to confirm
observable inputs, outputs, and failure cases, but do not copy its coursework, sessions, fixtures,
paths, or source files into the public worktree. Public code and tests are written from first
principles with synthetic fixtures. Deliberate product changes include relative and revision-aware manifests, the
cross-platform path contract, the split of the vault from machine state, dedicated-profile CDP
authentication, metadata-first progressive sync, merge-not-replace archival semantics, schema
versioning, and a corrected, human-gated submission route.

---

## Vault contract — the product the student and agent see

The vault is intentionally boring, legible, and usable without Agent2Learn running. It mirrors each
course's discovered D2L module hierarchy rather than assuming weeks, course codes, or a particular
term. The normative shape is:

```text
<vault>/
├── README.md                         vault landing page: terms, courses, next commands
├── .obsidian/                        minimal optional config; never overwrite an existing one
├── .a2l/
│   ├── VERSION                       integer vault schema version
│   ├── manifest.json                 canonical source keys -> source/derived artifact records
│   ├── AUDIT.md                      structural coverage report
│   ├── history/<source-key-digest>/  immutable prior source/twin revisions + metadata
│   ├── snapshots/                    deterministic inputs for `a2l diff`
│   ├── submissions/                  minimal verified/unknown local upload receipts
│   └── private/                      HMAC key and category inventory; permission-restricted
└── <Term label>/
    └── <Course label>_<term code>/
        ├── INDEX.md                  navigable course map, deadlines, coverage, policy citation
        ├── content/
        │   └── <mirrored module hierarchy>/
        │       ├── <source.ext>      original first-party source bytes
        │       ├── <source.md>       adjacent, hash-linked markdown twin when available
        │       └── <topic.url.txt>   external/licensed link stub; target is never fetched
        ├── assignments/
        │   └── <assignment>/
        │       ├── README.md         instructions, dates, links, local source inventory
        │       ├── instructions.html sanitized D2L RichText representation when present
        │       ├── instructions.md   provenance-backed twin; eligible grounding source
        │       ├── <attachments>     first-party assignment attachments + twins
        │       └── GROUNDING.md      created only by `a2l ground`; regenerated provenance report
        ├── announcements/
        │   └── announcements.md      merged chronology; withdrawn items remain marked
        ├── discussions/              absent unless explicitly enabled
        └── _meta/
            ├── toc.json  assignments.json  quizzes.json  news.json
            ├── content_map.json  ai_policy.json
            └── my_grades.json        absent unless explicitly enabled
```

Rules that make this layout durable:

- `<Term label>` is derived by the school adapter; `<term code>` and the course org-unit ID remain
  in metadata. `<Course label>` prefers the official course code, then the offering name, then a
  stable `Course-<short org-unit digest>` fallback. A path assigned to a canonical course/source key
  is persisted and does not move merely because a display title changes.
- `content/` follows the complete parent/child TOC by stable topic ID. Empty modules still appear in
  `INDEX.md`; a file bound never removes metadata from the tree. Duplicate titles are disambiguated
  deterministically under the cross-platform naming contract.
- Original bytes and generated twins are adjacent because that is the simplest surface for a human
  or file-reading agent. The manifest—not filename resemblance—proves which twin belongs to which
  source revision.
- `INDEX.md`, assignment `README.md`, announcements, policy records, and `_meta/*.json` are generated
  artifacts. Their deterministic provenance is recorded. `assignments/*/instructions.{html,md}` and
  first-party attachments retain their D2L source identity separately from the generated hub, so
  grounding can cite the prompt without treating generated summaries as evidence. User-authored
  drafts are never treated as generated and are never overwritten.
- `.a2l/` is vault-scoped implementation state and may travel with the vault; machine credentials,
  calibration, logs, and the persistent browser profile never live there. Agent study/search flows
  exclude `.a2l/history`, snapshots, generated reports, and optional sensitive categories unless a
  command explicitly needs them.
- Every generated markdown twin uses stable page/source markers and UTF-8 LF text so
  `path.md:line` citations survive ordinary navigation. Conversion changes can move lines, which is
  why machine-readable reports also pin source and derived hashes.
- All remote timestamps are parsed as timezone-aware instants, stored in UTC, and rendered in the
  school adapter's IANA timezone (`America/Toronto` for Waterloo), never the machine's ambient
  locale or timezone. Sorting uses explicit normalized keys rather than locale collation. A student
  traveling or moving the vault therefore gets the same deadlines and generated bytes; `today`
  labels the displayed zone.

---

## Product scope — the v0.1 command surface

This surface is now **frozen for v0.1**. A standalone `terms` verb is intentionally absent because
`courses --all-terms` exposes the same discovery data without another command to build and support.
Any further convenience verb goes to `docs/FUTURE.md` unless implementation evidence shows that an
existing command cannot satisfy a release requirement.

```
a2l init                      first-run: vault, school, skills, auth, first sync
a2l auth [--paste] [--check]  (re-)establish the LEARN session
a2l courses [--all-terms]     list discovered enrolments without downloading course files
a2l sync [--priority|--all] [--include-media]  incremental ingest -> convert -> index -> audit
a2l fetch <topic-or-path> [--allow-large]  fetch one known remote topic whose content is not local
a2l doctor [--report] [--open]  diagnose everything; emit a redacted issue body
a2l today                     what is due, what changed, exam countdown
a2l diff [--since]            what changed since the last sync
a2l calendar [-o FILE]        export deadlines + exams + office hours as .ics
a2l where <query>             fuzzy-find any topic across every course
a2l open <course>             reveal a course folder in the OS file manager
a2l privacy status            show enabled sensitive categories and local storage locations
a2l privacy purge <category>  preview + remove grades, discussions, or logs after confirmation
a2l ground <course> <item>    assemble a cited grounding pack
a2l check <file>              experimental evidence scan against class material
a2l skills install [--force]  install/refresh agent skills
a2l upgrade                   upgrade engine and skills together
a2l enable-submit             one-time acknowledgement; never sufficient to upload by itself
a2l submit <course> <item> <file>  resolve + preview; a human confirms the final POST in a TTY
```

**Explicitly absent from the public build:** `ground --solve`. The tool assembles sources and runs
an experimental lexical evidence scan over drafts; it neither verifies them nor generates graded
answers on the user's behalf from a single command.

---

## Cross-platform contract

This section is normative. Every requirement here is enforced by a test that runs on all three
operating systems in CI.

### C1. Path safety

A single module, `agent2learn/paths.py`, owns every filesystem-name decision. No other module may
call `os.chmod`, construct paths by string concatenation, or sanitise a name itself.

**`safe_name(name, *, maxlen=None) -> str`** must, in this order:

1. **Normalise to Unicode NFC.** APFS is normalisation-insensitive and macOS has historically
   stored NFD; Linux and Windows preserve whatever bytes they are given. Without an explicit
   normalisation step, a course file named `Café.pdf` produces different bytes in
   `content_map.json` on macOS than on Linux, and the vault stops being portable. NFC on every
   platform, always.
2. Replace the Win32-reserved characters `< > : " / \ | ? *` with `_`.
3. Replace every Unicode `Cc` control character and `Cf` format character with `_`, including
   `U+0000`–`U+001F`, `DEL`, the C1 controls, zero-width spaces, and joiners (the reference only
   handles `\r \n \t`). Format characters become visible underscores rather than disappearing, so
   invisible differences cannot create filenames that look identical.
4. Collapse runs of whitespace to a single space.
5. Strip leading whitespace and **trailing** dots and spaces. Leading whitespace has no useful
   vault meaning and can hide a reserved device name; Win32 silently discards trailing dots and
   spaces, so a name ending in `.` or ` ` produces a disk path that does not match what was
   recorded — a manifest/disk divergence.
6. If the result is empty, use `untitled`.
7. Truncate to a positive `maxlen`, defaulting to **60 on every platform** (see C2). Preserve a
   final simple extension matching `.[A-Za-z0-9]{1,15}` when the budget can retain at least one
   basename character; otherwise treat the whole component as a name. Converter dispatch still
   uses trusted source metadata and content inspection, never the extension alone. A universal
   budget is intentionally conservative: the same remote title must map to the same local name on
   Windows, macOS, and Linux.
8. Strip trailing dots and spaces again, because truncation can expose them. If that empties the
   result, use `untitled` truncated to the same positive budget.
9. Finally, suffix an underscore if the stem, case-insensitively and ignoring any extension,
   matches a reserved device name. **The set is exactly what Microsoft documents** — no more, no
   less:

   ```
   CON  PRN  AUX  NUL  CONIN$  CONOUT$
   COM1 … COM9   COM¹ COM² COM³
   LPT1 … LPT9   LPT¹ LPT² LPT³
   ```

   Three corrections to the naïve version of this list, all load-bearing:
   - **`COM0` and `LPT0` are *not* reserved.** They are valid Windows filenames. Rejecting them is
     a false positive that mangles a legitimate name.
   - **`CONIN$` and `CONOUT$` *are* reserved** and are commonly omitted.
   - **The ISO/IEC 8859-1 superscript digits `¹ ² ³` count as digits in device names.** Windows
     treats `COM¹` as a device; `echo test > COM¹` fails. A superscript is entirely plausible in
     course material.

   An extension does not rescue a reserved name: `NUL.txt` and `NUL.tar.gz` are both `NUL`.
   This check deliberately occurs **after truncation**, so a long name shortened to a device name
   cannot slip through. Insert the underscore immediately after the reserved stem and retain the
   length budget by dropping rightmost remainder or extension characters first. If the reserved
   stem alone fills the budget, replace its final character with `_`. The final result must be
   non-empty, no longer than `maxlen`, and non-reserved.

These rules apply on **all** platforms, not only Windows. A vault synced on Linux and a vault synced
on Windows from the same course must be byte-identical in structure, so that `content_map.json` is
portable and a vault can move between machines.

**`long_path(p: Path) -> Path`** returns `p` unchanged off Windows. On Windows it returns the
`\\?\`-prefixed form when the normalized absolute path exceeds 240 characters. The normalization
is lexical and does **not** follow symlinks or junctions: the named filesystem object must remain
the object a later no-follow check or atomic replacement addresses.

The `\\?\` prefix is sharp-edged and pathlib handles it imperfectly. The contract is therefore
strict:

- **Paths inside the codebase are always plain.** `long_path()` is called *inline, at the syscall
  boundary*, and its result is never stored, returned, joined, or compared.
- **Never join onto a prefixed path.** `Path(r"\\?\foo", r"\\?\bar")` silently evaluates to
  `\\?\bar` — a known pathlib behaviour, not a hypothetical.
- **A prefixed path cannot contain forward slashes, `.`, or `..`.** The prefix bypasses Win32 path
  normalisation and hands the string to the filesystem driver directly.
- **An existing `\\?\` prefix is checked before normalization**, because high-level path
  normalization may mishandle it. `long_path()` must never resolve through a symlink merely to
  measure a target path; link identity checks use no-follow metadata operations at the same
  syscall boundary.

**`collides(dest: Path) -> bool`** performs an **NFC-normalized, case-folded** existence check on
every platform. Windows is case-insensitive; macOS APFS is case-insensitive *by default but can be
configured case-sensitive*; Linux is case-sensitive. Because the platform cannot be trusted either
way, normalize the comparison ourselves everywhere. Using `Path.exists()` directly means the same
course yields different filenames on different machines. Collisions resolve with the `_2`, `_3`
suffix scheme, trimming the pre-extension basename as needed so the final component still fits the
universal 60-character budget.

Collision allocation must also be independent of API response order. When a batch introduces two
or more new identities into one directory, sort them by canonical source key before assigning local
names; once assigned, persist and reuse each path even if its title or later response ordering
changes. A reversed first-sync fixture must produce the same path-to-source mapping.

### C2. Path length budget

The default vault root is short and every component uses the universal 60-character ceiling, which
keeps normal course trees comfortably below legacy Win32 limits without changing their shape by
platform. Arbitrarily deep D2L module trees or a user-chosen long root can still exceed 260
characters; a per-component limit cannot honestly guarantee otherwise. Agent2Learn therefore uses
`long_path()` at every filesystem syscall boundary and never relies on the Windows registry setting
for its own correctness. UNC paths receive the proper `\\?\UNC\server\share\…` form rather than
the local-drive prefix.

`a2l doctor` reads
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`. If it is `0` or absent, doctor
reports it as informational — never as a failure — and states that Agent2Learn's own I/O handles
long paths via the `\\?\` prefix. Doctor also reports the longest vault-relative and absolute paths.
If an existing absolute path exceeds 240 characters, it warns that third-party tools such as editors
or sync clients may still fail and suggests a shorter vault root; it never asks the student to edit
the registry as the primary fix.

### C3. Directory locations

Use `platformdirs` with `appname="agent2learn"`, `appauthor=False` (avoiding the doubled
`AppData\Local\agent2learn\agent2learn` that the default produces on Windows).

| Purpose | API | Windows | macOS | Linux |
| --- | --- | --- | --- | --- |
| Config | `user_config_path` | `%LOCALAPPDATA%\agent2learn` | `~/Library/Application Support/agent2learn` | `~/.config/agent2learn` |
| Machine state (calibration, session fallback) | `user_state_path` | `%LOCALAPPDATA%\agent2learn` | `~/Library/Application Support/agent2learn` | `~/.local/state/agent2learn` |
| Cache | `user_cache_path` | `%LOCALAPPDATA%\agent2learn\Cache` | `~/Library/Caches/agent2learn` | `~/.cache/agent2learn` |
| Data (browser profile) | `user_data_path` | `%LOCALAPPDATA%\agent2learn` | `~/Library/Application Support/agent2learn` | `~/.local/share/agent2learn` |
| Logs | `user_log_path` | `%LOCALAPPDATA%\agent2learn\Logs` | `~/Library/Logs/agent2learn` | `~/.local/state/agent2learn/log` |
| Vault | user-chosen | `%USERPROFILE%\agent2learn` | `~/agent2learn` | `~/agent2learn` |

The vault holds only course content and a `.a2l/` directory containing vault-scoped state. Machine
state never lives in the vault; vault state never lives in the config dir.

### C4. Manifest paths are relative

The reference `manifest.json` stores absolute paths, which makes a vault non-portable and breaks
`_seen()` when the vault moves. The public manifest stores **vault-relative POSIX paths**
(forward slashes, on every platform) and resolves them against the configured vault root at load.

### C5. No symlinks required

`a2l skills install` **copies** by default on all platforms. Windows symlinks need Developer Mode
or elevation. `--link` is available as an opt-in for users who want one canonical copy.

### C6. Permissions

`os.chmod(0o600)` is a no-op on Windows. The session file is written with `0600` on POSIX and, on
Windows, is placed in `%LOCALAPPDATA%` (already per-user ACL'd). No code path may assume `chmod`
succeeded, and no code path may fail because it did not.

### C6b. Atomic replacement must tolerate transient Windows failures

Every state file — `session.json`, `config.json`, `manifest.json`, `calibration.json` — is written
to a unique sibling temporary file and installed with replacement semantics. A successful
`os.replace` is atomic for the same filesystem, but on Windows the operation can fail transiently
when another process holds the destination open; treating that as a permanent write failure will
surface intermittently in production.

On Windows `os.replace` calls `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, and *"existing opens
of the destination path are not allowed, even if they share delete access."* The failure is
`PermissionError: [WinError 5] Access is denied`. The common real-world cause is not another copy
of the program — it is **antivirus and content-indexing services transiently opening the file**, a
scenario Microsoft's own guidance calls out: *"it might just happen that an antivirus or content
indexing application randomly scans the whole file system… Rename can fail if the old file already
exists, and someone has an open handle on it."*

`manifest.json` is rewritten after every course during a long sync, so exposure is high and the
resulting bug reports would be intermittent and baffling.

Therefore `paths.py` provides the sanctioned atomic primitives:

```python
def atomic_write_text(dest: Path, text: str, *, retries: int = 5) -> None
def atomic_write_bytes(dest: Path, data: bytes, *, retries: int = 5) -> None
def atomic_install_temp(dest: Path, temp: Path, *, retries: int = 5) -> None
```

Text and byte helpers write to a unique sibling temporary file; downloads stream to a unique
`.part` and call `atomic_install_temp`. Each path is flushed and fsynced, permissions are tightened
on POSIX only, and `os.replace` is **retried on `PermissionError` with short exponential backoff**
before giving up. Generated text/byte temporaries are cleaned on every failure path. A completed
downloaded `.part` is deliberately retained when only its fsync or atomic installation fails, so
a later sync can retry installation without re-downloading it. No module may call `os.replace`
directly.

### C7. Encoding and line endings

Every **text** read and write passes `encoding="utf-8"` explicitly — Windows still defaults to the
ANSI code page in some configurations. Binary sources are always opened in binary mode. Every
generated markdown file is written with `newline="\n"`.
`.gitattributes` marks generated markdown as `text eol=lf`.

Generated JSON uses one canonical serializer: UTF-8 output from
`json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))` plus
exactly one trailing LF. Lists
whose source order has no documented meaning are sorted by canonical stable key; chronological and
TOC lists preserve their explicit semantic order with stable-ID tie-breakers. No output depends on
filesystem enumeration order, locale collation, hash randomization, or wall-clock access outside an
injected UTC clock.

### C8. Console output

Emoji and box-drawing characters degrade on legacy Windows consoles. The CLI detects whether the
stream supports UTF-8 and falls back to an ASCII glyph set (`[ok] [!] [x]`). Colour is disabled
when not a TTY, when `NO_COLOR` is set, or when the terminal does not support it.

---

## Install contract

There is no single command that installs this on all three operating systems; `uv` itself ships a
platform-split installer. The README presents a platform tab. This is the complete, supported set
of install paths — deliberately small, to keep maintenance and documentation consistent:

```bash
# macOS / Linux
curl -LsSf https://agent2learn.dev/install.sh | sh
```

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://agent2learn.dev/install.ps1 | iex"
```

```bash
# already have uv
uv tool install agent2learn && a2l init
```

Both installers perform the same five steps:

1. Detect `uv` and parse `uv --version`. Reuse an existing version at or above the script's tested
   minimum; never downgrade a newer installation. If absent or older, disclose the replacement and
   install the release-pinned bootstrap version by delegating to
   `https://astral.sh/uv/<uv-version>/install.{sh,ps1}`. v0.1 planning pins/tests uv `0.12.5` as the
   minimum and bootstrap version; release review may update both scripts together after installer
   smoke tests. Do not reimplement uv's installer and do not use the mutable latest-version URL.
2. Install the exact release embedded in the installer with
   `uv tool install "agent2learn==<version>"`.
3. Run `uv tool update-shell`, then obtain the actual executable directory from
   `uv tool dir --bin` and prepend it to the current process's `PATH`. Do not assume
   `~/.local/bin`. On Windows, uv itself updates the user registry and broadcasts
   `WM_SETTINGCHANGE`; the installer must not duplicate that Win32 logic. Already-open unrelated
   processes may still need to restart because they inherited an older environment.
4. Verify `a2l --version` executes.
5. In an interactive terminal, continue directly to `a2l init`. In a non-interactive shell,
   install and verify only, then print `run in a terminal: a2l init`.

Both installers must be idempotent, must preview the network, package, PATH, and onboarding actions,
and must exit non-zero with a readable message on failure. Neither may require administrator
privileges. Release automation updates the embedded version and tests the installers against the
exact candidate wheel before publication.
Running onboarding immediately is intentional: the advertised install command is the product's
guided setup flow, not a package-manager primitive. Before opening a browser or writing into an
agent directory, `a2l init` prints what it is about to do and obtains interactive consent. A
non-interactive shell installs and verifies the command, prints `run: a2l init`, and exits without
opening a browser.

**The CLI owns onboarding; the repository remains standards-installable.** `a2l skills install`
keeps the critical path on a single runtime, asks before writing, writes only to approved agent
directories, and can refresh stale copies on upgrade. Project-local installation into the
configured vault root is the onboarding default; it never treats the installer's arbitrary current
working directory as the project. Global installation is an explicit choice. The same canonical
`skills/` directories may also be installed directly with an Agent Skills-compatible installer.
Detected CLI targets, reviewed against the upstream `skills` registry for each release:

| Agent | Project | Global |
| --- | --- | --- |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.agents/skills/` | `~/.codex/skills/` |
| Cursor | `.agents/skills/` | `~/.cursor/skills/` |
| Universal Agent Skills target | `.agents/skills/` | `~/.config/agents/skills/` |

Shared project paths are written once even when several detected agents consume them. Standalone
`a2l skills install --project PATH` defaults `PATH` to the configured vault and requires an explicit
path if no vault is configured. It never creates marker directories merely to make agent detection
succeed.

`skills.sh.json` groups the four canonical skills for discovery. It does not contain skill text,
run code, install the Python engine, or introduce a second release version. The README presents
`a2l init` as the normal end-to-end path and the standards-based skill command as an alternative for
users who already manage skills that way.

---

## Authentication

Auth is the highest-churn moment in the product. Expiry is a **state**, never an error.

**Authentication paths, in order:**

1. **CDP against an already-installed Chrome or Edge, using a dedicated persistent profile.** No
   browser download. The user completes WatIAM and Duo in a real window. See the constraints below —
   the profile choice is mandatory, not hygiene.
2. **`a2l auth --paste`** — a documented, always-available manual path: open DevTools, copy
   `d2lSessionVal` and `d2lSecureSessionVal`, paste them in. This exists so that no user can ever
   reach a dead end. It is documented in the FAQ as a first-class option, not a workaround.

The paste flow accepts secrets only from a controlling TTY through a cross-platform hidden
multi-line reader. There is no cookie command-line argument, environment variable, ordinary piped
stdin path, log echo, or shell-history exposure. Parsers may recognize a cookie-header line,
DevTools table, or compact JSON export, but they discard every non-allowlisted domain/name before
constructing `Session`. After success, remind the student that the operating-system clipboard may
still contain session material and should be cleared; Agent2Learn does not inspect or mutate the
clipboard behind their back.

### CDP constraints — these are hard requirements, not preferences

**Chrome 136 and later ignore `--remote-debugging-port` and `--remote-debugging-pipe` when the
target is the default user-data directory.** Chrome now demands a non-standard `--user-data-dir`,
because a non-default directory uses a different encryption key — the change was made after
attackers began abusing the debugging port to exfiltrate cookies. Edge, being Chromium, inherits
this. Consequences:

1. **A dedicated `--user-data-dir` is mandatory.** Attaching to the student's everyday Chrome
   profile is not merely bad hygiene; on any current browser it simply does not work — nothing
   listens on the port and the only symptom is a missing `DevToolsActivePort` file.
2. **That profile must be persistent, and it must NOT live in the cache directory.** It holds the
   Duo "remember this device" trust cookie, which is what makes re-authentication a WatIAM-only
   step for thirty days instead of a full Duo dance every time. Caches are disposable by
   definition. Store it under `user_data_path() / "browser-profile"`.
3. **A fresh profile means the first sign-in is a full WatIAM + Duo.** This is expected and correct:
   the user signs in inside the Agent2Learn profile once, and the trust cookie persists there. Do
   not attempt to copy or read the student's real profile.
4. **Bind the listener to `127.0.0.1`**, use `--remote-debugging-port=0`, and discover the assigned
   port by reading the `DevToolsActivePort` file that Chrome writes into the user-data directory.
   Never hard-code 9222; never bind to a public interface.
5. Pass `--no-first-run --no-default-browser-check` so the profile does not open onboarding tabs.

Profile/process ownership is conservative. If Agent2Learn launched the dedicated browser, it closes
only that browser through CDP after session harvest and waits for profile data to flush. If the
profile is already open with a valid loopback DevTools endpoint, it may reconnect after validating
the endpoint and browser identity. A stale `DevToolsActivePort`, a profile lock without a reachable
debug endpoint, or an in-use profile during `--clear-profile` produces one actionable message;
Agent2Learn never kills a browser process, deletes lock files, or touches an everyday profile.

The dedicated profile is intentionally persistent. It retains the Waterloo SSO and Duo trust state
needed to make future authentication convenient. Agent2Learn never copies that profile, its cookies,
or the exported API session to another machine. The profile remains in the per-user application data
directory and is removed only by an explicit `a2l auth --clear-profile` or uninstall action that
names exactly what will be deleted.

**Read cookies with `Storage.getCookies`, not `Network.getAllCookies`.** The latter is deprecated in
the DevTools Protocol in favour of the former, and Chromium has already blocked extensions from
calling it. Both return the HttpOnly `d2lSessionVal`, which `document.cookie` cannot see — that is
the whole reason CDP is required rather than an in-page script.

**Login detection is authoritative, not heuristic.** Port the reference behaviour exactly: run an
in-page authenticated `fetch` of `/d2l/api/lp/{version}/users/whoami` across several API versions
and gate `logged_in` on the result. A present-but-expired `d2lSessionVal` must not read as logged
in. If `whoami` succeeds but no session cookie was harvested, raise rather than persist an
inconsistent session.

**Cookie scope.** CDP can return every cookie in the dedicated profile. Persist only the minimum
verified API-session cookies whose domain belongs to the configured Waterloo Learn host. Duo and
identity-provider trust cookies remain inside the browser profile; they are never
copied into `session.json`. A named test inserts unrelated cookies and proves that none enters the
exported API session.

**Authentication egress is explicit.** Reaching LEARN can redirect the dedicated browser through
WatIAM/Microsoft identity and Duo. The Waterloo adapter therefore declares a reviewed
`auth_hosts()` allowlist separately from `outline_hosts()`. CDP request interception permits the
configured LEARN origin plus those exact/boundary-matched authentication hosts only during the
interactive auth phase; it never learns new hosts from a redirect automatically. An undeclared
document or iframe stops navigation and shows only the sanitized hostname and `a2l auth --paste`
fallback. An undeclared optional subresource is failed locally, never continued, so analytics and
other incidental page requests cannot terminate an otherwise valid sign-in; if the sign-in needs
that request, the authoritative whoami check still fails and no session is saved. The list is
derived from same-device release validation and reviewed when Waterloo changes its login flow.
Cookies from those identity hosts remain solely inside the dedicated browser profile.

**Storage.** The standard install includes `keyring` and tries the OS credential store first —
macOS Keychain and Windows Credential Manager work with no user setup. On Linux, a usable backend
usually requires SecretService and may be unavailable on headless systems or WSL. Backend discovery
or use can also fail at runtime. Any unavailable or failing backend falls back **silently** to a
`0600` file in the machine-state directory (with the existing per-user ACL on Windows). A Linux or
WSL user must never see a D-Bus traceback. `a2l doctor` always reports which storage backend is
active without revealing values and labels the fallback accurately as permission-restricted, not
encrypted. Never store a password; only the minimum Learn session cookies and XSRF token required
by the API.

**Expiry handling.** Every network-touching command detects a login-HTML response and exits with
**code `75`** and exactly one line: `session expired · run: a2l auth`. Every long operation is
resumable, so re-authenticating and re-running never loses work.

> `75` is `EX_TEMPFAIL` in `sysexits.h`: *"temporary failure, indicating something that is not
> really an error… the request should be reattempted later."* That is precisely session expiry.
> `77` (`EX_NOPERM`) was the first instinct, but it means a durable permissions problem and would
> tell a wrapping script to give up rather than re-auth and retry.

**Politeness.** Default concurrent downloads drop from 4 to **2**, with jittered start and the
reference 429 back-off. Several hundred students syncing the night before a deadline must not
present as an attack.

Every HTTP operation has explicit connect/read timeouts. Idempotent GETs retry only bounded 429 and
transient 5xx failures, honoring a capped `Retry-After`; mutating requests never retry or silently
replay their body. The transport treats the method itself as mutating even when a caller omits the
hint, and refuses a 301/302/303/307/308 redirect for such a request so the caller must make the
follow-up decision explicitly. Non-mutating requests may follow only an allowed same-origin
redirect one hop at a time. Downloads stream
with actual-byte accounting, verify advertised size when present, and stop before consuming the
configured reserve of free disk. The default single-file ceiling is 2 GiB. Oversized or unknown-length
files that cross the ceiling remain `metadata_only` with a clear reason and an exact
`a2l fetch --allow-large <id>` action; an unknown length is streamed through the same ceiling rather
than treated as zero bytes. That one-file override shows the current free space and asks for
interactive confirmation before transferring further bytes. Limits are safety controls, not claims
that a file is malicious.

---

## Safety, integrity, and privacy

### Never fetch licensed third-party content

The University of Waterloo Libraries' electronic-resources guidelines prohibit *"systematic or
large-scale downloading"* and *"automated downloading using robots or intelligent agents"*. That
rule governs **licensed publisher and library e-resources** — journal PDFs, e-reserves,
eTextbooks — not an instructor's own uploaded slides.

Automatic fetching is constrained by an **egress allowlist**, not just a growing blocklist. Normal
API/file requests may target only the configured LEARN origin; separately rendered outlines may
target only first-party hosts explicitly declared by the school adapter. During interactive auth,
only the separately declared identity-provider hosts described above are additionally allowed.
External topic URLs are always link stubs. HTTP redirects are handled one hop at a time and stop
before any unapproved origin. CDP interception applies the same rule to top-level and subresource
requests during outline rendering; if blocking an undeclared dependency prevents a trustworthy
render, record `outline_unavailable` rather than broadening the allowlist at runtime.

Each `School` adapter also declares a structured `topic_exclusion_policy()` with excluded topic
kinds, normalized host suffixes, and URL markers. For Waterloo this covers LTI topics plus
`quicklink.d2l` and VitalSource targets. Host matching is boundary-aware after URL parsing, not an
unstructured substring check. Named tests cover direct URLs, redirects, mixed case, and lookalike
hosts. The README states this exact boundary: the tool prevents automatic third-party fetching; it
does not claim that a finite provider list can classify every future link perfectly.

Persisted metadata is a typed projection, never a raw API-response dump. Malformed JSON, an invalid
root shape, an invalid stable-ID row, or a malformed nested collection is a surfaced category gap,
never an empty successful response. URL fields are normalized
to the minimum first-party route needed by the product. External URL credentials, fragments, query
strings, LTI launch data, and transient signed values are discarded after in-memory policy
classification. This keeps a local archive or accidental screenshot from becoming a token archive.

### Treat every course file as untrusted content

The student's permission to download a file is not evidence that the file is safe to execute.
Agent2Learn separates archival bytes from conversion and follows these rules:

- Never execute notebook cells, Office macros, scripts, binaries, embedded PDF actions, or commands
  found in course material. Agent skills inherit the same rule; studying a code sample is not
  authorization to run it.
- Treat all source text and generated twins as **untrusted data, never agent instructions**. A PDF,
  announcement, HTML page, notebook, or discussion may contain text such as “ignore previous
  instructions,” request secrets, or tell an agent to run a command. Skills quote/cite that text as
  course material and do not obey it, reveal secrets, change configuration, contact a URL, or invoke
  tools because the source asked. Only the user's current request and host-agent policy authorize
  actions.
- HTML/RichText conversion is parser-only and network-disabled. Strip scripts, styles, forms,
  iframes, objects, embeds, event-handler attributes, active URL schemes, remote-image loads, URL
  credentials, fragments, and unapproved query strings from generated HTML/markdown. Assignment
  `instructions.html` is a sanitized source representation, not a byte-for-byte active page; its
  manifest record retains source identity and the canonical-input hash.
- Archives are inspected only in a private temporary directory. Reject absolute paths, `..`
  traversal, links, device names, encrypted members, excessive member count, excessive total
  uncompressed size, and suspicious compression ratios before extraction. Clean up on every exit.
- Type dispatch combines server metadata, magic-byte/content inspection, and extension; an
  extension alone is never trusted. A mismatch becomes an audit warning or conversion gap.
- Originals remain available as inert archive files, but `a2l open` reveals directories only and
  never launches a downloaded source. Generated markdown may link locally to the original; it does
  not auto-open or auto-fetch anything.
- Conversion runs with no inherited session cookies or network client. Parsing failures are scoped
  to one file, recorded, and cannot corrupt the current source revision or abort the rest of sync.

Security tests cover malicious HTML, zip-slip, zip bombs, notebook execution metadata, mislabeled
types, prompt-injection text, and converter attempts to access the network or spawn a process.

### Conversion is a versioned evidence boundary

PDF conversion is hidden behind a small `convert.ConverterBackend` protocol rather than spread
through the sync pipeline. A backend exposes its name and version and accepts one local source plus
the configured OCR word threshold; it returns deterministic page-ordered Markdown and structured
coverage diagnostics. The v0.1 implementations are:

- **`PdfOxideBackend` (default):** `pdf-oxide==0.3.77` performs text/structure extraction and renders
  pages for OCR. For every page, call `extract_text_auto(page_index)` as the probe. A page with
  fewer than the configurable threshold (default **80 whitespace-delimited words per page**, the
  same counting rule used to tune the benchmark) is rendered by
  `PdfDocument.render_page` and passed to `pytesseract`; a healthy page uses pdf-oxide Markdown.
  When every page is healthy, `to_markdown_all()` may provide whole-document structure. For a mixed
  document, use `to_markdown(page_index)` for healthy pages and OCR text for thin pages, then join
  them once in source order with Agent2Learn's stable page markers. Never append whole-document
  Markdown to per-page OCR, which would duplicate evidence.
- **`PdfiumBackend` (fallback):** `pypdfium2` provides degraded text extraction and rendering only
  when the default backend cannot open or convert the document. It is not the default renderer for
  OCR, and a lower word count alone does not silently switch backends. The manifest and audit record
  the backend/version actually used and warn when fallback output was accepted.

Agent2Learn never calls pdf-oxide's built-in OCR, model prefetch, or ONNX path: those facilities can
download models into a user cache. OCR is exclusively the local Tesseract executable reached
through `pytesseract`. If Tesseract or the requested language is unavailable, healthy digital pages
remain convertible, but a source with unresolved thin/image pages is an explicit conversion gap and
does not become trusted grounding evidence.

Notebook twins are rendered directly from `nbformat` v4 and are **never executed**. The renderer
preserves markdown cells and attachments; language-tagged fenced code; stream output;
`text/markdown` and `text/plain` display/execute output; deterministic image data URIs; and
ANSI-stripped error tracebacks, all in source order. An unsupported MIME bundle gets an explicit
marker instead of disappearing. In particular, executed-cell text such as dataframe printouts is
grounding evidence and may not be dropped.

The golden-vault test is the tripwire for converter regressions. Any default/fallback converter or
notebook-renderer change must explain its output diff, regenerate candidate golden fixtures from the
same frozen synthetic corpus, and prove byte-identical results on Windows, macOS, and Linux before
the fixture is accepted. The private 262-PDF acceptance corpus has passed the restated gate at
threshold 80: **zero conversion failures and 96.4% of baseline recovered words**, with the shortfall
attributed to hybrid image-slides in a single course and to a whole-page OCR threshold rather than
to extraction quality. Only aggregate/redacted results leave the private workspace.

### An archive must never lose what it captured

The reference implementation has a **known, twice-observed, deliberately deferred data-loss bug**,
and it must not be ported. `get_news()` rewrites `announcements.md` and `news.json` wholesale from
the current API response. When D2L expires an announcement, it vanishes from the response — and
therefore from the archive. The author caught it twice and hand-repaired the file byte-exact:

> *"re-caught and surgically fixed the recurring announcement-overwrite issue (an expired COURSE303
> survey notice was about to be silently dropped from the archive again) — reinserted byte-exact at
> its correct chronological position… Root-cause fix in ingest.py deferred per user."*

Tolerable in a private tool whose author notices. **Unacceptable in a public archival product**,
where nobody will notice and nobody will hand-repair. Silent data loss in a tool whose entire value
proposition is "archive" is the worst possible defect.

**The rule, generalised beyond announcements:** any artefact D2L can un-publish — announcements,
content topics that get hidden, dropbox folders that close, quizzes that are withdrawn — is
**merged, never replaced**.

- Every writer that consumes a list response first proves that all pages were fetched successfully,
  then performs a **union by stable ID** against what is already on disk. A partial, failed, or
  malformed response can add known items but can never mark an existing item missing.
- This merge rule applies to grades when explicitly enabled, discussion forums/topics/posts when
  explicitly enabled, and nested assignment attachments as well as the ordinary announcement,
  content-topic, dropbox, and quiz collections. An incomplete grade response preserves the prior
  opt-in snapshot; malformed discussion or attachment nesting records a category gap and cannot
  replace captured data or mark files missing.
- An item previously captured and absent from one complete response is retained with
  `"missing_since": <iso>`. Only after it is absent from two consecutive successful complete syncs
  is `"withdrawn_at": <iso>` set and a "no longer posted" note rendered. A reinstated item clears
  both markers.
- Nothing is ever deleted by a sync. Ordering is by the item's own date, so a reinstated item lands
  back in its correct chronological position.
- This is covered by a named test: ingest a fixture with three announcements, re-ingest with the
  middle one removed twice, assert all three remain and the middle is marked withdrawn only after
  the second complete absence.

### Source identity, content integrity, and revisions

A path-only manifest cannot detect a Learn file that changes in place. The public manifest is a
versioned mapping from stable source identity to structured entries:

```json
{
  "uwaterloo:67890:topic:12345": {
    "path": "Spring 2026/COURSE101/content/Week 1/Lecture.pdf",
    "sha256": "...",
    "source_id": "12345",
    "etag": null,
    "last_modified": "...",
    "size": 48123,
    "fetched_at": "...",
    "derived": {
      "markdown": {
        "path": "Spring 2026/COURSE101/content/Week 1/Lecture.md",
        "sha256": "...",
        "source_sha256": "...",
        "tool": "pdf-oxide",
        "tool_version": "...",
        "created_at": "..."
      }
    }
  }
}
```

- A canonical key of school adapter ID + course org-unit ID + entity kind + entity ID defines
  identity. Titles, term labels, and local paths never do.
- Every download streams to a sibling `.part` file, validates HTTP status and expected size when
  known, computes SHA-256 while streaming, flushes and fsyncs, then atomically replaces the current
  materialized file with the same Windows retry policy as state writes.
- A matching remote fingerprint and matching local hash may be skipped. Missing fingerprints do not
  imply unchanged content; the downloader uses a conditional request when supported or revalidates
  content.
- If the same canonical source key produces different bytes, the previous bytes are preserved under
  `.a2l/history/<sha256-of-canonical-source-key>/<timestamp>/` before the current path changes.
  Revision metadata records the full canonical key plus old/new hashes. The digest prevents unsafe
  path characters and collisions between entity types or courses whose local IDs overlap. A sync
  never silently destroys a captured revision.
- `.part` files are never entered into the manifest. An incomplete or interrupted download is
  removed and safely restarted from byte zero; v0.1 does not retain unaudited partial bytes for
  range resumption. If the download completed and only fsync or atomic installation failed, the
  validated `.part` is retained for the next sync to retry without re-downloading it. An atomic
  pending-install marker ties that part to its canonical source, destination, byte count, digest,
  and remote validator; a part with no validator is revalidated before reuse, and a stale, missing,
  or tampered marker/part is discarded rather than trusted.
- Every derived markdown twin records its own hash, the exact source hash, converter name/version,
  creation time, the configured PDF OCR word threshold when applicable, and ordered page-coverage
  modes/word counts. Study, grounding, indexing, and checking treat a twin as trusted course
  evidence only when both hashes match and the source revision is current. A stale or locally
  modified twin is a coverage/integrity gap, never silently accepted.
- Before regenerating a locally modified twin, preserve its bytes and prior metadata in the same
  source-key history bucket with a `local-modification` marker, then atomically install the new
  generated twin. The audit reports this event. Generated markdown is not a place where the tool
  silently discards a student's annotations.

The human-readable vault shows the current revision. Revision history is implementation state, not
duplicated into course folders, and is pruned only by a future explicit maintenance command that
shows exactly what will be removed.

### `content_map.json` distinguishes metadata, source, and trusted markdown

Every topic row contains its canonical source key/ID, title/kind, `availability`, `source_path`,
`path` (the trusted markdown path), source/derived hashes when present, and one next action. Allowed
availability values are `metadata_only`, `source_only`, `markdown_ready`, `external_link`,
`unsupported_format`, `conversion_gap`, and `integrity_gap`.

`conversion_gap` is an additive availability state within content-map schema version 1: it changes
no row keys, path rules, or identity invariants, so `CONTENT_MAP_VERSION` remains 1. Consumers must
handle the state explicitly and may not infer it from a filename or preserve it without a verified
manifest source.

- `path` is non-null only for a current hash-verified markdown twin.
- `source_path` may be non-null while `path` is null, distinguishing a conversion gap from a file
  that has not been downloaded. Every source-backed gap, including `unsupported_format`,
  `conversion_gap`, and `integrity_gap`, is valid only when the manifest still proves the current
  source path and source hash; a source-less gap row is reconciled to `metadata_only` and offers
  `a2l fetch`.
- External/licensed targets expose only a local `.url.txt` stub and are never offered to `fetch`.
  The stub links back through a deterministic query-free LEARN content-view URL built from the
  course/topic IDs and may show only the parsed destination hostname. Raw external URLs, URL
  user-info, fragments, signed query parameters, and LTI launch payloads are used in memory for
  classification and then discarded; they never enter the vault, manifest, logs, or reports.
- `a2l fetch <id>` downloads a `metadata_only` source or retries conversion/integrity repair for a
  fetchable local source, then prints the verified citation path. It never calls a topic missing
  merely because `path` is null.
- Index, ground, where, and check consume this schema; they do not infer state from filenames.

### Vault schema versioning

The vault outlives the tool that wrote it. `.a2l/VERSION` holds an integer schema version, written
at `init` and checked on every command.

- Same version → proceed.
- Vault older → write a backup of `.a2l/`, run the registered migrations in an isolated staged
  `.a2l/` state, and publish the result with atomic file installs and `VERSION` last. A migration
  callback that raises leaves the original VERSION and manifest untouched; if publishing fails,
  the backup is used to restore the original state.
- Vault **newer** than the installed tool → refuse to write, explain, and suggest `a2l upgrade`.
  Never let an older binary silently mangle a newer vault.

v0.1 ships version `1` and an empty migration registry. The registry existing from day one is the
point; retrofitting migrations onto vaults in the wild is not possible.

### Privacy defaults

- **Discussions are off by default.** Discussion text can contain classmates' names and personal
  introductions; collecting it is a materially different exposure from archiving one's own
  coursework. `--include-discussions` is opt-in. Unless `--discussion-authors` is also passed,
  authors are replaced with stable vault-local pseudonyms derived by HMAC-SHA-256 over the stable
  platform author ID when available, falling back to the normalized display name only when the API
  provides no identifier. The 32-byte random key is permission-restricted private vault state; raw
  IDs/names are discarded after rendering. Pseudonyms expose at least 80 digest bits and resolve the
  vanishingly unlikely local collision deterministically. A plain hash is prohibited because names
  are low entropy and readily reversible. Onboarding warns that fallback names can collide and post
  bodies may still contain self-identifying text.
- **Grades are an explicit onboarding choice.** The metadata sync is complete for the categories the
  student enables, but grade values are excluded unless the student opts in. Grade values never
  appear in logs, doctor reports, demo assets, or public fixtures.
- **Sensitive-category deletion is explicit and narrow.** `a2l privacy status` reports whether
  grades/discussions are enabled and where their local data lives. `a2l privacy purge grades` and
  `a2l privacy purge discussions` first enumerate exact files/JSON fields, default to preview, and
  require an interactive phrase before removal. The inventory covers current category files,
  snapshots, manifest records, category-derived index text, Agent2Learn-managed revisions/backups,
  and the discussion pseudonym key when no retained discussion needs it. They never use a recursive
  broad delete, touch unrelated course source files, or imply secure erasure from filesystem
  snapshots or external backups. Disabling a category stops future collection but does not silently
  destroy prior local data; the CLI points to purge.
- **No telemetry.** No analytics, no phone-home, no identifiers, and no passive version check.
  `a2l upgrade --check` contacts PyPI only when the user invokes it. `doctor --open` sends the
  already-rendered redacted issue body to GitHub only after displaying that external action. This
  runtime claim does not pretend that user-invoked HTTPS downloads are invisible: the static site,
  CDN, GitHub, Astral, npm, and PyPI may receive ordinary request metadata under their respective
  policies. `docs/PRIVACY.md` lists those actions and distinguishes provider logs from
  Agent2Learn-product telemetry.
- **Logs are allowlisted and bounded.** Rotating local logs contain event/diagnostic codes, stage
  timings, package versions, status classes, and exception class names only. They exclude URLs,
  query strings, headers, bodies, cookies, tokens, identities, course labels/IDs, filenames, grades,
  discussions, draft text, and submission phrases. Default retention is five 1 MiB files; `a2l
  privacy status` shows the directory and `a2l privacy purge logs` previews and clears only those
  known files. `--verbose` does not relax the data allowlist.
- `a2l doctor --report` redaction is specified in the Doctor section below.

### Course AI-policy surfacing — informational, never enforcing

After metadata has already produced the first deadline view, sync renders discovered course
outlines through the dedicated local CDP profile. Top-level navigation is limited to the configured
LEARN origin and first-party `outline_hosts()` declared by the school adapter. Rendered source and
markdown twin use the same manifest, hash, revision, and atomic-install contracts as other content.

Extract each course's stated generative-AI policy from a successfully rendered outline into
`_meta/ai_policy.json` and a line in the course `INDEX.md`. Coverage is tri-state:

- `found` — policy text plus `path.md:line` citation;
- `not_found_in_scanned_outline` — the outline was available and scanned, but no matching clause
  was found; this is not a claim that no policy exists elsewhere;
- `outline_unavailable` — not rendered, timed out, or blocked by authentication. Never collapse
  this into `not found`.

**This surfaces information. It does not gate behaviour.** The policy landscape is genuinely
unsettled and course outlines are often blunt instruments: one reference assignment explicitly
required students to prompt a GenAI model and critique its output with a disclosed model name,
while another course discouraged AI in assessments. Students may also use AI to study material for
courses whose assessment rules are more restrictive.

The requirements are therefore:

- Record the policy and where it came from (`path.md:line`).
- The skill instructs the agent to mention a relevant restriction **once**, factually, when the
  user asks for help producing graded work, with the source citation.
- Agent2Learn does not classify the policy or claim that a use is permitted. The student remains
  responsible, and the host agent's own safety and integrity rules continue to apply. The skill must
  also read assignment-specific instructions; if they prohibit AI-generated code, analysis, or final
  answers, it limits help to explicitly permitted forms and does not produce submit-ready work. Do
  not repeat the notice or moralise.
- Documented as convenience: *"Agent2Learn pulls cited AI-policy language out of each available
  course outline so you can review it without hunting through the page."*

### Submission is present, disabled, and gated

`a2l submit` means one narrow thing: upload a finished local file to the resolved Learn Dropbox
folder. It does not write the work, choose the file, or decide that the work is ready. The user is
the final gateway immediately before every mutating POST.

There are two independent gates:

1. `a2l enable-submit` prints the boundary, records a one-time acknowledgement, and enables the
   command. This prevents accidental discovery or agent invocation from reaching an upload flow.
2. Every `a2l submit <course> <item> <file>` resolves the exact course, folder, attempt state, file,
   byte size, SHA-256, and endpoint; validates deadlines and file readability; then prints a complete
   preview. In a non-interactive process the command stops there and cannot mutate LEARN. In an
   interactive controlling TTY it then offers the final gateway: a real upload occurs only if the
   human types a fresh one-time phrase containing the displayed confirmation code and filename. The
   code comes from `secrets`, is single-use, exists only in memory, and expires with the staged file
   after five minutes.

The preview and POST must describe the same immutable bytes. Before preview, copy the selected file
through a private `0600` staging file while computing SHA-256 and size; never trust a path that can
change between confirmation and upload. The POST streams that exact staged file, sets the required
top-level `Content-Length`, and has transport retries disabled. Staging names contain no course or
filename, are removed on every exit path, and stale staging files are cleaned locally on next start
without logging their contents. A deadline shown by the client is informational—the server remains
authoritative about special access and whether it accepts the submission.

There is **no `--yes`, `--force`, environment variable, piped-stdin, or non-interactive bypass in
v0.1**. An agent may prepare and invoke the preview only after the user explicitly asks to submit
that specific item; it must never type or synthesize the final confirmation. Immediately after the
human confirms, Agent2Learn performs exactly one POST and reports success **only** after API
read-back identifies a new submission by the current user with the expected filename, size, and
timestamp. Ambiguous read-back is failure, never success.

After the attempt, atomically write a minimal local receipt under `.a2l/submissions/`: canonical
course/folder keys, vault-relative selected-file path when the file is inside the vault (otherwise
only `location: external` plus basename), filename, SHA-256, size, confirmation/POST/read-back
timestamps, HTTP status class, and `verified` or `verification_unknown`. Never store absolute paths, cookies,
headers, response bodies, display names, grades, or the confirmation phrase. A receipt documents
what happened and prevents uncertainty from turning into an automatic retry; it is not itself proof
that LEARN accepted an unverified upload.

**Threat-model boundary:** a controlling TTY establishes an interactive session; it cannot
cryptographically prove that keystrokes came from a person rather than local software with terminal
control. The technical gate removes normal unattended interfaces and accidental mutation paths.
The canonical agent skill supplies the complementary workflow rule: after preparing the preview,
the agent returns control and the student personally decides whether to enter the phrase. Public
copy must describe this as a strong human-in-the-loop interlock, never as an impossible-to-automate
security boundary.

It is documented as *"upload a finished file to a Learn Dropbox folder after you personally review
and confirm the exact target"*. This human-in-the-loop behavior is a product requirement, not merely
skill wording.

> **Do not port the reference's `allow_abbrev=False`.** That is an `argparse` setting; this CLI is
> Typer, built on Click, and **Click does not abbreviate long options at all** — so `--con` fails
> with "no such option" without any configuration. Carrying the flag across would be a no-op that
> reads like a safety control. Test the behaviour, not the flag, and never set Click's
> `token_normalize_func`.

#### The public build uses only D2L's documented submission route

The reference posts to `…/dropbox/folders/{id}/submissions/**mypost**`. **D2L's official
documentation does not list that route.** The documented student route is:

```
POST /d2l/api/le/{version}/{orgUnitId}/dropbox/folders/{folderId}/submissions/mysubmissions/
```

The same reference documents a group variant at `…/submissions/group/{groupId}/`, but v0.1 does
not mutate group folders. Group identity, teammate visibility, and read-back semantics require their
own supervised test and confirmation copy; a group target produces a complete preview followed by
an explicit unsupported message and zero POSTs.

Authority: D2L's current
[Dropbox API reference](https://docs.valence.desire2learn.com/res/dropbox.html) and
[multipart upload guide](https://docs.valence.desire2learn.com/basic/fileupload.html), reviewed
2026-08-24. Re-check both during the release API review.

The private route was never evidence for a public mutation, because it was never exercised against
a real Dropbox — a dry run validates resolution and body construction, not server behaviour. That
gap is now closed empirically in favour of the documented route: see the validation note below.

Required handling in the public implementation:

1. **Use only the documented route, `mysubmissions`, after validating it in a designated non-graded
   test Dropbox or institution-provided sandbox.** Current D2L documentation marks LE API 1.82+ as
   the supported route family. Calibration must select a supported LE version and prove that the
   matching GET route is available before previewing upload. There is no `mypost` implementation or
   automatic fallback in v0.1; an unsupported instance keeps submission disabled.
2. The multipart body format *is* confirmed correct by the official docs: `multipart/mixed`, **JSON
   RichText part first**, then the file part with `Content-Disposition: form-data; name=""` and a
   `filename` — the empty `name` is deliberate and documented, not a bug.
3. **The dry run must resolve the folder and report the calibrated version/route without sending a
   file.** `OPTIONS` or `GET` is capability evidence, not proof that POST works, and must not be
   described as a verified upload.
4. **Route validated 2026-08-25.** One supervised POST to a human-selected non-graded individual
   Dropbox in a completed term returned **200** on
   `…/dropbox/folders/{id}/submissions/mysubmissions/` with `le 1.96`, and API read-back located the
   file by exact filename, byte size, and a post-confirmation timestamp. `X-Csrf-Token` is required
   and present in the harvested session; the documented `multipart/mixed` shape — JSON RichText part
   first, then the file part with `name=""` — is correct as written. `mypost` proved unnecessary.
   **Group submissions, closed folders, large files, and non-Waterloo instances remain unproven.**
   The route being real does not relax any safety control: `submit` still ships disabled behind
   `a2l enable-submit` plus a fresh per-file interactive TTY confirmation, and the FAQ states what
   has and has not been validated.

---

## `a2l check` — experimental evidence scan, specified

This is the only substantially new analysis code in v0.1. It is useful because the vault exists; it
is not the source of truth and it does not convert lexical similarity into semantic certainty.

### What it does

Given a draft the student has written, `check` reports, claim by claim, **what matching or related
evidence it found in the student's own course material** — with citations and an explicit,
unembarrassed "no matching evidence found" where retrieval finds nothing.

It does not grade, prove correctness, rewrite, or produce an answer. Every human-readable report
begins with: `Experimental lexical evidence scan — review the cited sources yourself.`

### Interface

```
a2l check <draft-file> [--course CODE] [--assignment QUERY]
          [--format md|json] [--strict]
```

- `<draft-file>` — `.md`, `.txt`, `.ipynb`, `.py`, `.r`, `.rmd`, or `.tex`.
- `--course` — inferred from the draft's location in the vault when omitted.
- `--strict` — exit non-zero if any claim has `no_matching_evidence` or `possible_conflict`.
  Intended as a review reminder, never as proof that a draft is correct.

### Algorithm

1. **Resolve scope.** Determine the course. If `--assignment` is given, or the draft sits inside an
   assignment folder, reuse the `ground.py` retrieval to build the candidate source set: the task
   file, sibling data files, the course outline, and the top-ranked lectures. Otherwise use every
   markdown twin in the course. Candidate sources must be traceable to a LEARN source ID or an
   explicitly recognized assignment data file. Exclude the draft itself, unknown local siblings,
   prior drafts/solutions, `GROUNDING.md`, INDEX/AUDIT/check output, and all other Agent2Learn-
   generated prose; a claim may never cite itself or another student-authored answer as evidence.
2. **Segment the draft into claims.** A claim is a checkable unit:
   - a sentence containing a definition, a numeric result, a named method, or a formula;
   - a fenced code block that uses a library, function, or API;
   - a step in an enumerated derivation.
   Prose that is purely connective ("Next, we consider…") is skipped and reported as such.
3. **Retrieve.** For each claim, score candidate source lines by term overlap using the shared
   tokeniser — which splits letter/digit boundaries so `Lab4` yields `{lab4, lab, 4}` — with the
   versioned `GENERIC` stopword set. **Both are specified in full in
   `2026-08-25-algorithm-reference.md`**; implement from there rather than inferring them. For claim terms `C`, source
   terms `S`, claim values/symbols `V`, and source values/symbols `W`, compute:

   - `term_coverage = |C ∩ S| / max(1, |C|)`;
   - `value_coverage = |V ∩ W| / |V|` when the claim has values/symbols;
   - `score = term_coverage` without values, otherwise
     `4/5 * term_coverage + 1/5 * value_coverage`.

   Terms are normalized case-folded tokens after stopwords; values/symbols are separately extracted
   numbers, comparison operators, and mathematical/code identifiers. Keep the top five spans by
   ascending sort key `(-score_bp, path, line)`. Compute with exact rational arithmetic and serialize
   `score_bp = floor(score * 10_000)` so platforms cannot disagree through floating-point or JSON
   formatting. The candidate floor is **3,500 bp (0.35)** and the strong-match floor is **7,500 bp
   (0.75)**. These constants and the tokenizer form `check_algorithm_version = 1`; changing any of
   them requires fixture review and a version bump.
4. **Classify.** Every claim receives exactly one evidence status:

   | Verdict | Meaning |
   | --- | --- |
   | `evidence_found` | A source span shares the claim's key terms, values, or notation. Cite it; do not claim semantic proof. |
   | `related_evidence` | Related material exists but does not establish this specific claim. Cite it and say what is missing. |
   | `no_matching_evidence` | Retrieval found no course span above the documented threshold. This is not proof the course omits it. |
   | `possible_conflict` | A source span *may* disagree. Cite both and ask the student to compare. **Never asserted as fact.** |
   | `skipped` | Connective prose, not a checkable claim. |

   Classification is deterministic: below `0.35` is `no_matching_evidence`; `0.35`–`0.749…` is
   `related_evidence`; `0.75+` with every extracted claim value/symbol present is
   `evidence_found`, otherwise `related_evidence`. `possible_conflict` may override a strong match
   only for an allowlisted, test-covered surface form in which the same normalized predicate and
   operands appear with opposite polarity (`is`/`is not`) or opposite comparison operators. A
   differing number alone never triggers it. If the narrow template does not match, return
   `related_evidence` and let the student compare the citation.

   > **On `possible_conflict` — this status is deliberately weak, and must stay
   > that way.** An earlier draft of this spec called it `contradicted` and described it as the
   > "highest-signal verdict," detected by "a negation or a differing numeric value." That is not
   > achievable with lexical matching and would be actively harmful:
   >
   > - **Negation detection is unreliable lexically.** "The shadow price is not defined for
   >   degenerate optima" versus a student's "the shadow price is defined at optimality" is a scope
   >   difference, not a contradiction — but the tokens say otherwise.
   > - **Differing numbers usually mean a different problem instance**, not an error. The lecture's
   >   `n = 10` machines and the lab's `n = 20` are both correct.
   > - **A false contradiction is worse than no tool at all.** It would lead a student to "correct"
   >   a right answer into a wrong one, using the authority of their own professor's slides.
   >
   > So the status surfaces a *candidate for comparison* and says so in those words. It never
   > states that the student is wrong. The rendered line reads
   > `? L58  your materials may say something different — compare:` followed by both spans.

5. **Notation check.** Flag symbols and terms in the draft that do not appear in the scanned course
   material and show a cited, lexically nearest course term when one clears its own documented
   threshold. Label it a candidate, never *"the term the course actually uses"* or a required
   replacement; lexical proximity cannot establish synonymy.
6. **Report.**

```
$ a2l check DRAFT_lab4.md --course COURSE101

  Experimental lexical evidence scan — review the cited sources yourself.

  COURSE 101 · Lab 4 · DRAFT_lab4.md
  24 claims · 19 evidence found · 3 related · 1 no match · 1 to compare

  ✓ L12  binary facility-location variables y_i ∈ {0,1}
         content/Weeks 3&4 LP and MIP Modelling/MIP-Modelling.md:88

  ~ L31  "the dual price equals the shadow price at optimality"
         related, not asserted → content/Week 3 LP Duality/Duality in LP.md:145
         source excerpt: "shadow price ... non-degenerate optima"

  ✗ L44  "apply Benders decomposition to separate the subproblem"
         no matching evidence found in the local COURSE 101 material
         nearest below-threshold span (not evidence):
         Two-Stage Stochastic Programming.md:12

  ? L58  "constraints must be strictly satisfied at the LP relaxation"
         your materials may say something different — compare:
         content/Weeks 3&4 LP and MIP Modelling/LP Modelling.md:203

  NOTATION
  · you write "objective coefficient"; nearest course wording candidate:
    "cost coefficient" (LP Modelling.md:31)

  ─────────────────────────────────────────────────────
  1 claim with no matching evidence, 1 worth comparing.  Review L44 and L58.
```

`--format json` emits the same content as a machine-readable array of claim objects
(`line`, `text`, `status`, `score_bp`, `citations[]`, `note`) plus `check_algorithm_version` and a
source-revision map containing source and derived SHA-256 values. This lets a saved report identify
the exact algorithm and local revisions it scanned even after a later sync updates the visible
vault.

### Design rules

- **Never silently pass.** An empty source set is an error, not a clean bill of health.
- **`no_matching_evidence` is not an accusation.** The copy must read as *"no matching evidence was
  found"*, which can mean the retrieval missed it, the relevant file is not downloaded, or the
  course genuinely omitted it. It is a prompt to inspect, not a verdict on the student.
- **Every non-`skipped` finding carries a citation or an explicit statement that none was found.**
- If any relevant candidate has `path: null`, report its explicit availability state before
  assigning `no_matching_evidence`. Offer `a2l fetch` only for fetchable metadata/source/integrity
  states; identify external links as deliberately unavailable rather than suggesting a forbidden
  fetch.
- The retrieval is lexical and deterministic in v0.1 — no embeddings, no model calls. It builds one
  in-memory inverted line index per run rather than rescanning every file for every claim. It runs
  offline and produces identical output on every machine. The performance target is under two
  seconds for 100 claims against the versioned 50,000-line synthetic benchmark on a two-core CI
  runner; this is a benchmark, not a promise for every vault or machine. An agent reading the JSON
  adds the semantic judgement. This keeps the tool honest about what it computed itself.

---

## `a2l doctor` — specified

Design principle: **never leave the user without exactly one next action.**

### Checks

| Group | Checks |
| --- | --- |
| Environment | installed `a2l` version; Python version; `uv` presence; OS and architecture; console encoding. Update availability is checked only by explicit `a2l upgrade --check`. |
| Filesystem | vault path exists and is writable; free disk space; Windows `LongPathsEnabled` (informational); longest vault-relative and absolute paths, with a third-party-tool warning above 240 absolute characters |
| Session | storage backend in use and backend viability (keychain or file); age of harvest; `whoami` HTTP status; API versions reachable |
| Optional tools | `tesseract` (OCR); a CDP-capable browser |
| Skills | which agents were detected; installed skill count and version per agent; staleness vs the installed package version |
| Vault | per term: courses, topics resolved out of total, conversion gaps, empty twins, last sync time |

### Output

Grouped checklist with `✓ / ⚠ / ✗` (ASCII fallback per C8), a one-line summary, and a single
suggested next command. Exit codes: `0` all clear, `1` warnings only, `2` at least one failure.

### `--report`

Emits a markdown block for a GitHub issue.

- **Redacted:** user's name, student ID, org-unit IDs, course codes, and absolute paths
  (`$HOME`/`%USERPROFILE%` → `~`).
- **Never present in any code path:** cookie values, tokens, grades.
- **Included through an allowlist after redaction:** package version, OS and architecture, Python
  version, install method, failed check identifiers, HTTP status classes, exception class names,
  per-stage timings, and sanitized diagnostic codes. Raw tracebacks, response bodies, headers, URL
  query strings, logs, filenames, and course metadata are excluded from the public issue body.
- `--open` first shows the GitHub destination and explains that the redacted body will leave the
  device, then opens a pre-filled issue for the user to review and submit.
- The repository's bug-report issue template requires the report block.

---

## Nice-touch features

These are specified, not optional. They are the difference between a utility and something a
student recommends to a friend.

| Feature | Behaviour |
| --- | --- |
| **`a2l calendar`** | Export every due date, exam, and office hour as a subscribable `.ics`. The reference repo already generates one; port and generalise it. Deterministic UIDs so re-export updates rather than duplicates. |
| **`a2l diff`** | What changed since the previous sync: new content, new announcements, changed due dates, and—only when enabled—new grades. Backed by a snapshot written on each sync. |
| **Grade-posted notice** | When grade sync is enabled, report new values locally without placing them in logs or support reports. |
| **Term rollover** | Sync detects a new enrolled term and asks: `New term detected: 6 courses. Sync? [Y/n]`. |
| **`a2l where <query>`** | Fuzzy-find any topic across every course and term; print the path and the `.md` twin. |
| **`a2l fetch <topic-or-path>`** | Resolve a known topic by stable ID or fuzzy path; download it when metadata-only or retry conversion/integrity repair when the source is local, then print a hash-verified citation path. Never fetch external-link states. |
| **`a2l open <course>`** | Reveal the course folder using `explorer` / `open` / `xdg-open`. |
| **Exam countdown** | During the exam period `a2l today` leads with days remaining per exam. |
| **Obsidian handshake** | Write a minimal `.obsidian/` config with no plugins or executable hooks so the vault opens cleanly. Skip the entire directory if one already exists. |
| **Shell completions** | `a2l completions {bash,zsh,fish,powershell}`. |
| **Vault-name collision** | If `~/agent2learn` exists and is not an Agent2Learn vault, offer `~/agent2learn-2`; never write into a directory the tool does not own. |

### Time to first value — split metadata from files

The onboarding performance target is **under 90 seconds of product-controlled work from installer
start to a real deadline on screen** on the release benchmark. Time spent by the student completing
WatIAM/Duo and unavoidable external network latency are measured separately, not hidden inside the
claim. Public copy uses measured distributions from alpha installs rather than promising 90 seconds
on every machine.

The naïve way to get there is "only sync the last four weeks of content, filtered by the topic's
`LastModifiedDate`." **That design is broken and must not be built.** Many instructors upload an
entire term on day one. A student installing in week 10 of such a course would match *nothing* in
the last four weeks and land on an empty vault with no deadlines — the exact opposite of the moment
the product is designed around. The inverse fails too: an instructor who re-uploads an old file
makes stale content look new. `LastModifiedDate` is a poor proxy for relevance.

The correct split is **not by date. It is by cost.**

| | Content | Cost | When |
| --- | --- | --- | --- |
| **Metadata** | TOC, dropbox folders and due dates, announcements, quiz dates, the course tree; grades only after explicit opt-in | JSON only — a few hundred KB, seconds | **Always complete for each enabled category, for every selected course** |
| **Files** | PDFs, slides, notebooks, datasets, media | hundreds of MB, minutes | Progressive |

So:

1. After authentication, `a2l init` lists the discovered active term and academic course offerings,
   defaults to all of them, and lets the student deselect before any course metadata request. It
   persists stable offering IDs rather than course-code strings. If multiple active academic terms
   are returned, it lists each term and its course count and requires an explicit term-code choice;
   it never silently chooses one. If no active academic term can be inferred, it stops with
   `a2l courses --all-terms` instead of guessing.
2. `a2l init` performs a **complete metadata sync for every selected course in the term.** This is
   fast, and it is what produces deadlines, the `INDEX.md` tree, announcements, and grades only when
   the student opted in. **The onboarding moment never waits on a file download.**
3. Onboarding offers three explicit file choices after showing size/time estimates:

   - **Full document archive (recommended):** every eligible course-owned document, with audio and
     video excluded unless the student opts into `--include-media`;
   - **Priority set:** assignment-linked files, outlines, and a deterministic byte-bounded set of
     recently released course documents; or
   - **Later:** retain the complete metadata/index now and download no files yet.

   `a2l sync` remembers that choice; `--all` and `--priority` override it for one run. Priority
   ordering uses assignment links and an explicit availability/release date when D2L supplies one.
   If those signals are absent, it follows reverse content-tree order within the disclosed byte
   budget and labels the result heuristic. A topic whose remote size is unknown is omitted from
   this byte-bounded priority set because selecting it would make the budget unprovable; it remains
   eligible for the full plan's per-file ceiling or an explicit `a2l fetch`. `LastModifiedDate` is
   only a tie-breaker, never the inclusion rule. Every mode is resumable by completed item.
4. Because metadata is always complete, `content_map.json` knows about every topic even when its
   file is not yet on disk. A topic with no local file is `metadata_only` with
   `source_path: null`/`path: null` and is fetched through `a2l fetch`; a local source without a
   verified twin has a different explicit state. `a2l` never claims a topic does not exist merely
   because its trusted markdown path is null.

`a2l init` prints a clearly labelled estimate of duration and disk footprint before starting the
file phase, based only on available remote metadata and conservative throughput assumptions. If
size is not knowable without downloading, it says `unknown` rather than inventing precision. The
file phase is interruptible without losing the metadata.

---

## Quality and verification

A change may merge only if all of the following hold.

### Automated

1. **CI passes on `windows-latest`, `macos-latest`, and `ubuntu-latest`** for Python **3.11–3.14**.
   Not a follow-up; the matrix exists from the first commit.

   > The floor is 3.11, not 3.10: **Python 3.10 reaches end of life in October 2026**, weeks after
   > this ships, and a tool a student installs in September should not be built on an interpreter
   > that is unsupported before their term ends. The ceiling is 3.14, stable since October 2025.
2. **Path-safety property tests.** `safe_name` is tested against reserved device names, reserved
   characters, control characters, trailing dots and spaces, over-length names, and Unicode. The
   same inputs must produce the same outputs on all three operating systems.
3. **Golden-vault test.** A fully synthetic API fixture, including a representative PDF and an
   executed notebook with textual output, is ingested on each OS; the resulting tree,
   `content_map.json`, `INDEX.md`, and generated twins must be byte-identical across all three. Any
   converter-output change regenerates a candidate on all three OSes and is accepted only after its
   byte diff is explained.
4. **No absolute paths in the manifest.** A schema-aware test walks every source and derived
   artifact path and asserts that each is normalized, vault-relative, POSIX, and non-escaping.
5. **Revision-integrity test.** Re-ingesting the same canonical source key with changed bytes
   preserves the prior revision in that key's SHA-256-addressed `.a2l/history` bucket, atomically
   installs the new bytes, invalidates or regenerates stale derived artifacts, and leaves no
   `.part` file. An unchanged fingerprint plus matching local source and derived hashes performs
   no rewrite.
6. **Licensed-content exclusion test.** A fixture TOC containing `quicklink.d2l`, `type=lti`, and
   `vitalsource` topics produces link stubs and zero downloads.
7. **Redaction test.** `doctor --report` run against a fixture containing a name, a student ID, and
   a home path emits none of them.
8. **Cookie-scope test.** A dedicated browser profile containing Learn, Duo, Google, and unrelated
   cookies exports only the minimum verified Learn API cookie set; Duo trust remains in the profile.
9. **Outline egress test.** Fake CDP navigation may reach only LEARN or adapter-declared first-party
   outline hosts; off-origin redirects and lookalikes are stopped before request. Failure yields
   `outline_unavailable`, never a false no-policy result.
10. **Offline test suite.** Every automated test runs with no network against fully synthetic API
   fixtures. Live same-device behavior is covered only by the explicit manual release gates.
11. **Installer smoke tests in CI.** `install.sh` on macOS and Ubuntu runners, `install.ps1` on the
   Windows runner, each ending in a successful `a2l --version`.

### Manual, before any release

12. **Done.** The private 262-PDF acceptance corpus was run at the default 80-words-per-page
    threshold: `pdf-oxide`/Tesseract recovered **96.4%** of the previous baseline's aggregate words
    with **zero failures** and 40% more headings. Re-run this corpus on any converter, threshold, or
    renderer change; the standing bar is **zero failures and ≥95% aggregate words with the shortfall
    attributed**. Preserve only aggregate redacted evidence, and stop the converter task if either
    condition fails.
13. Fresh-machine install on each OS, from the published installer, ending in a real sync.
14. A Windows student in the alpha group completes onboarding unaided.
15. Same-machine browser-to-API session replay verified on Windows, macOS, and Linux without ever
    copying a cookie or profile off its originating machine.
16. `a2l auth --paste` verified as a working advanced fallback on all three.
17. One real first-party outline renders through the dedicated profile on each OS; no external
    top-level request occurs and policy status matches manual inspection.
18. `a2l doctor --report` output read line by line for leaked identifiers.
19. One supervised upload to an explicitly designated non-graded test Dropbox succeeds only after
    the human confirmation phrase, followed by exact API read-back. Until this passes, published
    builds keep submission disabled.

---

## Repository safety

- The vault is **never** inside the repository. `.gitignore` covers `agent2learn/`, `*.session`,
  and `.a2l/`.
- `a2l init` resolves parent directories and refuses to place a vault inside the Agent2Learn source
  checkout. If any other selected root is already inside a Git worktree, it shows the repository
  root and requires explicit confirmation. A new vault gets a narrow `.gitignore` for `.a2l/`,
  optional grades/discussions, and submission receipts; this is defense in depth, not permission to
  publish copyrighted course files. `doctor` fails if known secrets/sensitive category files are
  tracked and warns if ordinary course sources are tracked.
- No session file, cookie, token, or API key is ever printed, logged, committed, or included in a
  doctor report.
- Browser profiles and exported sessions are never copied to another machine for testing or support.
- No fixture may contain real student data. Fixtures are synthesised.
- Private keys occasionally distributed as course material (`id_*`, `*_ed25519`, `*.pem`) are
  excluded from ingestion by name pattern and never converted.

---

## Explicit non-goals for v0.1

- **Any LMS other than D2L Brightspace.** Canvas and Moodle have different auth and different APIs;
  they would be a different codebase. `docs/PORTING.md` documents the `School` protocol for other
  Brightspace institutions; `docs/FUTURE.md` records other LMSs as unplanned.
- **Any school other than Waterloo, tested.** The `School` protocol and a `generic.py` stub exist
  from day one, and `--host` works, but only `uwaterloo.py` is tested and supported. Other schools
  arrive as pull requests.
- **A hosted or multi-user service.** Agent2Learn runs on the student's own machine against the
  student's own account. There is no server, no account, and no shared state.
- **Quiz question capture.** The student API exposes quiz metadata only. Surfaced as a documented
  platform limit.
- **MCP server.** The product's output is files, which agents already read well. An MCP server
  would spend thousands of tokens per session advertising tools that duplicate `grep`. Revisit only
  for a live-query surface.
- **A Claude Code plugin or npm runtime.** The canonical skill directories are standards-compatible
  and may be installed by either `a2l skills install` or an Agent Skills installer. A vendor plugin
  would add slash commands and a `SessionStart` hook plus another manifest and release artifact; it
  is recorded in `docs/FUTURE.md` as the strongest v0.2 candidate.
- **`ground --solve`.** Absent from the public build.
- **Group Dropbox mutation.** v0.1 previews and refuses group targets. Add it only after a separate
  supervised non-graded group upload/read-back test and group-specific human confirmation design.
- **Telemetry.** None.
