import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { LoginForm } from "./LoginForm";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

const me = {
  user: { id: "u", email: "rosa@example.com", name: "Rosa Hale" },
  workspace: { id: "w", name: "Acme" },
  role: { id: "r", key: "read_write", name: "Editor", description: "Can create and send agreements." },
  display_role: { name: "Editor", description: "Can create and send agreements." },
  permissions: [],
  is_creator: false,
};

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    }),
  );
}

function renderForm() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LoginForm />
    </QueryClientProvider>,
  );
}

async function submit(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: /log in/i }));
}

describe("LoginForm", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    replace.mockReset();
    search = "";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("goes to the requested page after logging in", async () => {
    search = "next=/people";
    fetchMock.mockImplementation(() => respond(200, me));
    renderForm();

    await submit("rosa@example.com", "correct horse battery");

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/people"));
  });

  it("shows the server's generic message for bad credentials", async () => {
    fetchMock.mockImplementation(() =>
      respond(401, {
        type: "/problems/invalid-credentials",
        title: "Email or password is incorrect",
        status: 401,
        code: "invalid-credentials",
        instance: "/api/v1/auth/login",
        request_id: "r",
      }),
    );
    renderForm();

    await submit("rosa@example.com", "wrong");

    expect(await screen.findByText("Email or password is incorrect")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("says how long to wait when throttled", async () => {
    fetchMock.mockImplementation(() =>
      respond(
        429,
        {
          type: "/problems/rate-limited",
          title: "Too many attempts; try again later",
          status: 429,
          code: "rate-limited",
          instance: "/api/v1/auth/login",
          request_id: "r",
        },
        { "Retry-After": "240" },
      ),
    );
    renderForm();

    await submit("rosa@example.com", "guess");

    expect(await screen.findByText("Too many attempts. Try again in 4 minutes.")).toBeTruthy();
  });

  it("prefills the email and confirms a password reset", () => {
    search = "reset=1&email=rosa%40example.com";
    renderForm();

    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("rosa@example.com");
    expect(screen.getByText("Log in with your new password.")).toBeTruthy();
  });
});
