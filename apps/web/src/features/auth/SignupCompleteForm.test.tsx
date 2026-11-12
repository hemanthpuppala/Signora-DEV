import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";
import { resetCapturedTokenForTests } from "@/shared/lib/useFragmentToken";

import { SignupCompleteForm } from "./SignupCompleteForm";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

function reply(status: number, body: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    }),
  );
}

describe("SignupCompleteForm", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/signup/verify#tok-abc");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    resetCapturedTokenForTests();
    window.history.replaceState(null, "", "/");
  });

  it("offers log-in when the account was created but the automatic log-in failed", async () => {
    fetchMock.mockImplementation((request) => {
      const path = new URL((request as Request).url).pathname;
      if (path === "/api/v1/meta") return reply(200, { version: "0", commit: "x", password_min_length: 12, password_rule: "Use 12 or more characters." });
      if (path === "/api/v1/auth/signup/verify") return reply(200, { email: "rosa@example.com" });
      if (path === "/api/v1/auth/signup/complete") return reply(201, { email: "rosa@example.com" });
      return reply(
        429,
        { type: "/problems/rate-limited", title: "Too many attempts", status: 429, code: "rate-limited", instance: "/api/v1/auth/login", request_id: "r" },
        { "Retry-After": "60" },
      );
    });
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SignupCompleteForm />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Company name"), "Hale & Ward LLP");
    await user.type(screen.getByLabelText("Your name"), "Rosa Hale");
    await user.type(screen.getByLabelText("Password", { exact: true }), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("Your account is ready.")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Log in to continue" });
    expect(link.getAttribute("href")).toBe("/login?email=rosa%40example.com");
    expect(replace).not.toHaveBeenCalled();
  });

  function answering(complete: (body: Record<string, unknown>) => Promise<Response>) {
    const sent: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (request) => {
      const path = new URL((request as Request).url).pathname;
      if (path === "/api/v1/meta") return reply(200, { version: "0", commit: "x", password_min_length: 12, password_rule: "Use 12 or more characters." });
      if (path === "/api/v1/auth/signup/verify") return reply(200, { email: "rosa@example.com" });
      if (path === "/api/v1/auth/signup/complete") {
        const body = (await (request as Request).json()) as Record<string, unknown>;
        sent.push(body);
        return complete(body);
      }
      return new Promise<Response>(() => {}); // the log-in that follows is not under test
    });
    return sent;
  }

  async function fillIn(website: string | null) {
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <SignupCompleteForm />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Company name"), "ScoutBoard");
    if (website !== null) await user.type(screen.getByLabelText("Company website"), website);
    await user.type(screen.getByLabelText("Your name"), "Rosa Hale");
    await user.type(screen.getByLabelText("Password", { exact: true }), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /create account/i }));
  }

  it("sends the company website as typed", async () => {
    const sent = answering(() => reply(201, { email: "rosa@example.com" }));
    await fillIn("https://www.scoutboard.com");
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.website).toBe("https://www.scoutboard.com");
  });

  it("sends no website when the optional field is left blank", async () => {
    const sent = answering(() => reply(201, { email: "rosa@example.com" }));
    await fillIn(null);
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.website).toBeNull();
  });

  it("shows the server's word on a website it refuses, at the field", async () => {
    answering(() =>
      reply(422, {
        type: "/problems/validation-failed",
        title: "Some fields need attention",
        status: 422,
        code: "validation-failed",
        instance: "/api/v1/auth/signup/complete",
        request_id: "r",
        errors: [{ field: "website", message: "Enter the company's website, like scoutboard.com" }],
      }),
    );
    await fillIn("localhost");
    expect(await screen.findByText("Enter the company's website, like scoutboard.com")).toBeTruthy();
  });
});
