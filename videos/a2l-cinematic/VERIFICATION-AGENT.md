# Your Agent headline follow-up — 2026-09-08

## Scope

Only the top agent chapter headline changed from `Codex × Agent2Learn.` to
`Your Agent × Agent2Learn.` Codex remains the actual terminal example.
The HTML template differs in precisely that one line. Motion JS, composition
CSS, timing/Foley cues (apart from output-name metadata), brand selection,
synthetic source excerpt, and audio metadata match the archived polished cut.

The website separately adopts this exact approved A2L artwork on main at the
owner's request. Product engine code, live accounts and course data are untouched.
At the end of the implementation follow-up, nothing had yet been committed,
pushed or deployed. Git finalization is recorded separately below.

## Deliverables

| File | Format | SHA-256 |
| --- | --- | --- |
| `renders/agent2learn-signalflow-agent-120fps.mp4` | 1920×1080, 17.5s, 2100 native frames, AAC stereo/48kHz | `f27af3acde0d9d991959a4e2ad45f411cec92c6e6b8cb5828da084496de25f27` |
| `renders/agent2learn-signalflow-agent.mp4` | 1920×1080, 17.5s, 1050 frames/60fps, AAC stereo/48kHz | `11ceacc9d7a8af52cf3eb4909a4fed333e9a463ce8088e2d27c3823425559fe9` |

## Evidence

- `npm test`: passed. 2100 sampled layout frames; 12 exact forward/reverse DOM
  checkpoints. Seven PNG checkpoints identical, five with only 1–12 tiny
  boundary-pixel differences within the existing tolerance (maximum channel
  delta 15). No thresholds relaxed. No runtime errors, failed assets, external
  requests, unintended tested collisions, or resting-panel overflow.
- Added a rendered-text range check: every chapter title retains at least 24px
  before its chapter label. The new agent headline fits without changing its
  font size or motion.
- 36 particle trajectories retained: 6460 moving samples, maximum 8.7864px
  step, 31-frame absorption taper, final arrival 7.6s, maximum landing error
  0.0000342px. All 44 input/Foley events and source lines 39–44 still match.
- HyperFrames strict check passed: 458 sweep samples, zero errors/warnings.
  Dedicated five-hero readability check passed all 236 checked text nodes.
  The existing single informational 6.25s projected-browser overlap remains;
  encoded review confirms the browser text is clipped below the header, not
  visibly covering it. No broad layout escape hatch added.
- Both complete MP4s decode successfully; resolution, duration, frame counts,
  audio format, distinct typing frames and nonblank final hold passed.
- The new render initially had different AAC bytes despite identical stems.
  `tools/preserve-title-audio.mjs` copied the preceding approved audio stream
  without re-encoding either stream. It verifies the approved source file,
  unchanged timing, exact audio packet hash and unchanged new video packet hash.
  Running it again is a no-op.
- Final decoded audio is sample-identical across the old 120fps master and
  both new exports: SHA-256
  `319e20bd216b8bd9be33b8712f23810a7955debc1824ceca0b719aa8cbeaeeb2`.
  The independent stem-mix comparison also passed all six sections; peak
  −3.365 dBFS and final 10ms RMS −85.071 dBFS.
- Inspected the encoded agent scene at 8.05s. Encoded storyboard, dense overview,
  ingestion sequence and full-resolution checkpoints remain under
  `renders/signalflow-agent-*` and `.checks/signalflow-agent-encoded/`.

## Preservation and limits

Frontend adoption was verified locally on main based at `81f712544e6b1ccac25d84b6d562c5a8b9d48fa1`:
`git pull origin main` returned already up to date. The build verified 13 HTML
pages and 512 local links/assets; Astro checks had zero errors/warnings/hints.
The format and disposable published-state gates passed. A real-browser sweep
passed 16 homepage/docs width/theme combinations with decoded marks, preserved
wide proportions, no document overflow and a minimum homepage header gap of
11.9375px at 320px. The approved source PNG is unchanged; wordmark, favicon,
512px icon and synthetic social card exports replace the former book mark.
Only frontend branding, its asset-generation/check scripts and related docs
changed in the main repository. No Python engine or release setting changed.

Prior source is retained in `.archive/signalflow-polish17.5/`. Both original
polished MP4 hashes remain unchanged. The fresh-render audio variants are kept
in `.checks/title-audio/`, and all older cuts remain intact.

These are local film/browser/export checks, not CI, a live product workflow,
music-rights clearance, trademark clearance, or a claim of subjective perfection.
Music and source material were not regenerated. Review public-distribution
rights before publishing, as already documented in CREDITS.md.

## Git finalization checks — 2026-09-08

Fresh pre-commit checks passed for both complete MP4 decodes, their exact hashes,
all six independent audio-mix comparison sections, and the 2100-frame composition
test. Two repeated seek checks found 8–11 byte-identical PNG checkpoints;
remaining checkpoints differed in only 1–6 edge pixels (maximum channel delta
15), within the original tolerance. All 12 DOM checkpoints remained exact.
Frontend build, brand drift,
formatting and disposable published-state checks also passed again.

Publication packaging changes only script formatting, reviewed public-hash
annotations, a historical verifier's portable logo pin, ignore rules and handoff
documentation, plus removal of one stale lock entry for a deleted registry demo.
The secret scanner's JSON baseline adds only 11 manually reviewed SHA-256
fingerprints (audio source, registry base and logo digests); no scanner directory
exclusion or detection threshold is widened. No scene, animation, cue, generated picture, soundtrack or final
MP4 was changed. Licensed catalog sources, stems, exports and temporary/reference
files remain local; the Git source checkpoint is not a public music release.
Only three reviewed picture-only stills are included from the render directory.
The focused repository smoke/documentation tests passed all 53 cases; video-tool
Ruff checks and formatting passed, and the complete staged pre-commit gate passed.
