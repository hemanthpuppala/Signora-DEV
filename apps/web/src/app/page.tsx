import { AppShell, Eyebrow, Heading1, Sub } from "@/shared/ui";

import { MetaPanel } from "./MetaPanel";

export default function HomePage() {
  return (
    <AppShell>
      <div>
        <Eyebrow>Agreements · signed before work begins</Eyebrow>
        <Heading1>Signora</Heading1>
        <Sub>The backbone is running.</Sub>
      </div>
      <MetaPanel />
    </AppShell>
  );
}
