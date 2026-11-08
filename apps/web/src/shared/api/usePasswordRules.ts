"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

/**
 * The server's password rule, stated up front as a hint (as Google, Microsoft and GitHub do).
 * The wording matches the server's own message; the server is the only enforcer.
 */
export function usePasswordRules() {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: Infinity,
  });
  const min = meta.data?.password_min_length;
  return { minLength: min, hint: min ? `Use ${min} or more characters.` : undefined };
}
