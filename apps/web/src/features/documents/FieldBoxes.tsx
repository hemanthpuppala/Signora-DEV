"use client";

import { isMark, toneOf, type FieldView, type PendingField, type RoleView } from "./fields";
import styles from "./fields.module.css";

/** What is chosen in the panel and on the page: a field by key, or a place found before the AI. */
export type Selection = { kind: "field"; key: string; place: number } | { kind: "pending"; id: string; place: number };

const MIN_SIDE = 8; // a checkbox stays clickable at any zoom

/**
 * The fields of one page drawn on the PDF (Phase 5 LLD §6.2-6.4): a box per place, in its party's
 * tone; solid for information, dashed for a signature or initials, dotted for a field that needs a
 * look; grey while the AI has not said who fills it. The boxes are for sight and the mouse; the
 * panel's list is the same fields for the keyboard and screen readers.
 */
export function FieldBoxes({
  page,
  scale,
  fields,
  pending,
  roles,
  selected,
  onSelect,
}: {
  page: number;
  scale: number;
  fields: readonly FieldView[];
  pending: readonly PendingField[];
  roles: readonly RoleView[];
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const boxes: { id: string; className: string; rect: readonly number[]; title: string; select: Selection; chosen: boolean }[] = [];
  for (const field of fields) {
    field.placements.forEach((placement, place) => {
      if (placement.page !== page) return;
      const classes = [styles.box, styles[toneOf(field, roles)]];
      if (isMark(field.holds)) classes.push(styles.mark);
      if (field.needs_review) classes.push(styles.review);
      boxes.push({
        id: `${field.key}-${place}`,
        className: classes.join(" "),
        rect: placement.rect,
        title: field.label,
        select: { kind: "field", key: field.key, place },
        chosen: selected?.kind === "field" && selected.key === field.key,
      });
    });
  }
  for (const found of pending) {
    found.placements.forEach((placement, place) => {
      if (placement.page !== page) return;
      boxes.push({
        id: `${found.id}-${place}`,
        className: `${styles.box} ${styles.pending}`,
        rect: placement.rect,
        title: found.label ?? "A place to fill",
        select: { kind: "pending", id: found.id, place },
        chosen: selected?.kind === "pending" && selected.id === found.id,
      });
    });
  }
  return (
    <div className={styles.boxes} aria-hidden="true">
      {boxes.map((box) => {
        const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = box.rect;
        return (
          <button
            key={box.id}
            type="button"
            tabIndex={-1}
            title={box.title}
            className={`${box.className}${box.chosen ? ` ${styles.chosen}` : ""}`}
            style={{
              left: x0 * scale,
              top: y0 * scale,
              width: Math.max((x1 - x0) * scale, MIN_SIDE),
              height: Math.max((y1 - y0) * scale, MIN_SIDE),
            }}
            onClick={() => onSelect(box.select)}
          />
        );
      })}
    </div>
  );
}
