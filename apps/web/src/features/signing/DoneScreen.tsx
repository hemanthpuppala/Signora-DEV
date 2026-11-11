"use client";

import Link from "next/link";

import { AuthPanel, BodyText, FactList, LinkButton, SmallText } from "@/shared/ui";

import { completedUrl, copyUrl, useDone, type SignerState } from "./api";
import styles from "./signing.module.css";
import { SignerProblem } from "./SignerNotices";

const VERIFIED: Record<string, (email: string) => string> = {
  email_code: (email) => `Email code to ${email}`,
  email_link: (email) => `Email link to ${email}`,
  signora_sign_in: () => "Signora sign-in",
};

/** The time signed, in the person's own zone, to the second: "Nov 11, 2026 at 9:14:22 AM PST". */
export function signedAt(iso: string): string {
  const at = new Date(iso);
  const date = at.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  const time = at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
  return `${date} at ${time}`;
}

function nextLine(waiting: readonly string[], countersigning: string | null): string {
  const names = waiting.length > 1 ? `${waiting.slice(0, -1).join(", ")} and ${waiting.at(-1)}` : waiting[0];
  if (names && countersigning) return `Waiting for ${names} to sign, then ${countersigning} countersigns. You'll get the completed copy by email.`;
  if (names) return `Waiting for ${names} to sign. You'll get the completed copy by email.`;
  if (countersigning) return `Waiting for ${countersigning} to countersign. You'll get the completed copy by email.`;
  return "Done. You'll get the completed copy by email shortly.";
}

/** The done screen (Phase 8 §9.1): thanks, when, how they were verified, a copy, what is next. */
export function DoneScreen({ state }: { state: SignerState }) {
  const done = useDone(state.recipient_id);
  if (done.isError) return <SignerProblem error={done.error} />;
  if (!done.data) return <AuthPanel eyebrow="Signed" heading="Signed.">{null}</AuthPanel>;
  const view = done.data;
  const first = state.name.split(" ")[0] ?? state.name;
  const countersigner = state.kind === "countersigner";
  const act = view.approved ? "Approved" : countersigner ? "Countersigned" : "Signed";
  const facts = (
    <FactList
      label="Your signing"
      facts={[
        { term: `${act} at`, value: signedAt(view.signed_at) },
        { term: "Verified by", value: (VERIFIED[view.verified_by] ?? VERIFIED.email_link)?.(state.email_masked) ?? "" },
      ]}
    />
  );
  const back = countersigner ? (
    <BodyText>
      <Link href="/countersign">Back to To countersign</Link>
    </BodyText>
  ) : null;

  if (view.completed && countersigner) {
    // Everyone has signed: the signed copy to keep, one primary action and two quiet ones.
    return (
      <AuthPanel eyebrow={`${state.company} · ${act}`} heading="Completed.">
        <BodyText>Everyone has signed {state.document_name}. Everyone was emailed the signed copy.</BodyText>
        {facts}
        <div className={styles.downloads}>
          <LinkButton href={completedUrl(state.recipient_id, "combined")} download>
            Download signed copy
          </LinkButton>
          <SmallText>The signed document and its certificate of completion, in one PDF.</SmallText>
          <div className={styles.quiet}>
            <a className={styles.quietLink} href={completedUrl(state.recipient_id, "document")} download>
              Document only
            </a>
            <a className={styles.quietLink} href={completedUrl(state.recipient_id, "certificate")} download>
              Certificate only
            </a>
          </div>
        </div>
        {back}
      </AuthPanel>
    );
  }

  return (
    <AuthPanel eyebrow={`${state.company} · ${state.document_name}`} heading={countersigner ? `${act}.` : `Signed. Thank you, ${first}.`}>
      {facts}
      <LinkButton href={copyUrl(state.recipient_id)} variant="quiet" download>
        Download a copy
      </LinkButton>
      <SmallText>{nextLine(view.waiting_for, view.countersigning)}</SmallText>
      {back}
    </AuthPanel>
  );
}
