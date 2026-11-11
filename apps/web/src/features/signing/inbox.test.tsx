import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

  it("lists each envelope waiting for me, linked to its countersign page", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        items: [
          {
            recipient_id: "r-9",
            envelope_id: "e-1",
            title: "Mutual NDA · Maya Chen",
            document_name: "Mutual NDA",
            department_id: "d-1",
            department_name: "Litigation",
            signers: ["Maya Chen"],
            signed_at: "2026-11-11T09:14:22Z",
            expires_at: "2026-11-25T09:14:22Z",
          },
        ],
        next_cursor: null,
      }),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <CountersignInbox />
      </QueryClientProvider>,
    );

    const link = await screen.findByRole("link", { name: /Mutual NDA · Maya Chen/ });
    expect(link.getAttribute("href")).toBe("/countersign/r-9");
    expect(link.textContent).toContain("Litigation");
    expect(link.textContent).toContain("Signed by Maya Chen");
  });

  it("says when there is nothing to countersign", async () => {
    fetchMock.mockImplementation(() => reply(200, { items: [], next_cursor: null }));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <CountersignInbox />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Nothing to countersign.")).toBeTruthy();
  });

  it("marks the navigation with a dot and the count only when something waits", () => {
    const { rerender } = render(<AppShell nav={[{ href: "/countersign", label: "To countersign", count: 2 }]}>{null}</AppShell>);
    expect(screen.getByRole("link", { name: /To countersign/ }).textContent).toBe("To countersign · 2");

    rerender(<AppShell nav={[{ href: "/countersign", label: "To countersign", count: 0 }]}>{null}</AppShell>);
    expect(screen.getByRole("link", { name: /To countersign/ }).textContent).toBe("To countersign");
  });
});
