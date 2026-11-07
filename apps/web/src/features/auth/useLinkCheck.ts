"use client";

import { useQuery } from "@tanstack/react-query";

import { useFragmentToken } from "@/shared/lib/useFragmentToken";

/** Reads the link's token and checks it once with ``verify``; a dead link is an answer. */
export function useLinkCheck<T>(name: string, verify: (token: string) => Promise<T>) {
  const token = useFragmentToken();
  const check = useQuery({
    queryKey: ["link", name, token],
    queryFn: () => verify(token as string),
    enabled: typeof token === "string",
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  return { token, check };
}
