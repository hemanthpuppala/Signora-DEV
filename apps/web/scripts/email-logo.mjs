// The Signora logo for emails, as an SVG: the finished frame of the site's animated logo (its
// letterforms, and the quill where it rests), from the same data the animation draws. Email
// clients cannot run the animation or show SVG reliably, so `make email-logo` rasterises this to
// public/email/signora-logo.png, the image every email's header shows.
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { QUILL, VANE, VIEW } from "../src/shared/ui/signature/logoArt.ts";
import { LOGO, SIG } from "../src/shared/ui/signature/penPaths.ts";

const INK = "#ffffff"; // the emails are white on black, as the console's header
const PAPER = "#000000";
// The feather in one colour, the middle of the site's gradient: the rasteriser (and some email
// clients) draw an SVG gradient black, and a black feather vanishes on the email's black.
const FEATHER = VANE[1];

// The quill's pose when the writing ends (logoSigning's nibAt at LOGO.end).
const frames = LOGO.nib.length / 5;
const position = Math.min(Math.max(LOGO.end * LOGO.fps, 0), frames - 1);
const i = Math.floor(position);
const j = Math.min(i + 1, frames - 1);
const mix = position - i;
const [x, y, tilt, lift, opacity] = [0, 1, 2, 3, 4].map(
  (k) => LOGO.nib[i * 5 + k] + (LOGO.nib[j * 5 + k] - LOGO.nib[i * 5 + k]) * mix,
);
const grow = 1 + 0.035 * lift;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}" width="${VIEW.w}" height="${VIEW.h}">
<path d="${SIG.path}" fill="${INK}"/>
${
  opacity > 0.001
    ? `<g opacity="${opacity.toFixed(3)}" transform="translate(${x} ${y - lift * 7}) rotate(${tilt}) scale(${grow}) translate(-18 -88)">
<path d="${QUILL.vane}" fill="${FEATHER}"/><path d="${QUILL.cuts}" fill="${PAPER}"/><path d="${QUILL.rachis}" fill="${PAPER}"/><path d="${QUILL.shaft}" fill="${INK}"/>
</g>`
    : ""
}
</svg>
`;

const out = resolve(dirname(fileURLToPath(import.meta.url)), "../public/email/signora-logo.svg");
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, svg);
console.log(`${out}: quill at (${x.toFixed(1)}, ${y.toFixed(1)}), opacity ${opacity.toFixed(2)}`);
