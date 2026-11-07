"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

/** The server's password rule, for the form hint; the server is the only enforcer. */
export function usePasswordRules() {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: Infinity,
  });
  const min = meta.data?.password_min_length;
  return {
    minLength: min,
    hint: min ? `At least ${min} characters. A passphrase works well.` : "Choose a long passphrase.",
  };
}
