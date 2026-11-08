"use client";

import type { components, ProblemDetails } from "@signora/contracts";
import { useQuery } from "@tanstack/react-query";

import { api, CSRF_COOKIE, CSRF_HEADER, unwrap } from "@/shared/api/client";
import { ApiError, NetworkError } from "@/shared/api/errors";
import { readCookie } from "@/shared/lib/cookies";

export type DocumentSummary = components["schemas"]["DocumentSummary"];
export type DocumentDetail = components["schemas"]["DocumentDetail"];
export type Version = components["schemas"]["VersionView"];
export type Upload = components["schemas"]["UploadView"];
export type VersionStatus = Version["status"];

export const documentsKey = (departmentId: string) => ["documents", departmentId] as const;
export const documentKey = (id: string) => ["document", id] as const;

/**
 * Polling while something is processing (Phase 4 LLD §6.5, ADR-DOC3): every second for the first
 * 10 s of the newest processing version, every 2 s up to a minute, then every 5 s; no polling when
 * nothing is processing. One place, so it can become Server-Sent Events later without the screens
 * changing. TanStack pauses it in background tabs.
 */
export function processingInterval(processingSince: readonly string[], now = Date.now()): number | false {
  if (processingSince.length === 0) return false;
  const newest = Math.max(...processingSince.map((at) => Date.parse(at)));
  const age = now - newest;
  if (age < 10_000) return 1_000;
  if (age < 60_000) return 2_000;
  return 5_000;
}

export function useDocuments(departmentId: string) {
  return useQuery({
    queryKey: documentsKey(departmentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/departments/{department_id}/documents", {
          params: { path: { department_id: departmentId } },
        }),
      ),
    // A list shows each document's newest version; poll while any is processing.
    refetchInterval: (query) =>
      processingInterval(
        (query.state.data ?? [])
          .filter((document) => document.latest_version.status === "processing")
          .map((document) => document.latest_version.created_at),
      ),
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: documentKey(id ?? ""),
    enabled: id !== null,
    queryFn: () =>
      unwrap(api.GET("/api/v1/documents/{document_id}", { params: { path: { document_id: id ?? "" } } })),
    refetchInterval: (query) =>
      processingInterval(
        (query.state.data?.versions ?? [])
          .filter((version) => version.status === "processing")
          .map((version) => version.created_at),
      ),
  });
}

/**
 * Send one file as the raw body (Phase 4 LLD §2.2). XMLHttpRequest, not fetch, because only it
 * reports upload progress. Throws ``ApiError`` for an answer, ``NetworkError`` for none.
 */
export function uploadFile(
  departmentId: string,
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<Upload> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const url = `/api/v1/departments/${encodeURIComponent(departmentId)}/uploads?filename=${encodeURIComponent(file.name)}`;
    request.open("POST", url);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    const token = readCookie(CSRF_COOKIE);
    if (token) request.setRequestHeader(CSRF_HEADER, token);
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status === 201) {
        resolve(request.response as Upload);
        return;
      }
      const body = request.response as Partial<ProblemDetails> | null;
      const problem: ProblemDetails =
        body && typeof body.code === "string"
          ? (body as ProblemDetails)
          : {
              type: "about:blank",
              title: request.statusText || `HTTP ${request.status}`,
              status: request.status,
              // Caddy refuses bodies over its own limit with a bare 413.
              code: request.status === 413 ? "payload-too-large" : `http-${request.status}`,
              instance: url,
              request_id: request.getResponseHeader("X-Request-ID"),
            };
      reject(new ApiError(problem));
    };
    request.onerror = () => reject(new NetworkError());
    request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => request.abort());
    request.send(file);
  });
}

/**
 * Files dropped on one page and uploaded on the next (the department page's and the new-department
 * page's dropzones hand them to the upload page, Phase 4 LLD §6.1, §6.3). Kept in memory: a reload
 * forgets them, and the person drops them again.
 */
const handedOff = new Map<string, File[]>();

export function handOff(departmentId: string, files: readonly File[]): void {
  handedOff.set(departmentId, [...(handedOff.get(departmentId) ?? []), ...files]);
}

/** The files waiting for a department (pure: safe in a state initializer). */
export function handedOffFiles(departmentId: string): File[] {
  return handedOff.get(departmentId) ?? [];
}

/** Forget them once the upload page has taken them. */
export function clearHandOff(departmentId: string): void {
  handedOff.delete(departmentId);
}

/** The department as the documents screens need it (the route passes it in). */
export type DepartmentRef = {
  id: string;
  name: string;
  status: "active" | "archived";
  access: "edit" | "read";
};

/** "50 MB", "12.4 MB", "640 KB". */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    const megabytes = bytes / (1024 * 1024);
    return `${Number.isInteger(megabytes) ? megabytes : megabytes.toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
