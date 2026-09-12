# Disclosure opening — local soundtrack audition

Date: 2026-09-11. Project: `videos/a2l-cinematic` in the existing
`motion/a2l-cinematic` worktree. Picture baseline:
`dc83d51369cca5b2bc65c6b8e576a45f3049f0bc` (approved upright gold-logo revision).

## Delivered scope

The existing 17.5s film now previews **Disclosure — Expressing What Matters**,
source 0.00–17.50s, at original speed. No picture, brand, course example, typing
cadence, particle trajectory or cut time changed. Both recorded Foley stems
are byte-identical to the previous Launchbeat revision. The bed is restrained,
with gentle native volume automation and a complete end fade.

The recording was retrieved from the
[official Disclosure visualiser](https://www.youtube.com/watch?v=nXOSgekiAJc)
using isolated yt-dlp 2026.08.19. No browser credentials were accessed, no
subscription or purchase was made, and no protected stream was bypassed.
`ffprobe` confirms a 264.701s Opus/stereo/48kHz source. It is locally frozen as
`.media/audio/bgm/bgm_017.webm`; its checksum and source URL are in `audio_meta.json`.
The source has a short quiet opening; this was not added by the mix.

## Local review assets

- Studio: <http://localhost:3017/#project/a2l-cinematic>
- Audio-only AAC: `renders/agent2learn-signalflow-disclosure-audio.m4a`
- Independent mix: `assets/audio/signalflow-disclosure-mix-reference.wav`
- Editable stems: `assets/audio/signalflow-disclosure-{bed,typing,interface}.wav`
- Previous cue/metadata: `.archive/signalflow-launchbeat-audio/`

All music/source/derived audio remains Git-ignored. The prior Launchbeat and
older movie/audio files are retained. **No new MP4 was rendered, no older MP4
was replaced, and no recording or derived audio was uploaded.** The owner
approved the mix and requested source commit/push on 2026-09-11. Publication is
limited to source, mix settings, provenance and verification, not music files.
The separate primary checkout's in-progress frontend work was not edited.

## Fresh verification

1. `npm run score` — passed; three complete 840,000-sample/channel, 48kHz stereo
   stems, 44 input cues, seven recorded keyboard variants.
2. `npm run test:soundtrack` — passed against the actual approved Git picture.
   Source/template/motion/style/brand and compiled picture are unchanged.
   Both Foley WAVs are byte-identical, music automation round-trips through the
   actual HTML, and Studio serves the exact new stem bytes. The test first
   failed on the old Launchbeat source before the swap.
3. `npm test` — passed. 2,100 layout frames, 12 exact forward/reverse DOM and
   pixel seeks, 36 particle trajectories, 6,460 moving samples; no runtime
   errors, failed assets, external requests or unintended overlaps. The 31-frame
   particle absorption and source-line reveal remain unchanged.
4. `npm run check -- --json` — passed on **HyperFrames 0.8.35**, upgraded from
   the previous project pin 0.8.33 under the HyperFrames maintenance workflow.
   Zero lint/runtime/layout/motion errors; 300 motion samples. 148/149 contrast
   checks pass, with the existing non-gating `$` entrance contrast warning at
   4.861s. The approved picture was not altered to suppress that warning.
5. `npm run test:audio -- --audio renders/agent2learn-signalflow-disclosure-audio.m4a`
   — passed across all six edit windows. Minimum encoded waveform correlation
   **0.9968**; greatest level deviation **0.060 dB**; AAC sample peak
   **-6.80 dBFS**, last 10ms RMS **-124.91 dBFS**. The encoded file spans the
   complete 17.5s reference without clipping or an abrupt end.
6. Pre-publication secret scan: the only new findings were the source SHA-256
   and the verifier's public Git baseline SHA. The former was recomputed from
   the local recording; the latter was verified as an ancestor of `origin/main`.
   Only those two exact fingerprints were recorded as non-secret in the existing
   baseline; no scanner rule or file-level exclusion was weakened.

Measured using the actual prepared stems and their authored volume envelopes:

| Measurement | Previous Launchbeat | Disclosure audition |
| --- | ---: | ---: |
| Automated music, integrated LUFS | -15.31 | -21.85 |
| Complete mix, integrated LUFS | -15.26 | -21.73 |
| Complete mix, true peak dBTP | -2.76 | -6.73 |

The music bed is approximately **6.5 LU quieter** while the existing foreground
effects are unchanged. The preparation target (-20 LUFS) is not the final
integrated measurement: the editable envelope lowers it further.

## Boundaries and next review

This is automated source/PCM/encoding and composition verification, not human
headphone/speaker listening, subjective approval, or a newly verified MP4.
The audio-only AAC check compares the review encode to the independent stem
mix; it does not claim that a new HyperFrames movie has been rendered.

The owner approved the updated Studio mix on 2026-09-11. A later movie render
must use the new `signalflow-disclosure`
export prefix, preserve all existing outputs, and run the export/audio gates.

This is a **local audition of a commercial recording**. A public stream is not
proof of synchronization/distribution clearance. Resolve the required rights
before publishing a film with this music. No rights-clearance claim is made.
