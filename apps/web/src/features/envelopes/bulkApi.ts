"use client";

import type { components } from "@signora/contracts";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";

export type Sheet = components["schemas"]["Sheet"];
export type SheetColumn = components["schemas"]["Column"];
export type SheetRow = components["schemas"]["Row"];
export type SheetProblem = components["schemas"]["CellProblem"];
export type BatchDefaults = components["schemas"]["BatchDefaults"];
export type Batch = components["schemas"]["BatchView"];
/** What is sent to be checked: the sheet's columns, its rows, and what is chosen once for all. */
export type CheckBody = components["schemas"]["CheckRequest"];
export type BatchBody = components["schemas"]["BatchRequest"];

type Version = { documentId: string; versionId: string };
const path = ({ documentId, versionId }: Version) => ({ document_id: documentId, version_id: versionId });

export const batchesKey = (departmentId: string) => ["envelope-batches", departmentId] as const;

/** The spreadsheet for a version, as a link to download (Bulk send §8). */
export const templateHref = ({ documentId, versionId }: Version) =>
  `/api/v1/documents/${documentId}/versions/${versionId}/bulk-template`;

/** A filled spreadsheet read by the server: its columns, its rows, and each row's problems. */
export function readSheet(version: Version, file: File): Promise<Sheet> {
  return unwrap(
    api.POST("/api/v1/documents/{document_id}/versions/{version_id}/bulk-rows", {
      params: { path: path(version), query: { filename: file.name } },
      // The file's bytes are the body, as the documents upload sends them.
      body: file as unknown as string,
      bodySerializer: (body) => body as unknown as BodyInit,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
}

/** The rows judged again after edits, by the same rules as at upload and at send. */
export function checkSheet(version: Version, body: CheckBody): Promise<Sheet> {
  return unwrap(
    api.POST("/api/v1/documents/{document_id}/versions/{version_id}/bulk-rows/check", {
      params: { path: path(version) },
      body,
    }),
  );
}

/** The given rows as a CSV with the spreadsheet's headers: the rows a sender left out. */
export function leftOutFile(version: Version, body: CheckBody): Promise<Blob> {
  return unwrap(
    api.POST("/api/v1/documents/{document_id}/versions/{version_id}/bulk-rows/left-out", {
      params: { path: path(version) },
      body,
      parseAs: "blob",
    }),
  ) as Promise<Blob>;
}

/** A department's bulk sends still going or sent in the last day; asked again while one is going. */
export function useBatches(departmentId: string) {
  return useQuery({
    queryKey: batchesKey(departmentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/envelope-batches", {
          params: { path: { department_id: departmentId } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.batches.some((batch) => batch.status === "sending") ? 2000 : false,
  });
}

/** How a ticked box is written in a cell the server gives back (envelopes.bulk_sheet.TICKED). */
export const TICKED = "yes";

/** Whether a row has anything that stops it from being sent. */
export const hasError = (row: SheetRow) => (row.problems ?? []).some((problem) => problem.level !== "warning");
