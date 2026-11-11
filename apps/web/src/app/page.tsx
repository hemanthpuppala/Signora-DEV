import type { Viewport } from "next";
import { Inter_Tight } from "next/font/google";
import { cookies } from "next/headers";

import { Landing } from "@/features/landing/Landing";
import { SESSION_COOKIE } from "@/shared/lib/routes";

// The landing page's text face, in the two weights it uses (served from our own origin).
const sans = Inter_Tight({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-landing-sans",
  display: "swap",
});

// The landing page's paper colour, for the browser's own chrome.
export const viewport: Viewport = { themeColor: "#0e0e0d" };

/** The public landing page. With a session cookie, its calls to action open the workspace. */
export default async function LandingPage() {
  const signedIn = (await cookies()).has(SESSION_COOKIE);
  return <Landing signedIn={signedIn} className={sans.variable} />;
}
