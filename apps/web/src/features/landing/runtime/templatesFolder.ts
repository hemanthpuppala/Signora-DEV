import { clamp } from "@/shared/lib/canvas";

import { TEAMS } from "../content";

import { createAutoplay } from "./autoplay";
import { q, qa } from "./dom";
import type { Scope } from "@/shared/lib/scope";

/**
 * §02: one folder that holds a team's templates. The demo opens it for each team in turn, fanning
 * the three templates out. The visitor can open the flap, pick a team, or open a single template.
 */
export function mountTemplatesFolder(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const folder = q(root, "#fd");
  const front = q<HTMLButtonElement>(root, "#fd-front");
  const papersSlot = q(root, "#fd-papers");
  const name = q(root, "#fd-name");
  const teamButtons = qa<HTMLButtonElement>(root, "#fd-teams button");
  let team = 0;
  let papers: HTMLButtonElement[] = [];

  function zoom(paper: HTMLButtonElement | null): void {
    for (const each of papers) each.classList.toggle("is-zoom", each === paper);
    folder.classList.toggle("has-zoom", paper !== null);
  }
  function setOpen(open: boolean): void {
    if (!open) zoom(null);
    folder.classList.toggle("is-open", open);
    front.setAttribute("aria-expanded", open ? "true" : "false");
    for (const paper of papers) paper.tabIndex = open ? 0 : -1;
  }
  function paperFor(title: string): HTMLButtonElement {
    const paper = document.createElement("button");
    paper.type = "button";
    paper.className = "fd-paper";
    paper.tabIndex = -1;
    paper.setAttribute("aria-label", `Open ${title}`);
    const heading = document.createElement("b");
    heading.textContent = title;
    const line = (className = "") => {
      const element = document.createElement("i");
      element.className = className;
      return element;
    };
    const signature = document.createElement("u");
    signature.textContent = "Signature";
    paper.append(heading, line(), line(), line("w70"), document.createElement("em"), line(), line("w56"), signature);
    return paper;
  }
  function fill(index: number): void {
    const next = TEAMS[index];
    if (!next) return;
    team = index;
    papers = next.templates.map(paperFor);
    papersSlot.replaceChildren(...papers);
    name.textContent = next.name;
    folder.setAttribute("aria-label", `${next.name} folder`);
    teamButtons.forEach((button, k) => button.setAttribute("aria-pressed", k === index ? "true" : "false"));
  }
  /** Closes the folder and changes its contents while they are faded out. */
  async function switchTo(index: number): Promise<void> {
    folder.classList.add("is-swap");
    await scope.sleep(280);
    setOpen(false);
    fill(index);
    await scope.sleep(40);
    folder.classList.remove("is-swap");
  }

  const autoplay = createAutoplay({
    scope,
    reduced,
    watch: folder,
    resume: q<HTMLButtonElement>(root, "#fd-resume"),
    onStart: () => setOpen(false),
    play: async (alive) => {
      for (let i = 0; i < TEAMS.length; i++) {
        if (i !== team) await switchTo(i);
        await scope.sleep(i ? 450 : 800);
        if (!alive()) return false;
        setOpen(true);
        await scope.sleep(2600);
        if (!alive()) return false;
        setOpen(false);
        await scope.sleep(950);
        if (!alive()) return false;
      }
      return alive();
    },
  });

  scope.on(front, "click", () => {
    const wasOpen = folder.classList.contains("is-open");
    autoplay.takeOver();
    setOpen(!wasOpen);
  });
  // Opening one template: it lifts out and straightens; a second click puts it back.
  scope.on<MouseEvent>(papersSlot, "click", (event) => {
    const paper = (event.target as Element).closest<HTMLButtonElement>(".fd-paper");
    if (!paper || !folder.classList.contains("is-open")) return;
    autoplay.takeOver();
    zoom(paper.classList.contains("is-zoom") ? null : paper);
  });
  teamButtons.forEach((button, index) => {
    scope.on(button, "click", async () => {
      autoplay.takeOver();
      if (index !== team) {
        setOpen(false);
        await scope.sleep(1000);
        await switchTo(index);
        await scope.sleep(120);
      }
      setOpen(true);
    });
  });

  // The folder turns to face the pointer (up to about 12°) on a spring, and settles back on leave.
  const tilt = { x: 0, y: 0, targetX: 0, targetY: 0, speedX: 0, speedY: 0, frame: 0 };
  const tiltTick = () => {
    tilt.speedX = (tilt.speedX + (tilt.targetX - tilt.x) * 0.08) * 0.78;
    tilt.speedY = (tilt.speedY + (tilt.targetY - tilt.y) * 0.08) * 0.78;
    tilt.x += tilt.speedX;
    tilt.y += tilt.speedY;
    folder.style.setProperty("--ry", `${(tilt.x * 12).toFixed(2)}deg`);
    folder.style.setProperty("--rx", `${(-tilt.y * 9).toFixed(2)}deg`);
    const moving =
      Math.abs(tilt.targetX - tilt.x) + Math.abs(tilt.targetY - tilt.y) + Math.abs(tilt.speedX) + Math.abs(tilt.speedY) >
      0.001;
    tilt.frame = moving ? scope.frame(tiltTick) : 0;
  };
  const tiltTo = (x: number, y: number) => {
    tilt.targetX = x;
    tilt.targetY = y;
    if (!tilt.frame && !reduced) tilt.frame = scope.frame(tiltTick);
  };
  const stage = q(root, ".fd-stage");
  scope.on<PointerEvent>(stage, "pointermove", (event) => {
    if (event.pointerType === "touch") return;
    const box = folder.getBoundingClientRect();
    const centerX = box.left + box.width / 2;
    const centerY = box.top + box.height / 2;
    tiltTo(
      clamp((event.clientX - centerX) / (box.width * 0.9), -1, 1),
      clamp((event.clientY - centerY) / (box.height * 1.2), -1, 1),
    );
  });
  scope.on(stage, "pointerleave", () => tiltTo(0, 0));

  fill(0);
  setOpen(reduced);
}
