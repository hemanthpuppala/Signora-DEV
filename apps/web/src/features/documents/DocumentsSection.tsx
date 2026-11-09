"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { formError } from "@/shared/api/errors";
import { Dropzone, Notice, Section, SmallText, StatusPill, TablePanel } from "@/shared/ui";

import { handOff, useDocuments } from "./api";
import { VERSION_STATUS } from "./status";
import { useDocumentLimits } from "./limits";

/**
 * The department page's documents (Phase 4 LLD §6.1, prototype 10). People with edit access also
 * get a dropzone: a dropped file opens the upload page, already uploading.
 */
export function DocumentsSection({ departmentId, canEdit }: { departmentId: string; canEdit: boolean }) {
  const router = useRouter();
  const documents = useDocuments(departmentId);
  const limits = useDocumentLimits();
  const uploadPage = `/departments/${departmentId}/upload`;
  const dropzone = canEdit ? (
    <Dropzone
      title="Drop a PDF or Word file"
      hint={limits.hint}
      accept=".pdf,.docx"
      onFile={(file) => {
        handOff(departmentId, [file]);
        router.push(uploadPage);
      }}
    />
  ) : null;

  if (documents.isError) {
    return (
      <Section title="Documents">
        <Notice tone="warning">{formError(documents.error)}</Notice>
      </Section>
    );
  }
  const rows = documents.data;
  if (!rows) return null;
  return (
    <Section title="Documents">
      {rows.length === 0 && !canEdit ? <SmallText>No documents yet.</SmallText> : null}
      {rows.length > 0 ? (
        <TablePanel label="Documents list">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Version</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((document) => {
                const latest = document.latest_version;
                const status = VERSION_STATUS[latest.status];
                return (
                  <tr key={document.id}>
                    <td>
                      <Link href={`/departments/${departmentId}/documents/${document.id}`}>
                        <b>{document.name}</b>
                      </Link>
                      {document.kind && document.page_count !== null ? (
                        <SmallText>
                          {[
                            document.kind === "docx" ? "Word → PDF" : "PDF",
                            `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`,
                            latest.status === "ready" && latest.field_count !== null
                              ? `${latest.field_count} ${latest.field_count === 1 ? "field" : "fields"}`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </SmallText>
                      ) : null}
                    </td>
                    <td>{`v${document.current_version?.number ?? latest.number}`}</td>
                    <td>
                      <StatusPill status={status.pill} label={status.label} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TablePanel>
      ) : null}
      {dropzone}
    </Section>
  );
}
