/**
 * Roadmap C4's date-filtered, exportable reports, read in a browser against the
 * real backend.
 *
 * The stubbed spec at `tests/e2e/reports.spec.ts` proves the screen calls the
 * routes it calls. Nothing here intercepts a request: every number comes from
 * the seeded database and the earlier live stories, read back over HTTP with the
 * browser's own session cookie so the screen agreeing with itself is not the
 * evidence.
 *
 * This spec runs after `b5-sale.spec.ts` and `payroll.spec.ts` (alphabetical,
 * serial per project), so the state it asserts on is the one those left behind:
 * the sale was voided back to opening stock, and the current month's payroll run
 * is APPROVED and PAID with the seed's one 500.00 advance recorded against it
 * (scenario §23.1.4). That is exactly the projection worth asserting: the
 * financial report counts the run's *net* pay - gross minus the deduction - even
 * though the manager could never have approved one, and the variance report stays
 * empty because no count was ever recorded.
 *
 * One successful sign-in, as the Manager (the only role this screen needs), and
 * it arrives last by design: A5 allows five login attempts a minute per address
 * and the earlier stories already took theirs, so this one is often throttled on
 * the first try. A throttled attempt costs no budget - DRF refuses the request
 * before it can be granted a slot - which is exactly why `signIn` retries after
 * the window clears instead of this suite being reordered or re-seeded to dodge
 * the limit.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";

const seed = readSeedSummary();

/** The first day of the current calendar month - what the screen defaults to. */
function monthStart(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

/** Today, as the screen's stock "as of" date defaults to it. */
function todayISO(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** The month the seeded run belongs to, as the screen prints it. */
function monthLabel(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

test.describe.configure({ mode: "serial" });

test("the Manager reads financial, inventory and payroll, and downloads the CSV", async ({
  page,
}) => {
  // The sign-in may have to sit out the tail of the A5 login window, which can
  // take a minute in itself; the suite's default test timeout is far shorter.
  test.setTimeout(240_000);

  await signIn(page, seed.manager);
  const wage = seed.payroll.monthly_wage;
  // The payroll story deducts a 500.00 advance from Seble's line before the
  // Owner approves it, so every figure "the run is worth" below is the net of
  // that deduction - the numbers exist on the server and this spec derives its
  // own from the same inputs rather than echoing a fifth copy.
  const DEDUCTION = "500.00";
  const net = (Number(wage) - Number(DEDUCTION)).toFixed(2);
  // The screen prints money()'s thousand-separated form; the API sends the raw
  // fixed-point string. The two are asserted against separately.
  const wageDisplay = Number(wage).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const netDisplay = Number(net).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  // --- Financial: income is nil (the b5 sale was voided), payroll is the
  // approved run's *net* this month, and the balance therefore goes negative by
  // that net - a 12000 wage with a 500 advance moves the books by 11500.
  await page.goto("/reports");

  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await expect(page.getByText("Income (cash)", { exact: true })).toBeVisible();
  await expect(page.getByText("Approved payroll", { exact: true })).toBeVisible();
  await expect(page.getByText(`${netDisplay} ETB`, { exact: true }).first()).toBeVisible();

  const financial = await readPage(page, "/reports/financial/");
  expect(financial).toMatchObject({
    currency: "ETB",
    income: { cash: "0.00", mobile_banking: "0.00", total: "0.00" },
    expenses_total: "0.00",
    // An approved-and-paid run counts; a mere proposal never would (§14.x). The
    // figure is the sum of the line nets, so the deduction is already inside it.
    payroll_total: net,
    net: `-${net}`,
  });

  // --- Inventory: the product's ledger is what the voided sale left it - the
  // opening stock - and no count was ever recorded, so variances are empty.
  await page.getByRole("button", { name: "Inventory" }).click();

  await expect(page.getByText("Stock balance", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: seed.product.sku })).toBeVisible();
  await expect(page.getByText("across 1 product.", { exact: false })).toBeVisible();
  await expect(page.getByText("Inventory variance", { exact: true })).toBeVisible();
  await expect(page.getByText("No approved variances in this period.")).toBeVisible();

  const balance = await readBalance(page, "/reports/inventory/stock-balance/");
  expect(balance).toMatchObject({ products: 1 });
  const variance = await readPage(page, "/reports/inventory/variance/");
  expect(variance).toMatchObject({ start: monthStart(), end: expect.any(String), lines: 0 });

  // --- Payroll: the run the manager generated is on screen, now approved and
  // paid by the previous story. Its tiles carry the gross, the deduction and the
  // net, and the deductions-by-type panel names the advance that explains it.
  await page.getByRole("button", { name: "Payroll" }).click();

  await expect(page.getByRole("cell", { name: monthLabel() })).toBeVisible();
  await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Runs", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("1", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(`${wageDisplay} ETB`, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(`${DEDUCTION} ETB`, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(`${netDisplay} ETB`, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Salary advance", { exact: true }).first()).toBeVisible();

  const payroll = await readPage(page, "/reports/payroll/");
  expect(payroll).toMatchObject({
    currency: "ETB",
    summary: { runs: 1, gross_total: wage, deduction_total: DEDUCTION, net_total: net },
  });
  const payrollDeductions = (payroll as { deductions: Record<string, string> }).deductions;
  expect(payrollDeductions).toMatchObject({ "Salary advance": DEDUCTION });
  const statuses = (payroll as { summary: { by_status: { status: string }[] } }).summary.by_status;
  expect(statuses.find((bucket) => bucket.status === "PAID")).toBeDefined();

  // --- Export: the anchor becomes an attachment whose rows are the same money
  // the screen printed, downloaded with the browser's own session.
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^payroll-.*\.csv$/);

  const stream = await download.createReadStream();
  expect(stream).not.toBeNull();
  const chunks: Buffer[] = [];
  for await (const chunk of stream as AsyncIterable<Buffer>) chunks.push(chunk);
  const csv = Buffer.concat(chunks).toString("utf8");
  expect(csv).toContain(monthStart());
  expect(csv).toContain("PAID");
  expect(csv).toContain(wage);
  expect(csv).toContain(DEDUCTION);
  expect(csv).toContain(net);
});

/** GET a report over the browser's own session and assert it succeeded. */
async function readPage(page: Page, path: string): Promise<Record<string, unknown>> {
  const response = await page.request.get(
    `/api/v1${path}?start=${monthStart()}&end=${monthStart()}`,
  );
  expect(response.status()).toBe(200);
  return (await response.json()) as Record<string, unknown>;
}

/** GET the stock-balance report, which keys on a single date, not a window. */
async function readBalance(page: Page, path: string): Promise<Record<string, unknown>> {
  const response = await page.request.get(`/api/v1${path}?date=${todayISO()}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as Record<string, unknown>;
}
