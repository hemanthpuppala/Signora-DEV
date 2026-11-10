"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  Button,
  Dialog,
  PdfViewer,
  DetailsPane,
  Section,
  TextButton,
  ViewerLayout,
  ViewerPane,
  type PdfOverlayArgs,
} from "@/shared/ui";

import type { DocumentDetail, Version } from "../api";
import documentStyles from "../document.module.css";
import { FieldBoxes, type Selection } from "../FieldBoxes";
import { HOLDS, type VersionFields } from "../fields";
import { FieldsPanel, type Filter } from "../FieldsPanel";
import { Versions } from "../Versions";
import {
  addField,
  addPlace,
  boxAt,
  clampRect,
  deleteField,
  deletePlace,
  findPlace,
  movePlace,
  newField,
  nextOptionName,
  nudge,
  setRect,
  type Draft,
  type Rect,
} from "./editor";
import { placingMessage, type Tool } from "./AddField";
import { VERSIONS_HELP } from "./help";
import { ReviewActionBar, SaveProblem } from "./ReviewBar";
import { useLeaveGuard } from "./useLeaveGuard";
import { useReview, type PanelEditing } from "./useReview";

/** Before the fields arrive: nothing to show or edit yet. */
const LOADING: VersionFields = {
  status: "loading",
  stage: null,
  fields_from: null,
  roles: [],
  fields: [],
  pending: [],
  flags: {
    no_fields: false,
    addressed_to_ai: false,
    xfa: false,
    already_signed: false,
    repaired: false,
  },
  revision: 0,
  warnings: [],
  allowed: {},
  formats: {},
} as unknown as VersionFields;

/** Whether a media query holds, kept current; ``otherwise`` until it is known (and where there is
 * no matchMedia). */
function useMedia(media: string, otherwise: boolean): boolean {
  const [matches, setMatches] = useState(otherwise);
  useEffect(() => {
    const query = window.matchMedia?.(media);
    if (!query) return undefined;
    const update = () => setMatches(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, [media]);
  return matches;
}
/** The panel sits beside the document from this width (ViewerLayout); under it, below the document. */
const BESIDE = "(min-width: 960px)";
/** A finger is the main pointer: the words say "tap". */
const TOUCH = "(pointer: coarse)";

/** Where keys belong to a control, not the page: text boxes, the shared Select (a combobox and
 * its list, whose arrows pick an option), and dialogs. */
const CONTROLS = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="combobox"], [role="listbox"], dialog';
const typing = (target: EventTarget | null) => target instanceof Element && target.closest(CONTROLS) !== null;

/** A new field's label: "Client signature", or the type alone when nobody is chosen. */
function labelFor(
  draft: Draft,
  holds: keyof typeof HOLDS,
  partyId: string | null,
): string {
  const party = draft.parties.find((p) => p.id === partyId);
  return party ? `${party.label} ${HOLDS[holds].toLowerCase()}` : HOLDS[holds];
}

type Pending = {
  message: string;
  detail: string;
  confirm: string;
  cancel: string;
  run: () => void;
};

/**
 * The shown version with its fields (Phase 6 §7): the viewer with its boxes, the panel beside it,
 * and the versions. Review is this page, no separate one; it changes with the version's state.
 * Unsaved edits are guarded: leaving the page, opening another version, going back to the current
 * one. Keys while editing: Ctrl+Z and Ctrl+Shift+Z undo and redo; with a box chosen the arrows
 * nudge it (Shift: 10 points) and Delete removes it; Escape puts a tool away.
 *
 * On a narrow screen the panel is under the document (§5.1). A box chosen on the page keeps the
 * person there, to move it; its name is pinned over the pages with "Details", which goes to its
 * form. Placing brings the pages into view.
 */
export function ReviewLayout({
  document,
  version,
  view: loaded,
  canEdit,
  top,
  onOpen,
}: {
  document: DocumentDetail;
  version: Version;
  view: VersionFields | undefined;
  canEdit: boolean;
  top: ReactNode;
  onOpen: (versionId: string | null) => void;
}) {
  const view = loaded ?? LOADING;
  const review = useReview({
    documentId: document.id,
    version,
    view,
    canEdit: canEdit && Boolean(loaded),
    onRevised: onOpen,
  });
  const { draft, editing } = review;
  const beside = useMedia(BESIDE, true);
  const touch = useMedia(TOUCH, false);
  const [picked, setPicked] = useState<{
    selection: Selection;
    token: number;
    on: "page" | "list"; // where it was chosen
  } | null>(null);
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [tool, setTool] = useState<Tool | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const leave = useLeaveGuard(review.changes);

  const select = useCallback(
    (selection: Selection, on: "page" | "list" = "list") =>
      setPicked((previous) => ({
        selection,
        token: (previous?.token ?? 0) + 1,
        on,
      })),
    [],
  );
  const selectOnPage = useCallback((selection: Selection) => select(selection, "page"), [select]);
  const selection = picked?.selection ?? null;
  const chosenPlace =
    selection?.kind === "field"
      ? draft.fields.find((f) => f.id === selection.id)?.places[selection.place]
      : undefined;

  /** Do it now, or ask first when it would drop unsaved changes. */
  const guarded = (run: () => void) => {
    if (review.changes === 0) return run();
    setPending({
      message: `Discard ${review.changes} unsaved ${review.changes === 1 ? "change" : "changes"}?`,
      detail: "Your changes to these fields are lost.",
      confirm: "Discard",
      cancel: "Keep editing",
      run: () => {
        review.discard();
        run();
      },
    });
  };
  const askDeleteField = (fieldId: string) => {
    const field = draft.fields.find((f) => f.id === fieldId);
    setPending({
      message: `Delete ${field?.label || "this field"}${field && field.places.length > 1 ? ` and its ${field.places.length} places` : ""}?`,
      detail: "You can undo this until you save.",
      confirm: "Delete field",
      cancel: "Cancel",
      run: () => {
        review.edit((d) => deleteField(d, fieldId));
        setPicked(null);
      },
    });
  };
  const removePlace = (placeId: string) => {
    const found = findPlace(draft, placeId);
    if (!found) return;
    if (found.field.places.length === 1) return askDeleteField(found.field.id);
    review.edit((d) => deletePlace(d, placeId));
    select({
      kind: "field",
      id: found.field.id,
      place: Math.max(0, found.index - 1),
    });
  };

  // Keys while editing (the panel's own inputs keep theirs).
  useEffect(() => {
    if (!editing) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && tool) {
        setTool(null);
        return;
      }
      if (typing(event.target)) return;
      const command = event.ctrlKey || event.metaKey;
      if (command && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) review.redo();
        else review.undo();
        return;
      }
      if (command && event.key.toLowerCase() === "y") {
        event.preventDefault();
        review.redo();
        return;
      }
      if (!chosenPlace || command) return;
      const step = event.shiftKey ? 10 : 1;
      const moves: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      };
      const by = moves[event.key];
      if (by) {
        event.preventDefault();
        review.edit(
          (d) => nudge(d, chosenPlace.id, by[0], by[1], version.pages),
          `nudge:${chosenPlace.id}`,
        );
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removePlace(chosenPlace.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /** A new field from the Add field row, at its box; its row opens with its details. */
  const placeField = (
    made: Extract<Tool, { kind: "field" }>,
    page: number,
    box: Rect,
  ) => {
    const choice = made.holds === "choice";
    const field = {
      ...newField(
        made.holds,
        labelFor(draft, made.holds, made.party_id),
        made.party_id,
        {
          page,
          rect: box,
          option_value: choice ? "Option 1" : null,
          option_text: choice ? "Option 1" : null,
        },
      ),
      filled_by: made.filled_by,
    };
    review.edit((d) => addField(d, field));
    select({ kind: "field", id: field.id, place: 0 }, "page");
  };

  const onDraw = (
    page: number,
    rect: Rect | null,
    at: { x: number; y: number },
  ) => {
    const size = version.pages[page - 1];
    if (!tool || !size) return;
    if (tool.kind === "field") {
      const box = rect
        ? clampRect(rect, size, false)
        : boxAt(tool.holds, at.x, at.y, size);
      placeField(tool, page, box);
    } else {
      const field = draft.fields.find((f) => f.id === tool.fieldId);
      if (!field) return setTool(null);
      const choice = field.holds === "choice";
      const option = nextOptionName(field);
      const box = rect
        ? clampRect(rect, size, false)
        : boxAt(field.holds, at.x, at.y, size);
      review.edit((d) =>
        addPlace(d, field.id, {
          page,
          rect: box,
          option_value: choice ? option : null,
          option_text: choice ? option : null,
        }),
      );
      select({ kind: "field", id: field.id, place: field.places.length }, "page");
    }
    setTool(null);
  };

  const panelEditing: PanelEditing | null = editing
    ? {
        review,
        pages: version.pages,
        allowed: view.allowed,
        formats: view.formats,
        touch,
        onAddPlace: (fieldId) => {
          const field = draft.fields.find((f) => f.id === fieldId);
          if (field) setTool({ kind: "place", fieldId, label: field.label });
        },
        onDeleteField: askDeleteField,
        tool,
        startPlacing: setTool,
        cancelPlacing: () => setTool(null),
      }
    : null;

  const focus = (() => {
    if (!picked || !selection) return null;
    const rect =
      selection.kind === "field"
        ? chosenPlace && { page: chosenPlace.page, rect: chosenPlace.rect }
        : (() => {
            const placement = view.pending.find(
              (found) => found.id === selection.id,
            )?.placements[selection.place];
            return placement && { page: placement.page, rect: placement.rect };
          })();
    if (!rect) return null;
    const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = rect.rect;
    return {
      page: rect.page,
      rect: [x0, y0, x1, y1] as const,
      token: picked.token,
    };
  })();
  // Under the document, a box chosen on the page keeps the person there: its name, and the way to
  // its form.
  const chosenField = selection?.kind === "field" ? draft.fields.find((f) => f.id === selection.id) : undefined;
  const stay = !beside && editing !== null && picked?.on === "page";
  const notice = tool
    ? { message: placingMessage(tool, touch), reveal: true, action: { label: "Cancel", onClick: () => setTool(null) } }
    : stay && chosenField
      ? {
          message: chosenField.label || HOLDS[chosenField.holds],
          action: {
            label: "Details",
            onClick: () => {
              const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
              window.document
                .getElementById(`field-${chosenField.id}`)
                ?.scrollIntoView?.({ block: "start", behavior: still ? "auto" : "smooth" });
            },
          },
        }
      : null;
  const nextNumber = Math.max(...document.versions.map((v) => v.number)) + 1;
  const current = document.current_version;

  return (
    <>
      <ViewerLayout>
        {loaded ? (
          <ReviewActionBar
            review={review}
            version={version}
            nextNumber={nextNumber}
            warnings={view.warnings}
            canEdit={canEdit}
          />
        ) : null}
        <ViewerPane>
          {top}
          {version.id !== current?.id && current ? (
            <div className={documentStyles.caption}>
              <TextButton onClick={() => guarded(() => onOpen(null))}>
                Back to the current version
              </TextButton>
            </div>
          ) : null}
          <PdfViewer
            url={`/api/v1/documents/${document.id}/versions/${version.id}/pdf`}
            pages={version.pages}
            label={`${document.name}, version ${version.number}`}
            focus={focus}
            notice={notice}
            {...(loaded
              ? {
                  renderOverlay: ({ page, scale }: PdfOverlayArgs) => (
                    <FieldBoxes
                      page={page}
                      scale={scale}
                      fields={draft.fields}
                      pending={view.pending}
                      parties={draft.parties}
                      selected={selection}
                      onSelect={selectOnPage}
                      editing={
                        editing
                          ? {
                              drawing: tool !== null,
                              onDraw,
                              onMove: (placeId, page, rect) =>
                                review.edit((d) => movePlace(d, placeId, page, rect, version.pages)),
                              onResize: (placeId, rect) =>
                                review.edit((d) => setRect(d, placeId, rect, version.pages, false)),
                            }
                          : null
                      }
                    />
                  ),
                }
              : {})}
          />
        </ViewerPane>
        <DetailsPane>
          {review.problem ? (
            <SaveProblem
              review={review}
              onShow={(fieldId) =>
                select({ kind: "field", id: fieldId, place: 0 })
              }
            />
          ) : null}
          {loaded ? (
            <FieldsPanel
              view={view}
              draft={draft}
              selected={selection}
              onSelect={select}
              onClear={() => setPicked(null)}
              filter={filter}
              onFilter={setFilter}
              editing={panelEditing}
              follow={!stay}
            />
          ) : null}
            <Section title="Versions" info={VERSIONS_HELP} collapsible>
            <Versions
              document={document}
              viewing={version.id}
              onOpen={(id) => guarded(() => onOpen(id))}
              canEdit={canEdit}
            />
          </Section>
        </DetailsPane>
        {pending ? (
          <Dialog
            title={pending.message}
            onClose={() => setPending(null)}
            actions={
              <>
                <Button
                  variant="destructive"
                  onClick={() => {
                    pending.run();
                    setPending(null);
                  }}
                >
                  {pending.confirm}
                </Button>
                <TextButton onClick={() => setPending(null)}>
                  {pending.cancel}
                </TextButton>
              </>
            }
          >
            {pending.detail}
          </Dialog>
        ) : null}
        {leave.leaving ? (
          <Dialog
            title={`Discard ${review.changes} unsaved ${review.changes === 1 ? "change" : "changes"}?`}
            onClose={leave.stay}
            actions={
              <>
                <Button variant="destructive" onClick={leave.leave}>
                  Discard
                </Button>
                <TextButton onClick={leave.stay}>Keep editing</TextButton>
              </>
            }
          >
            Leaving this page loses your changes to these fields.
          </Dialog>
        ) : null}
      </ViewerLayout>
    </>
  );
}
