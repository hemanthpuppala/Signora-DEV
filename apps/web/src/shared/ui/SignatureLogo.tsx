"use client";

import { useEffect, useRef } from "react";

import { Scope } from "@/shared/lib/scope";

import { mountLogoSigning } from "./signature/logoSigning";

/**
 * The Signora logo, signed by a quill: it writes itself, rests, and writes itself again. It is
 * decoration (hidden from assistive technology); the link or heading around it carries the name.
 * Size it with `className`; its ink is the CSS `color`.
 */
export function SignatureLogo({ className }: { className?: string | undefined }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!canvas.current) return;
    const scope = new Scope();
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    mountLogoSigning(canvas.current, scope, reduced);
    return () => scope.dispose();
  }, []);
  return <canvas ref={canvas} className={className} aria-hidden="true" />;
}
