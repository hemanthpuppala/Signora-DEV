import { looksLikeEmail } from "@/shared/lib/email";

import { FIELD_NAMES, SAMPLE_TEMPLATE } from "../content";

import { createAutoplay } from "./autoplay";
import { fieldError, q, qa, setBusy } from "./dom";
import type { Toast } from "./pageChrome";
import type { PhoneSigning } from "./phoneSigning";
import type { Scope } from "@/shared/lib/scope";

const SVG_NS = "http://www.w3.org/2000/svg";
const ACCEPTED = ["pdf", "docx"];
/** What the preview "finds": the template's fields plus the client's email. */
const FOUND_FIELDS = [...FIELD_NAMES, "Client email"];

type TemplateFile = { name: string; size: number; sample: boolean };
type Client = { name: string; email: string; matter: string };
type Point = { x: number; y: number };

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
const extensionOf = (name: string) => (name.split(".").pop() ?? "").toLowerCase();
const withoutExtension = (name: string) => name.replace(/\.(pdf|docx)$/i, "");

function tickIcon(): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "tick");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M3 8.5l3.2 3L13 4.5");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.5");
  svg.appendChild(path);
  return svg;
}

/**
 * §04: a working four-step envelope builder (upload, extract, client details, send) that ends on a
 * six-digit access code. Nothing leaves the page: the file is only named, the fields are samples.
 * It plays itself with an animated cursor until the visitor touches it; an envelope the visitor
 * sends is handed to the phone in §05.
 */
export function mountEnvelopeBuilder(
  root: HTMLElement,
  scope: Scope,
  reduced: boolean,
  phone: PhoneSigning,
  toast: Toast,
): void {
  const builder = q(root, "#builder");
  const panes = qa(builder, ".pane");
  const steps = qa(builder, ".steps li");
  const words = qa(root, ".how-words span");
  const fileInput = q<HTMLInputElement>(builder, "#file-in");
  const dropZone = q(builder, "#drop");
  const fileSlot = q(builder, "#file-slot");
  const fileErrorSlot = q(builder, "#file-err");
  const toExtract = q<HTMLButtonElement>(builder, "#to-2");
  const toDetails = q<HTMLButtonElement>(builder, "#to-3");
  const useSample = q<HTMLButtonElement>(builder, "#use-sample");
  const foundList = q(builder, "#found");
  const extractNote = q(builder, "#extract-note");
  const scan = q(builder, "#scan");
  const details = q<HTMLFormElement>(builder, "#details");
  const nameInput = q<HTMLInputElement>(builder, "#c-name");
  const emailInput = q<HTMLInputElement>(builder, "#c-email");
  const matterInput = q<HTMLInputElement>(builder, "#c-matter");
  const nameError = q(builder, "#c-name-err");
  const emailError = q(builder, "#c-email-err");
  const review = q<HTMLButtonElement>(builder, "#to-4");
  const summary = q(builder, "#summary");
  const sendView = q(builder, "#send-view");
  const sentView = q(builder, "#sent-view");
  const sendButton = q<HTMLButtonElement>(builder, "#send-btn");
  const codeShow = q(builder, "#code-show");
  const wait = (ms: number) => scope.sleep(reduced ? 0 : ms);

  let file: TemplateFile | null = null;
  let client: Client | null = null;
  let code: string | null = null;
  /** Bumped on every extraction, so a superseded run's timers do nothing. */
  let extraction = 0;

  // ── Steps ──
  function go(step: number): void {
    for (const pane of panes) {
      const number = Number(pane.dataset.pane);
      pane.classList.toggle("is-active", number === step);
      pane.classList.toggle("is-left", number < step);
      pane.inert = number !== step;
    }
    steps.forEach((item, i) => {
      if (i + 1 === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
      item.classList.toggle("is-done", i + 1 < step);
    });
    words.forEach((word, i) => {
      word.classList.toggle("is-on", i + 1 === step);
      word.classList.toggle("is-done", i + 1 < step);
    });
  }

  // ── 01 Upload ──
  function clearFile(): void {
    file = null;
    fileSlot.replaceChildren();
    fileInput.value = "";
    toExtract.disabled = true;
  }
  function setFile(next: TemplateFile): void {
    const extension = extensionOf(next.name);
    if (!ACCEPTED.includes(extension)) {
      clearFile();
      fileErrorSlot.textContent = `Signora takes PDF or DOCX files. "${next.name}" is a .${extension} file.`;
      return;
    }
    fileErrorSlot.textContent = "";
    file = next;
    const row = document.createElement("div");
    row.className = "file";
    const icon = document.createElement("span");
    icon.className = "file-ico";
    icon.textContent = extension.toUpperCase();
    const meta = document.createElement("span");
    meta.className = "file-meta";
    const title = document.createElement("b");
    title.textContent = next.name;
    const size = document.createElement("span");
    size.textContent = `${next.sample ? "Sample template · " : ""}${formatSize(next.size)}`;
    meta.append(title, size);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "link-btn";
    remove.textContent = "Remove";
    remove.addEventListener("click", clearFile);
    row.append(icon, meta, remove);
    fileSlot.replaceChildren(row);
    toExtract.disabled = false;
  }
  const setSample = () => setFile({ ...SAMPLE_TEMPLATE, sample: true });
  const fromUpload = (upload: File | undefined) => {
    if (upload) setFile({ name: upload.name, size: upload.size, sample: false });
  };
  scope.on(fileInput, "change", () => fromUpload(fileInput.files?.[0]));
  for (const type of ["dragenter", "dragover"]) {
    scope.on(dropZone, type, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-over");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    scope.on(dropZone, type, (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-over");
    });
  }
  scope.on<DragEvent>(dropZone, "drop", (event) => fromUpload(event.dataTransfer?.files[0]));
  scope.on(useSample, "click", setSample);

  // ── 02 Extract ──
  function runExtract(): void {
    const run = ++extraction;
    const current = () => run === extraction;
    foundList.replaceChildren();
    toDetails.disabled = true;
    extractNote.textContent = `Reading ${file?.name ?? "the document"}…`;
    scan.classList.remove("is-scanning");
    void scan.offsetWidth; // restart the scan line
    scan.classList.add("is-scanning");
    FOUND_FIELDS.forEach((name, i) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = name;
      item.append(label, tickIcon());
      foundList.appendChild(item);
      scope.timeout(() => item.classList.add("is-in"), reduced ? 0 : 500 + i * 360);
    });
    scope.timeout(
      () => {
        if (!current()) return;
        extractNote.textContent = `${FOUND_FIELDS.length} fields found · this preview shows sample fields`;
        toDetails.disabled = false;
      },
      reduced ? 0 : 500 + FOUND_FIELDS.length * 360 + 200,
    );
  }
  scope.on(toExtract, "click", () => {
    go(2);
    runExtract();
  });
  scope.on(toDetails, "click", () => {
    go(3);
    scope.timeout(() => nameInput.focus({ preventScroll: true }), 220);
  });
  for (const back of qa(builder, "[data-back]")) {
    scope.on(back, "click", () => go(Number(back.dataset.back)));
  }

  // ── 03 Details ──
  scope.on<SubmitEvent>(details, "submit", (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    const nameOk = fieldError(nameInput, nameError, name ? "" : "Enter the client's name.");
    const emailOk = fieldError(
      emailInput,
      emailError,
      looksLikeEmail(email) ? "" : "Enter an email like name@example.com.",
    );
    if (!nameOk || !emailOk) {
      (nameOk ? emailInput : nameInput).focus();
      return;
    }
    client = { name, email, matter: matterInput.value.trim() };
    const rows: [string, string][] = [
      ["Document", file?.name ?? ""],
      ["To", `${name} · ${email}`],
      ["Matter", client.matter || "—"],
      ["Opens with", "A six-digit access code"],
    ];
    summary.replaceChildren(
      ...rows.flatMap(([term, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.textContent = value;
        return [dt, dd];
      }),
    );
    sendView.hidden = false;
    sentView.hidden = true;
    go(4);
  });

  // ── 04 Send ──
  scope.on(sendButton, "click", async () => {
    const restore = setBusy(sendButton, "Sending");
    await wait(1000);
    restore();
    if (!file || !client) return;
    const sent = Array.from({ length: 6 }, () => Math.floor(Math.random() * 10)).join("");
    code = sent;
    codeShow.replaceChildren(
      ...[...sent].map((digit) => {
        const cell = document.createElement("span");
        cell.textContent = digit;
        return cell;
      }),
    );
    codeShow.setAttribute("aria-label", `Access code ${[...sent].join(" ")}`);
    q(builder, "#sent-line").textContent = `Sent to ${client.name}. They need this code to open ${file.name}.`;
    sendView.hidden = true;
    sentView.hidden = false;
    // Only an envelope the visitor sent reaches the phone; the demo's own does not.
    if (autoplay.isOn()) return;
    phone.setEnvelope({ code: sent, clientName: client.name, documentName: withoutExtension(file.name) });
    toast("Envelope sent");
  });
  scope.on(q(builder, "#copy-code"), "click", async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      toast("Code copied");
    } catch {
      toast(`Code: ${code}`);
    }
  });
  // The link scrolls to the phone; the code field takes focus once the scroll has settled.
  scope.on(q(builder, "#as-client"), "click", () => {
    scope.timeout(() => phone.focusCode(), 750);
  });

  function reset(): void {
    client = null;
    code = null;
    extraction++;
    clearFile();
    fileErrorSlot.textContent = "";
    details.reset();
    for (const input of [nameInput, emailInput]) input.removeAttribute("aria-invalid");
    nameError.textContent = emailError.textContent = "";
    foundList.replaceChildren();
    toDetails.disabled = true;
    sendView.hidden = false;
    sentView.hidden = true;
    go(1);
  }
  scope.on(q(builder, "#new-env"), "click", () => {
    reset();
    phone.setEnvelope(null);
  });

  // ── The demo cursor: flights follow a curved Bézier that settles with a small overshoot; the
  //    arrow leans into its horizontal speed, turns to face the way it travels, and squashes on a click. ──
  const cursor = q(builder, "#demo-cursor");
  type Flight = { from: Point; to: Point; c1: Point; c2: Point; started: number; duration: number; done: () => void };
  const pointer = { x: 0, y: 0, lean: 0, previousX: 0, turn: 0, turnTarget: 0, side: 1, frame: 0 };
  let flight: Flight | null = null;
  function cursorTick(now: number): void {
    if (flight) {
      const { from, to, c1, c2 } = flight;
      const u = Math.min(1, (now - flight.started) / flight.duration);
      const eased = u * u * (3 - 2 * u);
      const overshoot = 1.15;
      const m = eased - 1;
      const k = 1 + (overshoot + 1) * m * m * m + overshoot * m * m;
      const r = 1 - k;
      const [b0, b1, b2, b3] = [r * r * r, 3 * r * r * k, 3 * r * k * k, k * k * k];
      pointer.x = b0 * from.x + b1 * c1.x + b2 * c2.x + b3 * to.x;
      pointer.y = b0 * from.y + b1 * c1.y + b2 * c2.y + b3 * to.y;
      if (u >= 1) {
        const { done } = flight;
        pointer.x = to.x;
        pointer.y = to.y;
        flight = null;
        done();
      }
    }
    const speed = pointer.x - pointer.previousX;
    pointer.previousX = pointer.x;
    pointer.lean += (Math.max(-20, Math.min(20, speed * 1.3)) - pointer.lean) * 0.15;
    pointer.turn += (pointer.turnTarget - pointer.turn) * 0.13;
    cursor.style.transform =
      `translate(${(pointer.x - 5).toFixed(1)}px,${(pointer.y - 4).toFixed(1)}px) perspective(420px) ` +
      `rotate(${pointer.lean.toFixed(2)}deg) rotateY(${pointer.turn.toFixed(1)}deg)`;
    const moving =
      autoplay.isOn() || flight || Math.abs(pointer.lean) > 0.05 || Math.abs(pointer.turnTarget - pointer.turn) > 0.2;
    pointer.frame = moving ? scope.frame(cursorTick) : 0;
  }
  const runCursor = () => {
    if (!pointer.frame) pointer.frame = scope.frame(cursorTick);
  };
  function place(at: Point): void {
    pointer.x = pointer.previousX = at.x;
    pointer.y = at.y;
    pointer.lean = pointer.turn = pointer.turnTarget = 0;
    flight = null;
    runCursor();
  }
  function fly(to: Point): Promise<void> {
    return new Promise((done) => {
      const dx = to.x - pointer.x;
      const dy = to.y - pointer.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 1) {
        done();
        return;
      }
      if (dx > 24) pointer.turnTarget = 180;
      else if (dx < -24) pointer.turnTarget = 0;
      // An S-shaped path: the two control points bow to opposite sides of the straight line.
      pointer.side = -pointer.side;
      const normal = { x: -dy / distance, y: dx / distance };
      const long = distance > 180;
      const bend = (long ? Math.min(80, distance * 0.2) : distance * 0.16) * pointer.side;
      const back = long ? -0.75 : 0.55;
      flight = {
        from: { x: pointer.x, y: pointer.y },
        to,
        c1: { x: pointer.x + dx * 0.3 + normal.x * bend, y: pointer.y + dy * 0.3 + normal.y * bend },
        c2: { x: pointer.x + dx * 0.7 + normal.x * bend * back, y: pointer.y + dy * 0.7 + normal.y * bend * back },
        started: performance.now(),
        duration: Math.min(1150, 560 + distance * 0.9),
        done,
      };
      runCursor();
    });
  }
  /** A point on `element` in the builder's coordinates: its centre, or an offset from an edge. */
  function pointOn(element: Element, offsetX?: number, offsetY?: number): Point {
    const frame = builder.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    const along = (size: number, offset?: number) =>
      offset === undefined ? size / 2 : offset < 0 ? size + offset : offset;
    return {
      x: box.left - frame.left + along(box.width, offsetX),
      y: box.top - frame.top + along(box.height, offsetY),
    };
  }
  function press(): void {
    cursor.classList.add("is-press");
    scope.timeout(() => cursor.classList.remove("is-press"), 180);
    const ripple = document.createElement("span");
    ripple.className = "demo-ripple";
    ripple.style.left = `${pointer.x}px`;
    ripple.style.top = `${pointer.y}px`;
    builder.appendChild(ripple);
    scope.timeout(() => ripple.remove(), 650);
  }
  scope.add(() => qa(builder, ".demo-ripple").forEach((ripple) => ripple.remove()));

  const autoplay = createAutoplay({
    scope,
    reduced,
    watch: builder,
    resume: q<HTMLButtonElement>(root, "#demo-resume"),
    onStop: () => cursor.classList.remove("is-on"),
    play: async (alive) => {
      const click = async (element: Element, offsetX?: number, offsetY?: number) => {
        await fly(pointOn(element, offsetX, offsetY));
        if (!alive()) return false;
        await scope.sleep(160);
        press();
        await scope.sleep(140);
        return alive();
      };
      const type = async (input: HTMLInputElement, text: string) => {
        if (!(await click(input, 30))) return false;
        for (const character of text) {
          if (!alive()) return false;
          input.value += character;
          await scope.sleep(46 + Math.random() * 44);
        }
        return alive();
      };
      reset();
      place({ x: builder.clientWidth + 40, y: builder.clientHeight * 0.72 });
      cursor.classList.add("is-on");
      await scope.sleep(500);
      if (!alive()) return false;
      if (!(await click(useSample, 34, 9))) return false;
      setSample();
      await scope.sleep(950);
      if (!alive()) return false;
      if (!(await click(toExtract))) return false;
      go(2);
      runExtract();
      await scope.sleep(2750);
      if (!alive()) return false;
      if (!(await click(toDetails))) return false;
      go(3);
      await scope.sleep(420);
      if (!(await type(nameInput, "Avery Lin"))) return false;
      if (!(await type(emailInput, "avery.lin@example.com"))) return false;
      if (!(await type(matterInput, "Lease review"))) return false;
      await scope.sleep(280);
      if (!(await click(review))) return false;
      details.requestSubmit(review);
      await scope.sleep(1300);
      if (!alive()) return false;
      if (!(await click(sendButton))) return false;
      sendButton.click();
      // The send, then a hold on the access code.
      await scope.sleep(4500);
      if (!alive()) return false;
      cursor.classList.remove("is-on");
      await scope.sleep(450);
      return alive();
    },
  });
  // Any touch, key or input inside the builder hands it to the visitor.
  for (const type of ["pointerdown", "keydown", "focusin", "input", "dragenter"]) {
    scope.on(builder, type, () => autoplay.takeOver(), true);
  }

  go(1);
}
