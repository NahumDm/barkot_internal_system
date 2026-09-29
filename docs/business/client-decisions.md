# Client Decisions — Business Scope Confirmations

- **Recorded:** 2026-09-29
- **Source:** Direct client clarification round, closing spec §30 open items 1, 2, 3 and 7
- **Status:** Accepted by the client. These are business decisions of record.
- **Architecture baseline:** BARKOT-SAS-001 v1.0.0 (unchanged on disk; revisions folded into v1.1.0
  by the author. See `docs/architecture/ADR/ADR-0003-phase-0b-scope-confirmations.md` for the
  deviations these decisions create.)

This file is the business-side record of *what the client decided*. Architectural consequences are
recorded in ADR-0003. Where this file and the v1.0.0 specification text disagree, **this file wins
as the business decision** and the discrepancy is logged rather than silently reinterpreted.

---

## CD-01 — Sales are recorded individually

**Decision.** Every customer transaction is recorded as its own individual sale. There is no table,
group, tab or open-round workflow.

**What this settles.** Spec §30 open item 1 ("Confirm the exact customer sales recording workflow and
whether all sales are entered individually") is closed as *yes, individually*.

**Consequences.**

- `Sale` is the unit of business. One sale = one payment obligation, one set of stock movements.
- No `Table`, `Tab`, `Guest` or `OpenRound` entity is introduced.
- A sale cannot be left "open"; the only lifecycle implemented in this phase is create-and-complete.
- Sales that turn out to be wrong are voided with a reason (audit trail), never deleted.

## CD-02 — Payment methods: Cash and Mobile Banking

**Decision.** Barkot accepts exactly two payment methods today: **Cash** and **Mobile Banking**.

**What this settles.** Spec §30 open item 2 ("Confirm all payment methods currently used at Barkot")
is closed.

**Consequences.**

- Payment method is an explicit, mandatory, first-class attribute of every payment. Reports must be
  able to split income by `CASH` vs `MOBILE_BANKING` without inspecting free text.
- **Mobile Banking is a business category, not a provider.** It means money received into the
  restaurant's bank account by whatever mobile-banking app the customer used. It is recorded by the
  cashier like any other tender.
- **No Chapa or other online payment gateway is implemented in this version.** Spec §16 lists Chapa
  under "Optional / requirement validation" and spec §28 places it in Phase 6; the client has not
  requested it, so it stays there. No webhook, no redirect, no gateway transaction status table.
- The `integrations/` application remains an empty boundary marker (spec P08 / ADR-0001) so a future
  provider can be added behind an adapter without redesigning the sales or payment domain.

## CD-03 — Inventory scope is products/beverages, not food ingredients

**Decision.** Inventory controls sellable products — primarily beverages such as beer, plus other
sellable stock defined by the approved requirements. **Food ingredients and raw materials are out of
scope for this version.**

**What this settles.** Spec §30 open item 3 ("Confirm whether food ingredients are included in
inventory MVP or beverages are the first controlled stock class") is closed as *beverages and other
sellable products first*.

**Consequences.**

- `Product` is a sellable item. Food items may exist as sellable products if the sales scope needs
  them; their *ingredients* are not modelled.
- **Not built, and not to be added without a new client decision:** ingredient/raw-material stock,
  recipes, bills of materials (BOM), kitchen production, ingredient depletion, or any recipe-driven
  stock-out.
- Stock leaves inventory only through the ledger movements that the approved inventory architecture
  already names: sale, breakage/waste, count variance and manual stock-out.

## CD-04 — No receipt or file upload in this version

**Decision.** Receipt photographs, receipt PDFs and any other business file attachment are not
required for the current version.

**What this settles.** Spec §30 open item 7 ("Confirm whether receipts/documents need file uploads in
MVP") is closed as *no*.

**Consequences.**

- No `FileField` anywhere, no upload endpoint, no attachment model, no object-storage adapter.
- Spec §16 lists "Object storage" as optional-until-receipts and §26.3 repeats it. Both stay
  unimplemented.
- Spec §20.2 lists "file upload limits and content-type validation" and §23 lists "file upload
  limits" under security tests. Those clauses are **not applicable** in this version and their tests
  are deliberately absent. Logged in ADR-0003.

## CD-05 — Operational responsibilities (confirms spec §2, no change)

These restate what the client has always said and what the specification already records in §2 and
§9.2. They are listed here so the role model has an explicit business source. **No new roles are
invented.**

| Responsibility | Who | Where it lands |
| --- | --- | --- |
| Receive stock | Barman | `inventory.receive_stock` — Barman role, plus Manager/Owner |
| Record breakage/waste | Barman | `inventory.record_breakage` — Barman role, plus Manager/Owner |
| Perform stock counts | Cashier, Owner or Manager (situation-dependent) | `inventory.complete_stock_count` — Cashier, Manager, Owner. **Not** Barman |
| Approve count variance adjustments | Manager, Owner | `inventory.approve_adjustment` |
| Record sales | Cashier, Manager, Owner | `sales.create_sale` |
| Record expenses | Manager, Owner | `finance.create_expense` |
| Generate/approve payroll | Manager reviews, Owner approves | `payroll.generate_run`, `payroll.approve_run` |
| Manage users, products, settings | Owner | `accounts.*`, `products.*` |

## CD-06 — Pay employees monthly

Employees are paid monthly. This confirms spec §14.1 (`Payroll period -> generate -> review ->
approve -> mark paid -> report`). Statutory tax/deduction rules remain unconfirmed (spec §30 items 5
and 6) and are therefore **not hard-coded** — see the open questions below.

---

## Still open (spec §30)

These client questions are **not** answered by the clarifications above and are therefore excluded
from the implementation. They are not to be guessed at.

| # | Spec §30 item | Status |
| --- | --- | --- |
| 4 | Physical stock count frequency, and whether a formal closing time exists | Open |
| 5 | Payroll addition / overtime / absence rules | Open |
| 6 | Payroll deduction approval policy and statutory calculations with the accountant | Open |
| 8 | Fiscal/e-invoicing technical requirements | Open — explicitly out of scope until validated |
| 9 | Live availability of the chosen domain | Open — commercial, not technical |
| 10 | Commercially permitted production VPS provider and ETB payment method | Open — commercial |
