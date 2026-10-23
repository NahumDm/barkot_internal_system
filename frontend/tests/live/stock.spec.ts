/**
 * Two of §23.1's stories in a browser against the real backend: the Barman
 * receives stock, and the Manager closes a count whose variance only an
 * approver may post to the ledger.
 *
 * The stubbed suite answers the API at the network layer. Nothing here does:
 * the seed created the product, Django's ledger holds the opening stock, and
 * every write below goes through the same services a real click would. A route
 * answered the wrong way, or a permission granted to the wrong role, is a
 * failure rather than an invisible detail.
 *
 * The two stories, in order, because the second depends on the first:
 *
 * 1. **The Barman receives stock** (scenario 2). A delivery of 50 units at a
 *    20.00 cost is recorded on the receive screen, the receipt lands completed
 *    on the wire with its line cost, and the ledger moves exactly once - the
 *    shelf goes from 40 to 90 and no second movement sneaks a duplicate in.
 *    Receipts carry the purchase cost on the line, so the cost side of the
 *    story is asserted there rather than in finance, which does not see stock.
 * 2. **The Manager completes a count** (scenario 3). The count is opened while
 *    the shelf holds the received 90, the physical count of 89 is entered, and
 *    the variance is calculated as -1.000. A Cashier - who may *complete* a
 *    count but may not *approve* one - is refused an extra signer's job on the
 *    wire with a real 403, and then the Manager approves through the screen.
 *    Approval is a write to the ledger, so stock falls to exactly 89 and a
 *    `COUNT_VARIANCE OUT 1.000` movement exists for the variance report's line.
 *
 * The Cashier refusal needs that role's own session, not the Manager's. A count
 * is a per-render object (the approval button only exists on the same screen
 * that opened it), so refusal is asked over the wire - from inside the browser,
 * so CSRF and the real session travel with it. That session is a second browser
 * context, because a role pretending to be the manager would not prove anything.
 *
 * This file sorts last (alphabetical within the live project) for a reason:
 * receive and count approval change the stock the earlier stories leave alone,
 * and being last means no downstream spec has to know about them.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";
import { wirePost } from "./wire";

const seed = readSeedSummary();

/** What Django says when a role may not do something. */
const REFUSED = "You do not have permission to do that.";

/** How many units the Barman brings in, and at what cost. */
const RECEIVED_QTY = "50";
const UNIT_COST = "20.00";
/** The shelf before the receive, after it, and the counted figure. */
const ON_SHELF = Number(seed.product.opening_stock);
const AFTER_RECEIVE = ON_SHELF + Number(RECEIVED_QTY);
const COUNTED = String(AFTER_RECEIVE - 1);

/** The first day of the current month, as the variance report's window start. */
function monthStart(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

/** Today, so an approved count lands inside the report's inclusive window. */
function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** The product's stock on the shelf, read back over the browser's session. */
async function readStock(page: Page): Promise<number> {
  const response = await page.request.get(`/api/v1/products/${seed.product.id}/`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { current_stock: string | null };
  return body.current_stock === null ? Number.NaN : Number(body.current_stock);
}

/** The most recent stock receipt, read back over the browser's session. */
async function readLatestReceipt(page: Page): Promise<Record<string, unknown> | null> {
  const response = await page.request.get("/api/v1/inventory/receipts/?page_size=5");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results[0] ?? null;
}

/** The most recent stock movement, read back over the browser's session. */
async function readLatestMovement(page: Page): Promise<Record<string, unknown> | null> {
  const response = await page.request.get("/api/v1/inventory/movements/?page_size=5");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results[0] ?? null;
}

/** One stock count, located by id, read back over the browser's session. */
async function readCount(page: Page, id: number): Promise<Record<string, unknown> | null> {
  const response = await page.request.get("/api/v1/inventory/counts/?page_size=100");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results.find((count) => Number((count as { id: number }).id) === id) ?? null;
}

test.describe.configure({ mode: "serial" });

test("the Barman receives stock: receipt completed, cost recorded, stock up once", async ({
  page,
}) => {
  test.setTimeout(240_000);

  await signIn(page, seed.barman);
  expect(await readStock(page)).toBe(ON_SHELF);

  await page.goto("/inventory/receive");
  await page.getByLabel("Supplier", { exact: true }).fill("Barkot Brew Co.");
  await page.getByLabel("Product").selectOption(String(seed.product.id));
  await page.getByLabel("Quantity").fill(RECEIVED_QTY);
  await page.getByLabel("Unit price (ETB)").fill("20");
  await page.getByRole("button", { name: "Save record" }).click();

  // The receive screen clears its fields rather than announcing the write, so
  // the proof is on the wire: a completed receipt carrying the purchase cost,
  // and the ledger's one and only movement in.
  await expect.poll(async () => (await readLatestReceipt(page))?.id ?? null).not.toBeNull();
  expect(await readLatestReceipt(page)).toMatchObject({
    supplier_name: "Barkot Brew Co.",
    status: "COMPLETED",
    items: [
      {
        product: seed.product.id,
        product_name: seed.product.name,
        quantity: `${RECEIVED_QTY}.000`,
        unit_cost: UNIT_COST,
        currency: "ETB",
        line_cost: "1000.00",
      },
    ],
  });

  expect(await readLatestMovement(page)).toMatchObject({
    product: seed.product.id,
    kind: "RECEIPT",
    direction: "IN",
    quantity: `${RECEIVED_QTY}.000`,
    unit_cost: UNIT_COST,
    source: "STOCK_RECEIPT",
  });
  expect(await readStock(page)).toBe(AFTER_RECEIVE);

  // The movements screen is the human-readable version of the same ledger row.
  await page.goto("/inventory/movements");
  const movementRow = page.getByRole("row").filter({ hasText: `+${RECEIVED_QTY}.000` });
  await expect(movementRow).toHaveCount(1);
  await expect(movementRow).toContainText("RECEIPT");
  await expect(movementRow).toContainText(seed.product.name);
});

test("a count closes with its variance, and only an approver can post it", async ({
  browser,
  page,
}) => {
  test.setTimeout(240_000);

  // The Cashier proves the boundary while the count is real. A second context
  // carries their session, so the 403 below is that role's own answer.
  const cashierContext = await browser.newContext();
  const cashierPage = await cashierContext.newPage();
  await signIn(cashierPage, seed.cashier);

  // The API refuses the write; the screen must not offer it in the first place.
  // This is the real `/auth/me/` answer, not a stubbed permission list.
  await cashierPage.goto("/inventory/receive");
  await expect(
    cashierPage.getByText("Your role does not include this inventory action."),
  ).toBeVisible();

  await signIn(page, seed.manager);
  await page.goto("/inventory/counts");

  await page.getByRole("button", { name: "Open count" }).click();

  // The count shows the shelf it was opened against: the received 90.
  const countHeading = page.getByRole("heading", { name: /^Count #\d+ · DRAFT/ });
  await expect(countHeading).toBeVisible();
  await expect(page.getByText("90.000", { exact: true }).first()).toBeVisible();
  const countId = Number((await countHeading.textContent())?.match(/#(\d+)/)?.[1]);

  await page.getByLabel(`Physical quantity for ${seed.product.name}`).fill(COUNTED);
  await page.getByRole("button", { name: "Complete count" }).click();

  // The variance is the whole point of the screen: expected 90 counts against
  // the counted 89, and the -1.000 difference is stated before anyone may act
  // on it. The counted figure itself is history on a completed count - the
  // screen shows the expected quantity and the variance it produced - so the
  // variance assertion is the one that proves the arithmetic happened.
  await expect(page.getByText("90.000", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("-1.000", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Count #\d+ · COMPLETED/ })).toBeVisible();

  const completed = await readCount(page, countId);
  expect(completed).not.toBeNull();
  expect(completed).toMatchObject({
    status: "COMPLETED",
    items: [{ expected_quantity: "90.000", counted_quantity: "89.000", variance: "-1.000" }],
  });

  // The Cashier can complete a count but not approve one. A permitted role on
  // a missing id would get a 404; this is 403 - the authorisation answers
  // before the object is even consulted.
  const refusal = await wirePost(cashierPage, `/api/v1/inventory/counts/${countId}/approve/`);
  expect(refusal.status).toBe(403);
  expect((refusal.body as { error?: { message?: string } }).error?.message).toBe(REFUSED);

  // Approval is the Manager's job and it moves the ledger: 89 on the shelf, an
  // OUT variance movement, and the variance report's first line.
  await page.getByRole("button", { name: "Approve adjustment" }).click();
  await expect(page.getByText("Stock adjustment approved and ledger updated.")).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Count #\d+ · APPROVED/ })).toBeVisible();

  const approved = await readCount(page, countId);
  expect(approved).not.toBeNull();
  expect(approved).toMatchObject({ status: "APPROVED" });

  expect(await readLatestMovement(page)).toMatchObject({
    product: seed.product.id,
    kind: "COUNT_VARIANCE",
    direction: "OUT",
    quantity: "1.000",
    source: "STOCK_COUNT",
  });
  expect(await readStock(page)).toBe(AFTER_RECEIVE - 1);

  const varianceResponse = await page.request.get(
    `/api/v1/reports/inventory/variance/?start=${monthStart()}&end=${todayIso()}`,
  );
  expect(varianceResponse.status()).toBe(200);
  const variance = (await varianceResponse.json()) as {
    lines: number;
    rows: Record<string, unknown>[];
  };
  expect(variance.lines).toBeGreaterThanOrEqual(1);
  expect(variance.rows[0]).toMatchObject({ variance: "-1.000", status: "Approved" });

  await cashierContext.close();
});
