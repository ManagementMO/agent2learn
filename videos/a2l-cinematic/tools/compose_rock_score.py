"""Original six-bar pop-rock launch cue, authored to this film's exact edit.

The MIDI is our composition; GeneralUser GS supplies the sampled instruments.
No reference-video audio, commercial song, catalog melody, or neural imitation
is used. The instrument bank is downloaded separately and checked by SHA-256.
Run through npm run score:rock. FluidSynth and FFmpeg must be installed.
"""

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mido
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".media" / "rock-score"
ASSETS = ROOT / "assets"
FONT = ROOT / ".media" / "soundfonts" / "GeneralUser-GS.sf2"
# Pinned digest of the historical, locally retained soundfont.
FONT_SHA = (
    "9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe"  # pragma: allowlist secret
)
SR, BPM, LENGTH, PPQ = 48000, 144, 10, 960
BEAT = 60 / BPM
RNG = np.random.default_rng(2046)
WORK.mkdir(parents=True, exist_ok=True)
if not FONT.is_file() or hashlib.sha256(FONT.read_bytes()).hexdigest() != FONT_SHA:
    raise SystemExit("Missing or changed GeneralUser GS bank; see CREDITS.md.")


class Part:
    def __init__(self, name, channel, program, pan=64, volume=100):
        self.name, self.channel, self.events = name, channel, []
        for message in [
            mido.Message("program_change", channel=channel, program=program),
            mido.Message("control_change", channel=channel, control=7, value=volume),
            mido.Message("control_change", channel=channel, control=10, value=pan),
            mido.Message("control_change", channel=channel, control=91, value=18),
            mido.Message("control_change", channel=channel, control=93, value=0),
        ]:
            self.events.append((0, message))

    def note(self, pitch, beat, length, velocity):
        tick = max(0, round(beat * PPQ))
        end = max(tick + 1, round((beat + length) * PPQ))
        self.events += [
            (
                tick,
                mido.Message("note_on", channel=self.channel, note=pitch, velocity=int(velocity)),
            ),
            (end, mido.Message("note_off", channel=self.channel, note=pitch, velocity=0)),
        ]

    def track(self):
        track = mido.MidiTrack([mido.MetaMessage("track_name", name=self.name)])
        prior = 0
        for tick, message in sorted(self.events, key=lambda event: event[0]):
            track.append(message.copy(time=tick - prior))
            prior = tick
        track.append(mido.MetaMessage("end_of_track", time=max(0, 24 * PPQ - prior)))
        return track


# General MIDI uses zero-based program numbers here. Independent performances
# (different strum spacing, accents and articulation) create the stereo width;
# this is not one mono guitar duplicated into both channels.
left = Part("Rhythm guitar left", 0, 29, 24, 95)
right = Part("Rhythm guitar right", 1, 30, 104, 81)
bass = Part("Picked electric bass", 2, 34, 64, 104)
lead = Part("Clean electric hook", 3, 27, 58, 93)
drums = Part("Pop-rock kit", 9, 0, 64, 117)
parts = [left, right, bass, lead, drums]

# D – A – Bm – G – A – D. Six bars; the final tonic is a real cadence,
# with 1.5 seconds to ring under the completed brand lockup.
roots = [50, 45, 47, 43, 45, 50]
for bar, root in enumerate(roots):
    for step in range(8):
        at = bar * 4 + step / 2
        if bar == 5 and step > 0:
            continue
        # One little breath at the citation click; the pulse returns on source.
        if 14.5 <= at < 15.5:
            continue
        sustain = 3.5 if bar == 5 else (0.43 if step in [0, 3, 6] else 0.23)
        velocity = (111 if step in [0, 3, 6] else 89) + (2 if bar == 2 else 0)
        for voice, offset in enumerate([0, 7, 12]):
            left.note(root + offset, at + voice * 0.011, sustain, velocity - voice * 5)
            right.note(
                root + offset, at + 0.022 + voice * 0.013, sustain * 0.95, velocity - 5 - voice * 3
            )
        bass.note(root - 12, at, 3.5 if bar == 5 else 0.40, 108 if step % 2 == 0 else 90)
    if bar < 5:
        for at in [0, 1.5, 2, 2.75]:
            drums.note(36, bar * 4 + at, 0.16, 121 if at in [0, 2] else 101)
        for at in [1, 3]:
            drums.note(38, bar * 4 + at, 0.12, 119)
            drums.note(39, bar * 4 + at + 0.008, 0.09, 40)
        for step in range(8):
            drums.note(
                46 if step == 7 else 42, bar * 4 + step / 2, 0.12, 79 if step % 2 == 0 else 54
            )
        if bar in [0, 2, 4]:
            drums.note(49, bar * 4, 0.7, 88)
    else:
        drums.note(36, 20, 0.18, 125)
        drums.note(49, 20, 1.7, 105)
        drums.note(38, 20.015, 0.15, 91)

# A singable original hook rather than an arpeggiator left running underneath.
phrases = [
    [
        (0, 74, 0.45),
        (0.75, 78, 0.20),
        (1, 81, 0.60),
        (2, 78, 0.35),
        (2.5, 76, 0.38),
        (3.25, 74, 0.50),
    ],
    [
        (0, 73, 0.45),
        (0.75, 76, 0.20),
        (1, 81, 0.60),
        (2, 76, 0.35),
        (2.5, 73, 0.38),
        (3.25, 69, 0.45),
    ],
    [
        (0, 74, 0.45),
        (0.75, 78, 0.20),
        (1, 83, 0.60),
        (2, 81, 0.35),
        (2.5, 78, 0.38),
        (3.25, 74, 0.45),
    ],
    [(0, 79, 0.75), (1, 78, 0.4), (2.5, 74, 0.45), (3.25, 71, 0.4)],
    [(0, 73, 0.45), (0.75, 76, 0.2), (1, 81, 0.6), (2, 85, 0.4), (2.75, 81, 0.2), (3.25, 76, 0.4)],
    [(0, 78, 1.4), (0, 81, 1.4), (0, 86, 3.4)],
]
for bar, phrase in enumerate(phrases):
    for beat, pitch, length in phrase:
        lead.note(pitch, bar * 4 + beat, length, 102 if beat == 0 else 90)

# Small drummer fills announce the transformation and the final brand cadence.
for at, pitch, velocity in [
    (7.5, 38, 85),
    (7.75, 48, 92),
    (14.75, 38, 72),
    (15.5, 50, 95),
    (18.5, 38, 92),
    (18.75, 48, 101),
    (19.0, 47, 103),
    (19.25, 45, 107),
    (19.5, 43, 111),
    (19.75, 41, 117),
]:
    drums.note(pitch, at, 0.16, velocity)


def midi_file(selected):
    midi = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    midi.tracks.append(
        mido.MidiTrack(
            [
                mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)),
                mido.MetaMessage("time_signature", numerator=4, denominator=4),
                mido.MetaMessage("key_signature", key="D"),
            ]
        )
    )
    midi.tracks.extend(part.track() for part in selected)
    return midi


midi_file(parts).save(ASSETS / "a2l-launch-score.mid")


def render(part):
    path = WORK / part.name.replace(" ", "-")
    midi_file([part]).save(path.with_suffix(".mid"))
    subprocess.run(
        [
            "fluidsynth",
            "-niq",
            "-R",
            "0",
            "-C",
            "0",
            "-r",
            str(SR),
            "-g",
            ".65",
            "-T",
            "wav",
            "-O",
            "float",
            "-F",
            str(path.with_suffix(".wav")),
            str(FONT),
            str(path.with_suffix(".mid")),
        ],
        check=True,
        capture_output=True,
    )
    rate, data = wavfile.read(path.with_suffix(".wav"))
    assert rate == SR
    samples = np.zeros((SR * LENGTH, 2), dtype=np.float64)
    samples[: min(len(data), len(samples))] = data[: len(samples)]
    return part.name, samples


with ThreadPoolExecutor(max_workers=5) as pool:
    stems = dict(pool.map(render, parts))


def band(data, low, high):
    return sosfilt(butter(2, [low, high], btype="bandpass", fs=SR, output="sos"), data, axis=0)


guitars = band(stems[left.name] + stems[right.name], 150, 6500)
guitars = np.tanh(guitars * 1.3) / 1.3
low = band(stems[bass.name], 40, 3200)
hook = band(stems[lead.name], 400, 7200)
# A restrained stereo eighth-note slap gives the clean hook a physical space.
delay = round(BEAT * 0.75 * SR)
hook[delay:] += hook[:-delay, ::-1].copy() * 0.19
kit = band(stems[drums.name], 35, 17000)
mix = guitars * 0.9 + low * 1.08 + hook * 0.72 + kit * 1.25
times = np.arange(len(mix)) / SR

# Intentional density drop for the selected citation; not a voiceover duck.
breath = np.interp(times, [0, 5.98, 6.06, 6.39, 6.68, 10], [1, 1, 0.57, 0.57, 1, 1])
mix *= breath[:, None]


def add_sfx(start, length, gain, reverse=False):
    count = round(length * SR)
    t = np.arange(count) / SR
    noise = band(RNG.normal(0, 1, (count, 2)), 900, 6500)
    envelope = np.sin(np.pi * t / length) ** 2
    if reverse:
        envelope *= t / length
    sound = noise * envelope[:, None] * gain
    offset = round(start * SR)
    mix[offset : offset + count] += sound[: len(mix) - offset]


for start, length, gain in [
    (1.22, 0.44, 0.026),
    (2.4, 0.38, 0.024),
    (6.02, 0.26, 0.023),
    (8.18, 0.28, 0.035),
]:
    add_sfx(start, length, gain, True)
for at in [0.69, 4.15, 6.06, 8.45]:
    count = round(0.12 * SR)
    t = np.arange(count) / SR
    hit = np.sin(2 * np.pi * (180 * t - 260 * t**2)) * np.exp(-t * 42) * 0.035
    start = round(at * SR)
    mix[start : start + count] += hit[:, None]

# Tiny mechanical ticks follow the same weighted character table as the visible
# question. The test compares these authored events against the live JS table.
question = "What matters for Lab 4?"
weights = [
    (1.6 if char == " " else 1) + (0.34 if i % 4 == 0 else 0) for i, char in enumerate(question)
]
key_ticks = (3.12 + np.cumsum(weights) / sum(weights) * 0.99).tolist()
for i, at in enumerate(key_ticks):
    count = round(0.026 * SR)
    t = np.arange(count) / SR
    tick = (
        np.sin(2 * np.pi * (1350 + (i % 4) * 110) * t) * 0.0045 + RNG.normal(0, 0.002, count)
    ) * np.exp(-t * 190)
    offset = round(at * SR)
    mix[offset : offset + count] += tick[:, None]

mix *= np.interp(times, [0, 0.004, 9.50, 9.97, 10], [0, 1, 1, 0, 0])[:, None]
peak = np.max(np.abs(mix))
mix /= max(1, peak / 0.90)
raw = WORK / "rock-mix.wav"
wavfile.write(raw, SR, mix.astype(np.float32))

# Two-pass loudness preserves the punch of an already-balanced short music cue.
probe = subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(raw),
        "-af",
        "loudnorm=I=-14:TP=-1.8:LRA=7:print_format=json",
        "-f",
        "null",
        "-",
    ],
    check=True,
    capture_output=True,
    text=True,
)
analysis, _ = json.JSONDecoder().raw_decode(probe.stderr[probe.stderr.rfind("{") :])
normalizer = (
    "loudnorm=I=-14:TP=-1.8:LRA=7:linear=true:"
    f"measured_I={analysis['input_i']}:measured_TP={analysis['input_tp']}:"
    f"measured_LRA={analysis['input_lra']}:measured_thresh={analysis['input_thresh']}:"
    f"offset={analysis['target_offset']}"
)
output = ASSETS / "score.wav"
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(raw),
        "-af",
        normalizer,
        "-t",
        str(LENGTH),
        "-ar",
        str(SR),
        "-c:a",
        "pcm_s24le",
        str(output),
    ],
    check=True,
)
metadata = {
    "title": "Agent-ready",
    "type": "original authored instrumental pop-rock",
    "duration_seconds": LENGTH,
    "bpm": BPM,
    "key": "D major",
    "bars": 6,
    "sample_rate": SR,
    "channels": 2,
    "score": "assets/score.wav",
    "midi": "assets/a2l-launch-score.mid",
    "generator": "tools/compose_rock_score.py",
    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "soundfont": {
        "name": "GeneralUser GS 2.0.3",
        "author": "S. Christian Collins",
        "source": "https://github.com/mrbumpy409/GeneralUser-GS",
        # Public upstream source revision, not an account credential.
        "commit": "684543d5e5efaef08d02be50dcda8d552478fa60",  # pragma: allowlist secret
        "sha256": FONT_SHA,
        "license": (
            "See CREDITS.md; music use is permitted, source-sample provenance caveat retained."
        ),
    },
    "sync_hits_seconds": [0.69, 4.15, 6.06, 8.45],
    "citation_break_seconds": [5.98, 6.68],
    "typing_text": question,
    "typing_ticks_seconds": key_ticks,
    "camera_sweeps_seconds": [1.22, 2.4, 6.02, 8.18],
    "target_lufs": -14,
    "target_true_peak_dbtp": -1.8,
    "raw_loudness": analysis,
    "vocals": False,
    "reference_audio_used": False,
}
(ROOT / "audio_meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps(metadata, indent=2))
