/**
 * The dashboard API client (roadmap C6).
 *
 * The dashboard is a single read-only aggregate over the domains it shows, so
 * this module is intentionally thin: every figure comes from the endpoint the
 * server built from the same services the balance, stock-balance and payroll
 * screens use, and the sections that a role cannot see arrive as `null` rather
 * than being omitted, so a screen can tell "no permission" from "no data".
 */

import { get } from "./client";
import type { FinanceBalance } from "./finance";
import type { PayrollRunStatus } from "./payroll";

export interface DashboardPeriod {
  start: string;
  end: string;
  currency: string;
}

export interface DashboardSaleRow {
  id: number;
  reference: string;
  status: string;
  status_display: string;
  sold_at: string;
  total: string;
  currency: string;
  payment_status: string;
  payment_status_display: string;
  item_count: number;
  created_at: string;
}

export interface DashboardSales {
  total: string;
  cash: string;
  mobile_banking: string;
  transactions: number;
  recent: DashboardSaleRow[];
}

export interface DashboardInventory {
  as_of: string;
  in_stock_total: string;
  products: number;
}

export interface DashboardPayroll {
  id: number;
  period_month: string;
  status: PayrollRunStatus;
  status_display: string;
  gross_total: string;
  deduction_total: string;
  net_total: string;
  generated_at: string;
  approved_at: string | null;
  approved_by_username: string | null;
}

export interface DashboardResponse {
  period: DashboardPeriod;
  sales: DashboardSales | null;
  inventory: DashboardInventory | null;
  finance: FinanceBalance | null;
  payroll: DashboardPayroll | null;
}

/**
 * Fetch the dashboard over a period.
 *
 * Both dates are optional on the wire; the server defaults to the current
 * business month-to-date when either is absent. The screen always sends the
 * full month it is showing, so the printed period always matches the filters.
 */
export function getDashboard(start?: string, end?: string): Promise<DashboardResponse> {
  return get<DashboardResponse>("/dashboard/", { query: { start, end } });
}
