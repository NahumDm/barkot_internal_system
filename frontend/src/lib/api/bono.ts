/**
 * Bono API client.
 *
 * Bono is a custody token, not a payment instrument. The types below mirror the
 * serializers exactly, including the fact that a Barman's report response has no
 * money fields: money is optional here because the server decides whether the
 * signed-in role may see it, not because the UI invites a missing value.
 */

import { apiFetch, type RequestOptions } from "./client";
import type { PaginatedResponse } from "./finance";

export type BonoIssueKind = "INITIAL" | "ADDITIONAL";
export type BonoIncidentKind = "LOST_BONO" | "BROKEN_BOTTLE";
export type BonoIncidentResolution = "PENDING" | "RESOLVED" | "DEDUCTED";
export type BonoReportStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED";
export type BonoDayStatus = "OPEN" | "SUBMITTED" | "APPROVED";
export type BonoReviewResolution = "RETAIN" | "REASSIGN" | "UNPAIR";

export interface BonoTypeNested {
  id: number;
  code: string;
  name: string;
  color: string;
  selling_price: string;
  currency: string;
  is_active: boolean;
}

export interface BonoPairing {
  id: number;
  bono_type: BonoTypeNested;
  product: number;
  product_name: string;
  product_sku: string;
  is_active: boolean;
  paired_at: string;
  unpaired_at: string | null;
  price_at_pairing: string;
  currency: string;
  current_price: string | null;
  review_required: boolean;
  review_reason: string;
  previous_price: string | null;
  new_price: string | null;
  price_effective_from: string | null;
  flagged_at: string | null;
  reviewed_at: string | null;
  reviewed_by_name: string;
}

export interface BonoType {
  id: number;
  code: string;
  name: string;
  color: string;
  selling_price: string;
  currency: string;
  is_active: boolean;
  notes: string;
  active_pairings: BonoPairing[];
  pending_review_count: number;
  created_at: string;
  updated_at: string;
}

export interface BonoConfigHistoryEntry {
  id: number;
  action: string;
  actor_name: string;
  summary: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  created_at: string;
}

export interface BonoIssue {
  id: number;
  operational_date: string;
  bono_type: number;
  bono_name_snapshot: string;
  bono_color_snapshot: string;
  bono_price_snapshot: string;
  currency: string;
  employee: number;
  employee_name: string;
  kind: BonoIssueKind;
  quantity: number;
  occurred_at: string;
  note: string;
  recorded_by_name: string;
  created_at: string;
}

export interface BonoTransfer {
  id: number;
  operational_date: string;
  bono_type: number;
  bono_name_snapshot: string;
  bono_color_snapshot: string;
  from_employee: number;
  from_employee_name: string;
  to_employee: number;
  to_employee_name: string;
  quantity: number;
  occurred_at: string;
  reason: string;
  note: string;
  recorded_by_name: string;
  created_at: string;
}

export interface BonoIncident {
  id: number;
  operational_date: string;
  kind: BonoIncidentKind;
  bono_type: number | null;
  bono_name_snapshot: string;
  bono_color_snapshot: string;
  bono_price_snapshot: string;
  currency: string;
  product: number | null;
  product_name: string | null;
  responsible_employee: number | null;
  responsible_employee_name: string | null;
  quantity: number;
  reason: string;
  notes: string;
  occurred_at: string;
  breakage_record: number | null;
  resolution_status: BonoIncidentResolution;
  resolution_notes: string;
  payroll_deduction: number | null;
  payroll_deduction_amount: string | null;
  recorded_by_name: string;
  created_at: string;
}

export interface BonoReportLine {
  id: number;
  bono_type: number;
  bono_code_snapshot: string;
  bono_name_snapshot: string;
  bono_color_snapshot: string;
  bono_price_snapshot: string;
  currency: string;
  initial_issued_quantity: number;
  additional_issued_quantity: number;
  total_issued_quantity: number;
  transfers_in_quantity: number;
  transfers_out_quantity: number;
  lost_quantity: number;
  used_quantity: number;
  returned_quantity: number;
  accounted_quantity: number;
  discrepancy_quantity: number;
  explanation: string;
}

export interface BonoReportProductLine {
  id: number;
  product: number;
  product_name_snapshot: string;
  product_sku_snapshot: string;
  bono_type: number | null;
  bono_name_snapshot: string;
  bono_color_snapshot: string;
  opening_quantity: string;
  received_quantity: string;
  other_addition_quantity: string;
  sold_quantity: string;
  breakage_quantity: string;
  other_loss_quantity: string;
  expected_closing_quantity: string;
  physical_closing_quantity: string | null;
  variance_quantity: string | null;
  explanation: string;
}

export interface BonoReport {
  id: number;
  operational_date: string;
  revision: number;
  corrects: number | null;
  correction_reason: string;
  status: BonoReportStatus;
  status_display: string;
  submitted_by_name: string;
  submitted_at: string | null;
  approved_by_name: string;
  approved_at: string | null;
  rejected_by_name: string;
  rejected_at: string | null;
  rejection_reason: string;
  notes: string;
  /**
   * Omitted for a role without financial visibility (a Barman). The type is
   * optional so the UI is forced to handle the server's decision honestly.
   */
  sales_total?: string;
  cash_paid_total?: string;
  mobile_paid_total?: string;
  payments_total?: string;
  currency?: string;
  activity_generated_at: string;
  created_at: string;
  updated_at: string;
}

export interface BonoReportDetail extends BonoReport {
  bono_lines: BonoReportLine[];
  product_lines: BonoReportProductLine[];
}

export interface BonoStaffBalance {
  employee_id: number;
  employee_name: string;
  employee_position: string;
  bono_type_id: number;
  bono_name: string;
  bono_color: string;
  issued: number;
  transfers_in: number;
  transfers_out: number;
  lost: number;
  balance: number;
}

export interface BonoTypeTotal {
  bono_type_id: number;
  bono_code: string;
  bono_name: string;
  bono_color: string;
  initial_issued: number;
  additional_issued: number;
  total_issued: number;
  transfers_in: number;
  transfers_out: number;
  lost: number;
}

export interface BonoLatestReport {
  id: number;
  revision: number;
  status: BonoReportStatus;
  submitted_at: string | null;
  approved_at: string | null;
}

export interface BonoDaySummary {
  operational_date: string;
  day_status: BonoDayStatus;
  operations_locked: boolean;
  bono_totals: BonoTypeTotal[];
  staff_balances: BonoStaffBalance[];
  latest_report: BonoLatestReport | null;
  in_progress_dates: string[];
}

export interface BonoTypeInput {
  name: string;
  color: string;
  selling_price: string;
  currency?: string;
  notes?: string;
}

export interface BonoTypeChanges {
  name?: string;
  color?: string;
  is_active?: boolean;
  notes?: string;
  confirm_in_progress?: boolean;
  change_reason?: string;
}

export interface BonoProgressConfirmation {
  confirm_in_progress?: boolean;
  change_reason?: string;
}

export interface BonoIssueInput {
  operational_date: string;
  bono_type: number;
  employee: number;
  kind: BonoIssueKind;
  quantity: number;
  note?: string;
}

export interface BonoTransferInput {
  operational_date: string;
  bono_type: number;
  from_employee: number;
  to_employee: number;
  quantity: number;
  reason: string;
  note?: string;
}

export interface BonoIncidentInput {
  operational_date: string;
  kind: BonoIncidentKind;
  bono_type?: number | null;
  product?: number | null;
  responsible_employee?: number | null;
  quantity: number;
  reason: string;
  notes?: string;
}

export interface BonoReportUpdateInput {
  notes?: string;
  bono_lines?: Array<{
    id: number;
    used_quantity?: number;
    returned_quantity?: number;
    explanation?: string;
  }>;
  product_lines?: Array<{
    id: number;
    physical_closing_quantity?: string | null;
    explanation?: string;
  }>;
}

export interface BonoReportFilters {
  date?: string;
  status?: BonoReportStatus;
  page?: number;
  page_size?: number;
}

export interface BonoMovementFilters {
  date?: string;
  bono_type?: number;
  kind?: BonoIncidentKind;
  page?: number;
  page_size?: number;
}

export interface BonoTypeFilters {
  page?: number;
  page_size?: number;
}

export function listBonoTypes(
  filters: BonoTypeFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoType>> {
  return apiFetch<PaginatedResponse<BonoType>>("/bono/types/", {
    ...options,
    query: { ...options.query, page_size: 200, ...filters },
  });
}

export function createBonoType(
  input: BonoTypeInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoType> {
  return apiFetch<BonoType>("/bono/types/", { ...options, method: "POST", body: input });
}

export function updateBonoType(
  id: number,
  changes: BonoTypeChanges,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoType> {
  return apiFetch<BonoType>(`/bono/types/${id}/`, { ...options, method: "PATCH", body: changes });
}

export function addBonoPairings(
  bonoTypeId: number,
  input: { products: number[] } & BonoProgressConfirmation,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoType> {
  return apiFetch<BonoType>(`/bono/types/${bonoTypeId}/products/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function listBonoConfigHistory(
  bonoTypeId: number,
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoConfigHistoryEntry>> {
  return apiFetch<PaginatedResponse<BonoConfigHistoryEntry>>(`/bono/types/${bonoTypeId}/history/`, {
    ...options,
    query: { page_size: 50, ...options.query },
  });
}

export function listBonoPairings(
  filters: { bono_type?: number; active?: boolean; page?: number; page_size?: number } = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoPairing>> {
  return apiFetch<PaginatedResponse<BonoPairing>>("/bono/pairings/", {
    ...options,
    query: { page_size: 200, ...filters, ...options.query },
  });
}

export function removeBonoPairing(
  pairingId: number,
  input: { reason: string } & BonoProgressConfirmation,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoPairing> {
  return apiFetch<BonoPairing>(`/bono/pairings/${pairingId}/remove/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function resolveBonoPairingReview(
  pairingId: number,
  input: {
    resolution: BonoReviewResolution;
    reason: string;
    target_bono_type?: number | null;
  } & BonoProgressConfirmation,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoType | BonoPairing> {
  return apiFetch<BonoType | BonoPairing>(`/bono/pairings/${pairingId}/review/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function listBonoIssues(
  filters: BonoMovementFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoIssue>> {
  return apiFetch<PaginatedResponse<BonoIssue>>("/bono/issues/", {
    ...options,
    query: { page_size: 100, ...filters, ...options.query },
  });
}

export function createBonoIssue(
  input: BonoIssueInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoIssue> {
  return apiFetch<BonoIssue>("/bono/issues/", { ...options, method: "POST", body: input });
}

export function listBonoTransfers(
  filters: BonoMovementFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoTransfer>> {
  return apiFetch<PaginatedResponse<BonoTransfer>>("/bono/transfers/", {
    ...options,
    query: { page_size: 100, ...filters, ...options.query },
  });
}

export function createBonoTransfer(
  input: BonoTransferInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoTransfer> {
  return apiFetch<BonoTransfer>("/bono/transfers/", { ...options, method: "POST", body: input });
}

export function listBonoIncidents(
  filters: BonoMovementFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoIncident>> {
  return apiFetch<PaginatedResponse<BonoIncident>>("/bono/incidents/", {
    ...options,
    query: { page_size: 100, ...filters, ...options.query },
  });
}

export function createBonoIncident(
  input: BonoIncidentInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoIncident> {
  return apiFetch<BonoIncident>("/bono/incidents/", { ...options, method: "POST", body: input });
}

export function resolveBonoIncident(
  id: number,
  input: {
    resolution_status: Exclude<BonoIncidentResolution, "PENDING">;
    resolution_notes?: string;
  },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoIncident> {
  return apiFetch<BonoIncident>(`/bono/incidents/${id}/resolve/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function deductBonoIncident(
  id: number,
  input: { payroll_item: number; amount: string; reason: string },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoIncident> {
  return apiFetch<BonoIncident>(`/bono/incidents/${id}/deduct/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function getBonoDaySummary(
  date?: string,
  options: RequestOptions = {},
): Promise<BonoDaySummary> {
  return apiFetch<BonoDaySummary>("/bono/summary/", {
    ...options,
    query: { date, ...options.query },
  });
}

export function listBonoReports(
  filters: BonoReportFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<BonoReport>> {
  return apiFetch<PaginatedResponse<BonoReport>>("/bono/reports/", {
    ...options,
    query: { page_size: 50, ...filters, ...options.query },
  });
}

export function getBonoReport(id: number, options: RequestOptions = {}): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/`, options);
}

export function createBonoReport(
  input: { operational_date: string; notes?: string },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>("/bono/reports/", { ...options, method: "POST", body: input });
}

export function updateBonoReport(
  id: number,
  input: BonoReportUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/`, {
    ...options,
    method: "PATCH",
    body: input,
  });
}

export function refreshBonoReport(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/refresh/`, {
    ...options,
    method: "POST",
  });
}

export function submitBonoReport(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/submit/`, {
    ...options,
    method: "POST",
  });
}

export function approveBonoReport(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/approve/`, {
    ...options,
    method: "POST",
  });
}

export function rejectBonoReport(
  id: number,
  input: { reason: string },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/reject/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function correctBonoReport(
  id: number,
  input: { reason: string },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BonoReportDetail> {
  return apiFetch<BonoReportDetail>(`/bono/reports/${id}/correct/`, {
    ...options,
    method: "POST",
    body: input,
  });
}
