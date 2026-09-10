#!/usr/bin/env python3
"""
msg_localize.py -- VOCK language tag propagator

Reads audio tags from the source-language MSG files (set by language in
vock.cfg) and injects them into matching foreign-language MSG files pulled
from the RPU repo. Output is sparse -- only MSGs that actually receive a tag
are written.

  layout = data   (vock.cfg)
      Tagged foreign MSGs are written straight into the data/ tree at
      data/text/<lang>/<subdir>/<file>.msg. vock.py's 'dat' step packs them
      from data/** verbatim -- this tool no longer builds a DAT.

  layout = flat
      Tagged foreign MSGs are written to loc/tagged/<lang>/<subdir>/ and this
      tool rebuilds vock.dat with them merged in (there is no other path into
      the DAT for foreign text in the flat layout).

Usage:
    python3 msg_localize.py
    python3 msg_localize.py --rpu-text /path/to/RPU/data/text
    python3 msg_localize.py --dry-run
    python3 msg_localize.py --no-dat            # flat layout only
    python3 msg_localize.py --langs german french spanish

The RPU text folder defaults to PATHS["rpu_text"] in vock.cfg, resolved
against this vock.cfg's own folder (not project_root -- the RPU repo is a
sibling of vock/ itself). Override per-run with --rpu-text.
"""

import argparse
import configparser
import os
import re
import struct
import sys
import zlib
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

_config = {
    "language":     _ini_parser.get("general", "language"),
    "project_root": _ini_parser.get("general", "project_root", fallback="./"),
    "layout":       _ini_parser.get("general", "layout", fallback="flat").strip().lower(),
    "paths":        dict(_ini_parser["paths"]),
}
SOURCE_LANG  = _config["language"]
PATHS        = _config["paths"]
DATA_LAYOUT  = _config["layout"] == "data"

# Every paths entry is resolved against config["project_root"] (default "./"),
# mirroring vock.py's resolve_path() -- so pointing project_root at another
# project's folder retargets this tool too, instead of always reading from vock/.
_PROJECT_ROOT   = (_VOCK_DIR / _config.get("project_root", "./")).resolve()
# rpu_text is resolved against _VOCK_DIR, not project_root -- see vock.cfg.
RPU_TEXT_DIR    = (_VOCK_DIR / PATHS["rpu_text"]).resolve()
ENCODING        = "cp1252"

ALL_LANGS = [
    "english",
    "german", "french", "spanish", "italian",
    "polish", "russian", "czech", "hungarian",
]
_SOURCE_ALIASES = {"arpabet": "english"}
_source = _SOURCE_ALIASES.get(SOURCE_LANG, SOURCE_LANG)
DEFAULT_LANGS = [l for l in ALL_LANGS if l != _source]

if DATA_LAYOUT:
    # Source english MSGs and tagged foreign MSGs both live in the data/ tree.
    _DATA_ROOT      = _PROJECT_ROOT / PATHS.get("data_root", "./data")
    SOURCE_MSG_DIR  = _DATA_ROOT / "text" / _source / "dialog"
    TAGGED_OUT_DIR  = _DATA_ROOT / "text"          # out_dir / <lang> / <subdir> / <file>
    DAT_SRC_DIR     = _PROJECT_ROOT / "dat"        # unused (no DAT rebuild in data layout)
    DAT_FILES       = []
    DAT_OUT_DIR     = _PROJECT_ROOT / "dat"
else:
    SOURCE_MSG_DIR  = _PROJECT_ROOT / PATHS["msg"]
    _LOC_DIR        = _PROJECT_ROOT / PATHS["loc"]
    TAGGED_OUT_DIR  = _LOC_DIR / "tagged"
    DAT_SRC_DIR     = (_PROJECT_ROOT / PATHS["dat"]).parent
    DAT_FILES       = [Path(PATHS["dat"]).name]
    DAT_OUT_DIR     = _LOC_DIR

LANG_ENCODING = {
    "russian": "cp1251", "polish": "cp1250",
    "czech": "cp1250",   "hungarian": "cp1250",
}

MSG_LINE_RE = re.compile(r'^\{(\d+)\}\{([^}]*)\}\{(.*)\}\s*$')


def parse_msg(path, encoding):
    lines = []
    with open(path, encoding=encoding, errors="replace") as f:
        for raw in f:
            m = MSG_LINE_RE.match(raw.rstrip("\r\n"))
            if m:
                lines.append((int(m.group(1)), m.group(2), m.group(3)))
    return lines


def build_tag_map(eng_lines):
    return {num: tag for num, tag, _ in eng_lines if tag.strip()}


def inject_tags(foreign_path, tag_map, encoding, dry_run=False, out_path=None):
    with open(foreign_path, encoding=encoding, errors="replace", newline="") as f:
        raw_lines = f.readlines()

    out_lines = []
    injected = skipped = unchanged = 0
    foreign_line_nums = set()

    for raw in raw_lines:
        m = MSG_LINE_RE.match(raw.rstrip("\r\n"))
        if not m:
            out_lines.append(raw)
            continue
        num  = int(m.group(1))
        tag  = m.group(2)
        text = m.group(3)
        foreign_line_nums.add(num)
        if num in tag_map:
            new_tag = tag_map[num]
            if tag.strip():
                if tag.strip() == new_tag:
                    unchanged += 1
                    out_lines.append(raw)
                else:
                    print(f"  [CONFLICT] line {num}: existing '{tag}' vs English '{new_tag}' -- kept existing")
                    skipped += 1
                    out_lines.append(raw)
            else:
                injected += 1
                out_lines.append(f"{{{num}}}{{{new_tag}}}{{{text}}}\r\n")
        else:
            out_lines.append(raw)

    # Sparse output: only write a foreign MSG once it actually carries a tag —
    # either injected now, or already present from a previous run (unchanged).
    # A file with no matching tag line at all is left untouched / not created.
    if not dry_run and (injected or unchanged):
        dest = out_path or foreign_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding=encoding, errors="replace", newline="") as f:
            f.writelines(out_lines)

    missing = sorted(n for n in tag_map if n not in foreign_line_nums)
    return injected, skipped, unchanged, missing


def read_dat(path):
    with open(path, "rb") as f:
        data = f.read()
    total_size   = len(data)
    tree_size    = struct.unpack_from("<I", data, total_size - 8)[0]
    dat_size_chk = struct.unpack_from("<I", data, total_size - 4)[0]
    if dat_size_chk != total_size:
        print(f"  [WARN] DAT size mismatch ({dat_size_chk} vs {total_size})")
    tree_start = total_size - 8 - tree_size
    pos = tree_start
    file_count = struct.unpack_from("<I", data, pos)[0]; pos += 4
    files = []
    for _ in range(file_count):
        name_len  = struct.unpack_from("<I", data, pos)[0]; pos += 4
        name      = data[pos:pos+name_len].decode("cp1252", errors="replace"); pos += name_len
        flags     = struct.unpack_from("<B", data, pos)[0]; pos += 1
        real_sz   = struct.unpack_from("<I", data, pos)[0]; pos += 4
        packed_sz = struct.unpack_from("<I", data, pos)[0]; pos += 4
        file_off  = struct.unpack_from("<I", data, pos)[0]; pos += 4
        raw = data[file_off:file_off + packed_sz]
        files.append((name, zlib.decompress(raw) if flags & 0x01 else raw))
    return files


def write_dat(out_path, entries):
    entries = sorted(entries, key=lambda e: e[0].lower())
    file_data = bytearray()
    dir_tree  = bytearray()
    offsets   = []
    for _, content in entries:
        offsets.append(len(file_data))
        file_data += content
    dir_tree += struct.pack("<I", len(entries))
    for (name, content), offset in zip(entries, offsets):
        enc = name.encode("cp1252")
        dir_tree += struct.pack("<I", len(enc)) + enc
        dir_tree += struct.pack("<B", 0)
        dir_tree += struct.pack("<I", len(content))
        dir_tree += struct.pack("<I", len(content))
        dir_tree += struct.pack("<I", offset)
    total  = len(file_data) + len(dir_tree) + 8
    footer = struct.pack("<II", len(dir_tree), total)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(file_data); f.write(dir_tree); f.write(footer)
    print(f"  Written {len(entries)} files -> {out_path}  ({out_path.stat().st_size:,} bytes)")


def main():
    ap = argparse.ArgumentParser(description="VOCK language tag propagator")
    ap.add_argument("--msgdir",   default=str(SOURCE_MSG_DIR), help="Source-language MSG folder (default: from vock.cfg)")
    ap.add_argument("--rpu-text", default=str(RPU_TEXT_DIR),    help="RPU data/text folder")
    ap.add_argument("--tagged",   default=str(TAGGED_OUT_DIR),  help="Output folder for injected foreign MSGs")
    ap.add_argument("--dat-src",   default=str(DAT_SRC_DIR),     help="Source DAT folder (flat layout only)")
    ap.add_argument("--dat-out",   default=str(DAT_OUT_DIR),     help="Output folder for rebuilt DATs (flat layout only)")
    ap.add_argument("--dat-files", nargs="+", default=DAT_FILES, help="DAT filenames to rebuild (flat layout only)")
    ap.add_argument("--langs",    nargs="+", default=DEFAULT_LANGS)
    ap.add_argument("--encoding", default=ENCODING)
    ap.add_argument("--dry-run",  action="store_true")
    ap.add_argument("--no-dat",   action="store_true", help="flat layout only; the data layout never builds a DAT")
    args = ap.parse_args()

    eng_dir = Path(args.msgdir)
    rpu_dir = Path(args.rpu_text)
    out_dir = Path(args.tagged)
    dat_src = Path(args.dat_src)
    dat_out = Path(args.dat_out)

    if not eng_dir.exists(): ap.error(f"Source MSG dir not found: {eng_dir}")
    if not rpu_dir.exists(): ap.error(f"RPU text dir not found: {rpu_dir}")

    eng_msgs = list(eng_dir.glob("*.msg")) + list(eng_dir.glob("*.MSG"))
    if not eng_msgs: ap.error(f"No .msg files found in {eng_dir}")
    print(f"\nFound {len(eng_msgs)} {SOURCE_LANG} MSG file(s) in {eng_dir}")

    tagged_files = []

    for lang in args.langs:
        enc = LANG_ENCODING.get(lang, args.encoding)
        lang_found = False
        lang_total = 0

        for subdir in ("dialog", "dialog_female"):
            lang_dir = rpu_dir / lang / subdir
            if not lang_dir.exists(): continue
            if not lang_found:
                print(f"\n[{lang}]  encoding={enc}")
                lang_found = True
            print(f"  [{subdir}]")

            for eng_path in sorted(eng_msgs):
                stem = eng_path.stem.lower()
                matches = [p for p in lang_dir.iterdir()
                           if p.suffix.lower() == ".msg" and p.stem.lower() == stem]
                if not matches: continue
                foreign_path = matches[0]
                eng_lines = parse_msg(eng_path, ENCODING)
                tag_map   = build_tag_map(eng_lines)
                if not tag_map: continue
                out_path = out_dir / lang / subdir / foreign_path.name
                injected, skipped, unchanged, _ = inject_tags(
                    foreign_path, tag_map, enc,
                    dry_run=args.dry_run, out_path=out_path)
                lang_total += injected
                status = "[DRY RUN] " if args.dry_run else ""
                print(f"    {status}{foreign_path.name}: +{injected} tags"
                      + (f", {skipped} conflict(s)" if skipped else "")
                      + (f", {unchanged} already set" if unchanged else ""))
                # Only files that actually carry a tag are written (see inject_tags).
                if not args.dry_run and (injected or unchanged):
                    internal = f"text\\{lang}\\{subdir}\\{foreign_path.stem.upper()}.MSG"
                    tagged_files.append((internal, out_path))

        if not lang_found:
            print(f"\n[{lang}] skipped -- no dialog folder found")
        elif lang_found:
            print(f"  -> {lang_total} tag(s) injected total")

    if args.dry_run:
        print("\nDry run complete -- no files written.")
        return
    if not tagged_files:
        print("\nNo foreign MSGs were tagged.")
        return

    if DATA_LAYOUT:
        print(f"\n{len(tagged_files)} tagged MSG(s) written under {out_dir}/")
        print("Layout = data: vock.py's 'dat' step packs these from data/** — "
              "no DAT rebuild here.")
        return

    if args.no_dat:
        print(f"\nSkipping DAT rebuild (--no-dat). Tagged files are in {out_dir}/")
        return
    if not dat_src.exists():
        print(f"\n[WARN] DAT source dir not found: {dat_src} -- skipping DAT rebuild")
        return

    dat_files = sorted(p for p in dat_src.glob("*.dat") if p.name.lower() in [f.lower() for f in args.dat_files])
    if not dat_files:
        print(f"\n[WARN] No .dat files in {dat_src}")
        return

    dat_out.mkdir(parents=True, exist_ok=True)
    print(f"\nRebuilding {len(dat_files)} DAT file(s) from {dat_src}/ -> {dat_out}/...")
    for dat_path in dat_files:
        print(f"\n  [{dat_path.name}]")
        existing = read_dat(dat_path)
        print(f"    Read {len(existing)} existing entries")
        entries = {k.upper(): v for k, v in existing}
        added = replaced = 0
        for internal, local_path in tagged_files:
            content = local_path.read_bytes()
            key = internal.upper()
            if key in entries: replaced += 1
            else: added += 1
            entries[key] = content
        print(f"    +{added} new entries, {replaced} replaced")
        path_map = {k.upper(): k for k, _ in existing}
        for internal, _ in tagged_files:
            path_map[internal.upper()] = internal
        write_dat(dat_out / dat_path.name, [(path_map[k], v) for k, v in entries.items()])

    print("\nDone.")


if __name__ == "__main__":
    main()
