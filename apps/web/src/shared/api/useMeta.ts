"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

/**
 * The server's public settings (`GET /api/v1/meta`): limits, rules and the build. The single query
 * every reader shares, so they all see one cache entry. The values change only with a deploy.
 */
export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: Infinity,
  });
}
