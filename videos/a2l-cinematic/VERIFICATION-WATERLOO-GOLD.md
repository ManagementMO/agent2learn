# A2L Waterloo-gold identity — 2026-09-09

## Scope

- Original outlined serif **A2L**, a raised **2**, and a chamfered **#FFD54F**
  underline. The numeral has been refined to an upright bowl, substantial
  horizontal foot and vertical right terminal; A, L and underline are unchanged.
  One font-independent SVG master lives at
  `frontend/src/assets/brand/a2l-waterloo-gold.svg` (repository-relative).
- Website: shared inline mark in header, footer, agent setup, citation example,
  all documentation headers and 404; native favicon, 512px icon, light/dark
  vector and transparent PNG exports, social card and refreshed demo poster.
- Film: header, context receipt, terminal footer and closing frame. White ink
  in the terminal does not invert the gold. No timing, animation or audio edits.
- Refreshed synthetic poster, 12-frame storyboard and 36-frame ingestion sheet.
  `node tools/capture-review-stills.mjs` reproduces them from the current Studio
  composition, not a stale MP4.
- Historical raster/book assets remain available as explicit build variants.
  Default is `waterloo-gold`. The previous MP4s are untouched and still predate
  this logo and the Launchbeat soundtrack update. No new MP4 was rendered.

## Fresh checks

- Website `brand:check`, formatting and production build pass: 37 Astro files,
  zero diagnostics; 13 HTML pages; 500 internal links/assets.
- Logo browser regression: 16 cases, home and docs at 320/375/768/1440px, both
  themes. Native outlines, aspect ratio, correct ink, unchanged gold, no
  inversion, overflow or navigation collisions.
- Site browser regression: 38 cases including accessibility, responsive
  layouts, citations, clipboard flows, documentation search and demo dialog.
- The merged gold-marker design passes its five browser checks: light/dark
  left-to-right draw, fixed layout, hidden-tab pause/resume, once-only playback,
  reduced-motion and no-JavaScript fallbacks. Feature illustrations stay static.
- Published-state build check passes; actual release setting is unchanged.
- Brand export guard was proven by deliberately changing the dark export's
  gold: `brand:check` failed. Correct exports were regenerated and pass again.
- HyperFrames upgraded **0.8.31 → 0.8.33** per the project preview workflow.
  Full check passes: zero lint/runtime/layout/motion errors; 300 motion samples.
  It reports one contrast warning on the `$` in the existing sync-terminal
  entrance at 4.861s (entrance runs 4.82–4.97s). No logo contrast finding.
- Full film verifier passes: 2,100 layout frames, 12 exact DOM and pixel
  reverse seeks, 36 particles, source/citation identity, 44 typing/Foley events,
  no runtime errors, failed assets or external requests. An earlier run against
  the pre-upgrade preview reported a caret raster difference; after restarting
  the preview on 0.8.33, the full verifier passed without relaxing pixel limits.
- All three brand variants pass; an invalid variant is refused; normal build
  restores the selected gold identity. Gold remains unchanged in dark slots.
- Website poster matches the film poster and the production build byte-for-byte.
- Core gates: frozen dependency sync, Ruff lint/format, mypy, fixture
  reproducibility and notices checks pass. Full coverage run: **943 passed,
  4 skipped; 79.45%**, above the 77.5% floor. No core product code changed.
- The two new manifest checksums are SHA-256 digests of the public light/dark
  SVGs, not credentials. Only their exact scanner fingerprints are added to
  the reviewed secret baseline; no file, directory or rule is excluded.

## Checkout and delivery boundary

The authoritative combined changes are in `/Users/mo/Downloads/agent2learn`,
branch `design/a2l-waterloo-gold`, based on merged main **`204c97e` / PR #12**.
The superseded local website work was backed up before the branch was advanced
with a fast-forward. No conflict resolution or overwrite of the newer design
was needed. Website components, pages, styles, content, marker animation and
social-card layout script are byte-identical to that main baseline. Only the
master numeral, its provenance note and generated image exports change on the
website side. No remote deployment or package publication is part of this edit.

The generated film HTML's non-logo DOM, text, icon paths, animation code and
audio cues match main. The checked-in Studio serialization preserves its IDs,
leaving only two changed HTML lines for the logo references and closing image.

The already-running film worktree at `/Users/mo/Downloads/agent2learn-cinematic`
is a preview mirror on `motion/a2l-cinematic`, with the same changed video source
and assets, checked after the variant tests restored the default. It is not a
competing design. The WEBSITE preview serves the authoritative primary checkout.

Preview addresses:

- Website: `http://127.0.0.1:4322/`
- Single Agent2Learn editor: `http://localhost:3017/#project/a2l-cinematic`

The unrelated Roster servers and tabs were left alone. Local audio and old movie
exports remain ignored. Brand provenance and colour reference are documented in
`frontend/src/assets/brand/README.md`.
