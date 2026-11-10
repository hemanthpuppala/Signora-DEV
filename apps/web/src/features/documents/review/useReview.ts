"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";

import { documentKey, type Version } from "../api";
import type { Tool } from "./AddField";
import type { VersionFields } from "../fields";
import {
  apply,
  begin,
  fromView,
  redo,
  toFieldSet,
  undo,
  unsaved,
  type Draft,
  type Edit,
  type FieldSet,
  type History,
  type PageSize,
} from "./editor";

type Revised = { version_id: string; number: number; revision: number };
export type SaveProblem = { message: string; items: { fieldId: string | null; message: string }[]; stale: boolean };

/** "fields[3].places[0].rect" → the fourth field of the draft that was sent (the body lists its
 * fields in order). Read against that draft, never the one edited since: a field deleted after the
 * refusal would shift every later error onto the wrong field. */
export function problemOf(error: unknown, draft: Draft): SaveProblem | null {
  if (!error) return null;
  if (error instanceof ApiError && error.code === "fields-changed") {
    return { message: error.problem.title, items: [], stale: true };
  }
  if (error instanceof ApiError && error.problem.errors?.length) {
    const items = error.problem.errors.map((item) => {
      const index = /^fields\[(\d+)\]/.exec(item.field)?.[1];
      const field = index === undefined ? undefined : draft.fields[Number(index)];
      const party = /^parties\[(\d+)\]/.exec(item.field)?.[1];
      const who = party === undefined ? undefined : draft.parties[Number(party)];
      const name = field?.label || who?.label;
      return { fieldId: field?.id ?? null, message: name ? `${name}: ${item.message}` : item.message };
    });
    return { message: "Some changes can't be saved yet", items, stale: false };
  }
  if (error instanceof ApiError) return { message: error.problem.title, items: [], stale: false };
  return { message: "Connection lost. Save again when you are back online", items: [], stale: false };
}

/** The server's words for a save refused because the fields moved on (review.errors.FieldsChanged). */
const SAVED_ELSEWHERE = "Someone else saved these fields since you opened them. Reload to see their changes";

/** Unsaved edits and what they were made on: the version, and the revision and state loaded then. */
type Held = { versionId: string; revision: number; status: string; history: History };

/**
 * The review of one version (Phase 6 LLD §1.2, §1.6, §7): the editor's history over the fields as
 * last loaded, Save (in place for a version in review; the next version for an approved one) and
 * Approve.
 *
 * Optimistic concurrency (§1.6), kept on this side too. Unsaved edits belong to the revision they
 * were made on and are never dropped unasked: when the fields are saved elsewhere meanwhile, the
 * edits stay, the person is told, and Reload (their choice) takes the newer fields. With nothing
 * unsaved, the newer fields are simply shown. While a save is on its way nothing more is taken:
 * the server may settle what it stores, so an edit made meanwhile has nothing sound to stand on.
 */
export function useReview({
  documentId,
  version,
  view,
  canEdit,
  onRevised,
}: {
  documentId: string;
  version: Version;
  view: VersionFields;
  canEdit: boolean;
  onRevised: (versionId: string) => void;
}) {
  const queryClient = useQueryClient();
  const loaded = useMemo(() => fromView(view), [view]);
  const [state, setState] = useState<Held | null>(null);
  const mine = state?.versionId === version.id ? state : null;
  const moved = mine !== null && (mine.revision !== view.revision || mine.status !== view.status);
  const held = mine !== null && (!moved || unsaved(mine.history) > 0) ? mine : null;
  const history = held ? held.history : begin(loaded);
  const savedElsewhere = held !== null && moved; // unsaved edits on fields that have since moved on
  const hold = (next: History): Held =>
    held ? { ...held, history: next } : { versionId: version.id, revision: view.revision, status: view.status, history: next };
  const [editingApproved, setEditingApproved] = useState<string | null>(null);
  // The draft as it was last sent: a refused save names its fields by their place in that body.
  const [sent, setSent] = useState<Draft | null>(null);

  const approved = version.status === "approved";
  const inReview = version.status === "ready" && view.status === "ready";
  const editing = canEdit && (inReview || (approved && editingApproved === version.id));
  const changes = unsaved(history);

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: ["fields", version.id] });
    await queryClient.invalidateQueries({ queryKey: documentKey(documentId) });
  };

  const path = { document_id: documentId, version_id: version.id };
  const saveInPlace = useMutation({
    mutationFn: (body: FieldSet) =>
      unwrap(api.PUT("/api/v1/documents/{document_id}/versions/{version_id}/fields", { params: { path }, body })),
    onSuccess: async (_saved, body) => {
      // What was sent is what is saved: shown with nothing unsaved until the stored fields load.
      setState((current) => (current && current.revision === body.revision ? { ...current, history: begin(current.history.present) } : current));
      await reload();
      setState(null);
    },
  });
  const revise = useIdempotentAction<FieldSet, Revised>(
    `revise:${version.id}`,
    (body, key) =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/versions/{version_id}/revisions", {
          params: { path },
          body,
          headers: { "Idempotency-Key": key },
        }),
      ),
    { persistInput: false },
  );
  const revised = revise.state.status === "success" ? revise.state.data : null;
  useEffect(() => {
    if (!revised) return;
    // The page then shows the new version; its review starts afresh (the layout is keyed by version).
    void queryClient.invalidateQueries({ queryKey: documentKey(documentId) }).then(() => onRevised(revised.version_id));
  }, [revised, queryClient, documentId, onRevised]);

  const approve = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/documents/{document_id}/versions/{version_id}/approve", {
          params: { path },
          // The kinds of warning seen, each once (ten warnings of three kinds are three codes).
          body: { revision: view.revision, accepted: [...new Set(view.warnings.map((warning) => warning.code))] },
        }),
      ),
    onSuccess: reload,
  });

  const saving = saveInPlace.isPending || revise.isPending;
  const edit: Edit = (change: (draft: Draft) => Draft, merge?: string) => {
    if (saving) return; // nothing more is taken while a save is on its way
    setState(hold(apply(history, change, merge)));
  };
  const save = () => {
    if (savedElsewhere) return; // the server would refuse it: the notice already says why
    const body = toFieldSet(history.present, held?.revision ?? view.revision);
    setSent(history.present);
    if (approved) revise.run(body);
    else saveInPlace.mutate(body);
  };
  const discard = () => {
    setState(null);
    saveInPlace.reset();
    revise.reset();
  };
  const saveError = approved ? revise.state.error : saveInPlace.error;

  return {
    draft: history.present,
    editing,
    approved,
    inReview,
    changes,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    edit,
    undo: () => setState(hold(undo(history))),
    redo: () => setState(hold(redo(history))),
    discard,
    save,
    saving,
    problem: savedElsewhere ? { message: SAVED_ELSEWHERE, items: [], stale: true } : problemOf(saveError, sent ?? history.present),
    startEditing: () => setEditingApproved(version.id),
    stopEditing: () => {
      discard();
      setEditingApproved(null);
    },
    reload: async () => {
      discard();
      await reload();
    },
    approve,
    canApprove: canEdit && inReview,
  };
}

export type Review = ReturnType<typeof useReview>;

/** What the panel needs to edit (Phase 6 §3, §4): the review and the page's facts. */
export type PanelEditing = {
  review: Review;
  pages: readonly PageSize[];
  allowed: VersionFields["allowed"];
  shared: VersionFields["shared"];
  onAddPlace: (fieldId: string) => void;
  onDeleteField: (fieldId: string) => void;
  canDraw: boolean;
  /** Placing a new field or place (§5, §7.1): what the next press on a page makes. */
  tool: Tool | null;
  startPlacing: (tool: Tool) => void;
  cancelPlacing: () => void;
};
