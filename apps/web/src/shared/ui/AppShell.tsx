import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import { ScrollLatch } from "./ScrollLatch";
import styles from "./shell.module.css";

export type NavItem = { href: string; label: string; active?: boolean };

export type AppShellProps = {
  /** Workspace name shown next to the logo (signed-in console). */
  workspace?: string;
  nav?: readonly NavItem[];
  /** Controls after the navigation (e.g. "Log out"). */
  actions?: ReactNode;
  /** "content": a centred column (most pages); "full": the whole window, for workspace pages. */
  width?: "content" | "full";
  children: ReactNode;
};

export function TopBar({ workspace, nav = [], actions }: Omit<AppShellProps, "children">) {
  return (
    <header className={styles.topbar}>
      <div className={cx(styles.topbarInner, styles.wrap)}>
        <div className={styles.brand}>
          <Link href="/" className={styles.logo}>
            SIGNORA
          </Link>
          {workspace ? <span className={styles.workspace}>{workspace}</span> : null}
        </div>
        {nav.length || actions ? (
          <nav className={styles.nav} aria-label="Console">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cx(styles.navLink, item.active && styles.navActive)}
                aria-current={item.active ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
            {actions}
          </nav>
        ) : null}
      </div>
    </header>
  );
}

/** Logged-in console layout: top bar plus a centred main column (or the full width). */
export function AppShell({ workspace, nav, actions, width = "content", children }: AppShellProps) {
  return (
    <>
      <ScrollLatch />
      <TopBar
        {...(workspace ? { workspace } : {})}
        {...(nav ? { nav } : {})}
        {...(actions ? { actions } : {})}
      />
      <div className={styles.wrap}>
        <main className={cx(styles.main, width === "full" && styles.full)}>{children}</main>
      </div>
    </>
  );
}
