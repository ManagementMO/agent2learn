# Launchbeat — soundtrack-only preview verification

Date: 2026-09-08. Project: `videos/a2l-cinematic`, branch `motion/a2l-cinematic`.
Picture baseline: approved commit `bd77b17402c18e3b671598e893517035c1578cbe`.

## Outcome

The active 17.5s Studio preview has a new upbeat house/disco bed, a 4%
pitch-preserving tempo lift, more present transition/receipt accents and two
quiet UI chimes. The previous movie exports and audio stems remain intact.
This is ready for the owner's listening review, not a claim of subjective
perfection, music-rights clearance, or a newly exported final movie.

## Evidence

The soundtrack evidence below records the music-only pass. A subsequent owner
request removes the long bottom disclaimer and cleans up the Content tab's side
edges while preserving its blue text and underline. The boundary verifier permits
only those two exact picture edits against the same approved baseline; motion,
timing, other picture markup and the new audio remain protected.

Post-cleanup verification passed: `npm test`, `node tools/verify-soundtrack-edit.mjs`,
and `npm run check -- --strict --samples 9 --at 1.7,5.4,8.05,12.1,14.5,17.2`.
The latter reports no errors/warnings, 162/162 contrast passes, and the same
pre-existing information-only overlap at 6.25s. The removed-footer regression
was first observed failing on the old live DOM. Inspected both the full 5.4s
frame and the new Content underline at 96% preview scale / 2x display density.
Existing MP4s remain unchanged; these edits apply to Studio and subsequent renders.

- `node tools/verify-soundtrack-edit.mjs`: passed. Compiled picture HTML/motion,
  visual source/CSS, logo selection, typing, response and action timing match
  the approved baseline. The only excluded HTML differences are audio elements
  and the cue payload, whose picture-driving fields are compared separately.
- The typing stem is byte-identical to the previous cut. Its seven recorded
  variants still follow 43 individual keys plus one paste gesture.
- All three new stems return HTTP 200 from the actual Studio preview endpoint,
  and the served bytes equal the authored local files.
- `npm test`: passed. 2,100 layout samples, 12 exact forward/reverse DOM states,
  both pointer hit targets, source lines 39–44, all 44 input sound events and
  36 particle trajectories passed. Tiny bounded raster differences are recorded
  in the generated report; no runtime errors, failed assets or external requests.
- `npm run check -- --strict --samples 24 --at-transitions`: passed. Zero lint,
  runtime or motion errors/warnings; 165/165 contrast checks pass. One transient
  transition-overlap information item at 6.25s remains in the unchanged picture.
- Local mix: 48 kHz stereo, 840,000 samples/channel, 17.5s. FFmpeg EBU R128:
  **−15.2 LUFS**, 2.2 LU loudness range, **−2.8 dBFS true peak**.
- AAC audio-only review: **−15.3 LUFS**, **−1.4 dBFS true peak**. The independent
  waveform verifier passes all six sections: correlations 0.99867–0.99963,
  gain differences within 0.021 dB; sample peak −1.85 dBFS and a silent final
  10 ms. This verifies the audio-only encode, not a new HyperFrames MP4 mix.
- CLI update probe reports the project/current version as 0.8.31; no upgrade.

## Source selection

`bgm_012` has a sustained house/disco pulse across the entire selected window.
The other retrieved pop candidate (`bgm_013`) has useful energy only for its
opening seconds and then a quiet tail; repeating it would require an artificial
loop. The bounce candidate (`bgm_015`) suggests a slower pulse. The local script
`tools/audition-music.py` reports onset/rhythm estimates, not subjective listening
or a ground-truth BPM measurement. Original catalog descriptions are preserved.

The old bed's chosen 15.6s offset ran into the source's quieter ending during
the film's final seconds. The new selected window remains rhythmic through the
brand reveal; the authored envelope now controls its final fade.

## Reproduction and preservation

`npm run score` now prepares the cue sheet, builds all audio stems, and only then
publishes replacement audio paths in the compiled composition. A check confirms
`node tools/build.mjs --cues-only` leaves `index.html` untouched. This avoids
exposing missing replacement stems in Studio if audio preparation fails.
The two-pass loudnorm parser also handles FFmpeg summary text after its JSON.

```sh
npm run score
node tools/verify-soundtrack-edit.mjs
npm test
HYPERFRAMES_NO_TELEMETRY=1 npm run check -- --strict --samples 24 --at-transitions
uv run --no-project --python 3.12 --with numpy==2.2.6 python tools/verify-codex-audio.py --audio renders/agent2learn-signalflow-launchbeat-audio.m4a
```

Original cues and audio metadata are copied under the ignored local
`.archive/signalflow-agent-audio/` folder. Existing `signalflow-polish` stems and
`signalflow-agent` MP4s were not overwritten. Raw catalog assets and review audio
remain local/ignored. No commit, push or public publication was performed during
the soundtrack audition; source publication is a separately authorized follow-up.

## Source-publication verification — 2026-09-08

The owner subsequently requested commit/push/PR of the current work. The branch
was fast-forwarded to the existing PR #8 merge (`54d58e1`) without changing its
picture tree. Fresh pre-publication evidence:

- Python suite: **943 passed, 4 skipped**; separate branch-enabled coverage run
  passed the 77.5% floor with **79.45% total coverage**.
- Ruff lint, core format checks, mypy (88 files), the 20-fixture reproducibility
  check, and third-party notices all passed with the locked extras installed.
- The film behavior test, soundtrack/picture boundary verifier, strict HyperFrames
  check and AAC audio-only waveform verifier passed again. The existing
  information-only transition overlap at 6.25s is unchanged.
- Corrected three Python line-length failures in the audio tooling using the
  project formatter. No audio, motion or cue values changed during formatting.
- Secret-scan findings were verified against the actual source bytes: the two
  new values are SHA-256 checksums for `bgm_012` and `sfx_006`, not credentials.
  Their exact fingerprints were added to the existing baseline; the hook then
  refreshed existing audio line numbers and removed the superseded music digest.
  No detector, path filter or entropy threshold was relaxed.

Only source, documentation, schedules, metadata and the reviewed checksum
baseline are intended for GitHub. Catalog assets, audio stems, MP4s, reference
material and caches remain local under the existing ignore policy. This source
publication does not export a new MP4 or clear music-distribution rights.
