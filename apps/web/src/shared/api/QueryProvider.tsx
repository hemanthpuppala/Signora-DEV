"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { NetworkError } from "./errors";

const MAX_QUERY_RETRIES = 3;

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Topic 3.6: data changed while offline appears without a reload.
        refetchOnReconnect: true,
        refetchOnWindowFocus: true,
        staleTime: 15_000,
        // Retry reads only when no answer arrived; a definite API error is not retried.
        retry: (failureCount, error) => error instanceof NetworkError && failureCount < MAX_QUERY_RETRIES,
      },
    },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
