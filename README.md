# Agent2Learn

> Your own course material, on your own machine, as a vault your coding agent can read and cite.

Agent2Learn turns the material available through your own University of Waterloo LEARN account into
a durable local vault: original files beside Markdown twins, a stable index, and citations that
resolve to ordinary paths and line numbers. Your agent stops guessing about your course and starts
quoting it.

## Install

For most students, use the command for your operating system. In a real terminal it installs
Agent2Learn and starts guided setup immediately. If you already have uv, use the uv option below.

**macOS and Linux**

```bash
(installer="$(curl -fsSL https://raw.githubusercontent.com/ManagementMO/agent2learn/main/install.sh)" && bash -c "$installer")
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/ManagementMO/agent2learn/main/install.ps1 | iex
```

**Already have [uv](https://docs.astral.sh/uv/)?**

Bash or zsh:

```bash
uv tool install agent2learn && uv tool run --from agent2learn a2l init
```

Windows PowerShell:

```powershell
uv tool install agent2learn; if ($LASTEXITCODE -eq 0) { uv tool run --from agent2learn a2l init } else { throw "Agent2Learn installation failed" }
```

These uv commands start setup through uv itself, so a newly installed `a2l` does not need to be
on the current shell's PATH first. `uv tool install agent2learn` remains the install-only command.

These commands install the published package from PyPI, not an unreleased repository checkout.
Python 3.11–3.14 is supported. If uv selects an older system Python or your shell cannot find
`a2l`, see [setup troubleshooting](https://github.com/ManagementMO/agent2learn/blob/main/docs/FAQ.md#setup-and-path).

`install.sh` and `install.ps1` install a pinned Agent2Learn (currently 0.1.3), verify that `a2l`
runs, and then **continue straight into interactive `a2l init`** in the same command. The
macOS/Linux launcher waits for a successful download and preserves your terminal for setup prompts.
If a script runs without a terminal on both ends, such as in CI or a headless agent tool, it stops
after verification and prints the next step instead of setting anything up.

Neither script needs administrator rights or creates a vault, installs agent skills, or opens a
browser by itself. Onboarding does those things after showing you a preview and asking; you still
complete LEARN sign-in and Duo yourself. Already-open terminals or agents may need to be restarted
to pick up the new executable path, but you do not need to repeat completed setup.

### Agent skills

`a2l init` offers to run `a2l skills install`, which writes the four Agent2Learn skills into the
agent directories it finds, after previewing exactly what it will touch. You can rerun
`a2l skills install` at any time.

Separately, `npx skills add ManagementMO/agent2learn` is an optional skills-only route through the
skills ecosystem. It **does not install** the `a2l` engine — only the skill documents — so the
commands they describe will not exist until you install Agent2Learn itself with one of the three
options above. That route also runs a third-party CLI with its own network behaviour; see
[docs/PRIVACY.md](https://github.com/ManagementMO/agent2learn/blob/main/docs/PRIVACY.md).

## Then just ask

Once `a2l init` finishes, talk to your agent normally:

- "Read my ECON 101 outline and tell me what the late policy actually says."
- "Assemble the sources for Lab 4, then explain the model using only those files."
- "Scan my draft against my own course notes and show me what has no matching evidence."
- "What is due this week, and which lectures cover it?"

Your agent has the skills to run the right commands. If you would rather drive it yourself:

```text
a2l sync [--all|--priority]      metadata, outlines, files, twins, index, snapshot, audit
a2l today                        deadlines, overdue work, changes, and exam countdowns
a2l diff [--since SNAPSHOT]      changes between local sync snapshots
a2l calendar [-o FILE]           deterministic deadlines/exams/office-hours .ics export
a2l where QUERY                  fuzzy topic search across every local term
a2l open COURSE                  reveal one known course folder
a2l ground COURSE ITEM           assemble a cited grounding pack for one assignment
a2l check DRAFT                  experimental lexical evidence scan of a draft
a2l courses                      the offline view of your enrolment
a2l fetch SOURCE_ID              repair one missing file
a2l auth                         sign in, or --paste a session, or --clear-profile
a2l doctor                       diagnose one problem and get one next step
a2l skills install               install the agent skills
a2l privacy status               collection flags and redacted storage locations
a2l privacy purge CATEGORY       preview an exact grades/discussions/logs purge
a2l upgrade [--check]            the only command that contacts the network on its own
a2l completions SHELL            print a completion script; installs nothing
a2l enable-submit                one-time local acknowledgement for uploads
a2l submit COURSE ITEM FILE      preview an upload, then require your typed confirmation
```

## What this does, and what it does not

**It does:**

- Read **your own account only**, using your own browser session on the same device.
- Work **read-mostly**: ordinary GET requests against D2L's own student API, which enforces exactly
  the permissions your account already has. It cannot reach anything you could not open yourself.
- Keep originals beside Markdown twins, with a manifest that preserves earlier revisions when a file
  changes upstream.
- Tell you what is **missing** and why, rather than implying the archive is complete.

**It does not:**

- Download licensed eTextbooks or library e-resources. Those are recognised and **never** fetched;
  they are recorded as links for you to open in LEARN yourself.
- Collect discussions or grades. Both are **off by default** and only ever collected if you turn
  them on.
- Send Agent2Learn telemetry. There is none, so there is nothing to opt out of, and no passive
  version check. `a2l upgrade` contacts PyPI only when you run it.
- Upload anything by default. The submission path is **disabled in this build**. Even when enabled,
  every single file requires a fresh confirmation phrase that you type at your own terminal, after
  a full preview.
- Decide whether your work is right. `a2l check` reports what lexical retrieval matched in your own
  course files, with citations, and says plainly when it found nothing. It does not grade, and no
  status it prints means your work is correct, incorrect, or academically acceptable.

Agent2Learn is **not affiliated with, endorsed by, or supported by the University of Waterloo or
D2L Corporation**. You are responsible for using it within your course rules and your institution's
policies. See [DISCLAIMER.md](https://github.com/ManagementMO/agent2learn/blob/main/DISCLAIMER.md).

## Privacy defaults

| Setting | Default |
| --- | --- |
| Course files, outlines, assignment metadata | collected |
| Discussions | **off** |
| Grades | **off** |
| Uploads to LEARN | **disabled in this build**, and always confirmation-gated |
| Agent2Learn telemetry | none |
| Passive version or update checks | none |

Turning collection off does not delete what is already on disk; `a2l privacy purge` does that, and
it previews the exact targets and requires a typed phrase first. Full detail, including every
external request Agent2Learn can make, is in [docs/PRIVACY.md](https://github.com/ManagementMO/agent2learn/blob/main/docs/PRIVACY.md).

## Documentation

- [Install guide for agents](https://github.com/ManagementMO/agent2learn/blob/main/docs/install.md) — point your agent here and let it handle setup.
- [Authentication](https://github.com/ManagementMO/agent2learn/blob/main/docs/AUTHENTICATION.md) — the dedicated profile, Duo, expiry, and recovery.
- [Privacy](https://github.com/ManagementMO/agent2learn/blob/main/docs/PRIVACY.md) — what is stored, where, every network action, and how to delete it.
- [FAQ](https://github.com/ManagementMO/agent2learn/blob/main/docs/FAQ.md) — the things that actually go wrong.
- [Porting to another school](https://github.com/ManagementMO/agent2learn/blob/main/docs/PORTING.md) — the `School` protocol and a worked reference.
- [What is deferred, and why](https://github.com/ManagementMO/agent2learn/blob/main/docs/FUTURE.md)
- [Security policy](https://github.com/ManagementMO/agent2learn/blob/main/SECURITY.md) · [Disclaimer](https://github.com/ManagementMO/agent2learn/blob/main/DISCLAIMER.md) · [Licence](https://github.com/ManagementMO/agent2learn/blob/main/LICENSE) ·
  [Third-party notices](https://github.com/ManagementMO/agent2learn/blob/main/THIRD_PARTY_NOTICES.md)

## Status

Agent2Learn is available on [PyPI](https://pypi.org/project/agent2learn/).
The latest [GitHub release](https://github.com/ManagementMO/agent2learn/releases/latest) carries the
same verified wheel and source distribution. Use one install command above to start guided setup.
If you are already installed or resuming setup, run `a2l init` in your terminal.

The project remains in active development. Release checks are documented in
[docs/LAUNCH.md](https://github.com/ManagementMO/agent2learn/blob/main/docs/LAUNCH.md), including same-device authentication and a fresh supervised upload
test before submission capability can be enabled. **LEARN uploads remain disabled in this build.**

Licensed under [Apache-2.0](https://github.com/ManagementMO/agent2learn/blob/main/LICENSE).
