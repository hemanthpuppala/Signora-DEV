import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { makeQueryClient } from "@/shared/api/QueryProvider";

import { useDepartmentFollows } from "./_follow";

const template = (status: string) => ({ latest_version: { id: "v-1", status } });

describe("a department's counts follow its templates", () => {
  it("reads the department again when a template changes state, not on every poll", () => {
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { rerender } = renderHook(({ list }) => useDepartmentFollows(list), {
      wrapper,
      initialProps: { list: [template("detecting")] },
    });
    expect(invalidate).not.toHaveBeenCalled(); // the first answer is no change

    rerender({ list: [template("detecting")] }); // a poll, nothing new
    expect(invalidate).not.toHaveBeenCalled();

    rerender({ list: [template("ready")] }); // fields found: now waiting for approval
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([["departments"], ["department"]]);
  });
});
