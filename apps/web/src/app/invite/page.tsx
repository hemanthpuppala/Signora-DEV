import type { Metadata } from "next";
import { Suspense } from "react";

import { AcceptInviteForm } from "@/features/auth/AcceptInviteForm";

export const metadata: Metadata = { title: "Accept invitation", robots: { index: false } };

export default function Page() {
  return (
    <Suspense>
      <AcceptInviteForm />
    </Suspense>
  );
}
