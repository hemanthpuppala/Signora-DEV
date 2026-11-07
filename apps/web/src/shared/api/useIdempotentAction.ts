"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, NetworkError } from "./errors";

/**
 * The single helper every mutating action uses (backbone LLD §3.6, §8.5):
 *
 * 1. One idempotency key per user action, kept in sessionStorage until a definite answer arrives,
 *    so it survives a page refresh; every retry reuses it.
 * 2. While pending the caller shows "Sending…" and locks its inputs (``isPending``); on a network
 *    error the state is "retrying" ("Connection lost — retrying…"), never "failed".
 * 3. Retries automatically with the same key on the browser ``online`` event and on backoff
 *    (1 s, 2 s, 4 s … max 30 s); ``409 request-in-progress`` is retried after ``Retry-After``.
 * 4. Pressing again while pending resends the same key instead of starting a new action.
 */

export type ActionStatus = "idle" | "pending" | "retrying" | "success" | "error";

export type ActionState<TResult> = {
  status: ActionStatus;
  data: TResult | null;
  error: ApiError | null;
};

export type Perform<TInput, TResult> = (input: TInput, idempotencyKey: string) => Promise<TResult>;

type Pending<TInput> = { key: string; input: TInput };

const STORAGE_PREFIX = "signora:action:";
const BASE_DELAY_MS = 1_000;
export const MAX_DELAY_MS = 30_000;

function backoffMs(attempt: number): number {
  return Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
}

function readPending<TInput>(storageKey: string): Pending<TInput> | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_PREFIX + storageKey);
    return raw ? (JSON.parse(raw) as Pending<TInput>) : null;
  } catch {
    return null;
  }
}

function writePending<TInput>(storageKey: string, pending: Pending<TInput> | null): void {
  try {
    if (pending) window.sessionStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(pending));
    else window.sessionStorage.removeItem(STORAGE_PREFIX + storageKey);
  } catch {
    // Storage unavailable (private mode): the key still lives in memory for this page.
  }
}

export type IdempotentActionOptions = {
  /**
   * Keep the pending action in ``sessionStorage`` so it resumes after a refresh (default). Set to
   * ``false`` when the input holds a secret such as a password: the key then lives in memory only
   * and a refresh simply drops the attempt (the user submits again).
   */
  persistInput?: boolean;
};

export function useIdempotentAction<TInput, TResult>(
  storageKey: string,
  perform: Perform<TInput, TResult>,
  { persistInput = true }: IdempotentActionOptions = {},
) {
  const [state, setState] = useState<ActionState<TResult>>({ status: "idle", data: null, error: null });
  const pending = useRef<Pending<TInput> | null>(null);
  const attempt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef(false);
  // After unmount nothing is scheduled and no state is set; a stored action resumes on remount.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const performRef = useRef(perform);
  useEffect(() => {
    performRef.current = perform;
  }, [perform]);

  const store = useCallback(
    (value: Pending<TInput> | null) => {
      if (persistInput) writePending(storageKey, value);
    },
    [persistInput, storageKey],
  );

  // Retries are scheduled through this ref so they always call the latest ``send``.
  const sendRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const send = useCallback(async () => {
    const current = pending.current;
    if (!current || inFlight.current || !mounted.current) return;
    clearTimer();
    inFlight.current = true;
    // The answer belongs to ``current`` only while it is still this hook's action: a reset, a new
    // ``run`` or an unmount while the request was in flight makes it stale, and it is then ignored.
    const stillCurrent = () => mounted.current && pending.current?.key === current.key;
    try {
      const data = await performRef.current(current.input, current.key);
      if (!stillCurrent()) return;
      pending.current = null;
      store(null);
      attempt.current = 0;
      setState({ status: "success", data, error: null });
    } catch (error) {
      if (!stillCurrent()) return;
      if (error instanceof ApiError && error.code === "request-in-progress") {
        setState((s) => ({ ...s, status: "pending" }));
        const delay = (error.retryAfterSeconds ?? 1) * 1_000;
        timer.current = setTimeout(() => void sendRef.current(), delay);
      } else if (error instanceof ApiError) {
        pending.current = null;
        store(null);
        attempt.current = 0;
        setState({ status: "error", data: null, error });
      } else {
        // NetworkError or anything without an answer: the server may have acted; retry same key.
        if (!(error instanceof NetworkError)) console.error(error);
        setState((s) => ({ ...s, status: "retrying" }));
        timer.current = setTimeout(() => void sendRef.current(), backoffMs(attempt.current));
        attempt.current += 1;
      }
    } finally {
      inFlight.current = false;
      // A new action started while this request was in flight (its own send returned early on the
      // in-flight guard): send it now.
      if (mounted.current && pending.current && pending.current.key !== current.key) {
        void sendRef.current();
      }
    }
  }, [store]);

  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const run = useCallback(
    (input: TInput) => {
      if (pending.current) {
        // Pressed again while pending: resend the same key now (no new action).
        void send();
        return;
      }
      pending.current = { key: crypto.randomUUID(), input };
      store(pending.current);
      attempt.current = 0;
      setState({ status: "pending", data: null, error: null });
      void send();
    },
    [send, store],
  );

  const reset = useCallback(() => {
    clearTimer();
    pending.current = null;
    store(null);
    setState({ status: "idle", data: null, error: null });
  }, [store]);

  // Resume an action that was pending when the page was refreshed; retry on reconnect.
  useEffect(() => {
    const stored = persistInput ? readPending<TInput>(storageKey) : null;
    if (stored && !pending.current) {
      pending.current = stored;
      setState({ status: "retrying", data: null, error: null });
      void send();
    }
    const onOnline = () => {
      if (pending.current) {
        attempt.current = 0;
        void send();
      }
    };
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("online", onOnline);
      clearTimer();
    };
  }, [send, storageKey, persistInput]);

  const isPending = state.status === "pending" || state.status === "retrying";
  return { run, reset, state, isPending };
}
