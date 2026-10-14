/**
 * Product catalogue API client (roadmap B4).
 *
 * Thin wrapper around `apiFetch` that knows the product endpoints and types.
 * All errors surface as `ApiError` with stable `code` for UI branching.
 */

import { apiFetch, type RequestOptions } from "./client";
import { type ApiError } from "./errors";

export interface Category {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  display_order: number;
  product_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProductPrice {
  id: number;
  unit_price: string; // Decimal as string
  currency: string;
  effective_from: string;
  is_active: boolean;
  created_at: string;
}

/** Whether a product is counted in whole units (crates, bottles) or allows decimals (kg, litre). */
export type QuantityMode = "WHOLE" | "FRACTIONAL";

export interface Product {
  id: number;
  category: Category;
  name: string;
  sku: string;
  unit: string;
  quantity_mode: QuantityMode;
  is_stock_tracked: boolean;
  is_active: boolean;
  description: string;
  current_price: ProductPrice | null;
  current_stock: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProductListItem {
  id: number;
  category: number;
  category_name: string;
  name: string;
  sku: string;
  unit: string;
  quantity_mode: QuantityMode;
  is_stock_tracked: boolean;
  is_active: boolean;
  current_price: ProductPrice | null;
  current_stock: string | null;
}

export interface PaginatedResponse<T> {
  count: number;
  page_size: number;
  page: number;
  pages: number;
  results: T[];
}

export interface ProductCreateInput {
  category: number;
  name: string;
  sku: string;
  unit?: string;
  quantity_mode?: QuantityMode;
  is_stock_tracked?: boolean;
  description?: string;
}

export interface ProductUpdateInput {
  name?: string;
  unit?: string;
  quantity_mode?: QuantityMode;
  is_stock_tracked?: boolean;
  is_active?: boolean;
  description?: string;
}

export interface CategoryCreateInput {
  name: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface CategoryUpdateInput {
  name?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface PriceCreateInput {
  unit_price: string; // Decimal as string
  currency: string;
  effective_from?: string;
}

/** List products with optional filters and pagination. */
export function listProducts(
  options: RequestOptions & {
    query?: {
      category?: number;
      active?: boolean;
      stock_tracked?: boolean;
      search?: string;
      page?: number;
      page_size?: number;
    };
  } = {},
): Promise<PaginatedResponse<ProductListItem>> {
  return apiFetch<PaginatedResponse<ProductListItem>>("/products/", options);
}

/** Get a single product by ID. */
export function getProduct(id: number): Promise<Product> {
  return apiFetch<Product>(`/products/${id}/`);
}

/** Create a new product. */
export function createProduct(
  input: ProductCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Product> {
  return apiFetch<Product>("/products/", {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Partially update a product. */
export function updateProduct(
  id: number,
  input: ProductUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Product> {
  return apiFetch<Product>(`/products/${id}/`, {
    ...options,
    method: "PATCH",
    body: input,
  });
}

/** Retire (deactivate) a product. */
export function retireProduct(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<void> {
  return apiFetch<void>(`/products/${id}/`, {
    ...options,
    method: "DELETE",
  });
}

/** Add a new price for a product. */
export function setProductPrice(
  productId: number,
  input: PriceCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<{
  id: number;
  unit_price: string;
  currency: string;
  effective_from: string;
  is_active: boolean;
  created_at: string;
}> {
  return apiFetch(`/products/${productId}/prices/`, {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Get price history for a product. */
export function getPriceHistory(
  productId: number,
  options: RequestOptions = {},
): Promise<
  Array<{
    id: number;
    unit_price: string;
    currency: string;
    effective_from: string;
    is_active: boolean;
    created_at: string;
  }>
> {
  return apiFetch(`/products/${productId}/prices/history/`, options);
}

/** List categories. */
export function listCategories(options: RequestOptions = {}): Promise<PaginatedResponse<Category>> {
  return apiFetch<PaginatedResponse<Category>>("/products/categories/", options);
}

/** Get a single category. */
export function getCategory(id: number): Promise<Category> {
  return apiFetch<Category>(`/products/categories/${id}/`);
}

/** Create a new category. */
export function createCategory(
  input: CategoryCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Category> {
  return apiFetch<Category>("/products/categories/", {
    ...options,
    method: "POST",
    body: input,
  });
}

/** Partially update a category. */
export function updateCategory(
  id: number,
  input: CategoryUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Category> {
  return apiFetch<Category>(`/products/categories/${id}/`, {
    ...options,
    method: "PATCH",
    body: input,
  });
}

/** Delete a category (only if no products reference it). */
export function deleteCategory(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<void> {
  return apiFetch<void>(`/products/categories/${id}/`, {
    ...options,
    method: "DELETE",
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
