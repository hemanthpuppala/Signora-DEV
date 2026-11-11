import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { AppShell } from "@/shared/ui";

import { CountersignInbox } from "./CountersignInbox";

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

describe("to countersign", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  const item = (extra: Record<string, unknown> = {}) => ({
    recipient_id: "r-9",
    envelope_id: "e-1",
    title: "Mutual NDA · Maya Chen",
    document_name: "Mutual NDA",
    department_id: "d-1",
    department_name: "Litigation",
    signers: ["Maya Chen"],
    // Half a day off whole days, so a moment between building them and rendering never matters.
    signed_at: new Date(Date.now() - 2.5 * 86_400_000).toISOString(),
    expires_at: new Date(Date.now() + 1.5 * 86_400_000).toISOString(),
    countersigned_at: null,
    completed: false,
    ...extra,
  });

  it("lists what waits for me as a table: the template, who signed, how long, when it expires", async () => {
    const asked: string[] = [];
    fetchMock.mockImplementation((input) => {
      const url = new URL((input as Request).url);
      asked.push(url.searchParams.get("state") ?? "");
      return reply(200, { items: url.searchParams.get("state") === "done" ? [] : [item()], next_cursor: null });
    });
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <CountersignInbox />
      </QueryClientProvider>,
    );

    const link = await screen.findByRole("link", { name: "Mutual NDA" });
    expect(link.getAttribute("href")).toBe("/countersign/r-9");
    expect(screen.getByRole("img", { name: "Waiting for you" })).toBeTruthy(); // the orange dot
    expect(screen.getByText("Litigation")).toBeTruthy();
    expect(screen.getByText("2 days")).toBeTruthy(); // waiting since the last signer signed
    expect(screen.getByText("In 2 days")).toBeTruthy(); // expiring soon, said in orange
    expect(screen.getByRole("link", { name: "Countersign" }).getAttribute("href")).toBe("/countersign/r-9");

    await userEvent.setup().click(screen.getByRole("tab", { name: "Countersigned" }));
    expect(await screen.findByText("You haven't countersigned anything yet.")).toBeTruthy();
    expect(asked).toContain("done");
  });

  it("says when nothing waits", async () => {
    fetchMock.mockImplementation(() => reply(200, { items: [], next_cursor: null }));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <CountersignInbox />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Nothing waits for your countersignature.")).toBeTruthy();
  });

  it("marks the navigation with a dot and the count only when something waits", () => {
    const { rerender } = render(<AppShell nav={[{ href: "/countersign", label: "To countersign", count: 2 }]}>{null}</AppShell>);
    expect(screen.getByRole("link", { name: /To countersign/ }).textContent).toBe("To countersign · 2");

    rerender(<AppShell nav={[{ href: "/countersign", label: "To countersign", count: 0 }]}>{null}</AppShell>);
    expect(screen.getByRole("link", { name: /To countersign/ }).textContent).toBe("To countersign");
  });
});
