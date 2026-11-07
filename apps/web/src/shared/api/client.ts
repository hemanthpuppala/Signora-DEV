import type { paths, ProblemDetails } from "@signora/contracts";
import createClient from "openapi-fetch";

import { ApiError, NetworkError } from "./errors";

/**
 * Typed API client. Same origin: Caddy routes /api/* to the API in production; `next dev` rewrites
 * it in development. Types come from the generated contract, so API drift fails the build.
 */
export const api = createClient<paths>({ baseUrl: "" });

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

/** A definite answer that carries no problem document (e.g. Caddy's empty 413 for a large upload). */
function problemFromBareStatus(response: Response): ProblemDetails {
  return {
    type: "about:blank",
    title: response.statusText || `HTTP ${response.status}`,
    status: response.status,
    code: `http-${response.status}`,
    instance: new URL(response.url || "/", "http://unknown").pathname,
    request_id: response.headers.get("X-Request-ID"),
  };
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
  const retryAfter = Number(response.headers.get("Retry-After"));
  const retryAfterSeconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null;
  if (isProblem(error)) throw new ApiError(error, retryAfterSeconds);
  // A proxy's own 502/503/504: the API never answered, so the action may not have happened.
  if (NO_ANSWER_STATUSES.has(response.status)) throw new NetworkError(`HTTP ${response.status}`);
  // Any other status is a definite answer: retrying the same request would get it again.
  throw new ApiError(problemFromBareStatus(response), retryAfterSeconds);
}
