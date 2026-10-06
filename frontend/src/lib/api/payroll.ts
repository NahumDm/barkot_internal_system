/**
 * Payroll API client (roadmap C2).
 *
 * Thin wrappers over `apiFetch` that know the four payroll resources. Two
 * decisions are worth reading before the types.
 *
 * **Money is a string on the wire and stays a string here.** Every figure is a
 * `DecimalField(max_digits=14, decimal_places=2)` serialised by DRF, so
 * `"18000.00"` is exact and `18000` is a different claim. Arithmetic happens on
 * the server (`PayrollItem.save` and `PayrollRun` decide net pay); this module
 * reports what they decided. Formatting to a currency is a view concern and
 * lives in `features/payroll`.
 *
 * **There is no "additions" field.** The feature brief asks for a Basic Wage /
 * Additions / Deductions / Net Pay table, but a run's gross pay is read from
 * each employee's `monthly_wage` at generation time and nothing else can enter
 * a line. Showing an Additions column would be a column of zeros that looks
 * like data. It appears when the backend has a second input for it.
 */

import { apiFetch, type RequestOptions } from "./client";
import { type PaginatedResponse } from "./finance";

/** When a run exists for the month (first of the month) it was generated for. */
export type PayrollRunStatus = "GENERATED" | "APPROVED" | "PAID" | "CANCELLED";

/** Per-employee outcome, advanced by the run's own transition. */
export type PayrollItemStatus = "PENDING" | "APPROVED" | "PAID";

export type EmployeeStatus = "ACTIVE" | "INACTIVE" | "TERMINATED";

/**
 * Deduction kinds the client has actually asked for. Statutory categories are
 * deliberately absent until the accountant confirms them (spec §30 items 5-6),
 * so adding one here would be guessing at Ethiopian payroll tax.
 */
export type PayrollDeductionType = "ADVANCE" | "ABSENCE" | "LATE" | "OTHER";

/** An active staff profile that can still be put on payroll. */
export interface PayrollProfile {
  id: number;
  full_name: string;
  position: string;
  phone_number: string;
  start_date: string;
}

/** Someone on monthly payroll. Person details are read from their profile. */
export interface PayrollEmployee {
  id: number;
  profile: number;
  full_name: string;
  position: string;
  phone_number: string;
  start_date: string;
  monthly_wage: string;
  currency: string;
  status: EmployeeStatus;
  status_display: string;
  terminated_on: string | null;
  created_at: string;
  updated_at: string;
}

/** One month of payroll and where it sits in its lifecycle. */
export interface PayrollRun {
  id: number;
  /** First day of the month being paid, e.g. `"2026-10-01"`. */
  period_month: string;
  status: PayrollRunStatus;
  status_display: string;
  currency: string;
  gross_total: string;
  deduction_total: string;
  net_total: string;
  generated_at: string;
  approved_at: string | null;
  approved_by: number | null;
  approved_by_username: string | null;
  paid_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

/** One employee's line inside a run. Totals are computed, never typed in. */
export interface PayrollItem {
  id: number;
  run: number;
  employee: number;
  full_name: string;
  position: string;
  gross_amount: string;
  total_deductions: string;
  net_amount: string;
  currency: string;
  status: PayrollItemStatus;
  status_display: string;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
}

/** A deduction against one line, kept with the reason it was taken. */
export interface PayrollDeduction {
  id: number;
  payroll_item: number;
  run: number;
  employee_name: string;
  deduction_type: PayrollDeductionType;
  deduction_type_display: string;
  amount: string;
  currency: string;
  reason: string;
  occurred_on: string;
  created_at: string;
}

export interface PayrollEmployeeCreateInput {
  /** A `PayrollProfile.id` from `listPayrollProfiles`. */
  profile: number;
  monthly_wage: string;
  currency?: "ETB";
}

export interface PayrollRunGenerateInput {
  /** Any date in the month being paid; the server normalises to the 1st. */
  period: string;
  /** Omit to include every currently employable employee. */
  employee_ids?: number[];
  notes?: string;
}

export interface PayrollDeductionCreateInput {
  payroll_item: number;
  deduction_type: PayrollDeductionType;
  amount: string;
  reason?: string;
  /** Business-local date; defaults to the run's period. */
  occurred_on?: string;
}

export interface PayrollRunFilters {
  status?: PayrollRunStatus;
  page?: number;
  /** The server pages at 20 by default (`BarkotPagination`); payroll screens
   * ask for the whole history so the month picker can offer it. */
  page_size?: number;
}

export interface PayrollDeductionFilters {
  run?: number;
  payroll_item?: number;
  page?: number;
  page_size?: number;
}

/** Staff profiles that are not on payroll yet — the options for the create form. */
export function listPayrollProfiles(
  options: RequestOptions = {},
): Promise<PaginatedResponse<PayrollProfile>> {
  return apiFetch<PaginatedResponse<PayrollProfile>>("/payroll/profiles/", options);
}

export function listPayrollEmployees(
  options: RequestOptions = {},
): Promise<PaginatedResponse<PayrollEmployee>> {
  return apiFetch<PaginatedResponse<PayrollEmployee>>("/payroll/employees/", options);
}

/** Put an existing staff profile onto payroll. */
export function createPayrollEmployee(
  input: PayrollEmployeeCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<PayrollEmployee> {
  return apiFetch<PayrollEmployee>("/payroll/employees/", {
    ...options,
    method: "POST",
    body: input,
  });
}

export function listPayrollRuns(
  filters: PayrollRunFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<PayrollRun>> {
  return apiFetch<PaginatedResponse<PayrollRun>>("/payroll/runs/", {
    ...options,
    query: { ...options.query, ...filters },
  });
}

export function getPayrollRun(id: number, options: RequestOptions = {}): Promise<PayrollRun> {
  return apiFetch<PayrollRun>(`/payroll/runs/${id}/`, options);
}

/**
 * Create a month's run from current wages.
 *
 * Rejects with `invalid_state_transition` (409) when a run already exists for
 * the month or no employee is eligible — a duplicate month is the mistake this
 * endpoint is most likely to be asked for twice by accident.
 */
export function generatePayrollRun(
  input: PayrollRunGenerateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<PayrollRun> {
  return apiFetch<PayrollRun>("/payroll/runs/", {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Owner-only. Refuses with 409 unless the run is still `GENERATED`. */
export function approvePayrollRun(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<PayrollRun> {
  return apiFetch<PayrollRun>(`/payroll/runs/${id}/approve/`, {
    ...options,
    method: "POST",
  });
}

/** Owner-only. Refuses with 409 unless the run is `APPROVED`. */
export function markPayrollRunPaid(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<PayrollRun> {
  return apiFetch<PayrollRun>(`/payroll/runs/${id}/mark-paid/`, {
    ...options,
    method: "POST",
  });
}

/** One page of a run's payslip lines. Separate from the run on purpose. */
export function listPayrollItems(
  runId: number,
  options: RequestOptions = {},
): Promise<PaginatedResponse<PayrollItem>> {
  return apiFetch<PaginatedResponse<PayrollItem>>(`/payroll/runs/${runId}/items/`, options);
}

export function listPayrollDeductions(
  filters: PayrollDeductionFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<PayrollDeduction>> {
  return apiFetch<PaginatedResponse<PayrollDeduction>>("/payroll/deductions/", {
    ...options,
    query: { ...options.query, ...filters },
  });
}

/**
 * Record a deduction against one line.
 *
 * Refuses with `invalid_state_transition` once the run is approved (a signed
 * payslip is not edited), `invalid_deduction_amount` for zero or less, and
 * `excessive_deduction` when the total would pass gross pay.
 */
export function createPayrollDeduction(
  input: PayrollDeductionCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<PayrollDeduction> {
  return apiFetch<PayrollDeduction>("/payroll/deductions/", {
    ...options,
    method: "POST",
    body: input,
  });
}
