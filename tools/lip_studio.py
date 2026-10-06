#!/usr/bin/env python3
"""
lip_studio.py — browser-based LIP / TextGrid editor with a Fallout 2 talking-head preview.

Starts a small local web server and opens the LIP Studio page. The page draws the
Fallout 2 dialogue screen the same way fallout2-ce does (alltlk/di_talk art, highlight
blending, the 388x200 head window, font1.aaf reply text) and lip-syncs a talking head
to a .LIP while the speech plays.

The server only reads game art and speech and saves edited files back into the
project. All decoding (ACM, FRM, AAF), rendering and editing happens in the page.

Configuration comes from vock.cfg, same as vock.py: [general] project_root/layout and
[paths]. Game art is looked up in this order (first hit wins, names are case-insensitive):

  1. <project>/data           (layout = data) or <project>/art etc. (flat; data_root ignored)
  2. every entry in [lip_studio] sources (folders or .dat files), in order

Usage:
  python3 tools/lip_studio.py [--port 8642] [--project ../vock-fo2] [--source DIR_OR_DAT ...]
                              [--no-browser]
"""

import argparse
import configparser
import http.server
import importlib.util
import json
import os
import re
import shutil
import socketserver
import struct
import sys
import tempfile
import threading
import urllib.parse
import webbrowser
import zlib
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # vock/tools/
_VOCK_DIR   = _SCRIPT_DIR.parent                # vock/
_APP_DIR    = _SCRIPT_DIR / "lip_studio"

_ini = configparser.ConfigParser(inline_comment_prefixes=("#",))
if not _ini.read(_VOCK_DIR / "vock.cfg", encoding="utf-8"):
    sys.exit(f"[ERROR] Could not read config file: {_VOCK_DIR / 'vock.cfg'}")

LANGUAGE_CONFIG = {
    "arpabet": "english_us_arpa", "english": "english_mfa", "spanish": "spanish_mfa",
    "russian": "russian_mfa", "german": "german_mfa", "italian": "italian_mfa",
    "french": "french_mfa", "hungarian": "hungarian_mfa", "polish": "polish_mfa",
    "portuguese": "portuguese_mfa", "czech": "czech_mfa",
}
LANG_ENCODING = {
    "polish": "cp1250", "czech": "cp1250", "russian": "cp1251",
}

# Default art sources, relative to vock.cfg's folder: the extracted Talking Heads
# and master.dat trees that sit next to vock/ in the VOCK workspace.
DEFAULT_SOURCES = ["../dat/th", "../dat/master"]


# ─── Virtual file system ─────────────────────────────────────────────────────

class DirSource:
    """A loose folder, looked up case-insensitively (FRM names mix case freely)."""

    def __init__(self, root: Path):
        self.root = root
        self.name = str(root)
        self._listings: dict[Path, dict[str, str]] = {}

    def _listing(self, d: Path) -> dict:
        if d not in self._listings:
            try:
                self._listings[d] = {n.lower(): n for n in os.listdir(d)}
            except OSError:
                self._listings[d] = {}
        return self._listings[d]

    def resolve(self, rel: str) -> Path | None:
        cur = self.root
        for part in rel.split("/"):
            real = self._listing(cur).get(part.lower())
            if real is None:
                return None
            cur = cur / real
        return cur if cur.is_file() else None

    def read(self, rel: str) -> bytes | None:
        p = self.resolve(rel)
        return p.read_bytes() if p else None

    def list(self, rel_dir: str) -> list[str]:
        cur = self.root
        for part in [p for p in rel_dir.split("/") if p]:
            real = self._listing(cur).get(part.lower())
            if real is None:
                return []
            cur = cur / real
        return [n.lower() for n in self._listing(cur)]


class DatSource:
    """A Fallout 2 DAT2 archive. Only the directory tree is read up front."""

    def __init__(self, path: Path):
        self.path = path
        self.name = str(path)
        self.entries: dict[str, tuple[int, int, int, int]] = {}
        with open(path, "rb") as f:
            f.seek(-8, os.SEEK_END)
            tree_size, _total = struct.unpack("<II", f.read(8))
            f.seek(-8 - tree_size, os.SEEK_END)
            tree = f.read(tree_size)
        pos = 4
        for _ in range(struct.unpack_from("<I", tree, 0)[0]):
            n = struct.unpack_from("<I", tree, pos)[0]; pos += 4
            name = tree[pos:pos + n].decode("cp1252", "replace"); pos += n
            flags, real, packed, off = struct.unpack_from("<BIII", tree, pos); pos += 13
            self.entries[name.replace("\\", "/").lower()] = (flags, real, packed, off)

    def read(self, rel: str) -> bytes | None:
        e = self.entries.get(rel.lower())
        if e is None:
            return None
        flags, _real, packed, off = e
        with open(self.path, "rb") as f:
            f.seek(off)
            raw = f.read(packed)
        return zlib.decompress(raw) if flags & 1 else raw

    def list(self, rel_dir: str) -> list[str]:
        prefix = rel_dir.strip("/").lower() + "/"
        return [k[len(prefix):] for k in self.entries
                if k.startswith(prefix) and "/" not in k[len(prefix):]]


class GameFS:
    def __init__(self, sources):
        self.sources = sources

    def read(self, rel: str) -> bytes | None:
        rel = rel.replace("\\", "/").strip("/")
        for s in self.sources:
            data = s.read(rel)
            if data is not None:
                return data
        return None

    def exists(self, rel: str) -> bool:
        rel = rel.replace("\\", "/").strip("/")
        for s in self.sources:
            if isinstance(s, DirSource):
                if s.resolve(rel):
                    return True
            elif rel.lower() in s.entries:
                return True
        return False

    def list(self, rel_dir: str) -> list[str]:
        seen = set()
        for s in self.sources:
            seen.update(s.list(rel_dir))
        return sorted(seen)


def make_source(path: Path):
    if path.is_dir():
        return DirSource(path)
    if path.is_file() and path.suffix.lower() == ".dat":
        return DatSource(path)
    return None


# ─── Project layout ──────────────────────────────────────────────────────────

class Project:
    def __init__(self, root: Path):
        self.root = root
        self.layout = _ini.get("general", "layout", fallback="flat").strip().lower()
        paths = dict(_ini["paths"]) if _ini.has_section("paths") else {}
        wk = "./work/" if self.layout == "data" else "./"
        self.data_root = root / paths.get("data_root", "./data")
        self.wav_dir = root / (paths.get("wav") or wk + "wav")
        self.textgrid_dir = root / (paths.get("textgrid") or wk + "textgrid")
        self.flat = {k: root / paths.get(k, "./" + k) for k in ("acm", "lip", "txt")}
        lang = _ini.get("general", "language", fallback="arpabet").strip().lower()
        self.language = lang
        self.encoding = LANG_ENCODING.get(lang, "cp1252")
        self.mfa_name = LANGUAGE_CONFIG.get(lang, lang)
        self.lock_file = root / paths.get("mfa_lock", "./mfa_lock.cfg")

    def speech_dir(self, folder: str) -> Path:
        return self.data_root / "sound" / "speech" / folder

    def path_for(self, folder: str, stem: str, kind: str) -> Path:
        if kind == "textgrid":
            return self.textgrid_dir / f"{stem}.TextGrid"
        if kind == "wav":
            return self.wav_dir / f"{stem}.wav"
        if self.layout == "data":
            return self.speech_dir(folder) / f"{stem}.{kind}"
        return self.flat[kind] / f"{stem}.{kind}"

    def find(self, folder: str, stem: str, kind: str) -> Path | None:
        """Existing file for a stem, matching the extension case-insensitively."""
        p = self.path_for(folder, stem, kind)
        if p.is_file():
            return p
        if p.parent.is_dir():
            want = p.name.lower()
            for n in os.listdir(p.parent):
                if n.lower() == want:
                    return p.parent / n
        return None

    def speech_index(self) -> dict:
        """{folder: {stem: [kinds]}} for every voiced line the project has."""
        out: dict[str, dict[str, set]] = {}

        def add(folder, stem, kind):
            out.setdefault(folder, {}).setdefault(stem, set()).add(kind)

        if self.layout == "data":
            base = self.data_root / "sound" / "speech"
            if base.is_dir():
                for folder in sorted(os.listdir(base)):
                    d = base / folder
                    if not d.is_dir():
                        continue
                    for n in os.listdir(d):
                        stem, ext = os.path.splitext(n)
                        if ext.lower() in (".acm", ".lip", ".txt"):
                            add(folder.lower(), stem.lower(), ext[1:].lower())
        else:
            for kind, d in self.flat.items():
                if d.is_dir():
                    for n in os.listdir(d):
                        stem, ext = os.path.splitext(n)
                        if ext.lower() == "." + kind:
                            add(re.sub(r"\d+$", "", stem).lower(), stem.lower(), kind)
        for kind, d, ext in (("textgrid", self.textgrid_dir, ".textgrid"),
                             ("wav", self.wav_dir, ".wav")):
            if d.is_dir():
                for n in os.listdir(d):
                    stem, e = os.path.splitext(n)
                    if e.lower() == ext:
                        folder = re.sub(r"\d+$", "", stem).lower()
                        if folder in out:
                            out[folder].setdefault(stem.lower(), set()).add(kind)
        return {f: {s: sorted(k) for s, k in sorted(stems.items(), key=lambda kv: _natkey(kv[0]))}
                for f, stems in sorted(out.items())}


def _natkey(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ─── mfa_lock.cfg ────────────────────────────────────────────────────────────
# Same format vock.py's load_mfa_lock() reads: one stem per line, # comments.
# A locked stem is left out of the 'mfa' step, so its TextGrid on disk survives
# a pipeline re-run instead of being re-aligned over.

def read_locks(lock_file: Path) -> set[str]:
    if not lock_file.is_file():
        return set()
    out = set()
    for raw in lock_file.read_text(encoding="utf-8").splitlines():
        tok = raw.split("#", 1)[0].strip().lower()
        if tok:
            out.add(tok)
    return out


def set_lock(lock_file: Path, stem: str, on: bool, note: str = "") -> None:
    lines = lock_file.read_text(encoding="utf-8").splitlines() if lock_file.is_file() else []
    keep = [ln for ln in lines if ln.split("#", 1)[0].strip().lower() != stem]
    if on:
        keep.append(f"{stem}   # {note}" if note else stem)
    lock_file.write_text("\n".join(keep) + "\n", encoding="utf-8")


# ─── MFA re-alignment of one line ────────────────────────────────────────────

_vock_mod = None
_mfa_busy = threading.Lock()


def vock_module():
    """vock.py loaded as a module, for its dictionary merge and run_mfa()."""
    global _vock_mod
    if _vock_mod is None:
        spec = importlib.util.spec_from_file_location("vock_pipeline", _VOCK_DIR / "vock.py")
        _vock_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_vock_mod)
    return _vock_mod


def realign(project: "Project", folder: str, stem: str) -> str:
    """Align work/wav/<stem>.wav against the current .txt on its own, the way
    mfa_verify.py does, and return the new TextGrid text. Nothing is written
    into the project; the page decides whether to keep it."""
    wav = project.find(folder, stem, "wav")
    txt = project.find(folder, stem, "txt")
    if not wav:
        raise RuntimeError(f"no WAV for {stem} in {project.wav_dir} (run vock.py --steps wav)")
    if not txt:
        raise RuntimeError(f"no .txt for {stem}")
    if shutil.which("conda") is None:
        raise RuntimeError("conda not on PATH; MFA runs through 'conda run'")
    vock = vock_module()
    mfa_name = project.mfa_name
    main_dict = vock.find_mfa_dict(mfa_name)
    custom = vock.resolve_custom_dict(mfa_name, None)
    env = _ini.get("settings", "mfa_env", fallback="aligner").split("#")[0].strip()
    with tempfile.TemporaryDirectory(prefix=f"lip_studio_{stem}_") as tmp:
        corpus, out = Path(tmp) / "corpus", Path(tmp) / "out"
        corpus.mkdir()
        out.mkdir()
        dict_arg = mfa_name
        if custom and main_dict:
            dict_arg = str(Path(tmp) / "merged.dict")
            vock.merge_dictionaries(main_dict, custom, dict_arg)
        shutil.copy2(wav, corpus / f"{stem}.wav")
        text = txt.read_text(encoding=project.encoding)
        (corpus / f"{stem}.txt").write_text(text, encoding="utf-8")
        if not vock.run_mfa(str(corpus), str(out), env, dict_arg, mfa_name):
            raise RuntimeError("MFA failed (see the lip_studio.py console)")
        tg = out / f"{stem}.TextGrid"
        if not tg.is_file():
            raise RuntimeError("MFA produced no TextGrid")
        return tg.read_text(encoding="utf-8")


# ─── Phoneme table (same mapping vock.py uses) ───────────────────────────────

def load_phoneme_table(mfa_name: str) -> dict:
    path = _VOCK_DIR / "phonemes" / f"phonemes_{mfa_name}.py"
    if not path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location(f"phonemes_{mfa_name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(getattr(mod, "PHONEME_TABLE", {}))


# ─── Head → background guess from scripts ────────────────────────────────────

DEFINE_RE = re.compile(r"^\s*#define\s+((?:HEAD|BACKGROUND)_[A-Z0-9_]+)\s+\(?\s*(-?\d+)\s*\)?", re.M)
PAIR_RE = re.compile(r"\b(HEAD_[A-Z0-9_]+)\s*,\s*(BACKGROUND_[A-Z0-9_]+)")


def guess_backgrounds(script_roots: list[Path], heads: list[str], backgrounds: list[str]) -> dict:
    """Most common background each head is paired with in start_gdialog-style calls."""
    defines: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    files = []
    for root in script_roots:
        if root.is_dir():
            for dirpath, _dirs, names in os.walk(root):
                files += [Path(dirpath) / n for n in names if n.lower().endswith((".h", ".ssl"))]
    for p in files:
        try:
            text = p.read_text(encoding="cp1252", errors="replace")
        except OSError:
            continue
        if p.suffix.lower() == ".h":
            for name, val in DEFINE_RE.findall(text):
                defines.setdefault(name, int(val))
        else:
            for h, b in PAIR_RE.findall(text):
                counts.setdefault(h, {}).setdefault(b, 0)
                counts[h][b] += 1
    out = {}
    for h, bs in counts.items():
        hi = defines.get(h)
        if hi is None or not (0 <= hi < len(heads)):
            continue
        best = max(bs.items(), key=lambda kv: kv[1])[0]
        bi = defines.get(best)
        if bi is not None and 0 <= bi < len(backgrounds):
            out.setdefault(heads[hi], backgrounds[bi])
    return out


def read_lst(data: bytes | None) -> list[str]:
    if not data:
        return []
    out = []
    for line in data.decode("cp1252", "replace").splitlines():
        out.append(line.split(";")[0].strip().split(",")[0].strip().lower())
    while out and not out[-1]:
        out.pop()
    return out


# ─── HTTP ────────────────────────────────────────────────────────────────────

STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8"}
SAVE_KINDS = {"lip", "txt", "textgrid"}
STEM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class App:
    def __init__(self, project: Project, fs: GameFS, script_roots: list[Path]):
        self.project = project
        self.fs = fs
        self.script_roots = script_roots
        self._heads = None

    def heads(self) -> dict:
        if self._heads is None:
            heads = read_lst(self.fs.read("art/heads/heads.lst"))
            bgs = read_lst(self.fs.read("art/backgrnd/backgrnd.lst"))
            guess = guess_backgrounds(self.script_roots, heads, bgs)
            listing = set(self.fs.list("art/heads"))
            items = []
            for i, h in enumerate(heads):
                if not h or h == "reser":
                    continue
                moods = [m for m in ("np", "gp", "bp") if f"{h}{m}.frm" in listing]
                items.append({"id": i, "name": h, "moods": moods, "background": guess.get(h)})
            self._heads = {"heads": items,
                           "backgrounds": [b for b in bgs if b and not b.startswith("reserv")]}
        return self._heads

    def config(self) -> dict:
        p = self.project
        return {
            "project": str(p.root),
            "layout": p.layout,
            "language": p.language,
            "encoding": p.encoding,
            "phonemeMode": "arpa" if p.mfa_name.endswith("_arpa") else "ipa",
            "phonemeTable": load_phoneme_table(p.mfa_name),
            "sources": [s.name for s in self.fs.sources],
            "lockFile": str(p.lock_file),
        }


class Handler(http.server.BaseHTTPRequestHandler):
    app: App = None  # set in main()

    def log_message(self, fmt, *args):
        if os.environ.get("LIP_STUDIO_VERBOSE"):
            super().log_message(fmt, *args)

    # -- helpers --
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _err(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _stem_args(self, q):
        folder = (q.get("folder") or [""])[0].lower()
        stem = (q.get("stem") or [""])[0].lower()
        if not STEM_RE.match(folder) or not STEM_RE.match(stem):
            raise ValueError("bad folder/stem")
        return folder, stem

    # -- routes --
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        app = self.app
        try:
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/config":
                return self._json(app.config())
            if url.path == "/api/speech":
                return self._json(app.project.speech_index())
            if url.path == "/api/heads":
                return self._json(app.heads())
            if url.path == "/api/locks":
                return self._json(sorted(read_locks(app.project.lock_file)))
            if url.path == "/api/game":
                rel = (q.get("path") or [""])[0]
                if ".." in rel.replace("\\", "/").split("/"):
                    return self._err(400, "bad path")
                data = app.fs.read(rel)
                if data is None:
                    return self._err(404, f"not found: {rel}")
                return self._send(200, data, "application/octet-stream")
            if url.path == "/api/stem":
                folder, stem = self._stem_args(q)
                kind = (q.get("kind") or [""])[0]
                return self._stem(folder, stem, kind)
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # keep the server alive, report to the page
            return self._err(500, f"{type(e).__name__}: {e}")
        self._err(404, "no such route")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/api/lock":
                _folder, stem = self._stem_args(q)
                on = (q.get("on") or ["1"])[0] == "1"
                note = (q.get("note") or [""])[0].replace("\n", " ")[:200]
                set_lock(self.app.project.lock_file, stem, on, note)
                return self._json({"locked": on, "file": str(self.app.project.lock_file)})
            if url.path == "/api/realign":
                folder, stem = self._stem_args(q)
                if not _mfa_busy.acquire(blocking=False):
                    return self._err(409, "MFA is already running")
                try:
                    tg = realign(self.app.project, folder, stem)
                finally:
                    _mfa_busy.release()
                return self._send(200, tg.encode("utf-8"), "text/plain; charset=utf-8")
            if url.path == "/api/save":
                folder, stem = self._stem_args(q)
                kind = (q.get("kind") or [""])[0]
                if kind not in SAVE_KINDS:
                    return self._err(400, f"cannot save kind {kind!r}")
                body = self._body()
                if not body:
                    return self._err(400, "empty body")
                proj = self.app.project
                dest = proj.find(folder, stem, kind) or proj.path_for(folder, stem, kind)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                return self._json({"saved": str(dest)})
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:
            return self._err(500, f"{type(e).__name__}: {e}")
        self._err(404, "no such route")

    def _static(self, name: str):
        p = (_APP_DIR / name).resolve()
        if _APP_DIR.resolve() not in p.parents or not p.is_file():
            return self._err(404, "not found")
        self._send(200, p.read_bytes(), STATIC_TYPES.get(p.suffix, "application/octet-stream"))

    def _stem(self, folder: str, stem: str, kind: str):
        proj = self.app.project
        if kind == "audio":
            # The ACM is what the game plays, so LIP timing should be judged against it.
            # The page decodes it (formats.js decodeAcm).
            acm = proj.find(folder, stem, "acm")
            if acm:
                return self._send(200, acm.read_bytes(), "application/octet-stream")
            wav = proj.find(folder, stem, "wav")
            if wav:
                return self._send(200, wav.read_bytes(), "audio/wav")
            return self._err(404, f"no audio for {stem}")
        if kind == "wav":
            wav = proj.find(folder, stem, "wav")
            if wav:
                return self._send(200, wav.read_bytes(), "audio/wav")
            return self._err(404, f"no wav for {stem}")
        if kind in SAVE_KINDS:
            p = proj.find(folder, stem, kind)
            if not p:
                return self._err(404, f"no {kind} for {stem}")
            return self._send(200, p.read_bytes(), "application/octet-stream")
        return self._err(400, f"unknown kind {kind!r}")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description="LIP Studio: edit LIP/TextGrid files with a Fallout 2 talking-head preview.")
    ap.add_argument("--port", type=int, default=8642)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--project", help="project root (default: [general] project_root in vock.cfg)")
    ap.add_argument("--source", action="append", default=[],
                    help="extra game art source (folder or .dat), searched after the project; repeatable")
    ap.add_argument("--scripts", action="append", default=[],
                    help="extra script/header folder for the head-to-background guess; repeatable")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = ap.parse_args()

    proj_root = Path(args.project) if args.project else _VOCK_DIR / _ini.get("general", "project_root", fallback="./")
    project = Project(proj_root.resolve())

    cfg_sources = [s.strip() for s in _ini.get("lip_studio", "sources", fallback="").split(",") if s.strip()]
    source_paths = [Path(s) for s in args.source] + [_VOCK_DIR / s for s in (cfg_sources or DEFAULT_SOURCES)]
    sources = []
    if project.layout == "data":
        sources.append(DirSource(project.data_root))
    else:
        sources.append(DirSource(project.root))
    for sp in source_paths:
        s = make_source(sp.resolve())
        if s is None:
            print(f"[WARN] art source not found, skipped: {sp}")
        else:
            sources.append(s)

    script_cfg = [s.strip() for s in _ini.get("lip_studio", "scripts", fallback="").split(",") if s.strip()]
    script_roots = ([project.root / "scripts_src"] + [Path(s) for s in args.scripts]
                    + [_VOCK_DIR / s for s in (script_cfg or ["../compile/headers"])])

    Handler.app = App(project, GameFS(sources), script_roots)
    srv = Server((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"LIP Studio  {url}")
    print(f"  project   {project.root}  (layout={project.layout})")
    for s in sources:
        print(f"  art       {s.name}")
    print("Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
