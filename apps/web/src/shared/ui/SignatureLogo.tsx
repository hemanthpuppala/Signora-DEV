"use client";

import { useEffect, useRef } from "react";

import { Scope } from "@/shared/lib/scope";

import { mountLogoSigning } from "./signature/logoSigning";

type SignatureLogoProps = {
  className?: string | undefined;
  /** Sign again after resting this many seconds. Without it the logo signs once and stays. */
  repeatSeconds?: number;
};

/**
 * The Signora logo, signed by a quill: it writes itself once, then rests. It is decoration (hidden
 * from assistive technology); the link or heading around it carries the name. Size it with
 * `className`; its ink is the CSS `color`.
 */
export function SignatureLogo({ className, repeatSeconds }: SignatureLogoProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!canvas.current) return;
    const scope = new Scope();
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    mountLogoSigning(canvas.current, scope, reduced, repeatSeconds ? repeatSeconds * 1000 : undefined);
    return () => scope.dispose();
  }, [repeatSeconds]);
  return <canvas ref={canvas} className={className} aria-hidden="true" />;
}
