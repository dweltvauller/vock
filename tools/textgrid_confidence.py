#!/usr/bin/env python3
"""
textgrid_confidence.py  --  heuristic confidence scoring for MFA TextGrid alignments.

Usage:
    python3 tools/textgrid_confidence.py [prefix ...] [options]
    python3 tools/textgrid_confidence.py                 # scan every TextGrid
    python3 tools/textgrid_confidence.py lou skeet jenny  # scan just these NPCs
    python3 tools/textgrid_confidence.py --below 60       # only show suspicious ones
    python3 tools/textgrid_confidence.py --csv report.csv

This is a triage tool, not a verdict. It flags TextGrids whose phone-level
alignment *looks* wrong from the geometry alone, so you know which lines are
worth opening in LIP Editor / Praat before deciding anything needs fixing.
A low score means "go look at this", not "this is broken" -- a character
who draws a word out on purpose (a held "Hellooo") will also score low here,
same as a real MFA failure. Only your ears/eyes settle that.

Two independent signals feed the score, taking whichever is more damning:

  1. Coverage -- how much of the file a single phoneme interval eats up,
     both in absolute seconds and as a percentage of the file. A single
     phoneme spanning the entire line scores near 0. A normal held vowel
     of ~0.3-0.5s barely moves the score. The percentage side scales its
     floor up for short files (below ~2s) -- "Yes." is so short that even
     a completely normal vowel is 40-50% of the clip, and holding that to
     the same bar as a ten-second paragraph flagged short, ordinary lines
     for no reason.

  2. Completeness -- how many real phone intervals the TextGrid actually
     has versus how many the line's own text should produce, estimated by
     summing each word's phone count from the MFA + custom dictionaries.
     A TextGrid with far fewer intervals than its transcript implies is a
     sign MFA collapsed most of the line into one blob.

Floats (float_filter.cfg) get gentler scoring on both signals, and are
excluded from the default report entirely -- see "Floats" below.

Configuration comes from vock.cfg, same as vock.py: PATHS["textgrid"],
PATHS["txt"], PATHS["float_filter"], and the dictionary/language settings
used to size expected phone counts per word.

## Floats

A float's LIP file is a safety net vock.py generates in case the line was
*wrongly* classified as a float -- when classification is correct, floats
play as ACM-only overhead text with no talking head on screen, so their
LIP file is never actually read by the game. A bad alignment there is
usually inert, not a visible bug, so:

  - Floats are short by nature (often one word: a grunt, a yelp, "Ahhh!"),
    so a single phoneme legitimately covering most of the clip is normal,
    not a red flag -- the percentage-of-file penalty is heavily damped for
    them, and the absolute-duration floor is raised (interjections can be
    held a lot longer than a normal syllable without it being a bug).
  - A transcript that's purely a stage direction in parentheses -- (grunt),
    (snore), (chuckle) -- isn't actually spoken text, so word-count-based
    completeness scoring is skipped for it entirely (there's nothing to
    compare the phone count against).
  - They're left out of the default report so they don't drown out the
    talking-head lines that actually matter visually. Pass --include-floats
    to see them scored and flagged inline, or --floats-only to see just them
    (e.g. to sanity-check classification itself).
"""

import argparse
import configparser
import csv
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/

_ini_parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini_parser.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

_config = {
    "project_root": _ini_parser.get("general", "project_root", fallback="./"),
    "language":     _ini_parser.get("general", "language", fallback="arpabet"),
    "layout":       _ini_parser.get("general", "layout", fallback="flat").strip().lower(),
    "paths":        dict(_ini_parser["paths"]),
}
PATHS = _config["paths"]

# Every paths entry is resolved against config["project_root"] (default "./"),
# mirroring vock.py's resolve_path() -- so pointing project_root at another
# project's folder retargets this tool too, instead of always reading vock/.
_PROJECT_ROOT = (_VOCK_DIR / _config.get("project_root", "./")).resolve()

# textgrid defaults to ./textgrid (flat layout) or ./work/textgrid (data
# layout), mirroring vock.py -- a cfg key overrides either. See vock.cfg's
# [paths] comment for why it's commented out by default.
_wk = "./work/" if _config["layout"] == "data" else "./"
TEXTGRID_DIR = _PROJECT_ROOT / (PATHS.get("textgrid") or _wk + "textgrid")
TXT_DIR      = _PROJECT_ROOT / PATHS["txt"]

LANGUAGE_CONFIG = {
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
LANG_ENCODING = {
    "arpabet": "cp1252", "english": "cp1252", "spanish": "cp1252",
    "french": "cp1252", "german": "cp1252", "italian": "cp1252",
    "hungarian": "cp1252", "portuguese": "cp1252",
    "polish": "cp1250", "czech": "cp1250", "russian": "cp1251",
}

MFA_DICT_SEARCH_DIRS = [
    os.path.expanduser("~/Documents/MFA/pretrained_models/dictionary"),
    os.path.expanduser("~/.local/share/montreal-forced-aligner/pretrained_models/dictionary"),
]

# A generous per-phone ceiling before a hold counts as suspicious on its own,
# and how much of the *file* a single phoneme can reasonably occupy.
ABS_DURATION_FLOOR_S = 0.5
PCT_DURATION_FLOOR   = 10.0     # percent, for files at/above SHORT_FILE_REFERENCE_S
FALLBACK_PHONES_PER_WORD = 3.5  # used for words missing from every dictionary

# A flat percentage floor punishes short lines for the wrong reason: "Yes."
# at 0.4s has so little total duration that even a completely normal vowel
# is 40-50% of the file, without anything being wrong. The floor scales up
# as the file gets shorter instead, capped so it never goes fully blind.
SHORT_FILE_REFERENCE_S = 2.0    # at/above this duration, the flat floor applies unscaled
PCT_FLOOR_CAP = 60.0            # percent


def pct_floor_for(total_dur: float) -> float:
    if total_dur >= SHORT_FILE_REFERENCE_S:
        return PCT_DURATION_FLOOR
    return min(PCT_FLOOR_CAP, PCT_DURATION_FLOOR * (SHORT_FILE_REFERENCE_S / max(total_dur, 0.1)))

# Floats are short by nature (often a single interjection) -- score them
# more leniently so normal grunts/yelps don't drown out real problems.
FLOAT_ABS_DURATION_FLOOR_S = 1.5
FLOAT_PCT_PENALTY_WEIGHT   = 0.3


# ─── Float detection (mirrors vock.py's load_float_ranges / is_float_line) ────

def load_float_ranges(float_file) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {}
    if not float_file or not float_file.is_file():
        return result
    with open(float_file, encoding="utf-8") as fh:
        for raw in fh:
            token = raw.split("#", 1)[0].strip()
            if not token:
                continue
            parts = token.split(None, 1)
            if len(parts) < 2:
                continue
            prefix = parts[0].lower()
            for chunk in parts[1].split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    if "-" in chunk:
                        lo, hi = chunk.split("-", 1)
                        result.setdefault(prefix, []).append((int(lo.strip()), int(hi.strip())))
                    else:
                        n = int(chunk)
                        result.setdefault(prefix, []).append((n, n))
                except ValueError:
                    continue
    return result


def is_float_line(tag: str, float_map: dict) -> bool:
    if not float_map:
        return False
    tag_lower = tag.lower()
    for prefix in sorted(float_map, key=len, reverse=True):
        if tag_lower.startswith(prefix):
            suffix = tag_lower[len(prefix):]
            if not suffix.isdigit():
                break
            tag_num = int(suffix)
            for lo, hi in float_map[prefix]:
                if lo <= tag_num <= hi:
                    return True
            break
    return False


def is_nonverbal_cue(text: str) -> bool:
    """True for a transcript that's purely a stage direction, e.g. '(grunt)',
    '(snore)' -- not actually spoken text, so there's nothing to align."""
    stripped = text.strip()
    return bool(stripped) and stripped.startswith("(") and stripped.endswith((")", ").", ")!"))


# ─── TextGrid parsing (mirrors vock.py's regexes) ──────────────────────────────

def parse_tier(content: str, tier_name: str) -> list[tuple[float, float, str]]:
    m = re.search(rf'name\s*=\s*"{tier_name}s?"(.*?)(?=(?:item\s*\[|\Z))',
                   content, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    tier_text = m.group(1)
    # Anchored to "intervals [N]:" so the tier's own header xmin/xmax (which
    # precedes the first interval) can never be swept into interval [1] by a
    # loose xmin/xmax/text scan -- that would falsely report interval [1]'s
    # duration as the whole file whenever it isn't silence.
    intervals = re.findall(
        r'intervals\s*\[\d+\]:\s*'
        r'xmin\s*=\s*([\d.]+)\s*'
        r'xmax\s*=\s*([\d.]+)\s*'
        r'text\s*=\s*"([^"]*)"',
        tier_text, re.DOTALL)
    return [(float(xmin), float(xmax), label) for xmin, xmax, label in intervals]


def file_duration(content: str) -> float:
    m = re.search(r'^xmax\s*=\s*([\d.]+)', content, re.MULTILINE)
    return float(m.group(1)) if m else 0.0


# ─── Dictionary loading (phones-per-word only) ─────────────────────────────────

_FLOAT_RE = re.compile(r"^\d+(\.\d+)?$")

def _phones_from_pron_line(parts: list[str]) -> list[str]:
    """Strip leading probability columns (MFA dict format) and return phones."""
    i = 0
    while i < len(parts) and _FLOAT_RE.match(parts[i]):
        i += 1
    return parts[i:]


def load_word_phone_counts(mfa_name: str) -> dict[str, int]:
    """word -> phone count, first pronunciation wins, custom dict overrides."""
    counts: dict[str, int] = {}

    main_path = None
    for d in MFA_DICT_SEARCH_DIRS:
        candidate = os.path.join(d, f"{mfa_name}.dict")
        if os.path.isfile(candidate):
            main_path = candidate
            break

    def _load(path: str, overwrite: bool):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                word = re.sub(r"\(\d+\)$", "", parts[0].lower())
                phones = _phones_from_pron_line(parts[1:])
                if not phones:
                    continue
                if overwrite or word not in counts:
                    counts[word] = len(phones)

    if main_path:
        _load(main_path, overwrite=False)

    custom_path = _PROJECT_ROOT.parent / "vock" / "dictionaries" / f"custom.{mfa_name}.dict"
    if not custom_path.is_file():
        custom_path = _VOCK_DIR / "dictionaries" / f"custom.{mfa_name}.dict"
    if custom_path.is_file():
        _load(str(custom_path), overwrite=True)

    return counts


_WORD_RE = re.compile(r"[A-Za-z']+")

# Common English clitics MFA's own text normalizer splits off a word
# automatically (e.g. "wright'll" -> "wright" + "'ll"), longest first so
# "'ve" isn't shadowed by a shorter false match. Each is expected to be its
# own dictionary entry -- confirmed present in the MFA english_us_arpa dict
# ('s, 'd, 'll, 're, 've) or reasonable to assume for the rest.
_CLITICS = ["'ll", "'ve", "'re", "'em", "'s", "'d", "'m", "'t"]

def _lookup_word(w: str, word_phones: dict[str, int]) -> int | None:
    """Resolve one word's phone count, trying the same normalizations MFA's
    own text pipeline would apply before giving up on it. Returns None only
    if nothing plausible is found."""
    if w in word_phones:
        return word_phones[w]
    if f"({w})" in word_phones:               # inline non-verbal cue, e.g. "(mmhmhm)"
        return word_phones[f"({w})"]
    if w.startswith("'") and w[1:] in word_phones:   # leading elision: 'tis, 'em
        return word_phones[w[1:]]
    for clitic in _CLITICS:                    # trailing clitic: wright'll, mom's
        if w.endswith(clitic) and len(w) > len(clitic):
            stem, suffix = w[:-len(clitic)], clitic
            if stem in word_phones and suffix in word_phones:
                return word_phones[stem] + word_phones[suffix]
    # MFA's own text normalizer strips a bare trailing apostrophe as
    # punctuation before dictionary lookup -- and the base MFA dictionary
    # already carries plenty of common g-dropped spellings this way
    # (puttin', workin', jesus' -> puttin, workin, jesus are literal
    # entries), so this covers a lot of ground without needing a custom
    # dictionary entry at all.
    if w.endswith("'") and w[:-1] in word_phones:
        return word_phones[w[:-1]]
    return None


def expected_phone_count(text: str, word_phones: dict[str, int]) -> tuple[int, int]:
    """Returns (expected_phone_count, oov_word_count) for a line of text."""
    total, oov = 0, 0
    for raw in _WORD_RE.findall(text):
        w = raw.lower()
        if not w:
            continue
        n = _lookup_word(w, word_phones)
        if n is None:
            n = FALLBACK_PHONES_PER_WORD
            oov += 1
        total += n
    return round(total), oov


# ─── Scoring ────────────────────────────────────────────────────────────────

def score_file(stem: str, word_phones: dict[str, int], float_map: dict,
               tg_path: Path | None = None) -> dict | None:
    """Score stem's TextGrid. Defaults to TEXTGRID_DIR/<stem>.TextGrid; pass
    tg_path to score a TextGrid living elsewhere (e.g. a candidate isolated
    re-alignment that hasn't been committed anywhere yet)."""
    if tg_path is None:
        tg_path = TEXTGRID_DIR / f"{stem}.TextGrid"
    if not tg_path.is_file():
        return None
    content = tg_path.read_text(encoding="utf-8", errors="replace")
    is_float = is_float_line(stem, float_map)

    total_dur = file_duration(content)
    phones = [(xmin, xmax, label) for xmin, xmax, label in parse_tier(content, "phone")
              if label.strip()]
    if total_dur <= 0 or not phones:
        return {"stem": stem, "confidence": 0, "is_float": is_float,
                "note": "empty/unparseable TextGrid",
                "total_dur": total_dur, "actual_phones": len(phones),
                "expected_phones": None, "longest_dur": 0.0, "longest_pct": 0.0,
                "longest_label": ""}

    longest_dur, longest_label = max(
        ((xmax - xmin, label) for xmin, xmax, label in phones), key=lambda t: t[0])
    longest_pct = longest_dur / total_dur * 100

    abs_floor = FLOAT_ABS_DURATION_FLOOR_S if is_float else ABS_DURATION_FLOOR_S
    penalty_abs = _clamp((longest_dur - abs_floor) * 25, 0, 70)
    penalty_pct = _clamp((longest_pct - pct_floor_for(total_dur)) * 1.0, 0, 70)
    if is_float:
        penalty_pct *= FLOAT_PCT_PENALTY_WEIGHT
    coverage_penalty = max(penalty_abs, penalty_pct)

    txt_path = TXT_DIR / f"{stem}.txt"
    expected, oov = (None, 0)
    completeness_penalty = 0.0
    note = ""
    if txt_path.is_file():
        text = txt_path.read_text(encoding="cp1252", errors="replace")
        if is_nonverbal_cue(text):
            note = "non-verbal cue, completeness skipped"
        else:
            expected, oov = expected_phone_count(text, word_phones)
            if expected > 0:
                ratio = len(phones) / expected
                if ratio < 1:
                    completeness_penalty = _clamp((1 - ratio) * 60, 0, 60)

    total_penalty = min(95, coverage_penalty + completeness_penalty * 0.6)
    confidence = round(100 - total_penalty)

    return {
        "stem": stem, "confidence": confidence, "is_float": is_float,
        "total_dur": total_dur, "actual_phones": len(phones),
        "expected_phones": expected, "oov_words": oov,
        "longest_dur": longest_dur, "longest_pct": longest_pct,
        "longest_label": longest_label, "note": note,
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefixes", nargs="*",
        help="Only scan audio tags starting with these prefixes (default: all)")
    parser.add_argument("--language", default=_config["language"],
        choices=list(LANGUAGE_CONFIG.keys()),
        help=f"Dictionary/phoneme set for expected-phone-count estimation "
             f"(default from vock.cfg: {_config['language']})")
    parser.add_argument("--below", type=int, default=None, metavar="N",
        help="Only show files scoring below N (0-100)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
        help="Only show the N worst-scoring files")
    parser.add_argument("--csv", metavar="PATH",
        help="Also write the full report to this CSV path")
    parser.add_argument("--include-floats", action="store_true",
        help="Include float lines in the report (excluded by default -- "
             "see 'Floats' in --help)")
    parser.add_argument("--floats-only", action="store_true",
        help="Show only float lines (e.g. to sanity-check float classification)")
    args = parser.parse_args()

    if not TEXTGRID_DIR.is_dir():
        sys.exit(f"[ERROR] TextGrid folder not found: {TEXTGRID_DIR}")

    mfa_name = LANGUAGE_CONFIG[args.language]
    word_phones = load_word_phone_counts(mfa_name)
    if not word_phones:
        print(f"  [warn] no dictionary found for '{mfa_name}' -- completeness "
              f"scoring will fall back to a flat {FALLBACK_PHONES_PER_WORD} "
              f"phones/word estimate for every word", file=sys.stderr)

    float_filter_path = PATHS.get("float_filter")
    float_map = load_float_ranges(_PROJECT_ROOT / float_filter_path) if float_filter_path else {}

    stems = sorted(p.stem for p in TEXTGRID_DIR.glob("*.TextGrid"))
    if args.prefixes:
        prefixes = tuple(p.lower() for p in args.prefixes)
        stems = [s for s in stems if s.lower().startswith(prefixes)]
    if not stems:
        sys.exit("  No matching TextGrid files found.")

    results = [r for s in stems if (r := score_file(s, word_phones, float_map))]

    n_floats = sum(1 for r in results if r["is_float"])
    if args.floats_only:
        results = [r for r in results if r["is_float"]]
    elif not args.include_floats:
        results = [r for r in results if not r["is_float"]]

    results.sort(key=lambda r: r["confidence"])

    if args.below is not None:
        results = [r for r in results if r["confidence"] < args.below]
    if args.limit is not None:
        results = results[:args.limit]

    if not results:
        print("  Nothing matched the given filters.")
        return

    print(f"  {'stem':<12} {'conf':>4}  {'dur':>7}  {'phones':>7}  {'longest':>16}  note")
    print(f"  {'-'*12} {'-'*4}  {'-'*7}  {'-'*7}  {'-'*16}  {'-'*30}")
    for r in results:
        tag = "[float] " if r["is_float"] else ""
        if r["note"] and r["actual_phones"] == 0:
            print(f"  {r['stem']:<12} {r['confidence']:>4}  {'':>7}  {'':>7}  {'':>16}  {tag}{r['note']}")
            continue
        phones_str = f"{r['actual_phones']}"
        if r["expected_phones"] is not None:
            phones_str += f"/{r['expected_phones']}"
        longest_str = f"{r['longest_label']} {r['longest_dur']:.2f}s ({r['longest_pct']:.0f}%)"
        note_bits = [tag.strip()] if tag else []
        if r.get("oov_words"):
            note_bits.append(f"{r['oov_words']} OOV word(s)")
        if r["note"]:
            note_bits.append(r["note"])
        print(f"  {r['stem']:<12} {r['confidence']:>4}  {r['total_dur']:>6.2f}s  "
              f"{phones_str:>7}  {longest_str:>16}  {', '.join(note_bits)}")

    print(f"\n  {len(results)} file(s) shown. Lower confidence = more worth a visual/audio check.")
    if not args.include_floats and not args.floats_only and n_floats:
        print(f"  ({n_floats} float line(s) excluded -- pass --include-floats or --floats-only to see them)")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["stem", "confidence", "is_float", "total_dur", "actual_phones",
                              "expected_phones", "oov_words", "longest_label",
                              "longest_dur", "longest_pct", "note"])
            for r in results:
                writer.writerow([r["stem"], r["confidence"], r["is_float"], r.get("total_dur"),
                                  r.get("actual_phones"), r.get("expected_phones"),
                                  r.get("oov_words"), r.get("longest_label"),
                                  r.get("longest_dur"), r.get("longest_pct"), r["note"]])
        print(f"  CSV written to {args.csv}")


if __name__ == "__main__":
    main()
