"use client";

import { useEffect } from "react";

import { latchWheel } from "@/shared/lib/scrollLatch";

/** Puts the console's scroll rule in place while it is shown (``latchWheel``); draws nothing. */
export function ScrollLatch() {
  useEffect(() => latchWheel(), []);
  return null;
}
