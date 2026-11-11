"use client";

import { useEffect, useRef, type PointerEvent } from "react";

import styles from "./signaturePad.module.css";

/** The drawing's own box: points are kept in it, whatever size the pad is shown at. */
export const PAD_WIDTH = 1000;
export const PAD_HEIGHT = 400;
const MIN_STEP = 2; // pad units between kept points: steadier lines, fewer points

export type Stroke = [number, number][];

/** Draw strokes onto a canvas, scaled from the pad's box. */
export function paintStrokes(canvas: HTMLCanvasElement, strokes: readonly Stroke[]) {
  const context = canvas.getContext?.("2d");
  if (!context) return;
  const ratio = window.devicePixelRatio || 1;
  const { width, height } = canvas.getBoundingClientRect();
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.setTransform((canvas.width / PAD_WIDTH), 0, 0, canvas.height / PAD_HEIGHT, 0, 0);
  context.clearRect(0, 0, PAD_WIDTH, PAD_HEIGHT);
  context.lineWidth = 6;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = "#1a1a1a";
  for (const stroke of strokes) {
    const [first, ...rest] = stroke;
    if (!first) continue;
    context.beginPath();
    context.moveTo(first[0], first[1]);
    if (rest.length === 0) context.lineTo(first[0] + 0.1, first[1]);
    for (const [x, y] of rest) context.lineTo(x, y);
    context.stroke();
  }
}

/**
 * A pad to draw a signature with a finger, a mouse or a stylus (Phase 8 §5.1). The strokes are kept
 * as whole points in a 1000 x 400 box, so they are drawn the same on the page and in the PDF.
 */
export function SignaturePad({
  label,
  strokes,
  onChange,
}: {
  label: string;
  strokes: readonly Stroke[];
  onChange: (strokes: Stroke[]) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef<Stroke | null>(null);
  const all = useRef<Stroke[]>([...strokes]);

  useEffect(() => {
    all.current = [...strokes];
    if (canvas.current) paintStrokes(canvas.current, strokes);
  }, [strokes]);

  function at(event: PointerEvent<HTMLCanvasElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    const x = Math.round(((event.clientX - box.left) / box.width) * PAD_WIDTH);
    const y = Math.round(((event.clientY - box.top) / box.height) * PAD_HEIGHT);
    return [Math.min(PAD_WIDTH, Math.max(0, x)), Math.min(PAD_HEIGHT, Math.max(0, y))];
  }

  return (
    <div className={styles.pad}>
      <canvas
        ref={canvas}
        className={styles.canvas}
        role="img"
        aria-label={label}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          drawing.current = [at(event)];
          all.current = [...all.current, drawing.current];
        }}
        onPointerMove={(event) => {
          const stroke = drawing.current;
          if (!stroke) return;
          const point = at(event);
          const last = stroke[stroke.length - 1];
          if (last && Math.hypot(point[0] - last[0], point[1] - last[1]) < MIN_STEP) return;
          stroke.push(point);
          if (canvas.current) paintStrokes(canvas.current, all.current);
        }}
        onPointerUp={() => {
          if (!drawing.current) return;
          drawing.current = null;
          onChange([...all.current]);
        }}
        onPointerCancel={() => {
          drawing.current = null;
          onChange([...all.current]);
        }}
      />
      <span className={styles.line} aria-hidden="true" />
      <span className={styles.hint} aria-hidden="true">
        Draw here
      </span>
    </div>
  );
}
