"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { isMark, toneOf, type PartyRef, type PendingField } from "./fields";
import styles from "./fields.module.css";
import type { DraftField, Rect } from "./review/editor";

/** What is chosen in the panel and on the page: a field's place, or a place found before the AI. */
export type Selection = { kind: "field"; id: string; place: number } | { kind: "pending"; id: string; place: number };

const MIN_SHOWN = 8; // a checkbox stays clickable at any zoom
const DRAG = 3; // pixels before a press becomes a drag (a click selects)

type Handle = "move" | "nw" | "ne" | "sw" | "se";
type Gesture = { placeId: string; handle: Handle; x: number; y: number; rect: Rect; moved: boolean };

/** Editing on the page (Phase 6 §5): a tool to draw with, and what a gesture changes. */
export type BoxEditing = {
  /** Drawing a new box (the palette) or a new place of a field: the next press on a page. */
  drawing: boolean;
  onDraw: (page: number, rect: Rect | null, at: { x: number; y: number }) => void;
  onRect: (placeId: string, rect: Rect, keepSize: boolean) => void;
};

function moved(gesture: Gesture, dx: number, dy: number): Rect {
  const [x0, y0, x1, y1] = gesture.rect;
  switch (gesture.handle) {
    case "move":
      return [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
    case "nw":
      return [x0 + dx, y0 + dy, x1, y1];
    case "ne":
      return [x0, y0 + dy, x1 + dx, y1];
    case "sw":
      return [x0 + dx, y0, x1, y1 + dy];
    case "se":
      return [x0, y0, x1 + dx, y1 + dy];
  }
}

/**
 * The fields of one page drawn on the PDF (Phase 5 LLD §6.2-6.4, Phase 6 §5): a box per place, in
 * its party's tone; solid for information, dashed for a signature or initials, dotted for a field
 * that needs a look; grey while the AI has not said who fills it. The chosen place is marked. When
 * editing, a box is dragged to move it and its corners to resize it, and with a tool chosen a press
 * on the page places a new box (a click: its default size; a drag: the size drawn). Coordinates are
 * PDF points; ``scale`` only paints them. The boxes are for sight and the mouse; the panel's forms do
 * everything with the keyboard.
 */
export function FieldBoxes({
  page,
  scale,
  fields,
  pending,
  parties,
  selected,
  onSelect,
  editing,
}: {
  page: number;
  scale: number;
  fields: readonly DraftField[];
  pending: readonly PendingField[];
  parties: readonly PartyRef[];
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
  editing?: BoxEditing | null;
}) {
  const layer = useRef<HTMLDivElement>(null);
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const [live, setLive] = useState<Rect | null>(null); // the box under the pointer while dragging
  const [sketch, setSketch] = useState<{ x: number; y: number; rect: Rect | null } | null>(null);

  const point = (event: ReactPointerEvent) => {
    const box = layer.current?.getBoundingClientRect();
    return { x: (event.clientX - (box?.left ?? 0)) / scale, y: (event.clientY - (box?.top ?? 0)) / scale };
  };

  const startGesture = (event: ReactPointerEvent<HTMLElement>, placeId: string, handle: Handle, rect: Rect) => {
    if (!editing || editing.drawing || event.button !== 0) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setGesture({ placeId, handle, x: event.clientX, y: event.clientY, rect, moved: false });
  };
  const continueGesture = (event: ReactPointerEvent) => {
    if (!gesture) return;
    const dx = event.clientX - gesture.x;
    const dy = event.clientY - gesture.y;
    if (!gesture.moved && Math.hypot(dx, dy) < DRAG) return;
    if (!gesture.moved) setGesture({ ...gesture, moved: true });
    setLive(moved(gesture, dx / scale, dy / scale));
  };
  const endGesture = () => {
    if (gesture?.moved && live) editing?.onRect(gesture.placeId, live, gesture.handle === "move");
    setGesture(null);
    setLive(null);
  };

  const boxes: {
    id: string;
    className: string;
    rect: Rect;
    title: string;
    select: Selection;
    chosen: boolean;
    placeId: string | null;
  }[] = [];
  for (const field of fields) {
    field.places.forEach((place, index) => {
      if (place.page !== page) return;
      const classes = [styles.box, styles[toneOf(field, parties)]];
      if (isMark(field.holds)) classes.push(styles.mark);
      if (field.needs_review) classes.push(styles.review);
      boxes.push({
        id: place.id,
        className: classes.join(" "),
        rect: gesture?.placeId === place.id && live ? live : place.rect,
        title: field.label,
        select: { kind: "field", id: field.id, place: index },
        chosen: selected?.kind === "field" && selected.id === field.id && selected.place === index,
        placeId: place.id,
      });
    });
  }
  for (const found of pending) {
    found.placements.forEach((placement, index) => {
      if (placement.page !== page) return;
      const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = placement.rect;
      boxes.push({
        id: `${found.id}-${index}`,
        className: `${styles.box} ${styles.pending}`,
        rect: [x0, y0, x1, y1],
        title: found.label ?? "A place to fill",
        select: { kind: "pending", id: found.id, place: index },
        chosen: selected?.kind === "pending" && selected.id === found.id && selected.place === index,
        placeId: null,
      });
    });
  }

  const drawing = Boolean(editing?.drawing);
  const style = (rect: Rect) => ({
    left: rect[0] * scale,
    top: rect[1] * scale,
    width: Math.max((rect[2] - rect[0]) * scale, MIN_SHOWN),
    height: Math.max((rect[3] - rect[1]) * scale, MIN_SHOWN),
  });

  return (
    <div
      ref={layer}
      className={`${styles.boxes}${drawing ? ` ${styles.drawing}` : ""}`}
      data-layer="fields"
      aria-hidden="true"
      onPointerDown={(event) => {
        if (!drawing || event.button !== 0) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const at = point(event);
        setSketch({ ...at, rect: null });
      }}
      onPointerMove={(event) => {
        if (gesture) continueGesture(event);
        else if (sketch) {
          const at = point(event);
          if (Math.hypot(at.x - sketch.x, at.y - sketch.y) * scale >= DRAG) {
            setSketch({ ...sketch, rect: [sketch.x, sketch.y, at.x, at.y] });
          }
        }
      }}
      onPointerUp={() => {
        if (gesture) endGesture();
        else if (sketch) {
          editing?.onDraw(page, sketch.rect, { x: sketch.x, y: sketch.y });
          setSketch(null);
        }
      }}
      onPointerCancel={() => {
        setGesture(null);
        setLive(null);
        setSketch(null);
      }}
    >
      {boxes.map((box) => (
        <button
          key={box.id}
          type="button"
          tabIndex={-1}
          title={box.title}
          className={`${box.className}${box.chosen ? ` ${styles.chosen}` : ""}${editing && !drawing ? ` ${styles.movable}` : ""}`}
          style={style(box.rect)}
          onPointerDown={(event) => {
            if (box.placeId) startGesture(event, box.placeId, "move", box.rect);
          }}
          onClick={() => {
            if (!drawing) onSelect(box.select);
          }}
        >
          {box.chosen && editing && !drawing && box.placeId
            ? (["nw", "ne", "sw", "se"] as const).map((corner) => (
                <span
                  key={corner}
                  className={`${styles.handle} ${styles[corner]}`}
                  onPointerDown={(event) => box.placeId && startGesture(event, box.placeId, corner, box.rect)}
                />
              ))
            : null}
        </button>
      ))}
      {sketch?.rect ? <span className={`${styles.box} ${styles.sketch}`} style={style(normal(sketch.rect))} /> : null}
    </div>
  );
}

function normal([x0, y0, x1, y1]: Rect): Rect {
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
}
