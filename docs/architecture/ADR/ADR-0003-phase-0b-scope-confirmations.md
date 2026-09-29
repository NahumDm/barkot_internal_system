# ADR-0003 — Phase 0B scope confirmations and v1.1.0 deviation log

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decision makers:** Client (business scope), user, implementation agent
- **Spec version referenced:** BARKOT-SAS-001 v1.0.0
- **Business source:** `docs/business/client-decisions.md` (CD-01 … CD-06)

## Context

BARKOT-SAS-001 v1.0.0 left four scope questions open (§30 items 1, 2, 3 and 7) and deferred payment,
fiscal and storage integrations to a later phase (§16, §28 Phase 6). The client has now answered
them. The answers narrow the MVP in ways that the v1.0.0 text does not yet reflect, and they settle
two questions that the spec text alone would have led us to over-build.

This ADR records the deviations so the author's v1.1.0 revision can pick them up. The v1.0.0 DOCX is
not modified.

## Decision

### 1. Payment methods are a closed business enum, not a provider integration

`Payment.method` is a mandatory explicit field with exactly two values, `CASH` and
`MOBILE_BANKING` (CD-02). Reports split income by it.

`MOBILE_BANKING` is a **business category**, not a payment gateway. No Chapa adapter, no webhook
verification table, no redirect-handling status column and no gateway SDK are implemented. Spec §16
already classified Chapa as "Optional / requirement validation" and §28 already places integrations
in Phase 6, so this is a *confirmation of the existing deferral*, not a reversal.

`apps/integrations/` stays an empty boundary marker per spec P08 and ADR-0001 item 5. The
`Sale -> Payment -> Integration interface -> Provider adapter` chain is preserved as a structure, but
because no external provider is in scope, no adapter interface code is written yet. Adding a provider
later means adding an adapter in `integrations/` and an optional `provider_reference` on `Payment` —
it does not require reshaping `sales` or `finance`.

### 2. Inventory is product/beverage only; no ingredient model exists

`Product` is a sellable item. There is no ingredient entity, no recipe, no BOM, no kitchen
production and no recipe-driven stock-out anywhere in the schema (CD-03). `StockMovement` supports
exactly the movement kinds the approved inventory architecture names in §11.2 and §12: receipt,
sale, breakage/waste, stock-in, count variance and manual stock-out.

### 3. No file uploads in this version

No `FileField`, no upload endpoint, no attachment model, no object-storage adapter (CD-04). Two
clauses in the v1.0.0 text consequently become not-applicable rather than unimplemented, and are
listed as deviations in the table below so they are not mistaken for gaps.

### 4. Sales are individual transactions

`Sale` is the unit of business; no `Table`, `Tab`, `Guest` or open-round entity exists (CD-01).

### 5. Employee record is split across two existing domain boundaries

Spec §6.2 assigns "user profile/business role data" to `users` and "employees, payroll runs,
deductions, payment status" to `payroll`, while §14.2 describes a single `Employee` object carrying
`name, position, start_date, monthly_wage, status`. Those two statements cannot both be satisfied by
one model without either duplicating the fields or moving `monthly_wage` out of the §14.2 contract.

**Decision:** `users.EmployeeProfile` holds the person (`full_name`, `position`, `phone_number`,
`start_date`); `payroll.Employee` holds the monthly-payroll subject and links one-to-one to the
profile (`monthly_wage`, `status`). No field is duplicated, both §6.2 boundaries are honoured, and
§14.2's field list is fully present across the pair. `Employee` is required to have an
`EmployeeProfile`; a staff member without a login cannot yet be a payroll subject. This is recorded as
a v1.1.0 clarification item because §14.2 arguably expects a standalone `Employee` table.

## Deviations to fold into BARKOT-SAS-001 v1.1.0

| # | Spec clause | Deviation | Reason |
| --- | --- | --- | --- |
| D1 | §16, §28 Phase 6, §1.2 | Chapa is out of scope for the current version; `Payment.method` is the closed enum `CASH` / `MOBILE_BANKING` | CD-02 |
| D2 | §1.2, §11.1, §12 | Inventory covers sellable products only; no ingredient, recipe, BOM or kitchen-production entities | CD-03 |
| D3 | §16, §26.3 | Object storage and receipt/file upload are out of scope; no `FileField` in the schema | CD-04 |
| D4 | §1.2, §13.1 | Sales are individual transactions only; no table/group-order model | CD-01 |
| D5 | §14.2 vs §6.2 | `Employee` is split into `users.EmployeeProfile` + `payroll.Employee` to honour both clauses without duplication | §6.2/§14.2 conflict |
| D6 | §20.2 "File upload limits and content-type validation"; §23 "Security tests: file upload limits" | Clauses are not applicable in this version; the corresponding security tests are deliberately absent | CD-04 |
| D7 | §30 items 1, 2, 3, 7 | Closed by CD-01, CD-02, CD-03, CD-04 | Client answers |
| D8 | §8.1 | `/api/v1/` gains a CSRF bootstrap endpoint (`/auth/csrf`) alongside the listed `/auth/login`, `/auth/logout`, `/auth/me` | Django session + CSRF web flow (spec §9.1) needs a token before the first `POST`; without it the browser client cannot log in at all |

## Consequences

- **Positive:** the MVP schema matches what the client actually sells and how it is actually paid
  for. Nothing unused is modelled. Reports can split cash against mobile banking from day one.
- **Negative:** four spec clauses need editing in v1.1.0 (§16, §20.2, §23, §30). The author owns that
  edit; this ADR is the authoritative record until then.
- Reversal cost is low. A payment provider is additive (adapter plus a nullable reference column); an
  ingredient model is additive and would not disturb the movement ledger; a group-order model would
  require restructuring `Sale`, which is why CD-01 is recorded explicitly.
