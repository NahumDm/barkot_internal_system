/**
 * Roadmap C5's month-with-a-status is only worth shipping if a browser, talking
 * to this Django, can walk a month through its whole lifecycle and have the
 * backend agree at each step.
 *
 * The stubbed spec at `tests/e2e/payroll.spec.ts` proves the screen calls the
 * routes it calls. That suite concedes line by line what a real payment
 * actually looks like, because a stub is the author's guess about what Django
 * would have said. Nothing here intercepts a request: the seed created Seble's
 * row, Django pays it, and the approvals below are real writes through the
 * roles' real permissions.
 *
 * The story runs in two sign-ins, because the two acts are owned by different
 * people (spec A14.1):
 *
 * 1. The Manager generates the current month, records the one deduction the seed
 *    allows against it (a salary advance with a written reason), and is refused
 *    "Approve" - the owner-only button simply is not shown - while the payslip on
 *    screen is the seeded wage minus what the deduction took, not a number typed
 *    by a test (scenario §23.1.4: the reason is captured and the net reconciles).
 * 2. The Owner approves the run and then marks it paid. Each step is read back
 *    over HTTP with the browser's own cookie, because a screen agreeing with
 *    itself is not evidence that status moved.
 *
 * The run period is the current month because the screen defaults to it and
 * the seed resets between runs, so "the generated run" is always unique.
 *
 * Sign-in goes through the shared helper in `./signin`, which waits out A5's
 * five-attempts-a-minute window rather than failing on the first 429: with C6's
 * dashboard spec adding two more logins ahead of this file, the suite now runs
 * past the budget a single window allows. Each of these tests therefore sets
 * its own timeout, because a throttled retry costs a full minute.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";

const seed = readSeedSummary();

/**
 * The status chip in the run's summary box.
 *
 * A bare `getByText("Paid")` would also match the KPI label of that name, and a
 * `span`-only filter would also match the payslip rows' status chips, which carry
 * the same "Approved"/"Paid" text once the run moves. The summary box is the one
 * place on screen that always shows the audit trail, so the chip is found as the
 * sibling of the "Generated on ..." line - which only a run, never a row, has.
 */
function runStatus(page: Page, status: string) {
  return page
    .getByText(/^Generated on/)
    .locator("..")
    .getByText(status, { exact: true });
}

/** The generated run for this calendar month, read back over HTTP. */
async function readRun(page: Page): Promise<Record<string, unknown> | null> {
  const response = await page.request.get("/api/v1/payroll/runs/?page_size=100");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return body.results.find((run) => String(run.period_month).startsWith(month)) ?? null;
}

/** The one payslip line of a run, read back over HTTP. */
async function readItem(page: Page, runId: number): Promise<Record<string, unknown> | null> {
  const response = await page.request.get(`/api/v1/payroll/runs/${runId}/items/?page_size=100`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { results: Record<string, unknown>[] };
  return body.results[0] ?? null;
}

test.describe.configure({ mode: "serial" });

test("a Manager generates the month and cannot approve it", async ({ page }) => {
  // The sign-in may have to sit out the tail of the A5 login window.
  test.setTimeout(240_000);

  await signIn(page, seed.manager);
  await page.goto("/payroll/runs");

  // Nothing for this month yet - only the generation form.
  await expect(page.getByText(/Generate payroll for/)).toBeVisible();
  await expect(runStatus(page, "Generated")).toHaveCount(0);

  await page.getByRole("button", { name: "Generate run" }).click();

  // The run appears with a single payslip at the seeded wage.
  await expect(runStatus(page, "Generated")).toBeVisible();
  const employeeRow = page.getByRole("row").filter({ hasText: seed.payroll.full_name });
  await expect(employeeRow).toHaveCount(1);
  await expect(employeeRow).toContainText("12,000.00 ETB");

  // The money the screen shows is the seeded wage, served by Django rather
  // than assembled by the test - the seed wrote "12000.00", the serializers
  // round-trip fixed-point money, and the two match.
  const run = await readRun(page);
  expect(run).not.toBeNull();
  expect(run).toMatchObject({
    status: "GENERATED",
    gross_total: seed.payroll.monthly_wage,
    net_total: seed.payroll.monthly_wage,
  });
  const item = await readItem(page, Number((run as { id: number }).id));
  expect(item).not.toBeNull();
  expect(item).toMatchObject({
    full_name: seed.payroll.full_name,
    gross_amount: seed.payroll.monthly_wage,
    net_amount: seed.payroll.monthly_wage,
    total_deductions: "0.00",
  });

  // The Manager's permissions stop at generation: the button is not rendered
  // at all, and the screen says who has to sign it.
  await expect(page.getByRole("button", { name: "Approve run" })).toHaveCount(0);
  await expect(page.getByText("An owner approves this run before anything is paid.")).toBeVisible();

  // --- The deduction half of scenario §23.1.4: a salary advance with a reason.
  // The screens it must reconcile are the deductions register and the run -
  // the reason is captured as a first-class column, and the payslip's net pay
  // drops by exactly what was taken off it.
  await page.goto("/payroll/deductions");
  await page.getByLabel("Amount (ETB)").fill("500");
  await page.getByLabel("Reason").fill("Transport advance agreed by the owner.");
  await page.getByRole("button", { name: "Record deduction" }).click();

  await expect(
    page.getByText("500.00 ETB deducted from Seble Worku.", { exact: true }),
  ).toBeVisible();
  const deductionRow = page.getByRole("row").filter({ hasText: seed.payroll.full_name });
  await expect(deductionRow).toContainText("Salary advance");
  await expect(deductionRow).toContainText("500.00 ETB");
  await expect(deductionRow).toContainText("Transport advance agreed by the owner.");

  // Back on the run, the payslip still carries the gross, the deduction column
  // is populated and the net is the difference - the two screens disagreeing
  // would be exactly the bug this story exists to catch.
  await page.goto("/payroll/runs");
  const employeeRowAfter = page.getByRole("row").filter({ hasText: seed.payroll.full_name });
  await expect(employeeRowAfter).toContainText("12,000.00 ETB");
  await expect(employeeRowAfter).toContainText("500.00 ETB");
  await expect(employeeRowAfter).toContainText("11,500.00 ETB");

  const withDeduction = await readRun(page);
  expect(withDeduction).not.toBeNull();
  expect(withDeduction).toMatchObject({
    status: "GENERATED",
    gross_total: seed.payroll.monthly_wage,
    deduction_total: "500.00",
    net_total: "11500.00",
  });
  const itemAfter = await readItem(page, Number((withDeduction as { id: number }).id));
  expect(itemAfter).not.toBeNull();
  expect(itemAfter).toMatchObject({
    full_name: seed.payroll.full_name,
    gross_amount: seed.payroll.monthly_wage,
    total_deductions: "500.00",
    net_amount: "11500.00",
  });

  // The month is still a proposal while it waits for the Owner, so the
  // generation-permission surveillance from before the deduction still holds.
  await expect(page.getByRole("button", { name: "Approve run" })).toHaveCount(0);
  await expect(page.getByText("An owner approves this run before anything is paid.")).toBeVisible();
});

test("the Owner signs off a month Django really generated", async ({ page }) => {
  // The sign-in may have to sit out the tail of the A5 login window.
  test.setTimeout(240_000);

  await signIn(page, seed.owner);
  await page.goto("/payroll/runs");

  // The Manager's work from the previous step is still standing; the screen
  // defaults to the current month, which is the generated one.
  await expect(runStatus(page, "Generated")).toBeVisible();

  await page.getByRole("button", { name: "Approve run" }).click();

  await expect(runStatus(page, "Approved")).toBeVisible();
  await expect(runStatus(page, "Generated")).toHaveCount(0);
  await expect(page.getByText(/Approved by e2e-owner/)).toBeVisible();

  const approved = await readRun(page);
  expect(approved).not.toBeNull();
  expect(approved).toMatchObject({ status: "APPROVED" });

  // The approved month is now the screen's business to hand over the money.
  await page.getByRole("button", { name: "Mark as paid" }).click();

  await expect(runStatus(page, "Paid")).toBeVisible();
  await expect(page.getByText("Nothing left to do for this month.")).toBeVisible();

  const paid = await readRun(page);
  expect(paid).not.toBeNull();
  expect(paid).toMatchObject({ status: "PAID" });
});
