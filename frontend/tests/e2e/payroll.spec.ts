/**
 * Payroll in a real browser, with the API answered at the network layer
 * (roadmap C2; `docs/ADDING_AN_ENDPOINT.md` asks for both kinds of browser
 * evidence).
 *
 * The stubbed project exists for the states a live server will not produce on
 * demand, and payroll is mostly those. A run that has already been approved by
 * somebody else, a month with no run in it at all, and a session whose role has
 * never heard of payroll are all ordinary, all reachable from `POST /runs`, and
 * none of them can be asked for from a database fixture without building a
 * lifecycle into the seed. Here they are as a single answer at the network
 * layer, so what is being asserted is what the screen does with the response
 * rather than what the fixture happened to contain.
 *
 * The session stubs come from `./session`, deliberately: a signed-out answer
 * that used 403 instead of 401 would let a guard pass on a pairing the real API
 * never sends (see the notes there). What is added is the permission list,
 * because role presentation is the behaviour under test.
 */

import { expect, test, type Page } from "@playwright/test";

import { stubCsrf, stubSignedIn, type StubUser } from "./session";

const PAYROLL_VIEWER = "payroll.view_payroll";

/** A manager generates payroll and creates deductions; an owner signs it off. */
const MANAGER: StubUser = {
  id: 2,
  username: "e2e-manager",
  display_name: "Selam Bekele",
  role: "manager",
  role_name: "Manager",
  permissions: [
    PAYROLL_VIEWER,
    "payroll.manage_payroll_employees",
    "payroll.generate_run",
    "payroll.create_deduction",
    "sales.view_sales",
  ],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const OWNER: StubUser = {
  ...MANAGER,
  id: 1,
  username: "e2e-owner",
  role: "owner",
  role_name: "Owner",
  permissions: [...MANAGER.permissions, "payroll.approve_run", "payroll.mark_paid"],
};

/** A barman: a real role, and one that has no business being on this screen. */
const BARMAN: StubUser = {
  ...MANAGER,
  id: 3,
  username: "e2e-barman",
  role: "barman",
  role_name: "Barman",
  permissions: ["products.view_products", "inventory.view_inventory"],
};

const RUN_ID = 7;

const RUN = {
  id: RUN_ID,
  period_month: "2026-10-01",
  status: "GENERATED",
  status_display: "Generated",
  currency: "ETB",
  gross_total: "36000.00",
  deduction_total: "500.00",
  net_total: "35500.00",
  generated_at: "2026-10-01T08:00:00+00:00",
  approved_at: null,
  approved_by: null,
  approved_by_username: null,
  paid_at: null,
  notes: "",
  created_at: "2026-10-01T08:00:00+00:00",
  updated_at: "2026-10-01T08:00:00+00:00",
};

const APPROVED_RUN = {
  ...RUN,
  status: "APPROVED",
  status_display: "Approved",
  approved_at: "2026-10-02T09:30:00+00:00",
  approved_by: 1,
  approved_by_username: "e2e-owner",
};

const LINE = {
  id: 11,
  run: RUN_ID,
  employee: 3,
  full_name: "Abebe Bekele",
  position: "Waiter",
  gross_amount: "36000.00",
  total_deductions: "500.00",
  net_amount: "35500.00",
  currency: "ETB",
  status: "PENDING",
  status_display: "Pending",
  paid_at: null,
  created_at: "2026-10-01T08:00:00+00:00",
  updated_at: "2026-10-01T08:00:00+00:00",
};

function paginated(results: unknown[]) {
  return { count: results.length, page_size: 100, page: 1, pages: 1, results };
}

function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

async function fulfillWith(page_: Page, pattern: string, body: unknown): Promise<void> {
  await page_.route(pattern, (route) => route.fulfill(json(body)));
}

/** The month's runs, ready for whatever the test is about to do with them. */
async function stubRuns(page_: Page, runs: unknown[]): Promise<void> {
  await fulfillWith(page_, "**/api/v1/payroll/runs/*", paginated(runs));
}

/**
 * Count payroll requests without answering any of them.
 *
 * A screen that never asks is the assertion for a role that should not be
 * offered the module, and counting is the only way to say so: "the note is on
 * screen" is also true of a page that fetched everything and then hid it.
 */
function countingPayrollRoute(page_: Page, onCall: () => void) {
  return page_.route("**/api/v1/payroll/**", (route) => {
    onCall();
    return route.fulfill(json(paginated([])));
  });
}

test("a generated month shows its payslips and leaves approval to an owner", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await stubRuns(page, [RUN]);
  await fulfillWith(page, `**/api/v1/payroll/runs/${RUN_ID}/items/*`, paginated([LINE]));

  await page.goto("/payroll/runs");

  await expect(page.getByText("Monthly payroll", { exact: true })).toBeVisible();
  await expect(page.getByText("35,500.00 ETB", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "Abebe Bekele" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "35,500.00 ETB" })).toBeVisible();

  // The manager may generate payroll but not approve it, and the screen says
  // whose signature is missing rather than showing a button that would 403.
  await expect(page.getByText("An owner approves this run before anything is paid.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve run" })).toHaveCount(0);
});

test("an owner approves the run and the screen re-reads what changed", async ({ page }) => {
  let approved = false;
  await stubSignedIn(page, OWNER);
  // The approve POST is an unsafe request, so the client bootstraps a CSRF
  // token from `/auth/csrf/` first; leaving that unstubbed sends it to the real
  // origin's 404 page and the write fails before it leaves the browser.
  await stubCsrf(page);
  await page.route("**/api/v1/payroll/runs/*", (route) =>
    route.fulfill(json(paginated(approved ? [APPROVED_RUN] : [RUN]))),
  );
  await fulfillWith(page, `**/api/v1/payroll/runs/${RUN_ID}/items/*`, paginated([LINE]));
  await page.route(`**/api/v1/payroll/runs/${RUN_ID}/approve/`, (route) => {
    approved = true;
    return route.fulfill(json(APPROVED_RUN));
  });

  await page.goto("/payroll/runs");

  const approve = page.getByRole("button", { name: "Approve run" });
  await expect(approve).toBeVisible();
  await approve.click();

  // The button is only trustworthy because the list is re-read afterwards: a
  // screen that left it up would offer the same action a second time, and the
  // second attempt is a 409 the user did not cause.
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await expect(approve).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Mark as paid" })).toBeVisible();
});

test("a month with no run offers to generate it", async ({ page }) => {
  await stubSignedIn(page, MANAGER);
  await stubRuns(page, []);

  await page.goto("/payroll/runs");

  await expect(page.getByRole("heading", { name: /Generate payroll for/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate run" })).toBeVisible();
  // Nothing exists yet, so there is nothing to show a payslip table about — and
  // no request for lines the run does not have.
  await expect(page.getByText("This run has no lines.")).toHaveCount(0);
});

test("a role with no payroll access is told so and is never asked for the data", async ({
  page,
}) => {
  await stubSignedIn(page, BARMAN);
  let requests = 0;
  await countingPayrollRoute(page, () => {
    requests += 1;
  });

  await page.goto("/payroll/runs");

  await expect(
    page.getByText("Your role does not include payroll. Ask an owner if you need access."),
  ).toBeVisible();
  expect(requests).toBe(0);
});
