/**
 * Dashboard in a real browser, with the API answered at the network layer
 * (roadmap C6; `docs/ADDING_AN_ENDPOINT.md` asks for both kinds of browser
 * evidence).
 *
 * The dashboard is one read-only aggregate whose sections the peer domains
 * already decide, so the states worth proving here are the screen-side ones:
 * every section renders when present, a role whose sections arrive `null` is
 * told so and is never asked for the data, a `null` that means "no payroll run
 * yet" reads differently from one that means "not your role", and the default
 * request carries the local month-to-date the screen is showing.
 *
 * The session stubs come from `./session`, deliberately: a signed-out answer
 * that used 403 instead of 401 would let a guard pass on a pairing the real API
 * never sends (see the notes there). The dashboard reads permissions only on
 * the server, so these stubs prove the client renders what the wire says.
 */

import { expect, test } from "@playwright/test";

import { stubSignedIn, type StubUser } from "./session";

const MANAGER: StubUser = {
  id: 2,
  username: "e2e-manager",
  display_name: "Selam Bekele",
  role: "manager",
  role_name: "Manager",
  // The real Manager's slice of the matrix (backend/apps/accounts/permissions).
  permissions: [
    "sales.view_sales",
    "inventory.view_inventory",
    "finance.view_reports",
    "payroll.view_payroll",
  ],
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
  // Stock and sales, and nothing that would open the finance or payroll tiles.
  permissions: [
    "products.view_products",
    "inventory.view_inventory",
    "inventory.receive_stock",
    "inventory.record_breakage",
    "sales.view_sales",
  ],
};

const DASHBOARD = {
  period: { start: "2026-10-01", end: "2026-10-07", currency: "ETB" },
  sales: {
    total: "23726.50",
    cash: "18450.00",
    mobile_banking: "5276.50",
    transactions: 2,
    recent: [
      {
        id: 1,
        reference: "b5-0001",
        status: "COMPLETED",
        status_display: "Completed",
        sold_at: "2026-10-07T10:00:00Z",
        total: "120.00",
        currency: "ETB",
        payment_status: "PAID",
        payment_status_display: "Paid",
        item_count: 2,
        created_at: "2026-10-07T10:00:00Z",
      },
      {
        id: 2,
        reference: "b5-0002",
        status: "COMPLETED",
        status_display: "Completed",
        sold_at: "2026-10-06T10:00:00Z",
        total: "45.00",
        currency: "ETB",
        payment_status: "PENDING",
        payment_status_display: "Pending",
        item_count: 1,
        created_at: "2026-10-06T10:00:00Z",
      },
    ],
  },
  inventory: { as_of: "2026-10-07", in_stock_total: "156", products: 2 },
  finance: {
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    currency: "ETB",
    income: { cash: "18450.00", mobile_banking: "5276.50", total: "23726.50" },
    expenses_total: "3500.00",
    expense_breakdown: { Cleaning: "1500.00", Repairs: "2000.00" },
    payroll_total: "35500.00",
    net: "-15273.50",
  },
  payroll: {
    id: 7,
    period_month: "2026-10-01",
    status: "GENERATED",
    status_display: "Generated",
    gross_total: "36000.00",
    deduction_total: "500.00",
    net_total: "35500.00",
    generated_at: "2026-10-07T10:00:00Z",
    approved_at: null,
    approved_by_username: null,
  },
};

const BARMAN_DASHBOARD = {
  period: { start: "2026-10-01", end: "2026-10-07", currency: "ETB" },
  sales: DASHBOARD.sales,
  inventory: DASHBOARD.inventory,
  finance: null,
  payroll: null,
};

function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

test("a manager sees every section across the four panels", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await page.route("**/api/v1/dashboard**", (route) => route.fulfill(json(DASHBOARD)));

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("23,726.50 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("3,500.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Net result", { exact: true })).toHaveCount(2);

  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();
  await expect(page.getByText("b5-0001", { exact: true })).toBeVisible();
  await expect(page.getByText("PENDING", { exact: false })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
  await expect(page.getByText("156", { exact: true }).first()).toBeVisible();

  await expect(page.getByRole("heading", { name: "Finance" })).toBeVisible();
  await expect(page.getByText("-15,273.50 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Cleaning", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Payroll" })).toBeVisible();
  await expect(page.getByText("October 2026", { exact: true })).toBeVisible();
  await expect(page.getByText("Generated", { exact: true })).toBeVisible();
  await expect(page.getByText("36,000.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Open payroll" })).toBeVisible();
});

test("a shopfloor role is told the finance and payroll panels are not shown", async ({ page }) => {
  await stubSignedIn(page, BARMAN);
  await page.route("**/api/v1/dashboard**", (route) => route.fulfill(json(BARMAN_DASHBOARD)));

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Inventory" })).toBeVisible();
  await expect(
    page.getByText("Finance is not shown for your role.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Payroll is not shown for your role.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Net result", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open finance" })).toHaveCount(0);
});

test("a permitted role with no payroll run yet gets the empty state, not a denial", async ({
  page,
}) => {
  await stubSignedIn(page, MANAGER);
  await page.route("**/api/v1/dashboard**", (route) =>
    route.fulfill(json({ ...DASHBOARD, payroll: null })),
  );

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Finance" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Payroll" })).toHaveCount(0);
  await expect(
    page.getByText("No payroll run has been generated yet.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Payroll is not shown for your role.", { exact: true })).toHaveCount(
    0,
  );
});

test("the default request carries the local month-to-date it is showing", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  const requested: string[] = [];
  await page.route("**/api/v1/dashboard**", (route) => {
    requested.push(route.request().url());
    return route.fulfill(json(DASHBOARD));
  });

  await page.goto("/dashboard");

  // The header renders from the shell, so wait for the data before counting
  // requests: the heading is visible long before the effect's fetch fires.
  await expect(page.getByRole("heading", { name: "Sales" })).toBeVisible();
  expect(requested).toHaveLength(1);

  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const expectedStart = `${month}-01`;
  const expectedEnd = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  expect(requested[0]).toContain(`start=${expectedStart}`);
  expect(requested[0]).toContain(`end=${expectedEnd}`);
});
