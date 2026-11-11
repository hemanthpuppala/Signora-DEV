import { LANE_STEPS } from "../content";

import { createAutoplay } from "./autoplay";
import { q, qa } from "./dom";
import type { Scope } from "./scope";

const SVG_NS = "http://www.w3.org/2000/svg";

type Geometry = {
  points: { x: number; y: number }[];
  /** Path length at each step. */
  lengths: number[];
  total: number;
  path: SVGPathElement;
  labels: HTMLElement[];
};

/**
 * §06: an envelope's record as hand-offs between people. A document token rides one continuous
 * line that draws as it travels; each step's label appears on arrival and the acting person's lane
 * lights. Holds on the finished record and loops. Under reduced motion it shows the finished record.
 */
export function mountFirmLanes(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const stage = q(root, "#ln-stage");
  const svg = q<SVGSVGElement>(root, "#ln-svg");
  const token = q(root, "#ln-tok");
  const labelSlot = q(root, "#ln-labels");
  const fade = q(root, "#ln-fade");
  const lanes = qa(root, "#ln-cols > div");
  const lastStep = LANE_STEPS.length - 1;

  /** Lays the path and labels out for the stage's current size, with the token at the start. */
  function build(): Geometry {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    const top = 52;
    const rowHeight = (height - top - 16) / lastStep;
    const laneWidth = width / lanes.length;
    const points = LANE_STEPS.map(([, lane], i) => ({
      x: lane * laneWidth + Math.min(22, laneWidth * 0.18),
      y: top + i * rowHeight,
    }));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const path = document.createElementNS(SVG_NS, "path");
    svg.replaceChildren(path);
    // Each leg is a vertical S-curve; the length is measured after each leg is added.
    const lengths = [0];
    let d = "";
    points.forEach((point, i) => {
      const previous = points[i - 1];
      if (!previous) {
        d = `M${point.x} ${point.y}`;
        return;
      }
      const middle = (previous.y + point.y) / 2;
      d += ` C${previous.x} ${middle} ${point.x} ${middle} ${point.x} ${point.y}`;
      path.setAttribute("d", d);
      lengths.push(path.getTotalLength());
    });
    const total = lengths[lengths.length - 1] ?? 0;
    path.style.strokeDasharray = String(total);
    const labels = points.map((point, i) => {
      const label = document.createElement("span");
      label.className = "ln-label";
      label.textContent = LANE_STEPS[i]?.[0] ?? "";
      label.style.left = `${point.x}px`;
      label.style.top = `${point.y}px`;
      return label;
    });
    labelSlot.replaceChildren(...labels);
    const built = { points, lengths, total, path, labels };
    place(built, 0);
    return built;
  }
  /** Puts the token `length` along the path and draws the line up to it. */
  function place(g: Geometry, length: number): void {
    const at = g.path.getPointAtLength(length);
    token.style.transform = `translate(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px)`;
    g.path.style.strokeDashoffset = (g.total - length).toFixed(1);
  }
  function dot(g: Geometry, step: number): void {
    const point = g.points[step];
    if (!point) return;
    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("cx", String(point.x));
    circle.setAttribute("cy", String(point.y));
    circle.setAttribute("r", "2.4");
    svg.appendChild(circle);
  }
  function lightLane(lane: number | null): void {
    lanes.forEach((element, k) => element.classList.toggle("is-now", k === lane));
  }
  function arrive(g: Geometry, step: number): void {
    dot(g, step);
    g.labels.forEach((label, k) => {
      label.classList.toggle("is-in", k <= step);
      label.classList.toggle("is-now", k === step);
    });
    lightLane(LANE_STEPS[step]?.[1] ?? null);
  }
  function travel(g: Geometry, from: number, to: number, alive: () => boolean): Promise<boolean> {
    return new Promise((resolve) => {
      const started = performance.now();
      const duration = Math.max(700, Math.min(1300, (to - from) * 4.2));
      const tick = (now: number) => {
        if (!alive()) {
          resolve(false);
          return;
        }
        const u = Math.min(1, (now - started) / duration);
        const eased = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
        place(g, from + (to - from) * eased);
        if (u < 1) scope.frame(tick);
        else resolve(true);
      };
      scope.frame(tick);
    });
  }

  if (reduced) {
    const still = () => {
      const g = build();
      place(g, g.total);
      LANE_STEPS.forEach((_, i) => dot(g, i));
      for (const label of g.labels) label.classList.add("is-in");
    };
    still();
    scope.onResize(still);
    return;
  }

  build();
  const autoplay = createAutoplay({
    scope,
    reduced,
    watch: q(root, "#trail"),
    play: async (alive) => {
      const g = build();
      lightLane(null);
      fade.classList.remove("is-out");
      await scope.sleep(500);
      if (!alive()) return false;
      arrive(g, 0);
      await scope.sleep(1100);
      if (!alive()) return false;
      for (let step = 1; step <= lastStep; step++) {
        const arrived = await travel(g, g.lengths[step - 1] ?? 0, g.lengths[step] ?? g.total, alive);
        if (!arrived) return false;
        arrive(g, step);
        await scope.sleep(950);
        if (!alive()) return false;
      }
      g.labels[lastStep]?.classList.remove("is-now");
      await scope.sleep(2800);
      if (!alive()) return false;
      fade.classList.add("is-out");
      lightLane(null);
      await scope.sleep(700);
      return alive();
    },
  });
  // The path is laid out in pixels, so a change of width starts the record again at the new size.
  let width = stage.clientWidth;
  scope.on(window, "resize", () => {
    if (Math.abs(stage.clientWidth - width) < 2) return;
    width = stage.clientWidth;
    if (autoplay.isOn()) autoplay.restart();
    else build();
  });
}
