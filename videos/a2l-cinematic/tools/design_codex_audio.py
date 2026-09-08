"""Edit catalog music and recorded Foley into frame-synchronized demo stems.

This does not synthesize another MIDI rock track. The music is catalog sourced;
the custom work is the edit, transient selection, cue placement and mix. Track
volume automation remains editable in HyperFrames rather than baked into the bed.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks

RATE = 48000
ROOT = Path(__file__).resolve().parents[1]
CUES = json.loads((ROOT / "assets/cue-sheet.json").read_text())
N = round(CUES["duration"] * RATE)
PREFIX = CUES.get("audioPrefix", "codex")
OUT = ROOT / "assets/audio"
OUT.mkdir(parents=True, exist_ok=True)


def decode(path, filters=None):
    args = ["ffmpeg", "-v", "error", "-i", str(ROOT / path)]
    if filters:
        args += ["-af", filters]
    args += ["-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"]
    return np.frombuffer(subprocess.check_output(args), np.float32).reshape(-1, 2).copy()


def fade(sample, attack=0.001, release=0.006):
    a, r = min(round(attack * RATE), len(sample)), min(round(release * RATE), len(sample))
    sample = sample.copy()
    sample[:a] *= np.linspace(0, 1, a)[:, None]
    sample[-r:] *= np.linspace(1, 0, r)[:, None]
    return sample


def peak_normalize(sample, db):
    return sample * (10 ** (db / 20)) / max(float(np.max(np.abs(sample))), 1e-8)


def write(name, samples):
    if not np.isfinite(samples).all() or np.max(np.abs(samples)) >= 0.99:
        raise ValueError(f"Non-finite or clipped stem: {name}")
    wavfile.write(OUT / name, RATE, np.round(samples * 32767).astype(np.int16))


music = CUES.get("music", {})
music_id = music.get("id", "bgm_011")
music_path = music.get("path", ".media/audio/bgm/bgm_011.wav")
source_start = music.get("sourceStart", 15.6)
playback_rate = music.get("playbackRate", 1)
normalization_lufs = music.get("normalizationLufs", -18)
true_peak_db = music.get("truePeakDb", -3)
mastering_gain_db = music.get("masteringGainDb", 3)
if not 0.5 <= playback_rate <= 2 or source_start < 0:
    raise ValueError("Unsupported music edit")
# Pitch-preserving tempo matching is source preparation, not a picture retime.
# The new source's onset at ~16.73s lands on the 15.65s brand transition.
source_filters = (
    f"atrim=start={source_start}:duration={CUES['duration'] * playback_rate},"
    f"asetpts=PTS-STARTPTS,atempo={playback_rate},highpass=f=45"
)
normalizer = f"loudnorm=I={normalization_lufs}:TP={true_peak_db}:LRA=8"
measurement = subprocess.run(
    [
        "ffmpeg",
        "-v",
        "info",
        "-i",
        str(ROOT / music_path),
        "-af",
        f"{source_filters},{normalizer}:print_format=json",
        "-f",
        "null",
        "-",
    ],
    check=True,
    capture_output=True,
    text=True,
).stderr
# FFmpeg may append its output-summary line after loudnorm's JSON report.
measured, _ = json.JSONDecoder().raw_decode(measurement[measurement.rfind("{") :])
normalizer += (
    f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
    f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
    f":offset={measured['target_offset']}:linear=true"
)
bed = decode(music_path, f"{source_filters},{normalizer}")
bed = bed[:N]
if N - len(bed) > RATE * 0.05:
    raise ValueError("Music source is too short for the complete cut")
if len(bed) < N:  # atempo may round its final analysis window by a few samples
    bed = np.pad(bed, ((0, N - len(bed)), (0, 0)))
MASTER_GAIN = 10 ** (mastering_gain_db / 20)
bed *= MASTER_GAIN
write(f"{PREFIX}-bed.wav", bed)

recording = decode(".media/audio/sfx/sfx_003.mp3", "highpass=f=180,lowpass=f=10500")
mono = np.max(np.abs(recording), axis=1)
envelope = np.convolve(mono, np.ones(96) / 96, mode="same")
peaks, _ = find_peaks(
    envelope, distance=round(0.06 * RATE), prominence=float(envelope.max() * 0.12)
)
# Use a family of genuine recorded transients, so the cadence doesn't sound like
# one synthetic tick copied 43 times. The fixed selection is deterministic.
peaks = sorted(peaks, key=lambda p: float(envelope[p]), reverse=True)[:7]
samples = []
for p in sorted(peaks):
    start = max(0, p - round(0.006 * RATE))
    stop = min(len(recording), p + round(0.037 * RATE))
    samples.append(fade(recording[start:stop], 0.0005, 0.004))
if len(samples) < 4:
    raise ValueError("Too few isolated real keyboard transients")

typing = np.zeros((N, 2), np.float32)
interface = np.zeros((N, 2), np.float32)
events = []


def place(track, sample, time, db, kind, selector=None):
    db += 3  # common mastering lift, preserving the foreground/background ratio
    sample = peak_normalize(sample, db)
    i = round(time * RATE)
    if i < 0 or i >= N:
        raise ValueError("Cue outside composition")
    size = min(len(sample), N - i)
    track[i : i + size] += sample[:size]
    events.append({"time": time, "kind": kind, "selector": selector, "peak_dbfs": db})


for schedule in CUES["typing"]:
    for i, row in enumerate(schedule["rows"]):
        # Soft, varied key pressure, tied to real input only. A paste is one
        # clipboard gesture, not 60 impossible clicks played on top of it.
        variation = float(np.sin((i + 1) * 13.71 + len(schedule["text"]) * 0.7))
        db = -20.8 + variation * 1.25
        is_paste = row.get("kind") == "paste"
        if schedule["text"][row["count"] - 1] == " ":
            db += 0.7
        choice = (i * i + 3 * i + len(schedule["text"])) % len(samples)
        place(
            typing,
            samples[choice],
            row["time"],
            db - 1 if is_paste else db,
            "clipboard_paste" if is_paste else "recorded_key",
            schedule["selector"],
        )

click = decode(".media/audio/sfx/sfx_002.mp3", "highpass=f=180,lowpass=f=9500")
double = decode(".media/audio/sfx/sfx_004.mp3", "highpass=f=160,lowpass=f=9500")
whoosh = decode(".media/audio/sfx/sfx_005.mp3", "highpass=f=400,lowpass=f=6500")


def trim_silence(x):
    active = np.flatnonzero(np.max(np.abs(x), axis=1) > np.max(np.abs(x)) * 0.035)
    return fade(x[max(0, active[0] - 48) : min(len(x), active[-1] + 240)], 0.0005, 0.005)


click, double, whoosh = map(trim_silence, (click, double, whoosh))
for key, db, sound in [
    ("selectCourse", -15, click),
    ("syncComplete", -21, click),
    ("installEnter", -16, double),
    ("installDone", -21, click),
    ("initEnter", -18, double),
    ("launchEnter", -14.5, double),
    ("questionEnter", -13.5, double),
    ("sourceArrival0", -25, click),
    ("sourceArrival1", -24, click),
    ("sourceArrival2", -23, click),
    ("contextReady", -25, double),
    ("openSource", -14, click),
    ("proof", -23, click),
]:
    if key in CUES["actions"]:
        gain = CUES.get("soundGainOverridesDb", {}).get(key, db)
        place(interface, sound, CUES["actions"][key], gain, key)
for at, db in CUES.get("sweeps", [(1.5, -26), (3.0, -25), (9.08, -25), (11.65, -25)]):
    place(interface, whoosh, at, db, "soft_camera_sweep")

if CUES.get("audioAccents"):
    shimmer = trim_silence(decode(CUES["shimmerSource"]["path"], "highpass=f=900,lowpass=f=6500"))
    for cue in CUES["audioAccents"]:
        place(interface, shimmer, cue["time"], cue["gainDb"], cue["kind"])

write(f"{PREFIX}-typing.wav", typing)
write(f"{PREFIX}-interface.wav", interface)

# Also produce a listening/measurement reference. HyperFrames still receives the
# three separate stems plus this exact bed envelope, not the baked mix.
t = np.arange(N) / RATE
points = np.array(CUES["musicEnvelope"])
envelope = np.interp(t, points[:, 0], points[:, 1])
mix = bed * envelope[:, None] + typing + interface
write(f"{PREFIX}-mix-reference.wav", mix)
catalog = [
    json.loads(row) for row in (ROOT / ".media/manifest.jsonl").read_text().splitlines() if row
]
used = [music_id, "sfx_002", "sfx_003", "sfx_004", "sfx_005"]
if CUES.get("audioAccents"):
    used.append(CUES["shimmerSource"]["id"])
sources = []
for row in catalog:
    if row.get("id") in used:
        path = row["path"]
        sources.append(
            {
                "id": row["id"],
                "path": path,
                "description": row.get("description"),
                "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
            }
        )
meta = {
    "duration": CUES["duration"],
    "sample_rate": RATE,
    "channels": 2,
    "music": {
        "id": music_id,
        "source_start": source_start,
        "playback_rate": playback_rate,
        "normalization_lufs": normalization_lufs,
        "true_peak_target_db": true_peak_db,
        "mastering_gain_db": mastering_gain_db,
        "normalization_measurement": measured,
        "authorship": "catalog music; custom editorial and synchronized Foley mix",
    },
    "typing": CUES["typing"],
    "events": sorted(events, key=lambda e: e["time"]),
    "sources": sources,
    "reference_peak_dbfs": float(20 * np.log10(np.max(np.abs(mix)))),
    "automation": CUES["musicEnvelope"],
}
(ROOT / "audio_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
print(
    json.dumps(
        {
            "status": "written",
            "duration": CUES["duration"],
            "key_events": sum(len(s["rows"]) for s in CUES["typing"]),
            "keyboard_variants": len(samples),
            "mix_peak_dbfs": meta["reference_peak_dbfs"],
        },
        indent=2,
    )
)
