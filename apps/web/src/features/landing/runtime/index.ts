import { mountEnvelopeBuilder } from "./envelopeBuilder";
import { mountExtractionClip } from "./extractionClip";
import { mountFirmLanes } from "./firmLanes";
import { mountHeroFlux } from "./heroFlux";
import { mountLogoSigning } from "./logoSigning";
import { createToast, mountPageChrome } from "./pageChrome";
import { mountPhoneSigning } from "./phoneSigning";
import { Scope } from "./scope";
import { mountTemplatesFolder } from "./templatesFolder";

/**
 * Brings the landing page's server-rendered markup to life: the header, the hero and each
 * section's demo. Returns the call that stops everything again.
 */
export function mountLanding(root: HTMLElement): () => void {
  const scope = new Scope();
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  mountPageChrome(root, scope, reduced);
  mountLogoSigning(root, scope, reduced);
  mountHeroFlux(root, scope, reduced);
  mountTemplatesFolder(root, scope, reduced);
  mountExtractionClip(root, scope, reduced);
  const phone = mountPhoneSigning(root, scope, reduced);
  mountEnvelopeBuilder(root, scope, reduced, phone, createToast(root, scope));
  mountFirmLanes(root, scope, reduced);
  return () => scope.dispose();
}
