// LIP Studio: UI, timeline editor and engine-accurate lip-sync playback.

import {
  Palette, Frm, AafFont, parseLip, writeLip, newLip, parseTextGrid, writeTextGrid,
  textGridToEvents, findTier, frameForCode, decodeText, encodeCp1252, isAcm, decodeAcm,
  CODE_NAMES, CODE_EXAMPLES, PHONEME_COUNT, LIP_BYTES_PER_SEC,
} from "./formats.js";
import { DialogScreen } from "./screen.js";

const $ = (id) => document.getElementById(id);
const FRAME_COLORS = ["#4a4f45", "#d9534f", "#f0ad4e", "#e6d84a", "#5cb85c", "#3fc1c9", "#5b8def", "#9b6bdf", "#e46fb5"];

// ─── State ───────────────────────────────────────────────────────────────────

const S = {
  cfg: null, speech: {}, heads: [], backgrounds: [],
  folder: null, stem: null,
  audio: null,          // { buffer: AudioBuffer, label }
  lip: null, lipLabel: "",
  tg: null, tgLabel: "",
  txt: "", txtLabel: "",
  dirty: { lip: false, tg: false, txt: false },
  sel: null,            // { kind: "lip", i } | { kind: "tier", t, i }
  view: { t0: 0, pps: 200 },
  undo: [], redo: [],
  play: { on: false, src: null, ctxStart: 0, offset: 0, pos: 0 },
  lastFrame: -1,
  headInfo: "",
};
let screen = null, pal = null, actx = null;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function status(msg, err = false) {
  const el = $("status");
  el.textContent = msg;
  el.title = msg;
  el.classList.toggle("err", err);
}

async function fetchBuf(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error; } catch { /* body not JSON */ }
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.arrayBuffer();
}
const fetchJson = async (url) => JSON.parse(new TextDecoder().decode(await fetchBuf(url)));
const gameFile = (path) => fetchBuf("/api/game?path=" + encodeURIComponent(path));
const stemUrl = (kind) => `/api/stem?folder=${S.folder}&stem=${S.stem}&kind=${kind}`;

function download(name, data, type = "application/octet-stream") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([data], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const duration = () => S.audio?.buffer.duration
  ?? (S.lip ? S.lip.end / LIP_BYTES_PER_SEC : null) ?? S.tg?.xmax ?? 10;
const fmtT = (t) => t.toFixed(3);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ─── Engine lip-sync emulation (fallout2-ce lips.cc lipsTicker) ──────────────
// Phoneme i becomes current once the audio byte position is strictly past marker i.
// Before anything is passed the current phoneme is phoneme 0 (set by lipsLoad), and
// once the end marker is passed the engine resets to phoneme 0 and stops the speech.

function eventIndexAt(pos) {
  const ev = S.lip.events;
  let lo = 0, hi = ev.length - 1, k = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (ev[m].pos < pos) { k = m; lo = m + 1; } else hi = m - 1;
  }
  return k;
}

function codeAtPos(pos) {
  if (!S.lip || !S.lip.events.length) return 0;
  if (pos > S.lip.end) return S.lip.events[0].code;
  const k = eventIndexAt(pos);
  return S.lip.events[Math.max(0, k)].code;
}

// Frames the engine would have drawn from the start up to pos (for the running x offset).
function frameHistory(pos) {
  const out = [];
  if (!S.lip) return out;
  let last = -1;
  const push = (f) => { if (f !== last) { out.push(f); last = f; } };
  push(frameForCode(S.lip.events[0]?.code ?? 0));
  const k = Math.min(eventIndexAt(pos), S.lip.events.length - 1);
  for (let i = 0; i <= k; i++) push(frameForCode(S.lip.events[i].code));
  if (pos > S.lip.end) push(frameForCode(S.lip.events[0].code));
  return out;
}

function updateHead(t, seeking) {
  const pos = t * LIP_BYTES_PER_SEC;
  const code = codeAtPos(pos);
  const frame = frameForCode(code);
  if (seeking) {
    screen.replayFrames(frameHistory(pos));
  } else if (frame !== S.lastFrame) {
    screen.showFrame(frame);
  }
  S.lastFrame = frame;
  screen.render();
  const k = S.lip ? eventIndexAt(pos) : -1;
  $("readout").textContent = S.lip
    ? `event ${Math.max(0, k)}  code 0x${code.toString(16).padStart(2, "0")} ${CODE_NAMES[code] ?? "?"}  → frame ${frame}`
    : "no LIP loaded";
  for (const el of document.querySelectorAll(".frames .fr")) el.classList.toggle("on", +el.dataset.f === frame);
}

// ─── Audio ───────────────────────────────────────────────────────────────────

function audioCtx() {
  if (!actx) actx = new AudioContext();
  return actx;
}

async function setAudioFromBuf(buf, label) {
  stop();
  let decoded;
  if (isAcm(buf)) {
    const acm = decodeAcm(buf);
    decoded = audioCtx().createBuffer(1, Math.max(1, acm.samples.length), acm.rate || 22050);
    const ch = decoded.getChannelData(0);
    for (let i = 0; i < acm.samples.length; i++) ch[i] = acm.samples[i] / 32768;
  } else {
    decoded = await audioCtx().decodeAudioData(buf);
  }
  S.audio = { buffer: decoded, label };
  S.play.pos = 0;
  renderFiles();
  zoomFit();
}

function playPos() {
  const p = S.play;
  if (!p.on) return p.pos;
  return p.offset + (actx.currentTime - p.ctxStart) * p.rate;
}

function play() {
  if (!S.audio) { status("No audio loaded", true); return; }
  const ctx = audioCtx();
  ctx.resume();
  const p = S.play;
  if (p.pos >= S.audio.buffer.duration - 0.01) p.pos = 0;
  const src = ctx.createBufferSource();
  src.buffer = S.audio.buffer;
  p.rate = +$("rateSel").value;
  src.playbackRate.value = p.rate;
  src.connect(ctx.destination);
  src.start(0, p.pos);
  src.onended = () => {
    if (p.src !== src) return;
    p.on = false; p.src = null;
    p.pos = S.audio.buffer.duration;
    if ($("loopChk").checked) { p.pos = 0; play(); return; }
    // Speech over: the engine resets to phoneme 0.
    updateHead(p.pos + 1e-3, false);
    drawTimeline();
    $("playBtn").innerHTML = "&#9654;";
  };
  p.src = src; p.on = true; p.ctxStart = ctx.currentTime; p.offset = p.pos;
  S.lastFrame = -1;
  screen.replayFrames(frameHistory(p.pos * LIP_BYTES_PER_SEC));
  $("playBtn").innerHTML = "&#10074;&#10074;";
  requestAnimationFrame(tick);
}

function pause() {
  const p = S.play;
  if (!p.on) return;
  p.pos = playPos();
  p.on = false;
  const src = p.src; p.src = null;
  try { src.stop(); } catch { /* already stopped */ }
  $("playBtn").innerHTML = "&#9654;";
  seek(p.pos);
}

function stop() {
  pause();
  seek(0);
}

function seek(t) {
  const wasOn = S.play.on;
  if (wasOn) { const src = S.play.src; S.play.src = null; S.play.on = false; try { src.stop(); } catch { /* */ } }
  S.play.pos = Math.max(0, Math.min(t, duration()));
  if (wasOn) play();
  else { updateHead(S.play.pos, true); drawTimeline(); }
}

function tick() {
  if (!S.play.on) return;
  const t = playPos();
  updateHead(t, false);
  // Keep the playhead in view.
  const w = tlWidth();
  const x = (t - S.view.t0) * S.view.pps;
  if (x > w * 0.92 || x < 0) { S.view.t0 = Math.max(0, t - (w * 0.1) / S.view.pps); syncScroll(); }
  drawTimeline();
  requestAnimationFrame(tick);
}

// ─── Undo ────────────────────────────────────────────────────────────────────

function snapshot() {
  return JSON.stringify({ lip: S.lip, tg: S.tg, dirty: S.dirty });
}
function restore(snap) {
  const o = JSON.parse(snap);
  S.lip = o.lip; S.tg = o.tg; S.dirty = o.dirty;
  S.sel = null;
  refreshAll();
}
function mutate(kind, fn) {
  S.undo.push(snapshot());
  if (S.undo.length > 300) S.undo.shift();
  S.redo = [];
  fn();
  S.dirty[kind] = true;
  refreshAll();
}
function undo() { if (S.undo.length) { S.redo.push(snapshot()); restore(S.undo.pop()); } }
function redo() { if (S.redo.length) { S.undo.push(snapshot()); restore(S.redo.pop()); } }

// ─── Timeline ────────────────────────────────────────────────────────────────

const RULER_H = 20, WAVE_H = 90, LIP_H = 42, TIER_H = 30;
const tl = $("timeline");
const tlCtx = tl.getContext("2d");
let drag = null;

function rows() {
  const r = [{ kind: "ruler", y: 0, h: RULER_H }, { kind: "wave", y: RULER_H, h: WAVE_H },
    { kind: "lip", y: RULER_H + WAVE_H, h: LIP_H }];
  let y = RULER_H + WAVE_H + LIP_H;
  (S.tg?.tiers || []).forEach((t, i) => {
    if (t.cls !== "IntervalTier") return;
    r.push({ kind: "tier", t: i, y, h: TIER_H });
    y += TIER_H;
  });
  return r;
}
const tlWidth = () => $("timelineBox").clientWidth;
const xOf = (t) => (t - S.view.t0) * S.view.pps;
const tOf = (x) => S.view.t0 + x / S.view.pps;

function resizeTimeline() {
  const r = rows();
  const h = r[r.length - 1].y + r[r.length - 1].h;
  const dpr = window.devicePixelRatio || 1;
  const w = tlWidth();
  tl.width = Math.round(w * dpr);
  tl.height = Math.round(h * dpr);
  tl.style.height = h + "px";
  tlCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawTimeline() {
  const w = tlWidth();
  const r = rows();
  const h = r[r.length - 1].y + r[r.length - 1].h;
  if (Math.abs(tl.height - h * (window.devicePixelRatio || 1)) > 1 || Math.abs(tl.width - w * (window.devicePixelRatio || 1)) > 1) resizeTimeline();
  const c = tlCtx;
  c.clearRect(0, 0, w, h);
  c.font = "11px ui-sans-serif, system-ui, sans-serif";
  c.textBaseline = "middle";
  for (const row of r) {
    c.fillStyle = row.kind === "lip" ? "#15180f" : row.kind === "ruler" ? "#1b1e17" : "#0c0e0a";
    c.fillRect(0, row.y, w, row.h);
    if (row.kind === "ruler") drawRuler(c, row, w);
    if (row.kind === "wave") drawWave(c, row, w);
    if (row.kind === "lip") drawLipRow(c, row, w);
    if (row.kind === "tier") drawTierRow(c, row, w);
    c.fillStyle = "#343a2a";
    c.fillRect(0, row.y + row.h - 1, w, 1);
  }
  // End of audio / LIP.
  if (S.audio) {
    const x = xOf(S.audio.buffer.duration);
    c.fillStyle = "rgba(255,255,255,.08)";
    c.fillRect(x, RULER_H, w - x, h - RULER_H);
  }
  // Boundaries moving together with the dragged one.
  if (drag?.group?.length > 1) {
    const gx = Math.round(xOf(boundaryTime(drag.group[0]))) + 0.5;
    c.strokeStyle = "#f2b33d";
    c.lineWidth = 2;
    c.beginPath(); c.moveTo(gx, RULER_H); c.lineTo(gx, h); c.stroke();
    c.lineWidth = 1;
  }
  // Playhead.
  const px = Math.round(xOf(playPos())) + 0.5;
  c.strokeStyle = "#3cf06e";
  c.lineWidth = 1;
  c.beginPath(); c.moveTo(px, 0); c.lineTo(px, h); c.stroke();
  $("timeLbl").textContent = `${fmtT(playPos())} / ${fmtT(duration())}`;
}

function drawRuler(c, row, w) {
  const steps = [0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30];
  const step = steps.find((s) => s * S.view.pps >= 60) || 60;
  const t0 = Math.floor(S.view.t0 / step) * step;
  c.fillStyle = "#8a9478";
  c.strokeStyle = "#4a5238";
  for (let t = t0; xOf(t) < w; t += step) {
    const x = Math.round(xOf(t)) + 0.5;
    c.beginPath(); c.moveTo(x, row.y + 12); c.lineTo(x, row.y + row.h); c.stroke();
    c.fillText(t.toFixed(step < 0.01 ? 3 : step < 1 ? 2 : 0), x + 3, row.y + 8);
  }
}

function drawWave(c, row, w) {
  if (!S.audio) {
    c.fillStyle = "#4a5238";
    c.fillText("no audio", 8, row.y + row.h / 2);
    return;
  }
  const b = S.audio.buffer;
  const data = b.getChannelData(0);
  const sr = b.sampleRate;
  const mid = row.y + row.h / 2, amp = row.h / 2 - 3;
  c.fillStyle = "#2f7d45";
  for (let x = 0; x < w; x++) {
    const a = Math.floor(tOf(x) * sr), z = Math.floor(tOf(x + 1) * sr);
    if (z <= 0 || a >= data.length) continue;
    let mn = 1, mx = -1;
    const end = Math.min(data.length, Math.max(z, a + 1));
    const stride = Math.max(1, Math.floor((end - a) / 400));
    for (let i = Math.max(0, a); i < end; i += stride) { const v = data[i]; if (v < mn) mn = v; if (v > mx) mx = v; }
    c.fillRect(x, mid - mx * amp, 1, Math.max(1, (mx - mn) * amp));
  }
}

function drawLipRow(c, row, w) {
  c.fillStyle = "#8a9478";
  if (!S.lip) { c.fillText("no LIP — load one, or New LIP / TextGrid → LIP", 8, row.y + row.h / 2); return; }
  const ev = S.lip.events;
  for (let i = 0; i < ev.length; i++) {
    const a = ev[i].pos / LIP_BYTES_PER_SEC;
    const b = (i + 1 < ev.length ? ev[i + 1].pos : S.lip.end) / LIP_BYTES_PER_SEC;
    const x0 = xOf(a), x1 = xOf(b);
    if (x1 < 0 || x0 > w) continue;
    const f = frameForCode(ev[i].code);
    const selected = S.sel?.kind === "lip" && S.sel.i === i;
    c.fillStyle = FRAME_COLORS[f];
    c.globalAlpha = selected ? 1 : 0.55;
    c.fillRect(x0, row.y + 4, Math.max(1, x1 - x0), row.h - 9);
    c.globalAlpha = 1;
    c.fillStyle = "#e9eedf";
    c.fillRect(Math.round(x0), row.y, 1, row.h - 1);
    if (selected) { c.strokeStyle = "#f2b33d"; c.lineWidth = 2; c.strokeRect(x0 + 1, row.y + 3, Math.max(1, x1 - x0 - 2), row.h - 7); c.lineWidth = 1; }
    if (x1 - x0 > 18) {
      c.fillStyle = "#0c0e0a";
      c.save(); c.beginPath(); c.rect(x0, row.y, x1 - x0, row.h); c.clip();
      c.fillText(CODE_NAMES[ev[i].code] ?? `#${ev[i].code}`, x0 + 3, row.y + 14);
      c.fillText(String(f), x0 + 3, row.y + 29);
      c.restore();
    }
  }
  const xe = xOf(S.lip.end / LIP_BYTES_PER_SEC);
  c.fillStyle = "#ff5a4a";
  c.fillRect(Math.round(xe), row.y, 2, row.h - 1);
}

function drawTierRow(c, row, w) {
  const tier = S.tg.tiers[row.t];
  c.fillStyle = "#5c6650";
  c.fillText(tier.name, 4, row.y + 8);
  tier.items.forEach((it, i) => {
    const x0 = xOf(it.xmin), x1 = xOf(it.xmax);
    if (x1 < 0 || x0 > w) return;
    const selected = S.sel?.kind === "tier" && S.sel.t === row.t && S.sel.i === i;
    if (selected) { c.fillStyle = "rgba(242,179,61,.25)"; c.fillRect(x0, row.y, x1 - x0, row.h - 1); }
    else if (it.text) { c.fillStyle = "rgba(60,240,110,.07)"; c.fillRect(x0, row.y, x1 - x0, row.h - 1); }
    c.fillStyle = "#8fbf86";
    c.fillRect(Math.round(x0), row.y, 1, row.h - 1);
    if (it.text && x1 - x0 > 6) {
      c.save(); c.beginPath(); c.rect(x0, row.y, x1 - x0, row.h); c.clip();
      c.fillStyle = selected ? "#f2b33d" : "#cfd8bf";
      const tw = c.measureText(it.text).width;
      c.fillText(it.text, Math.max(x0 + 2, (x0 + x1 - tw) / 2), row.y + row.h / 2 + 3);
      c.restore();
    }
  });
}

// Boundaries a drag can grab, nearest first.
function boundaryAt(x, row) {
  const tol = 5;
  if (row.kind === "lip" && S.lip) {
    let best = null;
    S.lip.events.forEach((e, i) => {
      if (i === 0) return;  // marker 0 must stay at 0
      const d = Math.abs(xOf(e.pos / LIP_BYTES_PER_SEC) - x);
      if (d <= tol && (!best || d < best.d)) best = { d, kind: "lip", i };
    });
    const de = Math.abs(xOf(S.lip.end / LIP_BYTES_PER_SEC) - x);
    if (de <= tol && (!best || de < best.d)) best = { d: de, kind: "lipEnd" };
    return best;
  }
  if (row.kind === "tier") {
    const items = S.tg.tiers[row.t].items;
    let best = null;
    for (let i = 1; i < items.length; i++) {
      const d = Math.abs(xOf(items[i].xmin) - x);
      if (d <= tol && (!best || d < best.d)) best = { d, kind: "tier", t: row.t, i };
    }
    return best;
  }
  return null;
}

// exclude: row keys ("lip", "tier<N>") whose boundaries are being moved.
function snapTargets(exclude) {
  const out = [];
  if (S.lip && !exclude.includes("lip")) S.lip.events.forEach((e) => out.push(e.pos / LIP_BYTES_PER_SEC));
  S.tg?.tiers.forEach((t, ti) => {
    if (t.cls !== "IntervalTier" || exclude.includes("tier" + ti)) return;
    t.items.forEach((it) => out.push(it.xmin));
  });
  return out;
}

function snap(t, exclude) {
  if (!$("snapChk").checked) return t;
  let best = t, bd = 6 / S.view.pps;
  for (const s of snapTargets(exclude)) if (Math.abs(s - t) < bd) { bd = Math.abs(s - t); best = s; }
  return best;
}

// ─── Linked boundaries ───────────────────────────────────────────────────────
// A boundary is { kind: "lip", i } (LIP event i >= 1) or { kind: "tier", t, i }
// (start of interval i >= 1 in tier t). With "link" on, moving one moves every
// boundary on the other rows that sits at the same time.

const LINK_TOL = 0.001;  // LIP positions are whole bytes, TextGrid times are floats

function boundaryTime(m) {
  return m.kind === "lip" ? S.lip.events[m.i].pos / LIP_BYTES_PER_SEC : S.tg.tiers[m.t].items[m.i].xmin;
}

function boundaryRange(m) {
  if (m.kind === "lip") {
    const ev = S.lip.events;
    return [(ev[m.i - 1].pos + 1) / LIP_BYTES_PER_SEC,
      ((m.i + 1 < ev.length ? ev[m.i + 1].pos : S.lip.end) - 1) / LIP_BYTES_PER_SEC];
  }
  const items = S.tg.tiers[m.t].items;
  return [items[m.i - 1].xmin + 0.001, items[m.i].xmax - 0.001];
}

function linkedGroup(m) {
  if (!$("linkChk").checked) return [m];
  const t0 = boundaryTime(m);
  const out = [m];
  if (S.lip && m.kind !== "lip") {
    S.lip.events.forEach((e, i) => {
      if (i > 0 && Math.abs(e.pos / LIP_BYTES_PER_SEC - t0) <= LINK_TOL) out.push({ kind: "lip", i });
    });
  }
  S.tg?.tiers.forEach((tier, t) => {
    if (tier.cls !== "IntervalTier" || (m.kind === "tier" && m.t === t)) return;
    tier.items.forEach((it, i) => {
      if (i > 0 && Math.abs(it.xmin - t0) <= LINK_TOL) out.push({ kind: "tier", t, i });
    });
  });
  return out;
}

const groupRows = (g) => g.map((m) => (m.kind === "lip" ? "lip" : "tier" + m.t));

// Moves every boundary in the group to v, clamped so no row's intervals invert.
function moveGroup(g, v) {
  let lo = -Infinity, hi = Infinity;
  for (const m of g) { const [a, b] = boundaryRange(m); lo = Math.max(lo, a); hi = Math.min(hi, b); }
  if (lo > hi) return;
  v = Math.max(lo, Math.min(hi, v));
  for (const m of g) {
    if (m.kind === "lip") {
      S.lip.events[m.i].pos = Math.round(v * LIP_BYTES_PER_SEC);
      S.dirty.lip = true;
    } else {
      const items = S.tg.tiers[m.t].items;
      items[m.i - 1].xmax = v; items[m.i].xmin = v;
      S.dirty.tg = true;
    }
  }
}

function rowAt(y) { return rows().find((r) => y >= r.y && y < r.y + r.h); }

tl.addEventListener("mousedown", (e) => {
  const rect = tl.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  const row = rowAt(y);
  if (!row) return;
  const t = tOf(x);
  const b = boundaryAt(x, row);
  if (b) {
    drag = { ...b, moved: false, before: snapshot(), clickT: t, row };
    if (b.kind !== "lipEnd") drag.group = linkedGroup(b);
    if (b.kind === "lip") S.sel = { kind: "lip", i: b.i };
    if (b.kind === "tier") S.sel = { kind: "tier", t: b.t, i: b.i };
    renderInspector();
    drawTimeline();
    return;
  }
  selectAt(row, t);
  drag = { kind: "seek" };
  seek(t);
});

function selectAt(row, t) {
  if (row.kind === "lip" && S.lip) {
    const k = Math.max(0, eventIndexAt(t * LIP_BYTES_PER_SEC));
    if (t * LIP_BYTES_PER_SEC <= S.lip.end) S.sel = { kind: "lip", i: k };
  } else if (row.kind === "tier") {
    const i = S.tg.tiers[row.t].items.findIndex((it) => t >= it.xmin && t < it.xmax);
    if (i >= 0) S.sel = { kind: "tier", t: row.t, i };
  }
  renderInspector();
}

window.addEventListener("mousemove", (e) => {
  const rect = tl.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  if (!drag) {
    const row = rowAt(y);
    tl.style.cursor = row && x >= 0 && x <= rect.width && boundaryAt(x, row) ? "ew-resize" : "crosshair";
    return;
  }
  const t = Math.max(0, tOf(x));
  if (drag.kind === "seek") { seek(t); return; }
  drag.moved = true;
  if (drag.kind === "lipEnd") {
    const ev = S.lip.events;
    S.lip.end = Math.max(ev[ev.length - 1].pos + 1, Math.round(snap(t, ["lip"]) * LIP_BYTES_PER_SEC));
    S.dirty.lip = true;
  } else {
    moveGroup(drag.group, snap(t, groupRows(drag.group)));
  }
  drawTimeline();
  renderInspector();
  if (!S.play.on) updateHead(S.play.pos, true);
});

window.addEventListener("mouseup", () => {
  const d = drag;
  drag = null;
  if (!d) return;
  if (d.moved && d.before) {
    S.undo.push(d.before); S.redo = [];
    renderDirty();
  } else if (d.clickT !== undefined) {
    // Pressed on a boundary without dragging: treat it as a plain click.
    selectAt(d.row, d.clickT);
    seek(d.clickT);
  }
});

tl.addEventListener("wheel", (e) => {
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) {
    const rect = tl.getBoundingClientRect();
    zoomAround(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - rect.left);
  } else {
    const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) / S.view.pps;
    S.view.t0 = Math.max(0, Math.min(S.view.t0 + d, Math.max(0, duration() - tlWidth() / S.view.pps / 2)));
    syncScroll();
    drawTimeline();
  }
}, { passive: false });

tl.addEventListener("dblclick", (e) => {
  const rect = tl.getBoundingClientRect();
  const row = rowAt(e.clientY - rect.top);
  if (row?.kind === "tier" && S.sel?.kind === "tier") {
    const inp = $("insLabel");
    if (inp) { inp.focus(); inp.select(); }
  } else if (row?.kind === "lip" && S.sel?.kind === "lip") {
    $("insCodeSel")?.focus();
  }
});

function zoomAround(f, x) {
  const t = tOf(x);
  S.view.pps = Math.max(10, Math.min(20000, S.view.pps * f));
  S.view.t0 = Math.max(0, t - x / S.view.pps);
  syncScroll();
  drawTimeline();
}
function zoomFit() {
  S.view.pps = Math.max(10, (tlWidth() - 10) / Math.max(0.5, duration()));
  S.view.t0 = 0;
  syncScroll();
  drawTimeline();
}
function syncScroll() {
  const span = Math.max(0.0001, duration() - tlWidth() / S.view.pps);
  $("hscroll").value = span > 0 ? Math.round((S.view.t0 / span) * 1000) : 0;
}
$("hscroll").addEventListener("input", (e) => {
  const span = Math.max(0, duration() - tlWidth() / S.view.pps);
  S.view.t0 = (e.target.value / 1000) * span;
  drawTimeline();
});

// ─── Editing operations ──────────────────────────────────────────────────────

function insertEvent() {
  if (!S.lip) { status("No LIP: use New LIP first", true); return; }
  const pos = Math.round(playPos() * LIP_BYTES_PER_SEC);
  if (pos <= 0 || pos >= S.lip.end) { status("Playhead must be inside the LIP", true); return; }
  const ev = S.lip.events;
  if (ev.some((e) => e.pos === pos)) return;
  // Default code: whatever the phones tier says at the playhead, else repeat the current one.
  let code = codeAtPos(pos);
  const phones = findTier(S.tg, /^phones?$/i);
  if (phones && S.cfg) {
    const it = phones.items.find((x) => playPos() >= x.xmin && playPos() < x.xmax);
    if (it) code = textGridToEvents({ tiers: [{ cls: "IntervalTier", name: "phones", items: [it] }] },
      S.cfg.phonemeTable, S.cfg.phonemeMode)[0].code;
  }
  mutate("lip", () => {
    const i = eventIndexAt(pos) + 1;
    ev.splice(i, 0, { code, pos });
    S.sel = { kind: "lip", i };
  });
}

function deleteSelection() {
  const s = S.sel;
  if (!s) return;
  if (s.kind === "lip") {
    if (S.lip.events.length <= 1) return;
    mutate("lip", () => {
      const ev = S.lip.events;
      if (s.i === 0) { ev[0].code = ev[1].code; ev.splice(1, 1); }  // marker 0 stays at 0
      else ev.splice(s.i, 1);
      S.sel = { kind: "lip", i: Math.max(0, Math.min(s.i - 1, ev.length - 1)) };
    });
  } else if (s.kind === "tier") {
    // Remove the selected interval's left boundary (merge into the previous one).
    const items = S.tg.tiers[s.t].items;
    if (s.i === 0) return mergeInterval();
    mutate("tg", () => {
      const prev = items[s.i - 1], cur = items[s.i];
      prev.xmax = cur.xmax;
      prev.text = [prev.text, cur.text].filter(Boolean).join(" ");
      items.splice(s.i, 1);
      S.sel = { kind: "tier", t: s.t, i: s.i - 1 };
    });
  }
}

function splitInterval() {
  const s = S.sel;
  if (s?.kind !== "tier") { status("Select a TextGrid interval first", true); return; }
  const items = S.tg.tiers[s.t].items, it = items[s.i], t = playPos();
  if (t <= it.xmin + 0.001 || t >= it.xmax - 0.001) { status("Put the playhead inside the selected interval", true); return; }
  mutate("tg", () => {
    items.splice(s.i + 1, 0, { xmin: t, xmax: it.xmax, text: "" });
    it.xmax = t;
    S.sel = { kind: "tier", t: s.t, i: s.i + 1 };
  });
}

function mergeInterval() {
  const s = S.sel;
  if (s?.kind !== "tier") { status("Select a TextGrid interval first", true); return; }
  const items = S.tg.tiers[s.t].items;
  if (s.i + 1 >= items.length) return;
  mutate("tg", () => {
    const a = items[s.i], b = items[s.i + 1];
    a.xmax = b.xmax;
    a.text = [a.text, b.text].filter(Boolean).join(" ");
    items.splice(s.i + 1, 1);
  });
}

function rebuildLip() {
  if (!S.tg) { status("No TextGrid loaded", true); return; }
  if (S.lip && S.dirty.lip && !confirm("Replace the edited LIP events with ones built from the TextGrid?")) return;
  try {
    const events = textGridToEvents(S.tg, S.cfg.phonemeTable, S.cfg.phonemeMode);
    mutate("lip", () => {
      const lip = S.lip || newLip(S.stem || "", duration());
      lip.events = events;
      // Keep an existing end marker: vock sets it from the WAV length, which is a few ms
      // shorter than the decoded ACM (encoder delay).
      if (!S.lip) lip.end = Math.round(LIP_BYTES_PER_SEC * (S.audio?.buffer.duration ?? S.tg.xmax));
      lip.warnings = [];
      S.lip = lip;
      S.lipLabel = S.lipLabel || `${S.stem || "new"}.lip (from TextGrid)`;
      S.sel = null;
    });
    status(`Built ${events.length} events from the phones tier`);
  } catch (err) { status(err.message, true); }
}

function makeNewLip() {
  if (S.lip && !confirm("Discard the current LIP and start an empty one?")) return;
  mutate("lip", () => {
    S.lip = newLip(S.stem || "", duration());
    S.lipLabel = `${S.stem || "new"}.lip (new)`;
    S.sel = { kind: "lip", i: 0 };
  });
}

function fitEnd() {
  if (!S.lip || !S.audio) return;
  mutate("lip", () => {
    const ev = S.lip.events;
    S.lip.end = Math.max(ev[ev.length - 1].pos + 1, Math.round(S.audio.buffer.duration * LIP_BYTES_PER_SEC));
  });
}

function setCode(i, code) {
  if (!S.lip || S.lip.events[i]?.code === code) return;
  mutate("lip", () => { S.lip.events[i].code = code; });
  if (!S.play.on) updateHead(S.play.pos, true);
}

function selectRelative(d) {
  const s = S.sel;
  if (!s) return;
  if (s.kind === "lip") {
    const i = Math.max(0, Math.min(S.lip.events.length - 1, s.i + d));
    S.sel = { kind: "lip", i };
    seek(S.lip.events[i].pos / LIP_BYTES_PER_SEC + 0.0005);
  } else {
    const items = S.tg.tiers[s.t].items;
    const i = Math.max(0, Math.min(items.length - 1, s.i + d));
    S.sel = { kind: "tier", t: s.t, i };
    seek(items[i].xmin + 0.0005);
  }
  ensureVisible();
  renderInspector();
}

function nudge(sec) {
  const s = S.sel;
  if (!s || s.i <= 0) return;
  const m = s.kind === "lip" ? { kind: "lip", i: s.i } : { kind: "tier", t: s.t, i: s.i };
  const g = linkedGroup(m);
  mutate(s.kind === "lip" ? "lip" : "tg", () => moveGroup(g, boundaryTime(m) + sec));
}

function ensureVisible() {
  const t = playPos(), w = tlWidth() / S.view.pps;
  if (t < S.view.t0 || t > S.view.t0 + w) { S.view.t0 = Math.max(0, t - w / 3); syncScroll(); }
}

// ─── Inspector ───────────────────────────────────────────────────────────────

function renderInspector() {
  const box = $("inspector");
  const s = S.sel;
  if (!s || (s.kind === "lip" && !S.lip?.events[s.i]) || (s.kind === "tier" && !S.tg?.tiers[s.t]?.items[s.i])) {
    box.innerHTML = '<span class="note">Click an event or interval in the timeline.</span>';
    return;
  }
  // Don't rebuild while the user is typing in it.
  if (box.contains(document.activeElement) && document.activeElement.tagName === "INPUT" && drag == null && box.dataset.key === key(s)) {
    return;
  }
  box.dataset.key = key(s);
  if (s.kind === "lip") {
    const ev = S.lip.events, e = ev[s.i];
    const end = s.i + 1 < ev.length ? ev[s.i + 1].pos : S.lip.end;
    const opts = CODE_NAMES.map((n, c) => `<option value="${c}" ${c === e.code ? "selected" : ""}>0x${c.toString(16).padStart(2, "0")} ${esc(n)} — ${esc(CODE_EXAMPLES[c])} (frame ${frameForCode(c)})</option>`).join("");
    const grid = CODE_NAMES.slice(0, PHONEME_COUNT).map((n, c) => `<button data-code="${c}" class="${c === e.code ? "on" : ""}" style="border-left-color:${FRAME_COLORS[frameForCode(c)]}" title="0x${c.toString(16)} ${esc(CODE_EXAMPLES[c])} → frame ${frameForCode(c)}">${esc(n)}</button>`).join("");
    box.innerHTML = `
      <span class="k">LIP event</span><span>${s.i} of ${ev.length}${s.i === 0 ? " (marker 0, fixed at 0)" : ""}</span>
      <span class="k">Start (s)</span><input id="insStart" type="number" step="0.001" value="${fmtT(e.pos / LIP_BYTES_PER_SEC)}" ${s.i === 0 ? "disabled" : ""}>
      <span class="k">Length</span><span>${((end - e.pos) / LIP_BYTES_PER_SEC * 1000).toFixed(0)} ms · bytes ${e.pos}</span>
      <span class="k">Code</span><select id="insCodeSel">${opts}</select>
      <div class="codegrid">${grid}</div>`;
    $("insCodeSel").onchange = (ev2) => setCode(s.i, +ev2.target.value);
    box.querySelectorAll(".codegrid button").forEach((b) => (b.onclick = () => setCode(s.i, +b.dataset.code)));
    const st = $("insStart");
    st.onchange = () => {
      const pos = Math.round(+st.value * LIP_BYTES_PER_SEC);
      const lo = ev[s.i - 1].pos + 1, hi = end - 1;
      mutate("lip", () => { ev[s.i].pos = Math.max(lo, Math.min(hi, pos)); });
    };
  } else {
    const tier = S.tg.tiers[s.t], it = tier.items[s.i];
    box.innerHTML = `
      <span class="k">Tier</span><span>${esc(tier.name)} · interval ${s.i + 1} of ${tier.items.length}</span>
      <span class="k">Label</span><input id="insLabel" value="${esc(it.text)}">
      <span class="k">Start (s)</span><input id="insXmin" type="number" step="0.001" value="${fmtT(it.xmin)}" ${s.i === 0 ? "disabled" : ""}>
      <span class="k">End (s)</span><input id="insXmax" type="number" step="0.001" value="${fmtT(it.xmax)}" ${s.i === tier.items.length - 1 ? "disabled" : ""}>
      <span class="k">LIP code</span><span>${tierCodeHint(tier, it)}</span>`;
    $("insLabel").onchange = (e2) => mutate("tg", () => { it.text = e2.target.value.trim(); });
    $("insLabel").onkeydown = (e2) => { if (e2.key === "Enter") e2.target.blur(); e2.stopPropagation(); };
    const setB = (j, v) => mutate("tg", () => {
      const items = tier.items;
      const lo = items[j - 1].xmin + 0.001, hi = items[j].xmax - 0.001;
      const x = Math.max(lo, Math.min(hi, v));
      items[j - 1].xmax = x; items[j].xmin = x;
    });
    $("insXmin").onchange = (e2) => setB(s.i, +e2.target.value);
    $("insXmax").onchange = (e2) => setB(s.i + 1, +e2.target.value);
  }
}
const key = (s) => (s.kind === "lip" ? `l${s.i}` : `t${s.t}:${s.i}`);

function tierCodeHint(tier, it) {
  if (!/^phones?$/i.test(tier.name) || !S.cfg) return "—";
  const code = textGridToEvents({ tiers: [{ cls: "IntervalTier", name: "phones", items: [it] }] },
    S.cfg.phonemeTable, S.cfg.phonemeMode)[0].code;
  return `0x${code.toString(16).padStart(2, "0")} ${esc(CODE_NAMES[code])} → frame ${frameForCode(code)}`;
}

// ─── Panels ──────────────────────────────────────────────────────────────────

function renderDirty() {
  $("lipDirty").textContent = S.dirty.lip ? "●" : "";
  $("tgDirty").textContent = S.dirty.tg ? "●" : "";
  $("txtDirty").textContent = S.dirty.txt ? "●" : "";
  const target = S.stem ? S.stem : null;
  $("saveLip").disabled = !S.lip || !target;
  $("saveTg").disabled = !S.tg || !target;
  $("saveTxt").disabled = !target;
  $("saveLip").title = target ? `Write ${target}.lip into the project` : "Pick a line to save into the project, or download";
  $("saveTg").title = target ? `Write ${target}.TextGrid into the project` : "Pick a line to save into the project, or download";
  $("dlLip").disabled = !S.lip;
  $("dlTg").disabled = !S.tg;
  $("undoBtn").disabled = !S.undo.length;
  $("redoBtn").disabled = !S.redo.length;
}

function renderFiles() {
  $("audioInfo").textContent = S.audio
    ? `${S.audio.label} · ${S.audio.buffer.duration.toFixed(3)} s · ${S.audio.buffer.sampleRate} Hz`
    : "—";
  $("lipInfo").textContent = S.lip
    ? `${S.lipLabel} · ${S.lip.events.length} events · ${(S.lip.end / LIP_BYTES_PER_SEC).toFixed(3)} s`
    : "—";
  $("tgInfo").textContent = S.tg
    ? `${S.tgLabel} · ${S.tg.tiers.map((t) => `${t.name}(${t.items.length})`).join(" ")}`
    : "—";
  const warns = [...(S.lip?.warnings || [])];
  if (S.lip && S.audio) {
    const d = S.lip.end / LIP_BYTES_PER_SEC - S.audio.buffer.duration;
    if (Math.abs(d) > 0.05) warns.push(`LIP end is ${d > 0 ? "after" : "before"} the audio end by ${Math.abs(d).toFixed(3)} s`);
  }
  if (S.lip && S.lip.events.length + 1 <= 5) warns.push("5 markers or fewer: the engine logs \"Too few markers to stop speech\"");
  if (S.headInfo) warns.push(S.headInfo);
  $("warnings").innerHTML = warns.map((w) => `<li>${esc(w)}</li>`).join("");
  renderDirty();
}

function refreshAll() {
  renderFiles();
  renderInspector();
  drawTimeline();
  if (!S.play.on) updateHead(S.play.pos, true);
}

// ─── Talking head ────────────────────────────────────────────────────────────

const headCache = new Map();
async function loadFrm(path) {
  if (headCache.has(path)) return headCache.get(path);
  const frm = new Frm(await gameFile(path), path.split("/").pop());
  headCache.set(path, frm);
  return frm;
}

async function applyHead() {
  const name = $("headSel").value, mood = $("moodSel").value;
  S.headInfo = "";
  if (!name) { screen.setHead(null); refreshAll(); return; }
  try {
    const frm = await loadFrm(`art/heads/${name}${mood}.frm`);
    setHeadFrm(frm);
  } catch (e) {
    screen.setHead(null);
    S.headInfo = `${name}${mood}.frm: ${e.message}`;
  }
  try { localStorage.setItem("lipstudio.head." + (S.folder || ""), JSON.stringify({ name, mood })); } catch { /* storage off */ }
  refreshAll();
}

function setHeadFrm(frm) {
  screen.setHead(frm);
  const notes = [];
  if (frm.frameCount < 9) notes.push(`${frm.name} has ${frm.frameCount} frames; the engine needs 9 (missing ones freeze the mouth)`);
  const xs = frm.frames.filter((f) => f.x !== 0).length;
  if (xs) notes.push(`${frm.name}: ${xs} frame(s) have an x offset, so the head drifts while talking`);
  S.headInfo = notes.join(" · ");
  $("headInfo").textContent = `${frm.name}: ${frm.frameCount} frames, ${frm.frames[0]?.w}×${frm.frames[0]?.h}, shift ${frm.shiftX[0]},${frm.shiftY[0]}`;
  buildFrameStrip(frm);
  S.lastFrame = -1;
}

async function applyBackground() {
  const bg = $("bgSel").value;
  try {
    screen.background = bg ? await loadFrm(`art/backgrnd/${bg}`) : null;
  } catch (e) { status(`${bg}: ${e.message}`, true); screen.background = null; }
  const head = $("headSel").value;
  if (head) try { localStorage.setItem("lipstudio.bg." + head, bg); } catch { /* storage off */ }
  screen.render();
}

function buildFrameStrip(frm) {
  const strip = $("frameStrip");
  strip.innerHTML = "";
  for (let f = 0; f < 9; f++) {
    const fr = frm.frames[Math.min(f, frm.frameCount - 1)];
    const div = document.createElement("div");
    div.className = "fr"; div.dataset.f = f;
    const c = document.createElement("canvas");
    c.width = 388; c.height = 200;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(388, 200);
    const px = new Uint32Array(img.data.buffer);
    const ox = Math.trunc((388 - fr.w) / 2) + frm.shiftX[0], oy = 200 - fr.h;
    for (let y = 0; y < fr.h; y++) for (let x = 0; x < fr.w; x++) {
      const v = fr.data[y * fr.w + x];
      const X = ox + x, Y = oy + y;
      if (v && X >= 0 && X < 388 && Y >= 0 && Y < 200) px[Y * 388 + X] = pal.rgba[v];
    }
    ctx.putImageData(img, 0, 0);
    const label = document.createElement("span");
    label.textContent = `frame ${f}` + (f >= frm.frameCount ? " (missing)" : "");
    label.style.color = FRAME_COLORS[f];
    div.append(c, label);
    div.title = "Codes: " + CODE_NAMES.filter((_, c2) => frameForCode(c2) === f).join(" ");
    div.onclick = () => {
      if (S.sel?.kind !== "lip") return;
      const cur = S.lip.events[S.sel.i].code;
      if (frameForCode(cur) === f) return;
      // Pick the code that maps to this frame, preferring the TextGrid hint order.
      const code = CODE_NAMES.findIndex((_, c2) => frameForCode(c2) === f);
      setCode(S.sel.i, code);
    };
    strip.append(div);
  }
}

// ─── Loading ─────────────────────────────────────────────────────────────────

async function loadLine(folder, stem) {
  if (anyDirty() && !confirm("Discard unsaved changes?")) { $("stemSel").value = S.stem || ""; return; }
  stop();
  S.folder = folder; S.stem = stem;
  S.lip = null; S.tg = null; S.audio = null; S.txt = "";
  S.lipLabel = S.tgLabel = "";
  S.dirty = { lip: false, tg: false, txt: false };
  S.undo = []; S.redo = []; S.sel = null;
  try { localStorage.setItem("lipstudio.last", JSON.stringify({ folder, stem })); } catch { /* storage off */ }
  status(`Loading ${stem}…`);
  const kinds = S.speech[folder]?.[stem] || [];
  $("stemKinds").textContent = kinds.join(" · ");
  const tasks = [];
  if (kinds.includes("acm") || kinds.includes("wav")) {
    tasks.push(fetchBuf(stemUrl("audio")).then((b) => setAudioFromBuf(b, kinds.includes("acm") ? `${stem}.acm` : `${stem}.wav`)));
  }
  if (kinds.includes("lip")) {
    tasks.push(fetchBuf(stemUrl("lip")).then((b) => { S.lip = parseLip(b); S.lipLabel = `${stem}.lip`; }));
  }
  if (kinds.includes("textgrid")) {
    tasks.push(fetchBuf(stemUrl("textgrid")).then((b) => { S.tg = parseTextGrid(new TextDecoder().decode(b)); S.tgLabel = `${stem}.TextGrid`; }));
  }
  if (kinds.includes("txt")) {
    tasks.push(fetchBuf(stemUrl("txt")).then((b) => { S.txt = decodeText(b, S.cfg.encoding); S.txtLabel = `${stem}.txt`; }));
  }
  const res = await Promise.allSettled(tasks);
  const errs = res.filter((r) => r.status === "rejected").map((r) => r.reason.message);
  setText(S.txt, false);
  // Head defaults to the speech folder: the engine finds speech under SOUND\SPEECH\<head name>\.
  await pickHeadFor(folder);
  zoomFit();
  seek(0);
  refreshAll();
  status(errs.length ? `Loaded ${stem} with errors: ${errs.join("; ")}` : `Loaded ${stem}`, errs.length > 0);
}

async function pickHeadFor(folder) {
  let pref = null;
  try { pref = JSON.parse(localStorage.getItem("lipstudio.head." + folder) || "null"); } catch { /* */ }
  const head = S.heads.find((h) => h.name === (pref?.name || folder));
  if (head && $("headSel").value !== head.name) {
    $("headSel").value = head.name;
    await onHeadChange(pref?.mood);
  } else if (pref?.mood && $("moodSel").value !== pref.mood) {
    $("moodSel").value = pref.mood;
    await applyHead();
  }
}

async function onHeadChange(mood) {
  const name = $("headSel").value;
  const head = S.heads.find((h) => h.name === name);
  if (head) {
    if (mood && head.moods.includes(mood)) $("moodSel").value = mood;
    else if (!head.moods.includes($("moodSel").value) && head.moods.length) $("moodSel").value = head.moods[0];
    let bg = null;
    try { bg = localStorage.getItem("lipstudio.bg." + name); } catch { /* */ }
    bg = bg || head.background;
    if (bg && S.backgrounds.includes(bg)) { $("bgSel").value = bg; await applyBackground(); }
  }
  await applyHead();
}

function setText(t, dirty = true) {
  S.txt = t;
  $("txtArea").value = t;
  screen.replyText = t;
  screen.replyOffset = 0;
  if (dirty) S.dirty.txt = true;
  renderDirty();
  screen.render();
}

async function openFiles(files) {
  for (const f of files) {
    const name = f.name, lower = name.toLowerCase();
    const buf = await f.arrayBuffer();
    try {
      if (lower.endsWith(".lip")) {
        S.undo.push(snapshot());
        S.lip = parseLip(buf); S.lipLabel = name; S.dirty.lip = false;
      } else if (lower.endsWith(".textgrid")) {
        S.undo.push(snapshot());
        S.tg = parseTextGrid(new TextDecoder().decode(buf)); S.tgLabel = name; S.dirty.tg = false;
      } else if (lower.endsWith(".txt")) {
        setText(decodeText(buf, S.cfg.encoding), false); S.txtLabel = name;
      } else if (lower.endsWith(".frm")) {
        const frm = new Frm(buf, name);
        const f0 = frm.frames[0];
        if (frm.frameCount === 1 && f0.w === 388 && f0.h === 200) {
          screen.background = frm;
          $("bgSel").value = "";
        } else {
          setHeadFrm(frm);
          $("headSel").value = "";
        }
      } else if (/\.(acm|wav|mp3|ogg|flac|m4a|opus)$/.test(lower)) {
        await setAudioFromBuf(buf, name);
      } else {
        status(`Don't know what to do with ${name}`, true);
        continue;
      }
      status(`Opened ${name}`);
    } catch (e) {
      status(`${name}: ${e.message}`, true);
    }
  }
  zoomFit();
  refreshAll();
}

// ─── Saving ──────────────────────────────────────────────────────────────────

async function save(kind) {
  if (!S.stem) return;
  let body;
  if (kind === "lip") {
    if (!S.lip) return;
    if (!S.lip.name) S.lip.name = S.stem.slice(0, 8);
    body = writeLip(S.lip);
  } else if (kind === "textgrid") {
    if (!S.tg) return;
    body = new TextEncoder().encode(writeTextGrid(S.tg));
  } else {
    body = encodeCp1252(S.txt);
  }
  const r = await fetch(`/api/save?folder=${S.folder}&stem=${S.stem}&kind=${kind}`, { method: "POST", body });
  const j = await r.json();
  if (!r.ok) { status(`Save failed: ${j.error}`, true); return; }
  S.dirty[kind === "textgrid" ? "tg" : kind] = false;
  const kinds = S.speech[S.folder]?.[S.stem];
  if (kinds && !kinds.includes(kind)) kinds.push(kind);
  renderDirty();
  status(`Saved ${j.saved}`);
}

const anyDirty = () => S.dirty.lip || S.dirty.tg || S.dirty.txt;

// ─── Wiring ──────────────────────────────────────────────────────────────────

function fillSelect(sel, items, value) {
  sel.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  if (value !== undefined) sel.value = value;
}

function fillStems(folder, stem) {
  const stems = Object.keys(S.speech[folder] || {});
  fillSelect($("stemSel"), stems.map((s) => [s, `${s}  ${S.speech[folder][s].includes("lip") ? "" : "(no lip)"}`]), stem ?? stems[0]);
}

function applyScale() {
  const v = $("scaleSel").value;
  const c = $("screen");
  if (v === "fit") { c.style.width = "100%"; c.style.maxWidth = "none"; }
  else { c.style.width = 640 * +v + "px"; c.style.maxWidth = "100%"; }
  try { localStorage.setItem("lipstudio.scale", v); } catch { /* */ }
}

function wire() {
  $("folderSel").onchange = () => { fillStems($("folderSel").value); loadLine($("folderSel").value, $("stemSel").value); };
  $("stemSel").onchange = () => loadLine($("folderSel").value, $("stemSel").value);
  const step = (d) => {
    const sel = $("stemSel");
    const i = sel.selectedIndex + d;
    if (i < 0 || i >= sel.options.length) return;
    sel.selectedIndex = i;
    loadLine($("folderSel").value, sel.value);
  };
  $("prevLine").onclick = () => step(-1);
  $("nextLine").onclick = () => step(1);
  $("openFiles").onclick = () => $("fileInput").click();
  $("fileInput").onchange = (e) => { openFiles([...e.target.files]); e.target.value = ""; };

  $("playBtn").onclick = () => (S.play.on ? pause() : play());
  $("stopBtn").onclick = stop;
  $("rateSel").onchange = () => { if (S.play.on) { pause(); play(); } };
  $("scaleSel").onchange = applyScale;

  $("headSel").onchange = () => onHeadChange();
  $("moodSel").onchange = applyHead;
  $("bgSel").onchange = applyBackground;

  $("txtArea").addEventListener("input", (e) => setText(e.target.value));
  $("optionText").addEventListener("input", (e) => { screen.optionText = e.target.value; screen.render(); });
  $("saveTxt").onclick = () => save("txt");
  $("dlTxt").onclick = () => download(`${S.stem || "line"}.txt`, encodeCp1252(S.txt), "text/plain");
  $("saveLip").onclick = () => save("lip");
  $("saveTg").onclick = () => save("textgrid");
  $("dlLip").onclick = () => S.lip && download(`${S.stem || S.lip.name || "line"}.lip`, writeLip(S.lip));
  $("dlTg").onclick = () => S.tg && download(`${S.stem || "line"}.TextGrid`, writeTextGrid(S.tg), "text/plain");
  $("useWav").onclick = async () => {
    if (!S.stem) return;
    try { await setAudioFromBuf(await fetchBuf(stemUrl("wav")), `${S.stem}.wav`); refreshAll(); status("Playing work/wav"); }
    catch (e) { status(e.message, true); }
  };
  $("useAcm").onclick = async () => {
    if (!S.stem) return;
    try { await setAudioFromBuf(await fetchBuf(stemUrl("audio")), `${S.stem}.acm`); refreshAll(); status("Playing ACM"); }
    catch (e) { status(e.message, true); }
  };

  $("zoomIn").onclick = () => zoomAround(1.5, tlWidth() / 2);
  $("zoomOut").onclick = () => zoomAround(1 / 1.5, tlWidth() / 2);
  $("zoomFit").onclick = zoomFit;
  $("insertEv").onclick = insertEvent;
  $("deleteSel").onclick = deleteSelection;
  $("splitIv").onclick = splitInterval;
  $("mergeIv").onclick = mergeInterval;
  $("rebuildLip").onclick = rebuildLip;
  $("newLip").onclick = makeNewLip;
  $("fitEnd").onclick = fitEnd;
  $("undoBtn").onclick = undo;
  $("redoBtn").onclick = redo;

  // Reply window scroll, like the game's up/down halves.
  $("screen").addEventListener("click", (e) => {
    const r = e.target.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * 640, y = ((e.clientY - r.top) / r.height) * 480;
    const d = DialogScreen.hitReply(x, y);
    if (d) { screen.scrollReply(d); screen.render(); }
  });
  $("screen").addEventListener("mousemove", (e) => {
    const r = e.target.getBoundingClientRect();
    const d = DialogScreen.hitReply(((e.clientX - r.left) / r.width) * 640, ((e.clientY - r.top) / r.height) * 480);
    e.target.style.cursor = d < 0 ? "n-resize" : d > 0 ? "s-resize" : "default";
  });

  document.addEventListener("keydown", (e) => {
    const tag = document.activeElement?.tagName;
    const typing = tag === "TEXTAREA" || (tag === "INPUT" && document.activeElement.type !== "checkbox" && document.activeElement.type !== "range") || tag === "SELECT";
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (S.dirty.lip) save("lip");
      if (S.dirty.tg) save("textgrid");
      if (S.dirty.txt) save("txt");
      return;
    }
    if (typing) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    switch (e.key) {
      case " ": e.preventDefault(); S.play.on ? pause() : play(); break;
      case "Home": stop(); break;
      case "Delete": case "Backspace": deleteSelection(); break;
      case "i": case "I": insertEvent(); break;
      case "s": case "S": splitInterval(); break;
      case "m": case "M": mergeInterval(); break;
      case "+": case "=": zoomAround(1.5, tlWidth() / 2); break;
      case "-": zoomAround(1 / 1.5, tlWidth() / 2); break;
      case "PageUp": e.preventDefault(); $("prevLine").click(); break;
      case "PageDown": e.preventDefault(); $("nextLine").click(); break;
      case "ArrowLeft": case "ArrowRight": {
        e.preventDefault();
        const d = e.key === "ArrowLeft" ? -1 : 1;
        if (e.altKey) nudge(d * (e.shiftKey ? 0.001 : 0.01));
        else if (S.sel) selectRelative(d);
        else seek(playPos() + d * (e.shiftKey ? 0.01 : 0.1));
        break;
      }
      default: return;
    }
  });

  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); });
  window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
    openFiles([...e.dataTransfer.files]);
  });
  window.addEventListener("beforeunload", (e) => { if (anyDirty()) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("resize", () => { resizeTimeline(); drawTimeline(); });
}

// ─── Boot ────────────────────────────────────────────────────────────────────

async function boot() {
  status("Loading game art…");
  S.cfg = await fetchJson("/api/config");
  pal = new Palette(await gameFile("color.pal"));
  const [alltlk, diTalk, hilight1, hilight2, font] = await Promise.all([
    gameFile("art/intrface/alltlk.frm"), gameFile("art/intrface/di_talk.frm"),
    gameFile("art/intrface/hilight1.frm"), gameFile("art/intrface/hilight2.frm"),
    gameFile("font1.aaf"),
  ]);
  screen = new DialogScreen($("screen"), pal, {
    alltlk: new Frm(alltlk), diTalk: new Frm(diTalk),
    hilight1: new Frm(hilight1), hilight2: new Frm(hilight2), font: new AafFont(font),
  });
  screen.render();

  const [speech, heads] = await Promise.all([fetchJson("/api/speech"), fetchJson("/api/heads")]);
  S.speech = speech;
  S.heads = heads.heads;
  S.backgrounds = heads.backgrounds;
  fillSelect($("headSel"), [["", "(none)"], ...S.heads.map((h) => [h.name, `${h.name}${h.moods.length ? "" : " (no lip-sync art)"}`])]);
  fillSelect($("bgSel"), [["", "(none)"], ...S.backgrounds.map((b) => [b, b])]);
  const folders = Object.keys(S.speech);
  fillSelect($("folderSel"), folders.map((f) => [f, `${f} (${Object.keys(S.speech[f]).length})`]));

  try { const sc = localStorage.getItem("lipstudio.scale"); if (sc) $("scaleSel").value = sc; } catch { /* */ }
  applyScale();
  wire();
  resizeTimeline();

  let last = null;
  try { last = JSON.parse(localStorage.getItem("lipstudio.last") || "null"); } catch { /* */ }
  const folder = last && S.speech[last.folder] ? last.folder : folders[0];
  if (folder) {
    $("folderSel").value = folder;
    const stem = last && S.speech[folder][last.stem] ? last.stem : undefined;
    fillStems(folder, stem);
    await loadLine(folder, $("stemSel").value);
  } else {
    status("No speech found in the project. Open files to start.");
    refreshAll();
  }
}

boot().catch((e) => { console.error(e); status(`Startup failed: ${e.message}`, true); });
