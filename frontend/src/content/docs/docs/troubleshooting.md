---
title: Troubleshooting
description: One useful next step for common installation, authentication, and coverage problems.
---

Start here:

```bash
a2l doctor
```

It checks your local installation and vault, explains the result, and names one next command.

## My terminal cannot find a2l

After a successful install, open a new terminal. Existing terminals can retain an old PATH, especially on Windows.

If needed, inspect uv's tool directory:

```bash
uv tool dir --bin
```

If `a2l` is already there, repair or refresh your shell's PATH rather than installing another copy. `uv tool update-shell` updates future shell sessions.

## Sign-in stopped, or a command exited with 75

```bash
a2l auth
```

Complete WatIAM and Duo in the dedicated window, then retry. If browser launch is unavailable, use the supported hidden-input `a2l auth --paste` path on the same device. Read [authentication](/docs/authentication/) for details.

## Setup stopped at a metadata gap

A metadata category could not be read. Initialization keeps completed work and stops before file downloads rather than recording metadata as complete.

Rerun `a2l init`. It resumes the saved stages and can reuse a valid session for the same LEARN origin.

## Sync finished, but something is missing

Read `.a2l/AUDIT.md` and the course's `_meta/content_map.json`.

| Recorded situation                           | Next step                                                       |
| -------------------------------------------- | --------------------------------------------------------------- |
| Eligible source was not downloaded           | Run the indicated `a2l fetch SOURCE_ID`.                        |
| A download endpoint keeps failing            | Keep the recorded gap; fetch or a later sync can retry.         |
| Intact original, but no usable Markdown twin | Fix the recorded conversion cause, then sync.                   |
| Integrity mismatch                           | Inspect the local source and follow the repair advice.          |
| Licensed, external, or LTI target            | Open the link yourself in LEARN. Agent2Learn will not fetch it. |

A recorded remote gap can coexist with a successful sync. Local failures such as insufficient disk space still stop the operation.

## A scanned PDF has little text

Scanned pages need external Tesseract. `a2l doctor` reports whether it is installed and gives the next step. After installing the appropriate Tesseract build for your OS, rerun `a2l sync`.

The original PDF stays in your vault even when its Markdown conversion has a gap.

## Grounding found no sources for an assignment

If the course has source-backed material but none matches the assignment's terms, syncing may not change the result. Inspect the course index and source files. For a scoped draft scan, try omitting `--assignment` to search the whole course.

If two assignments share a title, use the Dropbox ID or exact folder selector named by the error.

## How do I remove Agent2Learn?

```bash
uv tool uninstall agent2learn
```

This removes the engine, not your vault or sign-in state. Before uninstalling, use the relevant [privacy commands](/docs/privacy/) if you want to purge sensitive categories or clear the dedicated profile. Deleting the vault folder is a separate decision.

## Still stuck?

```bash
a2l doctor --report
```

Include that report, your operating system, the command you ran, and what you expected in a [GitHub issue](https://github.com/ManagementMO/agent2learn/issues). Never attach session files, cookies, browser profiles, real course material, or unredacted screenshots.
