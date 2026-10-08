/**
 * §23.1 scenario 5, in a browser against the real backend: a Cashier cannot
 * approve payroll or move a product price, unless explicitly permitted — and
 * Owner, who is, can.
 *
 * Two of the three acts have no screen. A Cashier visiting payroll sees the
 * permissions note instead of a form, but there is no "approve payroll" button
 * to click and no price screen anywhere in the app; shipment of those stubs
 * waits for the change_prices and approve-run surfaces to exist. So the refusals
 * are asked over the wire, from inside the browser so the CSRF token and the
 * session cookie are the role's own — which is what makes a 403 the backend's
 * permission answer rather than a defence the test forgot.
 *
 * What is asserted, and why that is the honest version of the story:
 *
 * 1. The Cashier's own UI renders the no-access note on the payroll screen —
 *    the user-facing refusal of the month's pay list.
 * 2. Approving the run `payroll.spec.ts` left standing (this file runs after it,
 *    alphabetically, in the same serial project) returns a real permission 403.
 *    Authorisation answers before the object is consulted, so the refusal is
 *    independent of whether the run id is plausible.
 * 3. Setting a price on the seeded product returns the same 403 — the one grant
 *    the matrix withholds from every role but the Owner.
 * 4. The Owner, whose `products.change_prices` is explicit, writes the same
 *    price through the same route and it succeeds; the history read-back shows
 *    the new row. That is the "unless explicitly permitted" half of the story,
 *    load-bearing rather than decorative, because this permission is otherwise
 *    covered nowhere.
 *
 * Two sign-ins — the Cashier and the Owner — each of which may have to sit out
 * the tail of the A5 login window, hence the per-test timeouts.
 */

import { expect, test } from "@playwright/test";

import { readSeedSummary } from "./environment";
import { signIn } from "./signin";
import { wirePost } from "./wire";

const seed = readSeedSummary();

/** What Django says when a role may not do something. */
const REFUSED = "You do not have permission to do that.";

/** The first run in a freshly flushed database — the one `payroll.spec.ts` paid. */
const PAID_RUN_ID = 1;

/** The price the Owner is permitted to set — deliberately not the seeded one. */
const NEW_PRICE = "30.00";

test.describe.configure({ mode: "serial" });

test("a Cashier is refused payroll approval and price changes, on and off the wire", async ({
  page,
}) => {
  test.setTimeout(240_000);

  await signIn(page, seed.cashier);

  // The UI refusal: the payroll screen renders a note rather than a form, and
  // never offers generation or approval affordances to this role.
  await page.goto("/payroll/runs");
  await expect(
    page.getByText("Your role does not include payroll. Ask an owner if you need access."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate run" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve run" })).toHaveCount(0);

  // The wire refusal for the run the earlier story paid. A permitted Owner on
  // this route would move the status on; the Cashier is stopped before the
  // object is even looked up, so this is the permission boundary, not a 404.
  const approveRefusal = await wirePost(page, `/api/v1/payroll/runs/${PAID_RUN_ID}/approve/`);
  expect(approveRefusal.status).toBe(403);
  expect((approveRefusal.body as { error?: { message?: string } }).error?.message).toBe(REFUSED);

  // The price refusal, on the real seeded product.
  const priceRefusal = await wirePost(page, `/api/v1/products/${seed.product.id}/prices/`, {
    unit_price: NEW_PRICE,
    currency: "ETB",
  });
  expect(priceRefusal.status).toBe(403);
  expect((priceRefusal.body as { error?: { message?: string } }).error?.message).toBe(REFUSED);
});

test("the Owner is explicitly permitted the same price write", async ({ page }) => {
  test.setTimeout(240_000);

  await signIn(page, seed.owner);

  const permitted = await wirePost(page, `/api/v1/products/${seed.product.id}/prices/`, {
    unit_price: NEW_PRICE,
    currency: "ETB",
  });
  expect(permitted.status).toBe(201);

  // The new price is the current one: the history lists it newest-first.
  const historyResponse = await page.request.get(
    `/api/v1/products/${seed.product.id}/prices/history/`,
  );
  expect(historyResponse.status()).toBe(200);
  const history = (await historyResponse.json()) as { unit_price: string }[];
  expect(history[0].unit_price).toBe(NEW_PRICE);
});
