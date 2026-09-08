# Verification — Signalflow, 17.5 seconds

Verified locally **2026-09-07 PDT / 2026-09-08 UTC**.
The previous report and sources are preserved in
`.archive/glassflow17.5/`. This report describes the new Signalflow bytes only.

## Delivered bytes

| Export | Format | Frames | Runtime | Size |
| --- | --- | ---: | ---: | ---: |
| `renders/agent2learn-signalflow-120fps.mp4` | 1920×1080, native 120 fps, H.264/yuv420p, AAC stereo 48 kHz | 2,100 | 17.500s | 4,454,959 bytes |
| `renders/agent2learn-signalflow.mp4` | 1920×1080, 60 fps, H.264/yuv420p, AAC stereo 48 kHz | 1,050 | 17.500s | 2,546,774 bytes |

```text
120fps  e03ede6ec36e98e319e03b3f71f3b0ee854732682508a79e77c0a19650225670
60fps   1f6c7832f6c458ac4d3bda9a0b3ced3edc300a40e88a421abac6cdfdb094f341
logo    ea3b7fdb9152b63cfadc7f0bd163ced1519d5562316b95c239f6955db9461483
```

The master samples the authored timeline directly at 120 fps. The sharing copy
selects alternate frames, without generated interpolation, and preserves its
AAC stream. The master declares BT.709 primaries/transfer/matrix and limited
range. Both complete audio/video streams decode without errors. Four encoded
question-typing frames are distinct; the last frame contains the complete
light-background identity lockup, not a blank or black frame.

Final master render: **59.8 seconds**, three workers, high quality, CRF 17,
strict-all and no best-effort fallback. Evidence:
`.checks/render-signalflow.log`, `.checks/signalflow-export.json`.
The compiled picture, cues and three audio stems still match the pre-render
SHA-256 inventory at `.checks/signalflow-source-sha.txt`.

## Behavior, motion and readability

- Build, JavaScript syntax checks and `npm test`: passed.
- Final HyperFrames 0.8.31 strict check: **zero errors and warnings** in lint,
  runtime, layout, motion and contrast. **438 layout samples**, including
  **379 transition samples**, none dropped. Motion assertions use 300 samples.
- A separate contrast pass checks 1.7, 5.4, 8.05, 12.1 and 14.5 seconds:
  **236/236 text samples pass**, including the source editor after pullback.
- Custom geometry sweep: **all 2,100 master timestamps**. No tested unintended
  header/stage, terminal-row, answer/citation/footer, source/proof, panel,
  material-card or identity-lockup collision. Resting panels fit the stage;
  LEARN and incoming Codex shells remain separated during the handoff.
- LEARN remains **1400px wide**. Chrome tabs/address controls, Waterloo
  masthead, course navigation and a selected Week 1 module are distinct.
  CS 135 · Fall 2026 is explicitly marked **CS135-INSPIRED DEMO**; the
  term and authenticated course arrangement are illustrative, not observed.
- Three resource icons use locally frozen Lucide file-text/notebook-text path
  data: 24×24, currentColor, no fill, monochrome `rgb(37,37,37)`.
  Matching source/context icons remain crisp against their light/dark surfaces.
- Chapter labels are 33px/650, without numbers. Their glyphs fit the masks at
  rest; old letters clear before new letters enter.
- The bounded **36-point pool** links each course row to its own named receipt.
  **289 dense ingestion samples** produce **7,115 moving particle samples**;
  maximum sampled movement is **7.30px per 120fps step**. Points are absent
  before/after their sequence. This is continuity evidence, not a perceptual
  guarantee on every display.
- **12 forward/reverse hero DOM states match exactly** for the inspected
  geometry, transforms, text, opacity, visibility, clipping and visual styles.
- Course click **4.87s** and source click **12.80s** hit the actual targets.
- Five input sequences rewind to exact prefixes. **44 picture/audio events**
  match: 43 recorded-key placements plus one clipboard paste. Phrase pauses
  and non-periodic key intervals are pinned. Assistant output streams whole
  word groups on stable lines and has no artificial keyboard Foley.
- Source lines **39–44** match `assets/demo/content/Week 1/Week 1.md`.
  Line 42 is **“Use prefix notation in Racket.”** The frontend logo is
  byte-identical to its source. No runtime errors, failed assets or external
  asset requests occurred in the compiled-preview test.
- Final logo, wordmark, tagline and URL remain hidden until their own entrances;
  the complete lockup holds from 16.77s through the end.

Evidence: `.checks/signalflow-hyperframes.json`,
`.checks/signalflow-readability.json`, `.checks/signalflow-behavior.json`,
`.checks/signalflow-layout.json`, `.checks/signalflow-keyframes.json`.

## Findings corrected and limitations retained

The first reverse-seek test exposed Chrome repaint differences around scaled
terminal strokes. Inset strokes preserve the shape without a separately
rounded CSS border. Stationary terminal text no longer receives unnecessary
identity transforms. A second controlled probe isolated cached particle-glow
raster differences: removing persistent GPU promotion reduced that probe to
zero changed pixels without changing the trajectories or broadening the test.

The final test retains the original narrow raster tolerance. Eight hero PNG
pairs are byte-identical; four differ by **1–6 pixels out of 2,073,600**, maximum
channel delta **15/255** at tiny text/edge pixels. DOM states are exact; universal
byte-identical Chrome rasterization is not claimed. Diagnostic reports are
retained under `.checks/signalflow-*-raster-probe*.json` and
`.checks/signalflow-particle-layer-probe.json`.

The sync strip originally faded its black surface under pale text, briefly
washing out contrast. It now retracts with an opaque mask. The encoded 5.65s
exit was inspected and the contrast warning is gone.

One **informational** layout finding remains at 6.25s: the departing browser's
projected demo-label box crosses the header in geometry. Its actual pixels
are clipped below y240 by the stage. The exact encoded frame at
`.checks/signalflow-encoded/clipped-browser.png` shows no painted header
overlap. No blanket overlap or occlusion waiver was added.

The static keyframe extractor cannot resolve every helper/loop-generated
target. Its workspace onion-skin image contains guides rather than a reliable
fully painted camera sequence and is **not** used as visual proof. Actual
runtime seeks and the six-frame encoded camera strip verify the 12.92–13.72s
move instead. Keyframe JSON remains useful structural evidence only.

## Encoded audio

The established catalog groove is retained from source seconds 15.60–33.10.
This revision softens/re-times seven recorded keyboard variants, introduces a
single paste gesture, keeps assistant streaming silent, and synchronizes the
source arrivals at 7.34/7.48/7.62s and context-ready at 7.82s.

| Measurement of the delivered AAC | Result |
| --- | ---: |
| Integrated loudness | −17.58 LUFS |
| Loudness range | 8.50 LU |
| True peak | −3.36 dBTP |
| Sample peak | −3.36 dBFS |
| Final 10ms RMS | −85.07 dBFS |
| Samples per channel | 840,000 |

All six waveform sections pass against the independently assembled stem mix:
install, sync, ingestion, question, source click and outro. Correlation is
**0.99767–0.99938**; absolute gain differences are below **0.086 dB**.
Timing/ducking survives export and the fade ends cleanly. The loudness values
above are the input measurements of the delivered AAC, not the hypothetical
normalized output of the analysis filter.

Evidence: `.checks/signalflow-audio-verification.json`,
`.checks/signalflow-aac-levels.log`, `audio_meta.json`.
These are waveform/level checks, not human headphone review or rights clearance.
Music is catalog sourced with custom editorial/Foley work, not a new composition.

## Encoded visual review

Inspected the finished master, not only the browser preview:

- `renders/signalflow-storyboard.jpg`: eight ordered scene heroes.
- `renders/signalflow-dense-review.jpg`: **70 frames at 4 fps** across the film.
- `renders/signalflow-ingestion-review.jpg`: **36 frames at 12 fps** through
  document dissolution, curved point flow and named-source arrival.
- `.checks/signalflow-camera-encoded.jpg`: six camera poses, 12.92–13.72s.
- `renders/signalflow-poster.png`: full-resolution answer/source-editor pair.
- `.checks/signalflow-encoded/`: full-resolution LEARN, sync exit, handoff,
  context, answer, clipping diagnostic and final-lockup evidence.

The overview and close-ups show the intended sequence, readable source
emphasis, intact typography and separated panels. This is visual inspection,
not a claim of subjective artistic perfection or human real-time playback review.

## Preservation and handoff

Previous glassflow exports retain their original SHA-256 values:

```text
120fps  796414a7ac2cc795b9730e67212b4aa2eefac55900da538583492eecf5be6eaf
60fps   96acc708d0ac6c2c6bf9c09a6ae1db1458b9a98ded2b1ffd6996ef5b1791e06c
```

Previous source/docs are in `.archive/glassflow17.5/`; glassflow audio and
all older archives/exports remain in place. Nothing material was deleted.

Main remains `def7b7c` with only its pre-existing untracked `frontend/`.
Film work remains in `motion/a2l-cinematic` under the existing untracked
`videos/` directory. No product/frontend edit, commit, push, release,
public upload, paid generation or sign-in was performed. Studio responds
HTTP 200 at `http://localhost:3017/#project/a2l-cinematic`.

The film is a synthetic, stylized, time-compressed demonstration, not evidence
of a live installation/authentication/sync/Codex run. Public CS135 topic labels
informed the example; no private accounts, screenshots or lecture PDFs are
embedded. The original study-guide excerpt is not an official CS135 source,
a full provenance-backed vault, an endorsement or a correctness claim.

The requested local revision, both exports and proportionate technical checks
are complete. Remaining owner review: visual/music taste in real-time playback,
plus provider/account commercial music distribution rights before publishing.
See CREDITS.md and RESEARCH.md for provenance and source boundaries.
