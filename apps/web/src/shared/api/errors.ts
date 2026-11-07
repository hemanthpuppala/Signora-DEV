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
