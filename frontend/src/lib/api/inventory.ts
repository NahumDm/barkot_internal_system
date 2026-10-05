import { apiFetch, type RequestOptions } from "./client";
import type { PaginatedResponse, ProductListItem } from "./products";

export interface InventoryReceiptItem {
  id: number;
  product: number;
  product_name: string;
  quantity: string;
  unit_cost: string;
  currency: string;
  line_cost: string;
}

export interface StockReceipt {
  id: number;
  reference: string;
  supplier_name: string;
  status: "DRAFT" | "COMPLETED" | "APPROVED";
  received_at: string;
  completed_at: string | null;
  notes: string;
  items: InventoryReceiptItem[];
  created_at: string;
  updated_at: string;
}

export interface BreakageItem {
  id: number;
  product: number;
  product_name: string;
  quantity: string;
}

export interface BreakageRecord {
  id: number;
  reference: string;
  reason: string;
  occurred_at: string;
  notes: string;
  items: BreakageItem[];
  created_at: string;
  updated_at: string;
}

export interface StockCountItem {
  id: number;
  product: number;
  product_name: string;
  expected_quantity: string;
  counted_quantity: string;
  variance: string;
  note: string;
}

export interface StockCount {
  id: number;
  reference: string;
  status: "DRAFT" | "COMPLETED" | "APPROVED";
  counted_at: string;
  completed_at: string | null;
  approved_at: string | null;
  notes: string;
  items: StockCountItem[];
  created_at: string;
  updated_at: string;
}

export interface StockMovement {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  kind: string;
  direction: "IN" | "OUT";
  quantity: string;
  source: string;
  occurred_at: string;
  unit_cost: string | null;
  currency: string;
  reason: string;
  recorded_by: number | null;
}

export function listInventoryProducts(
  options: RequestOptions = {},
): Promise<PaginatedResponse<ProductListItem>> {
  return apiFetch<PaginatedResponse<ProductListItem>>("/products/", {
    ...options,
    query: { stock_tracked: true, active: true, page_size: 200, ...options.query },
  });
}

export function createStockReceipt(
  input: {
    supplier_name: string;
    reference?: string;
    received_at?: string;
    notes?: string;
    lines: Array<{
      product: number;
      quantity: string;
      unit_cost: string;
      currency: "ETB";
    }>;
  },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StockReceipt> {
  return apiFetch<StockReceipt>("/inventory/receipts/", {
    ...options,
    method: "POST",
    body: input,
  });
}

export function createBreakage(
  input: { reason: string; lines: Array<{ product: number; quantity: string }> },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<BreakageRecord> {
  return apiFetch<BreakageRecord>("/inventory/breakages/", {
    ...options,
    method: "POST",
    body: input,
  });
}

export function createStockCount(
  input: { products: number[] },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StockCount> {
  return apiFetch<StockCount>("/inventory/counts/", { ...options, method: "POST", body: input });
}

export function completeStockCount(
  id: number,
  input: { items: Array<{ item: number; counted_quantity: string }> },
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StockCount> {
  return apiFetch<StockCount>(`/inventory/counts/${id}/complete/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

export function approveStockCount(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StockCount> {
  return apiFetch<StockCount>(`/inventory/counts/${id}/approve/`, {
    ...options,
    method: "POST",
  });
}

export function listStockMovements(
  options: RequestOptions = {},
): Promise<PaginatedResponse<StockMovement>> {
  return apiFetch<PaginatedResponse<StockMovement>>("/inventory/movements/", options);
}
