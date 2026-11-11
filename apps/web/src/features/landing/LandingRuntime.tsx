"use client";

import { useEffect, useRef } from "react";

import { mountLanding } from "./runtime";

/**
 * Starts the landing page's animations and demos once the page is in the browser, and stops them
 * when the visitor leaves it. The page reads in full without this (it is server-rendered markup).
 */
export function LandingRuntime() {
  const marker = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const root = marker.current?.closest<HTMLElement>(".signora-landing");
    return root ? mountLanding(root) : undefined;
  }, []);
  return <span ref={marker} hidden />;
}
