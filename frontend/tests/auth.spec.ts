import { expect, test } from "@playwright/test";
import { stubSessionUnreachable, stubSignedIn, stubSignedOut } from "./e2e/session";

/**
 * B2's gate, in a real browser.
 *
 * The unit tests already assert the redirect, but they assert it against a
 * mocked router. This drives the built app to prove the guard is actually wired
 * between the URL and the screen - a guard that exists, works, and is never
 * mounted passes every unit test in the repository.
 */

test("an unauthenticated visit to /sales redirects to /login", async ({ page }) => {
  await stubSignedOut(page);

  await page.goto("/sales");

  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("the redirect keeps the attempted path so signing in can return there", async ({ page }) => {
  await stubSignedOut(page);

  await page.goto("/inventory/products");

  await expect(page).toHaveURL(/\/login\?next=%2Finventory%2Fproducts/);
});

test("a signed-in visit to /sales renders the page and does not redirect", async ({ page }) => {
  await stubSignedIn(page);

  await page.goto("/sales");

  await expect(page).toHaveURL(/\/sales$/);
  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();
});

test("protected content is never shown to a signed-out visitor", async ({ page }) => {
  await stubSignedOut(page);

  await page.goto("/sales");
  await expect(page).toHaveURL(/\/login/);

  // The sidebar offers 17 destinations. None of them should have been rendered
  // on the way past.
  await expect(page.locator("aside nav a")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Receive Stock");
});

test("an unreachable API offers a retry instead of asking the user to sign in", async ({
  page,
}) => {
  // The failure mode this guards against is quiet and expensive: a 502 that
  // reads as "session expired" sends a cashier to the login screen, where the
  // correct password also fails, and they conclude they are locked out.
  await stubSessionUnreachable(page);

  await page.goto("/sales");

  await expect(page.getByRole("heading", { name: /Cannot reach the server/ })).toBeVisible();
  await expect(page).not.toHaveURL(/\/login/);
});

test("the login page is reachable without a session", async ({ page }) => {
  await stubSignedOut(page);

  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
