/**
 * Roadmap B5's gate, in a browser, against the real thing.
 *
 * The stubbed specs in `tests/e2e/` answer the API at the network layer, which is
 * the right tool for states a server cannot be asked to produce on demand - a
 * 502, a temporary password, a throttled sign-in. It is the wrong tool for the
 * question B5 actually asks: does a cashier's browser, talking to this Django,
 * record a sale that leaves the right rows behind.
 *
 * A stub answers that question with the author's assumptions. Concretely: the
 * category route that resolved to a product retrieve, and the price-history route
 * that answered 405, both shipped with every stubbed spec green, because the stub
 * was answering instead of the router. Nothing here intercepts a request, so a
 * route that answers the wrong way is a failure rather than an invisible detail.
 *
 * The story runs in three steps, in order, because each depends on the last.
 *
 * 1. A wrong password is refused by Django's own authenticator - so the form is
 *    talking to a real one rather than to something that agrees with whatever it
 *    is sent. In the stubbed suite this shape is produced by the stub.
 * 2. A Cashier signs in with a real session, sees an empty till, records a sale,
 *    and the stock ledger moves exactly once. Read back over HTTP with the
 *    cashier's own cookie, because a screen agreeing with itself is not evidence.
 *    The income half of that story is on the till too: the dashboard's Takings
 *    and Transactions tiles show the money the sale took in.
 * 3. That Cashier cannot void it - a real 403 from a real permission, with the
 *    sale still standing - and a Manager can, after which the stock is back.
 *
 * Serial by design: one database, one story. It also keeps the sign-in count
 * low, which matters because A5 allows five login attempts a minute per address
 * and this run shares one.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";

const seed = readSeedSummary();

/** How many units this run sells, and therefore how much cash it takes. */
const QUANTITY = 3;
/** Stock before and after, as numbers: the ledger is fixed-point and its formatting is not the point. */
const ON_SHELF = Number(seed.product.opening_stock);
const AFTER_SALE = ON_SHELF - QUANTITY;
/** What the cashier types and what the screen shows, so a formatted string. */
const TOTAL = (Number(seed.product.unit_price) * QUANTITY).toFixed(2);

/** What Django says when a role may not do something. */
const REFUSED = "You do not have permission to do that.";

/**
 * The product select on the new-sale screen.
 *
 * Positional, and worth saying why: the `<label>Product</label>` beside it is not
 * associated with the `<select>` - no `htmlFor`, no `id`, no `aria-label` - so
 * there is no accessible name to match on. It is the first select on the screen;
 * the only other one is the payment method. Giving the control an accessible name
 * would be an improvement to the application, but it belongs in its own change
 * rather than smuggled in here to make a selector work.
 */
function productSelect(page: Page) {
  return page.getByRole("combobox").first();
}

/** The one sale row, whether or not anything else is on screen. */
function saleRow(page: Page) {
  return page.getByRole("row").filter({ hasText: /S-\d/ });
}

/**
 * The product's stock, read back over HTTP with the browser's own session cookie.
 *
 * A number rather than the string the API sends: the ledger is fixed-point, so
 * the same forty units come back as "40" or "40.000" depending on how they were
 * arrived at, and a test that asserted on that formatting would fail for a reason
 * that has nothing to do with the stock.
 */
async function readStock(page: Page): Promise<number> {
  const response = await page.request.get(`/api/v1/products/${seed.product.id}/`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { current_stock: string | null };
  return body.current_stock === null ? Number.NaN : Number(body.current_stock);
}

/** What the API says about one sale, located by its human reference. */
async function readSale(page: Page, reference: string): Promise<Record<string, unknown> | null> {
  const response = await page.request.get(`/api/v1/sales/?search=${encodeURIComponent(reference)}`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results[0] ?? null;
}

test.describe.configure({ mode: "serial" });

test("a wrong password is refused by Django itself", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(seed.cashier.username);
  await page.getByLabel("Password").fill("not-the-seeded-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  // The real view answers a serializer ValidationError, so the reason arrives
  // under `non_field_errors` and the client unwraps it - the same shape the
  // stubbed suite asserts, except that here Django produced it.
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("a Cashier records a sale: real session, stock down once, void refused", async ({ page }) => {
  // The sign-in may have to sit out the tail of the A5 login window, which can
  // cost a full minute per retry - see the shared helper's contract.
  test.setTimeout(240_000);

  await signIn(page, seed.cashier);
  expect(await readStock(page)).toBe(ON_SHELF);

  // An empty till to begin with. If this ever fails because a sale is already
  // listed, global setup did not reset - worth knowing, because every stock
  // assertion below is a difference from this starting point.
  await page.goto("/sales");
  await expect(page.getByText("No sales found.")).toBeVisible();

  await page.goto("/sales/transactions/new");
  // This option exists only because the seed created the product and Django
  // listed it, so its presence is itself a round trip.
  await expect(productSelect(page).locator("option", { hasText: seed.product.sku })).toHaveCount(1);
  await productSelect(page).selectOption(String(seed.product.id));
  await page.getByLabel("Qty").fill(String(QUANTITY));
  await page.getByLabel("Amount").fill(TOTAL);
  await page.getByRole("button", { name: "Record Sale" }).click();

  await expect(page).toHaveURL(/\/sales$/);
  const row = saleRow(page);
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("COMPLETED");
  await expect(row).toContainText("PAID");
  await expect(row).toContainText(TOTAL);

  // Server truth, over the same session.
  expect(await readStock(page)).toBe(AFTER_SALE);
  const reference = (await row.locator("td").first().innerText()).trim();
  expect(await readSale(page, reference)).toMatchObject({
    reference,
    status: "COMPLETED",
    payment_status: "PAID",
    total: TOTAL,
  });

  // The sale's income side is on the till too: the dashboard's Takings and
  // Transactions tiles are the money the ledger took in, not a number the
  // browser invented. The tile value is asserted through the Metric card that
  // owns its label, so a matching number elsewhere on screen cannot satisfy it.
  await page.goto("/dashboard");
  await expect(page.getByText("Takings", { exact: true }).first()).toBeVisible();
  await expect(
    page
      .getByText("Takings", { exact: true })
      .locator("..")
      .getByText(`${TOTAL} ETB`, { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Transactions", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText("Transactions", { exact: true }).locator("..").getByText("1", { exact: true }),
  ).toBeVisible();

  // The screen offers Void to anyone who can see the row; Django is what
  // refuses. The confirm has to be accepted or the request is never sent and
  // this test would pass without the backend ever being asked - Playwright
  // dismisses dialogs by default, so the handler below is load-bearing.
  await page.goto("/sales");
  const dialogs: { kind: string; message: string }[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push({ kind: dialog.type(), message: dialog.message() });
    if (dialog.type() === "confirm") void dialog.accept();
    else void dialog.dismiss();
  });

  await row.getByRole("button", { name: "Void" }).click();

  await expect
    .poll(() => dialogs.filter((d) => d.kind === "alert").map((d) => d.message))
    .toContain(REFUSED);
  // Refused means refused: the sale is still standing and the stock is still
  // where the sale left it.
  await expect(row).toContainText("COMPLETED");
  expect(await readStock(page)).toBe(AFTER_SALE);
});

test("a Manager voids the sale and the stock comes back", async ({ page }) => {
  // Same A5 window as the test above: this run shares one client address with
  // the rest of the live suite, so the sign-in must be able to wait it out.
  test.setTimeout(240_000);

  await signIn(page, seed.manager);
  await page.goto("/sales");

  const row = saleRow(page);
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("COMPLETED");

  page.on("dialog", (dialog) => void dialog.accept());

  await row.getByRole("button", { name: "Void" }).click();

  // The sale leaves the list rather than turning grey in it. That is the
  // backend's documented design rather than a UI decision: `VoidableManager`
  // excludes voided rows from the default queryset precisely so that a list or a
  // report cannot accidentally count one. A void is a reversal, not a state the
  // till still has to reconcile against.
  await expect(saleRow(page)).toHaveCount(0);

  // And the reversal actually happened: back to exactly what was on the shelf.
  // An extra IN movement would leave three units too many, and this is the
  // assertion that would say so.
  expect(await readStock(page)).toBe(ON_SHELF);
});
