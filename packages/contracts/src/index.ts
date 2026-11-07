/**
 * Public types of the Signora API contract.
 *
 * `schema.d.ts` is generated from `openapi.json` by `make contracts` (single source of truth: the
 * FastAPI application). Never edit generated files; change the API and regenerate instead.
 */
export type { components, operations, paths } from "./schema";

import type { components } from "./schema";

/** RFC 9457 problem details returned by every API error. */
export type ProblemDetails = components["schemas"]["ProblemDetails"];
