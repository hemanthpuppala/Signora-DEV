import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/shared/api/client";
import { makeQueryClient } from "@/shared/api/QueryProvider";

import { MetaPanel } from "./MetaPanel";

vi.mock("@/shared/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/shared/api/client")>();
  return { ...original, api: { GET: vi.fn() } };
});

const GET = vi.mocked(api.GET);

function answer(path: string) {
  const data = path === "/api/v1/meta" ? { version: "0.1.0", commit: "abc1234" } : { status: "ok" };
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
}

function renderPanel() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MetaPanel />
    </QueryClientProvider>,
  );
}

describe("MetaPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    GET.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("says it is retrying during an outage and recovers by itself when the API returns", async () => {
    let apiUp = false;
    GET.mockImplementation(((path: string) =>
      apiUp ? answer(path) : Promise.reject(new TypeError("Failed to fetch"))) as never);

    renderPanel();
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Connection lost — retrying…")).toBeTruthy();

    // Well past the old three-retry limit (1 + 2 + 4 + 8 + 16 s): still retrying, still saying so.
    await act(() => vi.advanceTimersByTimeAsync(31_000));
    const metaCalls = GET.mock.calls.filter(([path]) => path === "/api/v1/meta").length;
    expect(metaCalls).toBeGreaterThan(4);
    expect(screen.getByText("Connection lost — retrying…")).toBeTruthy();

    // The API returns: the next backoff retry (at most 30 s away, plus scheduling) succeeds without
    // focus or reload.
    apiUp = true;
    await act(() => vi.advanceTimersByTimeAsync(31_000));
    expect(screen.queryByText("Connection lost — retrying…")).toBeNull();
    expect(screen.getByText("abc1234")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
  });

  it("does not retry a definite API error", async () => {
    GET.mockImplementation((() =>
      Promise.resolve({
        error: {
          type: "/problems/internal",
          title: "Internal",
          status: 500,
          code: "internal",
          instance: "/api/v1/meta",
          request_id: "r-9",
        },
        response: new Response(null, { status: 500 }),
      })) as never);

    renderPanel();
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText("Something went wrong on our side (reference r-9).")).toBeTruthy();
    expect(GET.mock.calls.filter(([path]) => path === "/api/v1/meta")).toHaveLength(1);
  });
});
