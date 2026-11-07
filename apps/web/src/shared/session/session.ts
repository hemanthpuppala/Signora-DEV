"use client";

import type { components } from "@signora/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";

export type Me = components["schemas"]["MeResponse"];
export type PermissionName = "members.manage" | "members.directory" | "roles.manage" | "workspace.rename";

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
      queryClient.clear();
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

/** Only same-site paths are followed after log-in (no open redirect). */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}
