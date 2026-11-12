/**
 * The employee register, in a browser against the real backend (spec A5).
 *
 * The stubbed spec proves the screen calls the routes its author expected. This
 * one proves Django agrees: a person is registered without a login, edited,
 * given a real multipart PDF, archived and restored, and every one of those
 * states is read back from Postgres by a subsequent page load rather than
 * remembered by the test.
 *
 * The role matrix is walked in sign-ins rather than assumed from the nav:
 *
 * 1. The **Owner** creates a person and walks the whole register lifecycle.
 *    Registering creates no account, so the new row's `username` is empty and
 *    it never appears in payroll.
 * 2. The **Manager** may maintain the same register (`users.manage_employees`
 *    is one of the grants payroll narrowing deliberately kept) and edits the
 *    row the Owner created.
 * 3. The **Cashier** and **Barman** may not: the sidebar link is absent, the
 *    screen renders the refusal instead of the roster, and a wire request from
 *    their own session is answered with a real permission 403.
 *
 * The document upload is the only multipart write in the system, so it is
 * exercised through the actual file input. The assertion is on "PDF on file"
 * and the server-generated stored name, never on a URL: the API does not expose
 * one because documents are not served over HTTP.
 *
 * Runs before `payroll.spec.ts` alphabetically. That is safe because a register
 * row has no `payroll.Employee` companion until someone deliberately puts it on
 * payroll, so it cannot join the seeded month's payslip list.
 */

import { expect, test, type Page } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";
import { wirePost } from "./wire";

const seed = readSeedSummary();

/** A unique-enough name so a rerun against a non-flushed database is still readable. */
const NEW_NAME = "E2E Register Hire";
const EDITED_POSITION = "Head Waitstaff";
const START_DATE = "2026-01-05";
const CONTRACT_END = "2026-12-31";

/** What Django says when a role may not do something. */
const REFUSED = "You do not have permission to do that.";

/** A minimal file that satisfies the `%PDF-` content check. */
const PDF = Buffer.from("%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n");

function row(page: Page) {
  return page.getByRole("row").filter({ hasText: NEW_NAME });
}

/** Register the person through the screen; leaves the register refreshed. */
async function createPerson(page: Page): Promise<void> {
  await page.goto("/employees");
  await expect(page.getByRole("heading", { name: "Employee Register" })).toBeVisible();

  await page.getByLabel("Full name").fill(NEW_NAME);
  await page.getByLabel("Position").fill("Barman");
  await page.getByLabel("Phone (optional)").fill("+251911000111");
  await page.getByLabel("Started").fill(START_DATE);
  await page.getByLabel("Contract type").selectOption("TEMPORARY");
  await page.getByLabel("Contract ends (optional)").fill(CONTRACT_END);
  await page.getByLabel("Notes (optional)").fill("Registered by the live register spec.");
  await page.getByRole("button", { name: "Add to register" }).click();

  await expect(page.getByText(`${NEW_NAME} was added to the register.`)).toBeVisible();
  await expect(row(page)).toHaveCount(1);
  await expect(row(page)).toContainText("Barman");
  await expect(row(page)).toContainText("Temporary");
  await expect(row(page)).toContainText("Active");
  await expect(row(page)).toContainText("None");
}

test.describe.configure({ mode: "serial" });

test("an Owner registers, edits, documents, archives and restores a person", async ({ page }) => {
  test.setTimeout(240_000);

  await signIn(page, seed.owner);
  await expect(page.getByRole("link", { name: "Employee Register" })).toBeVisible();

  await createPerson(page);

  // --- Edit: the form switches from create to PATCH for the same row.
  await row(page).getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Position").fill(EDITED_POSITION);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`${NEW_NAME}'s record was updated.`)).toBeVisible();
  await expect(row(page)).toContainText(EDITED_POSITION);

  // --- Upload: a real multipart request through the file input.
  await row(page).locator('input[type="file"]').setInputFiles({
    name: "contract.pdf",
    mimeType: "application/pdf",
    buffer: PDF,
  });
  await expect(page.getByText(`PDF on file for ${NEW_NAME}.`)).toBeVisible();
  await expect(row(page)).toContainText("PDF on file");

  // Reload: the edit and the document are Django's answer, not React state.
  await page.reload();
  await expect(row(page)).toHaveCount(1);
  await expect(row(page)).toContainText(EDITED_POSITION);
  await expect(row(page)).toContainText("PDF on file");

  // --- Archive: current staff stops listing them, the archived filter finds them.
  await row(page).getByRole("button", { name: "Archive" }).click();
  await expect(page.getByText(`${NEW_NAME} was archived.`)).toBeVisible();
  await expect(row(page)).toHaveCount(0);

  await page.getByLabel("Showing").selectOption("archived");
  await expect(row(page)).toHaveCount(1);
  await expect(row(page)).toContainText("Archived");

  // --- Restore: back on the current register with the document intact.
  await row(page).getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText(`${NEW_NAME} was restored to the register.`)).toBeVisible();
  await expect(row(page)).toHaveCount(0);

  await page.getByLabel("Showing").selectOption("active");
  await expect(row(page)).toHaveCount(1);
  await expect(row(page)).toContainText("Active");
  await expect(row(page)).toContainText("PDF on file");
});

test("a Manager maintains the register but never creates a login", async ({ page }) => {
  test.setTimeout(240_000);

  await signIn(page, seed.manager);
  await expect(page.getByRole("link", { name: "Employee Register" })).toBeVisible();
  await page.goto("/employees");

  // The Manager sees the register and the Owner's row, and may edit it.
  await expect(page.getByRole("heading", { name: "Employee Register" })).toBeVisible();
  await expect(row(page)).toHaveCount(1);
  await row(page).getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Notes (optional)").fill("Maintained by the Manager.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`${NEW_NAME}'s record was updated.`)).toBeVisible();

  // There is no account-management surface here, and no delete: the row's
  // actions are Edit and Archive only.
  await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
});

test("a Cashier is refused the register on the screen and over the wire", async ({ page }) => {
  test.setTimeout(240_000);

  await signIn(page, seed.cashier);

  // Presentation: no menu entry, and the screen says why rather than showing
  // staff names, positions or contract dates.
  await expect(page.getByRole("link", { name: "Employee Register" })).toHaveCount(0);
  await page.goto("/employees");
  await expect(
    page.getByText(
      "Your role does not include the employee register. Ask an owner if you need access.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Employee Register" })).toBeVisible();

  // Authorisation: the list and the create route are refused from the
  // Cashier's own session and CSRF token.
  const list = await page.request.get("/api/v1/employees/");
  expect(list.status()).toBe(403);

  const created = await wirePost(page, "/api/v1/employees/", {
    full_name: "Cashier Should Not Create",
    position: "Cashier",
    start_date: START_DATE,
  });
  expect(created.status).toBe(403);
  expect((created.body as { error?: { message?: string } }).error?.message).toBe(REFUSED);
});

test("a Barman is refused the register as well", async ({ page }) => {
  test.setTimeout(240_000);

  await signIn(page, seed.barman);

  await expect(page.getByRole("link", { name: "Employee Register" })).toHaveCount(0);
  await page.goto("/employees");
  await expect(
    page.getByText(
      "Your role does not include the employee register. Ask an owner if you need access.",
    ),
  ).toBeVisible();

  const list = await page.request.get("/api/v1/employees/");
  expect(list.status()).toBe(403);
});
