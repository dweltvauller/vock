#!/usr/bin/env python3
"""
float_scan.py  --  cross-check float_filter.cfg against how scripts use each line.

Usage:
    python3 tools/float_scan.py                # scan every tagged dialog MSG
    python3 tools/float_scan.py andr west      # only these tag prefixes
    python3 tools/float_scan.py --all          # also list dual-use TH lines

A tag in float_filter.cfg is ACM-only: vock.py gives it no TextGrid and no
LIP. That is right for a float (float_msg / floater*), which plays without
lip-sync. But if the same MSG line is also a dialogue reply (Reply /
NMessage / gSay_*) under a talking head, the engine takes the lip-sync
path, finds no .lip, and plays nothing at all.

For each tagged line in data/text/<lang>/dialog/<script>.msg this reads
scripts_src/**/<script>.ssl and reports:

  ERROR  float-range tag used as a dialogue reply  -> silent in the TH window
  INFO   float-only tag missing from float_filter.cfg  -> works, but not in
         the opt-out floats DAT
  (--all) dual-use tag outside float_filter.cfg  -> correct, listed for review

Exit code is 1 when any ERROR is found, so this can gate a release.

Limits: only literal msg ids, the script's own #define constants and
random(a,b) / floater_rand(a,b) ranges are resolved, and only against the
script's own MSG. Lines pulled from another script's MSG
(message_str(SCRIPT_X, n)) or computed ids are not seen. The scan does not
know whether a call site is live (e.g. dead code under "if (0)"), so check
each hit in the script before changing the filter.

Configuration comes from vock.cfg, same as vock.py: project_root,
PATHS["float_filter"], PATHS["combat_filter"], PATHS["data_root"].
"""

import argparse
import configparser
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/
sys.path.insert(0, str(_VOCK_DIR))
from vock import load_ranges, in_ranges        # noqa: E402

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

PATHS         = dict(_ini_parser["paths"])
_PROJECT_ROOT = (_VOCK_DIR / _ini_parser.get("general", "project_root", fallback="./")).resolve()
_DATA_ROOT    = _PROJECT_ROOT / PATHS.get("data_root", "./data")

# Calls whose msg id plays as lip-synced speech when a dialogue window is open.
DIALOGUE_CALLS = ["Reply", "NMessage", "gSay_Reply", "gSay_Message"]
# Calls that put the line up as a float (see command.h / newreno.h macros).
FLOAT_CALLS = [
    "floater", "floater_rand", "floater_rand_with_check", "floater_type", "float_msg",
    "floater_bad", "floater_bad_rand", "floater_good", "floater_good_rand",
    "floater_sick", "floater_sick_rand", "floater_afraid", "floater_afraid_rand",
    "floater_high", "floater_high_rand",
]


def read_msg_tags(path: Path) -> dict[int, str]:
    """{msg id: audio tag} for every tagged line in a MSG file."""
    tags = {}
    with open(path, encoding="cp1252", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\{(\d+)\}\{([^}]*)\}", line)
            if m and m.group(2).strip():
                tags[int(m.group(1))] = m.group(2).strip()
    return tags


def strip_comments(src: str) -> str:
    """Drop /* */ and // comments, keeping line numbers intact."""
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def iter_calls(src: str, names: list[str]):
    """Yield (name, argument text, line number) for each call to one of *names*."""
    for m in re.finditer(r"\b(" + "|".join(names) + r")\s*\(", src):
        i = j = m.end()
        depth = 1
        while j < len(src) and depth:
            depth += {"(": 1, ")": -1}.get(src[j], 0)
            j += 1
        yield m.group(1), src[i:j - 1], src.count("\n", 0, m.start()) + 1


def msg_ids(arg: str, consts: dict[str, str], bare: bool = True) -> set[int]:
    """Msg ids referenced by a call argument: random(a,b) ranges, mstr(n) /
    message_str(NAME, n), and (when *bare*) the argument itself as a number."""
    def num(x):
        x = consts.get(x, x)
        return int(x) if str(x).isdigit() else None

    out = set()
    for a, b in re.findall(r"random\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)", arg):
        lo, hi = num(a), num(b)
        if lo is not None and hi is not None:
            out |= set(range(lo, hi + 1))
    for x in re.findall(r"(?:mstr|message_str\s*\(\s*NAME\s*,)\s*\(?\s*(\w+)", arg):
        if num(x) is not None:
            out.add(num(x))
    if bare and num(arg.strip()) is not None:
        out.add(num(arg.strip()))
    return out


def scan_script(src: str) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """({msg id: dialogue call lines}, {msg id: float call lines}) for one script."""
    src = strip_comments(src)
    consts = dict(re.findall(r"#define\s+(\w+)\s+\(?\s*(\d+)\s*\)?\s*$", src, flags=re.M))
    dialogue, floats = {}, {}
    for fn, arg, ln in iter_calls(src, DIALOGUE_CALLS):
        if fn.startswith("gSay_"):                 # gSay_Reply(NAME, x[, reaction])
            arg = arg.split(",", 1)[1] if "," in arg else arg
            if fn == "gSay_Message":
                arg = arg.rsplit(",", 1)[0]
        for i in msg_ids(arg, consts):
            dialogue.setdefault(i, []).append(ln)
    for fn, arg, ln in iter_calls(src, FLOAT_CALLS):
        if fn == "floater_rand_with_check":
            arg = "random(%s)" % ",".join(arg.split(",")[:2])
        elif fn.endswith("_rand"):
            arg = "random(%s)" % arg
        # float_msg / floater_type take a string, so only mstr(n) counts there
        bare = fn not in ("float_msg", "floater_type")
        for i in msg_ids(arg, consts, bare=bare):
            floats.setdefault(i, []).append(ln)
    return dialogue, floats


def main():
    ap = argparse.ArgumentParser(description="Cross-check float_filter.cfg against script usage.")
    ap.add_argument("prefixes", nargs="*", help="only report tags starting with these prefixes")
    ap.add_argument("--all", action="store_true", help="also list dual-use lines outside float_filter.cfg")
    ap.add_argument("--language", default="english", help="text/<language>/dialog folder (default: english)")
    args = ap.parse_args()

    msg_dir = _DATA_ROOT / "text" / args.language / "dialog"
    ssl_dir = _PROJECT_ROOT / "scripts_src"
    if not msg_dir.is_dir() or not ssl_dir.is_dir():
        sys.exit(f"[ERROR] needs layout=data: {msg_dir} and {ssl_dir}")

    float_map  = load_ranges(str(_PROJECT_ROOT / PATHS.get("float_filter", "./float_filter.cfg")))
    combat_map = load_ranges(str(_PROJECT_ROOT / PATHS.get("combat_filter", "./combat_filter.cfg")))
    ssl_paths  = {p.stem.lower(): p for p in ssl_dir.rglob("*.ssl")}
    want       = tuple(p.lower() for p in args.prefixes)

    errors, missing, dual, no_script = [], [], [], []
    for msg_path in sorted(msg_dir.glob("*.msg")):
        tags = read_msg_tags(msg_path)
        if want:
            tags = {i: t for i, t in tags.items() if t.lower().startswith(want)}
        if not tags:
            continue
        name = msg_path.stem.lower()
        if name not in ssl_paths:
            no_script.append(msg_path.name)
            continue
        dialogue, floats = scan_script(ssl_paths[name].read_text(encoding="cp1252", errors="replace"))
        rel = ssl_paths[name].relative_to(_PROJECT_ROOT)
        for i, tag in sorted(tags.items()):
            is_float = in_ranges(tag, float_map)
            if in_ranges(tag, combat_map):
                continue
            row = (f"{msg_path.name} {{{i}}} {tag}", rel, dialogue.get(i, []), floats.get(i, []))
            if is_float and i in dialogue:
                errors.append(row)
            elif not is_float and i in floats:
                (dual if i in dialogue else missing).append(row)

    def show(label, rows, blurb):
        print(f"\n{label} ({len(rows)}): {blurb}")
        for where, rel, d, f in rows:
            print(f"  {where:<34} {rel}  reply lines {d or '-'}  float lines {f or '-'}")

    show("ERROR", errors, "float-range tag used as a dialogue reply -> silent under a talking head")
    show("INFO", missing, "float-only tag not in float_filter.cfg -> not in the opt-out floats DAT")
    if args.all:
        show("OK", dual, "dual-use tag outside float_filter.cfg -> has a LIP, works both ways")
    if no_script:
        print(f"\nskipped, no matching .ssl: {', '.join(no_script)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
