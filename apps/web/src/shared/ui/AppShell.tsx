import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import { ScrollLatch } from "./ScrollLatch";
import styles from "./shell.module.css";

/** ``count``: things waiting there for the person (a dot and the number), shown above zero. */
export type NavItem = { href: string; label: string; active?: boolean; count?: number };

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

export type TopBarProps = Omit<AppShellProps, "children" | "width"> & {
  /** Where the logo leads; ``null``: nowhere (a signer has no console to go back to). */
  home?: string | null;
  /** On the right, instead of a navigation (a signer's screen: its name and next step). */
  aside?: ReactNode;
};

export function TopBar({ workspace, nav = [], actions, home = "/", aside }: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <div className={cx(styles.topbarInner, styles.wrap)}>
        <div className={styles.brand}>
          {home === null ? (
            <span className={styles.logo}>SIGNORA</span>
          ) : (
            <Link href={home} className={styles.logo}>
              SIGNORA
            </Link>
          )}
          {workspace ? <span className={styles.workspace}>{workspace}</span> : null}
        </div>
        {aside ? <div className={styles.aside}>{aside}</div> : null}
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
                {item.count ? (
                  <span className={styles.navCount} aria-label={`, ${item.count} waiting`}>
                    {` · ${item.count}`}
                  </span>
                ) : null}
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
