/**
 * Reports in a real browser, with the API answered at the network layer
 * (roadmap C4; `docs/ADDING_AN_ENDPOINT.md` asks for both kinds of browser
 * evidence).
 *
 * The report endpoints are read-only projections, so the states worth proving
 * are the screen-side ones: the three tabs render the four responses, the PDF
 * anchor becomes a download, and a role without `finance.view_reports` is told
 * so and is never asked for the data.
 *
 * The session stubs come from `./session`, deliberately: a signed-out answer
 * that used 403 instead of 401 would let a guard pass on a pairing the real API
 * never sends (see the notes there). The permission list is the behaviour under
 * test, so it is added here rather than taken from the default `OWNER`.
 */

import { expect, test } from "@playwright/test";

import { stubCsrf, stubSignedIn, type StubUser } from "./session";

const VIEW_REPORTS = "finance.view_reports";

/** Who reports are for: a viewer with the permission, or nobody. */
const MANAGER: StubUser = {
  id: 2,
  username: "e2e-manager",
  display_name: "Selam Bekele",
  role: "manager",
  role_name: "Manager",
  permissions: [VIEW_REPORTS, "sales.view_sales", "finance.view_balance"],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const BARMAN: StubUser = {
  ...MANAGER,
  id: 3,
  username: "e2e-barman",
  role: "barman",
  role_name: "Barman",
  permissions: [],
};

const FINANCIAL = {
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  currency: "ETB",
  income: { cash: "18450.00", mobile_banking: "5276.50", total: "23726.50" },
  expenses_total: "3500.00",
  expense_breakdown: { Cleaning: "1500.00", Repairs: "2000.00" },
  payroll_total: "35500.00",
  net: "-15273.50",
};

const STOCK_BALANCE = {
  as_of: "2026-10-07",
  in_stock_total: "156",
  products: 2,
  rows: [
    {
      product_id: 1,
      sku: "BTL-001",
      name: "Ambo Water",
      ledger_balance: "40",
      last_counted: null,
      last_counted_on: null,
      delta: null,
    },
    {
      product_id: 2,
      sku: "CRT-001",
      name: "Crate of beer",
      ledger_balance: "116",
      last_counted: "117",
      last_counted_on: "2026-10-05",
      delta: "1",
    },
  ],
};

const VARIANCE = {
  start: "2026-10-01",
  end: "2026-10-31",
  lines: 1,
  expected_total: "40",
  counted_total: "41",
  variance_total: "1",
  rows: [
    {
      stock_count_id: 4,
      reference: "SC-2026-004",
      status: "APPROVED",
      product_id: 1,
      sku: "BTL-001",
      name: "Ambo Water",
      counted_on: "2026-10-05",
      expected_quantity: "40",
      counted_quantity: "41",
      variance: "1",
      note: "Extra crate found",
    },
  ],
};

const PAYROLL_RUN = {
  run_id: 7,
  period_month: "2026-10-01",
  status: "GENERATED",
  status_display: "Generated",
  currency: "ETB",
  employees: 1,
  gross_total: "36000.00",
  deduction_total: "500.00",
  net_total: "35500.00",
};

const PAYROLL = {
  start: "2026-10-01",
  end: "2026-10-31",
  currency: "ETB",
  rows: [PAYROLL_RUN],
  summary: {
    runs: 1,
    gross_total: "36000.00",
    deduction_total: "500.00",
    net_total: "35500.00",
    by_status: [
      {
        ...PAYROLL_RUN,
        runs: 1,
        gross_total: "36000.00",
        deduction_total: "500.00",
        net_total: "35500.00",
      },
    ],
  },
  deductions: { "Salary advance": "500.00" },
};

function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

test("the financial tab renders the balance projection and offers its PDF", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await page.route("**/api/v1/reports/financial/*", (route) => route.fulfill(json(FINANCIAL)));

  await page.goto("/reports");

  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await expect(page.getByText("Income (cash)", { exact: true })).toBeVisible();
  await expect(page.getByText("18,450.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Approved expenses", { exact: true })).toBeVisible();
  await expect(page.getByText("Approved payroll", { exact: true })).toBeVisible();
  await expect(page.getByText("3,500.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("35,500.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("23,726.50 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Download PDF" })).toBeVisible();
});

test("the inventory tab shows the ledger and approved variances", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await page.route("**/api/v1/reports/financial/*", (route) => route.fulfill(json(FINANCIAL)));
  await page.route("**/api/v1/reports/inventory/stock-balance/*", (route) =>
    route.fulfill(json(STOCK_BALANCE)),
  );
  await page.route("**/api/v1/reports/inventory/variance/*", (route) =>
    route.fulfill(json(VARIANCE)),
  );

  await page.goto("/reports");
  await page.getByRole("button", { name: "Inventory" }).click();

  await expect(page.getByText("Stock balance", { exact: true })).toBeVisible();
  await expect(page.getByText("across 2 products.", { exact: false })).toBeVisible();
  await expect(page.getByRole("cell", { name: "BTL-001" }).first()).toBeVisible();
  await expect(page.getByText("not counted", { exact: true })).toBeVisible();

  await expect(page.getByText("Inventory variance", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "#4" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Extra crate found" })).toHaveCount(1);
});

test("the payroll tab renders runs, summary and deductions by type", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await page.route("**/api/v1/reports/financial/*", (route) => route.fulfill(json(FINANCIAL)));
  await page.route("**/api/v1/reports/payroll/*", (route) => route.fulfill(json(PAYROLL)));

  await page.goto("/reports");
  await page.getByRole("button", { name: "Payroll" }).click();

  await expect(page.getByRole("cell", { name: "October 2026" })).toBeVisible();
  await expect(page.getByText("Generated", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(page.getByText("Net total", { exact: true })).toBeVisible();
  await expect(page.getByText("35,500.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Salary advance", { exact: true })).toBeVisible();
  await expect(page.getByText("500.00 ETB", { exact: true }).first()).toBeVisible();
});

test("a role without reports access is told so and is never asked for the data", async ({
  page,
}) => {
  await stubSignedIn(page, BARMAN);
  let requests = 0;
  await page.route("**/api/v1/reports/**", (route) => {
    requests += 1;
    return route.fulfill(json({}));
  });

  await page.goto("/reports");

  await expect(
    page.getByText("Your role does not include reports. Ask an owner if you need access."),
  ).toBeVisible();
  expect(requests).toBe(0);
});

test("the PDF anchor downloads a report from the period on screen", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await stubCsrf(page);
  await page.route("**/api/v1/reports/financial/*", (route) => route.fulfill(json(FINANCIAL)));
  await page.route("**/api/v1/reports/payroll/*", (route) => route.fulfill(json(PAYROLL)));
  // The download URL is the same route with `export=pdf`; the answer changes
  // shape the way the backend's does - an attachment rather than JSON.
  await page.route("**/api/v1/reports/payroll/*", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("export") !== "pdf") return route.fulfill(json(PAYROLL));
    return route.fulfill({
      status: 200,
      contentType: "application/pdf",
      headers: {
        "content-disposition": 'attachment; filename="payroll-2026-10-01-2026-10-07.pdf"',
      },
      body: "%PDF-1.4\n% test export\n",
    });
  });

  await page.goto("/reports");
  await page.getByRole("button", { name: "Payroll" }).click();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PDF" }).last().click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^payroll-.*\.pdf$/);
});
