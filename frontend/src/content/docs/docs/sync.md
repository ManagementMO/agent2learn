---
title: Your first sync
description: Bring courses local, choose download scope, and understand coverage.
---

After onboarding, refresh the vault with:

```bash
a2l sync
```

The command uses your saved course selection and download scope. It refreshes metadata first, then handles eligible outlines and files, creates Markdown twins, updates the indexes, and writes a snapshot and coverage report.

## Choose how much to download

| Command                          | Scope for this run                                |
| -------------------------------- | ------------------------------------------------- |
| `a2l sync`                       | Your saved onboarding choice.                     |
| `a2l sync --priority`            | A deterministic selection within a byte budget.   |
| `a2l sync --all`                 | Every eligible document in your selected courses. |
| `a2l sync --all --include-media` | Eligible documents plus audio and video.          |

`--all` and `--priority` are mutually exclusive. The flags override scope for this run. Media can use considerably more disk space and remains excluded without `--include-media`.

Some files have no reported size. They remain eligible for a full sync's bounded downloader, but cannot count as zero bytes in the priority budget.

## See what changed

```bash
a2l today
a2l diff
```

`today` shows local deadlines, overdue work, changes, and exam countdowns. Dates use Waterloo's `America/Toronto` time zone. `diff` compares local sync snapshots.

To take deadlines into your calendar:

```bash
a2l calendar -o deadlines.ics
```

Import the file into your calendar app. It is a local export, not a live subscription.

## Read coverage before assuming completeness

Open `.a2l/AUDIT.md` in your vault. It records missing downloads, conversion gaps, excluded links, and citable coverage. A sync can complete successfully **with recorded gaps**; a successful exit alone does not mean every file is available.

For an eligible topic that has not downloaded, use its source ID from the content map or diagnostic output:

```bash
a2l fetch SOURCE_ID
```

Replace `SOURCE_ID` with the actual ID. Licensed and external links are never downloaded by this command.

## Refreshing preserves your archive

Sync merges new information into the vault. Earlier captured revisions are preserved when upstream files change. Locally modified generated twins are saved in history before refresh. Your own drafts are not generated artifacts and are not overwritten.

If your session expires with **exit code 75**, run `a2l auth` yourself, finish sign-in, and retry the same sync. Other failures start with [troubleshooting](/docs/troubleshooting/).
