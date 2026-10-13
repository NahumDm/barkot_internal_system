/**
 * Sales API client (roadmap B5).
 *
 * Thin wrapper around `apiFetch` that knows the sales endpoints and types.
 * All errors surface as `ApiError` with stable `code` for UI branching.
 */

import { apiFetch, type RequestOptions } from "./client";
import { type ApiError, type ErrorDetails } from "./errors";

export interface SaleItem {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  currency: string;
  price_source: number;
}

export interface Payment {
  id: number;
  method: "CASH" | "MOBILE_BANKING";
  method_display: string;
  amount: string;
  currency: string;
  status: string;
  status_display: string;
  received_at: string;
  reference: string;
  voided_at: string | null;
  void_reason: string | null;
}

export interface Sale {
  id: number;
  reference: string;
  status: "COMPLETED" | "VOIDED";
  status_display: string;
  sold_at: string;
  subtotal: string;
  total: string;
  amount_paid: string;
  currency: string;
  payment_status: string;
  payment_status_display: string;
  balance_due: string;
  note: string;
  items: SaleItem[];
  payments: Payment[];
  voided_at: string | null;
  void_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SaleListItem {
  id: number;
  reference: string;
  status: "COMPLETED" | "VOIDED";
  status_display: string;
  sold_at: string;
  total: string;
  currency: string;
  payment_status: string;
  payment_status_display: string;
  item_count: number;
  payments: Payment[];
  created_at: string;
}

export interface PaginatedResponse<T> {
  count: number;
  page_size: number;
  page: number;
  pages: number;
  results: T[];
}

export interface SaleLineInput {
  product: number;
  quantity: string;
  unit_price?: string;
}

export interface PaymentInput {
  method: "CASH" | "MOBILE_BANKING";
  amount: string;
}

export interface SaleCreateInput {
  lines: SaleLineInput[];
  payments: PaymentInput[];
  note?: string;
  sold_at?: string;
  idempotency_key?: string;
}

export interface VoidSaleInput {
  reason: string;
}

/** List sales with optional filters and pagination. */
export function listSales(
  options: RequestOptions & {
    query?: {
      status?: "COMPLETED" | "VOIDED";
      payment_status?: string;
      sold_after?: string;
      sold_before?: string;
      search?: string;
      page?: number;
      page_size?: number;
    };
  } = {},
): Promise<PaginatedResponse<SaleListItem>> {
  return apiFetch<PaginatedResponse<SaleListItem>>("/sales/", options);
}

/** Get a single sale by ID. */
export function getSale(id: number): Promise<Sale> {
  return apiFetch<Sale>(`/sales/${id}/`);
}

/** Create a new sale. */
export function createSale(
  input: SaleCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Sale> {
  return apiFetch<Sale>("/sales/", {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Get a single sale by ID (alias for getSale). */
export function getSaleDetail(id: number): Promise<Sale> {
  return apiFetch<Sale>(`/sales/${id}/`);
}

/** Void a sale. */
export function voidSale(
  id: number,
  input: VoidSaleInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<void> {
  return apiFetch<void>(`/sales/${id}/void/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Check if an error is a validation error (field-level). */
export function isValidationError(error: unknown): error is ApiError {
  return (
    error instanceof Error && "code" in error && (error as ApiError).code === "validation_error"
  );
}

/** Check if an error is a permission denied error. */
export function isPermissionDenied(error: unknown): error is ApiError {
  return (
    error instanceof Error && "code" in error && (error as ApiError).code === "permission_denied"
  );
}

/** Check if an error is a not found error. */
export function isNotFound(error: unknown): error is ApiError {
  return error instanceof Error && "code" in error && (error as ApiError).code === "not_found";
}

/** Check if an error is an inconsistent totals error. */
export function isInconsistentTotals(error: unknown): error is ApiError {
  return (
    error instanceof Error && "code" in error && (error as ApiError).code === "inconsistent_totals"
  );
}

/** Check if an error is an insufficient stock error. */
export function isInsufficientStock(error: unknown): error is ApiError {
  return (
    error instanceof Error && "code" in error && (error as ApiError).code === "insufficient_stock"
  );
}

/** Check if an error is an invalid state transition error. */
export function isInvalidStateTransition(error: unknown): error is ApiError {
  return (
    error instanceof Error &&
    "code" in error &&
    (error as ApiError).code === "invalid_state_transition"
  );
}
