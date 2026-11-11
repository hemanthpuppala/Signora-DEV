"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";
import { CONSOLE_HOME } from "@/shared/lib/routes";
import { can, type Me } from "@/shared/session";
import {
  Button,
  ClampedText,
  HeadAction,
  HeadRow,
  Heading1,
  MetricGrid,
  MetricTile,
  Notice,
  Tabs,
} from "@/shared/ui";

import { dayMonth, departmentKey, useDepartment, type Department } from "./api";

export type DepartmentTab = "envelopes" | "documents";

/**
 * Screens 07/08: one department. Every tab shares this head (the way back with Department
 * settings at its end, the name and its description, the counts) and the tabs; the open tab's
 * content comes from the route as ``children`` (a feature never imports another), and so do its
 * ``tabActions`` (at the end of the tab line) and the number of documents for the tab's label.
 */
export function DepartmentPage({
  me,
  id,
  tab,
  documentCount,
  tabActions,
  onAddEnvelope,
  children,
}: {
  me: Me;
  id: string;
  tab: DepartmentTab;
  documentCount?: number | undefined;
  tabActions?: (department: Department) => ReactNode;
  /** Opens the send (Phase 7); the route owns it, as features never import each other. */
  onAddEnvelope?: (() => void) | undefined;
  children: (department: Department) => ReactNode;
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
        back={{ href: CONSOLE_HOME, label: "Departments" }}
        backActions={
          <>
            {!archived && onAddEnvelope && data.access === "edit" ? (
              <HeadAction icon="send" label="New envelope" variant="primary" onClick={onAddEnvelope} />
            ) : null}
            {manages && !archived ? (
              <HeadAction icon="settings" label="Settings" href={`/departments/${id}/settings`} />
            ) : null}
          </>
        }
      >
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
      <Tabs
        label="Department"
        items={[
          { href: `/departments/${id}`, label: "Envelopes", active: tab === "envelopes" },
          {
            href: `/departments/${id}/documents`,
            label: documentCount === undefined ? "Templates" : `Templates · ${documentCount}`,
            active: tab === "documents",
          },
        ]}
        actions={tabActions?.(data)}
      />
      {children(data)}
    </>
  );
}
