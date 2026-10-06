#!/usr/bin/env python3
"""
lip_preview.py  --  render a talking head's lip-sync to an MP4, without the game.

Usage:
    python3 tools/lip_preview.py bgjes18                       # the line's shipped .lip
    python3 tools/lip_preview.py bgjes18 work/rhubarb/bgjes18.lip
                                       # shipped and Rhubarb side by side
    python3 tools/lip_preview.py a.lip b.lip --wav line.wav --head bgjes
    python3 tools/lip_preview.py bgjes18 --mood bad            # bad-mood frames

Each argument is a .lip path or an audio tag (tag = the .lip in
data/sound/speech/<folder>/). Several make one panel each, side by side and
labelled, all over the same audio, so two versions of a line can be compared
in one play-through.

The head is drawn the way fallout2-ce does it (game_dialog.cc): each LIP
phoneme picks a frame of <head><g|n|b>p.frm through _head_phoneme_lookup, the
frame is held until the next marker, and it sits bottom-aligned in the centre
of the 388x200 dialog window. Marker times are LIP offsets / 44100 s
(2 x 22050, see write_lip in vock.py). Under each panel: the frame slot in use.

The WAV defaults to <project>/work/wav/<stem>.wav (or ./wav for flat layout),
the head to the stem without its trailing digits (bgjes18 -> bgjes), and the
output to <project>/work/preview/<stem>.mp4.

Head FRMs are looked up in <project>/data/art/heads (or ./art/heads), then in
each --art folder in order; the palette is --pal, else color.pal in a heads
folder's data root, else ../dat/master/color.pal (extracted master.dat).
Needs Pillow and ffmpeg.

Configuration comes from vock.cfg, same as vock.py: project_root, layout,
PATHS["wav"], PATHS["lip"], PATHS["art"], PATHS["data_root"].
"""

import argparse
import configparser
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

PATHS         = dict(_ini_parser["paths"])
LAYOUT        = _ini_parser.get("general", "layout", fallback="flat").strip().lower()
_PROJECT_ROOT = (_VOCK_DIR / _ini_parser.get("general", "project_root", fallback="./")).resolve()

# fallout2-ce game_dialog.cc _head_phoneme_lookup: LIP phoneme -> head frame.
HEAD_PHONEME_LOOKUP = [
    0, 3, 1, 1, 3, 1, 1, 1, 7, 8, 7, 3, 1, 8, 1, 7, 7, 6, 6, 2, 2,
    2, 2, 4, 4, 5, 5, 2, 2, 2, 2, 2, 6, 2, 2, 5, 8, 2, 2, 2, 2, 8,
]
LIP_RATE   = 44100              # LIP offsets per second (2 x 22050)
WIN_W, WIN_H = 388, 200         # talking-head window
BAR_H      = 16                 # label / slot strip under each panel (unscaled px)
MOODS      = {"good": "gp", "neutral": "np", "bad": "bp"}


def read_lip(path: Path) -> list:
    """[(seconds, head frame), ...] from a v2 .lip file."""
    d = path.read_bytes()
    version, = struct.unpack(">I", d[0:4])
    if version != 2:
        raise RuntimeError(f"{path}: LIP version {version}, only 2 is supported")
    n_ph, = struct.unpack(">I", d[0x14:0x18])
    n_mk, = struct.unpack(">I", d[0x1C:0x20])
    phonemes = d[0x2C:0x2C + n_ph]
    base = 0x2C + n_ph
    cues = []
    for i in range(min(n_ph, n_mk)):
        _kind, pos = struct.unpack(">II", d[base + 8 * i:base + 8 * i + 8])
        ph = phonemes[i]
        cues.append((pos / LIP_RATE, HEAD_PHONEME_LOOKUP[ph] if ph < len(HEAD_PHONEME_LOOKUP) else 0))
    return cues


def read_frm(path: Path) -> list:
    """[(width, height, pixel bytes), ...] for direction 0 of an FRM."""
    d = path.read_bytes()
    n, = struct.unpack(">H", d[8:10])
    off, frames = 62, []
    for _ in range(n):
        w, h, size = struct.unpack(">HHI", d[off:off + 8])
        frames.append((w, h, d[off + 12:off + 12 + size]))
        off += 12 + size
    return frames


def find_file(name: str, dirs: list) -> Path | None:
    """First file called name (any case) in dirs."""
    for d in dirs:
        if d.is_dir():
            for p in d.iterdir():
                if p.name.lower() == name.lower():
                    return p
    return None


def head_images(frm: Path, palette: list, scale: int) -> list:
    """One RGB image per FRM frame, placed in the dialog window like the engine does."""
    images = []
    for w, h, px in read_frm(frm):
        im = Image.frombytes("P", (w, h), px)
        im.putpalette(palette)
        win = Image.new("RGB", (WIN_W, WIN_H))
        win.paste(im.convert("RGB"), ((WIN_W - w) // 2, WIN_H - h))
        images.append(win.resize((WIN_W * scale, WIN_H * scale), Image.NEAREST))
    return images


def slot_at(cues: list, t: float) -> int:
    """Head frame showing at time t: the last cue at or before t."""
    slot = cues[0][1] if cues else 0
    for ct, s in cues:
        if ct > t:
            break
        slot = s
    return slot


def main() -> None:
    ap = argparse.ArgumentParser(description="Render talking-head lip-sync to an MP4.")
    ap.add_argument("lips", nargs="+", help=".lip paths or audio tags (one panel each)")
    ap.add_argument("--wav", help="audio (default <project>/work/wav/<stem>.wav)")
    ap.add_argument("--head", help="head FRM prefix (default: stem without digits)")
    ap.add_argument("--mood", choices=list(MOODS), default="neutral", help="default neutral")
    ap.add_argument("--labels", nargs="+", help="panel labels (default: each .lip's folder)")
    ap.add_argument("--out", help="MP4 path (default <project>/work/preview/<stem>.mp4)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=int, default=2, help="pixel scale (default 2)")
    ap.add_argument("--art", action="append", default=[], help="extra heads folder (repeatable)")
    ap.add_argument("--pal", help="color.pal (default: found next to the art folders)")
    ap.add_argument("--project", help=f"project root (default from vock.cfg: {_PROJECT_ROOT})")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("[ERROR] ffmpeg not found on PATH")
    project = Path(args.project).resolve() if args.project else _PROJECT_ROOT
    wk = "work" if LAYOUT == "data" else "."
    data_root = project / PATHS.get("data_root", "./data")

    lips = []
    for a in args.lips:
        p = Path(a)
        if p.suffix.lower() != ".lip":
            stem = a.lower()
            folder = re.sub(r"\d+$", "", stem)
            if LAYOUT == "data":
                p = data_root / "sound" / "speech" / folder / f"{stem}.lip"
            else:
                p = project / PATHS.get("lip", "./lip") / f"{stem}.lip"
        if not p.is_file():
            sys.exit(f"[ERROR] no .lip at {p}")
        lips.append(p.resolve())

    stem = lips[0].stem.lower()
    head = (args.head or re.sub(r"\d+$", "", stem)).lower()
    wav = Path(args.wav) if args.wav else project / PATHS.get("wav", f"{wk}/wav") / f"{stem}.wav"
    if not wav.is_file():
        sys.exit(f"[ERROR] no WAV at {wav} (pass --wav)")

    art_dirs = [data_root / "art" / "heads" if LAYOUT == "data"
                else project / PATHS.get("art", "./art") / "heads"]
    art_dirs += [Path(d) for d in args.art]
    frm_name = f"{head}{MOODS[args.mood]}.frm"
    frm = find_file(frm_name, art_dirs)
    if not frm:
        sys.exit(f"[ERROR] {frm_name} not found in: {', '.join(map(str, art_dirs))} (add --art)")
    pal_path = Path(args.pal) if args.pal else None
    if not pal_path:
        for d in art_dirs:
            hit = find_file("color.pal", [d.parent.parent])   # <data root>/art/heads
            if hit:
                pal_path = hit
                break
    if not pal_path and (_VOCK_DIR.parent / "dat" / "master" / "color.pal").is_file():
        pal_path = _VOCK_DIR.parent / "dat" / "master" / "color.pal"   # extracted master.dat
    if not pal_path or not pal_path.is_file():
        sys.exit("[ERROR] color.pal not found next to the art folders (pass --pal)")
    palette = [min(255, c * 4) for c in pal_path.read_bytes()[:768]]

    labels = args.labels or [p.parent.name for p in lips]
    cues = [read_lip(p) for p in lips]
    heads = head_images(frm, palette, args.scale)
    s = args.scale
    panel_w, panel_h = WIN_W * s, (WIN_H + BAR_H) * s
    width = panel_w * len(lips)
    width += width % 2                                   # yuv420p needs even sizes
    height = panel_h + panel_h % 2

    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, check=True).stdout.strip())

    out = Path(args.out) if args.out else project / wk / "preview" / f"{stem}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(args.fps),
         "-i", "-", "-i", str(wav),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)],
        stdin=subprocess.PIPE)

    try:
        font = ImageFont.load_default(size=10 * s)
    except TypeError:                                    # Pillow < 10.1
        font = ImageFont.load_default()
    cache = {}
    for i in range(int(duration * args.fps) + 1):
        t = i / args.fps
        slots = tuple(slot_at(c, t) for c in cues)
        if slots not in cache:
            img = Image.new("RGB", (width, height), (24, 24, 24))
            draw = ImageDraw.Draw(img)
            for k, slot in enumerate(slots):
                x = k * panel_w
                if slot < len(heads):
                    img.paste(heads[slot], (x, 0))
                draw.text((x + 4 * s, WIN_H * s + 2 * s),
                          f"{labels[k] if k < len(labels) else ''}   frame {slot}",
                          fill=(62, 255, 0), font=font)
            cache[slots] = img.tobytes()
        ff.stdin.write(cache[slots])
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit("[ERROR] ffmpeg failed")
    print(f"[OK]   {stem}: {len(lips)} panel(s), {frm.name}, {duration:.2f}s -> {out}")


if __name__ == "__main__":
    main()
