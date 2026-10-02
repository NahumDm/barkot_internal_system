/**
 * Network stubs that stand in for the API during E2E (roadmap B2).
 *
 * The Playwright server runs `next start` alone; there is no Django behind it,
 * and starting one per test run would couple the frontend suite to the backend
 * stack. So `/auth/me/` is answered at the network layer instead.
 *
 * The stubs copy the real contract rather than a convenient one. A request with
 * no session at all is answered 401 `not_authenticated`, because the backend's
 * authenticator returns a challenge header and so makes DRF pick 401 over 403
 * (see `backend/apps/core/authentication.py`); 403 is reserved for a request that
 * was authenticated but not allowed. Answering 403 here would let the guard pass
 * on a pairing the real API never sends, and would turn "signed out" into
 * "signed in but forbidden" for any response that failed to parse as the envelope.
 *
 * The other 403s are real and mean something different: `session_expired` is
 * raised after a session that did exist idled out, and `password_change_required`
 * is raised for an authenticated user still on a temporary password.
 */

import type { Page } from "@playwright/test";

export interface StubUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  role_name: string;
  permissions: string[];
  email: string;
  phone_number: string;
  is_temporary_password: boolean;
  last_login: string | null;
}

export const OWNER: StubUser = {
  id: 1,
  username: "owner",
  display_name: "Selam Bekele",
  role: "owner",
  role_name: "Owner",
  permissions: ["sales.add_sale", "products.change_product"],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const ME_URL = "**/api/v1/auth/me/";

/** Answer `/auth/me/` as a user with no session (401, per the backend contract). */
export async function stubSignedOut(page: Page): Promise<void> {
  await page.route(ME_URL, (route) =>
    route.fulfill({
      status: 401,
      headers: { "www-authenticate": 'Session realm="barkot"' },
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "not_authenticated",
          message: "Sign in to continue. Your session may have expired.",
        },
      }),
    }),
  );
}

/** Answer `/auth/me/` as a signed-in user. */
export async function stubSignedIn(page: Page, user: StubUser = OWNER): Promise<void> {
  await page.route(ME_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user }),
    }),
  );
}

/** Answer `/auth/me/` with a failure that is not about authentication. */
export async function stubSessionUnreachable(page: Page, status = 502): Promise<void> {
  await page.route(ME_URL, (route) =>
    route.fulfill({
      status,
      contentType: "text/html",
      body: "<html><body>502 Bad Gateway</body></html>",
    }),
  );
}

/**
 * Model a real session lifecycle: signed out until credentials are accepted.
 *
 * Do not try to get this by registering `stubSignedOut` and then
 * `stubSignedIn`. Playwright consults the most recently added matching route
 * first, so the second registration silently replaces the first and the user
 * turns out to have been signed in the whole time - the test then asserts
 * nothing and passes anyway. One handler per endpoint, with the login stub
 * flipping the state, is the only way this reads honestly.
 */
export async function stubSessionStartingSignedOut(
  page: Page,
  user: StubUser = OWNER,
): Promise<void> {
  let authenticated = false;

  await page.route(ME_URL, (route) =>
    authenticated
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ user }),
        })
      : route.fulfill({
          status: 401,
          headers: { "www-authenticate": 'Session realm="barket"' },
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "not_authenticated",
              message: "Sign in to continue. Your session may have expired.",
            },
          }),
        }),
  );

  await page.route(LOGIN_URL, (route) => {
    // Accepting credentials is what creates the session; the cookie is opaque
    // to the client, so this flip is the whole observable effect of signing in.
    authenticated = true;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user }),
    });
  });
}

const CSRF_URL = "**/api/v1/auth/csrf/";
const LOGIN_URL = "**/api/v1/auth/login/";
const CHANGE_PASSWORD_URL = "**/api/v1/auth/change-password/";

/**
 * Answer `/auth/csrf/` with a token.
 *
 * The client reads the `csrftoken` cookie and only falls back to the response
 * body, so this stub is what lets a POST happen at all in a browser with no
 * real cookies.
 */
export async function stubCsrf(page: Page): Promise<void> {
  await page.route(CSRF_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "e2e-csrf-token" }),
    }),
  );
}

/** Accept credentials, answering with `user`. */
export async function stubLoginAccepted(page: Page, user: StubUser = OWNER): Promise<void> {
  await page.route(LOGIN_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user }),
    }),
  );
}

/**
 * Reject credentials the way the real view does: a serializer `ValidationError`,
 * so the message arrives under `non_field_errors` rather than as a bare 400.
 */
export async function stubLoginRejected(
  page: Page,
  message = "Those credentials were not accepted.",
): Promise<void> {
  await page.route(LOGIN_URL, (route) =>
    route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "validation_error",
          message: "The submitted data is invalid.",
          details: { non_field_errors: [message] },
        },
      }),
    }),
  );
}

/** Refuse a sign-in as the login rate limit does (A5: five a minute). */
export async function stubLoginThrottled(page: Page): Promise<void> {
  await page.route(LOGIN_URL, (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "throttled",
          message: "Too many requests. Wait a moment and try again.",
        },
      }),
    }),
  );
}

/** Accept a password change, returning the user with the flag now cleared. */
export async function stubPasswordChangeAccepted(
  page: Page,
  user: StubUser = OWNER,
): Promise<void> {
  await page.route(CHANGE_PASSWORD_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { ...user, is_temporary_password: false } }),
    }),
  );
}
