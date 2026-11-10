"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

import { isMark, toneOf, type PartyRef, type PendingField } from "./fields";
import styles from "./fields.module.css";
import { edgeSpeed, landingPage, scrollParent, slop } from "./review/drag";
import type { DraftField, Rect } from "./review/editor";

/** What is chosen in the panel and on the page: a field's place, or a place found before the AI. */
export type Selection = { kind: "field"; id: string; place: number } | { kind: "pending"; id: string; place: number };

const MIN_SHOWN = 8; // a checkbox stays clickable at any zoom
const LAYER = '[data-layer="fields"]';

/** Editing on the page (Phase 6 §5, §5.1): a tool to draw with, and what a gesture changes. */
export type BoxEditing = {
  /** Drawing a new box (the palette) or a new place of a field: the next press on a page. */
  drawing: boolean;
  onDraw: (page: number, rect: Rect | null, at: { x: number; y: number }) => void;
  /** A box let go on a page, its own or another; ``rect`` is in that page's points. */
  onMove: (placeId: string, page: number, rect: Rect) => void;
  onResize: (placeId: string, rect: Rect) => void;
};

/**
 * The fields of one page drawn on the PDF (Phase 5 LLD §6.2-6.4, Phase 6 §5): a box per place, in
 * its party's tone; solid for information, dashed for a signature or initials, dotted for a field
 * that needs a look; grey while the AI has not said who fills it. The chosen place is marked. When
 * editing, a box is dragged to move it and its corners to resize it, and with a tool chosen a press
 * on the page places a new box (a click or a tap: its default size; a mouse's drag: the size drawn).
 * Coordinates are PDF points; ``scale`` only paints them.
 *
 * By mouse or by finger (§5.1). A finger's drag on the page scrolls it, so a finger moves only the
 * chosen box: a tap chooses, the next drag moves. A box dragged past its page lands on the page it
 * is over, and a drag held near the top or bottom of the pages scrolls them. The boxes are for
 * sight and the pointer; the panel's forms do everything with the keyboard.
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
  const drag = useBoxDrag(layer, page, scale, editing?.drawing ? null : editing);
  const live = drag.live;
  const [sketch, setSketch] = useState<{ x: number; y: number; rect: Rect | null; draws: boolean } | null>(null);
  const point = drag.point;

  const boxes: {
    id: string;
    className: string;
    rect: Rect;
    title: string;
    select: Selection;
    chosen: boolean;
    placeId: string | null;
    dragged: boolean;
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
        rect: live?.placeId === place.id ? live.rect : place.rect,
        title: field.label,
        select: { kind: "field", id: field.id, place: index },
        chosen: selected?.kind === "field" && selected.id === field.id && selected.place === index,
        placeId: place.id,
        dragged: live?.placeId === place.id,
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
        dragged: false,
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
      data-page={page}
      aria-hidden="true"
      onPointerDown={(event) => {
        if (!drawing || event.button !== 0) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        // A tap places the default size: a finger's drag belongs to scrolling, and its wobble is no drawing.
        setSketch({ ...point(event.clientX, event.clientY), rect: null, draws: event.pointerType !== "touch" });
      }}
      onPointerMove={(event) => {
        if (drag.move(event)) return;
        if (sketch?.draws) {
          const at = point(event.clientX, event.clientY);
          if (Math.hypot(at.x - sketch.x, at.y - sketch.y) * scale >= slop(event.pointerType)) {
            setSketch({ ...sketch, rect: [sketch.x, sketch.y, at.x, at.y] });
          }
        }
      }}
      onPointerUp={() => {
        if (drag.end()) return;
        if (sketch) {
          editing?.onDraw(page, sketch.rect, { x: sketch.x, y: sketch.y });
          setSketch(null);
        }
      }}
      onPointerCancel={() => {
        drag.cancel();
        setSketch(null);
      }}
    >
      {boxes.map((box) => (
        <button
          key={box.id}
          type="button"
          tabIndex={-1}
          title={box.title}
          className={[
            box.className,
            box.chosen ? styles.chosen : "",
            editing && !drawing ? styles.movable : "",
            box.dragged ? styles.dragged : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={style(box.rect)}
          onPointerDown={(event) => {
            if (box.placeId) drag.start(event, box.placeId, "move", box.rect, box.chosen);
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
                  onPointerDown={(event) => box.placeId && drag.start(event, box.placeId, corner, box.rect, true)}
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

type Handle = "move" | "nw" | "ne" | "sw" | "se";
/** A box held by a pointer (a ref, not state: the frames that scroll the pages read it live). */
type Gesture = {
  placeId: string;
  handle: Handle;
  from: { x: number; y: number }; // where the press began, in this page's points
  rect: Rect; // the box as the press found it
  slop: number; // px the press may wander before it is a drag (a click selects)
  client: { x: number; y: number }; // where the pointer is now, on screen
  live: Rect | null; // the box under the pointer, once it is a drag
  pane: HTMLElement | null; // what scrolls the pages
  frame: number | null;
};

function moved(gesture: Pick<Gesture, "handle" | "rect">, dx: number, dy: number): Rect {
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
 * A box held and dragged on one page's layer (§5, §5.1): moved, or resized by a corner. The box
 * follows the pointer measured against the page, so the pages scrolling under a held drag count; a
 * moved box lands on the page its middle is over. ``move`` and ``end`` say whether a box was held.
 */
function useBoxDrag(
  layer: RefObject<HTMLDivElement | null>,
  page: number,
  scale: number,
  editing: Pick<BoxEditing, "onMove" | "onResize"> | null | undefined,
) {
  const gesture = useRef<Gesture | null>(null);
  const [live, setLive] = useState<{ placeId: string; rect: Rect } | null>(null); // the box while dragged

  const point = (clientX: number, clientY: number) => {
    const box = layer.current?.getBoundingClientRect();
    return { x: (clientX - (box?.left ?? 0)) / scale, y: (clientY - (box?.top ?? 0)) / scale };
  };

  /** The held box follows the pointer: measured against the page, so scrolling under it counts. */
  const follow = () => {
    const held = gesture.current;
    if (!held) return;
    const at = point(held.client.x, held.client.y);
    const [dx, dy] = [at.x - held.from.x, at.y - held.from.y];
    if (!held.live && Math.hypot(dx, dy) * scale < held.slop) return;
    held.live = moved(held, dx, dy);
    setLive({ placeId: held.placeId, rect: held.live });
  };
  /** Each frame of a drag: with the pointer near the top or bottom of the pages, they scroll. */
  const scrollUnder = () => {
    const held = gesture.current;
    if (!held) return;
    if (held.pane && held.live) {
      const box = held.pane.getBoundingClientRect();
      const before = held.pane.scrollTop;
      held.pane.scrollTop += edgeSpeed(held.client.y, box.top, box.bottom);
      if (held.pane.scrollTop !== before) follow();
    }
    held.frame = requestAnimationFrame(scrollUnder);
  };
  const letGo = () => {
    if (gesture.current?.frame != null) cancelAnimationFrame(gesture.current.frame);
    gesture.current = null;
    setLive(null);
  };
  useEffect(
    () => () => {
      if (gesture.current?.frame != null) cancelAnimationFrame(gesture.current.frame); // a page that leaves mid-drag
    },
    [],
  );

  /** Where a moved box lands: its own page, or the one its middle is over, in that page's points. */
  const landing = (rect: Rect, pane: HTMLElement | null): { page: number; rect: Rect } => {
    const own = layer.current?.getBoundingClientRect();
    if (!own) return { page, rect };
    const middle = own.top + ((rect[1] + rect[3]) / 2) * scale;
    if (middle >= own.top && middle <= own.bottom) return { page, rect };
    const layers = [...(pane ?? layer.current?.ownerDocument)?.querySelectorAll<HTMLElement>(LAYER) ?? []].map((element) => ({
      page: Number(element.dataset.page),
      box: element.getBoundingClientRect(),
    }));
    const to = landingPage(middle, page, layers.map(({ page, box }) => ({ page, top: box.top, bottom: box.bottom })));
    const target = layers.find((other) => other.page === to);
    if (!target || to === page) return { page, rect };
    const [dx, dy] = [(own.left - target.box.left) / scale, (own.top - target.box.top) / scale];
    return { page: to, rect: [rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy] };
  };

  const start = (event: ReactPointerEvent<HTMLElement>, placeId: string, handle: Handle, rect: Rect, chosen: boolean) => {
    if (!editing || event.button !== 0) return;
    // A finger's drag scrolls the page; only the chosen box takes it (its tap chose it).
    if (event.pointerType === "touch" && !chosen) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    gesture.current = {
      placeId,
      handle,
      from: point(event.clientX, event.clientY),
      rect,
      slop: slop(event.pointerType),
      client: { x: event.clientX, y: event.clientY },
      live: null,
      pane: scrollParent(layer.current),
      frame: null,
    };
    gesture.current.frame = requestAnimationFrame(scrollUnder);
  };
  const move = (event: ReactPointerEvent) => {
    if (!gesture.current) return false;
    gesture.current.client = { x: event.clientX, y: event.clientY };
    follow();
    return true;
  };
  const end = () => {
    const held = gesture.current;
    if (!held) return false;
    if (held.live && editing) {
      if (held.handle === "move") {
        const to = landing(held.live, held.pane);
        editing.onMove(held.placeId, to.page, to.rect);
      } else editing.onResize(held.placeId, held.live);
    }
    letGo();
    return true;
  };
  return { live, point, start, move, end, cancel: letGo };


}
