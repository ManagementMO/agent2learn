# Agent2Learn

> Your courses, as a vault your agent can actually read.

Agent2Learn is a local-first tool in active development for University of Waterloo students. It
turns the material available through a student's own LEARN account into a revision-safe,
Markdown-twinned vault that coding agents can navigate and cite.

The repository contains the tested implementation through Task 17, including the `a2l` command,
offline synthetic fixtures, cross-platform filesystem handling, revision-safe vault state, bounded
D2L transport, conversion, indexing, auditing, redacted diagnostics, local daily study views,
deterministic calendar export, snapshot diffs, navigation, and preview-first privacy controls. It
is still **not a v0.1 package release**: nothing is published to PyPI, Task 9's live same-device
validation remains a release gate, and implementation resumes at Task 18.

## Local study surface

After `a2l init` and a local sync, the read-only study commands are:

```text
a2l today                         deadlines, overdue work, changes, and exam countdowns
a2l diff [--since SNAPSHOT]       changes between local sync snapshots
a2l calendar [-o FILE]            deterministic deadlines/exams/office-hours .ics export
a2l where QUERY                   fuzzy topic search across every local term
a2l open COURSE                   reveal one known course folder
a2l privacy status                collection flags and redacted storage locations
a2l privacy purge CATEGORY        preview an exact grades/discussions/logs purge
```

Sensitive categories remain opt-in. Purge is deliberately preview-first and requires a fresh
interactive confirmation; disabling collection alone never deletes existing local data.

Start here:

- [Implementation context](AGENTS.md)
- [Approved public-release design](docs/superpowers/specs/2026-08-24-agent2learn-public-release-design.md)
- [Implementation plan](docs/superpowers/plans/2026-08-24-agent2learn-public-release.md)
- [Launch plan](docs/LAUNCH.md)
- [Licence](LICENSE) and [project disclaimer](DISCLAIMER.md)
