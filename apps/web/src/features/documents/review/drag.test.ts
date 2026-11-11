import { describe, expect, it } from "vitest";

import { edgeSpeed, landingPage, slop } from "./drag";

const PAGES = [
  { page: 1, top: 0, bottom: 800 },
  { page: 2, top: 816, bottom: 1616 },
  { page: 3, top: 1632, bottom: 2432 },
];

describe("where a dragged box lands", () => {
  it("is the page its middle is over", () => {
    expect(landingPage(400, 1, PAGES)).toBe(1);
    expect(landingPage(900, 1, PAGES)).toBe(2);
    expect(landingPage(2000, 1, PAGES)).toBe(3);
  });

  it("is the nearest page when let go between two, or past the first or last", () => {
    expect(landingPage(803, 1, PAGES)).toBe(1);
    expect(landingPage(813, 1, PAGES)).toBe(2);
    expect(landingPage(-50, 2, PAGES)).toBe(1);
    expect(landingPage(9000, 1, PAGES)).toBe(3);
  });

  it("stays on its own page on a tie, and where no page is measured", () => {
    expect(landingPage(808, 2, PAGES)).toBe(2); // the middle of the gap
    expect(landingPage(808, 1, PAGES)).toBe(1);
    const unmeasured = PAGES.map(({ page }) => ({ page, top: 0, bottom: 0 }));
    expect(landingPage(500, 2, unmeasured)).toBe(2);
    expect(landingPage(500, 2, [])).toBe(2);
  });
});

describe("scrolling under a drag held near the edge", () => {
  it("is still in the middle, and faster the nearer the top or bottom", () => {
    expect(edgeSpeed(300, 0, 600)).toBe(0);
    expect(edgeSpeed(40, 0, 600)).toBeLessThan(0);
    expect(edgeSpeed(560, 0, 600)).toBeGreaterThan(0);
    expect(edgeSpeed(590, 0, 600)).toBeGreaterThan(edgeSpeed(560, 0, 600));
    expect(edgeSpeed(900, 0, 600)).toBe(edgeSpeed(600, 0, 600)); // past the edge: the fastest, no faster
    expect(edgeSpeed(-40, 0, 600)).toBe(-edgeSpeed(600, 0, 600));
  });

  it("does nothing where there is no middle to rest in", () => {
    expect(edgeSpeed(10, 0, 120)).toBe(0);
  });
});

describe("how far a press may wander before it is a drag", () => {
  it("is more for a finger than a mouse", () => {
    expect(slop("touch")).toBeGreaterThan(slop("mouse"));
    expect(slop("pen")).toBe(slop("mouse"));
  });
});
