#!/usr/bin/env python3
"""
mfa_verify.py  --  detect and offer to fix MFA batch-alignment casualties.

Usage:
    python3 tools/mfa_verify.py [prefix ...] [options]
    python3 tools/mfa_verify.py                       # check every NPC group
    python3 tools/mfa_verify.py arth                  # just arth
    python3 tools/mfa_verify.py --below 60            # only re-check scores worse than this (default: 85)
    python3 tools/mfa_verify.py --apply               # apply every recommended swap
    python3 tools/mfa_verify.py --apply arth2 lou12   # apply only these specific stems

The story this exists for: MFA's --single_speaker mode pools acoustic
normalization statistics across every file in an NPC's batch. Usually that
helps, but a line whose delivery is an acoustic outlier for that character
can get its alignment corrupted by the pooled stats even though the rest of
the batch aligns fine -- confirmed on 'arth2', which scored terribly when
batched with the other 28 arth lines and aligned perfectly once run alone.

Two audio-only signals were tried to *predict* which lines are at risk
before ever running MFA (overall speaking rate, and within-file pause/
segment dominance) -- both failed to isolate arth2 from lines that turned
out fine, so this tool doesn't try to guess the cause. It checks the
*symptom* instead, using the same confidence scoring as
textgrid_confidence.py, and only recommends a fix when re-aligning a file
alone demonstrably improves its score:

  1. Score every existing TextGrid the normal way (batched result already
     on disk). Floats and stems already in mfa_lock.cfg are skipped --
     floats don't need this, locked stems have already been through this
     process.
  2. For anything below --below (default 85 -- deliberately generous, see
     below), re-align that file alone,
     outside its NPC's batch, using the same dictionary/settings vock.py's
     own mfa step would use.
  3. Score the isolated result too, and compare.
  4. Report both scores side by side with a recommendation. Nothing is
     written to textgrid/ or mfa_lock.cfg at this point -- recommend a
     swap doesn't mean apply it.
  5. Only with --apply does it actually overwrite the TextGrid and append
     the stem to mfa_lock.cfg, either for every recommended stem or just
     the ones you name.

A file that isolates no better than it batched (arth21's case: a real held
vowel, not a batching artifact) is left alone either way -- there's nothing
to swap in.

Configuration comes from vock.cfg, same as vock.py and textgrid_confidence.py.
"""

import argparse
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vock = _load_module("vock_pipeline", _VOCK_DIR / "vock.py")
tc   = _load_module("textgrid_confidence", _SCRIPT_DIR / "textgrid_confidence.py")

WAV_DIR = tc._PROJECT_ROOT / (tc.PATHS.get("wav") or tc._wk + "wav")
MFA_ENV = tc._ini_parser.get("settings", "mfa_env", fallback="aligner")
MFA_LOCK_PATH = tc._PROJECT_ROOT / tc.PATHS.get("mfa_lock", "./mfa_lock.cfg")

DEFAULT_BELOW = 85   # generous on purpose: the re-check itself is cheap and read-only,
                      # so it's safer to over-include than to miss a real case the way
                      # a 60 threshold missed the reproduced arth2 corruption (scored 69)
                      # during testing. SWAP_IMPROVEMENT_THRESHOLD is the real filter.
SWAP_IMPROVEMENT_THRESHOLD = 15   # isolated must beat batched by at least this much to recommend a swap


def resolve_dict_arg(mfa_name: str) -> str:
    """Mirrors vock.py main()'s own dictionary resolution: merge custom into
    main if a custom dictionary exists, else fall back to the MFA name."""
    main_dict_path = vock.find_mfa_dict(mfa_name)
    custom_dict_path = vock.resolve_custom_dict(mfa_name, None)
    if custom_dict_path and Path(custom_dict_path).is_file() and main_dict_path:
        tmp = tempfile.NamedTemporaryFile(suffix=".dict", delete=False)
        tmp.close()
        vock.merge_dictionaries(main_dict_path, custom_dict_path, tmp.name)
        return tmp.name
    return mfa_name


def realign_isolated(stem: str, mfa_name: str, dict_arg: str) -> Path | None:
    """Align stem's wav alone, outside its NPC batch. Returns the path to the
    resulting TextGrid, or None if MFA failed."""
    wav_path = WAV_DIR / f"{stem}.wav"
    txt_path = tc.TXT_DIR / f"{stem}.txt"
    if not wav_path.is_file() or not txt_path.is_file():
        return None

    with tempfile.TemporaryDirectory(prefix=f"mfa_verify_{stem}_") as tmp:
        corpus_dir = Path(tmp) / "corpus"
        out_dir = Path(tmp) / "out"
        corpus_dir.mkdir()
        out_dir.mkdir()
        shutil.copy2(wav_path, corpus_dir / f"{stem}.wav")
        shutil.copy2(txt_path, corpus_dir / f"{stem}.txt")

        ok = vock.run_mfa(str(corpus_dir), str(out_dir), MFA_ENV, dict_arg, mfa_name)
        result_tg = out_dir / f"{stem}.TextGrid"
        if not ok or not result_tg.is_file():
            return None

        # Copy out of the temp dir before it's cleaned up.
        persist_path = MFA_LOCK_PATH.parent / ".mfa_verify_cache" / f"{stem}.TextGrid"
        persist_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result_tg, persist_path)
        return persist_path


def apply_swap(stem: str, isolated_tg_path: Path, batched_score: float, isolated_score: float) -> None:
    dest = tc.TEXTGRID_DIR / f"{stem}.TextGrid"
    shutil.copy2(isolated_tg_path, dest)

    line = (f"{stem}   # auto-verified by mfa_verify.py: isolated {isolated_score:.0f} "
            f"vs batched {batched_score:.0f}\n")
    existing = MFA_LOCK_PATH.read_text(encoding="utf-8") if MFA_LOCK_PATH.is_file() else ""
    if not existing.endswith("\n") and existing:
        existing += "\n"
    MFA_LOCK_PATH.write_text(existing + line, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefixes", nargs="*",
        help="Only check audio tags starting with these prefixes (default: all)")
    parser.add_argument("--language", default=tc._config["language"],
        choices=list(tc.LANGUAGE_CONFIG.keys()))
    parser.add_argument("--below", type=float, default=DEFAULT_BELOW, metavar="N",
        help=f"Re-check stems scoring below N (default: {DEFAULT_BELOW})")
    parser.add_argument("--apply", nargs="*", default=None, metavar="STEM",
        help="Apply recommended swaps. With no names, applies every "
             "recommended stem; with names, applies only those.")
    args = parser.parse_args()

    mfa_name = tc.LANGUAGE_CONFIG[args.language]
    word_phones = tc.load_word_phone_counts(mfa_name)
    float_map = tc.load_float_ranges(tc._PROJECT_ROOT / tc.PATHS.get("float_filter", "")) \
        if tc.PATHS.get("float_filter") else {}
    locked = vock.load_mfa_lock(str(MFA_LOCK_PATH)) if MFA_LOCK_PATH.is_file() else set()

    stems = sorted(p.stem for p in tc.TEXTGRID_DIR.glob("*.TextGrid"))
    if args.prefixes:
        prefixes = tuple(p.lower() for p in args.prefixes)
        stems = [s for s in stems if s.lower().startswith(prefixes)]

    candidates = []
    for stem in stems:
        if stem.lower() in locked:
            continue
        if tc.is_float_line(stem, float_map):
            continue
        r = tc.score_file(stem, word_phones, float_map)
        if r and r["confidence"] < args.below:
            candidates.append((stem, r["confidence"]))

    if not candidates:
        print(f"  Nothing scored below {args.below:.0f} (excluding floats and already-locked stems).")
        return

    print(f"  {len(candidates)} stem(s) scoring below {args.below:.0f} -- re-aligning each in isolation…\n")

    dict_arg = resolve_dict_arg(mfa_name)
    try:
        results = []
        for stem, batched_score in candidates:
            print(f"  [{stem}] aligning alone…", end=" ", flush=True)
            iso_path = realign_isolated(stem, mfa_name, dict_arg)
            if iso_path is None:
                print("MFA failed, skipping")
                continue
            iso_result = tc.score_file(stem, word_phones, float_map, tg_path=iso_path)
            isolated_score = iso_result["confidence"] if iso_result else 0
            delta = isolated_score - batched_score
            recommend = delta >= SWAP_IMPROVEMENT_THRESHOLD
            print(f"batched={batched_score:.0f} isolated={isolated_score:.0f} "
                  f"({'+' if delta >= 0 else ''}{delta:.0f})  "
                  f"{'-> recommend swap' if recommend else '-> leave as is'}")
            results.append({"stem": stem, "batched": batched_score, "isolated": isolated_score,
                             "delta": delta, "recommend": recommend, "iso_path": iso_path})

        print(f"\n  {'stem':<12} {'batched':>7}  {'isolated':>8}  {'delta':>6}  recommendation")
        print(f"  {'-'*12} {'-'*7}  {'-'*8}  {'-'*6}  {'-'*30}")
        for r in results:
            rec = "SWAP" if r["recommend"] else "leave as is"
            print(f"  {r['stem']:<12} {r['batched']:>6.0f}  {r['isolated']:>7.0f}  "
                  f"{r['delta']:>+5.0f}  {rec}")

        n_recommend = sum(1 for r in results if r["recommend"])
        print(f"\n  {n_recommend}/{len(results)} recommended for a swap.")

        if args.apply is None:
            print("  Nothing applied -- pass --apply to write recommended swaps "
                  "(or --apply <stem ...> to cherry-pick).")
            return

        targets = ([r["stem"] for r in results if r["recommend"]] if not args.apply
                   else args.apply)
        applied = 0
        for r in results:
            if r["stem"] not in targets:
                continue
            if not r["recommend"] and r["stem"] in (args.apply or []):
                print(f"  [{r['stem']}] applying anyway despite no recommendation (explicitly named)")
            apply_swap(r["stem"], r["iso_path"], r["batched"], r["isolated"])
            print(f"  [{r['stem']}] TextGrid replaced, added to {MFA_LOCK_PATH.name}")
            applied += 1

        print(f"\n  {applied} stem(s) applied.")
    finally:
        # resolve_dict_arg() may have created a temp merged dictionary --
        # dict_arg equals mfa_name itself (not a file) when it didn't.
        if dict_arg != mfa_name and Path(dict_arg).is_file():
            Path(dict_arg).unlink()
        cache_dir = MFA_LOCK_PATH.parent / ".mfa_verify_cache"
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)


if __name__ == "__main__":
    main()
