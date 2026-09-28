# payroll

Employees, payroll runs, deductions and payment status.

Owns: Employee, PayrollRun, PayrollItem, PayrollDeduction.
Depends on: `users`, `finance`, `audit`.
Monthly cycle: generate -> review -> approve -> mark paid -> report. Generated payroll is never auto-paid (spec §14.1).
