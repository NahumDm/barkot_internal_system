/**
 * The typed HTTP client every API call goes through (spec §20.2, roadmap B1).
 *
 * Three decisions in here are load-bearing, and each one exists because the
 * obvious alternative is wrong.
 *
 * **The CSRF token is read from the cookie at send time, never cached.**
 * `/auth/csrf/` also returns the token in its body, and `CsrfResponseSerializer`
 * documents that as a way for a client to keep it in memory. But Django calls
 * `rotate_token()` inside `login()` and `logout()`, so the token a client cached
 * before signing in is stale the moment it does: every post-login write would
 * come back 403. The browser's copy of the cookie is the one thing that Django
 * itself updates, so that is what gets read - on every unsafe request.
 *
 * **Unsafe requests always send a JSON body, even an empty one.** Django's CSRF
 * check reads the body looking for a form token, so a request sent as
 * `multipart/form-data` is rejected with 415 before it is ever authorised. A
 * bodyless `POST` (logout) therefore goes out as `{}` with an explicit
 * `Content-Type: application/json`.
 *
 * **Nothing is persisted.** The session lives in an HttpOnly cookie that this
 * module cannot read, and the CSRF token lives in a cookie Django rewrites. So
 * there is no token to store, which is why `localStorage` stays empty across a
 * whole login session - asserted in `tests/api-client.test.ts`.
 */

import { ApiError, ErrorCode, type ErrorBody, type ErrorDetails } from "./errors";

const CSRF_COOKIE = "csrftoken";
const CSRF_HEADER = "X-CSRFToken";
const IDEMPOTENCY_HEADER = "Idempotency-Key";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

const RAW_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

/**\n * Same-origin in production (Nginx serves `/api/v1/`) and in development\n * (next.config.ts dev proxy forwards `/api/v1/` to the Django dev server).\n * The browser never makes cross-origin API requests, so no CORS headers\n * are required and the CSRF/Session cookies work identically in dev and prod.\n */
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, "");

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: HttpMethod;
  /** Serialised as JSON. Defaults to `{}` on unsafe requests. */
  body?: unknown;
  query?: Record<string, QueryValue>;
  /** Passed through as `Idempotency-Key` (spec §10.2). */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /**
   * Milliseconds to wait for a response before aborting. Off by default so a
   * slow report query is not killed by a deadline meant for interactivity; the
   * session check and logout opt in. A request that hits the deadline rejects
   * with an `ApiError` whose code is `request_timeout`, so callers can tell a
   * timed-out check from a refusal to authenticate - they need very different
   * handling.
   */
  timeoutMs?: number;
}

type JsonResult = { ok: true; value: unknown } | { ok: false; contentType: string | null };

/** Read one cookie by name, or null when it is absent or there is no document. */
export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;

  for (const part of document.cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() !== name) continue;
    return decodeURIComponent(part.slice(separator + 1).trim());
  }
  return null;
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  if (!query) return `${API_BASE_URL}${suffix}`;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }

  const encoded = params.toString();
  return encoded ? `${API_BASE_URL}${suffix}?${encoded}` : `${API_BASE_URL}${suffix}`;
}

/**
 * Parse a response body without ever throwing.
 *
 * A failed JSON parse is data, not a bug: it means the response was HTML or
 * plain text, and the caller needs to turn that into an `ApiError` rather than
 * catch a parser exception.
 */
async function readJson(response: Response): Promise<JsonResult> {
  if (response.status === 204) return { ok: true, value: undefined };

  const text = await response.text();
  if (!text) return { ok: true, value: undefined };

  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, contentType: response.headers.get("content-type") };
  }
}

/** Pull `{ error: { code, message, details } }` out of a parsed body, or null. */
function asErrorBody(value: unknown): ErrorBody | null {
  if (typeof value !== "object" || value === null) return null;

  const error = (value as { error?: unknown }).error;
  if (typeof error !== "object" || error === null) return null;

  const { code, message, details } = error as Record<string, unknown>;
  if (typeof code !== "string" || typeof message !== "string") return null;

  return {
    code,
    message,
    details: typeof details === "object" && details !== null ? (details as ErrorDetails) : null,
  };
}

/** Best available code for a status when the body was not the envelope. */
const FALLBACK_CODES: Record<number, string> = {
  400: ErrorCode.Validation,
  401: ErrorCode.NotAuthenticated,
  403: ErrorCode.PermissionDenied,
  404: ErrorCode.NotFound,
  405: "method_not_allowed",
  415: "unsupported_media_type",
  429: ErrorCode.Throttled,
};

const MALFORMED_MESSAGE =
  "The server sent a response the app could not read. Try again in a moment.";

function malformed(status: number): ApiError {
  const code =
    FALLBACK_CODES[status] ?? (status >= 500 ? ErrorCode.ServerError : ErrorCode.Malformed);
  return new ApiError(status, { code, message: MALFORMED_MESSAGE, details: null });
}

/**
 * Ask the API for a CSRF token and return it.
 *
 * The cookie is preferred over the response body because Django rewrites the
 * cookie on every rotation, so it is always the more current of the two. The
 * body is only the fallback for the narrow window where the cookie has not
 * landed yet.
 */
export async function fetchCsrfToken(): Promise<string> {
  const response = await fetch(buildUrl("/auth/csrf/"), {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "include",
  });

  const parsed = await readJson(response);
  if (!response.ok) {
    const body = parsed.ok ? asErrorBody(parsed.value) : null;
    throw body ? new ApiError(response.status, body) : malformed(response.status);
  }

  const fromBody = parsed.ok ? (parsed.value as { token?: unknown }).token : undefined;
  const token = readCookie(CSRF_COOKIE) ?? (typeof fromBody === "string" ? fromBody : undefined);

  if (typeof token !== "string" || !token) {
    throw malformed(response.status);
  }
  return token;
}

/** The current CSRF token, bootstrapping one if the cookie is not set yet. */
async function csrfToken(): Promise<string> {
  return readCookie(CSRF_COOKIE) ?? fetchCsrfToken();
}

const TIMEOUT_MESSAGE = "The request took too long to answer. Try again in a moment.";

function timeoutError(): ApiError {
  return new ApiError(0, { code: ErrorCode.Timeout, message: TIMEOUT_MESSAGE, details: null });
}

/**
 * Run a `fetch` with an optional deadline.
 *
 * A plain fetch has exactly one failure mode that matters for the session
 * check: the connection is accepted but never answered, and the request hangs
 * until the browser's network stack gives up minutes later. That is the whole
 * "Checking your session…" stall: nothing rejects, so the guard has nothing to
 * react to and offers no way out. Aborting after `timeoutMs` converts the stall
 * into a typed, catchable `ApiError` at the cost of one timer.
 *
 * A caller-supplied `signal` still works: aborting it cancels the request too,
 * and that abort is distinguishable from a deadline - an external abort
 * propagates as the browser's `AbortError` rather than as a timeout.
 */
async function fetchWithDeadline(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs?: number,
): Promise<Response> {
  if (!timeoutMs || timeoutMs <= 0) return fetch(input, init);

  const controller = new AbortController();
  if (init.signal) {
    if (init.signal.aborted) {
      controller.abort();
    } else {
      init.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<Response>((_resolve, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(timeoutError());
    }, timeoutMs);
  });

  try {
    return await Promise.race([
      fetch(input, { ...init, signal: controller.signal }),
      deadline,
    ]);
  } catch (error) {
    // The underlying fetch may reject with an AbortError a tick after the
    // deadline did; both mean the deadline passed, so whatever settles the race
    // first, the caller sees the typed timeout.
    if (timedOut) throw timeoutError();
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Perform an API request and return its parsed body.
 *
 * Rejects with `ApiError` on any non-2xx response. A 2xx response that is not
 * JSON also rejects, rather than resolving to `undefined`: silently handing
 * back nothing for a body the caller expected would turn a broken endpoint into
 * a blank screen with no signal.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const unsafe = !SAFE_METHODS.has(method);
  const headers = new Headers({ Accept: "application/json" });
  let body: string | undefined;

  if (unsafe) {
    body = JSON.stringify(options.body ?? {});
    headers.set("Content-Type", "application/json");
    headers.set(CSRF_HEADER, await csrfToken());
  }
  if (options.idempotencyKey) {
    headers.set(IDEMPOTENCY_HEADER, options.idempotencyKey);
  }

  const init: RequestInit = {
    method,
    headers,
    body,
    credentials: "include",
    ...(options.signal ? { signal: options.signal } : {}),
  };

  const response = await fetchWithDeadline(buildUrl(path, options.query), init, options.timeoutMs);

  const parsed = await readJson(response);

  if (!response.ok) {
    const body = parsed.ok ? asErrorBody(parsed.value) : null;
    throw body ? new ApiError(response.status, body) : malformed(response.status);
  }
  if (!parsed.ok) throw malformed(response.status);

  return parsed.value as T;
}

export function get<T>(
  path: string,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: "GET" });
}

export function post<T>(
  path: string,
  body?: unknown,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: "POST", body });
}

export function patch<T>(
  path: string,
  body?: unknown,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: "PATCH", body });
}

export function put<T>(
  path: string,
  body?: unknown,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: "PUT", body });
}

export function del<T>(
  path: string,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<T> {
  return apiFetch<T>(path, { ...options, method: "DELETE" });
}
