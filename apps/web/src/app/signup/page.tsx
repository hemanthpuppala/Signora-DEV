import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupStartForm } from "@/features/auth/SignupStartForm";

export const metadata: Metadata = { title: "Sign up", robots: { index: false } };

export default function Page() {
  return (
    <Suspense>
      <SignupStartForm />
    </Suspense>
  );
}
