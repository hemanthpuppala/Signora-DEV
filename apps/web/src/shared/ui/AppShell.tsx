import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import styles from "./shell.module.css";

export type NavItem = { href: string; label: string; active?: boolean };

export type AppShellProps = {
  /** Workspace name shown next to the logo (signed-in console). */
  workspace?: string;
  nav?: readonly NavItem[];
  /** Controls after the navigation (e.g. "Log out"). */
  actions?: ReactNode;
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

/** Logged-in console layout: top bar plus a centred main column. */
export function AppShell({ workspace, nav, actions, children }: AppShellProps) {
  return (
    <>
      <TopBar
        {...(workspace ? { workspace } : {})}
        {...(nav ? { nav } : {})}
        {...(actions ? { actions } : {})}
      />
      <div className={styles.wrap}>
        <main className={styles.main}>{children}</main>
      </div>
    </>
  );
}
