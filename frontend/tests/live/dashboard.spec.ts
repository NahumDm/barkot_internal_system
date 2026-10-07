/**
 * Roadmap C6's dashboard, read in a browser against the real backend.
 *
 * The stubbed spec at `tests/e2e/dashboard.spec.ts` proves the screen calls the
 * route it calls and phrases its two null states apart. Nothing here intercepts
 * a request: the summary is read over HTTP with the browser's own session
 * cookie, and each tile is then compared against the endpoint that owns it —
 * the balance for finance, the stock-balance report for inventory — so the
 * dashboard agreeing with itself is not the evidence.
 *
 * Ordering is load-bearing, and this file is where it lands: the suite runs
 * alphabetically, so `b5-sale` has already recorded and voided its sale (the
 * till is empty and the shelf is back to opening stock) while `payroll` has not
 * yet generated a run. That is exactly the state worth pinning: income of
 * `0.00` because a voided sale never counts, and a permitted Owner's payroll
 * tile as `null` because there is no run yet — which the screen must not
 * describe as a permission refusal.
 *
 * Two stories, two roles of the screen:
 *
 * 1. The Owner reads the whole summary, and the finance and inventory tiles
 *    are byte-equal to the reports that own them; the sales tile is empty
 *    because the only sale ever made was voided.
 * 2. A Cashier's summary carries sales and stock, and `null` finance and
 *    payroll that the screen words as refusals — with the server's own
 *    answer, not the UI's, deciding what each section is.
 *
 * Both stories sign in again after the earlier specs, so the first attempt is
 * often throttled by A5; the shared `signIn` waits the window out instead of
 * this suite being reordered or re-seeded.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";

const seed = readSeedSummary();

/** The shape apps/dashboard/serializers.py answers with, section by section. */
interface DashboardBody {
  period: { start: string; end: string; currency: string };
  sales: {
    total: string;
    cash: string;
    mobile_banking: string;
    transactions: number;
    recent: unknown[];
  } | null;
  inventory: { as_of: string; in_stock_total: string; products: number } | null;
  finance: {
    currency: string;
    income: { cash: string; mobile_banking: string; total: string };
    expenses_total: string;
    payroll_total: string;
    net: string;
  } | null;
  payroll: { period_month: string; status: string; net_total: string } | null;
}

test.describe.configure({ mode: "serial" });

test("the Owner's tiles reconcile with the balance and stock reports", async ({ page }) => {
  // The sign-in may have to sit out the tail of the A5 login window, which can
  // take a minute in itself; the suite's default test timeout is far shorter.
  test.setTimeout(240_000);

  // signIn lands on /dashboard, which is also this screen — so the only wait
  // needed is the one for the data panels rather than the header.
  await signIn(page, seed.owner);
  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();

  const dash = await readAs<DashboardBody>(page, "/api/v1/dashboard/");

  // The period is the server's current business month-to-date: it can only
  // start on the first, and every bound was produced by the server's own
  // calendar rather than the browser's.
  expect(dash.period.start).toMatch(/^\d{4}-\d{2}-01$/);
  expect(dash.period.end >= dash.period.start).toBe(true);

  // --- Sales: the b5 story recorded one sale and then voided it, and a voided
  // row never reaches a total or a ledger slice. The empty till, said twice.
  expect(dash.sales).toMatchObject({ total: "0.00", cash: "0.00", transactions: 0 });
  expect(dash.sales?.recent).toHaveLength(0);
  await expect(page.getByText("No sales in this period.")).toBeVisible();

  // --- Inventory: the shelf is the opening stock the void put back, and the
  // tile is character-identical to the C4 stock-balance report as of the same
  // day — including the fixed-point formatting, which is why the comparison is
  // on the whole section rather than on a number parsed out of it.
  const inventory = dash.inventory;
  expect(inventory).not.toBeNull();
  expect(inventory?.products).toBe(1);
  expect(Number(inventory?.in_stock_total)).toBe(Number(seed.product.opening_stock));
  const stock = await readAs<{
    as_of: string;
    in_stock_total: string;
    products: number;
  }>(page, `/api/v1/reports/inventory/stock-balance/?date=${dash.period.end}`);
  expect(dash.inventory).toEqual({
    as_of: stock.as_of,
    in_stock_total: stock.in_stock_total,
    products: stock.products,
  });
  await expect(
    page.getByText(inventory?.in_stock_total ?? "missing", { exact: true }).first(),
  ).toBeVisible();

  // --- Finance: the same object the balance endpoint answers with for the
  // period the dashboard printed, over the same session. Income is nil (the
  // voided sale never counts) and no run has been approved, so the lot nets to
  // nothing — which is the reconciliation, not an absence of one.
  const finance = dash.finance;
  expect(finance).not.toBeNull();
  expect(finance).toMatchObject({
    currency: "ETB",
    income: { cash: "0.00", mobile_banking: "0.00", total: "0.00" },
    expenses_total: "0.00",
    payroll_total: "0.00",
    net: "0.00",
  });
  const balance = await readAs<Record<string, unknown>>(
    page,
    `/api/v1/finance/balance/?start=${dash.period.start}&end=${dash.period.end}`,
  );
  expect(dash.finance).toEqual(balance);
  // The metric row and the finance panel each print it.
  await expect(page.getByText("Net result", { exact: true })).toHaveCount(2);

  // --- Payroll: this file runs before payroll.spec.ts generates the run, so
  // the Owner's tile is `null` for want of data, and the screen must say so as
  // an empty state rather than as a refusal the Owner was never subject to.
  expect(dash.payroll).toBeNull();
  await expect(
    page.getByText("No payroll run has been generated yet.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Payroll is not shown for your role.", { exact: true })).toHaveCount(
    0,
  );
});

test("a Cashier's summary carries sales and stock, and refuses the rest on the wire", async ({
  page,
}) => {
  test.setTimeout(240_000);

  await signIn(page, seed.cashier);
  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();

  const dash = await readAs<DashboardBody>(page, "/api/v1/dashboard/");
  expect(dash.sales).not.toBeNull();
  expect(dash.inventory).not.toBeNull();
  expect(dash.finance).toBeNull();
  expect(dash.payroll).toBeNull();

  // The screen phrases the refusals as refusals, and the figures behind them
  // are never drawn — the tile slot says its piece and there is no number.
  await expect(
    page.getByText("Finance is not shown for your role.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Payroll is not shown for your role.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Net result", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open payroll" })).toHaveCount(0);
});

/** GET a response over the browser's own session and assert it succeeded. */
async function readAs<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path);
  expect(response.status()).toBe(200);
  return (await response.json()) as T;
}
