# Verification — Signalflow Polish

Completed locally on **2026-09-08**, with the editorial A2L logo experiment.
This is the focused finishing pass requested after Signalflow. Historical
results for that previous cut remain in VERIFICATION.md and its archive.

## Delivered files

| Export | Format | Frames | Runtime | Bytes |
| --- | --- | ---: | ---: | ---: |
| renders/agent2learn-signalflow-polish-120fps.mp4 | 1920×1080, native 120 fps, H.264/yuv420p, AAC stereo 48 kHz | 2,100 | 17.500s | 4,489,218 |
| renders/agent2learn-signalflow-polish.mp4 | 1920×1080, 60 fps, H.264/yuv420p, AAC stereo 48 kHz | 1,050 | 17.500s | 2,562,413 |

```text
120fps  a6d99c497c9e2d6766a106b9dce990b02c299525e187e40f551f5f44b33f302c
60fps   be0f8fe2255125ca10683c8716991aafcede14430ad8647c87fb891517516a16
new PNG ddbd02a881678ea3e1abb9fc9476d6253a1ebfb06fed788cc59f9acaf1b63f0d
old SVG ea3b7fdb9152b63cfadc7f0bd163ced1519d5562316b95c239f6955db9461483
```

The master was rendered by HyperFrames 0.8.31 in 57.7 seconds, three workers,
high quality, CRF 17, strict-all and no best-effort fallback. It samples the
GSAP timeline directly; the 60 fps copy selects alternate frames without
generated interpolation and copies the AAC stream. Both complete streams
decode cleanly, question-typing frames change, and the last frame contains
the full identity lockup rather than a blank/black tail.

Evidence: .checks/render-signalflow-polish.log,
.checks/signalflow-polish-export.json. The final HTML, CSS, cues, three audio
stems and generated logo match .checks/signalflow-polish-source-sha.txt after
rendering. No visual source was changed after the master export.

## What changed

- **Particles:** receipt accents move from 7.34/7.48/7.62 to
  **7.20/7.36/7.52 seconds**. A single CustomEase curve gives each cubic path
  a faster middle and gentle deceleration. The absorption taper grows from
  0.14 to **0.26 seconds**, about **31 native frame intervals** instead of 17.
  Scale and opacity decrease monotonically into the receiving icon centre.
  A small finite halo belongs to each icon; no extra decorative particle pool.
- **Source file:** the breadcrumb badge says **Cited line 42**; the existing
  proof footer says **Source opened at line 42.** A restrained underline draws
  beneath **prefix notation**, the phrase shared with the answer. No new panel,
  extra course content or change to the exact excerpt.
- **Logo:** the built-in image generator produced a new original editorial
  A2L experiment, with broad typographic inspiration from D2L's official mark.
  The transparent 1774×887 PNG appears in the header, context, terminal footer
  and closing frame. No D2L artwork is included in the composition. The actual
  frontend book mark is unchanged and remains a tested build variant.

Runtime remains **17.5 seconds**. The approved typing cadence, question,
assistant response, music edit, source camera and palette are retained.
Only the three receipt accents were retimed in the audio.

## Fresh behavior and readability checks

- Build and JavaScript syntax checks passed.
- `npm test` passed: **2,100 master layout timestamps** with no tested
  unintended panel, text-row, proof-footer or logo/text collisions. Resting
  panels fit the stage and the moving LEARN/Codex shells stay separated.
- HyperFrames strict check passed with **zero errors and warnings** across
  lint, runtime, layout, motion and contrast. **458 layout samples**, including
  **399 transition samples**. Separate focused readability: **236/236** text
  samples pass at 1.7, 5.4, 8.05, 12.1 and 14.5 seconds.
- **36 particles**, **289 dense ingestion samples**, **6,460 moving point
  samples**; maximum movement **8.79 px per 120 fps step**. All points disappear
  by **7.60s**. Measured landing error is below **0.001 px**, with each receipt
  already over 95% opaque. All 36 tails pass monotonic scale/opacity checks.
- **12 forward/reverse DOM states match exactly**. Nine hero PNG pairs are
  byte-identical; the other three differ by **3–12 edge pixels** out of
  2,073,600, maximum channel delta 15/255. The narrow pre-existing tolerance
  was not loosened. Universal exact Chromium rasterization is not claimed.
- Both pointer clicks hit their actual targets. Five input sequences match
  the baked schedule: **43 recorded keys plus one clipboard-paste event**.
  Assistant response chunks remain silent and seek-safe.
- Source lines **39–44** equal the synthetic file. Line 42 is exactly
  **Use prefix notation in Racket.** No runtime errors, failed assets or
  external asset requests occurred in the compiled-preview test.
- `node tools/verify-brand-variants.mjs` passes both **frontend** and
  **editorial** variants, including their distinct closing proportions. An
  invalid variant is refused without replacing the valid composition.
  The test restores the configured editorial variant afterward.

Evidence: .checks/signalflow-polish-behavior.json,
.checks/signalflow-polish-layout.json,
.checks/signalflow-polish-hyperframes.json,
.checks/signalflow-polish-readability.json,
.checks/signalflow-polish-brand-variants.json.

## Problems found and resolved

The new raster logo initially changed after scrubbing backward from its large
closing placement to the small header/footer. A controlled runtime experiment
localized **1,084 changed pixels entirely to those marks**. Isolating the image
resource for each placement reduced the focused comparison to **zero**. The
build now creates byte-identical placement copies; it does not redraw or
resample the generated image. The main reverse-seek regression also passes.
Evidence: .checks/signalflow-polish-logo-raster-probe.jsonl and
tools/probe-logo-raster.mjs. Its shared-resource mutation still reproduces the
failure, while the real composition's isolated resources pass.

The landing test also caught receipts not being sufficiently opaque when the
first points finished. Their short entrance starts 60ms earlier. The points'
box-centre offset was corrected to the measured receiving SVG centres.

HyperFrames' bundler rejected a newly added interpolated querySelector. Using
the known receipt element ID avoids that parser limitation. The generated
inline module omits standalone development comments; the authored source
module retains them. Final lint is clean.

## Explicitly retained limitations

One informational layout finding at 6.25s is the departing browser label's
projected box crossing the header. Its actual pixels are clipped below y240
by the stage. The exact encoded frame was inspected and contains no painted
header overlap; no blanket overlap waiver was added.

The static keyframe extractor cannot resolve helper-created particle targets.
Its workspace shot displays guides rather than the actual fully painted
sequence. It is **not visual proof**. Runtime particle trajectories and the
encoded 36-frame ingestion sheet provide that evidence instead. The six-frame
encoded camera strip covers the source pullback. Keyframe JSON is structural
evidence only, under .checks/signalflow-polish-keyframes.json.

## Encoded audio

All six waveform comparisons against the independently assembled stem mix
pass: install, sync, ingestion, question, source click and outro. Correlations
are **0.99777–0.99944**, absolute gain differences below **0.081 dB**.

| Delivered AAC measurement | Result |
| --- | ---: |
| Integrated loudness | −17.58 LUFS |
| Loudness range | 8.60 LU |
| True/sample peak | −3.36 dB |
| Last 10ms RMS | −85.07 dBFS |
| Samples per channel | 840,000 |

These are input measurements of the delivered AAC, not the hypothetical
normalized output of the analysis filter. Evidence:
.checks/signalflow-polish-audio-verification.json,
.checks/signalflow-polish-aac-levels.log and audio_meta.json.
No human headphone review or music-rights clearance is claimed.

## Encoded picture inspection

Inspected the **exported master**, not just the Studio preview:

- renders/signalflow-polish-storyboard.jpg — eight scene heroes.
- renders/signalflow-polish-dense-review.jpg — 70 frames across the film.
- renders/signalflow-polish-ingestion-review.jpg — 36 frames at 12 fps.
- renders/signalflow-polish-poster.png — full-resolution answer/source pair.
- .checks/signalflow-polish-camera-encoded.jpg — six pullback poses.
- .checks/signalflow-polish-encoded/clipped-browser.png and final.png —
  full-resolution clipping and complete closing-lockup checks.

The inspected sequence retains intact lettering, clear scene progression,
separate panels, local-source emphasis and the experimental mark. This is
visual inspection plus technical sampling, not subjective perfection or a
claim of live playback on every display.

## Preservation, location and next review

Worktree: agent2learn-cinematic (local sibling checkout)
Branch: motion/a2l-cinematic
Studio: http://localhost:3017/#project/a2l-cinematic

Previous Signalflow source/docs are in .archive/signalflow17.5/. Its native
and sharing exports still match their original hashes:

```text
120fps  e03ede6ec36e98e319e03b3f71f3b0ee854732682508a79e77c0a19650225670
60fps   1f6c7832f6c458ac4d3bda9a0b3ced3edc300a40e88a421abac6cdfdb094f341
```

Nothing material was deleted. This turn did not edit frontend/product code,
commit, push, upload a film, publish a package or change an account. Main
advanced independently to 81f7125 during this work; its actual logo remains
byte-identical to the preserved film asset. The film work remains isolated in
the existing untracked videos directory, based on def7b7c.

Logo generation is a video-only experiment. The exact prompt is retained in
assets/brand/a2l-editorial-experiment.prompt.md. README.md documents the tested
one-flag switch back to the original mark without undoing the motion polish.

All three requested changes, both exports and proportionate local checks are
complete. Remaining creative decision: user review of the new logo and motion
in real-time playback. Before public distribution, confirm the existing catalog
music's commercial rights for the relevant provider/account. The film remains
a synthetic, stylized, time-compressed demonstration, not a live product test,
official CS135 document, endorsement or correctness claim.
