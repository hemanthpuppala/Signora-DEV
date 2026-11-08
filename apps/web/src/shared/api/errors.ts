import type { ProblemDetails } from "@signora/contracts";

/** The server answered with an RFC 9457 problem (a definite answer). */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails;
  /** Seconds from the Retry-After header, when present. */
  readonly retryAfterSeconds: number | null;

  constructor(problem: ProblemDetails, retryAfterSeconds: number | null = null) {
    super(problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  get code(): string {
    return this.problem.code;
  }

  get detail(): string | null {
    return this.problem.detail ?? null;
  }
}

/** No answer arrived (offline, connection reset, proxy timeout); the server may have acted. */
export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super("Connection lost", { cause });
    this.name = "NetworkError";
  }
}

const FALLBACK_TITLES: Record<string, string> = {
  "validation-failed": "Some fields need attention.",
  unauthenticated: "Please sign in again.",
  "permission-denied": "You do not have access to this.",
  "not-found": "This no longer exists.",
  "rate-limited": "Too many attempts. Please wait a moment.",
  "request-in-progress": "Still working on your previous request.",
  "http-413": "This is too large to send.",
};

/** A short, user-facing message; unexpected errors include the request id for support. */
export function userMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) {
      const reference = error.problem.request_id ? ` (reference ${error.problem.request_id})` : "";
      return `Something went wrong on our side${reference}.`;
    }
    return FALLBACK_TITLES[error.code] ?? error.problem.title;
  }
  if (error instanceof NetworkError) return "Connection lost — retrying…";
  return "Something went wrong.";
}

/** Field errors of a validation problem, keyed by field name ("password", "role_id"…). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.problem.errors) return {};
  return Object.fromEntries(error.problem.errors.map((item) => [item.field, item.message]));
}

/** A request error worth showing above a form (field errors are shown on their fields). */
export function formError(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  if (error instanceof ApiError && error.code === "validation-failed") return null;
  if (error instanceof ApiError && error.status === 429) {
    const minutes = error.retryAfterSeconds ? Math.ceil(error.retryAfterSeconds / 60) : null;
    return minutes ? `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.` : "Too many attempts. Please wait a moment.";
  }
  if (error instanceof ApiError && error.detail) return error.detail;
  return userMessage(error);
}
