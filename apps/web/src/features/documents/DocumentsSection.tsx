"use client";

import { useRouter } from "next/navigation";

import { formError } from "@/shared/api/errors";
import { DocumentCard, DocumentGrid, Dropzone, Notice, SmallText, StatusPill } from "@/shared/ui";

import { handOff, isWorking, useDocuments, type DocumentSummary } from "./api";
import { useDocumentLimits } from "./limits";
import { VERSION_STATUS } from "./status";

const updated = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/** "Word → PDF · 2 pages · 11 fields · updated Nov 8": what the card says about a document. */
function facts(document: DocumentSummary): string {
  const latest = document.latest_version;
  return [
    document.kind === "docx" ? "Word → PDF" : document.kind === "pdf" ? "PDF" : null,
    document.page_count !== null ? `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}` : null,
    latest.status === "ready" && latest.field_count !== null
      ? `${latest.field_count} ${latest.field_count === 1 ? "field" : "fields"}`
      : null,
    `updated ${updated(document.updated_at)}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * A department's Documents tab (Phase 4 LLD §6.1, the prototype's documents screen): each document
 * as a card leading to its page. With no documents yet, people with edit access get a dropzone: a
 * dropped file opens the upload page, already uploading.
 */
export function DocumentsSection({ departmentId, canEdit }: { departmentId: string; canEdit: boolean }) {
  const router = useRouter();
  const documents = useDocuments(departmentId);
  const limits = useDocumentLimits();

  if (documents.isError) return <Notice tone="warning">{formError(documents.error)}</Notice>;
  const list = documents.data;
  if (!list) return null;
  if (list.length === 0) {
    return canEdit ? (
      <Dropzone
        title="Drop a PDF or Word file"
        hint={limits.hint}
        accept=".pdf,.docx"
        onFile={(file) => {
          handOff(departmentId, file);
          router.push(`/departments/${departmentId}/upload`);
        }}
      />
    ) : (
      <SmallText>No templates yet.</SmallText>
    );
  }
  return (
    <DocumentGrid label="Templates">
      {list.map((document) => {
        const latest = document.latest_version;
        const status = VERSION_STATUS[latest.status];
        const current = document.current_version;
        return (
          <DocumentCard
            key={document.id}
            href={`/departments/${departmentId}/documents/${document.id}`}
            kind={document.kind === "docx" ? "DOC" : "PDF"}
            title={document.name}
            version={`V${current?.number ?? latest.number}`}
            facts={facts(document)}
            status={<StatusPill status={status.pill} label={status.label} live={isWorking(latest.status)} dotOnly />}
            // The current version's file as it was uploaded; none until a version is ready.
            download={
              current
                ? { href: `/api/v1/documents/${document.id}/versions/${current.id}/original`, label: "Download original" }
                : undefined
            }
          />
        );
      })}
    </DocumentGrid>
  );
}
