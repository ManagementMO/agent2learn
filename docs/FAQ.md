# FAQ

Start with `a2l doctor`. It is designed to name exactly one next action, and most of what follows
is what it will tell you.

## Setup and PATH

**`a2l: command not found` right after installing.**
The tool directory is not on this shell's `PATH` yet. `uv tool update-shell` (which the installers
run) updates future sessions, so **open a new terminal**. To find the directory:
`uv tool dir --bin`. If you installed manually, `uv tool install agent2learn` and then reopen the
terminal.

**Windows: I installed it but PowerShell cannot find `a2l`.**
uv writes the user `PATH` entry and broadcasts the change, but a terminal that was **already open**
before the install keeps its old environment. Close it and open a new one. Do not edit the registry
by hand.

**Can I add shell completions?**

```bash
a2l completions bash        # or zsh, fish, powershell, pwsh
```

It prints a script to standard output and installs nothing, so where it goes stays your decision.
Redirect it into your own completion directory or profile.

**Long paths on Windows.**
Agent2Learn prefixes its own filesystem calls, so it works whether or not `LongPathsEnabled` is
set. `a2l doctor` reports the setting for information only, never as a failure. If your vault root
is very deep, the advice is a shorter vault root — not a registry edit.

## Authentication

**Sign-in fails, or sync suddenly stops working.**
See [AUTHENTICATION.md](AUTHENTICATION.md). Exit code **75** means the session expired: run
`a2l auth`.

**There is no browser on this machine.**
`a2l auth --paste`. Input is hidden, so nothing is echoed or written to your shell history. This is
a supported path, not a hack.

**Should I clear or keep the dedicated browser profile?**
Keep it for fewer Duo prompts — the "remember this device" state lives there. Clear it with
`a2l auth --clear-profile` when handing the machine on, or when you want no local sign-in state.
Clearing removes the saved session too, and your vault is unaffected.

**Can I copy my session to another computer?**
No. Run `a2l auth` on each machine. Never paste a session, cookie, or profile anywhere — see
[AUTHENTICATION.md](AUTHENTICATION.md).

## Content and conversion

**Some PDFs have little or no text.**
Those pages have no text layer and need OCR. Agent2Learn uses **external Tesseract** through
`pytesseract`; if Tesseract is not installed, the gap is recorded explicitly rather than silently
producing an empty twin.

- macOS: `brew install tesseract`
- Debian/Ubuntu: `sudo apt install tesseract-ocr`
- Windows: install the UB Mannheim build and make sure `tesseract` is on `PATH`

Then rerun `a2l sync`. `a2l doctor` reports whether Tesseract was found.

**Why is a textbook or reading missing?**
Licensed eTextbooks and library e-resources are recognised and **never downloaded**. They are
recorded as links to open in LEARN yourself. This is deliberate, and no flag turns it off.

**A file is listed but has no local copy.**
Run `a2l fetch <source-id>`. The content map records why each item is unavailable — never fetched,
no Markdown twin yet, integrity mismatch, or a deliberate external link. Only the first three are
fetchable.

**How much disk will this use?**
It depends on your courses; slide decks and recordings dominate. `a2l init` estimates before
downloading and offers full, priority, or later. Media files are classified and counted so the
estimate is not a surprise. `a2l sync --priority` fetches the small, high-value material first.

**Can I move the vault?**
Yes: move the folder, then run `a2l init` and approve the new location, or edit `vault` in
`<config>/config.json`. The manifest stores vault-relative paths, so nothing breaks. Run
`a2l doctor` afterwards to confirm.

## Privacy and data

**How do I turn grades on or off?**
`a2l init` asks. Afterwards, `include_grades` in `<config>/config.json` controls it, and
`a2l privacy status` shows the current flags. Same for `include_discussions`.

**I turned grades off. Why are the old ones still there?**
Because disabling collection and deleting data are different actions, and conflating them would be
dishonest. Disabling stops future collection. `a2l privacy purge grades` deletes what is already on
disk, after previewing the exact targets and requiring a typed phrase.

**What does `a2l privacy purge` not do?**
It is a **logical** deletion. It removes the files and structured records it previews. It cannot
scrub filesystem free space, your backups, OS snapshots, or a copy already synced to a cloud
folder. The preview says this before you confirm.

**Does Agent2Learn phone home?**
No. No telemetry, no analytics, no crash reporting, and no passive version check. `a2l upgrade`
reads PyPI once, only when you run it. Every request the tool can make is listed in
[PRIVACY.md](docs/../PRIVACY.md).

## Submission

**Why can I not upload anything?**
The mutating submission path is **disabled in this build**. It stays disabled until a supervised,
designated non-graded upload has passed against a real instance for that exact release candidate.
Shipping an untested upload path that could touch graded work is not a trade worth making, so the
feature ships off rather than "probably fine".

**What is the difference between the preview and a verified upload?**
The **preview** shows the resolved course and Dropbox folder, the exact filename, byte size, and
SHA-256 of the staged copy, the endpoint and read-back route, and the phrase you must type. Nothing
has been sent at that point, and a non-interactive run stops there permanently.

A **verified** upload means: your typed phrase matched, exactly one POST was sent, and the
submissions list was then read back and contained exactly one record matching the folder, filename,
byte size, and a timestamp after your confirmation.

If read-back is ambiguous, missing, stale, size-mismatched, or unreadable, the result is reported as
**unknown** and you are told to check LEARN. Agent2Learn never retries a mutating request by itself,
and an unknown receipt cannot authorise a retry.

**Can I skip the confirmation in a script?**
No. There is no `--yes`, no `--force`, no environment variable, and piped input is not consent. A
controlling terminal proves interactivity, not identity — so the real protection against an agent
submitting on your behalf is the skill contract requiring it to stop at the preview and hand control
back to you.

**Group assignments?**
Not supported in v0.1. A group Dropbox is identified in the preview and then refused, with no
request sent. Submit those in LEARN.

## Licence and legal

**What licence?**
Apache-2.0. See [LICENSE](../LICENSE). Dependency licences are listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), which CI keeps current.

**Is this affiliated with Waterloo or D2L?**
No. Not affiliated with, endorsed by, or supported by either. See [DISCLAIMER.md](../DISCLAIMER.md).
You are responsible for using it within your course rules and institutional policies.

**Is `a2l check` allowed under my course's AI policy?**
That is your course's decision, not ours. Agent2Learn surfaces an AI-policy restriction from your
outline once, with a citation, when one is recorded — and never classifies an ambiguous policy.
`a2l check` produces no answers and no submit-ready work; it reports what lexical retrieval matched
in your own course files, with citations. Read your outline and ask your instructor.

## Reporting a bug

A good report contains:

1. What you ran, and what you expected.
2. What happened, including the exit code.
3. The output of **`a2l doctor --report`** — an allowlisted, redacted report designed to be safe to
   paste in public.
4. Your operating system and how you installed.

Do **not** attach a session, cookie, browser profile, real course material, or an unredacted
screenshot. `a2l doctor --open` opens a prefilled GitHub issue in your browser, and only when you
pass `--open`.
