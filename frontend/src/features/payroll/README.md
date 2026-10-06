# payroll

Three screens for roadmap C2: who is on the payroll, the month-by-month runs that
pay them, and the deductions taken off their payslips. Talk to
`/api/v1/payroll/{employees,profiles,runs,deductions}/`.

## Employees (`payroll/employees`)

A roster: Full Name, Position, Phone, Start Date, Monthly Wage, Status. The add
form offers the staff who are not on payroll yet (from `/payroll/profiles/`) and
takes the monthly wage; the profile's name, position, phone and start date are
read, never retyped.

## Payroll (`payroll/runs`)

Everything here is navigated by month. Prev/next pickers move between months and
the chips along the top are the months that have a run, so a month that was
never generated is not a blank space. Four KPI cards summarise the selected run,
and the payslip lines below carry the employee's Basic Wage, Deductions and Net
Pay.

**Paid and Pending are derived from the run's own status, not summed from the
lines**, and gross/deduction/net come from the API's computed `PayrollItem`
figures. Nothing is added up in the frontend, so there are not two
implementations of the same arithmetic to drift apart.

There is no "Additions" column. The backend has no such concept — gross is the
employee's monthly wage at generation time — and inventing one in the UI would
let a screen show money the API never signed.

**Approval is owned.** A manager may generate a run but only an owner approves or
marks it paid; the buttons appear by permission and state a signer is missing
otherwise. A run's lifecycle moves it between `GENERATED`, `APPROVED` and `PAID`,
and the screen re-reads the run after each write so a 409 — someone else changed
it first — fixes the view instead of leaving a stale button.

Lines are remembered per run (`itemsForRun`), never cleared in an effect; a row
from a month that is no longer selected simply is not shown.

## Deductions (`payroll/deductions`)

Recorded against a _line_ of a generated run (an approved one is fixed; the
correction belongs in the next run), with the employee pick filled from the
chosen run's lines. Reason is a first-class column, required in spirit and shown
back — a deduction with no explanation is exactly what an employee would query.
The API refuses an amount that is not positive or that would exceed the line's
gross, and the form says how much gross headroom remains.
