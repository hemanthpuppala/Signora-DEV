import type { FormEventHandler, ReactNode } from "react";

import { TopBar } from "./AppShell";
import styles from "./auth.module.css";
import { Eyebrow, Heading1 } from "./Typography";

export type AuthPanelProps = {
  eyebrow: string;
  heading: string;
  children: ReactNode;
  /** When set, the panel is a form (one decision per screen, prototype .auth). */
  onSubmit?: FormEventHandler<HTMLFormElement>;
};

/** Public auth screens (prototype 02-04): top bar plus one narrow centred column. */
export function AuthPanel({ eyebrow, heading, children, onSubmit }: AuthPanelProps) {
  const body = (
    <>
      <Eyebrow>{eyebrow}</Eyebrow>
      <Heading1>{heading}</Heading1>
      {children}
    </>
  );
  return (
    <>
      <TopBar />
      <main className={styles.wrap}>
        {onSubmit ? (
          <form className={styles.auth} onSubmit={onSubmit} noValidate>
            {body}
          </form>
        ) : (
          <div className={styles.auth}>{body}</div>
        )}
      </main>
    </>
  );
}
