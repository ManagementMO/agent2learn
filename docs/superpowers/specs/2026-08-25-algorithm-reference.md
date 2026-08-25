# Algorithm reference — the parts the prose only gestured at

- **Date:** 2026-08-25
- **Status:** normative supplement to the public release design spec
- **Audience:** an implementer with **no access to the private prototype**

## Why this document exists

A cold-read audit of the public repository — performed by a reader deliberately denied the private
prototype — put overall buildability at roughly **65%**, and found the shortfall concentrated in
exactly the wrong place:

| Area | Buildable from the docs alone |
| --- | --- |
| `paths.py`, `config.py`, `vault.py` | 100% |
| `index.py`, `snapshot.py` | 95% |
| `api.py`, `convert.py` | ~70% |
| `ingest.py` | 60% |
| **`check.py`** | **50%** |
| **`ground.py`** | **30%** |

The pattern is instructive. **The best-specified modules are the ones that were redesigned; the
worst-specified are the ones that were going to be ported.** `paths.py` scores 100% because every
naming decision was argued out and written down. `ground.py` scored 30% because the plan said
"implement from the approved grounding contract" — and a contract describes intent, not an
algorithm.

That is an ironic failure mode, because the lexical subsystem is the **only substantially new code
in v0.1** and the entire product differentiator. Left unspecified, an implementer invents a
tokeniser and a stopword list, `a2l check` produces different verdicts than the prototype, the
tuned constants become meaningless, and `check_algorithm_version = 1` names an unknown algorithm.

Everything below is stated so it can be implemented **without reading any private source**. Where a
value looks arbitrary it is: these are the constants the prototype actually ran with, and changing
one is a behavioural change requiring a version bump, not a refactor.

---

## 1. The tokeniser

Shared by `ground.py`, `check.py`, and the notation check. One implementation, one import site.

```python
def tok(s: str) -> list[str]:
    """Tokenise, splitting letter/digit boundaries so 'Lab4' -> ['lab4', 'lab', '4']."""
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if len(w) > 1 or w.isdigit():
            out.append(w)
        parts = re.findall(r"[a-z]+|[0-9]+", w)
        if len(parts) > 1:
            out.extend(p for p in parts if len(p) > 1 or p.isdigit())
    return out
```

Behaviour that matters, and is easy to get subtly wrong:

- **Case-folded first.** Everything is lowercased before matching.
- **Only `[a-z0-9]` runs survive.** Punctuation, underscores, and hyphens are separators, not
  characters. `lab_4` and `lab-4` both yield `['lab', '4']`.
- **The whole run is emitted *and* its parts**, when the run is mixed. `Lab4` yields **all three** of
  `lab4`, `lab`, `4`. This is deliberate: it lets `Lab4` match both `Lab 4` and `lab4`.
- **A pure run emits itself only.** `lab` yields `['lab']`; the split branch adds nothing because
  there is only one part.
- **Single letters are dropped, single digits are kept.** `len(w) > 1 or w.isdigit()` — so the `4` in
  `Lab 4` survives but a stray `a` does not.
- **Non-ASCII is discarded.** `[a-z0-9]` does not match accented characters, so `Café` tokenises to
  `['caf']`. Acceptable for retrieval over English course material; **note it as a known limitation**
  rather than silently widening the class, because widening it changes every score.

Worked examples — use these as test cases:

| Input | Output |
| --- | --- |
| `Lab4` | `['lab4', 'lab', '4']` |
| `LAB4` | `['lab4', 'lab', '4']` |
| `lab_4` | `['lab', '4']` |
| `Lab 4` | `['lab', '4']` |
| `Lab4A` | `['lab4a', 'lab', '4']` — trailing single letter `a` is dropped |
| `Assignment 1` | `['assignment', '1']` |
| `Café` | `['caf']` |

---

## 2. The `GENERIC` stopword set

Verbatim. **Not** a general English stopword list — it is a *coursework* stopword list, removing the
words that appear in nearly every assignment title and therefore carry no discriminating signal.

```python
GENERIC = {
    "take", "home", "activity", "lab", "the", "and", "for", "assignment", "part",
    "week", "solution", "in", "class", "copy", "of", "to", "a", "an",
}
```

Eighteen entries. Adding or removing one changes every retrieval score, so the set is **versioned
with the algorithm**: any edit requires bumping `check_algorithm_version` and regenerating fixtures.

Note that `lab`, `week`, and `assignment` are stopwords while `lab4` is not — which is precisely why
the tokeniser emits the unsplit run as well as its parts.

---

## 3. Lecture ranking (`ground.rank_lectures`)

```python
def rank_lectures(course_dir, task_text, exclude, top=12):
    qcount = Counter(t for t in tok(task_text) if t not in GENERIC)
    scored = []
    for md in (course_dir / "content").rglob("*.md"):
        if md in exclude:
            continue
        words = Counter(tok(md.read_text(errors="ignore")[:20000]))
        score = sum(min(qcount[w], 3) * c for w, c in words.items() if w in qcount)
        if score:
            scored.append((score, md))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top]]
```

The load-bearing details:

- **Query terms are counted, then capped at 3.** `min(qcount[w], 3)` stops a term repeated ten times
  in the task from dominating the ranking.
- **Source terms are *not* capped.** A lecture mentioning the term twenty times outranks one
  mentioning it twice.
- **Only the first 20,000 characters** of each twin are read. A bound on cost, and it biases toward
  material appearing early in a document.
- **Zero-score documents are excluded entirely**, not ranked last.
- **`top` defaults to 12.**
- Ties break on whatever order `rglob` yields, which is **not** deterministic across platforms.
  **This is a real defect for a project whose golden-vault test demands byte-identical output.** Fix
  it on implementation by sorting with an explicit key — `(-score, str(path))` — and record the
  change. It is called out here rather than reproduced faithfully.

---

## 4. Download route candidates

Four, tried in order, first success wins. Duplicates are skipped via a seen-set.

1. **The calibrated template**, if calibration has proven one for this instance, with `{ou}` and
   `{tid}` substituted.
2. `{base}/d2l/le/content/{ou}/topics/files/download/{tid}/DirectFileTopicDownload`
3. `{base}/d2l/api/le/{le}/{ou}/content/topics/{tid}/file`
4. The topic's own `Url` field, resolved against the base URL — **only when it is first-party.** An
   external or licensed target is a link stub and must never reach this list.

Calibration exists so that route 1 removes three failed round-trips per file on a known instance.

### The `is_html_topic` exception

The client treats an HTML response body as an expired session. That heuristic destroys **genuinely
HTML topics**, so it is suppressed for them:

```python
is_html_topic = str(url_field).lower().endswith((".html", ".htm")) or ttype == "html"
if "text/html" in content_type and not is_html_topic:
    ...treat as a login page and fail this candidate...
```

A topic counts as legitimately HTML when its URL ends `.html`/`.htm` **or** its type identifier is
`html`. For those, an HTML body is the expected payload.

> This heuristic is genuinely weak: a login page served for a real `.html` topic passes straight
> through and is archived as course content. Strengthen it on implementation — the login page is
> recognisable by its form action and title — and add a fixture for exactly that case.

---

## 5. HTTP politeness constants

| Constant | Value | Note |
| --- | --- | --- |
| `THROTTLE` | `0.05` s | Sleep after every successful request. |
| `MAX_RETRIES` | `5` | Total attempts, not additional ones. |
| Request timeout | `90` s | Prototype used a single value; the spec requires **separate connect and read timeouts** — use `(10, 90)`. |
| Backoff base | `1.0` s | Doubled after each 429. |
| Workers | `2` | Reduced from the prototype's 4, per the politeness requirement. |

429 handling: honour `Retry-After` when present, otherwise sleep the current backoff, then double
it. The prototype **does not cap** `Retry-After`; the public build must, per the spec.

**Jitter is specified nowhere in the prototype — it did not have any.** It is a public-build
addition, so choose and document it: stagger worker starts by `random.uniform(0, 0.5)` seconds so
two workers do not issue their first request in the same millisecond. Seed-free; it affects timing
only, never output bytes.

---

## 6. Other constants referenced but never given

| Constant | Value | Where |
| --- | --- | --- |
| `MIN_PDF_CHARS` | `200` | Below this the PDF text layer is treated as empty and OCR runs. Distinct from the converter's per-page threshold of **80 words/page** — one is a whole-document trigger, the other a per-page decision. Do not conflate them. |
| Free-disk reserve | not in the prototype | Public addition. Suggest **1 GiB**, configurable. |
| Per-file ceiling | not in the prototype | Public addition. **2 GiB**, per the spec. |
| Page markers | not in the prototype | Public addition. Emit a stable, greppable marker; `<!-- a2l:page N -->` keeps it invisible in rendered markdown while remaining line-addressable for citations. |

---

## 7. `INDEX.md` structure

The prototype generated this ad hoc, and the public spec describes its *content* without fixing its
*shape*. Since `INDEX.md` is a golden-vault artifact, the shape must be pinned on implementation.
Choose a structure, write it into the design spec, and generate a fixture — do not leave it to the
formatter.

At minimum it carries: course code and term, deadlines, the module/topic tree with relative links,
coverage summary, and the AI-policy citation when one was found.

---

## Standing rule

**Anything in this document that reads like a description rather than a rule is a defect in this
document.** If an implementer has to guess, the gap is here, not in their judgement — fix it here so
the next reader does not guess differently.
