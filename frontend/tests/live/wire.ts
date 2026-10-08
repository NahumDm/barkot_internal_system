/**
 * A same-origin POST from inside the browser, carrying the session's own CSRF
 * token.
 *
 * Used where a story has to ask the real backend for something no button does -
 * the refusals a role should never be able to reach, like approving payroll a
 * Cashier cannot approve. Playwright's `page.request` shares cookies but not the
 * CSRF dance: the app reads `csrftoken` from the cookie at send time (see
 * `src/lib/api/client.ts`), dots the `X-CSRFToken` header on, and posts from the
 * page so the browser itself supplies Origin, Referer and the session. This
 * helper does exactly that, so the 403 it expects is the backend's own
 * permission answer rather than a CSRF defence.
 *
 * The fetch is relative to `/api/v1/` just like the application's own client,
 * so it goes through the same Next proxy and never crosses an origin.
 */

import type { Page } from "@playwright/test";

export interface WireResult {
  status: number;
  body: unknown;
}

/** POST `path` (already starting with `/api/v1/`) from the page's own session. */
export async function wirePost(page: Page, path: string, body: unknown = {}): Promise<WireResult> {
  return page.evaluate(
    async ({ path, body: payload }) => {
      // Ensure the CSRF cookie exists before reading it. The login flow writes
      // one, but a page that signed in on an earlier render may be long past it.
      await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
      const cookie =
        document.cookie
          .split(";")
          .map((part) => part.trim())
          .find((part) => part.startsWith("csrftoken="))
          ?.slice("csrftoken=".length) ?? "";
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": cookie,
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      let json: unknown = null;
      try {
        json = await response.json();
      } catch {
        // A 500 or a plain-text answer still has a status worth asserting on.
      }
      return { status: response.status, body: json };
    },
    { path, body },
  );
}
