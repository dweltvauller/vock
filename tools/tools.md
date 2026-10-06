# Tools

Standalone utility scripts for the VOCK project.

---

## dict_lookup.py

Interactive MFA pronunciation dictionary lookup. Type a word, get its ARPA/IPA transcription(s). If a word isn't found, suggests close matches via fuzzy lookup.

**Dependencies:** None (stdlib only)

**Usage:**
```
python3 tools/dict_lookup.py [dict_name]
```

`dict_name` defaults to `english_us_arpa`. The `.dict` extension is optional.

**Where it looks for dictionaries:**
1. MFA system folders:
   - `~/Documents/MFA/pretrained_models/dictionary/`
   - `~/.local/share/montreal-forced-aligner/pretrained_models/dictionary/`
2. Project custom dictionaries: `vock/dictionaries/custom.<dict_name>.dict`

Custom entries take priority over MFA entries for any word they define.

---

## msg_localize.py

This tool is under development.

Reads audio tags from the source-language MSG files (set by `language` in `vock.cfg`), injects them into matching foreign-language MSG files from an RPU repo, then rebuilds `vock.dat` with the tagged foreign MSGs added.

**Dependencies:** None (stdlib only)

**Configuration:** Defaults for source language and all paths are read from `vock.cfg` (`[general] language` and `[paths]`). `PATHS["rpu_text"]` (default `../rpu/data/text`) is resolved against `vock.cfg`'s own folder rather than `project_root`, since the RPU repo is a sibling of `vock/` itself, not part of whichever project `project_root` points at.

**Expected folder layout** (relative to the `vock/` project root):
```
<parent>/
  vock/          ← this repo
    msg/         ← tagged source-language MSGs (source of truth for audio tags)
    dat/
      vock.dat   ← source DAT
    loc/         ← output: rebuilt DAT and tagged foreign MSGs (created on first run)
  rpu/           ← RPU repo (sibling of vock)
    data/text/
      german/dialog/
      french/dialog/
      ...
```

**Usage:**
```
python3 tools/msg_localize.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--msgdir PATH` | `vock/msg` (from `PATHS["msg"]`) | Tagged source-language MSG folder |
| `--rpu-text PATH` | `../rpu/data/text` (from `PATHS["rpu_text"]`) | RPU data/text folder |
| `--tagged PATH` | `vock/loc/tagged` (from `PATHS["loc"]`) | Output folder for injected foreign MSGs |
| `--dat-src PATH` | `vock/dat` (from `PATHS["dat"]`) | Source DAT folder |
| `--dat-out PATH` | `vock/loc` (from `PATHS["loc"]`) | Output folder for rebuilt DATs |
| `--dat-files FILE ...` | `vock.dat` (from `PATHS["dat"]`) | DAT filenames to rebuild |
| `--encoding ENC` | `cp1252` | Fallback encoding for MSG files |
| `--langs LANG ...` | all non-source languages | Languages to process (9 supported: english, german, french, spanish, italian, polish, russian, czech, hungarian) |
| `--dry-run` | — | Preview changes without writing |
| `--no-dat` | — | Tag MSGs but skip DAT rebuild |

---

## dialogue_sim.py

This tool is under development.

Point this tool to a msg and ssl file, and it will let you simulate the dialogue with that particular NPC.

---

## textgrid_confidence.py

Heuristic confidence scoring for MFA TextGrid alignments -- a triage tool, not a verdict. Flags TextGrids whose phone-level alignment *looks* wrong from the geometry alone (a phoneme holding an outsized share of the file, or far fewer phone intervals than the transcript should produce), so you know which lines are worth a visual/audio check in LIP Editor before deciding anything needs fixing. A low score means "go look at this," not "this is broken" -- a character drawing a word out on purpose scores low here too. Written after `arth2` (and a batch-alignment bug affecting some other NPCs) turned out to need this kind of scan; see the tool's own `--help` for the full method.

**Dependencies:** None (stdlib only)

**Configuration:** Read from `vock.cfg`, same as the main pipeline: `PATHS["textgrid"]`, `PATHS["txt"]`, `PATHS["float_filter"]`, and `[general] language` (picks which MFA dictionary sizes expected phone counts per word).

**Short lines:** the percentage-of-file coverage penalty scales its floor up for files under ~2s, since a flat percentage bar punishes short lines for the wrong reason -- "Yes." or "I'm Chad." is so brief that even a completely normal vowel is 40-50% of the clip. Confirmed against real visual checks (`chad4` moved 84 -> 92 after the fix, matching "moves his lips fine" feedback); this applies to every short line, not just floats.

**Floats:** excluded from the report by default -- a float's LIP file only matters if the line was *wrongly* classified as a float (correctly-classified floats play as ACM-only overhead text, so their LIP is never read). Floats also get gentler scoring on both signals when shown, since a single interjection naturally dominates a short clip. Pass `--include-floats` to fold them into the normal report, or `--floats-only` to see just them.

**Usage:**
```
python3 tools/textgrid_confidence.py [prefix ...] [options]
python3 tools/textgrid_confidence.py                 # scan every TextGrid
python3 tools/textgrid_confidence.py lou skeet jenny  # scan just these NPCs
python3 tools/textgrid_confidence.py --below 60       # only show suspicious ones
python3 tools/textgrid_confidence.py --csv report.csv
```

| Option | Default | Description |
|---|---|---|
| `prefixes` | all | Only scan audio tags starting with these prefixes |
| `--language LANG` | from `vock.cfg` | Dictionary/phoneme set for expected-phone-count estimation |
| `--below N` | — | Only show files scoring below N (0-100) |
| `--limit N` | — | Only show the N worst-scoring files |
| `--csv PATH` | — | Also write the full report to this CSV path |
| `--include-floats` | off | Fold float lines into the report |
| `--floats-only` | off | Show only float lines (e.g. to sanity-check float classification) |

---

## audio_processing_check.py

Audits source audio for consistent processing -- written for a corpus where noise floor reduction, a noise gate, a click filter, and ~0.2s of leading/trailing silence padding were applied by hand to some files and not others, over time. Measures each file's leading and trailing edge independently (silence duration vs. a target, noise floor dB within that silence window, and a heuristic count of isolated click transients), purely from the audio itself -- no before/after reference needed. A fifth column, `floor_dB`, reports the noise floor across the *whole file* (median dB of every quiet window, not just the two edges), so a noisy mid-line pause shows up even when both edges are clean -- useful since the edge columns are specifically about whether edge processing was applied, not the recording's overall background noise. None of the numbers say a file is "wrong" on their own; they say whether it looks like it went through the same processing as the rest of the corpus. Silence duration is the objective one (you set an exact target); floor and click count are comparative -- sort by them and look for the natural break between already-edited files and the rest. See the tool's own `--help` for the full method, including why click counts are the least trustworthy of the three.

**Dependencies:** `numpy`, `ffmpeg` (decodes any format ffmpeg reads, same as vock.py's own `wav` step)

**Configuration:** Read from `vock.cfg`: `PATHS["wav"]` (default) or `PATHS["audio"]` (`--source audio`).

**Source folder matters:** defaults to `wav/` (post -16 LUFS normalization) rather than `audio/`, because the absolute dB threshold that separates "silence" from "speech" is only meaningful once every file has been brought to a comparable loudness -- a quiet take in the raw `audio/` folder can otherwise read as silent even when it's genuine speech. Padding duration itself is unaffected by which folder you pick (loudness normalization doesn't add or remove silence), but the floor/click readings are far more comparable across files in `wav/`.

**Known limitations, found by validating against a batch with a known processing history:**
- Click detection skips a ~60ms margin right at the speech boundary before scanning -- the first stretch of "silence" right after speech stops is a natural decay/ring-down tail (consonant release, room reverb), not true silence, and without the margin it reads as clicks on *every* file, worst on the cleanest ones. Even with the fix, treat click count as exploratory: a fully-processed reference batch still scored higher than an untouched one on this signal, so it isn't fully trusted yet.
- The `src_format` column exists because MP3 encoders commonly zero-pad the start of a file (encoder priming delay) regardless of any noise gate -- a chunk of files reading as exact digital silence on the leading edge turned out to just be MP3s, not evidence of editing. Cross-check against format before reading a digital-silence leading edge as "this got gated."
- Silence duration remains the one fully-trustworthy signal here -- it's a direct, objective measurement against the exact target you gave, and every spot-check against real LIP Editor playback (`lou12`, `keith10`) confirmed the numbers it reported.

**Usage:**
```
python3 tools/audio_processing_check.py [prefix ...] [options]
python3 tools/audio_processing_check.py                      # scan every audio file
python3 tools/audio_processing_check.py lou skeet             # scan just these NPCs
python3 tools/audio_processing_check.py --sort floor          # worst noise floor first
python3 tools/audio_processing_check.py --below 0.08          # only files well under target
python3 tools/audio_processing_check.py --csv report.csv
```

| Option | Default | Description |
|---|---|---|
| `prefixes` | all | Only scan audio tags starting with these prefixes |
| `--source {wav,audio}` | `wav` | Which folder to scan |
| `--threshold DB` | `-35.0` | dB level above which a window counts as speech, not silence |
| `--target SECONDS` | `0.2` | Target leading/trailing silence duration (short end) |
| `--max-silence SECONDS` | `0.5` | Silence at or above this is flagged as noticeably long (`^`) -- long enough to read as the game lagging |
| `--sort {lead,trail,floor,file-floor,clicks}` | `trail` | Sort key -- `floor` is worst edge floor, `file-floor` is worst whole-file floor |
| `--below SECONDS` | — | Only show files whose leading OR trailing silence is below N seconds |
| `--above SECONDS` | — | Only show files whose leading OR trailing silence is at or above N seconds |
| `--limit N` | — | Only show the first N rows after sorting |
| `--csv PATH` | — | Also write the full report to this CSV path |

---

## mfa_verify.py

Detects and offers to fix MFA batch-alignment casualties like `arth2` -- a line whose delivery is an acoustic outlier for its NPC can get its alignment corrupted by `--single_speaker`'s pooled normalization stats even though the rest of the batch aligns fine. Two audio-only signals were tried to *predict* which lines are at risk before ever running MFA (overall speaking rate, within-file pause/segment dominance); both failed to isolate `arth2` from lines that turned out fine (one even flagged `arth21` -- a confirmed non-bug -- as the single biggest outlier in the batch). So this tool checks the *symptom* instead: it scores every existing TextGrid with the same logic as `textgrid_confidence.py`, and only recommends a fix when re-aligning a flagged file *alone* demonstrably improves its score. Nothing is written to `textgrid/` or `mfa_lock.cfg` until you pass `--apply`.

**Dependencies:** None beyond what `vock.py` and `textgrid_confidence.py` already need (it imports both directly rather than duplicating their logic)

**Configuration:** Read from `vock.cfg`, same as the tools above, plus `[settings] mfa_env` (needed to actually invoke MFA for the isolated re-alignments).

**The default `--below` threshold is 85, not something tighter like 60** -- found by testing: the reproduced `arth2` corruption scored 69, which a 60 threshold would have missed entirely. The re-check itself is cheap and read-only (nothing is written until `--apply`), so it's safer to over-include candidates here and let `SWAP_IMPROVEMENT_THRESHOLD` (a file must score at least 15 points better isolated than batched) do the real filtering -- a fine line that gets re-checked unnecessarily just reports "leave as is" and costs a bit of runtime, not correctness.

**Usage:**
```
python3 tools/mfa_verify.py [prefix ...] [options]
python3 tools/mfa_verify.py                       # check every NPC group
python3 tools/mfa_verify.py arth                  # just arth
python3 tools/mfa_verify.py --below 60            # only re-check scores worse than this
python3 tools/mfa_verify.py --apply               # apply every recommended swap
python3 tools/mfa_verify.py --apply arth2 lou12   # apply only these specific stems
```

| Option | Default | Description |
|---|---|---|
| `prefixes` | all | Only check audio tags starting with these prefixes |
| `--language LANG` | from `vock.cfg` | Dictionary/phoneme set, same as the main pipeline |
| `--below N` | `85` | Re-check stems scoring below N |
| `--apply [STEM ...]` | off | Apply swaps: no names = every recommended stem, names = only those (even if not recommended, with a warning) |

Verified end-to-end during development by deliberately reproducing the `arth2` corruption (temporarily unlocking it and re-running the batched `mfa` step) and confirming the tool detected it (batched 69 -> isolated 100), recommended a swap, and -- after `--apply` -- wrote a TextGrid byte-identical to the original hand-fixed version.
---

## float_scan.py

Cross-checks `float_filter.cfg` against how each script actually uses its lines. A tag in `float_filter.cfg` gets no TextGrid and no LIP. If the same MSG line is also a dialogue reply (`Reply` / `NMessage` / `gSay_*`) under a talking head, the engine takes the lip-sync path, finds no `.lip`, and plays nothing. This tool finds those lines before release.

**Dependencies:** None beyond `vock.py` (it imports `load_ranges` / `in_ranges` from it)

**Configuration:** Read from `vock.cfg`, same as the tools above. Needs `layout = data`: it reads `data/text/<language>/dialog/*.msg` and matches each one to `scripts_src/**/<same name>.ssl`.

**Usage:**
```
python3 tools/float_scan.py                # scan every tagged dialog MSG
python3 tools/float_scan.py andr west      # only these tag prefixes
python3 tools/float_scan.py --all          # also list dual-use TH lines
```

| Option | Default | Description |
|---|---|---|
| `prefixes` | all | Only report audio tags starting with these prefixes |
| `--all` | off | Also list dual-use lines outside `float_filter.cfg` (correct, shown for review) |
| `--language LANG` | `english` | `data/text/<LANG>/dialog` folder to read |

**Report groups:**
- `ERROR`: float-range tag used as a dialogue reply. Silent in the talking-head window. Exit code 1 when any are found.
- `INFO`: float-only tag missing from `float_filter.cfg`. Works, but is not in the opt-out floats DAT.
- `OK` (`--all`): dual-use tag outside `float_filter.cfg`. Has a LIP, plays in both places.

**Limits:** Only literal msg ids, the script's own `#define` constants and `random(a,b)` / `floater_rand(a,b)` ranges are resolved, and only against the script's own MSG. Lines from another script's MSG (`message_str(SCRIPT_X, n)`) and computed ids are not seen. It does not know whether a call site is live, so a reply inside dead code (e.g. `kctorr.ssl`'s `else if (0)` branch) still reports as an `ERROR`. Check each hit in the script before changing the filter.

---

## lip_studio.py

Browser-based LIP / TextGrid editor with a Fallout 2 talking-head preview. Pick a voiced line and it loads the ACM, `.lip`, `.TextGrid` and `.txt`, then plays the speech while the talking head lip-syncs on a copy of the in-game dialogue screen. Edit LIP events or TextGrid intervals on the timeline and you see the result straight away.

**Dependencies:** None (stdlib only). Needs a browser: open the printed URL in Chrome, Edge or Firefox on Windows. WSL forwards `localhost`.

**Configuration:** Read from `vock.cfg`, same as the tools above (`project_root`, `layout`, `[paths]`, `language`). Game art is looked up in this order, first hit wins, names case-insensitive:

1. the project's own `data/` (or the project root for `layout = flat`), so `data/art/heads/` overrides win
2. `[lip_studio] sources`: a comma-separated list of folders or `.dat` files, relative to `vock.cfg`. Default: `../dat/th, ../dat/master` (the extracted Talking Heads and `master.dat` trees next to `vock/`)

Needed art: `color.pal`, `font1.aaf`, `art/intrface/{alltlk,di_talk,hilight1,hilight2}.frm`, `art/heads/*`, `art/backgrnd/*`. The background for each head is guessed from `start_gdialog`-style calls (`HEAD_X, BACKGROUND_Y`) in `<project>/scripts_src` plus `[lip_studio] scripts` (default `../compile/headers`, which holds the `BACKGROUND_*` defines). You can change it in the page; the page remembers your choice per head.

**Usage:**
```
python3 tools/lip_studio.py                          # opens http://127.0.0.1:8642/
python3 tools/lip_studio.py --port 9000 --no-browser
python3 tools/lip_studio.py --source /mnt/c/Fallout/Fallout2-CE/master.dat
```

| Option | Default | Description |
|---|---|---|
| `--port N` | `8642` | Port to serve on |
| `--host H` | `127.0.0.1` | Interface to bind |
| `--project DIR` | `project_root` from `vock.cfg` | Project to read and save |
| `--source PATH` | none | Extra art folder or `.dat`, searched before `[lip_studio] sources`; repeatable |
| `--scripts DIR` | none | Extra script/header folder for the background guess; repeatable |
| `--no-browser` | off | Don't open a browser |

**What it shows.** The screen is drawn the way `fallout2-ce` draws it (`game_dialog.cc`), into a 640x480 palette buffer:
- `alltlk.frm` and `di_talk.frm`, the head window at (126,14), the background FRM, the head frame placed with the FRM shift and the running per-frame x offset, the two highlight overlays blended through the grey/olive blend tables, and the 8 frame pieces drawn back over the corners.
- The reply text from the `.txt`, in `font1.aaf` green, wrapped with the engine's `display_msg` rules (first line indented 10 px). Click the top or bottom half of the reply box to scroll, like in game. "Player option" draws an option line in the options box.
- The mouth frame follows the engine's `lipsTicker`: phoneme *i* becomes current once the audio byte position is strictly past marker *i*, and the code maps to a frame through `_head_phoneme_lookup`.

**Editing.**
- LIP lane: blocks coloured by head frame (0-8) with the code name. Drag a boundary to move an event. Click an event, then pick its code from the inspector or the code grid. Click a frame in the strip under the screen to give the selected event a code for that frame. `I` inserts an event at the playhead (code taken from the phones tier there). `Del` deletes. `Alt+←/→` nudges 10 ms (`Shift` for 1 ms). The red line is the end marker; you can drag it too.
- TextGrid tiers: drag boundaries, edit labels in the inspector, `S` splits the selected interval at the playhead, `M` merges it with the next one, `Del` removes its left boundary.
- `TextGrid → LIP` rebuilds the events from the phones tier with the same phoneme table and de-duplication as `vock.py` (identical output for every vock-fo2 line). `New LIP` starts an empty one. `End = audio` moves the end marker to the audio length.
- Snap (on by default) pulls dragged boundaries onto boundaries in the other rows.
- Link (off by default) moves boundaries together: dragging or `Alt`-nudging one also moves every boundary on the other rows at the same time (within 1 ms), e.g. a word start, its first phone and the LIP event built from it. The move stops where the tightest neighbouring interval in any of those rows would collapse. An amber line marks a linked drag. One undo reverts all rows.
- `Space` play/pause, `Home` rewind, `Ctrl+Z`/`Ctrl+Y` undo/redo, `Ctrl+S` saves everything changed, `PgUp`/`PgDn` previous/next line, `Ctrl+wheel` zoom.

**Files.** Save writes into the project: `.lip` and `.txt` to `data/sound/speech/<folder>/`, `.TextGrid` to `work/textgrid/` (flat layout: the `[paths]` folders). The download buttons save a copy instead. A loaded LIP is written back byte-identical when unchanged (header fields, marker types and the name field are kept), checked against all 879 vock-fo2 and 1029 `master.dat` LIPs. `Open files…` (or drag and drop) takes loose `.lip`, `.TextGrid`, `.txt`, `.acm`, `.wav`/`.mp3`/`.ogg`, and `.frm` files: a 388x200 single-frame FRM becomes the background, any other FRM the head.

**Audio.** The page decodes ACM itself with a port of the engine's decoder (`sound_decoder.cc`). Speech ACMs say stereo in the header but hold mono samples, and the engine plays them as mono, so the page does too. ffmpeg 8's `interplayacm` decoder fails on snd2acm output, so it isn't used. `Use WAV` plays `work/wav/<stem>.wav` instead; the ACM starts about 80 samples (4 ms) later than the WAV because of the encoder delay.
