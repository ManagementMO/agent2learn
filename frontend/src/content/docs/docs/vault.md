---
title: The vault
description: An ordinary folder, with originals, Markdown twins, indexes, and revision history.
---

A vault is a directory you approve during `a2l init`. By default, it is `~/agent2learn` on macOS and Linux, or `%USERPROFILE%\agent2learn` on Windows. It is separate from this project's source checkout.

## A map of the files

This example is simplified. Term, course, and module names come from your enrolment and course content tree.

```text
agent2learn/
├── README.md
├── .a2l/
│   ├── manifest.json
│   ├── AUDIT.md
│   ├── history/
│   └── snapshots/
└── <term>/
    └── <course>/
        ├── INDEX.md
        ├── content/
        │   └── <module>/
        │       ├── lecture.pdf
        │       └── lecture.md
        ├── assignments/
        │   └── <title> <dropbox-id>/
        │       ├── README.md
        │       ├── instructions.html
        │       ├── instructions.md
        │       └── GROUNDING.md
        └── _meta/
            ├── content_map.json
            ├── assignments.json
            └── ai_policy.json
```

Assignment instructions appear when LEARN provides them. `GROUNDING.md` appears only after you run `a2l ground`.

## Start with the index

The vault's `README.md` points to terms and courses. Each course's `INDEX.md` maps its modules, deadlines, assignments, and coverage. It follows the course hierarchy; it does not assume every instructor organizes material by week.

## Originals and twins

An original file holds captured source bytes. Its adjacent Markdown twin is a locally generated text representation. The manifest records their relationship and hashes, so retrieval does not rely on similar filenames to decide what can be cited.

Conversion can omit a diagram or struggle with a scanned page. The original remains available for inspection, and the coverage report records known gaps.

## Availability is explicit

`_meta/content_map.json` distinguishes metadata-only records, downloaded sources, usable twins, download or conversion gaps, integrity mismatches, unsupported formats, and excluded links.

An external or licensed target becomes a link stub. Seeing a topic in the index does not imply its contents were downloaded.

## Revisions and your own work

Captured source revisions and changed generated twins are preserved under `.a2l/history/`. A locally modified twin is preserved before refresh. Keep your drafts as separate user files; the engine does not treat them as course evidence.

Manifest paths are relative to the vault. To move it, move the folder and run `a2l init` to approve the new location, then run `a2l doctor`.

Browser profiles and saved sessions are machine state, stored separately. [Authenticate independently](/docs/authentication/) on each computer; never move sign-in state with a vault.
