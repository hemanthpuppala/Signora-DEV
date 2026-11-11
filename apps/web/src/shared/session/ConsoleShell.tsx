"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { userMessage } from "@/shared/api/errors";
import { api, unwrap } from "@/shared/api/client";
import { AppShell, Notice, TextButton, TopBar, type AppShellProps, type NavItem } from "@/shared/ui";

import { can, useSession, useSignOut, type Me, type PermissionName } from "./session";

type ConsoleShellProps = {
  /** The page needs this permission; without it the page shows "no access". */
  requires?: PermissionName;
  /** "full" for a workspace page that uses the whole window (the document page). */
  width?: AppShellProps["width"];
  children: (me: Me) => ReactNode;
};

const NAV: readonly {
  href: string;
  label: string;
  requires?: PermissionName;
  matches: (path: string) => boolean;
}[] = [
  { href: "/", label: "Departments", matches: (p) => p === "/" || p.startsWith("/departments") },
  { href: "/countersign", label: "To countersign", matches: (p) => p.startsWith("/countersign") },
  { href: "/people", label: "People", requires: "members.manage", matches: (p) => p === "/people" },
  { href: "/settings", label: "Settings", matches: (p) => p === "/settings" },
];

const NO_ACCESS: Partial<Record<PermissionName, string>> = {
  "members.manage": "Only the owner can manage people.",
  "departments.create": "Only owners and editors can create departments.",
  "departments.manage": "Only owners and editors can change departments.",
};
const NO_ACCESS_DEFAULT = "You don't have access to this page. Ask the owner if you need it.";

/**
 * Signed-in console: loads the session, sends signed-out visitors to /login (keeping the page to
 * return to), builds the navigation from permissions, and renders the page with the user.
 */
/**
 * How many envelopes wait for the signed-in user's countersignature (Phase 8 §7.2): read with the
 * navigation and again when the page regains focus.
 */
function useCountersignCount(signedIn: boolean): number {
  const count = useQuery({
    queryKey: ["me", "countersign", "count"],
    queryFn: () => unwrap(api.GET("/api/v1/me/countersign/count")),
    enabled: signedIn,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
  return count.data?.count ?? 0;
}

export function ConsoleShell({ requires, width = "content", children }: ConsoleShellProps) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const signOut = useSignOut();
  const waiting = useCountersignCount(session.isSuccess && session.data !== null);

  const signedOut = session.isSuccess && session.data === null;
  useEffect(() => {
    if (signedOut) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [signedOut, router, pathname]);

  if (session.isError) {
    return (
      <>
        <TopBar />
        <main style={{ padding: "48px var(--gutter)" }}>
          <Notice tone="warning" title="Signora is unreachable">
            {userMessage(session.error)}
          </Notice>
        </main>
      </>
    );
  }
  const me = session.data;
  if (!me) return <TopBar />; // loading, or about to redirect

  const nav: NavItem[] = NAV.filter((item) => !item.requires || can(me, item.requires)).map(
    (item) => ({
      href: item.href,
      label: item.label,
      active: item.matches(pathname),
      ...(item.href === "/countersign" ? { count: waiting } : {}),
    }),
  );
  const actions = (
    <TextButton
      onClick={() => signOut.mutate(undefined, { onSettled: () => router.replace("/login") })}
      disabled={signOut.isPending}
    >
      Log out
    </TextButton>
  );
  return (
    <AppShell workspace={me.workspace.name} nav={nav} actions={actions} width={width}>
      {requires && !can(me, requires) ? (
        <Notice title="No access">{NO_ACCESS[requires] ?? NO_ACCESS_DEFAULT}</Notice>
      ) : (
        children(me)
      )}
    </AppShell>
  );
}
