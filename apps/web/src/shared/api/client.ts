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
  // Proxies answer 502/504 with HTML when the API is unreachable: no answer from the API.
  if (!isProblem(error)) throw new NetworkError(`HTTP ${response.status}`);
  const retryAfter = Number(response.headers.get("Retry-After"));
  throw new ApiError(error, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null);
}
