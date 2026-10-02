/**
 * Network stubs that stand in for the API during E2E (roadmap B2).
 *
 * The Playwright server runs `next start` alone; there is no Django behind it,
 * and starting one per test run would couple the frontend suite to the backend
 * stack. So `/auth/me/` is answered at the network layer instead.
 *
 * The stubs copy the real contract rather than a convenient one. The status is
 * 403, not 401, because Django's `SessionAuthentication` supplies no
 * `WWW-Authenticate` header and DRF rewrites `NotAuthenticated` to 403 when one
 * is absent - which is why A6's expired-session rule is a 403. A stub that
 * answered 401 would let the guard pass on a status the real API never sends.
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

/** Answer `/auth/me/` as a user with no session. */
export async function stubSignedOut(page: Page): Promise<void> {
  await page.route(ME_URL, (route) =>
    route.fulfill({
      status: 403,
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
