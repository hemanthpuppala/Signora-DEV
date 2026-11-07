"use client";

import { ConsoleShell } from "@/shared/session";
import { Eyebrow, Heading1, Sub } from "@/shared/ui";

import { MetaPanel } from "./MetaPanel";

/** Console home. Projects (Phase 3) will live here; for now: who you are and system status. */
export default function HomePage() {
  return (
    <ConsoleShell>
      {(me) => (
        <>
          <div>
            <Eyebrow>{me.workspace.name}</Eyebrow>
            <Heading1>Welcome, {me.user.name.split(" ")[0]}.</Heading1>
            <Sub>Agreements signed before work begins.</Sub>
          </div>
          <MetaPanel />
        </>
      )}
    </ConsoleShell>
  );
}
