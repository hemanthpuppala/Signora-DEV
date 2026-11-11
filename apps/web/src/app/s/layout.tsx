import type { Metadata } from "next";
import type { ReactNode } from "react";

// Signing pages are for one person each: never indexed, never followed, never a referrer.
export const metadata: Metadata = {
  title: "Signing",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function SigningLayout({ children }: { children: ReactNode }) {
  return children;
}
