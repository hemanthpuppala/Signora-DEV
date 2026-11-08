"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

/**
 * The server's password rule, stated up front as a hint (as Google, Microsoft and GitHub do).
 * Both the length and the wording come from the server, which is the only enforcer.
 */
export function usePasswordRules() {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: Infinity,
  });
  return { minLength: meta.data?.password_min_length, hint: meta.data?.password_rule };
}
