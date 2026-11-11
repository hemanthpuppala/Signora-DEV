import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Source_Code_Pro } from "next/font/google";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { QueryProvider } from "@/shared/api/QueryProvider";
import { ToastProvider } from "@/shared/ui";

import "@/shared/ui/globals.css";

// Downloaded at build time and served from our own origin (no runtime call to Google).
const serif = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});
const mono = Source_Code_Pro({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Signora", template: "%s · Signora" },
  description: "Agreements signed before work begins.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "dark",
  themeColor: "#000000",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Reading request headers renders every page per request, which the nonce-based Content
  // Security Policy requires: Next.js applies the nonce from proxy.ts to its script tags.
  await headers();
  return (
    // data-scroll-behavior: the landing page scrolls smoothly between its sections; this tells
    // Next.js to switch that off while it changes page, so a new page opens at the top at once.
    <html lang="en" className={`${serif.variable} ${mono.variable}`} data-scroll-behavior="smooth">
      <body>
        <QueryProvider>
          <ToastProvider>{children}</ToastProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
