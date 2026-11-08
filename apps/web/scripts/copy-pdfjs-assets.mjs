// Copies the pdf.js worker and its data files (fonts, character maps, colour profiles, image
// decoders) into public/pdfjs/<version>/, so the viewer loads them from Signora's own origin
// (CSP worker-src 'self'; Phase 4 LLD topic 5). The versioned path lets browsers cache them for
// good. Runs before `next dev` and `next build`; the folder is generated, never committed.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const packageDir = dirname(require.resolve("pdfjs-dist/package.json"));
const { version } = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const publicDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "pdfjs");
const target = join(publicDir, version);

if (!existsSync(join(target, "pdf.worker.min.mjs"))) {
  rmSync(publicDir, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  cpSync(join(packageDir, "build", "pdf.worker.min.mjs"), join(target, "pdf.worker.min.mjs"));
  for (const folder of ["cmaps", "standard_fonts", "iccs", "wasm"]) {
    cpSync(join(packageDir, folder), join(target, folder), { recursive: true });
  }
  console.log(`pdf.js ${version} assets copied to public/pdfjs/${version}`);
}
