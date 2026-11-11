"use client";

import { CountersignInbox } from "@/features/signing/CountersignInbox";
import { ConsoleShell } from "@/shared/session";

export default function CountersignRoute() {
  return <ConsoleShell>{() => <CountersignInbox />}</ConsoleShell>;
}
