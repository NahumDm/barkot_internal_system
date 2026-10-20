/**
 * The reports API client (spec §15).
 *
 * Reports are read-only projections of other domains' authoritative data, and
 * these functions are deliberately thin: a typed GET per screen, nothing
 * else. The financial report reuses the same wire shape as the balance screen
 * (`/finance/balance/` returns it too), so both views render the identical
 * object rather than two objects that happen to agree today.
 *
 * Exports are plain anchors to `?export=pdf` — the browser downloads the PDF
 * because the response carries `Content-Disposition: attachment`.
 */

import { API_BASE_URL, get, type QueryValue } from "./client";
import type { FinanceBalance } from "./finance";

/** One product on the stock balance report. */
export interface StockBalanceRow {
  product_id: number;
  sku: string;
  name: string;
  ledger_balance: string;
  last_counted: string | null;
  last_counted_on: string | null;
  delta: string | null;
}

export interface StockBalanceReport {
  as_of: string;
  in_stock_total: string;
  products: number;
  rows: StockBalanceRow[];
}

/** One approved count line whose counted quantity differed from expected. */
export interface StockVarianceRow {
  stock_count_id: number;
  reference: string;
  status: string;
  product_id: number;
  sku: string;
  name: string;
  counted_on: string;
  expected_quantity: string;
  counted_quantity: string;
  variance: string;
  note: string;
}

export interface StockVarianceReport {
  start: string;
  end: string;
  lines: number;
  expected_total: string;
  counted_total: string;
  variance_total: string;
  rows: StockVarianceRow[];
}

export interface PayrollRunRow {
  run_id: number;
  period_month: string;
  status: string;
  status_display: string;
  currency: string;
  employees: number;
  gross_total: string;
  deduction_total: string;
  net_total: string;
}

export interface PayrollStatusBucket {
  status: string;
  status_display: string;
  runs: number;
  gross_total: string;
  deduction_total: string;
  net_total: string;
}

export interface PayrollReport {
  start: string;
  end: string;
  currency: string;
  rows: PayrollRunRow[];
  summary: {
    runs: number;
    gross_total: string;
    deduction_total: string;
    net_total: string;
    by_status: PayrollStatusBucket[];
  };
  deductions: Record<string, string>;
}

/** `{...period, export: "pdf"}` for a same-origin download anchor. */
function pdfUrl(path: string, query: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  params.set("export", "pdf");
  return `${API_BASE_URL}${path}?${params.toString()}`;
}

/** Backward-compatible alias. */
function csvUrl(path: string, query: Record<string, QueryValue>): string {
  return pdfUrl(path, query);
}

export function getFinancialReport(start: string, end: string): Promise<FinanceBalance> {
  return get<FinanceBalance>("/reports/financial/", { query: { start, end } });
}

/** The PDF download URL for the financial report for a period. */
export function financialPdfUrl(start: string, end: string): string {
  return pdfUrl("/reports/financial/", { start, end });
}

export const financialCsvUrl = financialPdfUrl;

export function getStockBalance(date: string): Promise<StockBalanceReport> {
  return get<StockBalanceReport>("/reports/inventory/stock-balance/", { query: { date } });
}

/** The PDF download URL for the stock balance as of a business date. */
export function stockBalancePdfUrl(date: string): string {
  return pdfUrl("/reports/inventory/stock-balance/", { date });
}

export const stockBalanceCsvUrl = stockBalancePdfUrl;

export function getStockVariance(start: string, end: string): Promise<StockVarianceReport> {
  return get<StockVarianceReport>("/reports/inventory/variance/", { query: { start, end } });
}

/** The PDF download URL for the variance report for a period. */
export function stockVariancePdfUrl(start: string, end: string): string {
  return pdfUrl("/reports/inventory/variance/", { start, end });
}

export const stockVarianceCsvUrl = stockVariancePdfUrl;

export function getPayrollReport(start: string, end: string): Promise<PayrollReport> {
  return get<PayrollReport>("/reports/payroll/", { query: { start, end } });
}

/** The PDF download URL for the payroll report for a period. */
export function payrollPdfUrl(start: string, end: string): string {
  return pdfUrl("/reports/payroll/", { start, end });
}

export const payrollCsvUrl = payrollPdfUrl;
