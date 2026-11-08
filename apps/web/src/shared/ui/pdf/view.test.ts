import { describe, expect, it } from "vitest";

import {
  canvasSize,
  clampZoom,
  cssSize,
  fitScale,
  pageAt,
  pageOffsets,
  stepZoom,
  wheelFactor,
  ZOOM_MAX,
  ZOOM_MIN,
} from "./view";

const A4 = { width: 595, height: 842 };
const LANDSCAPE = { width: 842, height: 595 };

describe("pdf viewer layout", () => {
  it("fits the widest page into the pane, within the zoom limits", () => {
    expect(fitScale(595 + 32, [A4])).toBe(1);
    expect(fitScale(842 + 32, [A4, LANDSCAPE])).toBe(1);
    expect(fitScale(0, [A4])).toBe(1);
    expect(fitScale(100_000, [A4])).toBe(ZOOM_MAX);
    expect(fitScale(40, [A4])).toBe(ZOOM_MIN);
  });

  it("steps zoom to the next quarter and clamps", () => {
    expect(stepZoom(1, 1)).toBe(1.25);
    expect(stepZoom(1.1, 1)).toBe(1.25);
    expect(stepZoom(1.1, -1)).toBe(1);
    expect(stepZoom(ZOOM_MIN, -1)).toBe(ZOOM_MIN);
    expect(clampZoom(Number.NaN)).toBe(1);
  });

  it("zooms in on a wheel up and out on a wheel down, gently", () => {
    expect(wheelFactor(-100)).toBeGreaterThan(1);
    expect(wheelFactor(100)).toBeLessThan(1);
    expect(wheelFactor(-10_000)).toBe(1.5);
  });

  it("sizes canvases for sharp rendering on dense screens", () => {
    expect(cssSize(A4, 1.5)).toEqual({ width: 893, height: 1263 });
    expect(canvasSize(A4, 1.5, 2)).toEqual({ width: 1785, height: 2526, renderScale: 3 });
  });

  it("knows which page is in the middle of the view", () => {
    const offsets = pageOffsets([A4, A4, A4], 1);
    expect(offsets).toEqual([0, 858, 1716]);
    expect(pageAt(offsets, 0, 800)).toBe(1);
    expect(pageAt(offsets, 600, 800)).toBe(2);
    expect(pageAt(offsets, 5000, 800)).toBe(3);
  });
});
