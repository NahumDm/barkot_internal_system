import { test, expect } from "@playwright/test";
import { stubSignedIn } from "./e2e/session";

/**
 * Structural baseline, written in B0 before there was any authentication.
 *
 * These now sign in first, because from B2 onward an unauthenticated visit to
 * any of these routes redirects to `/login` — which is the B2 gate working, not
 * a regression here. Each test asserts the shell rather than its contents,
 * because the shell is what B0 committed to and the screens arrive in B4 and
 * after.
 */

test("home redirects to the dashboard", async ({ page }) => {
  await stubSignedIn(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("sidebar exposes all 19 sidebar links (spec §7.4 plus the category manager and register)", async ({
  page,
}) => {
  await stubSignedIn(page);
  await page.goto("/dashboard");
  await expect(page).toHaveTitle(/Barkot/);
  await expect(page.locator("aside nav a")).toHaveCount(19);
});

test("product maintenance route renders its shell", async ({ page }) => {
  await stubSignedIn(page);
  await page.goto("/inventory/products");
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
});

test("category manager route renders its shell", async ({ page }) => {
  await stubSignedIn(page);
  await page.goto("/inventory/categories");
  await expect(page.getByRole("heading", { name: "Categories", level: 1 })).toBeVisible();
});
