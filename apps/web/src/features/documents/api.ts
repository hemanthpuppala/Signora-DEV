"use client";

import type { components } from "@signora/contracts";
import { useQuery } from "@tanstack/react-query";

import { answerError, api, CSRF_COOKIE, CSRF_HEADER, unwrap } from "@/shared/api/client";
import { NetworkError } from "@/shared/api/errors";
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
/** Still being worked on: processed in the background, or its fields being found (Phase 5 §1.1). */
export function isWorking(status: VersionStatus): boolean {
  return status === "processing" || status === "detecting";
}

/** Its working copy exists, so it can be shown while its fields are found and after. */
export function hasWorkingCopy(status: VersionStatus): boolean {
  return status === "detecting" || status === "ready";
}

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
    // A list shows each document's newest version; poll while any is still being worked on.
    refetchInterval: (query) =>
      processingInterval(
        (query.state.data ?? [])
          .filter((document) => isWorking(document.latest_version.status))
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
          .filter((version) => isWorking(version.status))
          .map((version) => version.created_at),
      ),
  });
}

/**
 * Send one file as the raw body (Phase 4 LLD §2.2). XMLHttpRequest, not fetch, because only it
 * reports upload progress. Fails as the typed client does (``answerError``): ``ApiError`` for an
 * answer, ``NetworkError`` for none, a proxy's 502/503/504 included.
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
      reject(
        answerError({
          status: request.status,
          statusText: request.statusText,
          url: request.responseURL || url,
          body: request.response,
          header: (name) => request.getResponseHeader(name),
        }),
      );
    };
    request.onerror = () => reject(new NetworkError());
    request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => request.abort());
    request.send(file);
  });
}

/**
 * A file dropped on one page and uploaded on the next (the department page's and the new-department
 * page's dropzones hand it to the upload page, Phase 4 LLD §6.1, §6.3). One document is uploaded at
 * a time. Kept in memory: a reload forgets it, and the person drops it again.
 */
const handedOff = new Map<string, File>();

export function handOff(departmentId: string, file: File): void {
  handedOff.set(departmentId, file);
}

/** The file waiting for a department (pure: safe in a state initializer). */
export function handedOffFile(departmentId: string): File | null {
  return handedOff.get(departmentId) ?? null;
}

/** Forget it once the upload page has taken it. */
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
