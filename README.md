# V.O.C.K. Vocal Output Creation Kit

A Python script that automates the complete voice modding pipeline for the Fallout 2 engine — Fallout 2 itself, and games built on it such as Fallout 1 via [*Fallout Et Tu*](https://github.com/rotators/Fo1in2/). Give it `.msg` dialogue file(s) and a folder of audio files — it produces a ready-to-install `vock.dat` containing ACM audio, LIP sync, and dialogue files.

## What it does

```
  msg ────────[parse per-language encoding]─► txt (one per dialog line)
                                              ↕ optional: edit manually here
  audio ──────[ffmpeg normalize + encode]───► wav  (22050 Hz mono 16-bit)
  wav ────────[snd2acm / wine]──────────────► acm
  wav + txt ──[MFA]─────────────────────────► textgrid
  textgrid ──────────────────────────────────► lip  (floats: ACM only, no LIP)
  msg + acm + lip + txt + scripts + art ──────► dat/<mod>.dat
                                               dat/<mod>-floats.dat   (if floats defined)
                                               dat/<mod>-combat.dat   (if combat lines defined)
                                               dat/<mod>-pipboy.dat   (if [acm_only] MSGs defined)
```

`<mod>` is the project folder name (e.g. `vock-fo2`), so sibling mods never
collide. Override with `mod_name` in `vock.cfg` `[general]`.

## Folder structure

All folders are created automatically or configured via `vock.cfg`.

```
vock/
├── vock.py
├── vock.cfg              ← Global settings and paths
├── npc_filter.cfg         ← Optional: NPC prefixes to include (omit to process all)
├── float_filter.cfg       ← Optional: float/ambient line definitions (ACM-only, no LIP)
├── combat_filter.cfg      ← Optional: per-NPC combat-bark line definitions (ACM-only, no LIP)
├── mfa_lock.cfg           ← Optional: audio tags whose TextGrid MFA must never regenerate
├── dictionaries/         ← custom.<language>.dict files
├── phonemes/             ← Phoneme mapping tables
├── msg/                  ← put your .MSG file(s) here
├── audio/                ← put your audio files here (MP3, WAV, FLAC, M4A, …)
├── scripts/              ← put pre-compiled .INT script files here (packed as scripts\*)
├── art/                  ← put art assets here, e.g. art/heads/*.FRM (packed as art\*)
├── txt/                  ← generated/editable: one .txt per audio line
├── wav/                  ← generated: 22050 Hz mono 16-bit PCM
├── acm/                  ← generated: Fallout 2 ACM audio files
├── textgrid/             ← generated: MFA alignment TextGrid files
├── lip/                  ← generated: Fallout 2 LIP files
├── unknown.txt           ← generated: words not recognized by dictionary
└── dat/
    ├── <mod>.dat         ← generated: ready-to-install Fallout 2 DAT archive
    ├── <mod>-floats.dat  ← generated: float/ambient audio DAT (if floats defined)
    ├── <mod>-combat.dat  ← generated: combat-bark audio DAT (if combat lines defined)
    └── <mod>-pipboy.dat  ← generated: holodisk-narration DAT (if [acm_only] MSGs)
```

### Source layout: `flat` vs `data`

`layout` in `vock.cfg` `[general]` selects how the project's source is arranged:

- **`flat`** (default) — the category folders above: `msg/`, `acm/`, `lip/`, `txt/`, `scripts/`, `art/`.
- **`data`** — a sparse, [RPU](https://github.com/BGforgeNet/Fallout2_Restoration_Project)-shaped `data/` tree holding only the files the mod changes:
  ```
  data/text/<lang>/dialog/*.msg      source + localised MSGs (diff against rpu/data/)
  data/sound/speech/<folder>/*.acm   generated speech (also .lip, .txt)
  data/scripts/*.int                 compiled scripts
  data/art/heads/*.frm
  work/wav/  work/textgrid/          MFA rebuild metadata (committed)
  work/audio/                        raw voice-actor takes (gitignored)
  ```
  Source MSGs are read from `data/text/<lang>/**/*.msg` (the `--language` value picks `<lang>`; `arpabet` → `english`), and the DAT is packed from `data/**` verbatim — the on-disk path *is* the in-DAT path, no synthesis. The MFA rebuild chain moves under `work/` (flat layout keeps `audio/`, `wav/`, `textgrid/` at the root). `tools/msg_localize.py` writes localised MSGs straight into `data/text/<lang>/dialog/` and builds no DAT of its own.

## Supported Languages

V.O.C.K. supports multiple languages configured via vock.cfg or by using the `--language` flag. If an NPC speaks multiple languages (e.g., Spanglish), the recommendation is to use the dominant language and add any non-dominant words to the custom dictionary.

- arpabet
- english
- spanish
- russian
- french
- german
- czech
- hungarian
- italian
- polish
- portuguese

Note: [ARPAbet](https://en.wikipedia.org/wiki/ARPABET) is a unique, English-specific set of phonetic transcription codes and currently features the largest dictionary. All other language options provided (english, spanish, russian, etc.) utilize the standard [International Phonetic Alphabet](https://en.wikipedia.org/wiki/International_Phonetic_Alphabet) models via MFA.

## Pipeline steps

| Step  | Input              | Output         | Description                                      |
|-------|--------------------|----------------|--------------------------------------------------|
| `msg` | `msg/*.msg`        | `txt/*.txt`    | Extract dialogue lines (one `.txt` per tag)      |
| `wav` | `audio/*`          | `wav/*.wav`    | Normalise + encode to 22050 Hz mono 16-bit PCM   |
| `acm` | `wav/*.wav`        | `acm/*.acm`    | Convert to Fallout 2 ACM via `snd2acm.exe`       |
| `mfa` | `wav/` + `txt/`    | `textgrid/`    | MFA forced alignment → phoneme timing            |
| `lip` | `textgrid/`        | `lip/*.lip`    | Generate Fallout 2 LIP files (floats skipped)    |
| `dat` | source tree + `acm/`+`lip/`+`txt/` | `dat/<mod>.dat`        | Pack talking-head files into a Fallout 2 DAT2 archive |
| `dat` | ACM-only stems (float / combat / holodisk) | `dat/<mod>-floats.dat`, `-combat.dat`, `-pipboy.dat` | Pack each ACM-only group into its own opt-out DAT2 archive (only the ones that have lines) |

## Output DAT structure

```
text\english\dialog\*.msg
sound\speech\<npc>\*.acm
sound\speech\<npc>\*.lip
sound\speech\<npc>\*.txt
scripts\*.int
art\heads\*.frm
```

Where `<npc>` is derived automatically from the audio tag, e.g.:

```
text\english\dialog\acmorlis.msg
sound\speech\mor\mor1.acm
sound\speech\mor\mor1.lip
sound\speech\mor\mor1.txt
```

## Requirements

See [docs/setup.md](docs/setup.md) for full installation instructions covering WSL, FFmpeg, snd2acm, and MFA.

## Usage

### Full pipeline (with MFA alignment)

```bash
# Activate your MFA environment
conda activate aligner

# Run the full pipeline
python3 vock.py
```

### Run only specific steps

Use `--steps` to run exactly the steps you name and skip the rest.

```bash
# Rebuild just the DAT from existing files
python3 vock.py --steps dat

# Re-run MFA alignment and regenerate LIP + DAT
python3 vock.py --steps mfa lip dat

# Re-encode audio and rebuild ACM only (e.g. after swapping audio files)
python3 vock.py --steps wav acm

# Run everything from the encoding step onward
python3 vock.py --steps wav acm mfa lip dat
```

### Skip specific steps from the full pipeline

Use `--skip` to run everything except the named step(s).

```bash
# Full pipeline but skip MFA (text approximation used for LIP)
python3 vock.py --skip mfa

# Full pipeline but skip ACM generation (no snd2acm.exe needed)
python3 vock.py --skip acm

# Skip both MFA and ACM (minimal dependencies: only ffmpeg required)
python3 vock.py --skip mfa acm
```

### Console verbosity

By default each step prints a header, one line per processed file, and a
one-line tally. Warnings and errors are always shown and collected into a
`PROBLEMS` recap after `DONE`.

```bash
python3 vock.py --terse   # -t: section headers and per-step tallies only
python3 vock.py --quiet   # -q: warnings, errors and the final summary only
```

Colour is used automatically when the output is a terminal; it is disabled when
output is piped/redirected or when `NO_COLOR` is set.

## Manual text-correction workflow (human-in-the-loop)

Fallout 2 dialogue sometimes contains placeholders, numbers, jokes, or names that MFA
cannot align correctly (e.g. `[Player Name]`, `$25`, `Vault 13`).
The recommended workflow is:

**1 — Extract the TXT files**

```bash
python3 vock.py --steps msg
```

This writes one `.txt` per audio-tagged line into `txt/`.  
For example, `txt/mor1.txt` might contain:

```
What is it? You know I have a lot to do, [Player Name]!
That’ll cost you $70.
Vault 13.
```

**2 — Edit the TXT files**

Open any `.txt` file in `txt/` and correct the text so MFA can align it:

```
What is it? You know I have a lot to do, Chosen One!
That’ll cost you seventy dollars.
Vault thirteen.
```

Save the file. `vock.py` will **never overwrite a manually-edited file** once it
exists — it detects the change and preserves your correction.

**3 — Resume the pipeline from audio**

```bash
conda activate aligner
python3 vock.py --steps wav acm mfa lip dat
```

The `mfa` and `lip` steps will read your corrected text from `txt/`.

**Re-running the full pipeline later**

If you run `python3 vock.py` again after editing a `.txt` file, the `msg` step
will notice the existing file differs from the MSG source and print
`[kept manual edit]` — your correction is safe.

## Selecting specific NPCs

`npc_filter.cfg` lets you focus the pipeline on a subset of characters. If the file is absent or empty, all characters are processed. If it contains entries, **only those prefixes** are processed.

The prefix is the audio tag stem — the letters before the number. For example, `mor` covers `mor1` through `mor27`.

```
# npc_filter.cfg
mor     # Morlis
zaius   # Zaius
ahs7    # AHS-7
```

This applies to steps 1–5 (msg, wav, acm, mfa, lip). The `dat` step always compiles all files already on disk, so characters you processed in a previous run are still included in `vock.dat`.

## Float lines and combat barks

Fallout 2 NPCs have two kinds of voiced lines: talking-head dialogue (which requires both ACM and LIP) and ambient floats (which play as overhead text with ACM audio only — no LIP file needed). `float_filter.cfg` defines which lines are floats so the pipeline can handle them correctly.

`combat_filter.cfg` is identical in format and behaviour, for per-NPC combat barks — lines that extend an NPC's numbered tag sequence and live in that NPC's own speech folder, exactly like floats.

**Format** — one NPC per line, with a comma-separated list of audio tag numbers or ranges:

```
# float_filter.cfg  (and combat_filter.cfg — same syntax)
mor   21, 22            # tags mor21, mor22
zaius 37                # tag zaius37
kaga  6-49              # tags kaga6 through kaga49
```

Filtered lines are detected during the `msg` step. During `mfa` and `lip` they are excluded — no TextGrid or LIP. During `dat`, float ACM files are packed into `<mod>-floats.dat` and combat ACM files into `<mod>-combat.dat`; both are kept out of the main `<mod>.dat` so a player can opt out of either. Talking-head files go into `<mod>.dat`.

Install whichever DATs you want: `<mod>.dat` for dialogue, `<mod>-floats.dat` for floats, `<mod>-combat.dat` for combat barks.

## ACM-only MSGs (holodisk narration)

Some MSG files carry one continuous recording per entry rather than per-NPC dialogue — the FISSION holodisk-narration path reads audio slugs from `pipboy.msg` this way. List such files under `[acm_only]` in `vock.cfg`:

```ini
[acm_only]
msgs = pipboy
```

Their tagged lines skip MFA and LIP (forced alignment does not apply to a long narration against fragmented page text), the generated audio goes to `sound/<msg-basename>/` (e.g. `sound/pipboy/`) as a bare `.acm` with no `.txt` or `.lip`, and it is packed into its own opt-out `<mod>-pipboy.dat` — inert until the engine feature is present, like stock `combatai.msg` audio fields.

## MFA alignment lock

MFA's `--single_speaker` mode pools acoustic normalization statistics across every file in an NPC's batch. Usually that helps, but if one line is an acoustic outlier for that character — unusually dramatic pacing, a long held vowel, a big mid-line pause — the pooled stats can end up mismatched for that line specifically, corrupting its alignment (a very long single-phoneme hold is the usual symptom) even though the rest of the batch aligns fine. Re-running MFA on the offending file *by itself*, outside its NPC's batch, typically fixes it since there's nothing left to skew the normalization.

Once you've hand-corrected a TextGrid this way, `mfa_lock.cfg` keeps it from being silently overwritten and re-broken the next time you run the full pipeline (or just `--steps mfa`) over that NPC.

**Format** — one audio tag per line:

```
# mfa_lock.cfg
arth2   # batch-alignment artifact, fixed by isolated re-alignment
```

Locked tags are excluded from their NPC's MFA corpus entirely — their existing TextGrid is left untouched, and the `lip` step reads it as normal. If a locked tag has no TextGrid on disk, `mfa` prints a warning (there's nothing to protect, and `lip` will fail for it). Remove a tag from the file whenever you want MFA to re-align it — e.g. after editing its audio or text.

## Custom Dictionary

If MFA fails to align specific game nouns (e.g., `GECK`, `Arroyo`), add them to the dictionary file corresponding to your language (e.g., `dictionaries/custom.english_us_arpa.dict`).

The format is one word per line, followed by its phoneme pronunciation:

```
# ARPAbet
geck G EH1 K
mynoc M IH1 N AH0 K
tribals T R AY1 B AH0 L Z
hassleful HH AE1 S AH0 L F AH0 L

# IPA
geck ɡ ɛ k
mynoc m ɪ n ə k
tribals t ɹ aj b ə l z
hassleful h æ s ə l f ə l
```

`vock.py` automatically detects the custom dictionary and merges it with the main MFA dictionary before running alignment.

After running the `mfa` step, check `unknown.txt` for a list of words that were assigned as "spoken noise" (`spn`). Use this file to identify missing custom dictionary entries:

```
Unknown words (MFA assigned 'spn')
23 occurrence(s) in 14 file(s).
Add pronunciations for these words to your custom dictionary
(dictionaries/custom.<mfa_name>.dict) and re-run --steps mfa lip dat

sally1.txt
  dunton        1.98s – 2.54s
  hmm           2.70s – 3.10s

sally2.txt
  idjit         2.82s – 3.35s
  shoo          8.36s – 8.97s
  shoo          8.97s – 9.17s
```

Typical causes of unknown words:

- **Game-specific nouns** — `geck`, `mynoc`, `brahmin`, `arroyo` → add to the custom dictionary.
- **Non-standard words** — `hassleful`, `tribals` → add to the custom dictionary. 
- **Numbers** — `$55`, `125` → edit the `.txt` file to the spoken form (`fifty five dollars`, `one hundred twenty five`)
- **Stage directions** — `(chuckle)`, `[Player Name]` → remove or replace in the `.txt` file.

## Custom Configuration
All global settings, file paths, and environment configurations are managed in `vock.cfg`. You can adjust these values to suit your specific project setup or system environment:
- `project_root`: Root folder that every path in `[paths]` is resolved against (default: `./`, this folder). Point it at another project's folder (e.g. `../vock-fo2/`) to run the pipeline against that project's `msg/`, `audio/`, `txt/`, etc. without moving or duplicating anything.
- `[paths]`: Defines the location of your input/output folders and the path to your snd2acm.exe executable, all relative to `project_root`.
  - `npc_filter`: points to `npc_filter.cfg` — NPC prefixes to include (omit or leave empty to process all).
  - `float_filter` / `combat_filter`: point to `float_filter.cfg` / `combat_filter.cfg` — float and per-NPC combat-bark line definitions (ACM-only, no LIP).
  - `mfa_lock`: points to `mfa_lock.cfg` — audio tags whose existing TextGrid `mfa` must never regenerate.
  - `dat_dir`: folder the DATs are written to (default: `./dat`). Filenames are `<mod>.dat` and `<mod>-{floats,combat,pipboy}.dat`, where `<mod>` is `mod_name` in `[general]` or, unset, the `project_root` folder name.
  - `scripts`: folder of pre-compiled `.INT` script files to pack into the DAT as `scripts\*` (flat layout; data layout packs `data/scripts/`).
  - `art`: folder of art assets to pack into the main DAT as `art\*`. Sub-folders are preserved, so `art/heads/foo.FRM` → `art\heads\foo.frm`.
  - `rpu_text`: path into the sibling RPU repo (default: `../rpu/data/text`) used by `tools/msg_localize.py`. Unlike the other `[paths]` entries, it resolves against `vock.cfg`'s own folder, not `project_root` — the RPU repo is shared infrastructure next to `vock/`, not part of whichever project `project_root` points at.
  - `loc`: output folder for localization tooling (see [Tools](#tools) below) — tagged foreign-language MSGs and rebuilt localized DATs.
- `[settings]`:
  - `mfa_env`: The name of the conda environment where MFA is installed (default: `aligner`).
  - `lufs`: The target loudness for audio normalization (default: `-16.0`).
  - `no_norm`: Set to `true` to disable automatic audio loudness normalization.
- `language`: Sets the default language/phoneme set used by the pipeline if no --language flag is provided.

## Notes

- **Universal audio input.** The `wav` step accepts MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WMA — any format FFmpeg can decode. Duration is always read via `ffprobe` for accuracy across all containers.
- **TXT validation.** During the `wav` step, audio files without a matching `.txt` file are skipped with a clear warning. This prevents untagged or misnamed audio from silently entering the pipeline.
- **Loudness normalisation.** Audio is normalised to −16 LUFS (EBU R128) during the `wav` step to match original Fallout 2 game files. Can be configured via `vock.cfg`.
- **Per-language encoding.** MSG and TXT files are read and written using the correct Windows code page for the selected language: CP1252 for Western European languages (English, Spanish, French, German, Italian, Hungarian, Portuguese), CP1250 for Central European (Polish, Czech), and CP1251 for Russian. The code page is selected automatically from `--language`.
- **Dependency fast-fail.** The script checks for `ffmpeg`, `ffprobe`, `conda`, and `snd2acm.exe` before starting and exits with a clear install message if anything required for the chosen steps is missing.

## Tools

Standalone utility scripts live in `tools/` — see [tools/tools.md](tools/tools.md) for full details.

- **`dict_lookup.py`** — interactive MFA pronunciation dictionary lookup. Type a word, get its ARPA/IPA transcription(s), with fuzzy suggestions if it's not found.
- **`msg_localize.py`** — tags foreign-language MSG files (from a sibling RPU repo) with the audio tags from your source-language MSGs. In the `data` layout it writes them straight into `data/text/<lang>/dialog/` (packed by the `dat` step); in the `flat` layout it writes to the `loc` folder and rebuilds `<mod>.dat` with the localized MSGs added.

## File formats

LIP and DAT binary format documentation: [docs/formats.md](docs/formats.md)

## How to obtain the MSG file

You must own a legal copy of Fallout 2.

**fo2dat** unpacks Fallout 2 DAT files. Build from source:

```bash
sudo apt install rustc cargo -y
git clone https://github.com/adamkewley/fo2dat
cd fo2dat
cargo build --release
sudo cp target/release/fo2dat /usr/local/bin/
```

Extract dialogue files from your `master.dat`:

```bash
mkdir master
fo2dat -xf master.dat -C master
```

Copy the specific `.MSG` file you want to edit into `vock/msg/`.

## How to edit the MSG file

1. Open your `.MSG` file (e.g. `ACMORLIS.MSG`) in a text editor.
2. Locate the line you want to add voice to. The format is:
   `{103}{}{What is it? You know I have a lot to do!}`
3. Add your audio tag in the middle bracket:
   `{103}{mor1}{What is it? You know I have a lot to do!}`
4. Save your audio file as `mor1.mp3` (or `.wav`, `.flac`, etc.) in `audio/`.
   The script matches the audio file to the MSG tag automatically.

## Other useful tools

- LIP Editor: https://fodev.net/files/mirrors/teamx-utils/LIPEditor0.96b.rar
