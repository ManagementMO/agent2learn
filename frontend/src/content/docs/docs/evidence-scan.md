---
title: Scan a draft
description: Understand the experimental lexical evidence scan and its limits.
---

`a2l check` is an **experimental lexical evidence scan**. It looks for matching and related text in your captured course material and gives you citations to review. It does not grade your work, determine correctness, or establish academic-policy compliance.

## Run a scan

```bash
a2l check draft.md --course "DEMO 101"
```

Replace the synthetic course selector with your own. If the draft is inside a course folder, the command can infer the course from its location.

To limit retrieval to the sources for an assignment:

```bash
a2l check draft.md --course "DEMO 101" --assignment "Problem Set 1"
```

Supported draft formats are `.md`, `.txt`, `.ipynb`, `.py`, `.r`, `.rmd`, and `.tex`. Notebook content is read without execution.

## Read the results

| Status                 | What to do with it                                                               |
| ---------------------- | -------------------------------------------------------------------------------- |
| `evidence_found`       | Matching source text was found. Read the citation and its context.               |
| `related_evidence`     | Related material exists. Decide whether it applies to the claim.                 |
| `no_matching_evidence` | No local source cleared the threshold. Check wording and coverage.               |
| `possible_conflict`    | Compare the cited spans yourself. This is not a finding that your work is wrong. |
| `skipped`              | The text was treated as structure or could not be meaningfully scanned.          |

The same word can appear in an incorrect claim and a correct source. Different wording can hide a useful connection. A missing match is not proof that the course omits an idea.

## Incomplete coverage changes what can be found

The scan reuses grounding's eligible source set. It cannot use unfetched documents, unavailable Markdown twins, or files whose current bytes fail integrity checks.

If an assignment's wording matches no eligible material, try a whole-course scan. If the course itself lacks current source-backed material, read the audit and use the indicated sync or fetch command.

## Machine-readable output

```bash
a2l check draft.md --course "DEMO 101" --format json
```

Add `--strict` to request a nonzero exit for results needing review. This is a workflow reminder; its exit status is not a verdict on correctness or permission to submit.
