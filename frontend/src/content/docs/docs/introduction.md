---
title: A course vault your agent can read.
description: What Agent2Learn does, and where to start.
---

Agent2Learn turns the material available through **your own Waterloo LEARN account** into a local folder of original files, readable Markdown, and navigable course indexes. Your coding agent can use that material as context and point you back to the exact source lines it read.

You keep the files. Open them in your editor, Obsidian, or an agent that can read local files. The vault remains useful when Agent2Learn is not running.

## The everyday workflow

1. **Set up once.** Choose a vault folder, sign in on your own device, and select your courses with `a2l init`.
2. **Bring your material local.** Run `a2l sync` to refresh course metadata, download eligible files, and create Markdown twins.
3. **Study from sources.** Ask your agent a question, follow its citations, and inspect the course material yourself.

Start with the [installation guide](/docs/installation/), or [give your agent the setup prompt](/docs/for-agents/).

## What you get

| In your vault                     | What it is for                                                  |
| --------------------------------- | --------------------------------------------------------------- |
| Original files and Markdown twins | Keep the source and read its text side by side.                 |
| A course `INDEX.md`               | Find modules, assignments, deadlines, and local coverage.       |
| Grounding packs                   | Gather current, source-backed material for an assignment.       |
| Revision history                  | Preserve earlier captured files when upstream material changes. |
| A coverage report                 | See what is missing, excluded, or could not be converted.       |

The [vault guide](/docs/vault/) shows how these fit together.

## A few useful things to ask

- “Explain this concept using my lecture notes, and cite the lines you use.”
- “Find the sources I need to work through this assignment.”
- “What is due this week?”
- “Scan my draft for matching course evidence and show me the sources to review.”

The last request uses `a2l check`, an **experimental lexical evidence scan**. It finds overlapping text; it does not decide whether an answer is correct or whether your use of AI is permitted.

## Know the boundaries

Agent2Learn is an independent project for University of Waterloo LEARN. It has no hosted course storage or product telemetry. Grades and discussions are off by default, licensed third-party content stays as links, and **uploads are disabled in this build**.

Use your course's AI policy and assignment instructions to decide what assistance is permitted. The [privacy guide](/docs/privacy/) explains what is stored and which network requests the tool makes.

Agent2Learn is not affiliated with, endorsed by, or supported by the University of Waterloo or D2L Corporation.
