"use client";

import { PeoplePanel } from "@/features/people/PeoplePanel";
import { ConsoleShell } from "@/shared/session";
import { Eyebrow, Heading1 } from "@/shared/ui";

export default function PeoplePage() {
  return (
    <ConsoleShell requires="members.manage">
      {(me) => (
        <>
          <div>
            <Eyebrow>Workspace</Eyebrow>
            <Heading1>People</Heading1>
          </div>
          <PeoplePanel me={me} />
        </>
      )}
    </ConsoleShell>
  );
}
