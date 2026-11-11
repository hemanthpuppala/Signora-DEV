import { clamp } from "@/shared/lib/canvas";

import { FIELD_NAMES } from "../content";

import { createAutoplay } from "./autoplay";
import { q, qa } from "./dom";
import type { Scope } from "@/shared/lib/scope";

/**
 * §03: Signora reads a template. A light travels round the page while it reads, then each blank is
 * found in reading order: it fills, a hand-drawn arrow names it, and its cell in the row below
 * lights. Holds on the result and loops. Under reduced motion it shows the result.
 */
export function mountExtractionClip(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const stage = q(root, ".x-stage");
  const sheet = q(root, "#x-sheet");
  const status = q(root, "#x-status");
  const statusWrap = q(root, "#x-status-wrap");
  const fields = qa(sheet, ".xf");
  const notes = qa(sheet, ".x-note");
  const cells = qa(root, "#fields-row > div");

  /** An element's offset inside the sheet, before the sheet's own scaling. */
  function offsetInSheet(element: HTMLElement): { x: number; y: number } {
    let x = 0;
    let y = 0;
    let current: HTMLElement | null = element;
    while (current && current !== sheet) {
      x += current.offsetLeft;
      y += current.offsetTop;
      current = current.offsetParent as HTMLElement | null;
    }
    return { x, y };
  }
  function placeNotes(): void {
    fields.forEach((field, i) => {
      const note = notes[i];
      if (!note) return;
      const at = offsetInSheet(field);
      note.style.left = `${at.x + field.offsetWidth + 2}px`;
      note.style.top = `${at.y + field.offsetHeight / 2 - 25}px`;
    });
  }
  /** Scales the 400 × 480 sheet to the room the stage has. */
  function fit(): void {
    const scale = clamp(Math.min((stage.clientWidth - 48) / 400, (stage.clientHeight - 100) / 480), 0.4, 1.2);
    sheet.style.setProperty("--k", scale.toFixed(3));
  }
  function reset(): void {
    for (const field of fields) field.classList.remove("is-found");
    for (const note of notes) note.classList.remove("is-on");
    for (const cell of cells) cell.classList.remove("is-on");
    sheet.classList.remove("is-reading");
    status.textContent = "Reading template";
    statusWrap.classList.remove("is-done");
  }
  function found(field: HTMLElement): void {
    const index = Number(field.dataset.i);
    field.classList.add("is-found");
    const note = notes[fields.indexOf(field)];
    note?.classList.remove("is-fade");
    note?.classList.add("is-on");
    cells[index]?.classList.add("is-on");
    status.textContent = `Found · ${FIELD_NAMES[index] ?? ""}`;
  }
  function done(): void {
    status.textContent = `${fields.length} fields found`;
    statusWrap.classList.add("is-done");
  }

  fit();
  placeNotes();
  scope.onResize(fit);

  if (reduced) {
    sheet.classList.add("is-in");
    fields.forEach(found);
    done();
    return;
  }
  createAutoplay({
    scope,
    reduced,
    watch: stage,
    play: async (alive) => {
      reset();
      sheet.classList.add("is-in");
      await scope.sleep(700);
      if (!alive()) return false;
      sheet.classList.add("is-reading");
      await scope.sleep(1500);
      if (!alive()) return false;
      const inReadingOrder = [...fields].sort((a, b) => offsetInSheet(a).y - offsetInSheet(b).y);
      for (const [k, field] of inReadingOrder.entries()) {
        found(field);
        await scope.sleep(k < inReadingOrder.length - 1 ? 1150 : 1500);
        if (!alive()) return false;
      }
      sheet.classList.remove("is-reading");
      done();
      await scope.sleep(3000);
      if (!alive()) return false;
      for (const note of notes) note.classList.add("is-fade");
      for (const field of fields) field.classList.remove("is-found");
      await scope.sleep(650);
      return alive();
    },
  });
}
