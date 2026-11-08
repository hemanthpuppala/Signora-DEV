"use client";

import { ConsoleShell } from "@/shared/session";
import { Heading1 } from "@/shared/ui";

/** Console home. Projects (Phase 3) will live here. */
export default function HomePage() {
  return (
    <ConsoleShell>{(me) => <Heading1>Welcome, {me.user.name.split(" ")[0]}.</Heading1>}</ConsoleShell>
  );
}
