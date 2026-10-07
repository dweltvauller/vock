#!/usr/bin/env python3
"""
rhubarb_lip.py  --  build a Fallout 2 .lip from the audio with Rhubarb Lip Sync.

EXPERIMENTAL: under test, not part of the production pipeline. Output goes to
work/rhubarb and is never written to data/.

Usage:
    python3 tools/rhubarb_lip.py bgjes18               # one line, by audio tag
    python3 tools/rhubarb_lip.py bgjes18 bgjes19 ...   # several lines
    python3 tools/rhubarb_lip.py path/to/line.wav      # any 16-bit PCM WAV
    python3 tools/rhubarb_lip.py bgjes18 -r phonetic   # ignore the dialog text
    python3 tools/rhubarb_lip.py bgjes18 --floor -40   # stricter silence floor

The 'lip' step of vock.py turns MFA's TextGrid phones into mouth shapes, so
anything MFA cannot place (breaths, coughs, wheezes, a word it parks in the
wrong pause) gets no mouth movement or the wrong one. Rhubarb reads the mouth
shapes straight from the audio instead, so every sound the speaker makes moves
the mouth where it really happens.

Rhubarb (https://github.com/DanielSWolf/rhubarb-lip-sync) outputs 9 mouth
shapes. Each one is written as the ARPAbet phone that best matches it, looked
up in phonemes_english_us_arpa.py like an MFA phone, so it lands on the same
talking-head frame an MFA phone of that shape would:

    shape  mouth                        phone  LIP code  head frame
    A      closed (M, B, P)             M      0x20      6
    B      slightly open, teeth (K, S)  S      0x1B      2
    C      open (EH, AE)                EH     0x04      3
    D      wide open (AA)               AA     0x06      1
    E      slightly rounded (AO, ER)    UH     0x09      8
    F      puckered (UW, OW, W)         UW     0x0A      7
    G      teeth on lip (F, V)          F      0x17      4
    H      tongue up (L)                L      0x23      5
    X      rest                         SIL    0x00      0

Head frames are from _head_phoneme_lookup in fallout2-ce game_dialog.cc.

Dialog text: by default the line's .txt is passed to Rhubarb (-d) with the
sound tags such as (dry-cough) or *Cough* removed, and Rhubarb's English
recognizer (pocketSphinx) is used. With -r phonetic, or when no text is
left (no .txt, or only sound tags), Rhubarb's language-independent phonetic
recognizer is used instead.

Silence floor: Rhubarb's phonetic recognizer can move the mouth on room noise.
Any shape whose span is quieter than --floor dBFS RMS (default -45) is
replaced by rest. --floor off disables this.

Output goes to <project>/work/rhubarb/ (or --out): <stem>.lip plus
<stem>.tsv with Rhubarb's raw shapes, for checking. Nothing in data/ is
touched; copy a .lip over data/sound/speech/<folder>/<stem>.lip to try it
in game.

Needs the rhubarb binary on PATH (or --rhubarb). WAV input must be 16-bit
PCM; the vock 'wav' step already writes 22050 Hz mono 16-bit.

Configuration comes from vock.cfg, same as vock.py: project_root, layout,
PATHS["wav"], PATHS["txt"], PATHS["data_root"].
"""

import argparse
import array
import configparser
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/
sys.path.insert(0, str(_VOCK_DIR))
from vock import write_lip, load_phoneme_module  # noqa: E402

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

PATHS         = dict(_ini_parser["paths"])
LAYOUT        = _ini_parser.get("general", "layout", fallback="flat").strip().lower()
_PROJECT_ROOT = (_VOCK_DIR / _ini_parser.get("general", "project_root", fallback="./")).resolve()

# Rhubarb mouth shape -> ARPAbet phone (see the table in the docstring).
SHAPE_PHONE = {
    "A": "M",
    "B": "S",
    "C": "EH",
    "D": "AA",
    "E": "UH",
    "F": "UW",
    "G": "F",
    "H": "L",
    "X": "SIL",
}
PHONE_TABLE = load_phoneme_module("english_us_arpa").PHONEME_TABLE
SHAPE_CODE  = {shape: PHONE_TABLE[phone] for shape, phone in SHAPE_PHONE.items()}

# Non-speech tags in the .txt, e.g. (dry-cough), [laughs], *Cough*.
TAG_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*")


def project_dirs(project: Path) -> tuple[Path, Path, Path]:
    """(wav dir, txt dir or speech root, default output dir) for a project."""
    wk = "work" if LAYOUT == "data" else "."
    wav_dir = project / PATHS.get("wav", f"{wk}/wav")
    if LAYOUT == "data":
        txt_dir = project / PATHS.get("data_root", "./data") / "sound" / "speech"
    else:
        txt_dir = project / PATHS.get("txt", "./txt")
    return wav_dir.resolve(), txt_dir.resolve(), (project / wk / "rhubarb").resolve()


def find_txt(stem: str, txt_dir: Path) -> Path | None:
    """The line's dialog .txt: <dir>/<stem>.txt, or one folder down (data layout)."""
    direct = txt_dir / f"{stem}.txt"
    if direct.is_file():
        return direct
    hits = sorted(txt_dir.glob(f"*/{stem}.txt"))
    return hits[0] if hits else None


def run_rhubarb(rhubarb: str, wav: Path, dialog: str | None, recognizer: str) -> list:
    """Run Rhubarb on a WAV and return [(seconds, shape), ...]."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.tsv"
        cmd = [rhubarb, "-q", "-r", recognizer, "-f", "tsv", "-o", str(out)]
        if dialog:
            dlg = Path(tmp) / "dialog.txt"
            dlg.write_text(dialog, encoding="utf-8")
            cmd += ["-d", str(dlg)]
        r = subprocess.run(cmd + [str(wav)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"rhubarb failed on {wav.name}:\n{r.stderr.strip()}")
        cues = []
        for line in out.read_text().splitlines():
            if line.strip():
                t, shape = line.split()
                cues.append((float(t), shape))
    return cues


def read_wav(wav: Path) -> tuple[array.array, int, float]:
    """(mono 16-bit samples, sample rate, duration in seconds)."""
    with wave.open(str(wav), "rb") as w:
        if w.getsampwidth() != 2:
            raise RuntimeError(f"{wav.name}: need 16-bit PCM, got {8 * w.getsampwidth()}-bit")
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        samples = array.array("h", w.readframes(n))
    if sys.byteorder == "big":
        samples.byteswap()
    if ch > 1:
        samples = array.array("h", samples[::ch])
    return samples, rate, n / rate


def rms_dbfs(samples: array.array, rate: int, start: float, end: float) -> float:
    a, b = int(start * rate), max(int(end * rate), int(start * rate) + 1)
    chunk = samples[a:b]
    if not chunk:
        return -math.inf
    mean_sq = sum(s * s for s in chunk) / len(chunk)
    return 10 * math.log10(mean_sq / 32768.0 ** 2) if mean_sq else -math.inf


def build_events(cues: list, samples, rate: int, duration: float,
                 floor: float | None) -> tuple[list, int]:
    """[(seconds, LIP code), ...] from Rhubarb cues; also the count floored to rest."""
    events, floored = [], 0
    for i, (t, shape) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else duration
        if t >= duration:
            break
        if floor is not None and shape != "X" and rms_dbfs(samples, rate, t, end) < floor:
            shape = "X"
            floored += 1
        code = SHAPE_CODE[shape]
        if not events or events[-1][1] != code:
            events.append((t, code))
    if not events or events[0][0] > 0:
        events.insert(0, (0.0, SHAPE_CODE["X"]))
    return events, floored


def main() -> None:
    ap = argparse.ArgumentParser(description="[EXPERIMENTAL] Build Fallout 2 .lip files with Rhubarb Lip Sync.")
    ap.add_argument("lines", nargs="+", help="audio tags (e.g. bgjes18) or WAV paths")
    ap.add_argument("-r", "--recognizer", choices=["pocketSphinx", "phonetic"],
                    help="Rhubarb recognizer (default: pocketSphinx with the .txt, "
                         "phonetic when there is none)")
    ap.add_argument("--floor", default="-45",
                    help="dBFS RMS below which a shape becomes rest, or 'off' (default -45)")
    ap.add_argument("--out", help="output folder (default <project>/work/rhubarb)")
    ap.add_argument("--project", help=f"project root (default from vock.cfg: {_PROJECT_ROOT})")
    ap.add_argument("--rhubarb", default="rhubarb", help="rhubarb binary (default: on PATH)")
    args = ap.parse_args()
    print("[EXPERIMENTAL] rhubarb_lip.py is under test; output is not used by the pipeline.")

    rhubarb = shutil.which(args.rhubarb) or (args.rhubarb if os.path.isfile(args.rhubarb) else None)
    if not rhubarb:
        sys.exit(f"[ERROR] rhubarb not found: {args.rhubarb} (put it on PATH or pass --rhubarb)")
    floor = None if args.floor.lower() == "off" else float(args.floor)

    project = Path(args.project).resolve() if args.project else _PROJECT_ROOT
    wav_dir, txt_dir, out_default = project_dirs(project)
    out_dir = Path(args.out).resolve() if args.out else out_default
    out_dir.mkdir(parents=True, exist_ok=True)

    failed = 0
    for line in args.lines:
        if line.lower().endswith(".wav"):
            wav, stem = Path(line).resolve(), Path(line).stem.lower()
        else:
            stem = line.lower()
            wav = wav_dir / f"{stem}.wav"
        if not wav.is_file():
            print(f"[SKIP] {stem}: no WAV at {wav}")
            failed += 1
            continue

        txt = find_txt(stem, txt_dir)
        dialog = None
        if txt and args.recognizer != "phonetic":
            dialog = " ".join(TAG_RE.sub(" ", txt.read_text(encoding="cp1252")).split()) or None
        recognizer = args.recognizer or ("pocketSphinx" if dialog else "phonetic")

        try:
            cues = run_rhubarb(rhubarb, wav, dialog, recognizer)
            samples, rate, duration = read_wav(wav)
        except RuntimeError as e:
            print(f"[FAIL] {stem}: {e}")
            failed += 1
            continue

        events, floored = build_events(cues, samples, rate, duration, floor)
        lip = out_dir / f"{stem}.lip"
        write_lip(str(lip), stem, duration, events)
        (out_dir / f"{stem}.tsv").write_text("".join(f"{t:.2f}\t{s}\n" for t, s in cues))
        moving = sum(1 for _t, c in events if c != SHAPE_CODE["X"])
        print(f"[OK]   {stem}: {duration:.2f}s, {recognizer}"
              f"{' + text' if dialog else ''}, {len(events)} events "
              f"({moving} mouth, {floored} floored to rest) -> {lip}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
