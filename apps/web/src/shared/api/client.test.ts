import { describe, expect, it } from "vitest";

import { unwrap } from "./client";
import { ApiError, NetworkError, userMessage } from "./errors";

function answer(status: number, error?: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve({ error, response: new Response(null, { status, headers }) });
}

async function apiErrorOf(call: Promise<unknown>): Promise<ApiError> {
  const error: unknown = await call.catch((e: unknown) => e);
  if (!(error instanceof ApiError)) throw new Error(`expected an ApiError, got ${String(error)}`);
  return error;
}

const problem = {
  type: "/problems/not-found",
  title: "Not found",
  status: 404,
  code: "not-found",
  instance: "/api/v1/x",
  request_id: "r-1",
};

describe("unwrap", () => {
  it("returns data for a success", async () => {
    const call = Promise.resolve({ data: { ok: true }, response: new Response(null, { status: 200 }) });
    await expect(unwrap(call)).resolves.toEqual({ ok: true });
  });

  it("treats a failed fetch as no answer", async () => {
    await expect(unwrap(Promise.reject(new TypeError("Failed to fetch")))).rejects.toBeInstanceOf(
      NetworkError,
    );
  });

  it.each([502, 503, 504])("treats a proxy's bare %i as no answer", async (status) => {
    await expect(unwrap(answer(status, "<html>Bad Gateway</html>"))).rejects.toBeInstanceOf(
      NetworkError,
    );
  });

  it("treats a problem document as a definite answer, keeping Retry-After", async () => {
    const error = await apiErrorOf(unwrap(answer(404, problem, { "Retry-After": "3" })));
    expect(error.code).toBe("not-found");
    expect(error.retryAfterSeconds).toBe(3);
  });

  it("treats a bare non-proxy status (Caddy's empty 413) as a definite answer", async () => {
    const error = await apiErrorOf(unwrap(answer(413, undefined, { "X-Request-ID": "r-413" })));
    expect(error.status).toBe(413);
    expect(error.problem.request_id).toBe("r-413");
    expect(userMessage(error)).toBe("This is too large to send.");
  });

  it("reports a bare 500 as a server error, not a lost connection", async () => {
    const error = await apiErrorOf(unwrap(answer(500, "Internal Server Error")));
    expect(userMessage(error)).toBe("Something went wrong on our side.");
  });
});
