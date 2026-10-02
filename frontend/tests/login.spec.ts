import { expect, test } from "@playwright/test";
import {
  OWNER,
  stubCsrf,
  stubLoginAccepted,
  stubLoginRejected,
  stubLoginThrottled,
  stubPasswordChangeAccepted,
  stubSessionStartingSignedOut,
  stubSignedIn,
  stubSignedOut,
} from "./e2e/session";

/**
 * B3's gate, in a real browser: enter credentials, land on the dashboard.
 *
 * Also the first E2E test that drives the sign-in form itself rather than
 * arriving at a page, so it is where the CSRF bootstrap, the login POST and the
 * post-sign-in navigation are exercised together against the real client.
 */

const NEW_HIRE = {
  ...OWNER,
  username: "new-hire",
  display_name: "New Hire",
  is_temporary_password: true,
};

test("entering credentials lands on the dashboard", async ({ page }) => {
  await stubCsrf(page);
  await stubLoginAccepted(page);
  await stubSignedIn(page);

  await page.goto("/login");
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("hunter2");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("signing in returns the user to the page they were trying to reach", async ({ page }) => {
  await stubCsrf(page);
  await stubSessionStartingSignedOut(page);

  await page.goto("/sales");
  await expect(page).toHaveURL(/\/login\?next=%2Fsales/);

  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("hunter2");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/sales$/);
});

test("rejected credentials are explained and the form stays usable", async ({ page }) => {
  await stubCsrf(page);
  await stubLoginRejected(page);
  await stubSignedOut(page);

  await page.goto("/login");
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.locator('p[role="alert"]')).toContainText(
    "Those credentials were not accepted.",
  );
  await expect(page).toHaveURL(/\/login/);
  // The form must still be usable rather than stuck behind a disabled control.
  await expect(page.getByLabel("Username")).toBeEditable();
});

test("a throttled sign-in says to wait, not that the password was wrong", async ({ page }) => {
  // A5 allows five attempts a minute. Reporting the sixth as rejected credentials
  // sends someone to reset a password they never got wrong.
  await stubCsrf(page);
  await stubLoginThrottled(page);
  await stubSignedOut(page);

  await page.goto("/login");
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("hunter2");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.locator('p[role="alert"]')).toContainText(/wait a minute/i);
});

test("a temporary password lands on the change screen, not the dashboard", async ({ page }) => {
  await stubCsrf(page);
  await stubLoginAccepted(page, NEW_HIRE);
  await stubSignedIn(page, NEW_HIRE);

  await page.goto("/login");
  await page.getByLabel("Username").fill("new-hire");
  await page.getByLabel("Password").fill("temp-1234");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/change-password$/);
  await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
});

test("setting a new password releases the user into the application", async ({ page }) => {
  await stubCsrf(page);
  await stubLoginAccepted(page, NEW_HIRE);
  await stubSignedIn(page, NEW_HIRE);
  await stubPasswordChangeAccepted(page, NEW_HIRE);

  await page.goto("/login");
  await page.getByLabel("Username").fill("new-hire");
  await page.getByLabel("Password").fill("temp-1234");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/change-password$/);

  // "New password" is a substring of "Confirm new password", so it needs to be
  // matched exactly or the second field wins.
  await page.getByLabel("Current password").fill("temp-1234");
  await page.getByLabel("New password", { exact: true }).fill("a-much-better-one");
  await page.getByLabel("Confirm new password").fill("a-much-better-one");
  await page.getByRole("button", { name: "Set password" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  // The guard must not bounce the user straight back now the flag is cleared.
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("a temporary-password user is redirected out of the application", async ({ page }) => {
  // The API refuses every other endpoint with password_change_required, so
  // parking them on the dashboard means a page where nothing works.
  await stubSignedIn(page, NEW_HIRE);

  await page.goto("/sales");

  await expect(page).toHaveURL(/\/change-password$/);
  await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
});
