#!/usr/bin/env python3
r"""
vock.py  ─  V.O.C.K.  Vocal Output Creation Kit
           Complete Fallout 2 voice modding pipeline.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  msg ────────[parse CP1252]────────────────► txt (one per dialog line)
                                              ↕ optional: edit manually here
  audio ──────[ffmpeg normalize + encode]───► wav  (22050 Hz mono 16-bit)
  wav ────────[snd2acm / wine]──────────────► acm
  wav + txt ──[MFA]─────────────────────────► textgrid
  textgrid ─────────────────────────────────► lip
  msg + acm + lip + txt + int + art ────────► dat/<mod>.dat

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLDER STRUCTURE (all created automatically)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ./msg/          ← put your .MSG file(s) here
  ./audio/        ← put your audio files here (MP3, WAV, FLAC, M4A, …)
  ./txt/          ← generated/editable: one .txt per audio line
  ./wav/          ← generated: 22050 Hz mono 16-bit PCM (ready for ACM/MFA)
  ./acm/          ← generated: Fallout 2 ACM files
  ./textgrid/     ← generated: MFA TextGrid files
  ./lip/          ← generated: Fallout 2 LIP files
  ./scripts/      ← put pre-compiled Fallout 2 .INT script files here (packed into dat as scripts\*)
  ./art/          ← put art assets here, e.g. art/heads/*.FRM (packed into dat as art\*)
  ./unknown.txt   ← generated: words not recognized by the dictionary
  ./dat/<mod>.dat ← generated: ready-to-install Fallout 2 DAT archive
                    (<mod> = project folder name; + -floats/-combat/-pipboy overlays)

  The above is the "flat" layout. With `layout = data` in vock.cfg the project
  is instead an RPU-shaped, sparse data/ tree: source MSGs are read from
  data/text/<lang>/**/*.msg, generated speech (acm/lip/txt) is written into
  data/sound/speech/<folder>/, and the DAT is packed from data/** verbatim.
  wav/ and textgrid/ stay top-level as rebuild metadata. Floats
  (float_filter.cfg) and per-NPC combat barks (combat_filter.cfg) are ACM-only
  and go to <mod>-floats.dat / <mod>-combat.dat; MSGs listed in [acm_only]
  (e.g. pipboy → holodisk narration) are ACM-only too and go to <mod>-pipboy.dat.
  All three overlays are excluded from the main DAT so a player can opt out.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEPS  (run with --steps or skip with --skip)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  msg   Parse .MSG → individual .txt files (txt/, or data/sound/speech/<folder>/)
  wav   Convert audio/ → standardised 22050 Hz mono 16-bit in wav/
  acm   wav/ → ACM via snd2acm.exe
  mfa   MFA forced alignment → textgrid/   (ACM-only stems skipped)
  lip   textgrid/ → lip/                   (ACM-only stems skipped)
  dat   Pack the source tree + acm/lip/txt → dat/<mod>.dat (+ overlay DATs)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Full pipeline:
  conda activate aligner
  python3 vock.py

  # Text-correction workflow (human-in-the-loop):
  python3 vock.py --steps msg          # extract TXT files
  #  … edit txt/mor1.txt, txt/mor2.txt, etc. …
  python3 vock.py --steps wav mfa lip dat   # resume from audio

  # Rebuild just the DAT:
  python3 vock.py --steps dat

  # Skip ACM generation (no snd2acm needed):
  python3 vock.py --skip acm

  # Change language:
  python3 vock.py --language spanish

  # Console output (default: one line per processed file):
  python3 vock.py --terse        # section headers and per-step tallies only
  python3 vock.py --quiet        # warnings, errors and the final summary only

  # All CLI options:
  python3 vock.py [--language LANG] [--steps STEP [STEP ...]] [--skip STEP [STEP ...]] [-t | -q]

  All paths and settings are configured in vock.cfg.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUPPORTED LANGUAGES  (--language)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  arpabet   english_us_arpa   dictionaries/custom.english_us_arpa.dict
  english   english_mfa       dictionaries/custom.english_mfa.dict
  spanish   spanish_mfa       dictionaries/custom.spanish_mfa.dict
  russian   russian_mfa       dictionaries/custom.russian_mfa.dict
  german    german_mfa        dictionaries/custom.german_mfa.dict
  italian   italian_mfa       dictionaries/custom.italian_mfa.dict
  french    french_mfa        dictionaries/custom.french_mfa.dict
  hungarian hungarian_mfa     dictionaries/custom.hungarian_mfa.dict
  polish    polish_mfa        dictionaries/custom.polish_mfa.dict
  portuguese portuguese_mfa   dictionaries/custom.portuguese_mfa.dict

  Phoneme maps are loaded from ./phonemes/phonemes_<mfa_name>.py
  Each file must export exactly one dict named PHONEME_TABLE.
"""

import argparse
import configparser
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vock.cfg")
_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _parser.read(_CONFIG_PATH, encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_CONFIG_PATH}")

config = {
    "language":     _parser.get("general", "language"),
    "project_root": _parser.get("general", "project_root", fallback="./"),
    "layout":       _parser.get("general", "layout", fallback="flat").strip().lower(),
    "mod_name":     _parser.get("general", "mod_name", fallback="").strip(),
    "paths":    dict(_parser["paths"]),
    "acm_only_msgs": {
        tok.lower()
        for tok in _parser.get("acm_only", "msgs", fallback="").replace(",", " ").split()
        if tok.strip()
    },
    "settings": {
        "mfa_env": _parser.get("settings", "mfa_env"),
        "lufs":    _parser.getfloat("settings", "lufs"),
        "no_norm": _parser.getboolean("settings", "no_norm"),
    },
}

# ─── Language configuration ───────────────────────────────────────────────────

#: Maps --language value → MFA model/dictionary name
LANGUAGE_CONFIG: dict[str, str] = {
    "arpabet":    "english_us_arpa",
    "english":    "english_mfa",
    "spanish":    "spanish_mfa",
    "russian":    "russian_mfa",
    "german":     "german_mfa",
    "italian":    "italian_mfa",
    "french":     "french_mfa",
    "hungarian":  "hungarian_mfa",
    "polish":     "polish_mfa",
    "portuguese": "portuguese_mfa",
    "czech":      "czech_mfa",
}

#: Maps --language value → Windows code page used by Fallout 2 MSG/TXT files.
#: CP1252 (Western European) covers English, Spanish, French, German, Italian,
#: Hungarian, and Portuguese.  Polish and Czech use CP1250 (Central European).
#: Russian uses CP1251 (Cyrillic).
LANG_ENCODING: dict[str, str] = {
    "arpabet":    "cp1252",
    "english":    "cp1252",
    "spanish":    "cp1252",
    "french":     "cp1252",
    "german":     "cp1252",
    "italian":    "cp1252",
    "hungarian":  "cp1252",
    "portuguese": "cp1252",
    "polish":     "cp1250",
    "czech":      "cp1250",
    "russian":    "cp1251",
}

def lang_enc(language: str) -> str:
    """Return the Windows code page for MSG/TXT files in the given language."""
    return LANG_ENCODING.get(language, "cp1252")

#: Maps --language value → data/text/<dir> folder name. Only 'arpabet' differs:
#: it is English text aligned with the ARPAbet phoneme model, so its MSGs live
#: under data/text/english/. Every other language maps to itself.
_TEXT_DIR_LANG: dict[str, str] = {"arpabet": "english"}

def text_dir_lang(language: str) -> str:
    """Return the data/text/<dir> folder name for the given --language value."""
    return _TEXT_DIR_LANG.get(language, language)

def load_phoneme_module(mfa_name: str):
    """
    Dynamically import ./phonemes/phonemes_<mfa_name>.py and return the module.
    Exits with an error if the file does not exist.
    """
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(script_dir, "phonemes", f"phonemes_{mfa_name}.py")
    if not os.path.isfile(module_path):
        sys.exit(f"\n[ERROR] Phoneme file not found: {module_path}\n"
                 f"Cannot proceed without a valid phoneme mapping for {mfa_name}.")
    spec   = importlib.util.spec_from_file_location(f"phonemes_{mfa_name}", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_phoneme_converter(mfa_name: str, module) -> callable:
    """
    Return a ``(str) -> int`` callable for the given MFA model.

    Every phoneme file must export a dict named PHONEME_TABLE.
    The stripping/normalisation logic lives here, not in the phoneme files.

    ARPAbet (english_us_arpa):
      Strip trailing stress digits (0/1/2), upper-case, look up in PHONEME_TABLE.

    IPA-based models (everything else):
      Strip MFA stress markers (ˈ ˌ) and length mark (ː), lower-case,
      look up in PHONEME_TABLE.

    Falls back to 0x0D (open-mouth shape) for unknown symbols in both cases.
    """
    if not hasattr(module, "PHONEME_TABLE"):
        sys.exit(f"\n[ERROR] phonemes_{mfa_name}.py must export a dict named PHONEME_TABLE.")

    table    = module.PHONEME_TABLE
    FALLBACK = 0x0D

    if mfa_name == "english_us_arpa":
        def _convert(phoneme: str) -> int:
            p = re.sub(r"\d", "", phoneme.strip().upper())
            return table.get(p, FALLBACK)
    else:
        def _convert(phoneme: str) -> int:
            p = re.sub(r"[ˈˌː]", "", phoneme.strip().lower())
            return table.get(p, FALLBACK)

    return _convert

# ─── Character NPC include list ───────────────────────────────────────────────

def load_npc_prefixes(npc_file: str | None) -> set[str]:
    """
    Read npc_filter.cfg (or any path set in config["paths"]["npc_filter"]).
    Returns a set of lower-cased NPC tag prefixes to include in the pipeline.
    Returns an empty set when the file is absent or unset — meaning process all.

    File format: one prefix per line, # comments, blank lines ignored.
        arth    # King Arthur
        ahs7    # Oz
    """
    if not npc_file or not os.path.isfile(npc_file):
        return set()
    included: set[str] = set()
    with open(npc_file, encoding="utf-8") as fh:
        for raw in fh:
            token = raw.split("#", 1)[0].strip().lower()
            if token:
                included.add(token)
    return included


def filter_by_prefix(items: list, include: set[str], key=lambda x: x[0]) -> list:
    """
    Keep items whose NPC tag starts with a prefix listed in *include*.
    key(item) must return the tag string (e.g. 'mor1', 'ahs71').
    Returns items unchanged when include is empty (process all).
    Prefixes are matched longest-first to avoid shorter prefixes shadowing longer ones.
    """
    if not include:
        return items
    prefixes = sorted(include, key=len, reverse=True)
    return [it for it in items
            if any(key(it).lower().startswith(p) for p in prefixes)]


def load_ranges(range_file: str | None) -> dict[str, list[tuple[int, int]]]:
    """
    Read a per-NPC tag-range filter file (float_filter.cfg, combat_filter.cfg, or
    any path set under config["paths"]).
    Returns {PREFIX: [(start, end), …]} mapping audio-tag-number ranges per NPC prefix.
    Returns an empty dict when the file is absent or unset.

    File format: PREFIX  start-end  (# comments, blank lines ignored)
        mor   1-2       # Morlis floats (tags mor1, mor2)
        zaius 1         # Zaius float   (tag zaius1)
    Numbers refer to the numeric suffix of the audio tag, not the MSG line number.
    """
    result: dict[str, list[tuple[int, int]]] = {}
    if not range_file or not os.path.isfile(range_file):
        return result
    with open(range_file, encoding="utf-8") as fh:
        for raw in fh:
            token = raw.split("#", 1)[0].strip()
            if not token:
                continue
            parts = token.split(None, 1)   # split on first whitespace only
            if len(parts) < 2:
                continue
            prefix = parts[0].lower()
            for chunk in parts[1].split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "-" in chunk:
                    try:
                        lo, hi = chunk.split("-", 1)
                        result.setdefault(prefix, []).append((int(lo.strip()), int(hi.strip())))
                    except ValueError:
                        print(f"  [warn] {os.path.basename(range_file)}: invalid range '{chunk}' for '{prefix}' — skipping")
                else:
                    try:
                        n = int(chunk)
                        result.setdefault(prefix, []).append((n, n))
                    except ValueError:
                        print(f"  [warn] {os.path.basename(range_file)}: invalid entry '{chunk}' for '{prefix}' — skipping")
    return result


def in_ranges(tag: str, range_map: dict) -> bool:
    """Return True if *tag*'s numeric suffix falls in a range from *range_map*.

    Used to classify a line as ACM-only (no LIP): float_filter.cfg for ambient
    floats, combat_filter.cfg for per-NPC combat barks.

    Matching is done on the numeric suffix of the audio tag (e.g. 'eric3' → 3),
    not the MSG line number, so the ranges are version-stable.

    Prefix matching uses startswith (longest key first), mirroring filter_by_prefix,
    so digit-ending prefixes like 'ahs7' are handled correctly — e.g. 'ahs739' maps
    to prefix 'ahs7' with suffix '39', not prefix 'ahs' with suffix '739'.
    """
    if not range_map:
        return False
    tag_lower = tag.lower()
    for prefix in sorted(range_map, key=len, reverse=True):
        if tag_lower.startswith(prefix):
            suffix = tag_lower[len(prefix):]
            if not suffix.isdigit():
                break
            tag_num = int(suffix)
            for lo, hi in range_map[prefix]:
                if lo <= tag_num <= hi:
                    return True
            break
    return False


# ─── MFA alignment lock list ───────────────────────────────────────────────────

def load_mfa_lock(lock_file: str | None) -> set[str]:
    """
    Read mfa_lock.cfg (or any path set in config["paths"]["mfa_lock"]).
    Returns a set of lower-cased audio-tag stems whose TextGrid must never be
    regenerated by the 'mfa' step — e.g. after a bad MFA alignment (a batching
    artifact, a hand-tuned pause) has been manually corrected and should
    survive future full pipeline runs.

    Locked stems are excluded from the MFA corpus entirely; their existing
    TextGrid is left untouched. If a locked stem has no existing TextGrid,
    a warning is printed (there is nothing to protect, and 'lip' will fail
    for it) since that likely means the lock entry is stale.

    File format: one audio tag per line, # comments, blank lines ignored.
        arth2   # MFA batch-alignment bug, fixed by hand — see notes
    """
    if not lock_file or not os.path.isfile(lock_file):
        return set()
    locked: set[str] = set()
    with open(lock_file, encoding="utf-8") as fh:
        for raw in fh:
            token = raw.split("#", 1)[0].strip().lower()
            if token:
                locked.add(token)
    return locked


def resolve_custom_dict(mfa_name: str, explicit_path: str | None) -> str | None:
    """
    Return the path for the language-specific custom dictionary, or *explicit_path*
    if the caller supplied one.  Returns None when no file exists.
    """
    if explicit_path:
        return explicit_path
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    candidate   = os.path.join(script_dir, "dictionaries", f"custom.{mfa_name}.dict")
    return candidate if os.path.isfile(candidate) else None

def resolve_mfa_dict_paths(mfa_name: str) -> list[str]:
    """Return the default MFA pretrained dictionary search paths for *mfa_name*."""
    return [
        os.path.expanduser(
            f"~/Documents/MFA/pretrained_models/dictionary/{mfa_name}.dict"),
        os.path.expanduser(
            f"~/.local/share/montreal-forced-aligner/pretrained_models/dictionary/{mfa_name}.dict"),
    ]



ALL_STEPS = ["msg", "wav", "acm", "mfa", "lip", "dat"]

# ─── LIP constants ────────────────────────────────────────────────────────────

LIP_VERSION     = 0x00000002
LIP_UNKNOWN     = 0x00005800
LIP_SAMPLE_RATE = 22050
LIP_MULTIPLIER  = 2   # offset = seconds × 2 × 22050


# ─── MSG parser ───────────────────────────────────────────────────────────────

MSG_LINE_RE = re.compile(r"^\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{(.*)\}\s*$")

def parse_msg(path: str, encoding: str = "cp1252") -> list:
    """Return [(line_num, audio_tag, text), …] for lines with a non-empty audio tag."""
    results = []
    with open(path, encoding=encoding) as fh:
        for line in fh:
            m = MSG_LINE_RE.match(line)
            if not m:
                continue
            try:
                line_num = int(m.group(1).strip())
            except ValueError:
                line_num = -1
            tag, text = m.group(2).strip(), m.group(3).strip()
            if tag:
                results.append((line_num, tag, text))
    return results

# ─── Audio helpers ────────────────────────────────────────────────────────────

# Supported audio input extensions
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}

def ffprobe_duration(path: str) -> float:
    """Use ffprobe to get duration in seconds. Works for any container."""
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on '{path}': {r.stderr.strip()}")
    data = json.loads(r.stdout)
    dur = data.get("format", {}).get("duration")
    if dur is None:
        raise RuntimeError(f"ffprobe returned no duration for '{path}'")
    return float(dur)

def wav_is_standard(path: str) -> bool:
    """Return True if WAV is already 22050 Hz, mono, 16-bit PCM."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            return (w.getframerate() == 22050 and
                    w.getnchannels() == 1 and
                    w.getsampwidth() == 2)
    except Exception:
        return False

# ─── TextGrid parser ──────────────────────────────────────────────────────────

def parse_textgrid_phones(tg_path: str) -> list:
    with open(tg_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    phones_match = re.search(
        r'name\s*=\s*"phones?"(.*?)(?=(?:item\s*\[|\Z))',
        content, re.DOTALL | re.IGNORECASE)
    if not phones_match:
        raise ValueError(f"No 'phones' tier in {tg_path}")
    tier_text = phones_match.group(1)
    intervals = re.findall(
        r'xmin\s*=\s*([\d.]+).*?xmax\s*=\s*([\d.]+).*?text\s*=\s*"([^"]*)"',
        tier_text, re.DOTALL)
    return [(float(xmin), float(xmax), label) for xmin, xmax, label in intervals]

def parse_textgrid_words(tg_path: str) -> list:
    """Return [(xmin, xmax, word), …] from the words tier."""
    with open(tg_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    words_match = re.search(
        r'name\s*=\s*"words?"(.*?)(?=(?:item\s*\[|\Z))',
        content, re.DOTALL | re.IGNORECASE)
    if not words_match:
        raise ValueError(f"No 'words' tier in {tg_path}")
    tier_text = words_match.group(1)
    intervals = re.findall(
        r'xmin\s*=\s*([\d.]+).*?xmax\s*=\s*([\d.]+).*?text\s*=\s*"([^"]*)"',
        tier_text, re.DOTALL)
    return [(float(xmin), float(xmax), label) for xmin, xmax, label in intervals]

def find_spn_ranges(tg_path: str) -> list:
    """Return [(xmin, xmax), …] for every 'spn' interval in the phones tier."""
    return [(xmin, xmax)
            for xmin, xmax, label in parse_textgrid_phones(tg_path)
            if label.strip().lower() == "spn"]

def report_unknown_words(textgrid_dir: str) -> list:
    """
    Scan all TextGrids in textgrid_dir.
    For each word whose time range contains a 'spn' phone interval,
    write a report to unknown.txt. Returns the list of (stem, word, xmin, xmax)
    findings (empty when everything was recognised).
    """
    findings = []
    tg_files = sorted(f for f in os.listdir(textgrid_dir) if f.endswith(".TextGrid"))
    if not tg_files:
        return findings

    for tg_file in tg_files:
        stem    = os.path.splitext(tg_file)[0]
        tg_path = os.path.join(textgrid_dir, tg_file)
        try:
            words      = parse_textgrid_words(tg_path)
            spn_ranges = find_spn_ranges(tg_path)
        except Exception as e:
            status("WARN", tg_file, f"could not scan: {e}")
            continue

        for xmin, xmax, word in words:
            if not word.strip():
                continue
            for smin, smax in spn_ranges:
                if smin >= xmin and smax <= xmax + 0.001:
                    findings.append((stem, word, xmin, xmax))
                    break

    out_path = "unknown.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        if findings:
            n_files = len({s for s, *_ in findings})
            f.write("Unknown words (MFA assigned 'spn')\n")
            f.write(f"{len(findings)} occurrence(s) in {n_files} file(s).\n")
            f.write("Add pronunciations for these words to your custom dictionary\n")
            f.write("(dictionaries/custom.<mfa_name>.dict) and re-run --steps mfa lip dat\n")
            current_stem = None
            for stem, word, xmin, xmax in findings:
                if stem != current_stem:
                    f.write(f"\n{stem}.txt\n")
                    current_stem = stem
                f.write(f"  {word:<20}  {xmin:.2f}s – {xmax:.2f}s\n")
            status("WARN", "", f"{len(findings)} unknown word(s) — see {out_path}")
        else:
            f.write("No unknown words — all words recognised by MFA.\n")
            status("OK", "", "no unknown words — all recognised by MFA", record=False)

    return findings

def build_events_from_textgrid(tg_path: str, phoneme_to_code) -> list:
    """Build (timestamp, lip_code) events from a TextGrid file."""
    intervals = parse_textgrid_phones(tg_path)
    events = []
    for xmin, _xmax, label in intervals:
        code = phoneme_to_code(label)
        events.append((xmin, code))
    deduped = []
    for xmin, code in events:
        if not deduped or deduped[-1][1] != code:
            deduped.append((xmin, code))
    return deduped if deduped else [(0.0, 0x00)]

# ─── MFA ─────────────────────────────────────────────────────────────────────

def run_mfa(corpus_dir: str, output_dir: str, mfa_env: str,
            dict_path: str,
            mfa_name: str) -> bool:
    """Run MFA alignment via 'conda run'. Returns True on success."""
    cmd = [
        "conda", "run", "-n", mfa_env, "--no-capture-output",
        "mfa", "align", "--clean", "--single_speaker",
        "--output_format", "long_textgrid",
        corpus_dir,
        dict_path,
        mfa_name,
        output_dir,
    ]
    n = len([f for f in os.listdir(corpus_dir) if f.endswith(".wav")])
    note(f"running MFA on {n} file(s)…  (this may take a minute)")
    r = subprocess.run(cmd, text=True)
    return r.returncode == 0

# ─── snd2acm ─────────────────────────────────────────────────────────────────

DEFAULT_MFA_DICT_PATHS: list[str] = []  # populated at runtime via resolve_mfa_dict_paths()

def find_mfa_dict(mfa_name: str) -> str | None:
    for path in resolve_mfa_dict_paths(mfa_name):
        if os.path.isfile(path):
            return path
    return None

def merge_dictionaries(main_dict: str, custom_dict: str, out_path: str) -> None:
    """Append custom_dict entries to a copy of main_dict, written to out_path."""
    with open(main_dict, encoding="utf-8") as f:
        base = f.read()
    with open(custom_dict, encoding="utf-8") as f:
        custom = f.read().strip()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(base)
        if not base.endswith("\n"):
            f.write("\n")
        f.write(custom)
        f.write("\n")

def resolve_path(rel_path: str | None) -> str | None:
    """Resolve a config["paths"] entry against config["project_root"].

    Falls back to "./" if project_root isn't set, so existing vock.cfg
    files without it keep working unchanged.
    """
    if rel_path is None:
        return None
    root = config.get("project_root", "./")
    return os.path.normpath(os.path.join(root, rel_path))

def find_snd2acm(hint: str = None) -> str | None:
    candidates = []
    if hint:
        candidates.append(hint)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates += [
        "snd2acm",
        "snd2acm.exe",
        os.path.join(script_dir, "snd2acm.exe"),
        os.path.join(os.getcwd(), "snd2acm.exe"),
    ]
    for c in candidates:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def wav_to_acm(snd2acm_bin: str, wav_path: str, acm_path: str) -> None:
    cmd = [snd2acm_bin, "-16", wav_path, acm_path, "-q0"]
    if os.name != "nt" and snd2acm_bin.lower().endswith(".exe"):
        cmd.insert(0, "wine")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"snd2acm failed:\n{r.stderr.strip()}")
    if not os.path.isfile(acm_path) or os.path.getsize(acm_path) == 0:
        raise RuntimeError(f"snd2acm produced no output for '{wav_path}'")

# ─── LIP writer ──────────────────────────────────────────────────────────────

def write_lip(out_path: str, stem: str, duration: float, events: list) -> None:
    """Write a Fallout 2 .LIP binary file."""
    num_phonemes = len(events)
    num_markers  = num_phonemes + 1
    file_length  = round(LIP_MULTIPLIER * LIP_SAMPLE_RATE * duration)
    acm_field    = stem.lower().encode("ascii")[:8].ljust(8, b"\x00")

    with open(out_path, "wb") as f:
        f.write(struct.pack(">I", LIP_VERSION))
        f.write(struct.pack(">I", LIP_UNKNOWN))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", file_length))
        f.write(struct.pack(">I", num_phonemes))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", num_markers))
        f.write(acm_field)
        f.write(b"VOC\x00")
        # Phoneme code bytes
        for _ts, code in events:
            f.write(struct.pack("B", code))
        # Marker table: (type DWORD, offset DWORD) per event + end marker
        for idx, (ts, _code) in enumerate(events):
            if idx == 0:
                f.write(struct.pack(">I", 1))
                f.write(struct.pack(">I", 0))
            else:
                offset = round(LIP_MULTIPLIER * LIP_SAMPLE_RATE * ts)
                f.write(struct.pack(">I", 0))
                f.write(struct.pack(">I", offset))
        f.write(struct.pack(">I", 1))
        f.write(struct.pack(">I", file_length))

# ─── DAT2 packer ─────────────────────────────────────────────────────────────
#
# Fallout 2 DAT2 layout (little-endian):
#   [Data Block]   raw file bytes concatenated from offset 0
#   [Directory Tree]
#     DWORD  num_files
#     per file:
#       DWORD  filename_len
#       BYTES  filename (ASCII, backslash separators, lowercase)
#       BYTE   is_compressed  (0 = uncompressed)
#       DWORD  real_size
#       DWORD  packed_size
#       DWORD  offset_in_data_block
#   [Footer]
#     DWORD  tree_size   (bytes of Directory Tree)
#     DWORD  file_size   (total DAT bytes)
#
# Reference: https://fodev.net/files/fo2/dat.html

def _npc_folder(stem: str) -> str:
    """Derive the NPC folder from a stem like mor1 → mor."""
    return re.sub(r"\d+$", "", stem).lower()

def sound_folder(stem: str, src_msg: str | None, acm_only_msgs: set[str]) -> tuple[str, ...]:
    """Folder under sound/ for an audio stem, as path parts.

    Lines from an ACM-only MSG (e.g. pipboy.msg → holodisk narration) go to
    sound/<msg basename>/ (e.g. sound/pipboy/); every other line goes to
    sound/speech/<NPC prefix>/, so per-NPC combat barks land in that NPC's own
    folder alongside their dialogue.
    """
    if src_msg:
        base = os.path.splitext(os.path.basename(src_msg))[0].lower()
        if base in acm_only_msgs:
            return (base,)
    return ("speech", _npc_folder(stem))

def collect_data_tree_entries(data_root: str, exclude_stems: set[str] | None = None,
                              exclude_dirs: tuple[str, ...] = ("sound\\speech\\",)):
    """Build [(dat_path, local_path), …] by walking an RPU-shaped data/ tree
    verbatim — the on-disk layout *is* the DAT layout.

    exclude_stems: speech stems (filename without extension) to leave out, so the
    float / combat / holodisk overlays can carry them instead of the main DAT.
    exclude_dirs : lowercase DAT-path prefixes the stem exclusion applies under.
    """
    entries = []
    exclude = {s.lower() for s in (exclude_stems or ())}
    if not os.path.isdir(data_root):
        return entries
    for root, _dirs, files in os.walk(data_root):
        for f in sorted(files):
            local_path = os.path.join(root, f)
            rel = os.path.relpath(local_path, data_root).replace(os.sep, "\\")
            if exclude and rel.lower().startswith(exclude_dirs):
                if os.path.splitext(f)[0].lower() in exclude:
                    continue
            entries.append((rel, local_path))
    return entries

def collect_dat_entries(msg_paths, acm_dir, lip_dir, txt_dir,
                        include_acm=True, only_stems=None,
                        include_msg=True, discover_from="lip",
                        int_dir=None, art_dir=None, sound_dirs=None):
    """
    Build [(dat_path, local_path), …] pairs with backslash separators.

    only_stems   : if given (set of lowercase stems), restrict output to those stems.
    include_msg  : whether to include MSG files (set False for the float DAT).
    discover_from: "lip" — find stems via lip/ dir (default, for talking-head DAT).
                   "acm" — find stems via acm/ dir (for float DAT, which has no LIP files).
    int_dir      : folder of pre-compiled .INT scripts → packed as scripts\\*.
    art_dir      : folder of art assets (e.g. art_dir/heads/*.FRM) → packed as
                   art\\<subpath>, preserving the sub-folder layout under art_dir.
    sound_dirs   : optional {stem: DAT folder} override for ACM-only MSG stems
                   (e.g. "sound\\pipboy"); those get only their ACM, no LIP/TXT.
    """
    entries = []

    # MSG files → text\english\dialog\
    if include_msg:
        for msg_path in msg_paths:
            if os.path.isfile(msg_path):
                msg_name = os.path.basename(msg_path).lower()
                entries.append((f"text\\english\\dialog\\{msg_name}", msg_path))

    # Discover stems from the requested source directory
    stem_files: dict[str, str] = {}   # stem → path of the discovery file (lip or acm)
    if discover_from == "lip" and os.path.isdir(lip_dir):
        for f in os.listdir(lip_dir):
            if f.lower().endswith(".lip"):
                stem = os.path.splitext(f)[0].lower()
                stem_files[stem] = os.path.join(lip_dir, f)
    elif discover_from == "acm" and os.path.isdir(acm_dir):
        for f in os.listdir(acm_dir):
            if f.lower().endswith(".acm"):
                stem = os.path.splitext(f)[0].lower()
                stem_files[stem] = os.path.join(acm_dir, f)

    # Apply stem whitelist
    if only_stems is not None:
        normalised = {s.lower() for s in only_stems}
        stem_files = {s: p for s, p in stem_files.items() if s in normalised}

    for stem in sorted(stem_files):
        if sound_dirs and stem in sound_dirs:
            acm_path = os.path.join(acm_dir, stem + ".acm")
            if include_acm and os.path.isfile(acm_path):
                entries.append((f"{sound_dirs[stem]}\\{stem}.acm", acm_path))
            continue
        folder = _npc_folder(stem)
        base   = f"sound\\speech\\{folder}"
        # LIP file — present for talking-head stems and floats (included as a safety net)
        lip_path = os.path.join(lip_dir, stem + ".lip")
        if os.path.isfile(lip_path):
            entries.append((f"{base}\\{stem}.lip", lip_path))
        # ACM file
        if include_acm:
            acm_path = os.path.join(acm_dir, stem + ".acm")
            if os.path.isfile(acm_path):
                entries.append((f"{base}\\{stem}.acm", acm_path))
        # TXT file
        txt_path = os.path.join(txt_dir, stem + ".txt")
        if os.path.isfile(txt_path):
            entries.append((f"{base}\\{stem}.txt", txt_path))

    # INT files → scripts\
    if int_dir and os.path.isdir(int_dir):
        for f in sorted(os.listdir(int_dir)):
            if f.lower().endswith(".int"):
                entries.append((f"scripts\\{f.lower()}", os.path.join(int_dir, f)))

    # Art assets (e.g. art/heads/*.FRM) → art\<subpath>, sub-folders preserved
    if art_dir and os.path.isdir(art_dir):
        for root, _dirs, files in os.walk(art_dir):
            for f in sorted(files):
                local_path = os.path.join(root, f)
                rel = os.path.relpath(local_path, art_dir).replace(os.sep, "\\")
                entries.append((f"art\\{rel.lower()}", local_path))

    return entries

def write_dat2(out_path: str, entries: list) -> None:
    """Write a Fallout 2 DAT2 archive (pure Python, uncompressed)."""
    # Normalise paths to lowercase ASCII with backslashes, sort alphabetically
    entries = [(d.lower(), l) for d, l in entries]
    entries.sort(key=lambda x: x[0])

    # Read all file data upfront and track offsets
    file_data, offsets = [], []
    cursor = 0
    for _dat_path, local_path in entries:
        raw = open(local_path, "rb").read()
        file_data.append(raw)
        offsets.append(cursor)
        cursor += len(raw)

    # Build the directory tree
    tree = bytearray()
    tree += struct.pack("<I", len(entries))
    for i, (dat_path, _local) in enumerate(entries):
        raw      = file_data[i]
        fn_bytes = dat_path.encode("ascii")
        tree += struct.pack("<I", len(fn_bytes))
        tree += fn_bytes
        tree += struct.pack("<B", 0)            # is_compressed = 0
        tree += struct.pack("<I", len(raw))     # real_size
        tree += struct.pack("<I", len(raw))     # packed_size  (= real since uncompressed)
        tree += struct.pack("<I", offsets[i])   # offset in data block

    tree_size = len(tree)
    file_size = cursor + tree_size + 8  # +8 for the two footer DWORDs

    with open(out_path, "wb") as f:
        for raw in file_data:
            f.write(raw)
        f.write(tree)
        f.write(struct.pack("<I", tree_size))
        f.write(struct.pack("<I", file_size))

# ─── Dependency fast-fail check ──────────────────────────────────────────────

def check_dependencies(run: set, snd2acm_hint: str, mfa_env: str) -> None:
    """Exit with a clear error message if required tools are missing."""
    errors = []

    # ffmpeg and ffprobe are required by the wav step (and lip for duration)
    needs_ffmpeg = bool(run & {"wav", "lip"})
    if needs_ffmpeg:
        if not shutil.which("ffmpeg"):
            errors.append(
                "  ffmpeg  not found on PATH.\n"
                "  Install:  sudo apt install ffmpeg -y")
        if not shutil.which("ffprobe"):
            errors.append(
                "  ffprobe not found on PATH.\n"
                "  Install:  sudo apt install ffmpeg -y  (ffprobe is bundled with ffmpeg)")

    # snd2acm for the acm step
    if "acm" in run:
        if not find_snd2acm(snd2acm_hint):
            errors.append(
                "  snd2acm.exe  not found.\n"
                "  Download from https://fodev.net/files/mirrors/teamx-utils/snd2acm.rar\n"
                "  and place snd2acm.exe next to vock.py.  On Linux also install Wine:\n"
                "    sudo apt install wine -y")

    # conda for the mfa step
    if "mfa" in run:
        if not shutil.which("conda"):
            errors.append(
                "  conda  not found on PATH.\n"
                "  Install Miniconda:\n"
                "    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh\n"
                "    bash Miniconda3-latest-Linux-x86_64.sh -b\n"
                "    ~/miniconda3/bin/conda init bash && exec bash")

    if errors:
        print(f"\n{_RED}{_BOLD}[DEPENDENCY ERROR]{_RESET} "
              f"The following required tools are missing:\n")
        for e in errors:
            print(e)
        print()
        sys.exit(1)

# ─── Console output ───────────────────────────────────────────────────────────

#: ANSI colour is used only when stdout is an interactive terminal and the
#: caller hasn't opted out via NO_COLOR (https://no-color.org/). Piped or
#: redirected output (CI logs, `| tee`, `> file`) stays plain ASCII.
_USE_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM", "") != "dumb"
)

def _c(code: str) -> str:
    """Return an ANSI escape, or "" when colour is disabled."""
    return code if _USE_COLOR else ""

_RESET  = _c("\033[0m")
_DIM    = _c("\033[2m")
_BOLD   = _c("\033[1m")
_RED    = _c("\033[31m")
_GREEN  = _c("\033[32m")
_YELLOW = _c("\033[33m")
_CYAN   = _c("\033[36m")

#: (colour, TTY glyph, plain-text label) per status kind.
_STATUS = {
    "OK":   (_GREEN,  "✓", "ok  "),
    "WARN": (_YELLOW, "⚠", "warn"),
    "FAIL": (_RED,    "✗", "FAIL"),
    "SKIP": (_DIM,    "·", "skip"),
    "INFO": (_CYAN,   "›", "info"),
}

#: Verbosity: 0 = quiet (warnings, errors and the final summary only),
#: 1 = terse (section headers + per-step tallies, no per-file lines),
#: 2 = full (every processed file) — the default. Set from the CLI
#: via set_verbosity().
_verbosity = 2

def set_verbosity(level: int) -> None:
    global _verbosity
    _verbosity = level

#: WARN/FAIL lines collected during the run, reprinted by print_problem_recap().
_problems: list[tuple[str, str, str]] = []
_current_section = ""

def status(kind: str, name: str = "", detail: str = "",
           *, record: bool = True, bulk: bool = False) -> None:
    """
    Print one aligned status line:  ``<mark>  <name>   <detail>``

        status("OK",   "mor1.acm", "12.3 KB")    ->     ✓  mor1.acm              12.3 KB
        status("FAIL", "mor4",     "ffmpeg: …")   ->     ✗  mor4                  ffmpeg: …

    *kind* is OK | WARN | FAIL | SKIP | INFO.  WARN and FAIL lines are always
    shown and are stashed under the current section for the end-of-run PROBLEMS
    recap (unless *record* is False).

    *bulk* marks a routine one-per-file line: shown only at ``-v``.  Other
    OK/INFO/SKIP lines show at normal verbosity and are hidden by ``-q``.
    """
    if record and kind in ("WARN", "FAIL"):
        _problems.append((kind, _current_section,
                          "  ".join(p for p in (name, detail) if p)))
    is_problem = kind in ("WARN", "FAIL")
    show = is_problem or _verbosity >= 2 or (_verbosity >= 1 and not bulk)
    if not show:
        return
    colour, glyph, label = _STATUS.get(kind, _STATUS["INFO"])
    mark = glyph if _USE_COLOR else label
    if name and detail:
        body = f"{name:<20}  {_DIM}{detail}{_RESET}"
    else:
        body = name or detail
    print(f"  {colour}{mark}{_RESET}  {body}")

def note(text: str = "", *, indent: int = 2) -> None:
    """A plain progress / per-step tally line — shown at normal verbosity and up."""
    if _verbosity >= 1:
        print(f"{' ' * indent}{text}" if text else "")

def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")

def summarise(items, limit: int | None = None) -> str:
    """
    ``'a, b, c'`` when short; ``'a, b, c, … +N more'`` past *limit*
    (default 8). Keeps config-banner lists from wrapping across the
    screen — the authoritative list lives in the .cfg file.
    """
    items = list(items)
    if limit is None:
        limit = 8
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f", … +{len(items) - limit} more"

def _fmt_dur(sec: float) -> str:
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(round(sec)), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"

def _fmt_size(kb: float) -> str:
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.1f} KB"

def print_section(title: str, step: int | None = None, total: int | None = None,
                  *, skipped: bool = False) -> None:
    """Slim, numbered step banner. Suppressed entirely by ``-q``."""
    global _current_section
    _current_section = title
    if _verbosity < 1:
        return
    tag = f"STEP {step}/{total} · " if step else ""
    if skipped:
        print(f"\n{_DIM}── {tag}{title} — skipped{_RESET}")
        return
    label = f"━━ {tag}{title} "
    print(f"\n{_BOLD}{_CYAN}{label}{'━' * max(4, 64 - len(label))}{_RESET}")

def print_summary(title: str, rows: list[tuple[str, str]],
                  *, duration: float | None = None) -> None:
    """The DONE banner: a bold rule and a left-aligned label/value table."""
    bar  = f"{_BOLD}{_GREEN}{'═' * 60}{_RESET}"
    head = f"{_BOLD}{title}{_RESET}"
    if duration is not None:
        head += f"   {_DIM}{_fmt_dur(duration)}{_RESET}"
    print(f"\n{bar}\n  {head}\n{bar}")
    w = max((len(k) for k, _v in rows), default=0)
    for k, v in rows:
        print(f"  {k:<{w}}  {v}")

def print_problem_recap() -> None:
    """Reprint every WARN/FAIL from the run, grouped by the step that raised it."""
    if not _problems:
        print(f"\n  {_GREEN}No warnings or errors.{_RESET}")
        return
    n_fail = sum(k == "FAIL" for k, _s, _m in _problems)
    n_warn = sum(k == "WARN" for k, _s, _m in _problems)
    rule = f"{_YELLOW}{'─' * 60}{_RESET}"
    print(f"\n{rule}")
    print(f"  {_BOLD}PROBLEMS{_RESET}   {n_fail} error(s), {n_warn} warning(s)")
    print(rule)
    last = None
    for kind, section, msg in _problems:
        if section != last:
            print(f"\n  {_DIM}{section}{_RESET}")
            last = section
        colour, glyph, label = _STATUS[kind]
        mark = glyph if _USE_COLOR else label
        print(f"    {colour}{mark}{_RESET}  {msg}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def _scan_msg_dir(path: str) -> list:
    """Return sorted list of .MSG file paths found in *path* (a directory)."""
    if not os.path.isdir(path):
        sys.exit(f"MSG directory not found: '{path}'\n"
                 "Create a 'msg/' folder and put your .MSG file(s) in it, "
                 "or update the 'msg' path in vock.cfg.")
    found = sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".msg"))
    if not found:
        sys.exit(f"No .MSG files found in '{path}/'")
    return found


def main():
    parser = argparse.ArgumentParser(
        description="V.O.C.K. — Vocal Output Creation Kit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--language", default=config["language"],
        choices=list(LANGUAGE_CONFIG.keys()),
        help=f"MFA language / phoneme set (default from vock.cfg: {config['language']}). "
             f"Choices: {', '.join(LANGUAGE_CONFIG)}")
    parser.add_argument("--steps", nargs="+", metavar="STEP", choices=ALL_STEPS,
        help=f"Run ONLY these step(s). Available: {', '.join(ALL_STEPS)}")
    parser.add_argument("--skip",  nargs="+", metavar="STEP", choices=ALL_STEPS,
        help="Skip these step(s) from the full pipeline.")
    parser.add_argument("-t", "--terse", action="store_true",
        help="Section headers and per-step tallies only — no per-file lines.")
    parser.add_argument("-q", "--quiet", action="store_true",
        help="Only warnings, errors and the final summary.")
    args = parser.parse_args()

    if args.terse and args.quiet:
        parser.error("--terse and --quiet cannot be combined")
    set_verbosity(0 if args.quiet else 1 if args.terse else 2)
    _start = time.monotonic()

    # ── Resolve all paths and settings from vock.cfg ──────────────────────────
    # Every paths entry is resolved against config["project_root"] (default "./"),
    # so pointing project_root at another project's folder retargets the whole
    # pipeline without touching anything else here.
    paths  = config["paths"]
    layout = config.get("layout", "flat")
    acm_only_msgs = config.get("acm_only_msgs", set())

    # Mod name → DAT filenames. Defaults to the project_root folder name so
    # sibling mods (vock-fo2, vock-fo1, vock-sonora) never collide on vock.dat.
    mod_name = (config.get("mod_name")
                or os.path.basename(os.path.normpath(config.get("project_root", "."))
                                    ) or "vock")

    # audio / wav / textgrid: the MFA rebuild chain. Under layout=data it lives
    # in work/ (work/audio gitignored, work/wav + work/textgrid committed);
    # flat layout keeps ./audio ./wav ./textgrid. A cfg key overrides either.
    _wk = "./work/" if layout == "data" else "./"
    audiodir    = resolve_path(paths.get("audio")    or _wk + "audio")
    wavdir      = resolve_path(paths.get("wav")      or _wk + "wav")
    textgriddir = resolve_path(paths.get("textgrid") or _wk + "textgrid")

    dat_dir          = resolve_path(paths.get("dat_dir", "./dat"))
    datfile          = os.path.join(dat_dir, f"{mod_name}.dat")
    float_datfile    = os.path.join(dat_dir, f"{mod_name}-floats.dat")
    combat_datfile   = os.path.join(dat_dir, f"{mod_name}-combat.dat")
    pipboy_datfile   = os.path.join(dat_dir, f"{mod_name}-pipboy.dat")
    snd2acm_cfg      = resolve_path(paths["snd2acm"])
    npc_filter_file  = resolve_path(paths.get("npc_filter"))    # optional key; None if absent

    # data layout: an RPU-shaped data/ tree, packed verbatim. Source MSGs are
    # read from data/text/<lang>/**/*.msg; generated speech (acm/lip/txt) is
    # written into data/sound/speech/<folder>/, except ACM-only MSG audio
    # (acm only, e.g. holodisks) which goes to data/sound/<msg basename>/.
    data_root   = resolve_path(paths.get("data_root", "./data"))
    sound_root  = os.path.join(data_root, "sound")
    speech_root = os.path.join(sound_root, "speech")
    acm_only_roots = [os.path.join(sound_root, m) for m in sorted(acm_only_msgs)]
    # flat layout: category folders. Unused when layout == "data".
    msgdir      = resolve_path(paths["msg"])
    txtdir      = resolve_path(paths["txt"])
    acmdir      = resolve_path(paths["acm"])
    lipdir      = resolve_path(paths["lip"])
    intdir      = resolve_path(paths.get("scripts", "./scripts"))
    artdir      = resolve_path(paths.get("art", "./art"))

    settings    = config["settings"]
    mfa_env     = settings["mfa_env"]
    lufs        = settings["lufs"]
    no_norm     = settings["no_norm"]

    npc_prefixes = load_npc_prefixes(npc_filter_file)
    float_filter_file  = resolve_path(paths.get("float_filter"))
    float_map          = load_ranges(float_filter_file)
    combat_filter_file = resolve_path(paths.get("combat_filter"))
    combat_map         = load_ranges(combat_filter_file)
    mfa_lock_file = resolve_path(paths.get("mfa_lock"))
    mfa_lock      = load_mfa_lock(mfa_lock_file)

    # ── Source-tree layout helpers ───────────────────────────────────────────
    def _source_msg_paths() -> list:
        """Source-language MSG file paths (the ones parsed for audio tags)."""
        if layout == "data":
            base = os.path.join(data_root, "text", text_dir_lang(args.language))
            if not os.path.isdir(base):
                sys.exit(f"MSG source not found: '{base}'\n"
                         f"layout=data expects data/text/{text_dir_lang(args.language)}/**/*.msg")
            found = sorted(
                os.path.join(r, f)
                for r, _d, files in os.walk(base)
                for f in files if f.lower().endswith(".msg"))
            if not found:
                sys.exit(f"No .msg files under '{base}/'")
            return found
        return _scan_msg_dir(msgdir)

    def _speech_dir(stem: str) -> str:
        """data-layout sound/<folder> for a stem (uses stem_src, below)."""
        return os.path.join(sound_root,
                            *sound_folder(stem, stem_src.get(stem.lower()), acm_only_msgs))

    def needs_txt(stem: str) -> bool:
        """data layout: ACM-only MSG stems (holodisks) get no .txt on disk."""
        return not (layout == "data" and stem.lower() in acm_only_stems)

    def txt_path_for(stem: str) -> str:
        return (os.path.join(_speech_dir(stem), stem + ".txt") if layout == "data"
                else os.path.join(txtdir, stem + ".txt"))

    def acm_path_for(stem: str) -> str:
        return (os.path.join(_speech_dir(stem), stem + ".acm") if layout == "data"
                else os.path.join(acmdir, stem + ".acm"))

    def lip_path_for(stem: str) -> str:
        return (os.path.join(_speech_dir(stem), stem + ".lip") if layout == "data"
                else os.path.join(lipdir, stem + ".lip"))

    def _iter_existing(ext: str):
        """Yield (stem, path) for every generated .<ext> already on disk, across
        both layouts — used when a step is skipped and later steps still need
        the files it would have produced."""
        if layout == "data":
            if os.path.isdir(speech_root):
                for r, _d, files in os.walk(speech_root):
                    for f in files:
                        if f.lower().endswith(ext):
                            yield os.path.splitext(f)[0], os.path.join(r, f)
        else:
            d = {"txt": txtdir, "acm": acmdir, "lip": lipdir}[ext.lstrip(".")]
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith(ext):
                        yield os.path.splitext(f)[0], os.path.join(d, f)

    def is_acm_only(stem: str) -> bool:
        """ACM-only = no MFA, no LIP: holodisk narration (acm_only msgs),
        ambient floats, and per-NPC combat barks."""
        src  = stem_src.get(stem.lower())
        base = os.path.splitext(os.path.basename(src))[0].lower() if src else ""
        return (base in acm_only_msgs
                or in_ranges(stem, float_map)
                or in_ranges(stem, combat_map))

    def _data_overlay_entries(stems: set[str]) -> list:
        """data layout: [(dat_path, local_path), …] for the speech files (acm +
        any lip/txt) whose stem is in *stems* — for an opt-out overlay DAT."""
        out, want = [], {s.lower() for s in stems}
        for top in [speech_root] + acm_only_roots:
            if not (want and os.path.isdir(top)):
                continue
            for r, _d, files in os.walk(top):
                for f in sorted(files):
                    if os.path.splitext(f)[0].lower() in want:
                        p = os.path.join(r, f)
                        out.append((os.path.relpath(p, data_root).replace(os.sep, "\\"), p))
        return out

    # ── Language & Dictionary Resolution ──────────────────────────────────────
    mfa_name        = LANGUAGE_CONFIG[args.language]
    phoneme_mod     = load_phoneme_module(mfa_name)
    phoneme_to_code = make_phoneme_converter(mfa_name, phoneme_mod)

    custom_dict_path = resolve_custom_dict(mfa_name, None)
    main_dict_path   = find_mfa_dict(mfa_name)

    # Prepare printable strings
    custom_dict_print = custom_dict_path if custom_dict_path and os.path.isfile(custom_dict_path) else "None"
    main_dict_print   = main_dict_path if main_dict_path else f"{mfa_name} (MFA built-in/downloaded)"

    # ── Scan the source MSGs once, up front (always — so the mfa/lip/dat steps
    #    see this even when the msg step is skipped). Records, per audio stem,
    #    which MSG file it came from (stem_src, for speech-folder routing) and
    #    which stems are ACM-only floats / combat barks. ────────────────────────
    stem_src:      dict[str, str] = {}   # stem → source .msg path
    float_stems:   set[str] = set()
    combat_stems:  set[str] = set()
    acm_only_stems: set[str] = set()     # from [acm_only] msgs, e.g. pipboy
    acm_only_dirs: dict[str, str] = {}   # acm-only stem → DAT folder, e.g. sound\pipboy
    try:
        _scan_paths = _source_msg_paths()
    except SystemExit:
        _scan_paths = []
    for _mp in _scan_paths:
        _base = os.path.splitext(os.path.basename(_mp))[0].lower()
        try:
            for _ln, _tag, _text in parse_msg(_mp, encoding=lang_enc(args.language)):
                t = _tag.lower()
                stem_src.setdefault(t, _mp)
                if in_ranges(_tag, float_map):
                    float_stems.add(t)
                if in_ranges(_tag, combat_map):
                    combat_stems.add(t)
                if _base in acm_only_msgs:
                    acm_only_stems.add(t)
                    acm_only_dirs.setdefault(t, f"sound\\{_base}")
        except Exception:
            pass

    if _verbosity >= 1:
        print_section("Configuration")
        for label, value in (
            ("Language",       args.language),
            ("Mod",            mod_name),
            ("Layout",         layout + (f"  ({data_root})" if layout == "data" else "")),
            ("Acoustic Model", mfa_name),
            ("Dictionary",     main_dict_print),
            ("Custom Dict",    custom_dict_print),
            ("Phoneme Map",    f"phonemes_{mfa_name}.py"),
            ("NPC filter",     summarise(sorted(npc_prefixes)) if npc_prefixes else "all"),
        ):
            print(f"  {label:<15}: {value}")
        # Floats / combat / MFA lock: show the count, then a truncated sample
        # (full list under -v) so a big filter file doesn't flood the banner.
        # The authoritative lists live in those files.
        if float_map:
            print(f"  {'Floats':<15}: {len(float_stems)} stem(s) — "
                  f"{summarise(sorted(float_stems))}")
        if combat_map:
            print(f"  {'Combat barks':<15}: {len(combat_stems)} stem(s) — "
                  f"{summarise(sorted(combat_stems))}")
        if acm_only_msgs:
            print(f"  {'ACM-only msgs':<15}: {summarise(sorted(acm_only_msgs))}")
        if mfa_lock:
            print(f"  {'MFA lock':<15}: {len(mfa_lock)} "
                  f"{_plural(len(mfa_lock), 'tag')} — {summarise(sorted(mfa_lock))}")

    # Resolve which steps to run
    if args.steps:
        run = set(args.steps)
    else:
        run = set(ALL_STEPS)
        if args.skip:
            for s in args.skip:
                run.discard(s)

    ordered_steps = [s for s in ALL_STEPS if s in run]
    n_steps = len(ordered_steps)
    def _step_no(key: str) -> int | None:
        return ordered_steps.index(key) + 1 if key in ordered_steps else None

    # Fast-fail dependency check
    check_dependencies(run, snd2acm_cfg, mfa_env)

    # ── Pipeline state ────────────────────────────────────────────────────────
    msg_paths  = []
    txt_map    = {}      # stem → text (from msg step or loaded from txt/)
    wav_pairs  = []      # (stem, std_wav_path, txt_path) — 22050 Hz mono 16-bit

    acm_ok     = 0
    lip_ok     = 0
    lip_fail   = 0
    n_unknown  = 0      # MFA 'spn' occurrences → unknown.txt (set by the mfa step)

    # ── STEP 1: MSG → TXT ────────────────────────────────────────────────────
    if "msg" in run:
        print_section("Parse MSG → TXT", _step_no("msg"), n_steps)

        msg_paths = _source_msg_paths()

        all_entries = []
        for msg_path in msg_paths:
            found = parse_msg(msg_path, encoding=lang_enc(args.language))
            if not found:
                status("WARN", os.path.basename(msg_path),
                       "no tagged audio lines — skipping")
                continue
            all_entries.extend(found)
            if len(msg_paths) > 1:
                note(f"{os.path.basename(msg_path)}: {len(found)} tagged line(s)")

        if not all_entries:
            sys.exit("No audio-tagged lines found in any MSG file.")

        all_entries = filter_by_prefix(all_entries, npc_prefixes, key=lambda x: x[1])

        # Collapse repeated audio tags. The same tag legitimately recurs across
        # MSG lines (one spoken line reused by several dialogue nodes). Group by
        # tag; when the grouped lines disagree on text it's a real ambiguity —
        # the recording only matches one — so warn once, naming the lines, and
        # keep the first occurrence.
        by_tag: dict[str, list[tuple[int, str]]] = {}
        for line_num, tag, text in all_entries:
            by_tag.setdefault(tag, []).append((line_num, text))

        for tag, occ in sorted(by_tag.items()):
            if len({t for _ln, t in occ}) > 1:
                lines = ", ".join(str(ln) for ln, _t in occ)
                status("WARN", tag,
                       f"reused on MSG lines {lines} with differing text — "
                       f"keeping line {occ[0][0]}")

        if layout != "data":
            os.makedirs(txtdir, exist_ok=True)
        written = kept = 0
        for tag, occ in sorted(by_tag.items()):
            text = occ[0][1]                       # first occurrence wins
            if not needs_txt(tag):
                txt_map[tag] = text                # ACM-only: text kept in memory only
                continue
            out  = txt_path_for(tag)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if os.path.isfile(out):
                existing = open(out, encoding=lang_enc(args.language)).read().strip()
                if existing == text:
                    txt_map[tag] = text
                else:
                    txt_map[tag] = existing        # respect a manual edit on disk
                    kept += 1
                    status("INFO", f"{tag}.txt", "kept manual edit on disk",
                           record=False, bulk=True)
                continue
            with open(out, "w", encoding=lang_enc(args.language)) as fh:
                fh.write(text)
            txt_map[tag] = text
            written += 1

        parts = [f"{written} new"] if written else []
        if kept:
            parts.append(f"{kept} kept (edited on disk)")
        note(f"{len(by_tag)} tag(s)" + (f" — {', '.join(parts)}" if parts else " — all current"))

    else:
        print_section("Parse MSG → TXT", skipped=True)
        # Resolve msg_paths for the DAT step (best-effort; missing dir is not fatal here)
        try:
            msg_paths = _source_msg_paths()
        except SystemExit:
            msg_paths = []
        # Load txt_map from existing TXT files (respecting manual edits)
        for stem, p in _iter_existing(".txt"):
            txt_map[stem] = open(p, encoding=lang_enc(args.language)).read().strip()

    # ── STEP 2: audio/ → wav/ (Universal Audio step) ─────────────────────────
    if "wav" in run:
        print_section("Audio → WAV  (22050 Hz mono 16-bit)", _step_no("wav"), n_steps)
        os.makedirs(wavdir, exist_ok=True)

        # Scan audio/ for all supported formats
        audio_files_by_stem: dict[str, list[str]] = {}
        if os.path.isdir(audiodir):
            for f in sorted(os.listdir(audiodir)):
                ext = os.path.splitext(f)[1].lower()
                if ext in AUDIO_EXTS:
                    stem = os.path.splitext(f)[0]
                    audio_files_by_stem.setdefault(stem, []).append(f)
        else:
            status("WARN", "", f"audio folder '{audiodir}/' not found")

        # Higher-priority format wins (wav > everything else) when a stem has
        # more than one source file -- e.g. a leftover take in another format
        # that never got cleaned up after a re-record. That's silent data loss
        # waiting to happen if nobody notices, so flag it every time it fires.
        audio_map: dict[str, str] = {}
        for stem, files in sorted(audio_files_by_stem.items()):
            if len(files) > 1:
                files_sorted = sorted(files, key=lambda f: (os.path.splitext(f)[1].lower() != ".wav", f))
                chosen, ignored = files_sorted[0], files_sorted[1:]
                status("WARN", stem,
                       f"{len(files)} source files ({', '.join(files)}) — using "
                       f"{chosen}, ignoring {', '.join(ignored)}; delete the "
                       f"unwanted take(s) so this can't pick wrong later")
                audio_map[stem] = os.path.join(audiodir, chosen)
            else:
                audio_map[stem] = os.path.join(audiodir, files[0])

        if not audio_map:
            sys.exit(f"No audio files found in '{audiodir}/'")

        enc_ok = 0
        skipped = 0
        for stem in filter_by_prefix(sorted(audio_map), npc_prefixes, key=lambda x: x):
            src_path = audio_map[stem]
            # Validate: must have a matching TXT (ACM-only MSG stems need none —
            # needs_txt() is only False for stems tagged in those MSGs)
            txt_path = txt_path_for(stem) if needs_txt(stem) else None
            if txt_path and not os.path.isfile(txt_path):
                status("SKIP", stem,
                       "no matching .txt (run 'msg' first, or tag not in MSG)",
                       bulk=True)
                skipped += 1
                continue

            out_wav = os.path.join(wavdir, stem + ".wav")
            try:
                ext = os.path.splitext(src_path)[1].lower()
                # Fast path: WAV already in correct format and norm disabled
                if no_norm and ext == ".wav" and wav_is_standard(src_path):
                    shutil.copy2(src_path, out_wav)
                    status("OK", f"{stem}.wav", "copied — already 22050 Hz mono 16-bit",
                           bulk=True)
                else:
                    cmd = ["ffmpeg", "-y", "-i", src_path]
                    if not no_norm:
                        cmd.extend(["-af", f"loudnorm=I={lufs}:LRA=11:TP=-1.5"])
                    cmd.extend(["-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", out_wav])
                    r = subprocess.run(cmd, capture_output=True, text=True)
                    if r.returncode != 0:
                        raise RuntimeError(r.stderr.strip())
                    action = "encoded + normalised" if not no_norm else "encoded"
                    status("OK", f"{stem}.wav", action, bulk=True)

                wav_pairs.append((stem, out_wav, txt_path))
                enc_ok += 1
            except RuntimeError as e:
                status("FAIL", stem, f"ffmpeg: {e}")

        note(f"{enc_ok} WAV ready, {skipped} skipped (no matching .txt)")

    else:
        print_section("Audio → WAV", skipped=True)
        # Populate wav_pairs from existing standardised WAVs
        if os.path.isdir(wavdir):
            for f in sorted(os.listdir(wavdir)):
                if f.lower().endswith(".wav"):
                    stem     = os.path.splitext(f)[0]
                    txt_path = txt_path_for(stem) if needs_txt(stem) else None
                    if (txt_path is None or os.path.isfile(txt_path)) and \
                            filter_by_prefix([(stem,)], npc_prefixes, key=lambda x: x[0]):
                        wav_pairs.append((stem, os.path.join(wavdir, f), txt_path))

    # ── STEP 3: wav/ → ACM ───────────────────────────────────────────────────
    if "acm" in run:
        print_section("WAV → ACM", _step_no("acm"), n_steps)
        if not wav_pairs:
            status("SKIP", "", "no standardised WAV files — run 'wav' first")
        else:
            snd2acm_bin = find_snd2acm(snd2acm_cfg)
            if not snd2acm_bin:
                status("WARN", "", "snd2acm.exe not found — ACM generation skipped")
                status("INFO", "", "place snd2acm.exe next to vock.py and re-run",
                       record=False)
            else:
                if layout != "data":
                    os.makedirs(acmdir, exist_ok=True)
                for stem, wav_path, _txt in wav_pairs:
                    acm_path = acm_path_for(stem)
                    os.makedirs(os.path.dirname(acm_path), exist_ok=True)
                    try:
                        wav_to_acm(snd2acm_bin, wav_path, acm_path)
                        size_kb = os.path.getsize(acm_path) / 1024
                        status("OK", f"{stem}.acm", f"{size_kb:.1f} KB", bulk=True)
                        acm_ok += 1
                    except RuntimeError as e:
                        status("FAIL", stem, str(e))
                note(f"{acm_ok}/{len(wav_pairs)} ACM written")
    else:
        print_section("WAV → ACM", skipped=True)

    # ── STEP 4: MFA alignment ─────────────────────────────────────────────────
    # In flat layout every line gets MFA + a LIP (floats included, as a safety
    # net for a mis-classified line). In data layout the ACM-only categories —
    # holodisk narration, ambient floats, per-NPC combat barks — are skipped
    # here and in the LIP step: they have no talking head, and forced alignment
    # of a long holodisk read against fragmented text only produces noise.
    head_wav_pairs = wav_pairs
    _acm_only_skip = (
        {p[0] for p in wav_pairs if is_acm_only(p[0])} if layout == "data" else set()
    )

    if "mfa" in run:
        print_section("MFA forced alignment → TextGrid", _step_no("mfa"), n_steps)
        if not head_wav_pairs:
            status("SKIP", "", "no WAV files — run 'wav' first")
        else:
            import tempfile
            os.makedirs(textgriddir, exist_ok=True)

            # Resolve dictionary — merge custom dict once, reuse across all groups
            dict_arg   = mfa_name   # MFA built-in name as fallback
            _merge_tmp = None       # holds TemporaryDirectory when we merge

            if custom_dict_path and os.path.isfile(custom_dict_path):
                if main_dict_path:
                    _merge_tmp = tempfile.TemporaryDirectory(prefix="vock_dict_")
                    merged = os.path.join(_merge_tmp.name, "merged.dict")
                    merge_dictionaries(main_dict_path, custom_dict_path, merged)
                    dict_arg = merged
                    note(f"using custom dictionary: {os.path.basename(custom_dict_path)}")
                else:
                    status("WARN", "",
                           f"custom dictionary found ({custom_dict_path}) but the main "
                           f"MFA dictionary for '{mfa_name}' could not be located — "
                           f"passing '{mfa_name}' to MFA directly")

            # Locked stems keep their existing TextGrid untouched — excluded from
            # the MFA corpus entirely so they can't skew the pooled per-speaker
            # normalization for the rest of their group either.
            alignable_pairs = []
            for item in head_wav_pairs:
                stem = item[0].lower()
                if item[0] in _acm_only_skip:
                    status("SKIP", item[0], "ACM-only (holodisk/float/combat) — no MFA",
                           bulk=True)
                elif stem in mfa_lock:
                    tg_path = os.path.join(textgriddir, item[0] + ".TextGrid")
                    if os.path.isfile(tg_path):
                        status("SKIP", item[0], "locked — existing TextGrid kept", bulk=True)
                    else:
                        status("WARN", item[0],
                               "in mfa_lock but no TextGrid on disk — 'lip' will fail "
                               "for it until you unlock or supply one")
                else:
                    alignable_pairs.append(item)

            # Group head_wav_pairs by NPC tag prefix (e.g. MOR, ARTH, ZAIUS …)
            groups: dict[str, list] = {}
            for item in alignable_pairs:
                prefix = re.sub(r"\d+$", "", item[0].lower())
                groups.setdefault(prefix, []).append(item)

            total_tg      = 0
            failed_groups: list[str] = []

            for prefix, pairs in sorted(groups.items()):
                note(f"[{prefix}] aligning {len(pairs)} file(s)…")
                with tempfile.TemporaryDirectory(prefix=f"vock_{prefix}_") as corpus_dir:
                    for stem, wav_path, txt_path in pairs:
                        shutil.copy2(wav_path, os.path.join(corpus_dir, stem + ".wav"))
                        text = open(txt_path, encoding=lang_enc(args.language)).read()
                        open(os.path.join(corpus_dir, stem + ".txt"), "w",
                             encoding="utf-8").write(text)

                    mfa_tmp_out = os.path.join(corpus_dir, "aligned")
                    os.makedirs(mfa_tmp_out)

                    ok = run_mfa(corpus_dir, mfa_tmp_out, mfa_env, dict_arg, mfa_name)

                    if ok:
                        group_tg = 0
                        for f in os.listdir(mfa_tmp_out):
                            if f.endswith(".TextGrid"):
                                shutil.copyfile(
                                    os.path.join(mfa_tmp_out, f),
                                    os.path.join(textgriddir, f))
                                total_tg += 1
                                group_tg += 1
                        note(f"[{prefix}] {group_tg}/{len(pairs)} TextGrid(s) exported",
                             indent=4)
                    else:
                        failed_groups.append(prefix)
                        status("WARN", f"[{prefix}]",
                               "MFA failed — text approximation will be used for these files")

            if _merge_tmp:
                _merge_tmp.cleanup()

            note(f"{total_tg} TextGrid(s) saved")
            if failed_groups:
                note(f"MFA failed for group(s): {', '.join(failed_groups)}")
            n_unknown = len(report_unknown_words(textgriddir))
    else:
        print_section("MFA forced alignment", skipped=True)

    # ── STEP 5: LIP generation ────────────────────────────────────────────────
    if "lip" in run:
        print_section("Generate LIP files", _step_no("lip"), n_steps)
        if not head_wav_pairs:
            status("SKIP", "", "no WAV files for duration — run 'wav' first")
        else:
            if layout != "data":
                os.makedirs(lipdir, exist_ok=True)
            for stem, wav_path, _txt_path in head_wav_pairs:
                if stem in _acm_only_skip:
                    status("SKIP", stem, "ACM-only (holodisk/float/combat) — no LIP",
                           bulk=True)
                    continue
                lip_path = lip_path_for(stem)
                os.makedirs(os.path.dirname(lip_path), exist_ok=True)
                tg_path  = os.path.join(textgriddir, stem + ".TextGrid")

                try:
                    duration = ffprobe_duration(wav_path)
                except Exception as e:
                    status("FAIL", stem, f"could not read duration: {e}")
                    lip_fail += 1
                    continue

                if os.path.isfile(tg_path):
                    try:
                        events = build_events_from_textgrid(tg_path, phoneme_to_code)
                        write_lip(lip_path, stem, duration, events)
                        status("OK", f"{stem}.lip",
                               f"{duration:.3f}s, {len(events)} events, MFA", bulk=True)
                        lip_ok += 1
                    except Exception as e:
                        status("FAIL", stem, f"TextGrid error ({e})")
                        lip_fail += 1
                else:
                    status("FAIL", stem, "missing TextGrid (MFA failed or was skipped)")
                    lip_fail += 1

            note(f"{lip_ok} LIP generated, {lip_fail} failed")
    else:
        print_section("Generate LIP files", skipped=True)

    # ── STEP 6: Build DAT ────────────────────────────────────────────────────
    if "dat" in run:
        include_acm = ("acm" not in (args.skip or []))
        os.makedirs(os.path.dirname(datfile) or ".", exist_ok=True)

        # Float, combat and holodisk (ACM-only) speech is carried by opt-out
        # overlay DATs, so keep it all out of the main DAT.
        overlay_split = float_stems | combat_stems | acm_only_stems

        def _build_dat(target, entries):
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            if not entries:
                status("SKIP", os.path.basename(target), "no files to pack")
                return
            try:
                write_dat2(target, entries)
                kb = os.path.getsize(target) / 1024
                status("OK", os.path.basename(target),
                       f"{len(entries)} file(s), {kb:.1f} KB  →  {target}")
            except Exception as e:
                status("FAIL", os.path.basename(target), f"DAT creation failed: {e}")

        # ── 6a: main DAT ─────────────────────────────────────────────────────
        print_section(f"Build {os.path.basename(datfile)}", _step_no("dat"), n_steps)
        if layout == "data":
            main_entries = collect_data_tree_entries(
                data_root, exclude_stems=overlay_split,
                exclude_dirs=("sound\\speech\\",)
                             + tuple(f"sound\\{m}\\" for m in sorted(acm_only_msgs)))
        else:
            main_entries = collect_dat_entries(
                msg_paths    = msg_paths,
                acm_dir      = acmdir,
                lip_dir      = lipdir,
                txt_dir      = txtdir,
                include_acm  = include_acm,
                include_msg  = True,
                discover_from = "lip",
                int_dir      = intdir,
                art_dir      = artdir,
            )
        _build_dat(datfile, main_entries)

        # ── 6b: opt-out overlay DATs (floats, combat barks, holodisk) ────────
        for name, stems, target in (
            ("floats",       float_stems,    float_datfile),
            ("combat barks", combat_stems,   combat_datfile),
            ("holodisk",     acm_only_stems, pipboy_datfile),
        ):
            if not stems:
                continue
            print_section(f"Build {os.path.basename(target)}  ({name})")
            if layout == "data":
                entries = _data_overlay_entries(stems)
            else:
                entries = collect_dat_entries(
                    msg_paths     = [],
                    acm_dir       = acmdir,
                    lip_dir       = lipdir,
                    txt_dir       = txtdir,
                    include_acm   = include_acm,
                    only_stems    = stems,
                    include_msg   = False,
                    discover_from = "acm",
                    int_dir       = None,
                    art_dir       = None,
                    sound_dirs    = acm_only_dirs,
                )
            _build_dat(target, entries)
    else:
        print_section("Build DAT", skipped=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    rows: list[tuple[str, str]] = [
        ("Steps", ", ".join(ordered_steps) or "(none)"),
        ("TXT",   f"{len(txt_map)} known"),
        ("WAV",   str(len(wav_pairs))),
        ("ACM",   str(acm_ok) if "acm" in run else "skipped"),
    ]
    if "lip" in run:
        rows.append(("LIP", f"{lip_ok} generated, {lip_fail} failed"))
    else:
        rows.append(("LIP", "skipped"))
    if n_unknown:
        rows.append(("Unknown words", f"{n_unknown}  → unknown.txt"))
    if "dat" in run:
        if os.path.isfile(datfile):
            rows.append((os.path.basename(datfile),
                         f"{_fmt_size(os.path.getsize(datfile) / 1024)}   {datfile}"))
        for stems, target in ((float_stems,    float_datfile),
                              (combat_stems,   combat_datfile),
                              (acm_only_stems, pipboy_datfile)):
            if stems and os.path.isfile(target):
                rows.append((os.path.basename(target),
                             f"{_fmt_size(os.path.getsize(target) / 1024)}   {target}"))
    else:
        rows.append(("DAT", "skipped"))

    print_summary("DONE", rows, duration=time.monotonic() - _start)
    print_problem_recap()
    print()


if __name__ == "__main__":
    main()
