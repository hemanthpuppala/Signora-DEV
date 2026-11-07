import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AppShell, Eyebrow, Heading1 } from "@/shared/ui";

import { Gallery } from "./Gallery";

export const metadata: Metadata = { title: "Component gallery", robots: { index: false } };

/** Development-only component gallery (backbone LLD §8.6). Absent from production builds. */
export default function ComponentGalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <AppShell workspace="Hale & Ward LLP" nav={[{ href: "/dev/ui", label: "Gallery", active: true }]}>
      <div>
        <Eyebrow>Design system</Eyebrow>
        <Heading1>Components</Heading1>
      </div>
      <Gallery />
    </AppShell>
  );
}
