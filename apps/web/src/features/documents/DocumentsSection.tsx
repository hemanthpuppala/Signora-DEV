"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { formError } from "@/shared/api/errors";
import { SEARCH_SETTLE_MS, useDebounced } from "@/shared/lib/useDebounced";
import {
  DocumentCard,
  DocumentGrid,
  Dropzone,
  ListControls,
  Notice,
  SearchField,
  Select,
  SmallText,
  StatusPill,
  TextButton,
} from "@/shared/ui";

import { handOff, isWorking, useDocuments, useTemplates, type DocumentSummary, type TemplateSort } from "./api";
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

const SORTS: readonly { value: TemplateSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "updated", label: "Recently updated" },
  { value: "oldest", label: "Oldest first" },
  { value: "name", label: "Name (A–Z)" },
];
const BEST_MATCH = "match"; // what a search is ordered by until another order is chosen

/**
 * A department's Documents tab (Phase 4 LLD §6.1, the prototype's documents screen): each document
 * as a card leading to its page. With no documents yet, people with edit access get a dropzone: a
 * dropped file opens the upload page, already uploading.
 */
export function DocumentsSection({ departmentId, canEdit }: { departmentId: string; canEdit: boolean }) {
  const router = useRouter();
  const documents = useDocuments(departmentId); // every template: whether there are any at all
  const [typed, setTyped] = useState("");
  const query = useDebounced(typed.trim(), SEARCH_SETTLE_MS);
  const [chosen, setChosen] = useState<TemplateSort | null>(null); // none: best match, or newest
  const templates = useTemplates(departmentId, query, chosen);
  const limits = useDocumentLimits();

  if (documents.isError) return <Notice tone="warning">{formError(documents.error)}</Notice>;
  const all = documents.data;
  if (!all) return null;
  if (all.length === 0) {
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
  const list = templates.data ?? [];
  const sorts = query ? [{ value: BEST_MATCH, label: "Best match" }, ...SORTS] : SORTS;
  return (
    <>
      <ListControls
        search={<SearchField label="Search templates" value={typed} onChange={(event) => setTyped(event.target.value)} />}
      >
        <Select
          label="Sort templates"
          labelHidden
          options={sorts}
          value={chosen ?? (query ? BEST_MATCH : "newest")}
          onChange={(value) => setChosen(value === BEST_MATCH ? null : (value as TemplateSort))}
        />
      </ListControls>
      {templates.isError ? <Notice tone="warning">{formError(templates.error)}</Notice> : null}
      {/* While searching, how many match, said once the answer comes (and read aloud). */}
      <div role="status" aria-live="polite">
        {query && templates.isSuccess ? (
          list.length > 0 ? (
            <SmallText>{list.length === 1 ? "1 template matches" : `${list.length} templates match`}</SmallText>
          ) : (
            <SmallText>
              {`No template matches “${query}”. `}
              <TextButton onClick={() => setTyped("")}>Clear search</TextButton>
            </SmallText>
          )
        ) : null}
      </div>
      <TemplateGrid departmentId={departmentId} list={list} />
    </>
  );
}

function TemplateGrid({ departmentId, list }: { departmentId: string; list: readonly DocumentSummary[] }) {
  if (list.length === 0) return null;
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
