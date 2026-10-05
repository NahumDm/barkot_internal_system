import { apiFetch, type RequestOptions } from "./client";

export interface FinanceBalance {
  period_start: string;
  period_end: string;
  currency: string;
  income: {
    cash: string;
    mobile_banking: string;
    total: string;
  };
  expenses_total: string;
  expense_breakdown: Record<string, string>;
  payroll_total: string;
  net: string;
}

export interface ExpenseCategory {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Expense {
  id: number;
  category: number;
  category_name: string;
  description: string;
  amount: string;
  currency: string;
  incurred_on: string;
  status: "RECORDED" | "APPROVED" | "VOIDED";
  status_display: string;
  approved_at: string | null;
  recorded_at: string;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  count: number;
  page_size: number;
  page: number;
  pages: number;
  results: T[];
}

export interface ExpenseCreateInput {
  category: number;
  description: string;
  amount: string;
  currency: "ETB";
  incurred_on: string;
}

export function getFinanceBalance(start: string, end: string): Promise<FinanceBalance> {
  return apiFetch<FinanceBalance>("/finance/balance/", { query: { start, end } });
}

export function listExpenseCategories(
  options: RequestOptions = {},
): Promise<PaginatedResponse<ExpenseCategory>> {
  return apiFetch<PaginatedResponse<ExpenseCategory>>("/finance/categories/", options);
}

export function createExpenseCategory(
  input: { name: string; description?: string },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<ExpenseCategory> {
  return apiFetch<ExpenseCategory>("/finance/categories/", {
    ...options,
    method: "POST",
    body: input,
  });
}

export function listExpenses(options: RequestOptions = {}): Promise<PaginatedResponse<Expense>> {
  return apiFetch<PaginatedResponse<Expense>>("/finance/expenses/", options);
}

export function createExpense(
  input: ExpenseCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Expense> {
  return apiFetch<Expense>("/finance/expenses/", {
    ...options,
    method: "POST",
    body: input,
  });
}

export function approveExpense(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Expense> {
  return apiFetch<Expense>(`/finance/expenses/${id}/approve/`, {
    ...options,
    method: "POST",
  });
}
