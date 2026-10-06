// Fallout 2 dialogue screen, drawn the way fallout2-ce game_dialog.cc draws it,
// into a 640x480 palette-indexed buffer.

import { encodeCp1252 } from "./formats.js";

export const W = 640, H = 480;

// _backgrndRects: frame pieces re-drawn over the head window corners and edges.
const BACKGRND_RECTS = [
  [126, 14, 152, 40], [488, 14, 514, 40], [126, 188, 152, 214], [488, 188, 514, 214],
  [152, 14, 488, 24], [152, 204, 488, 214], [126, 40, 136, 188], [504, 40, 514, 188],
];
const HEAD_X = 126, HEAD_Y = 14, HEAD_W = 388, HEAD_H = 200;
const REPLY = { x: 135, y: 225, w: 379, h: 58, rect: [5, 10, 374, 58] };
const OPTIONS = { x: 127, y: 335, w: 393, h: 117, rect: [5, 5, 388, 112] };

export class DialogScreen {
  constructor(canvas, pal, art) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.pal = pal;
    this.art = art;  // { alltlk, diTalk, hilight1, hilight2, font }
    this.buf = new Uint8Array(W * H);
    this.image = this.ctx.createImageData(W, H);
    this.pixels = new Uint32Array(this.image.data.buffer);

    this.background = null;  // Frm 388x200
    this.head = null;        // Frm (phoneme file)
    this.frame = 0;
    this.totalHotX = 0;
    this.replyText = "";
    this.replyOffset = 0;
    this.optionText = "";

    this.green = pal.rgb2color(0x00ff00);
    this.lightBlend = pal.blendTable(pal.rgb2color(0x8c8c8c));  // COLOR_GREY
    this.darkBlend = pal.blendTable(pal.rgb2color(0xadad5a));   // COLOR_OLIVE
    this.greenBlend = pal.blendTable(this.green);

    // Window stack: background window (alltlk), dialog sub-window (di_talk) at the bottom.
    this.bgWindow = new Uint8Array(W * H);
    const a = art.alltlk.frames[0];
    blit(a.data, a.w, a.h, a.w, this.bgWindow, 0, 0, W, false);
    // _gdCreateHeadWindow saves the 8 frame pieces before anything is drawn on top.
    this.saved = BACKGRND_RECTS.map(([l, t, r, b]) => {
      const w = r - l, h = b - t, out = new Uint8Array(w * h);
      for (let y = 0; y < h; y++) out.set(this.bgWindow.subarray((t + y) * W + l, (t + y) * W + l + w), y * w);
      return { l, t, w, h, data: out };
    });
    this.subY = H - art.diTalk.frames[0].h;
  }

  setHead(frm) { this.head = frm; this.totalHotX = 0; }

  // gameDialogRenderTalkingHead: running x offset resets at frame 0 and grows with
  // each drawn frame's x offset. Call this once per phoneme change, like the engine.
  showFrame(frame) {
    if (this.head && frame >= this.head.frameCount) frame = this.head.frameCount - 1;
    this.frame = frame;
    if (!this.head) return;
    if (frame === 0) this.totalHotX = 0;
    this.totalHotX += this.head.frames[frame]?.x || 0;
  }

  // Replays a frame sequence from the start, so a seek lands on the same running
  // offset the engine would have after playing up to that point.
  replayFrames(frames) {
    this.totalHotX = 0;
    for (const f of frames) this.showFrame(f);
  }

  render() {
    const buf = this.buf;
    buf.set(this.bgWindow);
    this.drawHeadWindow(buf);
    this.drawReply(buf);
    // Dialog sub-window (di_talk), then the options window on top of it.
    const d = this.art.diTalk.frames[0];
    blit(d.data, d.w, d.h, d.w, buf, 0, this.subY, W, false);
    this.drawOptions(buf);
    const px = this.pixels, rgba = this.pal.rgba;
    for (let i = 0; i < W * H; i++) px[i] = rgba[buf[i]];
    this.ctx.putImageData(this.image, 0, 0);
  }

  drawHeadWindow(buf) {
    const base = HEAD_Y * W + HEAD_X;
    if (this.background) {
      const b = this.background.frames[0];
      blitClip(b.data, Math.min(b.w, HEAD_W), Math.min(b.h, HEAD_H), b.w, buf, base, W, false);
    } else {
      for (let y = 0; y < HEAD_H; y++) buf.fill(0, base + y * W, base + y * W + HEAD_W);
    }
    if (this.head && this.head.frames[this.frame]) {
      const f = this.head.frames[this.frame];
      const rotX = this.head.shiftX[0] + this.totalHotX;
      const rotY = this.head.shiftY[0];
      let dest = W * (HEAD_H - f.h) + rotX + Math.trunc((HEAD_W - f.w) / 2);
      if (dest + W * rotY > 0) dest += W * rotY;
      blitClip(f.data, f.w, f.h, f.w, buf, base + dest, W, true);
    }
    // Highlights blended over the head, then the saved frame pieces on top.
    this.drawHighlight(buf, this.art.hilight1.frames[0], 426, 15, this.lightBlend);
    const h2 = this.art.hilight2.frames[0];
    this.drawHighlight(buf, h2, 129, 214 - h2.h - 2, this.darkBlend);
    for (const s of this.saved) {
      for (let y = 0; y < s.h; y++) {
        for (let x = 0; x < s.w; x++) {
          const c = s.data[y * s.w + x];
          if (c) buf[(s.t + y) * W + s.l + x] = c;
        }
      }
    }
  }

  // gameDialogRenderHighlight: the highlight FRM's pixel value picks a blend row.
  drawHighlight(buf, f, dx, dy, table) {
    for (let y = 0; y < f.h; y++) {
      let d = (dy + y) * W + dx;
      for (let x = 0; x < f.w; x++, d++) {
        let a = f.data[y * f.w + x];
        if (a !== 0) a = Math.min(13, (256 - a) >> 4);
        buf[d] = table[256 * a + buf[d]];
      }
    }
  }

  drawReply(buf) {
    // _demo_copy_title: the reply window starts as a copy of the background window.
    const win = new Uint8Array(REPLY.w * REPLY.h);
    for (let y = 0; y < REPLY.h; y++) {
      win.set(this.bgWindow.subarray((REPLY.y + y) * W + REPLY.x, (REPLY.y + y) * W + REPLY.x + REPLY.w), y * REPLY.w);
    }
    const [l, t, r, b] = REPLY.rect;
    this.lastReplyLayout = drawWrapped(this.art.font, win, REPLY.w, { left: l, top: t, right: r, bottom: b },
      this.replyText, this.replyOffset, this.greenBlend);
    for (let y = 0; y < REPLY.h; y++) {
      buf.set(win.subarray(y * REPLY.w, (y + 1) * REPLY.w), (REPLY.y + y) * W + REPLY.x);
    }
  }

  drawOptions(buf) {
    if (!this.optionText) return;
    const [l, t, r, b] = OPTIONS.rect;
    // Options are drawn straight into the window, which sits over di_talk.
    const win = new Uint8Array(OPTIONS.w * OPTIONS.h);
    for (let y = 0; y < OPTIONS.h; y++) {
      win.set(buf.subarray((OPTIONS.y + y) * W + OPTIONS.x, (OPTIONS.y + y) * W + OPTIONS.x + OPTIONS.w), y * OPTIONS.w);
    }
    drawWrapped(this.art.font, win, OPTIONS.w, { left: l, top: t, right: r, bottom: b },
      "• " + this.optionText, 0, this.greenBlend);
    for (let y = 0; y < OPTIONS.h; y++) {
      buf.set(win.subarray(y * OPTIONS.w, (y + 1) * OPTIONS.w), (OPTIONS.y + y) * W + OPTIONS.x);
    }
  }

  // Reply scroll, like the up/down halves of the reply window in game.
  scrollReply(dir) {
    const lay = this.lastReplyLayout;
    if (!lay) return;
    if (dir > 0 && lay.nextOffset > 0) this.replyOffset = lay.nextOffset;
    if (dir < 0) this.replyOffset = lay.prevOffset;
  }

  static hitReply(x, y) {
    return x >= REPLY.x && x < REPLY.x + REPLY.w && y >= REPLY.y && y < REPLY.y + REPLY.h
      ? (y - REPLY.y < 29 ? -1 : 1) : 0;
  }
}

function blit(src, w, h, srcPitch, dest, dx, dy, destPitch, trans) {
  for (let y = 0; y < h; y++) {
    const s = y * srcPitch, d = (dy + y) * destPitch + dx;
    if (!trans) { dest.set(src.subarray(s, s + w), d); continue; }
    for (let x = 0; x < w; x++) { const c = src[s + x]; if (c) dest[d + x] = c; }
  }
}

// Linear-address blit like blitBufferToBuffer[Trans]: a negative or oversized x
// offset wraps into the neighbouring row instead of clipping, same as the engine.
function blitClip(src, w, h, srcPitch, dest, start, destPitch, trans) {
  for (let y = 0; y < h; y++) {
    const s = y * srcPitch, d = start + y * destPitch;
    for (let x = 0; x < w; x++) {
      const i = d + x;
      if (i < 0 || i >= dest.length) continue;
      const c = src[s + x];
      if (!trans || c) dest[i] = c;
    }
  }
}

// gameDialogDrawText (display_msg) word wrap. The first line of the whole text is
// indented 10px; later lines start at x 0 (rect.left is not applied, as in the engine).
// Returns where the next page starts so the reply can scroll.
function drawWrapped(font, buf, pitch, rect, text, offset, blend) {
  const s = encodeCp1252(text.replace(/\r?\n/g, " "));
  const width = (a, b) => font.stringWidth(s.subarray(a, b));
  const maxWidth = rect.right - rect.left;
  const lh = font.lineHeight();
  const n = s.length;
  const lineStarts = [];
  let start = Math.min(offset, n), top = rect.top, nextOffset = 0;
  const drawLine = (a, b) => {
    lineStarts.push(a);
    font.draw(buf, pitch, a === 0 ? 10 : 0, top, s.subarray(a, b), maxWidth, blend);
  };
  while (start < n) {
    let end = -1;
    if (width(start, n) > maxWidth) {
      end = start + 1;
      while (end < n && s[end] !== 32) end++;
      if (end < n) {
        let look = end + 1;
        for (;;) {
          while (look < n && s[look] !== 32) look++;
          if (look >= n) break;
          if (width(start, look) >= maxWidth) break;
          end = look; look++;
        }
      } else {
        if (rect.bottom - lh < top) { nextOffset = start; break; }
        drawLine(start, n);
        top += lh;
        start = n;
        break;
      }
    }
    const lineEnd = end < 0 ? n : end;
    if (width(start, lineEnd) > maxWidth) break;  // "word too long"
    if (rect.bottom - lh < top) { nextOffset = start; break; }
    drawLine(start, lineEnd);
    top += lh;
    if (end < 0) break;
    start = end + 1;
  }
  // Previous page: re-wrap from 0 and step back by the number of lines a page holds.
  let prevOffset = 0;
  if (offset > 0) {
    const all = [];
    let st = 0;
    while (st < n) {
      all.push(st);
      let e = -1;
      if (width(st, n) > maxWidth) {
        e = st + 1;
        while (e < n && s[e] !== 32) e++;
        if (e < n) {
          let look = e + 1;
          for (;;) {
            while (look < n && s[look] !== 32) look++;
            if (look >= n || width(st, look) >= maxWidth) break;
            e = look; look++;
          }
        } else break;
      }
      if (e < 0) break;
      st = e + 1;
    }
    const perPage = Math.max(1, lineStarts.length || Math.floor((rect.bottom - rect.top) / lh));
    const idx = all.indexOf(offset);
    prevOffset = idx > 0 ? all[Math.max(0, idx - perPage)] : 0;
  }
  return { nextOffset, prevOffset, lines: lineStarts.length };
}
