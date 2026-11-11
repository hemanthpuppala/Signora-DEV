import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { forgetExchangesForTests, OpenLink } from "./OpenLink";
import { SignerPage } from "./SignerPage";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const RECIPIENT = "0193a5f2-0000-7000-8000-000000000001";

function reply(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

const problem = (status: number, code: string, title: string) => ({
  type: `/problems/${code}`,
  title,
  status,
  code,
  instance: "/api/v1/sign/open",
  request_id: "r",
});

function show(node: React.ReactNode) {
  render(<QueryClientProvider client={makeQueryClient()}>{node}</QueryClientProvider>);
}

describe("opening a signing link", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    replace.mockReset();
    forgetExchangesForTests();
  });

  it("exchanges the token once and moves to the clean address", async () => {
    fetchMock.mockImplementation(() => reply(200, { recipient_id: RECIPIENT, next: "verify" }));
    show(<OpenLink token="tok-1" />);

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith(`/sign/${RECIPIENT}`));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(await request.json()).toEqual({ token: "tok-1" });
  });

  it("says a closed link is no longer open, and never why", async () => {
    fetchMock.mockImplementation(() =>
      reply(404, problem(404, "link-closed", "This request is no longer open")),
    );
    show(<OpenLink token="tok-2" />);

    expect(await screen.findByText("This request is no longer open.")).toBeTruthy();
    expect(screen.getByText("Nothing more is needed from you.")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("the signer's page", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("names the sender and the step", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        recipient_id: RECIPIENT,
        name: "Maya Chen",
        email_masked: "m•••@example.com",
        title: "Mutual NDA · Maya Chen",
        company: "Hale & Ward LLP",
        sender_name: "Rosa Hale",
        sender_email: "rosa@haleward.example",
        next: "verify",
        signed_at: null,
      }),
    );
    show(<SignerPage recipientId={RECIPIENT} />);

    expect(await screen.findByText("Confirm it's you.")).toBeTruthy();
    expect(screen.getByText("Rosa Hale sent you this to review and sign.")).toBeTruthy();
  });

  it("asks to open the link again when the session ended", async () => {
    fetchMock.mockImplementation(() =>
      reply(401, problem(401, "session-ended", "Your session ended")),
    );
    show(<SignerPage recipientId={RECIPIENT} />);

    expect(await screen.findByText("Your session ended.")).toBeTruthy();
  });
});
