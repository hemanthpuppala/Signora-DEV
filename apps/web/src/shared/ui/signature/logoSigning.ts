import { clamp } from "@/shared/lib/canvas";
import type { Scope } from "@/shared/lib/scope";

import { LOGO, SIG } from "./penPaths";

/** The part of the pen-path drawing the logo shows: the letterforms plus room for the quill. */
const VIEW = { x: 19.25, y: -43.15, w: 304, h: 250 };
const TAU = Math.PI * 2;
const VANE = ["#ffffff", "#e4e4e4", "#8e8e8e"] as const;

// The quill, drawn with its nib at (18, 88).
const QUILL = {
  vane: "M30 72C26 52 42 28 82 12C76 32 62 52 38 68Z",
  cuts: "M31.4 52.4L33.9 50.5L39.4 58.2Z M42.4 36.2L44.6 34.3L48.6 41.6Z M63.4 46.6L61.6 48.6L57.4 46.6Z",
  rachis:
    "M36.3 66.2L38.9 62.8L41.5 59.5L44.1 56.2L46.8 52.9L49.4 49.7L52.1 46.4L54.9 43.2L57.7 39.9L60.5 36.6L63.4 33.3L66.3 29.9L69.3 26.5L72.4 23.0L75.5 19.4L78.7 15.7L82.0 12.0L81.9 11.9L78.5 15.6L75.3 19.2L72.1 22.7L68.9 26.1L65.9 29.5L63.0 32.9L60.1 36.2L57.2 39.5L54.4 42.8L51.7 46.0L49.0 49.3L46.3 52.5L43.6 55.8L41.0 59.1L38.3 62.4L35.6 65.7Z",
  shaft:
    "M18.1 88.1L20.0 86.2L21.8 84.4L23.5 82.6L25.2 80.8L26.8 79.0L28.3 77.2L29.8 75.4L31.2 73.6L32.6 71.9L33.9 70.2L35.2 68.5L36.5 66.9L35.4 66.1L34.2 67.7L32.8 69.3L31.5 71.0L30.0 72.7L28.6 74.4L27.1 76.1L25.6 77.9L24.0 79.8L22.5 81.7L21.0 83.7L19.4 85.7L17.8 87.9Z",
};

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
