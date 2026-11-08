import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "./QueryProvider";
import { useMeta } from "./useMeta";
import { usePasswordRules } from "./usePasswordRules";

const META = {
  version: "0.1.0",
  commit: "abc1234",
  password_min_length: 12,
  password_rule: "Use 12 or more characters.",
  document_max_bytes: 20 * 1024 * 1024,
  document_max_pages: 200,
};

function Readers() {
  const rules = usePasswordRules();
  const meta = useMeta();
  return (
    <p>
      {rules.hint ?? "…"} | {meta.data?.document_max_pages ?? "…"}
    </p>
  );
}

describe("useMeta", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("serves every reader of the server's settings from one request", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(META), { headers: { "content-type": "application/json" } })),
    );
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <Readers />
        <Readers />
      </QueryClientProvider>,
    );

    expect(await screen.findAllByText("Use 12 or more characters. | 200")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
