import { createAutoplay } from "./autoplay";
import { context2d, cssVar, q, qa, setBusy, sizeCanvas, type Surface } from "./dom";
import { SIG } from "./penPaths";
import type { Scope } from "./scope";

const TAU = Math.PI * 2;
const DEFAULT_DOCUMENT = "Engagement Letter";
const VIEWS = ["code", "sign", "done"] as const;
type ViewName = (typeof VIEWS)[number];

/** An envelope built in §04 that the phone should open: its code, the client and the document. */
export type PhoneEnvelope = { code: string; clientName: string; documentName: string };

export type PhoneSigning = {
  /** Shows the envelope sent from the builder (its code is then the only one accepted), or the sample. */
  setEnvelope(envelope: PhoneEnvelope | null): void;
  /** Puts the cursor in the first digit of the access code. */
  focusCode(): void;
};

/**
 * §05: the client's phone. Two steps: enter the six-digit access code, then review and sign on a
 * pad whose line width follows the pen's speed. The demo types a code, opens the document and
 * writes the Signora signature along its recorded pen path; any touch hands the phone over.
 */
export function mountPhoneSigning(root: HTMLElement, scope: Scope, reduced: boolean): PhoneSigning {
  const phone = q(root, ".phone");
  const views: Record<ViewName, HTMLElement> = {
    code: q(root, "#v-code"),
    sign: q(root, "#v-sign"),
    done: q(root, "#v-done"),
  };
  const codeForm = views.code as HTMLFormElement;
  const digitGroup = q(root, "#digits");
  const digits = qa<HTMLInputElement>(digitGroup, "input");
  const openButton = q<HTMLButtonElement>(root, "#open-doc");
  const codeError = q(root, "#code-err");
  const lock = q(root, "#lockline");
  const pad = q(root, "#pad");
  const padCanvas = q<HTMLCanvasElement>(root, "#pad-canvas");
  const signButton = q<HTMLButtonElement>(root, "#sign-btn");
  const hint = q(root, "#phone-hint");
  const wait = (ms: number) => scope.sleep(reduced ? 0 : ms);

  let envelope: PhoneEnvelope | null = null;
  let surface: Surface | null = null;
  let inkLength = 0;

  // ── Views ──
  function show(name: ViewName): void {
    const index = VIEWS.indexOf(name);
    VIEWS.forEach((key, i) => {
      const view = views[key];
      view.classList.toggle("is-on", i === index);
      view.classList.toggle("is-past", i < index);
      view.inert = i !== index;
    });
    // The pad is measured once its view has a size.
    if (name === "sign") scope.timeout(setupPad, 60);
  }

  // ── Step 1: the access code ──
  const codeValue = () => digits.map((digit) => digit.value).join("");
  function syncCode(): void {
    for (const digit of digits) digit.classList.toggle("has", digit.value !== "");
    openButton.disabled = codeValue().length !== digits.length;
  }
  /** Spreads typed or pasted digits over the boxes, starting at `from`. */
  function fill(text: string, from: number): void {
    [...text].slice(0, digits.length - from).forEach((character, k) => {
      const box = digits[from + k];
      if (box) box.value = character;
    });
    digits[Math.min(digits.length - 1, from + text.length)]?.focus();
    syncCode();
  }
  digits.forEach((digit, i) => {
    const previous = digits[i - 1];
    const next = digits[i + 1];
    scope.on(digit, "input", () => {
      const value = digit.value.replace(/\D/g, "");
      if (value.length > 1) {
        fill(value, i);
        return;
      }
      digit.value = value;
      codeError.textContent = "";
      digitGroup.classList.remove("is-wrong");
      if (value) next?.focus();
      syncCode();
    });
    scope.on<KeyboardEvent>(digit, "keydown", (event) => {
      if (event.key === "Backspace" && !digit.value && previous) {
        previous.focus();
        previous.value = "";
        syncCode();
        event.preventDefault();
      }
      if (event.key === "ArrowLeft") previous?.focus();
      if (event.key === "ArrowRight") next?.focus();
    });
    scope.on<ClipboardEvent>(digit, "paste", (event) => {
      const pasted = (event.clipboardData?.getData("text") ?? "").replace(/\D/g, "");
      if (pasted) {
        event.preventDefault();
        fill(pasted, i);
      }
    });
    scope.on(digit, "focus", () => digit.select());
  });
  scope.on<SubmitEvent>(codeForm, "submit", async (event) => {
    event.preventDefault();
    const code = codeValue();
    if (code.length !== digits.length) return;
    if (envelope && code !== envelope.code) {
      codeError.textContent = "That code does not match this envelope.";
      digitGroup.classList.remove("is-wrong");
      void digitGroup.offsetWidth; // restart the shake
      digitGroup.classList.add("is-wrong");
      return;
    }
    const restore = setBusy(openButton, "Checking");
    await wait(700);
    lock.classList.add("is-unlocked");
    await wait(420);
    restore();
    show("sign");
  });

  // ── Step 2: the signature pad ──
  function setupPad(): Surface {
    surface = sizeCanvas(padCanvas);
    const { ctx } = surface;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.fillStyle = ctx.strokeStyle = cssVar(pad, "--ink");
    inkLength = 0;
    pad.classList.remove("has-ink");
    signButton.disabled = true;
    return surface;
  }
  function clearPad(): void {
    surface?.ctx.clearRect(0, 0, surface.w, surface.h);
    inkLength = 0;
    pad.classList.remove("has-ink");
    signButton.disabled = true;
  }
  type Sample = { x: number; y: number; t: number };
  let drawing = false;
  let last: Sample = { x: 0, y: 0, t: 0 };
  let lastWidth = 2;
  const sample = (event: PointerEvent): Sample => {
    const box = padCanvas.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top, t: performance.now() };
  };
  scope.on<PointerEvent>(padCanvas, "pointerdown", (event) => {
    const { ctx } = surface?.w ? surface : setupPad();
    drawing = true;
    padCanvas.setPointerCapture(event.pointerId);
    last = sample(event);
    lastWidth = 2.2;
    ctx.beginPath();
    ctx.arc(last.x, last.y, 1.1, 0, TAU);
    ctx.fill();
  });
  scope.on<PointerEvent>(padCanvas, "pointermove", (event) => {
    if (!drawing || !surface) return;
    const { ctx } = surface;
    for (const each of event.getCoalescedEvents?.() ?? [event]) {
      const point = sample(each);
      const distance = Math.hypot(point.x - last.x, point.y - last.y);
      if (distance < 0.8) continue;
      // A faster pen leaves a thinner line, eased so the width changes smoothly.
      const speed = distance / Math.max(1, point.t - last.t);
      const width = lastWidth + (Math.max(0.9, Math.min(3.2, 3.4 - speed * 1.6)) - lastWidth) * 0.35;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.quadraticCurveTo(last.x, last.y, (last.x + point.x) / 2, (last.y + point.y) / 2);
      ctx.lineTo(point.x, point.y);
      ctx.stroke();
      inkLength += distance;
      last = point;
      lastWidth = width;
    }
    if (inkLength > 40) {
      pad.classList.add("has-ink");
      signButton.disabled = false;
    }
  });
  for (const type of ["pointerup", "pointercancel"]) {
    scope.on(padCanvas, type, () => {
      drawing = false;
    });
  }
  scope.on(q(root, "#pad-clear"), "click", clearPad);
  scope.on(signButton, "click", async () => {
    const restore = setBusy(signButton, "Signing");
    await wait(700);
    restore();
    const time = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    q(root, "#done-time").textContent = `Signed ${time}${envelope ? ` by ${envelope.clientName}` : ""}`;
    show("done");
    if (!autoplay.isOn()) scope.timeout(() => q(root, "#sign-reset").focus({ preventScroll: true }), 400);
  });

  function reset(): void {
    for (const digit of digits) digit.value = "";
    syncCode();
    codeError.textContent = "";
    lock.classList.remove("is-unlocked");
    clearPad();
    show("code");
  }
  scope.on(q(root, "#sign-reset"), "click", reset);

  // ── The demo ──
  const glyph = new Path2D(SIG.path);
  const inkCanvas = document.createElement("canvas");
  const tap = (button: HTMLElement) => {
    button.classList.add("is-tap");
    scope.timeout(() => button.classList.remove("is-tap"), 170);
  };
  /** Writes the signature on the pad along the recorded pen path; resolves false if interrupted. */
  function playSignature(alive: () => boolean): Promise<boolean> {
    return new Promise((resolve) => {
      const { ctx, w, h } = setupPad();
      const dpr = padCanvas.width / w;
      const [left, top, right, bottom] = SIG.bb;
      const boxWidth = right - left;
      const boxHeight = bottom - top;
      const scale = Math.min((w - 28) / boxWidth, (h - 26) / boxHeight);
      const offsetX = (w - boxWidth * scale) / 2 - left * scale;
      const offsetY = (h - boxHeight * scale) / 2 - top * scale - 5;
      const toPad = () => [dpr * scale, 0, 0, dpr * scale, dpr * offsetX, dpr * offsetY] as const;
      const color = cssVar(pad, "--ink");
      const minRadius = 0.75 / scale;
      inkCanvas.width = padCanvas.width;
      inkCanvas.height = padCanvas.height;
      const ink = context2d(inkCanvas);
      ink.setTransform(...toPad());
      ink.fillStyle = color;
      const dots = SIG.ink;
      const count = dots.length / 4;
      const started = performance.now();
      let i = 0;
      const tick = (now: number) => {
        if (!alive()) {
          resolve(false);
          return;
        }
        const t = (now - started) / 1000;
        ink.beginPath();
        while (i < count && dots[i * 4 + 3]! <= t) {
          const x = dots[i * 4]!;
          const y = dots[i * 4 + 1]!;
          const radius = Math.max(minRadius, dots[i * 4 + 2]! * 1.12 + 0.12);
          ink.moveTo(x + radius, y);
          ink.arc(x, y, radius, 0, TAU);
          i++;
        }
        ink.fill();
        // The ink so far, clipped to the letterforms; once written, the full letterforms fade in.
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, padCanvas.width, padCanvas.height);
        ctx.setTransform(...toPad());
        ctx.clip(glyph);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(inkCanvas, 0, 0);
        const dry = Math.max(0, Math.min(1, (t - SIG.end) / 0.6));
        if (dry > 0) {
          ctx.setTransform(...toPad());
          ctx.globalAlpha = dry * dry * (3 - 2 * dry);
          ctx.fillStyle = color;
          ctx.fill(glyph);
        }
        ctx.restore();
        if (i > 0) pad.classList.add("has-ink");
        if (dry >= 1) {
          inkLength = Number.POSITIVE_INFINITY;
          signButton.disabled = false;
          resolve(true);
          return;
        }
        scope.frame(tick);
      };
      scope.frame(tick);
    });
  }
  const autoplay = createAutoplay({
    scope,
    reduced,
    watch: phone,
    resume: q<HTMLButtonElement>(root, "#phone-resume"),
    onStart: () => {
      hint.hidden = false;
    },
    play: async (alive) => {
      reset();
      await scope.sleep(1100);
      if (!alive()) return false;
      const code = envelope?.code ?? String(Math.floor(100000 + Math.random() * 900000));
      for (const [k, digit] of digits.entries()) {
        digit.value = code[k] ?? "";
        syncCode();
        await scope.sleep(180);
        if (!alive()) return false;
      }
      await scope.sleep(450);
      if (!alive()) return false;
      tap(openButton);
      codeForm.requestSubmit();
      await scope.sleep(1900);
      if (!alive()) return false;
      if (!(await playSignature(alive))) return false;
      await scope.sleep(650);
      if (!alive()) return false;
      tap(signButton);
      signButton.click();
      await scope.sleep(4500);
      return alive();
    },
  });
  for (const type of ["pointerdown", "pointermove", "keydown", "focusin", "input"]) {
    scope.on<PointerEvent>(
      phone,
      type,
      (event) => {
        // Moving over the phone is not taking it over; dragging on it is.
        if (type === "pointermove" && !event.buttons) return;
        autoplay.takeOver();
      },
      true,
    );
  }

  VIEWS.forEach((key, i) => {
    views[key].inert = i !== 0;
  });

  return {
    setEnvelope(next) {
      envelope = next;
      const documentName = next?.documentName ?? DEFAULT_DOCUMENT;
      q(root, "#v-doc-1").textContent = documentName;
      q(root, "#v-doc-2").textContent = documentName;
      q(root, "#v-from").textContent = next ? `For ${next.clientName}` : "Sent by [Your firm]";
      q(root, "#v-signer").textContent = next ? `${next.clientName} · signature` : "Client signature";
      hint.textContent = next
        ? "This envelope opens with the code from §04"
        : "Use the code from §04, or any six digits";
      reset();
    },
    focusCode() {
      digits[0]?.focus({ preventScroll: true });
    },
  };
}
