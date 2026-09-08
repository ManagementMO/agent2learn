# Signalflow research and design decisions

## Official/public references consulted for this edit

- [Waterloo CS135 course description](https://cs.uwaterloo.ca/current/courses/course_descriptions/cDescr/CS135.shtml) identifies Designing Functional Programs and its functional-programming focus.
- [CS135 course notes](https://student.cs.uwaterloo.ca/~cs135/slides/index.html) lists L01 values and expressions, including prefix notation, and L02 functions. These public topics informed the more student-specific example. No lecture PDF is embedded or copied.
- [CS135 detailed course discussion](https://cs.uwaterloo.ca/~plragde/135-detail.html) is explicitly a possible week-by-week guide, not an actual schedule. It associates introductory arithmetic/prefix notation/functions with the opening material. “Week 1” in the film is a plausible authored demo, not a claim about a particular term's teaching calendar.
- [Charm VHS](https://github.com/charmbracelet/vhs) treats Type, Sleep, Copy/Paste and Enter as separate actions in terminal recordings. Applied as an editorial principle: installation is pasted, short commands typed, and the student's input has meaningful pauses. We did not install VHS or imply a live terminal recording.
- [Screen Studio animation guidance](https://preview.screen.studio/guide/animations) distinguishes focused motion that stabilizes quickly for reading from smoother, more creative movement. Applied here: flowing ingestion, then a stable question/answer and citation.
- [GSAP MotionPathPlugin](https://gsap.com/docs/v3/Plugins/MotionPathPlugin/) was fetched through Context7. Explicit cubic anchors/control points support the document-information trajectories while a paused timeline keeps seeking deterministic.
- [Lucide source](https://github.com/lucide-icons/lucide) supplies file-text, notebook-text and terminal SVGs. 24×24 view boxes, currentColor strokes, no gradients or filled pastel badges. Local copies and the complete license notice are retained in assets/icons/.

These sources support mechanisms and topic choices. The claim that the result
looks or feels better remains a design judgment, not a research-proven fact.

## Direction applied

The primary problem was mechanical repetition: a repeating per-character timing
formula, clipped assistant text, and large rectangular rows simply shrinking
into the terminal. The new design separates three kinds of motion:

1. Human input: a single paste, non-periodic key intervals, phrase pauses and a
   thin attached caret; authentic recorded-key variants are softened.
2. Information transfer: the rows dissolve into 36 indexed points, follow
   curved paths and resolve into corresponding named local-source receipts.
3. Reading/proof: camera motion settles; the assistant streams meaningful
   chunks; the local source line is larger, heavier and distinctly highlighted.

The neutral glass treatment remains at window edges. Essential text sits on
opaque white/black surfaces. No arbitrary neon, particles behind every scene,
or decorative folder sculpture was added.

## UI familiarity and privacy

Earlier Google Chrome imagery and the user's LEARN screenshot informed tabs,
omnibox, masthead, utilities and course navigation. None of the authenticated
screenshot's pixels, people, announcements, private files or account state is
embedded. The film is explicitly CS135-inspired and synthetic. Public CS135
references do not establish what its current authenticated LEARN course looks
like; the content arrangement and term are illustrative.

The exact frontend book mark is preserved as a selectable variant. The terminal is a stylized Codex
workflow and its Agent2Learn receipt panel is explanatory, not an assertion
that Codex ships this exact panel.

## Renderer and asset choice

Keep the existing HyperFrames 0.8.31 / GSAP 3.14.2 project. The read-only upgrade
probe confirmed the pin is current for this session. Local catalog search on
the words tier returned arc-motion-path and particle-dissolve mechanisms.
The installed arc-motion-path reference informed the route geometry; the
fixed-pool particle recipe informed bounded, seek-safe construction. Their
showcase artwork is not mounted.

Exact text, source links and deterministic motion favor authored geometry for
this particular film. No video-generator footage, new paid music, external
upload or additional sign-in was needed. This is not a claim that a renderer
is universally best.

Product wording was checked against README and docs/LAUNCH.md. Source-install
syntax remains the previously verified uv Git-tool installation form.
No auth, installation, syncing, package publishing or actual agent invocation
is performed by this film work.

## Focused finishing pass — 2026-09-08

The [official D2L homepage](https://www.d2l.com/) and its
[current served logo](https://www.d2l.com/wp-content/uploads/2022/08/logo.svg)
were inspected. The relevant character is strong editorial serif lettering,
not generic rounded AI imagery. A new image-generation prompt explores A2L
lettering in that broad direction while excluding D2L glyphs, green underline,
book/folder artwork and claims of affiliation. The source logo is not a frame
or layer in the film, and the frontend has not been rebranded.

[GSAP CustomEase](https://gsap.com/docs/v3/Eases/CustomEase/) documentation was
fetched through Context7 before use. One continuous normalized ease drives
each explicit cubic path: a slightly faster middle with a gradual end. The
tail separately tapers opacity and scale for 0.26 seconds. Receiving icons
have a small finite halo tied to the same three audio arrival cues.

No new scene, panel, course content or question was needed. The source view
now identifies its cited line and underlines the exact phrase in the answer.
This preserves the approved picture's reading time and restrained palette.
