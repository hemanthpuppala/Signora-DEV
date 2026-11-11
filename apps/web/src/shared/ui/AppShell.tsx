import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/shared/lib/cx";

import { ScrollLatch } from "./ScrollLatch";
import { SignatureLogo } from "./SignatureLogo";
import styles from "./shell.module.css";

export type NavItem = { href: string; label: string; active?: boolean };

export type AppShellProps = {
  /** Where the logo links: the landing page by default, the console's home when signed in. */
  home?: string;
  /** Workspace name shown next to the logo (signed-in console). */
  workspace?: string;
  nav?: readonly NavItem[];
  /** Controls after the navigation (e.g. "Log out"). */
  actions?: ReactNode;
  /** "content": a centred column (most pages); "full": the whole window, for workspace pages. */
  width?: "content" | "full";
  children: ReactNode;
};

export function TopBar({ home = "/", workspace, nav = [], actions }: Omit<AppShellProps, "children">) {
  return (
    <header className={styles.topbar}>
      <div className={cx(styles.topbarInner, styles.wrap)}>
        <div className={styles.brand}>
          <Link href={home} className={styles.logo} aria-label="Signora">
            <SignatureLogo className={styles.logoMark} />
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
export function AppShell({ home, workspace, nav, actions, width = "content", children }: AppShellProps) {
  return (
    <>
      <ScrollLatch />
      <TopBar
        {...(home ? { home } : {})}
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
