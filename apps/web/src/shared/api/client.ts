import type { paths, ProblemDetails } from "@signora/contracts";
import createClient from "openapi-fetch";

import { readCookie } from "@/shared/lib/cookies";

import { ApiError, NetworkError } from "./errors";

/**
 * Typed API client. Same origin: Caddy routes /api/* to the API in production; `next dev` rewrites
 * it in development. Types come from the generated contract, so API drift fails the build.
 */
export const api = createClient<paths>({
  // The page's own origin (an absolute base works for both browser and Node Request; on the
  // server, where client components only render, no request is made).
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  // Looked up per call (not captured at import), so tests can stub fetch.
  fetch: (request) => globalThis.fetch(request),
});

/** Signed double-submit CSRF token (Phase 2 LLD §4.3): readable cookie echoed in a header. */
export const CSRF_COOKIE = "__Host-signora_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

api.use({
  onRequest({ request }) {
    if (!UNSAFE_METHODS.has(request.method)) return undefined;
    const token = readCookie(CSRF_COOKIE);
    if (token) request.headers.set(CSRF_HEADER, token);
    return request;
  },
});

type ClientResult<T> = { data?: T; error?: unknown; response: Response };

function isProblem(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "status" in value &&
    "title" in value
  );
}

/**
 * Statuses a proxy (Caddy, Funnel) answers when the API itself never did: unreachable, starting,
 * or too slow. Only these, without a problem body, mean "no answer" and are safe to retry.
 */
const NO_ANSWER_STATUSES = new Set([502, 503, 504]);

/** An answer that is not a success, as fetch or XMLHttpRequest delivers it. */
export type ErrorAnswer = {
  status: number;
  statusText: string;
  url: string;
  body: unknown;
  header: (name: string) => string | null;
};

/** A definite answer that carries no problem document (e.g. Caddy's empty 413 for a large upload). */
function problemFromBareStatus(answer: ErrorAnswer): ProblemDetails {
  return {
    type: "about:blank",
    title: answer.statusText || `HTTP ${answer.status}`,
    status: answer.status,
    code: `http-${answer.status}`,
    instance: new URL(answer.url || "/", "http://unknown").pathname,
    request_id: answer.header("X-Request-ID"),
  };
}

/**
 * The error for an answer that is not a success, whatever sent the request: ``ApiError`` when the
 * server answered (with its Retry-After), ``NetworkError`` when only a proxy did.
 */
export function answerError(answer: ErrorAnswer): ApiError | NetworkError {
  const retryAfter = Number(answer.header("Retry-After"));
  const retryAfterSeconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null;
  if (isProblem(answer.body)) return new ApiError(answer.body, retryAfterSeconds);
  // A proxy's own 502/503/504: the API never answered, so the action may not have happened.
  if (NO_ANSWER_STATUSES.has(answer.status)) return new NetworkError(`HTTP ${answer.status}`);
  // Any other status is a definite answer: retrying the same request would get it again.
  return new ApiError(problemFromBareStatus(answer), retryAfterSeconds);
}

/**
 * Await an openapi-fetch call and return its data, or throw ``ApiError`` (the server answered) or
 * ``NetworkError`` (no answer: the action may or may not have happened).
 */
export async function unwrap<T>(call: Promise<ClientResult<T>>): Promise<T> {
  let result: ClientResult<T>;
  try {
    result = await call;
  } catch (error) {
    throw new NetworkError(error);
  }
  const { data, error, response } = result;
  if (response.ok) return data as T;
  throw answerError({
    status: response.status,
    statusText: response.statusText,
    url: response.url,
    body: error,
    header: (name) => response.headers.get(name),
  });
}
