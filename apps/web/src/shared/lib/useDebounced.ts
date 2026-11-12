import { useEffect, useState } from "react";

/** A value that settles: the latest one once it has not changed for ``ms`` (a search as typed). */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** How long a search box waits for typing to stop before it asks the server. */
export const SEARCH_SETTLE_MS = 300;
