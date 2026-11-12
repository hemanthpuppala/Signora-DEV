// The Signora logo for emails, as an SVG: the finished frame of the site's animated logo (its
// letterforms, and the quill where it rests), from the same data the animation draws. Email
// clients cannot run the animation or show SVG reliably, so `make email-logo` rasterises this to
// public/email/signora-logo.png, the image every email's header shows.
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { QUILL, VANE, VIEW } from "../src/shared/ui/signature/logoArt.ts";
import { LOGO, SIG } from "../src/shared/ui/signature/penPaths.ts";

// Two inks: white for the emails' black page, black for an email app that repaints it light.
// The feather in one colour (the rasteriser draws an SVG gradient black): the middle of the site's
// gradient on black, its darkest stop on white.
const INKS = [
  { name: "signora-logo", ink: "#ffffff", paper: "#000000", feather: VANE[1] },
  { name: "signora-logo-black", ink: "#111111", paper: "#ffffff", feather: VANE[2] },
];

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

function logo({ ink, paper, feather }) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}" width="${VIEW.w}" height="${VIEW.h}">
<path d="${SIG.path}" fill="${ink}"/>
${
  opacity > 0.001
    ? `<g opacity="${opacity.toFixed(3)}" transform="translate(${x} ${y - lift * 7}) rotate(${tilt}) scale(${grow}) translate(-18 -88)">
<path d="${QUILL.vane}" fill="${feather}"/><path d="${QUILL.cuts}" fill="${paper}"/><path d="${QUILL.rachis}" fill="${paper}"/><path d="${QUILL.shaft}" fill="${ink}"/>
</g>`
    : ""
}
</svg>
`;
}

const dir = resolve(dirname(fileURLToPath(import.meta.url)), "../public/email");
mkdirSync(dir, { recursive: true });
for (const version of INKS) {
  writeFileSync(resolve(dir, `${version.name}.svg`), logo(version));
}
console.log(`${dir}: ${INKS.map((v) => v.name).join(", ")}; quill at (${x.toFixed(1)}, ${y.toFixed(1)})`);
