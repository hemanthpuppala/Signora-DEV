import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProblemDetails } from "@signora/contracts";

import { ApiError, NetworkError } from "./errors";
import { useIdempotentAction, type Perform } from "./useIdempotentAction";

type Input = { name: string };

function problem(code: string, status: number): ProblemDetails {
  return { type: `/problems/${code}`, title: code, status, code, instance: "/x", request_id: "r-1" };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("useIdempotentAction", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("succeeds on the first try and clears the stored key", async () => {
    const perform = vi.fn<Perform<Input, string>>().mockResolvedValue("created");
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "Finance" }));
    expect(result.current.isPending).toBe(true);
    await flush();

    expect(result.current.state).toEqual({ status: "success", data: "created", error: null });
    expect(window.sessionStorage.length).toBe(0);
  });

  it("retries with the same key after a network error, with backoff", async () => {
    const perform = vi
      .fn<Perform<Input, string>>()
      .mockRejectedValueOnce(new NetworkError())
      .mockRejectedValueOnce(new NetworkError())
      .mockResolvedValue("created");
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "Finance" }));
    await flush();
    expect(result.current.state.status).toBe("retrying");

    await act(async () => vi.advanceTimersByTime(1_000));
    await flush();
    await act(async () => vi.advanceTimersByTime(2_000));
    await flush();

    expect(result.current.state.status).toBe("success");
    const keys = perform.mock.calls.map(([, key]) => key);
    expect(new Set(keys).size).toBe(1);
    expect(keys).toHaveLength(3);
  });

  it("retries immediately when the browser comes back online", async () => {
    const perform = vi
      .fn<Perform<Input, string>>()
      .mockRejectedValueOnce(new NetworkError())
      .mockResolvedValue("created");
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "Finance" }));
    await flush();
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await flush();

    expect(result.current.state.status).toBe("success");
    expect(perform).toHaveBeenCalledTimes(2);
  });

  it("honours Retry-After on 409 request-in-progress", async () => {
    const perform = vi
      .fn<Perform<Input, string>>()
      .mockRejectedValueOnce(new ApiError(problem("request-in-progress", 409), 3))
      .mockResolvedValue("created");
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "Finance" }));
    await flush();
    expect(result.current.state.status).toBe("pending");

    await act(async () => vi.advanceTimersByTime(2_900));
    expect(perform).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTime(200));
    await flush();

    expect(result.current.state.status).toBe("success");
  });

  it("pressing again while pending resends the same key, not a new action", async () => {
    let release: (value: string) => void = () => undefined;
    const perform = vi
      .fn<Perform<Input, string>>()
      .mockRejectedValueOnce(new NetworkError())
      .mockImplementation(() => new Promise<string>((resolve) => (release = resolve)));
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "Finance" }));
    await flush();
    act(() => result.current.run({ name: "Changed while pending" }));
    await flush();
    act(() => release("created"));
    await flush();

    const [first, second] = perform.mock.calls;
    expect(second?.[1]).toBe(first?.[1]);
    expect(second?.[0]).toEqual({ name: "Finance" });
  });

  it("a definite API error ends the action and drops the key", async () => {
    const perform = vi
      .fn<Perform<Input, string>>()
      .mockRejectedValue(new ApiError(problem("validation-failed", 422)));
    const { result } = renderHook(() => useIdempotentAction("create-project", perform));

    act(() => result.current.run({ name: "" }));
    await flush();

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.error?.code).toBe("validation-failed");
    expect(window.sessionStorage.length).toBe(0);

    act(() => result.current.run({ name: "Finance" }));
    expect(perform.mock.calls[1]?.[1]).not.toBe(perform.mock.calls[0]?.[1]);
  });

  it("resumes a pending action after a page refresh with the stored key", async () => {
    window.sessionStorage.setItem(
      "signora:action:create-project",
      JSON.stringify({ key: "stored-key-1", input: { name: "Finance" } }),
    );
    const perform = vi.fn<Perform<Input, string>>().mockResolvedValue("created");

    const { result } = renderHook(() => useIdempotentAction("create-project", perform));
    await flush();

    expect(perform).toHaveBeenCalledWith({ name: "Finance" }, "stored-key-1");
    expect(result.current.state.status).toBe("success");
  });
});
