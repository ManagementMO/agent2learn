"""Compare local music rhythm/edit points; measurements are not a listening review."""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks, stft


def inspect(path):
    rate, hop = 12000, 120
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ar",
            str(rate),
            "-ac",
            "1",
            "-",
        ]
    )
    samples = np.frombuffer(raw, np.float32)
    _, times, spectrum = stft(samples, rate, nperseg=1024, noverlap=1024 - hop)
    magnitude = np.log1p(20 * np.abs(spectrum))
    flux = np.maximum(np.diff(magnitude, axis=1), 0).sum(axis=0)
    flux = np.r_[0, flux]
    pulse = flux - np.mean(flux)
    ac = correlate(pulse, pulse, mode="full", method="fft")[len(pulse) - 1 :]
    lags = np.arange(round(60 / 170 * rate / hop), round(60 / 85 * rate / hop))
    ranked = sorted(lags, key=lambda i: float(ac[i]), reverse=True)
    tempos = []
    for lag in ranked:
        bpm = 60 * rate / hop / lag
        if all(abs(bpm - row["bpm"]) > 4 for row in tempos):
            tempos.append({"bpm": round(bpm, 2), "periodicity": round(float(ac[lag] / ac[0]), 3)})
        if len(tempos) == 3:
            break
    peaks, _ = find_peaks(flux, distance=12, prominence=max(float(np.std(flux) * 0.75), 1e-6))
    windows = []
    for start in np.arange(0, len(samples) / rate - 4.99, 2.5):
        clip = samples[round(start * rate) : round((start + 5) * rate)]
        event_mask = (times[peaks] >= start) & (times[peaks] < start + 5)
        windows.append(
            {
                "start": round(float(start), 2),
                "rms_dbfs": round(float(20 * np.log10(max(np.sqrt(np.mean(clip**2)), 1e-9))), 2),
                "onsets_per_second": round(float(event_mask.sum() / 5), 2),
            }
        )
    strong = sorted(peaks, key=lambda i: float(flux[i]), reverse=True)[:35]
    return {
        "path": str(path),
        "duration": round(len(samples) / rate, 3),
        "tempo_candidates_not_ground_truth": tempos,
        "windows": windows,
        "strong_onsets": sorted(round(float(times[p]), 3) for p in strong),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([inspect(path) for path in args.files], indent=2))
