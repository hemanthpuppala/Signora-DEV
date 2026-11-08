"use client";

import { useEffect, useState } from "react";

// The token taken from the address bar, kept in memory for the rest of this page load (never in
// browser storage). Effects can run more than once (React strict mode in development, a remount),
// and after the first run the fragment is already gone from the address bar.
let captured: { path: string; token: string } | null = null;

function readToken(): string | null {
  const path = window.location.pathname;
  const fromUrl = window.location.hash.slice(1);
  if (fromUrl) {
    captured = { path, token: fromUrl };
    window.history.replaceState(null, "", path + window.location.search);
    return fromUrl;
  }
  return captured?.path === path ? captured.token : null;
}

/**
 * The one-time token from the URL fragment (``/invite#<token>``). Fragments never reach a server,
 * so the token stays out of every log; once read it is removed from the address bar and history.
 * ``undefined`` until read on the client, ``null`` when the link has no token.
 */
export function useFragmentToken(): string | null | undefined {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    // Reading browser state after mount is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(readToken());
  }, []);
  return token;
}

/** Tests only: forget the captured token between cases. */
export function resetCapturedTokenForTests(): void {
  captured = null;
}
