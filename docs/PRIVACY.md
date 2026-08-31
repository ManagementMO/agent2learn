# Privacy

Agent2Learn is **local-first**: your course material, the manifest that tracks it, and every
report are written to a folder you choose on your own machine, and no Agent2Learn server receives
any of it. There is no Agent2Learn telemetry, no analytics, no crash reporting, and
no passive version check.

This page will not claim total isolation, because that would be false. Agent2Learn is a client for
a web service: it signs in to LEARN and downloads material from **your own account** over the
network. Below is every request it can make, and who else is involved.

## What is stored, and where

`<vault>` is the folder you approved during `a2l init`. `<config>` and `<state>` are the ordinary
per-user directories for your operating system.

| Data | Location | Default | Notes |
| --- | --- | --- | --- |
| Course files, outlines, assignment prompts and data | `<vault>/<term>/<course>/` | collected | The original bytes, exactly as LEARN served them. |
| Markdown twins | beside each original | collected | Generated locally, never uploaded. |
| Structured manifest and revision history | `<vault>/.a2l/` | collected | Source IDs, paths, SHA-256 digests, sizes, timestamps, and preserved earlier revisions of changed files. |
| Course index, content map, audit, snapshots | `<vault>/.a2l/`, `<course>/_meta/`, `<course>/INDEX.md` | collected | Local navigation and coverage reports. |
| Discussions | `<course>/_meta/` | **off** | Only if you enable them. Author names are pseudonymised. |
| Grades | `<course>/_meta/` | **off** | Only if you enable them. |
| LEARN API session | OS keyring, or a permission-restricted file if no keyring is available | required | The minimum cookies needed for the API, scoped to the LEARN origin. Nothing else from your browser. |
| Dedicated browser profile | `<state>/browser-profile/` | created on first `a2l auth` | A separate Chrome/Edge profile holding your LEARN sign-in and any Duo "remember this device" state. It is not your normal browser profile. |
| Configuration | `<config>/config.json` | created by `a2l init` | Vault path, school, and your collection choices. |
| Local log | `<state>` log directory | on | Bounded and redacted; no cookies, tokens, or request bodies. |
| Submission receipts | `<vault>/.a2l/submissions/` | only after an upload attempt | Course, folder id, filename, digest, size, timestamps, and outcome. Never absolute paths, identities, headers, bodies, or your confirmation phrase. |

## Every external network action

Agent2Learn makes no request on its own initiative. Each row below happens only because you ran
the command in the first column.

| When | Who is contacted | Why |
| --- | --- | --- |
| `a2l auth` (interactive) | Your LEARN host, plus the identity hosts the school adapter declares for sign-in — for Waterloo that is **Duo** (`duosecurity.com`) and the Waterloo ADFS hand-off (`adfs.uwaterloo.ca`), over HTTPS on the default port | To let you sign in yourself, in a real browser. Requests to hosts the adapter has not declared are blocked; an undeclared page or iframe stops the sign-in, and an undeclared optional subresource is failed without leaving your machine. |
| `a2l sync`, `a2l courses`, `a2l fetch`, `a2l today` after a sync | Your LEARN host only. The adapter may also declare first-party outline hosts, but Waterloo's list is currently empty, so nothing else is contacted | To read your own enrolment and material. Licensed and external targets are recorded as links and never fetched. |
| `a2l submit` | Your LEARN host | One upload, after your typed confirmation. Disabled in this build. |
| `install.sh` / `install.ps1` | **Astral** (`astral.sh`) for uv; the host serving the installer script | To install a pinned uv and then Agent2Learn. |
| Any install method | **PyPI** | To download Agent2Learn and its dependencies. |
| `a2l upgrade` | **PyPI** (`pypi.org`) once, per invocation | To read the latest published version. This is the only command that contacts the network on its own behalf. |
| `a2l doctor --open` | **GitHub** | Only when you pass `--open`; it opens a prefilled issue in your browser. |
| `npx skills add ManagementMO/agent2learn` | **npm** and **GitHub**, plus whatever that CLI does | This is a third-party tool with its own network behaviour and its own telemetry disclosures. It is not Agent2Learn code, and choosing this route means accepting its terms. It installs skill documents only, not the engine. |

Nothing here is a background task, a daemon, or a scheduled job. If you do not run a command,
Agent2Learn makes no requests at all.

### What those providers can see

Ordinary hosting, CDN, and package-registry **request logs** remain governed by those providers,
not by Agent2Learn. Downloading Agent2Learn from PyPI, fetching uv from Astral, or using the npm
route means those services see a request from your IP address in the normal way any download does.
Agent2Learn cannot and does not delete those logs.

Your institution can already see your LEARN activity, because it runs LEARN. Agent2Learn's
requests look like a client using the student API with your own permissions.

## Reports are redacted, on purpose

`a2l doctor` has two audiences and two different outputs:

- The **terminal** report is for you and may show local paths, because you already know them.
- The **shareable** report (`a2l doctor --report`) is built from an allowlist: version, Python,
  operating system and architecture, install method, and per check only a fixed identifier, a
  known status, and a fixed public note. Free-text detail and fix hints are never included,
  because they legitimately contain vault paths and course names. An allowlist is used rather than
  a blocklist so that a check added later cannot become a new way to leak.

## Deleting things

```bash
a2l privacy status                # what is collected, and where, with paths redacted
a2l privacy purge grades          # preview, then require a typed phrase
a2l privacy purge discussions
a2l privacy purge logs
a2l auth --clear-profile          # remove the dedicated browser profile and the saved session
```

Two honest limits:

- **Turning collection off never deletes anything.** It only stops future collection. Use
  `a2l privacy purge` for deletion.
- **`a2l privacy purge` is a logical deletion.** It removes the files and structured records it
  previews, from the vault. It cannot scrub your filesystem's free space, your backups, your
  Time Machine or File History snapshots, or a synced copy in a cloud folder. The preview says so.

To remove everything: purge what you want removed, run `a2l auth --clear-profile`, delete the vault
folder, delete `<config>/config.json`, then `uv tool uninstall agent2learn`. `a2l doctor` prints
the exact paths for your machine.

## Where the vault must not live

Do not put the vault inside a Git repository you push, or in a shared or public cloud folder.
Agent2Learn refuses to create a vault inside its own checkout and warns when it detects vault
files tracked by Git — tracked session-like files, grades, discussions, or submissions are a
failure, not a warning. A `.gitignore` is not a privacy control.
