"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { can, type Me } from "@/shared/session";
import {
  Button,
  ClampedText,
  Eyebrow,
  HeadRow,
  Heading1,
  LinkButton,
  MetricGrid,
  MetricTile,
  Notice,
} from "@/shared/ui";

import { dayMonth, departmentKey, useDepartment, type Department } from "./api";

/** Screens 07/08: one department. Its documents come from the documents feature, through the
 * route (a feature never imports another), as ``documents``. */
export function DepartmentPage({
  me,
  id,
  documents,
}: {
  me: Me;
  id: string;
  documents?: (department: Department) => ReactNode;
}) {
  const queryClient = useQueryClient();
  const department = useDepartment(id);
  const restore = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/departments/{department_id}/restore", {
          params: { path: { department_id: id } },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(departmentKey(id), updated);
      void queryClient.invalidateQueries({ queryKey: ["departments"] });
    },
  });

  if (department.isError) {
    const missing = department.error instanceof ApiError && department.error.status === 404;
    return (
      <Notice tone="warning" title={missing ? "Not found" : "Something went wrong"}>
        {missing ? "This department doesn't exist." : formError(department.error)}
      </Notice>
    );
  }
  const data = department.data;
  if (!data) return null;

  const manages = can(me, "departments.manage");
  const archived = data.status === "archived";
  return (
    <>
      <HeadRow
        actions={
          manages && !archived ? (
            <LinkButton href={`/departments/${id}/settings`} variant="quiet">
              Department settings
            </LinkButton>
          ) : null
        }
      >
        <Eyebrow>Department</Eyebrow>
        <Heading1>{data.name}</Heading1>
        {data.description ? <ClampedText>{data.description}</ClampedText> : null}
      </HeadRow>
      {archived && data.archived_at ? (
        <Notice
          title="Archived"
          action={
            manages ? (
              <Button variant="quiet" compact loading={restore.isPending} onClick={() => restore.mutate()}>
                Restore
              </Button>
            ) : undefined
          }
        >
          {`Archived on ${dayMonth(data.archived_at)}.${manages ? " Restore it to make changes." : ""}`}
        </Notice>
      ) : null}
      {restore.error ? <Notice tone="warning">{formError(restore.error)}</Notice> : null}
      <MetricGrid>
        <MetricTile value={data.counts.sent} label="Sent" />
        <MetricTile value={data.counts.signed} label="Signed" />
        <MetricTile value={data.counts.pending} label="Pending" />
      </MetricGrid>
      {documents?.(data)}
    </>
  );
}
