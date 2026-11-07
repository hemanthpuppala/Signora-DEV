import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/shared/api/client";

import { fetchSession, safeNext } from "./session";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

const problem = (code: string, status: number) => ({
  type: `/problems/${code}`,
  title: code,
  status,
  code,
  instance: "/api/v1/me",
  request_id: "r-1",
});

describe("session", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    // jsdom runs on http, where browsers refuse __Host- cookies; stub what the page would read.
    vi.spyOn(document, "cookie", "get").mockReturnValue("other=1; __Host-signora_csrf=csrf-123");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    fetchMock.mockReset();
  });

  it("treats 401 from /me as signed out, not as an error", async () => {
    fetchMock.mockResolvedValue(json(401, problem("unauthenticated", 401)));
    await expect(fetchSession()).resolves.toBeNull();
  });

  it("surfaces other failures", async () => {
    fetchMock.mockResolvedValue(json(500, problem("internal-error", 500)));
    await expect(fetchSession()).rejects.toThrow();
  });

  it("sends the CSRF cookie back in a header on state changes only", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })));

    await api.POST("/api/v1/auth/logout");
    await api.GET("/api/v1/meta");

    const [post, get] = fetchMock.mock.calls.map(([request]) => request as Request);
    expect(post?.headers.get("X-CSRF-Token")).toBe("csrf-123");
    expect(get?.headers.get("X-CSRF-Token")).toBeNull();
  });

  it.each([
    [null, "/"],
    ["/people", "/people"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    ["https://evil.example", "/"],
  ])("follows only same-site paths after log-in (%s)", (next, expected) => {
    expect(safeNext(next)).toBe(expected);
  });
});
