# Agent2Learn — Launch Plan

- **Date:** 2026-08-24
- **Status:** ready to execute once v0.1 clears its definition of done
- **Companion docs:** the design spec and implementation plan under `docs/superpowers/`

---

## The one-line positioning

> **Your courses, as a vault your agent can actually read.**

Never lead with "scraper", "bypass", "automate D2L", or any framing built on D2L as a foil. The
product is an *archive and study system for your own coursework*. That is both the honest
description and the one that survives a hostile reading.

**Elevator version (30 seconds):**

> Agent2Learn turns the material available through your own Waterloo LEARN account into a local,
> organized course vault with markdown twins. Your coding agent can navigate it, cite the exact
> source lines it used, quiz you from your material, and run an explicitly experimental evidence
> scan over a draft. The engine runs on your computer; it talks directly to LEARN and stores no
> password. Licensed e-resources are left as links, discussions and grades are off by default, and
> there is no Agent2Learn account, cloud vault, runtime backend, or product telemetry. The invoked
> installer and package hosts still receive ordinary HTTPS request metadata, as the privacy guide
> explains.

**The differentiator, in one sentence, when someone compares it to a downloader:**

> A downloader gives you files. Agent2Learn gives you a vault your agent can cite — and `a2l check`,
> which shows the matching, related, missing, or possibly conflicting evidence its lexical scan
> found in your own course material.

---

## Positioning against the field

| | What they do | Where Agent2Learn differs |
| --- | --- | --- |
| Live Brightspace CLIs | Query grades, dates, and content on demand. | Agent2Learn materializes a durable local vault, preserves source revisions, creates markdown twins and indexes, and gives agents a stable citation surface. v0.1 officially supports Waterloo only. |
| Generic Brightspace downloaders | Dump files to disk. | No markdown twins, no index, no citation surface, no agent integration, no audit. |
| Manually uploading PDFs to a chat | Answers from the files selected for that conversation. | Agent2Learn keeps the source archive local and persistent, maps LEARN topic IDs to files, and teaches compatible agents to cite the vault. It does not claim that citations or lexical matching prove an answer correct. |

**The line to use when someone says "isn't this just a scraper":**

> The download is the boring part — that took a weekend. The point is what you can do once your
> course is text your agent can cite: ask a question and inspect the cited source, or run `a2l
> check` on a draft and see where its deterministic lexical scan found matching or related course
> evidence—and where local coverage is incomplete.

---

## Phase 0 — Before anyone sees it

**Duration:** ~2 weeks. **Gate:** do not proceed until every box is ticked.

- [ ] v0.1 passes its definition of done, including the three-OS CI matrix.
- [ ] Same-device browser-to-API auth is manually validated on Windows, macOS, and Linux without
      moving cookies, profiles, or Duo state between devices.
- [ ] The designated non-graded upload test and exact read-back pass with the human confirmation
      gate. If not, the published build and every launch asset say submission is disabled.
- [ ] The dependency/license review, third-party notices, SBOM, secret scan, and synthetic fixture
      review are signed off for the exact release artifacts.
- [ ] The private 262-PDF converter acceptance corpus passes at the shipped 80-words-per-page
      threshold with at least 100% of the recorded baseline's recovered words and zero candidate
      failures; the release record contains only aggregate/redacted evidence. The completed
      21-document sample and interrupted broad run are supporting evidence, not substitutes.
- [x] Re-check and create the approved documentation-first
      `ManagementMO/agent2learn` GitHub repository. The GitHub target returned 404 immediately
      before creation on 2026-08-25; the tracked scaffold passed its private-path and secret scan.
- [ ] Re-check the `agent2learn` PyPI project immediately before package publication and acquire the
      final domain only when the safety baseline is ready. PyPI returned 404 on 2026-08-25; domain
      registration was not verified. Availability is not a durable fact, and PyPI names must not be
      squatted with a placeholder release.
- [ ] **Email `learnhelp@uwaterloo.ca` to request technical/security guidance.** Draft below. Send
      it early enough to incorporate concrete concerns; do not imply silence equals approval.
- [ ] **Recruit ten alpha students** across at least three faculties, with **at least three on
      Windows**. They will find auth failures you cannot predict. Fix every one before Phase 1.
- [ ] Record the demo assets (shot list below).
- [ ] `agent2learn.dev` live, serving `install.sh`, `install.ps1`, `install.md`, and `llms.txt`.
- [ ] GitHub Discussions enabled; `FAQ.md` written; the bug-report template requires an
      `a2l doctor --report` block.
- [ ] Repository topics set: `agent-skill`, `agent-skills`, `brightspace`, `d2l`, `uwaterloo`,
      `claude-code`, `codex`. GitHub-crawler directories index tagged repos automatically — free
      long-tail discovery for zero effort.

### The `learnhelp@uwaterloo.ca` email

Send it from your UW address. Keep it factual and ask for the right review path. This is neither a
legal approval request nor a claim that the help desk can authorize every aspect of the project;
the goal is to surface technical, security, rate-limit, and acceptable-use concerns before launch.

> **Subject:** Request for guidance: open-source local LEARN archive/study tool
>
> Hi,
>
> I'm a Waterloo student building an open-source tool called Agent2Learn. It lets a student archive
> material available through **their own** LEARN account into a local course folder, with markdown
> conversions and indexes for search and agent-assisted study. Before a public Waterloo release,
> could you point me to the appropriate technical/security or platform contact and flag any LEARN
> API, acceptable-use, or rate-limit concerns I should address?
>
> How it works, briefly:
> - The engine runs on the student's device and connects directly to LEARN. Agent2Learn has no
>   runtime backend, account system, product telemetry, or remote course storage; the public site and
>   package hosts are used only for user-invoked installation, documentation, and upgrades.
> - It opens a dedicated persistent Chrome/Edge profile for WatIAM + Duo. That keeps Waterloo/Duo
>   remembered-login state on the same device for convenience. It never asks for or stores a
>   password, and the profile/session cookies are never copied off that device.
> - After the student's normal interactive WatIAM/Duo sign-in, its course-data API operations are
>   read-only GETs except one separately disabled Dropbox-upload feature. That feature, if released, previews the
>   exact target and requires a fresh human confirmation immediately before one POST, followed by
>   API read-back. It will remain disabled unless a designated non-graded test succeeds.
> - It **deliberately does not download licensed publisher or library content** — eTextbooks, LTI
>   resources, and VitalSource links are recorded as links and never fetched. This is enforced in
>   code and covered by tests.
> - It limits itself to two concurrent requests with back-off, to stay well inside normal browsing
>   behaviour.
> - Discussions and grade values are excluded by default. Public fixtures and demos are synthetic.
>
> Design/repository: <private review link or public repository><br>
> Privacy and authentication notes: <link><br>
> Security contact: <link>
>
> I would appreciate any concrete changes you recommend and am happy to walk through the request
> flow or provide a redacted technical demo. I will not send session credentials or student data.
>
> Thanks,
> <your name>

Track the date, recipient, response, and any resulting action in a private release checklist. A
help-desk response is useful evidence, not permanent authorization; re-check when authentication,
submission, request volume, or university policy materially changes.

### Demo asset shot list

The GIF does more work than every paragraph you will write. Record with `asciinema` (terminal) and
a clean screen recording (editor). Build every public asset from the synthetic demo vault and fake
API fixture. Never record a real WatIAM/Duo flow, authenticated browser profile, course title,
deadline, filename, grade, name, ID, or classmate content; cropping or blurring after capture is not
the primary privacy control.

1. **`a2l init` — 45 seconds.** Install line → disclosed dedicated-profile handoff → synthetic
   authenticated transition → metadata progress → ends on **useful synthetic deadlines**. Trim only
   idle time and label the data `DEMO`; do not fake benchmark numbers. This is the hero asset.
2. **`a2l today` — 8 seconds.** One command, a week of work laid out.
3. **The citation moment — 20 seconds.** Ask an agent a course question; it answers and cites
   `content/Week 3/Duality.md:145`. Cut to the synthetic source. *This is the emotional core of the
   product*—make the inspectability unmistakable without claiming the answer was proven correct.
4. **`a2l check` — 25 seconds.** Lead with its experimental-scan disclosure. Show one
   `evidence_found`, one `related_evidence`, one `no_matching_evidence`, one `possible_conflict`,
   and one path-null `a2l fetch` hint. Never label a result supported, contradicted, verified, or
   graded. **This is the asset that gets shared.**
5. **The before/after — 12 seconds.** Split screen: twelve clicks through D2L to find last week's
   lab, versus one question.
6. **A still of the vault in Obsidian**, for the note-taking audience.

Run a frame-by-frame privacy review and OCR scan before publication. The source recording itself
must already be synthetic; redaction is only a second layer.

---

## Phase 1 — Soft launch: finals week

**Why now, not the start of term:** finals is peak pain. "I'm behind in four courses and have no
notes" is when someone will actually install a new tool. Start of term is when they *intend* to.

- **Where:** your own cohort, program group chats, EngSoc / MathSoc / faculty Discords.
- **Target:** ~50 users. **No Reddit yet.**
- **Goal:** not growth. The goal is that the twelfth stranger's install works without you.
- **Instrument by hand:** ask every single user "did it install first try?" and log the answer.
  With no telemetry, this is your only data. It is enough at this scale.
- **Ship weekly.** Every fix in this phase is worth ten later.

**Exit criterion:** ten consecutive unassisted installs across at least two operating systems.

---

## Phase 2 — Hard launch: first week of term

Peak habit-formation. Someone who installs in week one uses it for four months.

### r/uwaterloo

That subreddit punishes self-promotion and rewards utility. The post that works:

> **Title:** I built a thing that turns your Learn courses into a folder your AI can actually read

Structure:

1. **The GIF, above the fold.** No architecture diagram, no feature list.
2. One line of who you are: *"3A MSE, I built this because I was drowning in four courses and could
   never find the lab I needed."*
3. Three bullets of what it does. Not ten.
4. **Pre-empt the top comment inside the post itself** — a "What this does and doesn't do" block:
   your own account only · never touches licensed eTextbooks · discussions off by default · no
   Agent2Learn telemetry · local vault and same-device login state · network access limited to the
   configured LEARN origin, disclosed first-party outline hosts, and the reviewed WatIAM/Duo login
   hosts during authentication · open source, here's the code. Say *"I asked Learn support for technical
   guidance on <date>; here is what changed as a result"* only if that is literally true. Never
   imply university endorsement, and never say "nothing leaves your machine."
5. The install block: two lines, one per platform.
6. **End with a question, not a call to action:** *"What would you want it to do?"*

Then **answer every comment for 48 hours.** That is the entire game on that sub. A maintainer who
replies to the sceptic thoughtfully converts the thread.

**Timing:** Tuesday or Wednesday, 9–11am ET.

**Do not:** cross-post the same text everywhere, argue with the harshest comment, or promise
features in replies.

### Same week

- **WatTools** — the canonical index of UW-student-built tools since 2011. Submit.
- **GitHub topics** — already set in Phase 0. They improve repository discovery and make the
  supported ecosystems legible at a glance.
- **Agent Skills compatibility** — verify that
  `npx skills add ManagementMO/agent2learn --list` discovers the same four canonical skills. Link it
  from the repository for students who already use that ecosystem, while keeping the normal
  install→`a2l init` path primary.

**Do not make registry ranking the launch strategy.** `skills.sh` is a useful standards-compatible
installation route, but it installs instructions, not the Python engine or the user's vault. Treat
it as compatibility and long-tail discovery; the product promise still starts with the tested
Agent2Learn installer and continues directly into onboarding.

---

## Phase 3 — Outside the bubble

### Show HN

> **Show HN: A local, source-cited course vault for Waterloo LEARN**

Lead with what is real: v0.1 officially supports **University of Waterloo LEARN**, while its school
adapter boundary is designed for future Brightspace ports. Emphasize the local-first architecture,
no Agent2Learn runtime backend/account/product telemetry, same-device authentication, revision-safe archive,
`Apache-2.0`, three-OS tests, synthetic fixtures, and deliberate refusal to fetch licensed
content. Do not claim broad Brightspace compatibility until another adapter has its own fixtures and
maintainer. Post 8–10am ET on a weekday and be available for technical questions.

> **Expect the licence question on HN, and answer it in the post rather than the comments.** One
> line: *"Agent2Learn is Apache-2.0, and its required PDF/OCR stack is permissively licensed, so the
> public release has no converter-driven copyleft obligation."* Link the exact lock, SBOM, and
> third-party notices, including the bundled PDFium notices, and avoid presenting the sentence as
> legal advice.

### X / Twitter

Post the **grounding** thread, not the scraper thread.

> I built a local course-vault workflow that tells my coding agent to ground answers in cited class
> material.
>
> When its deterministic scan finds no matching evidence—or a relevant file has not been fetched—it
> says that plainly instead of turning lexical similarity into certainty.
>
> Here's what happens when I run it on a draft I wrote: 🧵

Show the source-navigation path and the `possible_conflict` line with the experimental-scan banner.
Land the thread on the repository. Tag the agent-skills community only where relevant and disclose
that skills are instructions layered over the separately installed local engine.

### The blog post that actually spreads

Not "how I scraped my LMS." Write:

> **What changes when an AI study workflow has to show its course sources?**

Structure: the problem (a general model writes generic textbook answers, not *your* professor's
notation) → the constraint (only these files, cite every step, stop when the material runs out) →
what changed → `a2l check` and examples of matching, related, missing, and possibly conflicting
evidence → the honest limits of lexical retrieval, incomplete local coverage, and agent compliance
with instructions. Ship it with the repo, and cross-post only where you can answer comments.

This is the piece that generalises past Waterloo and past this tool. It is the idea, not the
project.

---

## Nice-touch moments worth marketing

Each of these is small to build and disproportionately shareable:

| Moment | Why it spreads |
| --- | --- |
| `a2l init` ending on the student's **real local deadlines** | The user-visible payoff; public screenshots still use synthetic data |
| `a2l calendar` → deadlines in Apple/Google Calendar | Useful to people who will never open a terminal again |
| **Grade-posted notice**, only after grade opt-in | Useful without making sensitive data a default or marketing screenshot |
| **Term rollover** prompt in September | Delight, twice a year, unprompted |
| The vault opening cleanly in **Obsidian** | An entire adjacent community, for free |
| `a2l check` surfacing **possibly conflicting evidence** | A useful reason to inspect both cited passages, not an automated correctness verdict |
| A path-null finding offering **`a2l fetch`** | Turns an honest coverage gap into one clear next action |

---

## Support infrastructure

Anything with authentication is a support magnet. Have this live *before* Phase 2, not after.

- **GitHub Discussions** — categories: Install help · Ideas · Show and tell · Other schools.
- **Issue template** requiring an `a2l doctor --report` block. This is the difference between five
  minutes and five days per ticket.
- **Private security reporting** through `SECURITY.md`. Never ask for session files, browser
  profiles, cookies, raw API responses, real vaults, or screen recordings of WatIAM/Duo.
- **`docs/FAQ.md`** seeded from the Phase 1 alpha, not invented.
- **`docs/AUTHENTICATION.md`** with same-device recovery, `--paste`, and profile-clearing guidance.
- **A response-time promise you can keep.** "Usually within a couple of days, I'm a student too" is
  better than silence and better than an unkept 24-hour promise.
- **A public roadmap** in Discussions, so feature requests have somewhere to go besides issues.

---

## Risks and pre-planned responses

| Risk | Response |
| --- | --- |
| **"This is against the rules / academic misconduct"** | Point to the exact documented boundary, not an implied endorsement: it archives material available to the student's account, excludes licensed targets, omits `ground --solve`, surfaces course AI-policy text, and scans drafts for lexical evidence without grading or proving them. Address concrete policy citations and change the product if required. |
| **UW changes or blocks session replay** | Pause affected releases, publish an honest status note, reproduce only with same-device accounts whose owners are testing, and contact the appropriate platform team. `--paste` is a fallback for harvest failures, not a way to evade a deliberate block. |
| **D2L Corporation objects to the name** | You already avoided the bare "A2L" brand and any anti-D2L framing. If contacted, respond promptly and courteously; a rename is survivable, a fight is not. |
| **A user publishes a screenshot containing private data** | Make grade/discussion capture opt-in, keep public demos synthetic, add screenshot guidance, and promptly ask the poster to remove exposed data. Treat any product-facilitated leak as a security/privacy incident rather than assigning blame. |
| **A session/profile leak is reported** | Use the private security channel, tell the affected user to clear Agent2Learn session/profile state and follow Waterloo account-security guidance, rotate/revoke what the platform supports, remove public artifacts, and ship a scoped advisory. Never request a copy of the leaked secret. |
| **The upload path is ambiguous or duplicates a file** | Never retry a mutating POST. Report verification failure, direct the human to inspect LEARN, preserve local evidence without secrets, and disable the feature if the route cannot be made unambiguous. |
| **A Windows install wave fails** | The three-OS CI, the installer smoke tests, and the alpha Windows users exist precisely to prevent this. If it happens anyway: pin the issue, fix, patch release, and reply in the Reddit thread — visible responsiveness converts a bad launch. |
| **It gets popular and you graduate** | Decide ownership before it matters. WatTools transferred its domain to the university for exactly this reason. Options: hand to an incoming student, transfer to a UW club, or archive with an honest notice. |

---

## What success looks like

Deliberately modest, because vanity metrics will mislead you here.

| Horizon | Signal |
| --- | --- |
| Week 1 | 10 unassisted installs across ≥2 operating systems |
| Month 1 | 100 installs · <5 open install bugs · one unsolicited "this is great" |
| Term 1 | 500 installs · someone you have never met answers a support question for you |
| Term 2 | A pull request adding a `schools/` adapter for another university |
| The real one | A student says Agent2Learn changed how they study — not how they download |

The metric that actually matters is **unassisted install success rate**. Everything else follows
from it, and nothing compensates for it.
