/**
 * Role-denied controls and direct URLs, proven in the browser shell.
 *
 * The live suite proves the server's refusals; these stubs prove the screen does
 * not offer an action the matrix withholds, and that a bookmark or a hand-typed
 * URL lands on an explanation instead of a form that will fail on submit. The
 * users below carry the matrix's real permission sets for their role.
 */

import { expect, test } from "@playwright/test";

import { stubSignedIn, type StubUser } from "./session";

const BARMAN: StubUser = {
  id: 4,
  username: "e2e-barman",
  display_name: "Bereket Barman",
  role: "barman",
  role_name: "Barman",
  permissions: [
    "products.view_products",
    "inventory.view_inventory",
    "inventory.receive_stock",
    "inventory.record_breakage",
    "bono.view_bono",
  ],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const CASHIER: StubUser = {
  id: 3,
  username: "e2e-cashier",
  display_name: "Chaltu Cashier",
  role: "cashier",
  role_name: "Cashier",
  permissions: [
    "products.view_products",
    "inventory.view_inventory",
    "inventory.complete_stock_count",
    "sales.view_sales",
    "sales.create_sale",
    "bono.view_bono",
    "bono.submit_report",
  ],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function pageOf(results: unknown[]) {
  return { count: results.length, page_size: 200, page: 1, pages: 1, results };
}

const PRODUCT = {
  id: 1,
  category: 1,
  category_name: "Beer",
  name: "Heineken",
  sku: "BEER-HEIN-001",
  unit: "bottle",
  quantity_mode: "WHOLE",
  bottles_per_crate: 24,
  is_stock_tracked: true,
  is_active: true,
  description: "",
  current_price: {
    id: 1,
    unit_price: "100.00",
    currency: "ETB",
    effective_from: "2026-01-01T00:00:00+00:00",
    is_active: true,
    created_at: "2026-01-01T00:00:00+00:00",
  },
  current_stock: "10.000",
};

const BONO_TYPE = {
  id: 1,
  code: "11111111-1111-1111-1111-111111111111",
  name: "House Bono",
  color: "#8E192F",
  selling_price: "100.00",
  currency: "ETB",
  is_active: true,
  notes: "",
  active_pairings: [],
  pending_review_count: 0,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
};

const BONO_SUMMARY = {
  operational_date: "2026-10-23",
  day_status: "OPEN",
  operations_locked: false,
  bono_totals: [],
  staff_balances: [],
  latest_report: null,
  in_progress_dates: [],
};

const SALE = {
  id: 1,
  reference: "S-2026-001",
  status: "COMPLETED",
  status_display: "Completed",
  sold_at: "2026-10-01T12:00:00+00:00",
  total: "100.00",
  amount_paid: "100.00",
  currency: "ETB",
  payment_status: "PAID",
  payment_status_display: "Paid",
  balance_due: "0.00",
  note: "",
  item_count: 1,
  items: [],
  payments: [],
  voided_at: null,
  void_reason: "",
  created_at: "2026-10-01T12:00:00+00:00",
  updated_at: "2026-10-01T12:00:00+00:00",
};

/**
 * One row, not an empty page: the table's Actions column and its Void buttons
 * only exist once a row renders, so an empty stub would make the refusal checks
 * pass without ever exercising the control.
 */
async function stubLists(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/v1/products/**", (route) => route.fulfill(json(pageOf([PRODUCT]))));
  await page.route("**/api/v1/products/categories/**", (route) => route.fulfill(json(pageOf([]))));
  await page.route("**/api/v1/sales/**", (route) => route.fulfill(json(pageOf([SALE]))));
}

async function stubBono(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/v1/bono/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/summary/")) return route.fulfill(json(BONO_SUMMARY));
    if (path.endsWith("/types/")) return route.fulfill(json(pageOf([BONO_TYPE])));
    return route.fulfill(json(pageOf([])));
  });
}

test("a Barman is never offered sales, count, catalogue writes or Bono custody actions", async ({
  page,
}) => {
  await stubSignedIn(page, BARMAN);
  await stubLists(page);
  await stubBono(page);

  await page.goto("/bono");
  await expect(
    page.getByRole("heading", { name: "Custody and daily reconciliation" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Sales", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Custody actions" })).toHaveCount(0);

  await page.goto("/bono/reports");
  await expect(page.getByRole("heading", { name: "Daily reports" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Prepare a report" })).toHaveCount(0);

  await page.goto("/inventory/products");
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Product" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
});

test("a Barman's allowed screens still render", async ({ page }) => {
  await stubSignedIn(page, BARMAN);
  await stubLists(page);

  await page.goto("/inventory/receive");
  await expect(page.getByLabel(/Supplier/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save record" })).toBeVisible();

  await page.goto("/inventory/breakage");
  await expect(page.getByRole("heading", { name: "Breakage & waste" })).toBeVisible();
});

test("direct URLs a Barman may not open explain the refusal", async ({ page }) => {
  // Nine cold production renders on one page; the default 30s is not enough.
  test.setTimeout(120_000);
  await stubSignedIn(page, BARMAN);
  await stubLists(page);
  await stubBono(page);

  const refusals: Array<[string, string]> = [
    ["/sales/transactions/new", "Your role does not include recording sales."],
    ["/inventory/counts", "Your role does not include this inventory action."],
    ["/inventory/products/new", "Your role does not include managing the product catalogue."],
    ["/inventory/categories", "Your role does not include managing product categories."],
    ["/finance", "Your role does not include viewing finance."],
    ["/bono/configuration", "Your role does not include Bono configuration."],
    ["/reports", "Your role does not include reports."],
    ["/payroll/runs", "Your role does not include payroll."],
    ["/employees", "Your role does not include the employee register."],
    ["/settings", "Your role does not include account settings."],
  ];

  for (const [route, message] of refusals) {
    await page.goto(route);
    await expect(page.getByText(message), route).toBeVisible();
  }
});

test("a Cashier keeps the sale and count actions the matrix grants", async ({ page }) => {
  await stubSignedIn(page, CASHIER);
  await stubLists(page);
  await stubBono(page);

  await page.goto("/sales");
  await expect(page.getByRole("button", { name: "New Sale" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Actions" })).toHaveCount(0);

  await page.goto("/sales/transactions/new");
  await expect(page.getByText("Your role does not include recording sales.")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "New Sale" })).toBeVisible();

  await page.goto("/bono/reports");
  await expect(page.getByRole("heading", { name: "Prepare a report" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Daily reports" })).toBeVisible();

  await page.goto("/inventory/counts");
  await expect(page.getByRole("button", { name: "Open count" })).toBeVisible();

  await page.goto("/inventory/receive");
  await expect(page.getByText("Your role does not include this inventory action.")).toBeVisible();
});
