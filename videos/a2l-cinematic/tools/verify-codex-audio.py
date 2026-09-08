"""Check rendered AAC against the independently assembled editable-stem mix."""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE = 48000


def decode(path):
    return np.frombuffer(
        subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(ROOT / path),
                "-vn",
                "-f",
                "f32le",
                "-ar",
                str(RATE),
                "-ac",
                "2",
                "-",
            ]
        ),
        np.float32,
    ).reshape(-1, 2)


cues = json.loads((ROOT / "src/launchflow-cues.json").read_text())
revision = cues["exportPrefix"]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--audio", type=Path, help="An audio-only review encode instead of the final MP4"
)
args = parser.parse_args()
encoded_path = args.audio or Path(f"renders/agent2learn-{revision}-120fps.mp4")
ref = decode(f"assets/audio/{cues['audioPrefix']}-mix-reference.wav")
encoded = decode(encoded_path)[: len(ref)]
assert len(encoded) == len(ref), "Encoded audio must span the complete film"
assert np.isfinite(encoded).all()
results = []
for start, end, label in [
    (0, 3.1, "install typing"),
    (4.8, 5.5, "sync typing"),
    (5.62, 8.15, "course ingestion and context receipts"),
    (8.65, 10.28, "question typing"),
    (12.8, 13.95, "source click"),
    (15.65, 17.5, "outro fade"),
]:
    a = ref[round(start * RATE) : round(end * RATE)].flatten()
    b = encoded[round(start * RATE) : round(end * RATE)].flatten()
    corr = float(np.corrcoef(a, b)[0, 1])
    gain = float(20 * np.log10(np.sqrt(np.mean(b * b)) / np.sqrt(np.mean(a * a))))
    assert corr > 0.96, f"Exported {label} must retain the designed waveform: {corr}"
    assert abs(gain) < 0.6, f"Exported {label} must retain intended levels: {gain}"
    results.append(
        {
            "section": label,
            "start": start,
            "end": end,
            "waveform_correlation": corr,
            "gain_difference_db": gain,
        }
    )
peak = float(20 * np.log10(np.max(np.abs(encoded))))
tail = float(20 * np.log10(max(float(np.sqrt(np.mean(encoded[-480:] ** 2))), 1e-10)))
assert peak < -1, "AAC must preserve at least 1 dB sample-peak headroom"
assert tail < -45, "End of encoded music must fade cleanly"
report = {
    "status": "passed",
    "encoded_file": str(encoded_path),
    "audio_only_review": args.audio is not None,
    "samples_per_channel": len(encoded),
    "sample_peak_dbfs": peak,
    "last_10ms_rms_dbfs": tail,
    "sections": results,
    "scope": "Waveform/level/sync check, not human listening or music-rights clearance",
}
(ROOT / f".checks/{revision}-audio-verification.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(json.dumps(report, indent=2))
