---
title: Command reference
description: The complete v0.1 command surface, grouped by what you want to do.
---

The engine's command is `a2l`. Run `a2l --help` for the command list, or append `--help` to a command for its exact arguments and options.

```bash
a2l --version
a2l sync --help
```

`COURSE`, `ITEM`, `FILE`, and `SOURCE_ID` below are placeholders for your local course selector, assignment selector, file, and source ID. Quote names that contain spaces.

## Setup and maintenance

| Command                    | Purpose                                                     |
| -------------------------- | ----------------------------------------------------------- |
| `a2l init`                 | Create or resume interactive onboarding.                    |
| `a2l init --vault PATH`    | Preview a specific vault location.                          |
| `a2l auth`                 | Sign in using the dedicated browser profile.                |
| `a2l auth --check`         | Check the saved session without opening a browser.          |
| `a2l auth --paste`         | Use hidden input in your own terminal on the same device.   |
| `a2l auth --clear-profile` | Confirm removal of the dedicated profile and saved session. |
| `a2l doctor`               | Diagnose local state and get one next command.              |
| `a2l doctor --report`      | Print an allowlisted report designed for public support.    |
| `a2l doctor --open`        | Open a prefilled GitHub issue in your browser.              |
| `a2l upgrade --check`      | Check PyPI for a newer version without installing it.       |
| `a2l upgrade`              | Upgrade the engine and handle managed skill refreshes.      |
| `a2l completions SHELL`    | Print completions for bash, zsh, fish, powershell, or pwsh. |

The three authentication options are mutually exclusive. `auth` and `init` require your participation; an agent must hand interactive sign-in back to you.

## Courses and synchronization

| Command                             | Purpose                                                |
| ----------------------------------- | ------------------------------------------------------ |
| `a2l courses`                       | Read the saved enrolment view offline.                 |
| `a2l courses --all-terms`           | Include every discovered term.                         |
| `a2l courses --json`                | Print machine-readable enrolment metadata.             |
| `a2l sync`                          | Refresh the saved course selection and download scope. |
| `a2l sync --all`                    | Fetch all eligible documents in that selection.        |
| `a2l sync --priority`               | Use the byte-bounded priority scope.                   |
| `a2l sync --include-media`          | Include audio and video for this run.                  |
| `a2l fetch SOURCE_ID`               | Fetch or repair one known eligible source.             |
| `a2l fetch SOURCE_ID --allow-large` | Preview and confirm a one-file size override.          |

`--all` and `--priority` cannot be combined. No fetch option enables licensed external downloads.

## Daily use and source navigation

| Command                     | Purpose                                                           |
| --------------------------- | ----------------------------------------------------------------- |
| `a2l today`                 | Show local deadlines, overdue work, changes, and exam countdowns. |
| `a2l diff`                  | Compare local sync snapshots.                                     |
| `a2l diff --since SNAPSHOT` | Compare from a specified snapshot.                                |
| `a2l calendar -o FILE`      | Write an iCalendar export.                                        |
| `a2l where QUERY`           | Search local topic maps across terms.                             |
| `a2l open COURSE`           | Reveal a local course directory in your file manager.             |
| `a2l ground COURSE ITEM`    | Write an assignment grounding pack with source citations.         |

These views use your local vault. Refresh with `a2l sync` when you need current LEARN data.

## Experimental evidence scan

```bash
a2l check FILE --course COURSE
a2l check FILE --course COURSE --assignment ITEM
a2l check FILE --course COURSE --format json
a2l check FILE --course COURSE --strict
```

`--course` can be omitted when the draft's location identifies its course. `--format` accepts `md` (default) or `json`. `--strict` requests a nonzero exit for findings needing review.

Every result is retrieval evidence. It is not a correctness, grading, or academic-policy verdict. Read [how to interpret a scan](/docs/evidence-scan/) before relying on its statuses.

## Agent skills

| Command                             | Purpose                                                         |
| ----------------------------------- | --------------------------------------------------------------- |
| `a2l skills install`                | Preview and install the four skills for the configured project. |
| `a2l skills install --project PATH` | Target detected agent directories under a specific project.     |
| `a2l skills install --global`       | Target detected user-level skill directories.                   |
| `a2l skills install --link`         | Opt into links instead of the default copies.                   |
| `a2l skills install --force`        | Explicitly refresh managed skill directories after preview.     |

`--project` and `--global` are mutually exclusive. Use the preview to see exactly which files will change.

## Privacy and submission

| Command                         | Purpose                                                             |
| ------------------------------- | ------------------------------------------------------------------- |
| `a2l privacy status`            | Show collection flags and redacted storage categories.              |
| `a2l privacy purge grades`      | Preview and confirm deletion of captured grades.                    |
| `a2l privacy purge discussions` | Preview and confirm deletion of captured discussions.               |
| `a2l privacy purge logs`        | Preview and confirm deletion of local logs.                         |
| `a2l enable-submit`             | Acknowledge uploads locally, only in a release with the capability. |
| `a2l submit COURSE ITEM FILE`   | The gated submission path; unavailable in this build.               |

**Uploads are disabled in this build.** Acknowledgement cannot override the release capability. In a future enabled build, every individual upload would still require a complete preview and a fresh confirmation typed by the user. Group submissions are outside v0.1's mutation scope.

## Exit codes worth recognizing

- **75:** the LEARN session expired. Re-authenticate, then retry the original command.
- A sync may exit successfully while reporting coverage gaps. Read `.a2l/AUDIT.md`.
- A strict evidence scan's nonzero exit means review is needed, not that an answer is incorrect.
