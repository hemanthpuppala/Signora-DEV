"use client";

import { useEffect, useState } from "react";

/**
 * The one-time token from the URL fragment (``/invite#<token>``). Fragments never reach a server,
 * so the token stays out of every log; once read it is removed from the address bar and history.
 * ``undefined`` until read on the client, ``null`` when the link has no token.
 */
export function useFragmentToken(): string | null | undefined {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const value = window.location.hash.slice(1);
    if (value) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    // Reading browser state after mount is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(value || null);
  }, []);
  return token;
}
