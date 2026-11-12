"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { refreshDepartments } from "@/shared/api/queryKeys";

/**
 * The department's counts follow its templates: when a template's newest version changes state
 * (its fields found, so now waiting for approval; approved; failed), the department is read again
 * for its "to approve" dot. The templates' list already polls while one is being worked on.
 */
export function useDepartmentFollows(
  templates: readonly { latest_version: { id: string; status: string } }[] | undefined,
): void {
  const queryClient = useQueryClient();
  const states = templates?.map((t) => `${t.latest_version.id}:${t.latest_version.status}`).join(",");
  const seen = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (states === undefined) return;
    if (seen.current !== undefined && seen.current !== states) refreshDepartments(queryClient);
    seen.current = states;
  }, [states, queryClient]);
}
