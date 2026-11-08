"use client";

import type { components } from "@signora/contracts";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";

export type Department = components["schemas"]["Department"];
export type DepartmentSummary = components["schemas"]["DepartmentSummary"];
export type DepartmentStatus = "active" | "archived";

export const departmentsKey = (status: DepartmentStatus) => ["departments", status] as const;
export const departmentKey = (id: string) => ["department", id] as const;

export function useDepartments(status: DepartmentStatus) {
  return useQuery({
    queryKey: departmentsKey(status),
    queryFn: () => unwrap(api.GET("/api/v1/departments", { params: { query: { status } } })),
  });
}

export function useDepartment(id: string) {
  return useQuery({
    queryKey: departmentKey(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}", {
          params: { path: { department_id: id } },
        }),
      ),
  });
}

/** "7 November": how dates read in sentences across the console. */
export function dayMonth(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long" });
}
