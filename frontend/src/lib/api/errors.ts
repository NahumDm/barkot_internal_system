/**
 * The single failure type every API call rejects with (spec §20.2, roadmap B1).
 *
 * The API answers every failure with `{ error: { code, message, details? } }`
 * (see `backend/apps/core/exceptions.py`), so there is exactly one shape to
 * handle. Callers branch on `code`; `message` is written for a person to read
 * and must never be parsed.
 *
 * `ApiError` deliberately also covers responses that are *not* that envelope: a
 * proxy 502 page, or the HTML that the browsable API serves for an
 * unauthenticated `/api/docs/` request (found during A9). Those must still
 * surface as a catchable, typed error rather than a `SyntaxError` thrown from
 * deep inside `JSON.parse`, or every caller grows its own try/catch to survive
 * an outage.
 */

/** Envelope codes the client is allowed to branch on. */
export const ErrorCode = {
  Validation: "validation_error",
  NotAuthenticated: "not_authenticated",
  PermissionDenied: "permission_denied",
  NotFound: "not_found",
  Throttled: "throttled",
  ServerError: "server_error",
  /** The response was not the error envelope the API promises. */
  Malformed: "malformed_response",
} as const;

export type KnownErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

/** `details` maps a field name to its messages; `non_field_errors` holds the rest. */
export type ErrorDetails = Record<string, string[]>;

export interface ErrorBody {
  code: string;
  message: string;
  details?: ErrorDetails | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorDetails | null;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? null;
  }
}

/** True when the failure was a field-level rejection, so a form can highlight inputs. */
export function isValidationError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === ErrorCode.Validation;
}

/** True when the session is missing, expired, or was ended by the server. */
export function isNotAuthenticated(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === ErrorCode.NotAuthenticated;
}
