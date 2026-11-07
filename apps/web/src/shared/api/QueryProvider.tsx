"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { NetworkError } from "./errors";

/**
 * Retry a read only when no answer arrived, and keep retrying until one does, so the page recovers
 * by itself when the API returns. The delay is TanStack's default backoff (1 s, 2 s, 4 s … max 30 s,
 * the same schedule as ``useIdempotentAction``), and TanStack pauses retries while the tab is hidden
 * or offline. A definite API error is not retried.
 */
export function shouldRetryRead(_failureCount: number, error: unknown): boolean {
  return error instanceof NetworkError;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Topic 3.6: data changed while offline appears without a reload.
        refetchOnReconnect: true,
        refetchOnWindowFocus: true,
        staleTime: 15_000,
        retry: shouldRetryRead,
      },
    },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
