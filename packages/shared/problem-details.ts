// =============================================================================
// Aether Shared — Canonical API Error Contract type (RFC 7807-compatible)
//
// This is the canonical TYPE for the Problem-Details shape the backend emits
// from every JSON failure path (see `shared/common/common.py`). It is
// consumed type-only across the frontends and SDKs.
//
// The runtime PARSER (`parseProblemDetails`) lives in `@aether/ui`
// (`frontend/shared/src/problem-details.ts`) — this package compiles to
// CommonJS and its runtime values are not resolvable by the app rollup
// builds, but its types always are.
// =============================================================================

export interface ProblemDetails {
  /** URI identifying the error category (stable identifier, may not resolve). */
  type: string;
  /** Short human-readable title of the error category. */
  title: string;
  /** HTTP status code. */
  status: number;
  /** Stable machine-readable UPPER_SNAKE code. */
  code: string;
  /** Human-readable explanation of this occurrence. */
  detail: string;
  /** Legacy alias of `detail` kept for older clients. */
  message?: string;
  request_id?: string;
  correlation_id?: string;
  /** Whether retrying the same request may succeed. */
  retryable?: boolean;
  /** Optional field-level errors. */
  errors?: unknown[];
  /** Problem-Details extensions (retry_after_seconds, upgrade_url, ...). */
  [extension: string]: unknown;
}
