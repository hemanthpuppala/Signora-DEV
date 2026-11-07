import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "@/features/auth/LoginForm";

export const metadata: Metadata = { title: "Log in", robots: { index: false } };

export default function Page() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
