#!/usr/bin/env python3
"""
audio_processing_check.py  --  audit source audio for consistent processing.

Usage:
    python3 tools/audio_processing_check.py [prefix ...] [options]
    python3 tools/audio_processing_check.py                      # scan every audio file
    python3 tools/audio_processing_check.py lou skeet             # scan just these NPCs
    python3 tools/audio_processing_check.py --sort floor           # worst noise floor first
    python3 tools/audio_processing_check.py --csv report.csv

Written for a corpus where audio processing (noise floor reduction, a noise
gate, a click filter, and ~0.2s of leading/trailing silence padding) was
applied by hand to some files and not others, over time -- this surfaces
which files still look untouched, purely by inspecting the audio itself
(no before/after reference needed).

For each file it measures, independently for the leading and trailing edge:

  - silence duration -- how long before speech starts / after speech ends,
    using an absolute dB threshold (--threshold, default -35dB) to tell
    silence from speech. Compared against --target (default 0.2s) on the
    short end, and flagged as noticeably long past --max-silence (default
    0.5s -- long enough to read as the game lagging, not just a clean
    pause) on the long end. Both directions matter equally here.
  - noise floor -- the median dB level *within* that silence window. A
    gated/denoised file reads close to digital silence (well under -50dB);
    an untouched recording's room tone/hiss usually sits much higher.

  A fifth, whole-file measure sits alongside the per-edge pair:

  - file floor -- the median dB level across every quiet window in the
    whole file (any stretch below --threshold, not just the leading/
    trailing padding), so a mid-line pause with audible hiss or hum shows
    up even when both edges happen to be clean. This is the more reliable
    read on the recording's actual background noise; the lead/trail floor
    columns are specifically about whether edge processing was applied.

  - click count -- isolated sample-to-sample transients within the silence
    window, the kind a click filter removes. Heuristic and approximate:
    a large jump relative to the window's own local baseline, grouped into
    events by proximity. Treat this column as a rough signal, not a count
    you should trust to the integer -- it's the only one of the four here
    without an unambiguous, verifiable definition.

None of these numbers say a file is "wrong" on their own -- they say
whether it looks like it went through the same processing as the rest of
the corpus. Silence duration is the one truly objective measure (you gave
an exact target); floor and clicks are comparative -- sort by them and look
for the natural break between your already-edited files and the rest.

Configuration comes from vock.cfg, same as vock.py: PATHS["audio"].
Reads any format ffmpeg can decode (mp3, wav, flac, ...), same as vock.py's
own 'wav' step.
"""

import argparse
import configparser
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

_config = {
    "project_root": _ini_parser.get("general", "project_root", fallback="./"),
    "layout":       _ini_parser.get("general", "layout", fallback="flat").strip().lower(),
    "paths":        dict(_ini_parser["paths"]),
}
PATHS = _config["paths"]
_PROJECT_ROOT = (_VOCK_DIR / _config.get("project_root", "./")).resolve()

# audio / wav default to ./audio ./wav (flat layout) or ./work/audio
# ./work/wav (data layout), mirroring vock.py -- a cfg key overrides either.
# See vock.cfg's [paths] comment for why they're commented out by default.
_wk = "./work/" if _config["layout"] == "data" else "./"

# 'wav' (post -16 LUFS normalization) is the default target: an absolute dB
# threshold is only meaningful once every file has been brought to a
# comparable loudness. Raw 'audio/' sources vary file to file with mic/gain,
# so a quiet take can read as silent even when it's genuine speech -- pass
# --source audio to look there instead, with that caveat in mind.
SOURCE_DIRS = {
    "wav":   PATHS.get("wav")   or _wk + "wav",
    "audio": PATHS.get("audio") or _wk + "audio",
}

SAMPLE_RATE = 22050          # matches vock.py's own 'wav' step target rate
WINDOW_MS = 10
MIN_CONSECUTIVE_SPEECH_WINDOWS = 3   # avoid a single noisy blip triggering "speech started"
CLICK_DELTA_MULTIPLIER = 12
CLICK_MIN_ABS_DELTA = 200            # int16 scale floor, so true digital silence doesn't self-trigger
# The ~60ms right after speech ends (or before it starts) is a decay/ring-down
# tail -- a consonant release, room reverb -- not true silence yet, even
# though it's quiet enough to cross the speech threshold. Scanning that
# margin for clicks mistakes normal speech decay for artifacts (confirmed:
# it made a known fully-processed batch score *worse* than an untouched
# one). Click detection only looks past this margin, into the deep interior
# of the silence window.
CLICK_BOUNDARY_MARGIN_MS = 60
CLICK_GROUP_GAP_SAMPLES = 100        # ~4.5ms at 22050Hz -- merge nearby hits into one "click"

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def decode_to_mono_pcm(path: Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any ffmpeg-readable audio file to a mono int16 numpy array."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path),
           "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(sr), "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode(errors="replace").strip() or "ffmpeg produced no output")
    return np.frombuffer(r.stdout, dtype=np.int16)


def windowed_db(samples: np.ndarray, sr: int, window_ms: int = WINDOW_MS) -> np.ndarray:
    win = max(1, int(sr * window_ms / 1000))
    n = len(samples) // win
    if n == 0:
        return np.array([])
    frames = samples[:n * win].astype(np.float64).reshape(n, win)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6) / 32768)


def _first_speech_window(is_speech: np.ndarray, min_run: int) -> int:
    """Index of the first window that starts a run of >= min_run speech windows.
    Returns len(is_speech) if speech never sustains (whole file reads as silence)."""
    run = 0
    for i, v in enumerate(is_speech):
        run = run + 1 if v else 0
        if run >= min_run:
            return i - min_run + 1
    return len(is_speech)


def file_noise_floor(db: np.ndarray, threshold_db: float) -> float | None:
    """Median dB across every window in the file that reads as silence
    (below threshold_db), not just the leading/trailing edges -- so a
    noisy mid-line pause counts even when both edges are clean."""
    silent = db[db <= threshold_db]
    return float(np.median(silent)) if len(silent) > 0 else None


def measure_edge_silence(samples: np.ndarray, db: np.ndarray, win: int, sr: int,
                          threshold_db: float) -> tuple:
    """Returns (leading_s, leading_floor_db, leading_clicks,
                trailing_s, trailing_floor_db, trailing_clicks)."""
    if len(db) == 0:
        return (0.0, None, 0, 0.0, None, 0)

    is_speech = db > threshold_db

    lead_win = _first_speech_window(is_speech, MIN_CONSECUTIVE_SPEECH_WINDOWS)
    trail_win_from_end = _first_speech_window(is_speech[::-1], MIN_CONSECUTIVE_SPEECH_WINDOWS)

    lead_samples = lead_win * win
    trail_samples = trail_win_from_end * win

    lead_s = lead_samples / sr
    trail_s = trail_samples / sr

    lead_floor = float(np.median(db[:lead_win])) if lead_win > 0 else None
    trail_floor = float(np.median(db[len(db) - trail_win_from_end:])) if trail_win_from_end > 0 else None

    margin = int(sr * CLICK_BOUNDARY_MARGIN_MS / 1000)
    # Leading region: speech starts at its right edge, so trim the margin
    # off the end. Trailing region: speech just ended at its left edge, so
    # trim the margin off the start. Whatever's left (if anything) is the
    # deep interior, away from the natural decay tail.
    lead_clicks = count_clicks(samples[:max(0, lead_samples - margin)]) if lead_samples > margin else 0
    trail_start = len(samples) - trail_samples
    trail_clicks = count_clicks(samples[trail_start + margin:]) if trail_samples > margin else 0

    return (lead_s, lead_floor, lead_clicks, trail_s, trail_floor, trail_clicks)


def count_clicks(region: np.ndarray) -> int:
    """Heuristic count of isolated transients within a (presumed silent) region."""
    if len(region) < 3:
        return 0
    delta = np.abs(np.diff(region.astype(np.int64)))
    baseline = float(np.median(delta)) if len(delta) else 0.0
    cutoff = max(baseline * CLICK_DELTA_MULTIPLIER, CLICK_MIN_ABS_DELTA)
    hits = np.nonzero(delta > cutoff)[0]
    if len(hits) == 0:
        return 0
    gaps = np.diff(hits)
    return int(1 + np.sum(gaps > CLICK_GROUP_GAP_SAMPLES))


def analyze_file(path: Path, threshold_db: float) -> dict | None:
    try:
        samples = decode_to_mono_pcm(path)
    except Exception as e:
        return {"stem": path.stem, "error": str(e)}
    if len(samples) == 0:
        return {"stem": path.stem, "error": "empty/undecodable audio"}

    db = windowed_db(samples, SAMPLE_RATE)
    win = max(1, int(SAMPLE_RATE * WINDOW_MS / 1000))

    lead_s, lead_floor, lead_clicks, trail_s, trail_floor, trail_clicks = \
        measure_edge_silence(samples, db, win, SAMPLE_RATE, threshold_db)
    file_floor = file_noise_floor(db, threshold_db)

    return {
        "stem": path.stem, "error": None,
        "src_format": source_format(path.stem),
        "duration": len(samples) / SAMPLE_RATE,
        "lead_s": lead_s, "lead_floor": lead_floor, "lead_clicks": lead_clicks,
        "trail_s": trail_s, "trail_floor": trail_floor, "trail_clicks": trail_clicks,
        "file_floor": file_floor,
    }


def source_format(stem: str) -> str:
    """The original audio/ file's format for this stem, regardless of which
    --source folder is being scanned -- MP3 encoders commonly zero-pad the
    start of a file (encoder priming delay), which can masquerade as a
    noise-gated leading edge even on files nobody has touched."""
    audio_dir = _PROJECT_ROOT / SOURCE_DIRS["audio"]
    matches = list(audio_dir.glob(f"{stem}.*"))
    return matches[0].suffix.lstrip(".").lower() if matches else "?"


SORT_KEYS = {
    "lead":       lambda r: r["lead_s"],
    "trail":      lambda r: r["trail_s"],
    "floor":      lambda r: min(x for x in (r["lead_floor"], r["trail_floor"]) if x is not None) \
                             if r["lead_floor"] is not None or r["trail_floor"] is not None else 999,
    "file-floor": lambda r: r["file_floor"] if r["file_floor"] is not None else 999,
    "clicks":     lambda r: -(r["lead_clicks"] + r["trail_clicks"]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefixes", nargs="*",
        help="Only scan audio tags starting with these prefixes (default: all)")
    parser.add_argument("--source", choices=list(SOURCE_DIRS), default="wav",
        help="Which folder to scan: 'wav' (post-normalization, default -- more "
             "reliable for an absolute dB threshold) or 'audio' (your raw edits, "
             "but loudness varies file to file so the threshold is less trustworthy)")
    parser.add_argument("--threshold", type=float, default=-35.0, metavar="DB",
        help="dB level above which a window counts as speech, not silence (default: -35)")
    parser.add_argument("--target", type=float, default=0.2, metavar="SECONDS",
        help="Target leading/trailing silence duration (default: 0.2)")
    parser.add_argument("--max-lead", type=float, default=0.5, metavar="SECONDS",
        help="Leading silence at or above this is flagged as noticeably long "
             "(default: 0.5) -- the engine waits for audio to actually start, "
             "so a long lead-in reads as the game lagging.")
    parser.add_argument("--max-trail", type=float, default=1.5, metavar="SECONDS",
        help="Trailing silence at or above this is flagged (default: 1.5, much "
             "looser than --max-lead) -- a long tail is mostly harmless since "
             "the engine just discards it once the next audio starts; this only "
             "catches genuinely excessive outliers, not a lag concern.")
    parser.add_argument("--sort", choices=["lead", "trail", "floor", "file-floor", "clicks"], default="trail",
        help="Sort key: shortest silence (lead/trail), noisiest edge floor (floor), "
             "noisiest whole-file floor (file-floor), most clicks (clicks). Default: trail")
    parser.add_argument("--below", type=float, default=None, metavar="SECONDS",
        help="Only show files whose leading OR trailing silence is below N seconds")
    parser.add_argument("--above", type=float, default=None, metavar="SECONDS",
        help="Only show files whose leading OR trailing silence is at or above N seconds")
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument("--csv", metavar="PATH")
    args = parser.parse_args()

    audio_dir = _PROJECT_ROOT / SOURCE_DIRS[args.source]
    if not audio_dir.is_dir():
        sys.exit(f"[ERROR] audio folder not found: {audio_dir}")
    print(f"  Source: {args.source}/  ({audio_dir})")

    paths = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    if args.prefixes:
        prefixes = tuple(p.lower() for p in args.prefixes)
        paths = [p for p in paths if p.stem.lower().startswith(prefixes)]
    if not paths:
        sys.exit("  No matching audio files found.")

    print(f"  Analyzing {len(paths)} file(s)…")
    results, errors = [], []
    for p in paths:
        r = analyze_file(p, args.threshold)
        if r is None:
            continue
        if r.get("error"):
            errors.append(r)
        else:
            results.append(r)

    if args.below is not None:
        results = [r for r in results
                   if r["lead_s"] < args.below or r["trail_s"] < args.below]
    if args.above is not None:
        results = [r for r in results
                   if r["lead_s"] >= args.above or r["trail_s"] >= args.above]

    results.sort(key=SORT_KEYS[args.sort])
    if args.limit is not None:
        results = results[:args.limit]

    def fmt_floor(v):
        return f"{v:6.1f}" if v is not None else "   n/a"

    print(f"\n  {'stem':<12} {'fmt':>4} {'dur':>7}  {'lead_s':>7} {'lead_dB':>8} {'l_clk':>6}  "
          f"{'trail_s':>8} {'trail_dB':>9} {'t_clk':>6}  {'floor_dB':>9}")
    print(f"  {'-'*12} {'-'*4} {'-'*7}  {'-'*7} {'-'*8} {'-'*6}  {'-'*8} {'-'*9} {'-'*6}  {'-'*9}")
    for r in results:
        flag_l = " !" if r["lead_s"] < args.target * 0.5 else (" ^" if r["lead_s"] >= args.max_lead else "  ")
        flag_t = " !" if r["trail_s"] < args.target * 0.5 else (" ^" if r["trail_s"] >= args.max_trail else "  ")
        print(f"  {r['stem']:<12} {r['src_format']:>4} {r['duration']:>6.2f}s  "
              f"{r['lead_s']:>6.2f}s{flag_l}{fmt_floor(r['lead_floor'])}  {r['lead_clicks']:>5}  "
              f"{r['trail_s']:>7.2f}s{flag_t}{fmt_floor(r['trail_floor'])}  {r['trail_clicks']:>5}  "
              f"{fmt_floor(r['file_floor']):>9}")

    print(f"\n  {len(results)} file(s) shown (target: {args.target:.2f}s, "
          f"leading flagged long at {args.max_lead:.2f}s, trailing at {args.max_trail:.2f}s). "
          f"'!' = under half the target, '^' = at or above the long threshold "
          f"(mainly a lag concern on the leading edge -- trailing is mostly harmless).")
    if errors:
        print(f"  {len(errors)} file(s) failed to decode:")
        for e in errors[:10]:
            print(f"    {e['stem']}: {e['error']}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["stem", "src_format", "duration", "lead_s", "lead_floor_db", "lead_clicks",
                              "trail_s", "trail_floor_db", "trail_clicks", "file_floor_db"])
            for r in results:
                writer.writerow([r["stem"], r["src_format"], r["duration"], r["lead_s"], r["lead_floor"],
                                  r["lead_clicks"], r["trail_s"], r["trail_floor"], r["trail_clicks"],
                                  r["file_floor"]])
        print(f"  CSV written to {args.csv}")


if __name__ == "__main__":
    main()
