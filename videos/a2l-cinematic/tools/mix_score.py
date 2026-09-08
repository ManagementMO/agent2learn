"""Build the 18s launch mix from frozen catalog music and timed sound effects.

Only ordinary audio files enter this mixer; credentials and catalog URLs never
enter the project. The edit uses a continuous eighteen-second musical phrase, places UI
accents on picture cuts, and leaves the citation reveal quieter and readable.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

RATE = 48000
ROOT = Path(__file__).resolve().parent.parent


def read_audio(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "2",
            "-ar",
            str(RATE),
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2).astype(np.float64)


music = read_audio(ROOT / "assets/audio/music.wav")
# Find the strongest low-frequency phase on the advertised 120 BPM grid.
mono = music.mean(axis=1)
low = sosfilt(butter(3, 170, fs=RATE, output="sos"), mono)
hop = 480
energy = np.sqrt(np.mean(low[: len(low) // hop * hop].reshape(-1, hop) ** 2, axis=1))
flux = np.maximum(0, np.diff(energy, prepend=energy[0]))
phase_scores = []
for phase in np.arange(0, 0.5, 0.01):
    indices = np.round((phase + np.arange(0, 20, 0.5)) * 100).astype(int)
    phase_scores.append(sum(max(flux[max(0, i - 1) : i + 2]) for i in indices))
phase = int(np.argmax(phase_scores)) * 0.01
offset = int(phase * RATE)
bed = music[offset : offset + 18 * RATE].copy()
assert len(bed) == 18 * RATE
times = np.arange(len(bed)) / RATE


def smooth(a, b):
    p = np.clip((times - a) / (b - a), 0, 1)
    return p * p * (3 - 2 * p)


gain = 0.86 + 0.14 * smooth(1.5, 2)
gain *= 1 - 0.22 * (smooth(8.85, 9.2) - smooth(12.2, 12.5))
gain *= np.minimum(times / 0.025, 1)
gain *= 1 - smooth(16.65, 17.98)
bed *= gain[:, None]
mix = bed.copy()
whoosh = read_audio(ROOT / "assets/audio/whoosh.mp3")
click = read_audio(ROOT / "assets/audio/click.mp3")
whoosh /= max(0.001, np.max(np.abs(whoosh)))
click /= max(0.001, np.max(np.abs(click)))


def add(sound, at, volume, pan=0):
    start = int(at * RATE)
    end = min(len(mix), start + len(sound))
    stereo = np.array([1 - max(0, pan) * 0.35, 1 + min(0, pan) * 0.35])
    mix[start:end] += sound[: end - start] * volume * stereo


for at, vol, pan in [
    (1.66, 0.04, 0),
    (4.66, 0.05, -0.5),
    (6.36, 0.04, 0.4),
    (8.86, 0.04, -0.5),
    (12.36, 0.05, 0.4),
    (14.86, 0.05, 0),
]:
    add(whoosh, at, vol, pan)
for at in [2.30, 2.46, 2.62, 7.78, 8.79, 9.39]:
    add(click, at, 0.018 if at < 7 else 0.035)
# Broadband sub impacts are original, short, unpitched transition accents.
for at in [1.8, 4.8, 12.5, 15]:
    t = np.arange(int(0.5 * RATE)) / RATE
    phase_drop = 2 * np.pi * (42 * t + 33 * 0.065 * (1 - np.exp(-t / 0.065)))
    hit = np.sin(phase_drop) * np.exp(-t * 13) * (1 - np.exp(-t * 600)) * 0.04
    add(np.stack([hit, hit], axis=1), at, 1)

raw = ROOT / "assets/score-raw.wav"
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
final = ROOT / "assets/score.wav"
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(raw),
        "-af",
        "loudnorm=I=-15:TP=-1.5:LRA=8",
        "-ar",
        str(RATE),
        "-c:a",
        "pcm_s24le",
        str(final),
    ],
    check=True,
)
report = {
    "duration": 18,
    "sample_rate": RATE,
    "channels": 2,
    "catalog_bpm": 120,
    "estimated_grid_phase_seconds": phase,
    "source_sections": [[phase, phase + 18]],
    "music": "assets/audio/music.wav",
    "effects": ["assets/audio/whoosh.mp3", "assets/audio/click.mp3"],
    "loudness_target_lufs": -15,
    "true_peak_ceiling_dbtp": -1.5,
    "citation_duck_seconds": [8.85, 12.5],
}
(ROOT / "audio_meta.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
