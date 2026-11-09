"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, formError } from "@/shared/api/errors";

import { documentKey, formatBytes, uploadFile } from "./api";
import { useDocumentLimits } from "./limits";

/** A file on its way up, before it is a version. */
export type Uploading = { name: string; progress: number };

/**
 * Add a new version straight from a file (Phase 4 LLD §6.4): upload it, then add it, with no form
 * in between; the version's own status carries on from there. A file identical to any version in
 * the department is never a version (§2.3): the person is told where it already is.
 */
export function useNewVersion(departmentId: string, documentId: string) {
  const queryClient = useQueryClient();
  const limits = useDocumentLimits();
  const [uploading, setUploading] = useState<Uploading | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const add = async (file: File) => {
    const upload = await uploadFile(departmentId, file, (progress) => setUploading({ name: file.name, progress }));
    if (upload.duplicate) {
      const where = upload.duplicate;
      setProblem(
        `This file is already here as ${where.document_name}${where.archived ? " (archived)" : ""}, version ${where.version_number}. It can only be added as a separate document.`,
      );
      return;
    }
    const updated = await unwrap(
      api.POST("/api/v1/documents/{document_id}/versions", {
        params: { path: { document_id: documentId } },
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: { upload_id: upload.id, ai_instructions: "" },
      }),
    );
    queryClient.setQueryData(documentKey(documentId), updated);
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const start = (file: File) => {
    setProblem(null);
    if (limits.maxBytes !== undefined && file.size > limits.maxBytes) {
      setProblem(`Upload a file of ${formatBytes(limits.maxBytes)} or less`);
      return;
    }
    setUploading({ name: file.name, progress: 0 });
    add(file)
      .catch((error: unknown) => setProblem(error instanceof ApiError ? error.problem.title : formError(error)))
      .finally(() => setUploading(null));
  };

  return { start, uploading, problem };
}
