import { renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { resetCapturedTokenForTests, useFragmentToken } from "./useFragmentToken";

function openLink(url: string) {
  window.history.replaceState(null, "", url);
}

describe("useFragmentToken", () => {
  afterEach(() => {
    resetCapturedTokenForTests();
    openLink("/");
  });

  it("keeps the token when strict mode runs the effect twice, and clears the address bar", async () => {
    openLink("/invite#tok-123");
    const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;

    const { result } = renderHook(() => useFragmentToken(), { wrapper: strict });

    await waitFor(() => expect(result.current).toBe("tok-123"));
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/invite");
  });

  it("gives a remounted page the same token", async () => {
    openLink("/reset-password#tok-456");
    const first = renderHook(() => useFragmentToken());
    await waitFor(() => expect(first.result.current).toBe("tok-456"));
    first.unmount();

    const again = renderHook(() => useFragmentToken());
    await waitFor(() => expect(again.result.current).toBe("tok-456"));
  });

  it("is null for a page opened without a token, and does not reuse another page's token", async () => {
    openLink("/invite#tok-789");
    const invite = renderHook(() => useFragmentToken());
    await waitFor(() => expect(invite.result.current).toBe("tok-789"));

    openLink("/reset-password");
    const reset = renderHook(() => useFragmentToken());
    await waitFor(() => expect(reset.result.current).toBeNull());
  });
});
