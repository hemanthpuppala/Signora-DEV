"use client";

import type { components } from "@signora/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";

export type Me = components["schemas"]["MeResponse"];
/** Generated from the API's Permission enum, so a renamed permission fails the build. */
export type PermissionName = components["schemas"]["Permission"];

export const SESSION_QUERY_KEY = ["me"] as const;

/** The signed-in user, or ``null`` when signed out (a 401 is an answer, not an error). */
export async function fetchSession(): Promise<Me | null> {
  try {
    return await unwrap(api.GET("/api/v1/me"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function useSession() {
  return useQuery({ queryKey: SESSION_QUERY_KEY, queryFn: fetchSession, staleTime: 60_000 });
}

export function can(me: Me | null | undefined, permission: PermissionName): boolean {
  return Boolean(me?.permissions.includes(permission));
}

/** Log in and make the new session the cached one. */
export async function logIn(email: string, password: string): Promise<Me> {
  return unwrap(api.POST("/api/v1/auth/login", { body: { email, password } }));
}

export function useLogIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => logIn(email, password),
    onSuccess: (me) => {
      // Drop cached data nothing is showing (it may belong to a previous user). Queries on screen
      // stay as they are: refetching them would, e.g., re-check a link that was just used up.
      queryClient.removeQueries({ type: "inactive" });
      queryClient.setQueryData(SESSION_QUERY_KEY, me);
    },
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(SESSION_QUERY_KEY, null);
    },
  });
}

/**
 * Where to go after log-in: only a path on this site (no open redirect). The value is resolved the
 * way the browser will resolve it (which drops tabs and newlines and treats "\\" like "/"), and kept
 * only when the result stays on this origin; anything else goes home.
 */
export function safeNext(value: string | null | undefined, origin?: string): string {
  if (!value || !value.startsWith("/")) return "/";
  const here = origin ?? window.location.origin;
  try {
    const url = new URL(value, here);
    return url.origin === here ? `${url.pathname}${url.search}${url.hash}` : "/";
  } catch {
    return "/";
  }
}
