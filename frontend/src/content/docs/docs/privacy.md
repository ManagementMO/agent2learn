---
title: Privacy
description: What stays local, what is collected, and what uses the network.
---

Agent2Learn stores your course material and reports in the vault you choose. It has **no runtime backend, hosted course storage, product telemetry, crash reporting, or passive update checks**.

It still uses the network when you ask it to sign in, sync, or install. Local storage does not mean total network isolation.

## Defaults

| Data or action                                         | Default                          |
| ------------------------------------------------------ | -------------------------------- |
| Your course files, outlines, and assignment metadata   | Collected into your local vault. |
| Markdown twins, indexes, coverage reports, and history | Generated locally.               |
| Grade values                                           | Off.                             |
| Discussions                                            | Off.                             |
| Uploads to LEARN                                       | Disabled in this build.          |
| Licensed publisher and library resources               | Kept as links; never downloaded. |
| Agent2Learn telemetry                                  | None.                            |

Your API session and dedicated browser profile are stored in the operating system's user directories, outside the course vault. The session uses a keyring where available, with a permission-restricted file fallback.

## What uses the network

- **Authentication:** your configured LEARN origin and declared identity-provider hosts during interactive sign-in. A session check also contacts LEARN.
- **Sync and fetch:** LEARN for your own course data. Outline rendering is limited to LEARN and any separately declared first-party outline hosts.
- **Installation:** the chosen installer host, Astral when installing uv, and PyPI for the engine and dependencies.
- **Upgrade:** PyPI, only when you invoke the command.
- **Support:** GitHub when you request `a2l doctor --open`.
- **Optional skills CLI:** npm, GitHub, and that third-party tool's own documented services.

Package and hosting providers retain their ordinary request logs under their own policies. There is no Agent2Learn background sync or update daemon.

Your coding agent is separate software. If you give local files to an agent using a hosted model, their contents may be sent to that provider under its settings. Decide which files your agent can access and follow your course rules.

## See collection state

```bash
a2l privacy status
```

This shows collection flags and redacted storage categories. Grade and discussion collection follow saved configuration. Turning collection off stops future capture; it does not delete existing records.

## Delete captured sensitive categories

```bash
a2l privacy purge grades
a2l privacy purge discussions
a2l privacy purge logs
```

Each command previews its exact targets and requires your typed confirmation in a terminal. Deletion is logical: it cannot scrub backups, filesystem free space, OS snapshots, or copies in synced folders.

To remove the dedicated browser profile and saved session, run `a2l auth --clear-profile` and confirm the preview.

## Keep your vault private

Keep it outside a Git repository you push and outside shared or public cloud folders. Ignore rules alone do not prevent disclosure. Uninstalling the engine does not delete the vault.

For support, share `a2l doctor --report`. Ordinary `doctor` output can contain local paths; the `--report` version uses an allowlist intended for public sharing.

The [full data-flow record](https://github.com/ManagementMO/agent2learn/blob/main/docs/PRIVACY.md) covers storage and network behavior in more detail. Report security issues through the [private security reporting guidance](https://github.com/ManagementMO/agent2learn/blob/main/SECURITY.md).
