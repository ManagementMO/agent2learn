# Tactile proof and restrained firefly polish — 2026-09-11

Implemented against clean `1bd497f85d85424550e8fdd4ebf442aaa1f588b9` in the
cinematic worktree. The user approved the second visual concept in full and
only the small warm particle material from the first concept.

## Delivered in the composition

- Pearl-white source-editor chrome and optical window rims; application content
  stays opaque. The black terminal remains a familiar terminal.
- The citation link and arrow share one small dark-gold target. Its matching
  source highlight has a white upper bevel, narrow gold gutter, soft shadow and
  a 4px surface settle independent of the text. Existing exact source words,
  line numbers, underline and source-open receipt remain in place.
- Thirty-six tiny golden points follow the original paths. Each receiving
  document icon briefly warms, then returns to monochrome. The 0.26s absorption
  taper and all three landing positions are unchanged.
- No side-by-side ingestion redesign, enlarged beads, ribbons, new panels,
  added claims, or additional decorative particles.
- Follow-up: removed the citation chip's corner dot and replaced only the final
  GitHub URL with `uv tool install agent2learn`, as the user's requested release
  placeholder. Removed the external-link arrow from that command. The opening
  source install is unchanged; this is not evidence of package publication.

Unchanged: the shared upright A2L artwork, demo copy, course content, scene
durations, camera moves, typing cadence and Foley events. `exportPrefix` is now
`signalflow-tactile`; `audioPrefix` remains `signalflow-disclosure`. This only
reserves distinct future filenames. Existing MP4s have not been rendered over.
No frontend or Python product code is part of this edit.

## Verification

Commands run from `videos/a2l-cinematic/`:

```sh
npm run build
npm test
npm run test:polish
npm run test:soundtrack
npm run check -- --snapshots
npm run check -- --at 1,4.861,5.4,6.3,7.5,8.05,12.1,13.74,14.5,17.2 --snapshots
```

- Build passed using the existing pinned HyperFrames 0.8.35 (latest at check).
- The main behavioral gate passed: no tested collisions in 2,100 frames;
  12/12 exact forward/reverse DOM and pixel matches; zero runtime errors,
  failed assets or external requests; all 44 typing/Foley events agree.
  The fresh pre-commit rerun again passed with 12/12 exact DOM matches and
  11/12 exact pixel matches: the 6.3s perspective pose differed by one color
  level at 56 edge pixels, within the existing 64-pixel/one-level tolerance.
  No tolerance was widened for this revision.
- All 36 particle landings meet their own source icon within 0.000035px.
  Maximum sampled travel is 8.79px per 120fps frame, with 31 absorption intervals
  and the same last arrival at 7.60s.
- The new browser regression first failed on the old gray particle pool, then
  passed after implementation. It checks restrained yellow circles, a timed
  reversible source-surface reveal, stable sentence geometry, and neutral
  document icons after absorption.
- The focused ten-time HyperFrames check passed with zero lint, runtime, layout
  or motion findings and 160/160 sampled text contrast checks passing.
- The default nine-time sweep also passed, but retained its pre-existing
  transient contrast warning on the sync strip's `$` entrance around 4.861s.
  The denser/strict all-transition gate and MP4 export were not run in this pass;
  neither is implied by the selected-frame contrast result.
- The existing Disclosure bed, typing and interface stems are byte-identical
  to the approved mix, and the server returns those exact bytes. The soundtrack
  gate now separates its historical `--original-picture` audit from current
  sound/brand preservation; visual correctness is covered by the two browser
  gates above, not by comparing to intentionally superseded CSS.

Actual current-composition review images are local under
`.checks/signalflow-tactile-hero-*.png` and `.checks/tactile-detail/`.
The earlier before/concept images remain in
`.checks/visual-polish-concepts-20260911/`. These are review artifacts, not movie
exports. The keyframes diagnostic recognizes the source's two CSS-variable
poses, but its selector onion-strip did not paint that pseudo-element usefully;
full-frame runtime captures and reverse-seek checks are the visual evidence.

## Review and publication boundary

Use the existing Studio at `http://localhost:3017/#project/a2l-cinematic`.
No additional preview server was started. The approved changes are prepared on
`motion/tactile-proof`, based on main `6d4259f` after soundtrack PR #16 merged.
Commit/PR status is tracked in GitHub, not inferred from these local checks.
No new MP4 or public campaign is claimed by this document. The commercial recording and derived
audio remain local/ignored; the previous soundtrack's public-use clearance
boundary is unchanged. See `CREDITS.md` and `VERIFICATION-DISCLOSURE.md`.
