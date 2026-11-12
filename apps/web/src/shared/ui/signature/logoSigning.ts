import { clamp } from "@/shared/lib/canvas";
import type { Scope } from "@/shared/lib/scope";

import { LOGO, SIG } from "./penPaths";

import { QUILL, VANE, VIEW } from "./logoArt";

/** The part of the pen-path drawing the logo shows: the letterforms plus room for the quill. */
const TAU = Math.PI * 2;

/**
 * When the signing last finished, anywhere in this tab. The logo is on every page; a page opened
 * after it has signed shows it at rest instead of signing again on each navigation.
 */
let lastFinished = Number.NEGATIVE_INFINITY;

/**
 * The Signora logo on a canvas: a quill writes "Signora" along the recorded pen path and rests in
 * the logo pose. It signs once per tab; with `repeatMs` it signs again after resting that long.
 * Under reduced motion it shows the finished logo.
 *
 * The ink takes the canvas's CSS `color`; the gaps in the quill take its `--signature-paper`
 * (the colour behind the logo).
 */
export function mountLogoSigning(
  canvas: HTMLCanvasElement,
  scope: Scope,
  reduced: boolean,
  repeatMs?: number,
): void {
  // Ink accumulates on a second canvas, so each frame stamps only the new dots.
  const inkCanvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const ink = inkCanvas.getContext("2d");
  if (!ctx || !ink) return;
  const glyph = new Path2D(SIG.path);
  const quill = {
    vane: new Path2D(QUILL.vane),
    cuts: new Path2D(QUILL.cuts),
    rachis: new Path2D(QUILL.rachis),
    shaft: new Path2D(QUILL.shaft),
  };
  const style = getComputedStyle(canvas);
  const colors = { ink: style.color, paper: style.getPropertyValue("--signature-paper").trim() || "#000000" };
  let stamped = 0;
  let frame = 0;
  let rest = 0;
  let lastTime = 0;

  function clearInk(): void {
    stamped = 0;
    ink!.setTransform(1, 0, 0, 1, 0, 0);
    ink!.clearRect(0, 0, inkCanvas.width, inkCanvas.height);
  }
  function size(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = inkCanvas.width = Math.round(canvas.clientWidth * dpr);
    canvas.height = inkCanvas.height = Math.round(canvas.clientHeight * dpr);
    clearInk();
  }
  /** Maps pen-path coordinates onto the canvas, centred; returns the scale. */
  function applyView(target: CanvasRenderingContext2D): number {
    const k = Math.min(canvas.width / VIEW.w, canvas.height / VIEW.h);
    const offsetX = (canvas.width - VIEW.w * k) / 2;
    const offsetY = (canvas.height - VIEW.h * k) / 2;
    target.setTransform(k, 0, 0, k, offsetX - VIEW.x * k, offsetY - VIEW.y * k);
    return k;
  }
  /** Stamps every ink dot laid down up to time `t`. */
  function stamp(t: number): void {
    const dots = LOGO.ink;
    const count = dots.length / 4;
    let i = stamped;
    if (i >= count || dots[i * 4 + 3]! > t) return;
    const k = applyView(ink!);
    const minRadius = (0.6 * (canvas.width / Math.max(1, canvas.clientWidth))) / k;
    ink!.fillStyle = "#000";
    ink!.beginPath();
    while (i < count && dots[i * 4 + 3]! <= t) {
      const x = dots[i * 4]!;
      const y = dots[i * 4 + 1]!;
      const radius = Math.max(minRadius, dots[i * 4 + 2]! * 1.12 + 0.12);
      ink!.moveTo(x + radius, y);
      ink!.arc(x, y, radius, 0, TAU);
      i++;
    }
    ink!.fill();
    stamped = i;
  }
  /** The quill's [x, y, tiltDeg, lift, opacity] at time `t`, between recorded frames. */
  function nibAt(t: number): number[] {
    const track = LOGO.nib;
    const last = track.length / 5 - 1;
    const position = clamp(t * LOGO.fps, 0, last);
    const i = Math.floor(position);
    const j = Math.min(i + 1, last);
    const mix = position - i;
    return [0, 1, 2, 3, 4].map((k) => track[i * 5 + k]! + (track[j * 5 + k]! - track[i * 5 + k]!) * mix);
  }
  function draw(t: number): void {
    const c = ctx!;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    if (!canvas.width || !canvas.height) return;
    // The ink so far, clipped to the true letterforms and tinted with the ink colour.
    c.save();
    applyView(c);
    c.clip(glyph);
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalCompositeOperation = "source-over";
    c.drawImage(inkCanvas, 0, 0);
    c.globalCompositeOperation = "source-in";
    c.fillStyle = colors.ink;
    c.fillRect(0, 0, canvas.width, canvas.height);
    c.restore();
    // Once the writing ends, the full letterforms fade in over the stamped ink.
    const u = clamp((t - LOGO.writeEnd) / 0.7, 0, 1);
    const dry = u * u * u * (10 - 15 * u + 6 * u * u);
    if (dry > 0) {
      applyView(c);
      c.globalAlpha = dry;
      c.fillStyle = colors.ink;
      c.fill(glyph);
      c.globalAlpha = 1;
    }
    const [x = 0, y = 0, tilt = 0, lift = 0, opacity = 0] = nibAt(t);
    if (opacity <= 0.001) return;
    applyView(c);
    c.translate(x, y - lift * 7);
    c.rotate((tilt * Math.PI) / 180);
    c.scale(1 + 0.035 * lift, 1 + 0.035 * lift);
    c.translate(-18, -88);
    c.globalAlpha = opacity;
    const gradient = c.createLinearGradient(26.3, 12, 82, 72);
    gradient.addColorStop(0, VANE[0]);
    gradient.addColorStop(0.55, VANE[1]);
    gradient.addColorStop(1, VANE[2]);
    c.fillStyle = gradient;
    c.fill(quill.vane);
    c.fillStyle = colors.paper;
    c.fill(quill.cuts);
    c.fill(quill.rachis);
    c.fillStyle = colors.ink;
    c.fill(quill.shaft);
    c.globalAlpha = 1;
  }
  function play(): void {
    scope.clearTimeout(rest);
    scope.cancelFrame(frame);
    clearInk();
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(LOGO.end, (now - started) / 1000);
      lastTime = t;
      stamp(t);
      draw(t);
      if (t < LOGO.end) {
        frame = scope.frame(tick);
      } else {
        frame = 0;
        lastFinished = performance.now();
        if (repeatMs) rest = scope.timeout(play, repeatMs);
      }
    };
    frame = scope.frame(tick);
  }
  /** Repaints the current pose (after a resize) unless the writing is running. */
  function redraw(): void {
    if (frame) return;
    clearInk();
    stamp(lastTime);
    draw(lastTime);
  }

  size();
  const sinceFinished = performance.now() - lastFinished;
  const resting = repeatMs ? sinceFinished < repeatMs : Number.isFinite(lastFinished);
  if (reduced || resting) {
    lastTime = LOGO.end;
    redraw();
    if (!reduced && repeatMs) rest = scope.timeout(play, repeatMs - sinceFinished);
  } else {
    scope.timeout(play, 500);
  }
  scope.onResize(() => {
    size();
    redraw();
  });
}
