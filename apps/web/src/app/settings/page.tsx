"use client";

import { SettingsPanel } from "@/features/account/SettingsPanel";
import { ConsoleShell } from "@/shared/session";
import { Eyebrow, Heading1 } from "@/shared/ui";

export default function SettingsPage() {
  return (
    <ConsoleShell>
      {(me) => (
        <>
          <div>
            <Eyebrow>Account</Eyebrow>
            <Heading1>Settings</Heading1>
          </div>
          <SettingsPanel me={me} />
        </>
      )}
    </ConsoleShell>
  );
}
