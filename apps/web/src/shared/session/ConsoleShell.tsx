"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { userMessage } from "@/shared/api/errors";
import { AppShell, Notice, TextButton, TopBar, type NavItem } from "@/shared/ui";

import { can, useSession, useSignOut, type Me, type PermissionName } from "./session";

type ConsoleShellProps = {
  /** The page needs this permission; without it the page shows "no access". */
  requires?: PermissionName;
  children: (me: Me) => ReactNode;
};

const NAV: readonly { href: string; label: string; requires?: PermissionName }[] = [
  { href: "/", label: "Home" },
  { href: "/people", label: "People", requires: "members.manage" },
  { href: "/settings", label: "Settings" },
];

const NO_ACCESS: Partial<Record<PermissionName, string>> = {
  "members.manage": "Only the owner can manage people.",
};
const NO_ACCESS_DEFAULT = "You don't have access to this page. Ask the owner if you need it.";

/**
 * Signed-in console: loads the session, sends signed-out visitors to /login (keeping the page to
 * return to), builds the navigation from permissions, and renders the page with the user.
 */
export function ConsoleShell({ requires, children }: ConsoleShellProps) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const signOut = useSignOut();

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
    (item) => ({ href: item.href, label: item.label, active: item.href === pathname }),
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
    <AppShell workspace={me.workspace.name} nav={nav} actions={actions}>
      {requires && !can(me, requires) ? (
        <Notice title="No access">{NO_ACCESS[requires] ?? NO_ACCESS_DEFAULT}</Notice>
      ) : (
        children(me)
      )}
    </AppShell>
  );
}
