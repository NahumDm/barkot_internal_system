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
  /** The session was valid but had idled past the timeout, so it was ended. */
  SessionExpired: "session_expired",
  /** The account is on a temporary password and must set a new one. Detected
   * from `is_temporary_password` on the user, not from this code: `/auth/me/`
   * stays callable while a change is pending and answers with the flag. */
  PasswordChangeRequired: "password_change_required",
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

/**
 * True when the user is not signed in, for any of the reasons the API uses.
 *
 * Both codes mean the same thing to a person at the keyboard, and collapsing
 * them is not a simplification: `not_authenticated` is a 401 for a request that
 * carried no usable session, while `session_expired` is a 403 raised only after
 * a session that did exist idled past the limit — and the server ends it on the
 * way out, so the retry that follows is a 401. A client that recognises only the
 * first one reports an expired session as a server outage, and tells a user to
 * wait for a server that is perfectly healthy.
 */
export function isSessionEnded(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.code === ErrorCode.NotAuthenticated || error.code === ErrorCode.SessionExpired)
  );
}

/** True when the failure was a permission denied error. */
export function isPermissionDenied(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === ErrorCode.PermissionDenied;
}

/** True when the failure was a not found error. */
export function isNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === ErrorCode.NotFound;
}

/** True when the failure was an inconsistent totals error. */
export function isInconsistentTotals(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.code === ErrorCode.Validation &&
    (error.details?.["non_field_errors"]?.includes("totals") ?? false)
  );
}

/** True when the failure was an insufficient stock error. */
export function isInsufficientStock(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.code === ErrorCode.Validation &&
    (error.details?.["non_field_errors"]?.includes("stock") ?? false)
  );
}

/** True when the failure was an invalid state transition error. */
export function isInvalidStateTransition(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.code === ErrorCode.Validation &&
    (error.details?.["non_field_errors"]?.includes("state") ?? false)
  );
}
