import { test, expect } from "@playwright/test";

test("home redirects to the dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("sidebar exposes all 17 normative sidebar links (spec §7.4)", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveTitle(/Barkot/);
  await expect(page.locator("aside nav a")).toHaveCount(17);
});

test("product maintenance route renders its shell", async ({ page }) => {
  await page.goto("/inventory/products");
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
});
