/**
 * The responsive frame (spec §7): the sidebar's 960px breakpoint and the rule
 * that no screen scrolls the page sideways.
 *
 * On a phone the persistent sidebar was the whole problem: a 256px column that
 * never moved, on top of content that could not shrink beside it. These specs
 * pin the contract that replaced it - a drawer below 960px and the same
 * sidebar it always was at 960px and above - and sweep every route for the
 * horizontal overflow the phone session hit.
 *
 * The session stub comes from `./session` for the reasons recorded there: the
 * `chromium` project has no Django, and these are shell-level assertions. The
 * overflowing elements the drawer fixes sit inside `overflow-x-auto` wrappers,
 * so "does the document scroll" is the honest question to ask of every route,
 * populated or not.
 */

import { expect, test, type Page } from "@playwright/test";

import { stubSignedIn } from "./session";

const ROUTES = [
  "/dashboard",
  "/sales",
  "/sales/transactions",
  "/sales/transactions/new",
  "/inventory",
  "/inventory/products",
  "/inventory/categories",
  "/inventory/receive",
  "/inventory/counts",
  "/inventory/movements",
  "/inventory/breakage",
  "/finance",
  "/finance/expenses",
  "/finance/balance",
  "/payroll/employees",
  "/payroll/runs",
  "/payroll/deductions",
  "/employees",
  "/reports",
  "/settings",
];

const PHONE_WIDTHS = [320, 360, 390];

/** How far the document scrolls past its own viewport. One pixel is rounding. */
async function pageOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

test.describe("responsive frame", () => {
  test("below 960px the sidebar is an off-canvas drawer", async ({ page }) => {
    await stubSignedIn(page);
    await page.setViewportSize({ width: 959, height: 800 });
    await page.goto("/dashboard");

    const toggle = page.getByRole("button", { name: "Open navigation" });
    const sidebar = page.locator("aside.sidebar");

    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toHaveAttribute("aria-controls", "app-navigation");
    await expect(sidebar).toBeHidden();

    await toggle.click();
    await expect(sidebar).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("button", { name: "Close navigation" })).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");

    await page.keyboard.press("Escape");
    await expect(sidebar).toBeHidden();
    await expect(toggle).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  });

  test("the backdrop and the close button dismiss the drawer", async ({ page }) => {
    await stubSignedIn(page);
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/dashboard");

    const toggle = page.getByRole("button", { name: "Open navigation" });
    const sidebar = page.locator("aside.sidebar");

    await toggle.click();
    await expect(sidebar).toBeVisible();
    // Right of the 256px drawer, so the pointer lands on the backdrop, not the panel.
    await page.locator(".sidebar-backdrop").click({ position: { x: 360, y: 400 } });
    await expect(sidebar).toBeHidden();

    await toggle.click();
    await expect(sidebar).toBeVisible();
    await page.getByRole("button", { name: "Close navigation" }).click();
    await expect(sidebar).toBeHidden();
  });

  test("following a link closes the drawer and moves focus to the page", async ({ page }) => {
    await stubSignedIn(page);
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/dashboard");

    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.locator('aside nav a[href="/finance"]').click();

    await expect(page).toHaveURL(/\/finance$/);
    await expect(page.locator("aside.sidebar")).toBeHidden();
    await expect(page.locator("main.main")).toBeFocused();
  });

  test("at 960px and above the persistent sidebar is shown, with no toggle", async ({ page }) => {
    await stubSignedIn(page);
    for (const width of [960, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/dashboard");
      await expect(page.locator("aside.sidebar")).toBeVisible();
      await expect(page.locator(".nav-toggle")).toBeHidden();
    }
  });

  test("no route scrolls the page horizontally at phone widths", async ({ page }) => {
    // Three widths times every route, each a full navigation whose API calls
    // fail against the stubbed project's absent backend. The register added a
    // route to the sweep, so the budget that fit 18 of them no longer fits 19.
    test.setTimeout(420_000);
    await stubSignedIn(page);
    for (const width of PHONE_WIDTHS) {
      await page.setViewportSize({ width, height: 800 });
      for (const route of ROUTES) {
        await page.goto(route);
        await expect(page.locator("aside.sidebar")).toBeAttached();
        expect(await pageOverflow(page), `${route} at ${width}px`).toBeLessThanOrEqual(1);
      }
    }
  });

  test("no route scrolls the page horizontally in landscape", async ({ page }) => {
    test.setTimeout(120_000);
    await stubSignedIn(page);
    for (const [width, height] of [
      [600, 360],
      [900, 420],
    ]) {
      await page.setViewportSize({ width, height });
      for (const route of ["/dashboard", "/inventory/products", "/finance/expenses"]) {
        await page.goto(route);
        await expect(page.locator("aside.sidebar")).toBeAttached();
        expect(await pageOverflow(page), `${route} at ${width}x${height}`).toBeLessThanOrEqual(1);
      }
    }
  });

  test("every route fits at tablet, desktop and phone-landscape sizes", async ({ page }) => {
    // Five viewports times the twenty routes below. The API is absent in the
    // stubbed project, so each navigation settles quickly; the budget is for a
    // cold production server rendering every route for the first time.
    test.setTimeout(900_000);
    await stubSignedIn(page);
    const viewports: Array<[number, number, string]> = [
      [768, 1024, "tablet portrait"],
      [1024, 900, "small desktop"],
      [1440, 900, "desktop"],
      [844, 390, "phone landscape"],
      [932, 430, "large phone landscape"],
    ];

    for (const [width, height, label] of viewports) {
      await page.setViewportSize({ width, height });
      for (const route of ROUTES) {
        await page.goto(route);
        await expect(page.locator("aside.sidebar")).toBeAttached();
        expect(
          await pageOverflow(page),
          `${route} at ${width}x${height} (${label})`,
        ).toBeLessThanOrEqual(1);
      }
    }
  });
});
