import { Scope } from "@/shared/lib/scope";

import { mountEnvelopeBuilder } from "./envelopeBuilder";
import { mountExtractionClip } from "./extractionClip";
import { mountFirmLanes } from "./firmLanes";
import { mountHeroFlux } from "./heroFlux";
import { createToast, mountPageChrome } from "./pageChrome";
import { mountPhoneSigning } from "./phoneSigning";
import { mountTemplatesFolder } from "./templatesFolder";

/**
 * Brings the landing page's server-rendered markup to life: the header, the hero and each
 * section's demo. Returns the call that stops everything again.
 */
export function mountLanding(root: HTMLElement): () => void {
  const scope = new Scope();
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The page is complete without its demos, so one that fails to start is reported and left
  // still; it does not take the page, or the other demos, down with it.
  const start = (name: string, mount: () => void) => {
    try {
      mount();
    } catch (error) {
      console.error(`Landing page: ${name} did not start`, error);
    }
  };
  start("the header and page motion", () => mountPageChrome(root, scope, reduced));
  start("the hero", () => mountHeroFlux(root, scope, reduced));
  start("the templates folder", () => mountTemplatesFolder(root, scope, reduced));
  start("the extraction clip", () => mountExtractionClip(root, scope, reduced));
  start("the builder and the phone", () => {
    const phone = mountPhoneSigning(root, scope, reduced);
    mountEnvelopeBuilder(root, scope, reduced, phone, createToast(root, scope));
  });
  start("the record lanes", () => mountFirmLanes(root, scope, reduced));
  return () => scope.dispose();
}
