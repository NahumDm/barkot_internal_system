/**
 * Contract tests for the API client (roadmap B1).
 *
 * These pin the behaviour that is easy to break by accident and expensive to
 * discover late: the CSRF token being read fresh rather than cached, requests
 * carrying cookies across origins, JSON bodies on writes, and failures arriving
 * as one typed error. The `localStorage` test is the B1 exit gate: session auth
 * must leave no token in the browser for script to reach.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, fetchCsrfToken, readCookie } from "@/lib/api/client";
import { ApiError, ErrorCode } from "@/lib/api/errors";
import { changePassword, currentUser, login, logout } from "@/lib/api/auth";

const CSRF = "test-csrf-token";

const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

interface RecordedRequest {
  url: string;
  method: string;
  credentials: RequestCredentials | undefined;
  headers: Headers;
  body: string | undefined;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function htmlResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: { "content-type": "text/html" } });
}

function noContentResponse(): Response {
  return new Response(null, { status: 204 });
}

/**
 * Re-reads what `fetch` was called with.
 *
 * `init` is inspected rather than replayed into a `Request`, because the URLs
 * here are same-origin relative paths and undici refuses to parse those without
 * a base. Responses are rebuilt per call with `mockImplementation`, never
 * `mockResolvedValue`, because a `Response` body can only be read once.
 */
function requests(): RecordedRequest[] {
  return fetchMock().mock.calls.map(([input, init]) => ({
    url: typeof input === "string" ? input : String(input),
    method: init?.method ?? "GET",
    credentials: init?.credentials,
    headers: new Headers(init?.headers),
    body: init?.body as string | undefined,
  }));
}

function setCsrfCookie(value: string): void {
  document.cookie = `csrftoken=${value}`;
}

function clearCsrfCookie(): void {
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

/**
 * Await a request that must fail and hand back the `ApiError`.
 *
 * Throws if the request resolves, so a test cannot pass just because the code
 * under test stopped rejecting at all.
 */
async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("Expected the request to fail, but it resolved.");
}

beforeEach(() => {
  clearCsrfCookie();
  setCsrfCookie(CSRF);
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("request shape", () => {
  it("calls the versioned API with an Accept header and cookies included", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ ok: true }));

    await apiFetch("/auth/me/");

    const [request] = requests();
    expect(request.url).toBe("/api/v1/auth/me/");
    expect(request.headers.get("Accept")).toBe("application/json");
    expect(request.credentials).toBe("include");
  });

  it("serialises query parameters and drops empty ones", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ results: [] }));

    await apiFetch("/sales/", { query: { page: 2, page_size: 20, q: "", cursor: null } });

    expect(requests()[0].url).toBe("/api/v1/sales/?page=2&page_size=20");
  });

  it("passes an Idempotency-Key through untouched (spec §10.2)", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ id: 9 }));

    await apiFetch("/sales/", { method: "POST", body: {}, idempotencyKey: "sale-abc-123" });

    expect(requests()[0].headers.get("Idempotency-Key")).toBe("sale-abc-123");
  });
});

describe("CSRF handling", () => {
  it("sends the cookie's token on unsafe requests", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user: { id: 1 } }));

    await apiFetch("/auth/login/", { method: "POST", body: { username: "u" } });

    expect(requests()[0].headers.get("X-CSRFToken")).toBe(CSRF);
  });

  it("re-reads the cookie every time, so a rotated token is never stale", async () => {
    // Django rotates the CSRF token inside login() and logout(). A client that
    // cached the token would send the pre-login value and get a 403 on its very
    // next write.
    fetchMock().mockImplementation(() => jsonResponse({ user: { id: 1 } }));

    setCsrfCookie("token-before-login");
    await apiFetch("/auth/login/", { method: "POST", body: {} });
    setCsrfCookie("token-after-login");
    await apiFetch("/sales/", { method: "POST", body: {} });

    const [first, second] = requests();
    expect(first.headers.get("X-CSRFToken")).toBe("token-before-login");
    expect(second.headers.get("X-CSRFToken")).toBe("token-after-login");
  });

  it("omits the header on safe requests", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ results: [] }));

    await apiFetch("/products/");

    expect(requests()[0].headers.get("X-CSRFToken")).toBeNull();
  });

  it("bootstraps a token from /auth/csrf/ when the cookie is absent", async () => {
    clearCsrfCookie();
    fetchMock()
      .mockImplementationOnce(() => jsonResponse({ token: CSRF }))
      .mockImplementation(() => jsonResponse({ id: 1 }));

    await apiFetch("/sales/", { method: "POST", body: {} });

    const [bootstrap, write] = requests();
    expect(bootstrap.url).toBe("/api/v1/auth/csrf/");
    expect(bootstrap.method).toBe("GET");
    expect(write.headers.get("X-CSRFToken")).toBe(CSRF);
  });

  it("reads a cookie value containing '=' and decodes it", () => {
    document.cookie = "csrftoken=abc=def";
    expect(readCookie("csrftoken")).toBe("abc=def");
    expect(readCookie("absent")).toBeNull();
  });

  it("surfaces a failed bootstrap as an ApiError", async () => {
    clearCsrfCookie();
    fetchMock().mockImplementation(() =>
      jsonResponse({ error: { code: "throttled", message: "Too many requests." } }, 429),
    );

    await expect(fetchCsrfToken()).rejects.toMatchObject({
      code: ErrorCode.Throttled,
      status: 429,
    });
  });
});

describe("write bodies", () => {
  it("sends JSON with a content type on unsafe requests", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user: { id: 1 } }));

    await apiFetch("/auth/login/", { method: "POST", body: { username: "u", password: "p" } });

    const request = requests()[0];
    expect(request.headers.get("Content-Type")).toBe("application/json");
    expect(request.body).toBe('{"username":"u","password":"p"}');
  });

  it("sends an empty JSON object when there is no body, which logout needs", async () => {
    // Django's CSRF check parses the body for a form token, so a bodyless POST
    // sent as multipart is refused with 415 before it is ever authorised.
    fetchMock().mockImplementation(noContentResponse);

    await logout();

    const request = requests()[0];
    expect(request.headers.get("Content-Type")).toBe("application/json");
    expect(request.body).toBe("{}");
  });

  it("sends no body at all on reads", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user: { id: 1 } }));

    await currentUser();

    expect(requests()[0].body).toBeUndefined();
  });
});

describe("failures", () => {
  it("rejects with the envelope's code, message and field details", async () => {
    fetchMock().mockImplementation(() =>
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "The submitted data is invalid.",
            details: { username: ["This field is required."] },
          },
        },
        400,
      ),
    );

    const error = await captureError(login({ username: "", password: "" }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe(ErrorCode.Validation);
    expect(error.status).toBe(400);
    expect(error.details?.username).toEqual(["This field is required."]);
  });

  it("turns an HTML error page into a typed error instead of a parse crash", async () => {
    // Found in A9: an unauthenticated request to the browsable /api/docs/ gets
    // DRF's HTML login page, not JSON.
    fetchMock().mockImplementation(() =>
      htmlResponse("<!DOCTYPE html><html><body>Login</body></html>", 401),
    );

    const error = await captureError(currentUser());

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe(ErrorCode.NotAuthenticated);
    expect(error.status).toBe(401);
  });

  it("reports an unreadable 5xx as a server error", async () => {
    fetchMock().mockImplementation(() => htmlResponse("<html>502 Bad Gateway</html>", 502));

    const error = await captureError(apiFetch("/sales/"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe(ErrorCode.ServerError);
  });

  it("still reports an envelope that arrived with an unexpected status", async () => {
    fetchMock().mockImplementation(() =>
      jsonResponse({ error: { code: "permission_denied", message: "No." } }, 403),
    );

    await expect(apiFetch("/admin-only/", { method: "POST", body: {} })).rejects.toMatchObject({
      code: ErrorCode.PermissionDenied,
      status: 403,
    });
  });

  it("does not resolve a 2xx that is not JSON", async () => {
    fetchMock().mockImplementation(() => htmlResponse("<html>hi</html>", 200));

    await expect(apiFetch("/reports/")).rejects.toBeInstanceOf(ApiError);
  });

  it("resolves undefined for 204 No Content", async () => {
    fetchMock().mockImplementation(noContentResponse);

    await expect(logout()).resolves.toBeUndefined();
  });
});

describe("deadlines", () => {
  it("abandons a request that outlives its deadline with a typed timeout", async () => {
    vi.useFakeTimers();
    // A connection that is accepted but never answered: the failure mode behind
    // the "Checking your session…" stall. Left alone, nothing here ever rejects.
    fetchMock().mockImplementation(() => new Promise<Response>(() => undefined));

    const request = currentUser({ timeoutMs: 1_000 });
    const outcome = expect(request).rejects.toMatchObject({
      code: ErrorCode.Timeout,
      status: 0,
    });

    await vi.advanceTimersByTimeAsync(1_000);
    await outcome;
  });

  it("leaves a request without a deadline to the browser's own timeouts", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user: { id: 1 } }));

    await expect(currentUser()).resolves.toEqual({ id: 1 });
  });

  it("tells a request the caller cancelled apart from one that timed out", async () => {
    // The session check aborts on unmount. That abort must stay an AbortError:
    // a deliberate cancellation is not a slow server and must not be reported as
    // a retryable timeout.
    vi.useFakeTimers();
    const controller = new AbortController();
    fetchMock().mockImplementation(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );

    const request = currentUser({ signal: controller.signal, timeoutMs: 1_000 });
    const outcome = expect(request).rejects.toMatchObject({ name: "AbortError" });

    controller.abort();
    await outcome;
  });
});

describe("auth endpoints", () => {
  const user = {
    id: 4,
    username: "owner",
    display_name: "Owner",
    role: "owner",
    role_name: "Owner",
    permissions: ["sales.add_sale"],
    email: "",
    phone_number: "",
    is_temporary_password: false,
    last_login: null,
  };

  it("unwraps the user from login and posts the credentials", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user }));

    await expect(login({ username: "owner", password: "pw" })).resolves.toEqual(user);

    const request = requests()[0];
    expect(request.url).toBe("/api/v1/auth/login/");
    expect(request.method).toBe("POST");
  });

  it("reads /auth/me/ without a CSRF header", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user }));

    await expect(currentUser()).resolves.toEqual(user);
    expect(requests()[0].headers.get("X-CSRFToken")).toBeNull();
  });

  it("posts all three password fields and returns the refreshed user", async () => {
    fetchMock().mockImplementation(() => jsonResponse({ user }));

    await changePassword({
      current_password: "old",
      new_password: "new-password",
      new_password_confirm: "new-password",
    });

    const request = requests()[0];
    expect(request.url).toBe("/api/v1/auth/change-password/");
    expect(JSON.parse(request.body ?? "{}")).toEqual({
      current_password: "old",
      new_password: "new-password",
      new_password_confirm: "new-password",
    });
  });
});

describe("B1 gate: no token is left in the browser", () => {
  it("leaves localStorage and sessionStorage untouched across a whole session", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fetchMock()
      .mockImplementationOnce(() => jsonResponse({ token: CSRF }))
      .mockImplementationOnce(() => jsonResponse({ user: { id: 4 } }))
      .mockImplementationOnce(() => jsonResponse({ id: 11 }))
      .mockImplementationOnce(noContentResponse);

    await fetchCsrfToken();
    await login({ username: "owner", password: "pw" });
    setCsrfCookie("rotated-by-login");
    await apiFetch("/sales/", { method: "POST", body: { total: 100 } });
    await logout();

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(setItem).not.toHaveBeenCalled();
  });
});

describe("base URL", () => {
  it("honours NEXT_PUBLIC_API_BASE_URL for the cross-origin dev server", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000/api/v1/");
    vi.resetModules();
    const reloaded = await import("@/lib/api/client");

    fetchMock().mockImplementation(() => jsonResponse({ results: [] }));
    await reloaded.get("/products/");

    expect(reloaded.API_BASE_URL).toBe("http://localhost:8000/api/v1");
    expect(requests()[0].url).toBe("http://localhost:8000/api/v1/products/");
  });
});
