import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupCompleteForm } from "@/features/auth/SignupCompleteForm";

export const metadata: Metadata = { title: "Create your account", robots: { index: false } };

export default function Page() {
  return (
    <Suspense>
      <SignupCompleteForm />
    </Suspense>
  );
}
