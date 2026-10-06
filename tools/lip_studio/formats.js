// File formats used by LIP Studio: color.pal, FRM, AAF, LIP, TextGrid, WAV.
// Fallout files are big-endian unless noted.

// ─── LIP codes ───────────────────────────────────────────────────────────────

// fallout2-ce game_dialog.cc _head_phoneme_lookup: LIP phoneme code -> head frame.
export const HEAD_PHONEME_LOOKUP = [
  0, 3, 1, 1, 3, 1, 1, 1, 7, 8, 7, 3, 1, 8, 1, 7, 7, 6, 6, 2, 2,
  2, 2, 4, 4, 5, 5, 2, 2, 2, 2, 2, 6, 2, 2, 5, 8, 2, 2, 2, 2, 8,
];
export const PHONEME_COUNT = 42;

// Short names for the 42 codes (ARPAbet where one exists, else IPA).
// From phonemes/lip_phoneme_mapping_reference.yaml.
export const CODE_NAMES = [
  "sil", "IY", "IH", "EY", "EH", "AE", "AA", "AO", "OW", "UH", "UW", "ER", "ɒ", "AH",
  "AY", "AW", "OY", "P", "B", "T", "D", "K", "G", "F", "V", "TH", "DH", "S", "Z",
  "SH", "ZH", "HH", "M", "N", "NG", "L", "W", "Y", "R", "CH", "JH", "0x29",
];
export const CODE_EXAMPLES = [
  "silence/rest", "bee, lady", "busy, guild", "bay, they", "end, bread", "cat, plaid",
  "arm", "paw, ball", "open, toe", "wolf, bush", "dew, blue", "cure, tourist",
  "slaw, fought", "lug, blood", "sky, night", "now, shout", "join, boy", "pin, dippy",
  "bug, bubble", "tip, matter", "dad, add", "cat, folk", "gun, egg", "fat, cliff",
  "vine, five", "thongs", "leather", "sit, less", "zed, buzz", "sham, ocean",
  "treasure, azure", "hop, who", "man, palm", "net, funny", "ring, pink", "live, well",
  "wit, why", "you, onion", "run, carrot", "chip, watch", "jam, wage", "unused",
];

export function frameForCode(code) {
  return code >= 0 && code < PHONEME_COUNT ? HEAD_PHONEME_LOOKUP[code] : 0;
}

// LIP marker positions are byte offsets into 22050 Hz 16-bit mono audio.
export const LIP_BYTES_PER_SEC = 2 * 22050;

// ─── Palette and color tables (fallout2-ce color.cc) ─────────────────────────

export class Palette {
  constructor(buf) {
    const d = new Uint8Array(buf);
    this.cmap = new Uint8Array(768);       // 6-bit components
    this.mapped = new Uint8Array(256);
    for (let i = 0; i < 256; i++) {
      const r = d[i * 3], g = d[i * 3 + 1], b = d[i * 3 + 2];
      if (r <= 63 && g <= 63 && b <= 63) {
        this.cmap.set([r, g, b], i * 3);
        this.mapped[i] = 1;
      }
    }
    this.colorTable = d.slice(768, 768 + 32768);  // rgb555 -> palette index
    this.rgba = new Uint32Array(256);              // little-endian ABGR for ImageData
    for (let i = 0; i < 256; i++) {
      const r = Math.min(255, this.cmap[i * 3] * 4);
      const g = Math.min(255, this.cmap[i * 3 + 1] * 4);
      const b = Math.min(255, this.cmap[i * 3 + 2] * 4);
      this.rgba[i] = (255 << 24) | (b << 16) | (g << 8) | r;
    }
    this._intensity = new Map();
    this._blend = new Map();
  }

  rgb2color(hex) {
    const r = (hex >> 16) & 0xff, g = (hex >> 8) & 0xff, b = hex & 0xff;
    return this.colorTable[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)];
  }

  color2rgb(c) {  // Color2RGB: 15-bit value from the 6-bit palette
    const r = this.cmap[c * 3] >> 1, g = this.cmap[c * 3 + 1] >> 1, b = this.cmap[c * 3 + 2] >> 1;
    return (r << 10) | (g << 5) | b;
  }

  // _setIntensityTableColor
  intensityTable(color) {
    let t = this._intensity.get(color);
    if (t) return t;
    t = new Uint8Array(256);
    if (this.mapped[color]) {
      const rgb = this.color2rgb(color);
      const r = (rgb & 0x7c00) >> 10, g = (rgb & 0x3e0) >> 5, b = rgb & 0x1f;
      let shift = 0;
      for (let i = 0; i < 128; i++) {
        t[i] = this.colorTable[(((r * shift) >> 16) << 10) | (((g * shift) >> 16) << 5) | ((b * shift) >> 16)];
        const lr = r + (((0x1f - r) * shift) >> 16);
        const lg = g + (((0x1f - g) * shift) >> 16);
        const lb = b + (((0x1f - b) * shift) >> 16);
        t[128 + i] = this.colorTable[(lr << 10) | (lg << 5) | lb];
        shift += 512;
      }
    }
    this._intensity.set(color, t);
    return t;
  }

  // _buildBlendTable: 14 rows of 256. Row 0 = identity, 1-7 = mix toward ch, 8-13 = shades of ch.
  blendTable(ch) {
    let t = this._blend.get(ch);
    if (t) return t;
    t = new Uint8Array(256 * 14);
    for (let i = 0; i < 256; i++) t[i] = i;
    const rgb = this.color2rgb(ch);
    const r = (rgb & 0x7c00) >> 10, g = (rgb & 0x3e0) >> 5, b = rgb & 0x1f;
    let r2 = r, g2 = g, b2 = b, weight = 6, row = 256;
    for (let j = 0; j < 7; j++) {
      for (let i = 0; i < 256; i++) {
        const c = this.color2rgb(i);
        const mr = (c & 0x7c00) >> 10, mg = (c & 0x3e0) >> 5, mb = c & 0x1f;
        const idx = ((((r2 + mr * weight) / 7) | 0) << 10) | ((((g2 + mg * weight) / 7) | 0) << 5) | (((b2 + mb * weight) / 7) | 0);
        t[row + i] = this.colorTable[idx];
      }
      weight--; row += 256; r2 += r; g2 += g; b2 += b;
    }
    const it = this.intensityTable(ch);
    let step = 0;
    for (let j = 0; j < 6; j++) {
      const v = it[((((step / 7) | 0) + 0xffff) / 512) | 0];
      t.fill(v, row, row + 256);
      step += 0x10000; row += 256;
    }
    this._blend.set(ch, t);
    return t;
  }
}

// ─── FRM ─────────────────────────────────────────────────────────────────────

export class Frm {
  constructor(buf, name = "") {
    const v = new DataView(buf);
    this.name = name;
    this.fps = v.getUint16(4);
    this.frameCount = v.getUint16(8);
    this.shiftX = [], this.shiftY = [], this.dataOffsets = [];
    for (let i = 0; i < 6; i++) {
      this.shiftX.push(v.getInt16(10 + i * 2));
      this.shiftY.push(v.getInt16(22 + i * 2));
      this.dataOffsets.push(v.getUint32(34 + i * 4));
    }
    // Only direction 0 (ROTATION_NE) is used for interface, background and head art.
    this.frames = [];
    let off = 62 + this.dataOffsets[0];
    for (let f = 0; f < this.frameCount; f++) {
      const w = v.getUint16(off), h = v.getUint16(off + 2), size = v.getUint32(off + 4);
      const x = v.getInt16(off + 8), y = v.getInt16(off + 10);
      this.frames.push({ w, h, x, y, data: new Uint8Array(buf, off + 12, w * h) });
      off += 12 + size;
    }
  }
}

// ─── AAF interface font (fallout2-ce font_manager.cc) ────────────────────────

export class AafFont {
  constructor(buf) {
    const v = new DataView(buf);
    if (v.getUint32(0) !== 0x41414646) throw new Error("not an AAF font");
    this.maxHeight = v.getUint16(4);
    this.letterSpacing = v.getUint16(6);
    this.wordSpacing = v.getUint16(8);
    this.lineSpacing = v.getUint16(10);
    this.glyphs = [];
    for (let i = 0; i < 256; i++) {
      const o = 12 + i * 8;
      this.glyphs.push({ w: v.getUint16(o), h: v.getUint16(o + 2), off: v.getUint32(o + 4) });
    }
    this.data = new Uint8Array(buf, 2060);
  }
  lineHeight() { return this.lineSpacing + this.maxHeight; }
  charWidth(ch) { return ch === 32 ? this.wordSpacing : this.glyphs[ch].w; }
  stringWidth(bytes) {
    let w = 0;
    for (const ch of bytes) w += this.charWidth(ch) + this.letterSpacing;
    return w;
  }
  // interfaceFontDrawImpl: blend each glyph pixel (0-9) into dest via the color's blend table.
  draw(buf, pitch, x, y, bytes, length, blend) {
    let px = x;
    for (const ch of bytes) {
      const cw = this.charWidth(ch);
      const end = px + cw + this.letterSpacing;
      if (end - x > length) break;
      const g = this.glyphs[ch];
      let src = g.off;
      const top = y + (this.maxHeight - g.h);
      for (let gy = 0; gy < g.h; gy++) {
        let d = (top + gy) * pitch + px;
        for (let gx = 0; gx < g.w; gx++, d++) {
          const val = this.data[src++];
          if (d >= 0 && d < buf.length) buf[d] = blend[(val << 8) + buf[d]];
        }
      }
      px = end;
    }
  }
}

// ─── cp1252 text ─────────────────────────────────────────────────────────────

const CP1252 = new TextDecoder("windows-1252");
const CP1252_REVERSE = (() => {
  const m = new Map();
  const all = CP1252.decode(Uint8Array.from({ length: 256 }, (_, i) => i));
  for (let i = 0; i < 256; i++) if (!m.has(all[i])) m.set(all[i], i);
  return m;
})();
export function decodeText(buf, encoding = "windows-1252") {
  return new TextDecoder(encoding === "cp1252" ? "windows-1252" : encoding).decode(buf);
}
export function encodeCp1252(str) {
  return Uint8Array.from([...str], (c) => CP1252_REVERSE.get(c) ?? 63);
}

// ─── LIP ─────────────────────────────────────────────────────────────────────
// Layout per vock.py write_lip() and fallout2-ce lipsLoad():
//   version, field_4, flags, field_10, field_1C (length in bytes), phonemeCount,
//   field_28, markerCount, name[8], ext[4], phonemes[phonemeCount] (u8),
//   markers[markerCount] {type u32, position u32}

export function parseLip(buf) {
  const v = new DataView(buf);
  const version = v.getUint32(0);
  if (version !== 2) throw new Error(`unsupported LIP version ${version}`);
  const h = {
    version,
    field4: v.getUint32(4), flags: v.getUint32(8), field10: v.getUint32(12),
    length: v.getUint32(16), field28: v.getUint32(24),
  };
  const pc = v.getUint32(20), mc = v.getUint32(28);
  const name = new TextDecoder("ascii").decode(new Uint8Array(buf, 32, 8)).replace(/\0.*$/s, "");
  const ext = new TextDecoder("ascii").decode(new Uint8Array(buf, 40, 4)).replace(/\0.*$/s, "");
  let o = 44;
  const phonemes = Array.from(new Uint8Array(buf, o, pc)); o += pc;
  const markers = [];
  for (let i = 0; i < mc; i++, o += 8) markers.push({ type: v.getUint32(o), pos: v.getUint32(o + 4) });
  const warnings = [];
  if (mc !== pc + 1) warnings.push(`marker count ${mc} != phoneme count ${pc} + 1`);
  if (markers.length && markers[0].pos !== 0) warnings.push(`marker 0 at ${markers[0].pos}, engine expects 0`);
  for (let i = 1; i < mc; i++) if (markers[i].pos < markers[i - 1].pos) warnings.push(`marker ${i} goes backwards`);
  phonemes.forEach((p, i) => { if (p >= PHONEME_COUNT) warnings.push(`phoneme ${i} has invalid code ${p}`); });
  if (mc <= 5) warnings.push(`only ${mc} markers: the engine logs "Too few markers to stop speech"`);
  // Editable model: one event per phoneme, plus the end position.
  // Marker types are kept as loaded: vock writes 1 for the first and last marker,
  // Interplay's files also use 1 to flag word starts. The engine ignores them.
  const events = phonemes.map((code, i) => ({ code, pos: i < markers.length ? markers[i].pos : 0, type: markers[i]?.type }));
  const last = markers.length > pc ? markers[markers.length - 1] : null;
  // Raw name bytes too: some Interplay files have junk after the terminating zero.
  const nameRaw = Array.from(new Uint8Array(buf, 32, 8));
  return { header: h, name, nameRaw, ext, events, end: last ? last.pos : h.length, endType: last?.type, warnings };
}

export function writeLip(lip) {
  const n = lip.events.length;
  const buf = new ArrayBuffer(44 + n + (n + 1) * 8);
  const v = new DataView(buf);
  const h = lip.header;
  v.setUint32(0, 2);
  v.setUint32(4, h.field4 ?? 0x5800);
  v.setUint32(8, h.flags ?? 0);
  v.setUint32(12, h.field10 ?? 0);
  v.setUint32(16, lip.end);
  v.setUint32(20, n);
  v.setUint32(24, h.field28 ?? 0);
  v.setUint32(28, n + 1);
  const name = new Uint8Array(buf, 32, 8);
  if (lip.nameRaw) name.set(lip.nameRaw);
  else [...(lip.name || "").slice(0, 8)].forEach((c, i) => (name[i] = c.charCodeAt(0) & 0x7f));
  const ext = lip.ext || "VOC";
  [...ext.slice(0, 3)].forEach((c, i) => v.setUint8(40 + i, c.charCodeAt(0)));
  let o = 44;
  lip.events.forEach((e) => v.setUint8(o++, e.code));
  lip.events.forEach((e, i) => {
    v.setUint32(o, e.type ?? (i === 0 ? 1 : 0)); v.setUint32(o + 4, i === 0 ? 0 : e.pos); o += 8;
  });
  v.setUint32(o, lip.endType ?? 1); v.setUint32(o + 4, lip.end);
  return buf;
}

export function newLip(stem, durationSec) {
  return {
    header: { version: 2, field4: 0x5800, flags: 0, field10: 0, field28: 0 },
    name: (stem || "").toLowerCase().slice(0, 8), ext: "VOC",
    events: [{ code: 0, pos: 0 }],
    end: Math.round(LIP_BYTES_PER_SEC * durationSec),
    warnings: [],
  };
}

// ─── TextGrid (Praat long or short text format) ──────────────────────────────

export function parseTextGrid(text) {
  // Tokenize: quoted strings ("" escapes a quote), numbers, and <exists>/flags.
  // Labels like `xmin =` and `item [1]:` are skipped by only taking values.
  const toks = [];
  const re = /"((?:[^"]|"")*)"|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|<(exists|absent)>/g;
  let m;
  const body = text.replace(/^﻿/, "");
  // Strip "name = " style keys so numbers inside identifiers (item [1]) don't count.
  const cleaned = body.replace(/item\s*\[\d*\]\s*:?/g, "").replace(/(intervals|points)\s*\[\d+\]\s*:?/g, "");
  while ((m = re.exec(cleaned))) {
    if (m[1] !== undefined) toks.push({ s: m[1].replace(/""/g, '"') });
    else if (m[2] !== undefined) toks.push({ n: parseFloat(m[2]) });
    else toks.push({ flag: m[3] });
  }
  let i = 0;
  const next = () => toks[i++];
  const str = () => { const t = next(); if (!t || t.s === undefined) throw new Error("TextGrid: expected string"); return t.s; };
  const num = () => { const t = next(); if (!t || t.n === undefined) throw new Error("TextGrid: expected number"); return t.n; };
  if (str() !== "ooTextFile") throw new Error("not a Praat text file");
  if (str() !== "TextGrid") throw new Error("not a TextGrid");
  const tg = { xmin: num(), xmax: num(), tiers: [] };
  if (toks[i] && toks[i].flag) i++;
  const nt = num();
  for (let k = 0; k < nt; k++) {
    const cls = str(), name = str();
    const tier = { cls, name, xmin: num(), xmax: num(), items: [] };
    const n = num();
    for (let j = 0; j < n; j++) {
      if (cls === "IntervalTier") tier.items.push({ xmin: num(), xmax: num(), text: str() });
      else tier.items.push({ time: num(), text: str() });
    }
    tg.tiers.push(tier);
  }
  return tg;
}

const q = (s) => '"' + String(s).replace(/"/g, '""') + '"';
const fmt = (x) => String(+x.toFixed(6));

export function writeTextGrid(tg) {
  const L = ['File type = "ooTextFile"', 'Object class = "TextGrid"', "",
    `xmin = ${fmt(tg.xmin)} `, `xmax = ${fmt(tg.xmax)} `, "tiers? <exists> ",
    `size = ${tg.tiers.length} `, "item []: "];
  tg.tiers.forEach((t, k) => {
    L.push(`    item [${k + 1}]:`, `        class = ${q(t.cls)} `, `        name = ${q(t.name)} `,
      `        xmin = ${fmt(t.xmin)} `, `        xmax = ${fmt(t.xmax)} `);
    if (t.cls === "IntervalTier") {
      L.push(`        intervals: size = ${t.items.length} `);
      t.items.forEach((it, j) => L.push(`        intervals [${j + 1}]:`,
        `            xmin = ${fmt(it.xmin)} `, `            xmax = ${fmt(it.xmax)} `, `            text = ${q(it.text)} `));
    } else {
      L.push(`        points: size = ${t.items.length} `);
      t.items.forEach((it, j) => L.push(`        points [${j + 1}]:`,
        `            number = ${fmt(it.time)} `, `            mark = ${q(it.text)} `));
    }
  });
  return L.join("\n") + "\n";
}

export function findTier(tg, re) {
  return tg?.tiers.find((t) => t.cls === "IntervalTier" && re.test(t.name)) || null;
}

// vock.py make_phoneme_converter + build_events_from_textgrid.
export function textGridToEvents(tg, table, mode) {
  const phones = findTier(tg, /^phones?$/i) || tg.tiers.find((t) => t.cls === "IntervalTier");
  if (!phones) throw new Error("TextGrid has no interval tier");
  const FALLBACK = 0x0d;
  const conv = mode === "arpa"
    ? (p) => table[p.trim().toUpperCase().replace(/\d/g, "")] ?? FALLBACK
    : (p) => table[p.trim().toLowerCase().replace(/[ˈˌː]/g, "")] ?? FALLBACK;
  const out = [];
  for (const it of phones.items) {
    const code = conv(it.text);
    if (!out.length || out[out.length - 1].code !== code) {
      out.push({ code, pos: Math.round(LIP_BYTES_PER_SEC * it.xmin) });
    }
  }
  if (!out.length) out.push({ code: 0, pos: 0 });
  out[0].pos = 0;  // write_lip always writes marker 0 at position 0
  return out;
}

// ─── WAV ─────────────────────────────────────────────────────────────────────

export function isAcm(buf) {
  const d = new Uint8Array(buf, 0, Math.min(4, buf.byteLength));
  return d[0] === 0x97 && d[1] === 0x28 && d[2] === 0x03;
}

// ─── ACM (Interplay audio) ───────────────────────────────────────────────────
// Port of fallout2-ce sound_decoder.cc: same band readers and 16-bit scale table,
// with the inverse transform written the way libacm's juggle_block() does it.
// Speech ACMs claim two channels but hold mono samples; the engine plays the
// sample stream as mono, and so does this.

const PACK3_3 = new Uint8Array(32), PACK5_3 = new Uint16Array(128), PACK11_2 = new Uint8Array(128);
for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let m = 0; m < 3; m++) PACK3_3[i + j * 3 + m * 9] = i + j * 4 + m * 16;
for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) for (let m = 0; m < 5; m++) PACK5_3[i + j * 5 + m * 25] = i + j * 8 + m * 64;
for (let i = 0; i < 11; i++) for (let j = 0; j < 11; j++) PACK11_2[i + j * 11] = i + j * 16;

export function decodeAcm(buf) {
  const src = new Uint8Array(buf);
  let pos = 0, hold = 0, bits = 0;
  const need = (n) => {
    while (bits < n) {
      const ch = pos < src.length ? src[pos++] : 0;
      hold = (hold | (ch << bits)) >>> 0;
      bits += 8;
    }
  };
  const drop = (n) => { hold >>>= n; bits -= n; };
  const get = (n) => { need(n); const v = hold & ((1 << n) - 1); drop(n); return v >>> 0; };

  if (get(24) !== 0x032897 || get(8) !== 1) throw new Error("not an ACM file");
  let fileCnt = get(16);
  fileCnt += get(16) * 65536;
  const channels = get(16), rate = get(16);
  const levels = get(4), spsb = get(12);
  const subbands = 1 << levels, total = spsb * subbands;
  const bsps = Math.max(1, ((2048 / subbands) | 0) - 2);
  const blockTotal = bsps * subbands;
  const samples = new Int32Array(total);
  const wrap = new Int32Array(2 * subbands + 2);
  const scale = new Int16Array(65536), B0 = 32768;  // AudioDecoder_scale0 at the middle

  let p = 0, i = 0;
  const put = (v) => { samples[p] = v; p += subbands; return --i === 0; };
  const readers = {
    0: () => { while (i) put(0); },
    3: (nb) => { const base = B0 - (1 << (nb - 1)); while (i) { const v = get(nb); put(scale[base + v]); } },
    17: () => {
      while (i) {
        need(3); const v = hold & 0xff;
        if (!(v & 1)) { drop(1); if (put(0) || put(0)) break; }
        else if (!(v & 2)) { drop(2); if (put(0)) break; }
        else { drop(3); put(scale[B0 + (v & 4 ? 1 : -1)]); }
      }
    },
    18: () => {
      while (i) {
        need(2); const v = hold;
        if (!(v & 1)) { drop(1); if (put(0)) break; }
        else { drop(2); put(scale[B0 + (v & 2 ? 1 : -1)]); }
      }
    },
    19: () => {
      const base = B0 - 1;
      while (i) {
        const v = PACK3_3[get(5)];
        if (put(scale[base + (v & 3)])) break;
        if (put(scale[base + ((v >> 2) & 3)])) break;
        put(scale[base + (v >> 4)]);
      }
    },
    20: () => {
      while (i) {
        need(4); const v = hold & 0xff;
        if (!(v & 1)) { drop(1); if (put(0) || put(0)) break; }
        else if (!(v & 2)) { drop(2); if (put(0)) break; }
        else { drop(4); put(scale[B0 + (v & 8 ? (v & 4 ? 2 : 1) : (v & 4 ? -1 : -2))]); }
      }
    },
    21: () => {
      while (i) {
        need(3); const v = hold & 0xff;
        if (!(v & 1)) { drop(1); if (put(0)) break; }
        else { drop(3); put(scale[B0 + (v & 4 ? (v & 2 ? 2 : 1) : (v & 2 ? -1 : -2))]); }
      }
    },
    22: () => {
      const base = B0 - 2;
      while (i) {
        const v = PACK5_3[get(7)];
        if (put(scale[base + (v & 7)])) break;
        if (put(scale[base + ((v >> 3) & 7)])) break;
        if (put(scale[base + (v >> 6)])) break;
      }
    },
    23: () => {
      while (i) {
        need(5); let v = hold;
        if (!(v & 1)) { drop(1); if (put(0) || put(0)) break; }
        else if (!(v & 2)) { drop(2); if (put(0)) break; }
        else if (!(v & 4)) { drop(4); if (put(scale[B0 + (v & 8 ? 1 : -1)])) break; }
        else { drop(5); v = (v >> 3) & 3; if (v >= 2) v += 3; put(scale[B0 + v - 3]); }
      }
    },
    24: () => {
      while (i) {
        need(4); let v = hold & 0xff;
        if (!(v & 1)) { drop(1); if (put(0)) break; }
        else if (!(v & 2)) { drop(3); if (put(scale[B0 + (v & 4 ? 1 : -1)])) break; }
        else { drop(4); v = (v >> 2) & 3; if (v >= 2) v += 3; put(scale[B0 + v - 3]); }
      }
    },
    26: () => {
      while (i) {
        need(5); let v = hold;
        if (!(v & 1)) { drop(1); if (put(0) || put(0)) break; }
        else if (!(v & 2)) { drop(2); if (put(0)) break; }
        else { drop(5); v = (v >> 2) & 7; if (v >= 4) v += 1; put(scale[B0 + v - 4]); }
      }
    },
    27: () => {
      while (i) {
        need(4); let v = hold;
        if (!(v & 1)) { drop(1); if (put(0)) break; }
        else { drop(4); v = (v >> 1) & 7; if (v >= 4) v += 1; put(scale[B0 + v - 4]); }
      }
    },
    29: () => {
      while (i) {
        const v = PACK11_2[get(7)];
        if (put(scale[B0 + (v & 0x0f) - 5])) break;
        put(scale[B0 + (v >> 4) - 5]);
      }
    },
  };

  // Returns false when the block must not be untransformed (Fmt31 or a bad band).
  const readBands = () => {
    const pw = get(4), step = get(16);
    const n = 1 << pw;
    for (let k = 0; k < n; k++) { scale[B0 + k] = k * step; scale[B0 - 1 - k] = -(k + 1) * step; }
    for (let band = 0; band < subbands; band++) {
      const fmt = get(5);
      if (fmt === 31) {
        // Fmt31 (some Russian ACMs): raw 16-bit samples for the whole block.
        for (let k = 0; k < total; k++) samples[k] = ((get(16) << 16) >> 16) << levels;
        return false;
      }
      p = band; i = spsb;
      const r = fmt >= 3 && fmt <= 16 ? readers[3] : readers[fmt];
      if (!r) return false;
      if (i) r(fmt);
    }
    return true;
  };

  const juggle = (w, b, subLen, subCount) => {
    for (let k = 0; k < subLen; k++) {
      let q = b + k, r0 = wrap[w], r1 = wrap[w + 1];
      for (let j = 0; j < subCount >> 1; j++) {
        const r2 = samples[q]; samples[q] = r1 * 2 + r0 + r2; q += subLen;
        const r3 = samples[q]; samples[q] = r2 * 2 - r1 - r3; q += subLen;
        r0 = r2; r1 = r3;
      }
      wrap[w++] = r0; wrap[w++] = r1;
    }
  };
  const untransform = () => {
    if (!levels) return;
    let off = 0, remaining = spsb;
    while (remaining > 0) {
      let subLen = subbands >> 1, subCount = Math.min(bsps, remaining) * 2, w = 0;
      juggle(w, off, subLen, subCount); w += subLen * 2;
      for (let k = 0, q = off; k < subCount; k++, q += subLen) samples[q]++;
      while (subLen > 1) { subLen >>= 1; subCount *= 2; juggle(w, off, subLen, subCount); w += subLen * 2; }
      off += blockTotal; remaining -= bsps;
    }
  };

  const out = new Int16Array(fileCnt);
  let done = 0;
  while (done < fileCnt) {
    if (readBands()) untransform();
    const n = Math.min(total, fileCnt - done);
    for (let k = 0; k < n; k++) out[done + k] = samples[k] >> levels;
    done += n;
    if (pos >= src.length + 8 && n === total && done < fileCnt) {
      // Past the end of the data: the engine keeps decoding zeros; stop early instead.
      break;
    }
  }
  return { rate, channels, samples: out };
}
