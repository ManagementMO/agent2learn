# Signalflow Polish assets and provenance

## Logo and picture

assets/brand/frontend-mark.svg preserves the former frontend book mark from
frontend/public/brand/mark.svg before the approved A2L website rebrand.
It remains the reversible frontend variant. The older generated monogram and
folder-stack artwork remain unused.

This film's editorial variant uses assets/brand/a2l-editorial-experiment.png,
generated with the built-in ChatGPT image-generation tool on 2026-09-08 at the
user's request. Exact prompt: assets/brand/a2l-editorial-experiment.prompt.md.
The original 1774×887 transparent PNG is unchanged. Header/context/footer
placement copies are byte-identical to avoid cross-size raster-cache drift.
The dark terminal inverts the monochrome image as a display treatment only.

The [official D2L wordmark](https://www.d2l.com/wp-content/uploads/2022/08/logo.svg)
was inspected for broad typographic inspiration; it is reference-only under
.media/images/logo_002.svg and is not mounted in the film. The generated A2L
has different lettering and no D2L green underline. This is a reversible design
experiment now also approved by the owner for frontend use. It is not a claim
of D2L affiliation or trademark clearance.

Chrome/Waterloo LEARN and Codex are stylized demo interfaces, not live captures
or endorsements. Public CS135 opening topics inform the example; the term,
LEARN arrangement, study guide and displayed source excerpt are synthetic.
No private screenshots, lecture PDFs, real student/instructor names, grades,
credentials or reference-film artwork/audio are included.

## Monochrome icons

Official Lucide SVG path data, locally frozen via the media workflow:

| File | Source |
| --- | --- |
| assets/icons/file-text.svg | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/file-text.svg |
| assets/icons/notebook-text.svg | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/notebook-text.svg |
| assets/icons/terminal.svg | https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/terminal.svg |

The complete Lucide ISC and applicable Feather MIT notices are retained in
assets/icons/LUCIDE-LICENSE. The film adapts size, stroke width and currentColor
to its light/dark surfaces. The old illustrated sprites are not used for the
visible course, context or source-editor document icons.

## Software

HyperFrames 0.8.35, GSAP 3.14.2, Geist Variable/Mono 5.3.0,
Playwright 1.58.2, FFmpeg, NumPy 2.2.6 and SciPy 1.15.3.
Geist Mono includes its real medium weight rather than relying on synthetic
bold. Dependencies retain their licenses.

Registry references: ui-focus-zoom, code-terminal-run, tilt-card,
arc-motion-path. These informed authored mechanisms; their showcase UI and
branding are not mounted.

## Current preview music — Disclosure (2026-09-11)

**Disclosure — Expressing What Matters**, sourced from the artist's
[official visualiser](https://www.youtube.com/watch?v=nXOSgekiAJc).
The public audio stream was retrieved without account cookies, subscription
changes or DRM circumvention. Local source: `.media/audio/bgm/bgm_017.webm`,
264.701s, Opus stereo/48kHz. The local media resolver froze it as `bgm_017`;
`audio_meta.json` records the source SHA-256 and public source URL.

The audition uses source **0.00–17.50s**, playback rate **1.0**, two-pass loudness
preparation (-20 LUFS target, -6 dBTP ceiling, no added mastering gain) and a
native HyperFrames volume envelope. The short quiet opening belongs to the
recording; no silence was inserted. All established typing/click/receipt/chime/
sweep cues remain unchanged, and both Foley stems are byte-identical to the
previous Launchbeat preview.

Active local files:

- `assets/audio/signalflow-disclosure-{bed,typing,interface}.wav`
- `assets/audio/signalflow-disclosure-mix-reference.wav`
- `renders/agent2learn-signalflow-disclosure-audio.m4a` (audio-only review)

This is a commercial recording, **not an original composition, catalog-cleared
track, or newly generated music**. Availability of a public stream does not
establish rights to publish this synchronization. All source/derived audio is
local and Git-ignored; no upload or MP4 export was performed. Obtain the required
clearance before public release. The owner approved the updated editor mix on
2026-09-11; this is creative approval, not a rights-clearance claim.

## Previous preview music and Foley — Launchbeat (2026-09-08)

New bed: `.media/audio/bgm/bgm_012.wav`, retrieved through the existing signed-in
HeyGen catalog. Provider track ID: `840f825204824c678f82835e27044fca`; catalog
description: “energetic house disco instrumental, upbeat tempo, neon vibes”.
This is catalog music, **not a newly composed original song**.

The editorial source window starts at 0.454s and consumes 18.2 source seconds
at a pitch-preserving rate of 1.04, producing the 17.5s bed without looping.
Two-pass loudness preparation and the existing separate-stem workflow are used;
the final volume envelope is authored in HyperFrames, not baked into its bed.
The prepared bed is additionally registered as `bgm_016` in the local media ledger.

New quiet context/brand accent: `.media/audio/sfx/sfx_006.mp3`, HeyGen catalog
track `fd8d6893299c363d`, described as a brief bright synthesized UI chime.
It lands at 7.82s and 16.10s, with bounded level and bandwidth. All original
keyboard/click/sweep sources below remain in use. The keyboard stem is
byte-identical; some interface gains and sweep levels are slightly increased.

Preserved local stems: `assets/audio/signalflow-launchbeat-{bed,typing,interface}.wav`.
The independent listening mix is `signalflow-launchbeat-mix-reference.wav`.
An AAC audio-only review is in `renders/agent2learn-signalflow-launchbeat-audio.m4a`.
No finished MP4 was replaced. This revision's metadata is now preserved in
`.archive/signalflow-launchbeat-audio/audio_meta.json`; `audio_meta.json` tracks
the active Disclosure audition.

Two other newly retrieved alternatives are retained but unused: `bgm_013`
(short pop beat with a long quiet tail) and `bgm_015` (slower bounce-style groove).
The resolver also adopted an older local `assets/audio/music.wav` as `bgm_014`;
that is not a fresh download and was not selected. Selection uses catalog
descriptions and waveform/rhythm checks; a human listening review is still owed.

The owner allowed non-copyright-free material for this audition. Catalog access
and provenance do not independently establish public-distribution rights.
No subscription change, public upload, or new rights-clearance claim was made.

## Previous approved movie soundtrack — preserved

Music is catalog sourced, not an original composition. Custom work is the
editorial trim, 43 recorded-key placements and one paste gesture, varied key
pressure/transients, action clicks, transition sweeps, ducking and mix.

Existing locally retained sources:

| Local source | Use |
| --- | --- |
| .media/audio/bgm/bgm_011.wav | Established electronic groove from 15.60–33.10s |
| .media/audio/sfx/sfx_003.mp3 | Seven isolated recorded keyboard variants |
| .media/audio/sfx/sfx_002.mp3 | Dry course/citation/receipt clicks |
| .media/audio/sfx/sfx_004.mp3 | Enter and confirmation gestures |
| .media/audio/sfx/sfx_005.mp3 | Soft camera sweeps |

Metadata and source hashes are in audio_meta.json and .media/manifest.jsonl.
This edit did not retrieve new music or change an account/subscription.

The renderer consumes assets/audio/signalflow-polish-bed.wav,
signalflow-polish-typing.wav and signalflow-polish-interface.wav, all 48kHz stereo.
signalflow-polish-mix-reference.wav independently combines them with the same
automation for comparison. The assistant's text streaming has no typing Foley.

Source-arrival accents: 7.20/7.36/7.52s; context-ready: 7.82s. Keyboard and music
retain the approved Signalflow treatment; only the receipt accents are retimed.
Final levels and encoded sync are reported separately.

Catalog access/provenance is not independent distribution-rights clearance.
Confirm the provider/account's commercial music rights before a public campaign.
No human headphone/speaker review or rights clearance is claimed.

The Signalflow, glassflow, launchflow and codex-demo exports/audio are preserved.
