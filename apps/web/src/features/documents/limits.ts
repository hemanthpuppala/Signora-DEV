"use client";

import { useMeta } from "@/shared/api/useMeta";

import { formatBytes } from "./api";

/** The upload limits as the server enforces them (Phase 4 LLD §2.1), stated before uploading. */
export function useDocumentLimits() {
  const meta = useMeta();
  const maxBytes = meta.data?.document_max_bytes;
  const maxPages = meta.data?.document_max_pages;
  const hint =
    maxBytes && maxPages
      ? `or click to choose · up to ${formatBytes(maxBytes)} · up to ${maxPages} pages`
      : "or click to choose";
  return { maxBytes, maxPages, hint };
}
