import type { QueryClient } from "@tanstack/react-query";

/**
 * Query keys more than one feature uses: one definition, so a change made in one feature (a
 * template approved, uploaded) refreshes what another shows (a department's counts and dots).
 */
export const departmentsKey = (status: string) => ["departments", status] as const;
export const departmentKey = (id: string) => ["department", id] as const;

/** Every department's data again: its card on the Departments page and its own page's tabs. */
export function refreshDepartments(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["departments"] });
  void queryClient.invalidateQueries({ queryKey: ["department"] });
}
