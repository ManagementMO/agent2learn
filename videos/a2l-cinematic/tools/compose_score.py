"""Original, deterministic 18-second electronic score for the pearl launch film.

No samples, catalog music, or reference audio enter this version. Notes, drums,
glass mallets, stereo delays and transition effects are synthesized here. Picture
cut times are first-class composition events rather than a stock loop edit.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
RATE = 48000
DURATION = 18
BPM = 160
BEAT = 60 / BPM
N = RATE * DURATION
rng = np.random.default_rng(240907)
stems = {
    name: np.zeros((N, 2), dtype=np.float64)
    for name in ["drums", "bass", "chords", "mallets", "transitions"]
}
events = []


def clock(duration):
    return np.arange(round(duration * RATE)) / RATE


def hz(note):
    return 440 * 2 ** ((note - 69) / 12)


def filt(x, cutoff, mode="lowpass", order=2):
    return sosfilt(butter(order, cutoff, btype=mode, fs=RATE, output="sos"), x)


def envelope(t, attack=0.003, decay=0.2):
    return (1 - np.exp(-t / attack)) * np.exp(-t / decay)


def add(stem, sample, at, level=1, pan=0, delay_send=0):
    start = round(at * RATE)
    if start >= N:
        return
    sample = np.asarray(sample)
    if sample.ndim == 1:
        sample = sample[:, None] * np.array(
            [np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)]
        )
    end = min(N, start + len(sample))
    stems[stem][start:end] += sample[: end - start] * level
    if delay_send:
        for tap in range(1, 5):
            offset = start + round(tap * BEAT * 0.75 * RATE)
            if offset >= N:
                break
            tail = min(N, offset + len(sample))
            echo = sample[:, ::-1] if tap % 2 else sample
            stems[stem][offset:tail] += (
                echo[: tail - offset] * level * delay_send * 0.46 ** (tap - 1)
            )


def kick():
    t = clock(0.32)
    phase = 2 * np.pi * (51 * t + 120 * 0.018 * (1 - np.exp(-t / 0.018)))
    body = np.sin(phase) * envelope(t, 0.0006, 0.075)
    transient = filt(rng.normal(0, 1, len(t)), 3500, "highpass") * np.exp(-t / 0.004)
    return np.tanh(body * 1.6) * 0.62 + transient * 0.055


def clap():
    t = clock(0.22)
    noise = filt(rng.normal(0, 1, len(t)), [950, 7800], "bandpass")
    gate = np.zeros(len(t))
    for at, strength in [(0, 0.8), (0.009, 0.65), (0.022, 1)]:
        gate += np.where(t >= at, strength * np.exp(-np.maximum(0, t - at) / 0.025), 0)
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.03) * 0.11
    return noise * gate * 0.18 + body


def hat(opened=False):
    t = clock(0.23 if opened else 0.065)
    noise = filt(rng.normal(0, 1, len(t)), [6200, 15500], "bandpass")
    return noise * envelope(t, 0.0008, 0.050 if opened else 0.011) * 0.13


def bass(note, duration):
    t = clock(duration)
    f = hz(note)
    core = (
        np.sin(2 * np.pi * f * t)
        + 0.18 * np.sin(2 * np.pi * 2 * f * t)
        + 0.05 * np.sin(2 * np.pi * 3 * f * t)
    )
    return np.tanh(core * 1.3) * envelope(t, 0.004, 0.16) * 0.48


def chord(notes, duration, airy=False):
    t = clock(duration)
    wave = np.zeros((len(t), 2))
    for i, note in enumerate(notes):
        f = hz(note)
        for side, cents in enumerate([-3.2, 3.2]):
            fundamental = 2 * np.pi * f * 2 ** (cents / 1200) * t
            for harmonic in range(1, 9):
                wave[:, side] += np.sin(fundamental * harmonic + i * 0.27) / harmonic**1.8
    for side in range(2):
        wave[:, side] = filt(wave[:, side], 2600 if airy else 1900)
    env = envelope(t, 0.018 if airy else 0.005, 0.75 if airy else 0.20)
    return wave / len(notes) * env[:, None] * 0.34


def mallet(note, duration=0.7):
    t = clock(duration)
    f = hz(note)
    # Short FM glass attack over a softer harmonic body; not a pure sine beep.
    wave = np.sin(2 * np.pi * f * t + 1.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.024))
    wave += 0.21 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / 0.08)
    return filt(wave, 6800) * envelope(t, 0.0018, 0.14) * 0.14


def sweep(at, length=0.34, rising=True, level=0.11):
    t = clock(length)
    noise = rng.normal(0, 1, len(t))
    airy = filt(noise, [1900, 10000], "bandpass")
    shape = (t / length) ** 2 if rising else np.exp(-t / 0.075)
    shape *= np.minimum(t / 0.008, 1) * np.minimum((length - t) / 0.012, 1)
    add("transitions", airy * shape * 0.16, at, level / 0.11, pan=0.12)


# Dmaj9 -> Bm7 -> Gmaj9 -> Asus -> Dmaj9. The motif and harmony are authored,
# not inferred from or sampled out of the inspiration video.
chords = [[50, 57, 61, 66, 69], [47, 54, 57, 62, 66], [43, 50, 54, 57, 62], [45, 52, 57, 62, 64]]
roots = [38, 35, 31, 33]
kick_times = []
for bar in range(10):
    start = bar * 4 * BEAT
    notes = chords[bar % 4]
    root = roots[bar % 4]
    proof = 9 <= start < 12.5
    # Sparse opening; crisp two-step motion grows from the first file transfer.
    positions = [0, 1.5, 2.75] if bar % 2 == 0 else [0, 1.75, 2.5, 3.5]
    for beat in positions:
        at = start + beat * BEAT
        if 9 <= at < 12.5:
            continue
        add("drums", kick(), at, 0.86 if at < 1.8 else 1)
        kick_times.append(at)
        add("bass", bass(root if beat < 2 else root + 12, 0.3), at + 0.013, 0.82)
    for beat in [1, 3]:
        at = start + beat * BEAT
        if not 9 <= at < 12.5:
            add("drums", clap(), at, 0.82)
    for step in range(8):
        at = start + step * 0.5 * BEAT + (0.011 if step % 2 else 0)
        if at >= 15:
            continue
        add(
            "drums",
            hat(step % 4 == 1),
            at,
            0.42 if 9 <= at < 12.5 else 0.78,
            pan=0.25 if step % 2 else -0.25,
        )
    for beat in [0, 0.75, 2, 3.25]:
        at = start + beat * BEAT
        add(
            "chords",
            chord(notes, 1.1 if proof else 0.65, airy=proof),
            at,
            0.67 if proof else 0.88,
            delay_send=0.20,
        )
    motif = [notes[0] + 24, notes[2] + 12, notes[4] + 12, notes[3] + 12]
    for step, note in enumerate(motif):
        at = start + (0.5 + step * 0.75) * BEAT
        add(
            "mallets",
            mallet(note),
            at,
            0.52 if proof else 0.70,
            pan=[-0.26, 0.16, 0.3, -0.12][step],
            delay_send=0.28,
        )

# Picture-specific accents remain exact even when the edit point is syncopated.
for cut in [1.8, 4.8, 6.5, 9, 12.5, 15]:
    sweep(max(0, cut - 0.24), 0.24, True, 0.085)
    sweep(cut, 0.24, False, 0.065)
    events.append({"time": cut, "event": "picture-cut accent"})
for at, note in [(7.76, 78), (8.76, 81), (9.35, 86)]:
    add("mallets", mallet(note, 0.38), at, 0.75, delay_send=0.12)
    events.append({"time": at, "event": "citation motif"})

# Re-entry and logo cadence. The ending resolves, rather than fading a loop mid-bar.
add("drums", kick(), 12.5, 1)
add("bass", bass(38, 0.4), 12.51, 0.9)
add("drums", kick(), 15, 1)
add("chords", chord([50, 57, 61, 66, 69, 76], 3, airy=True), 15, 1.2, delay_send=0.18)
for at, note, level in [
    (15, 74, 0.8),
    (15.375, 78, 0.7),
    (15.75, 81, 0.72),
    (16.125, 85, 0.62),
    (16.5, 86, 0.63),
]:
    add("mallets", mallet(note, 1.2), at, level, delay_send=0.32)

# Gentle ducking creates clean transients without turning the mix into an EDM pump.
times = np.arange(N) / RATE
duck = np.ones(N)
for at in kick_times + [12.5, 15]:
    elapsed = times - at
    duck *= 1 - 0.26 * np.where(elapsed >= 0, np.exp(-np.maximum(0, elapsed) / 0.09), 0)
stems["chords"] *= duck[:, None]
stems["mallets"] *= (0.7 + 0.3 * duck)[:, None]
mix = sum(stems.values())
fade = np.minimum(times / 0.006, 1) * np.clip((17.995 - times) / 0.8, 0, 1)
mix *= fade[:, None]
mix = np.tanh(mix * 1.15) / 1.15
raw = ROOT / "assets/score-custom-raw.wav"
final = ROOT / "assets/score-custom.wav"
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "f32le",
        "-ar",
        str(RATE),
        "-ac",
        "2",
        "-i",
        "pipe:0",
        "-c:a",
        "pcm_s24le",
        str(raw),
    ],
    input=mix.astype("<f4").tobytes(),
    check=True,
)
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(raw),
        "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=7",
        "-ar",
        str(RATE),
        "-c:a",
        "pcm_s24le",
        str(final),
    ],
    check=True,
)
report = {
    "title": "In Context — custom electronic score",
    "duration": DURATION,
    "sample_rate": RATE,
    "channels": 2,
    "bpm": BPM,
    "key": "D major",
    "source": "original deterministic synthesis; no samples",
    "seed": 240907,
    "loudness_target_lufs": -14,
    "true_peak_ceiling_dbtp": -1.5,
    "events": events,
    "file": "assets/score-custom.wav",
}
(ROOT / "audio_custom_meta.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
