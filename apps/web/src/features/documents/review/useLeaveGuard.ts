"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Leaving with unsaved changes asks first (Phase 6 §1.7): closing or reloading the tab gets the
 * browser's own prompt; a link inside the app is held and our dialog asks ("Discard 3 unsaved
 * changes?"). The browser's back button inside the app is not caught: the App Router has no
 * cancellable navigation event, and the tab prompt covers leaving the site.
 */
export function useLeaveGuard(changes: number) {
  const router = useRouter();
  const [leaving, setLeaving] = useState<string | null>(null);

  useEffect(() => {
    if (changes === 0) return undefined;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = ""; // older browsers need it set
    };
    // Captured on the document, before the link's own handler, so the app never navigates.
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]");
      if (!(link instanceof HTMLAnchorElement) || link.target === "_blank" || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return; // leaving the site: the tab prompt asks
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      event.preventDefault();
      event.stopPropagation();
      setLeaving(`${url.pathname}${url.search}${url.hash}`);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [changes]);

  return {
    leaving,
    stay: () => setLeaving(null),
    leave: () => {
      const to = leaving;
      setLeaving(null);
      if (to) router.push(to);
    },
  };
}
