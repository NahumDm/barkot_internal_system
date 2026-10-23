"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { useRouter } from "next/navigation";

import {
  getProduct,
  listProducts,
  listCategories,
  setProductPrice,
  updateProduct,
  type ProductListItem,
  type QuantityMode,
} from "@/lib/api/products";
import { type ApiError, ApiError as ApiErrorClass, isValidationError } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { Field, FormError } from "@/features/auth/form-parts";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

function formatPrice(price: { unit_price: string; currency: string } | null): string {
  if (!price) return "Not set";
  return `${Number(price.unit_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${price.currency}`;
}

function ProductRow({
  product,
  canManage,
  onEdit,
}: {
  product: ProductListItem;
  canManage: boolean;
  onEdit: (id: number) => void;
}) {
  return (
    <tr className="border-b border-border hover:bg-surface/50">
      <td className="px-3 py-2 text-sm text-ink">{product.sku}</td>
      <td className="px-3 py-2 text-sm text-ink">{product.name}</td>
      <td className="px-3 py-2 text-sm text-ink">{product.category_name}</td>
      <td className="px-3 py-2 text-sm text-ink">{product.unit}</td>
      <td className="px-3 py-2 text-sm text-ink">{formatPrice(product.current_price)}</td>
      <td className="px-3 py-2 text-sm">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
            product.is_active ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-800"
          }`}
        >
          {product.is_active ? "Active" : "Retired"}
        </span>
      </td>
      <td className="px-3 py-2 text-sm">
        {canManage && (
          <button
            type="button"
            onClick={() => onEdit(product.id)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs font-medium text-ink hover:bg-surface/50"
          >
            Edit
          </button>
        )}
      </td>
    </tr>
  );
}

function ProductsTable({
  products,
  canManage,
  onEdit,
  emptyMessage = "No products found.",
}: {
  products: ProductListItem[];
  canManage: boolean;
  onEdit: (id: number) => void;
  emptyMessage?: string;
}) {
  if (products.length === 0) {
    return <div className="text-center py-8 text-ink-secondary">{emptyMessage}</div>;
  }

  return (
    <div className="overflow-x-auto rounded border border-border bg-surface">
      <table className="w-full text-left">
        <thead className="bg-surface border-b border-border">
          <tr>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              SKU
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Name
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Category
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Unit
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Price
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Status
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <ProductRow key={product.id} product={product} canManage={canManage} onEdit={onEdit} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PaginationControls({
  page,
  pages,
  pageSize,
  count,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pages: number;
  pageSize: number;
  count: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const start = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, count);

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-3 py-3 text-sm text-ink-secondary">
      <div className="flex items-center gap-2">
        <span>
          Showing {start}–{end} of {count}
        </span>
        <select
          value={pageSize}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => onPageSizeChange(Number(e.target.value))}
          className="rounded border border-border bg-surface px-2 py-1 text-sm text-ink"
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size} per page
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(1)}
          disabled={page === 1}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          « First
        </button>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          ‹ Prev
        </button>
        <span className="px-2 py-1 text-sm text-ink">
          Page {page} of {pages}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page === pages}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          Next ›
        </button>
        <button
          onClick={() => onPageChange(pages)}
          disabled={page === pages}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          Last »
        </button>
      </div>
    </div>
  );
}

function ProductFilters({
  search,
  onSearchChange,
  activeFilter,
  onActiveFilterChange,
  stockTrackedFilter,
  onStockTrackedFilterChange,
  categoryFilter,
  onCategoryFilterChange,
  categories,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  activeFilter: "all" | "true" | "false";
  onActiveFilterChange: (value: "all" | "true" | "false") => void;
  stockTrackedFilter: "all" | "true" | "false";
  onStockTrackedFilterChange: (value: "all" | "true" | "false") => void;
  categoryFilter: number | "all";
  onCategoryFilterChange: (value: number | "all") => void;
  categories: Array<{ id: number; name: string }>;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <Field
          label="Search"
          type="search"
          value={search}
          onChange={onSearchChange}
          errors={[]}
          autoComplete="off"
          hint="Search by name, SKU, or description"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <select
          value={activeFilter}
          onChange={(e) => onActiveFilterChange(e.target.value as "all" | "true" | "false")}
          className="control control--inline"
        >
          <option value="all">All statuses</option>
          <option value="true">Active only</option>
          <option value="false">Retired only</option>
        </select>
        <select
          value={stockTrackedFilter}
          onChange={(e) => onStockTrackedFilterChange(e.target.value as "all" | "true" | "false")}
          className="control control--inline"
        >
          <option value="all">All stock tracking</option>
          <option value="true">Tracked only</option>
          <option value="false">Untracked only</option>
        </select>
        <select
          value={categoryFilter}
          onChange={(e) =>
            onCategoryFilterChange(e.target.value === "all" ? "all" : Number(e.target.value))
          }
          className="control control--inline"
        >
          <option value="all">All categories</option>
          {categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

interface EditProductForm {
  name: string;
  unit: string;
  quantity_mode: QuantityMode;
  bottles_per_crate: string;
  is_stock_tracked: boolean;
  is_active: boolean;
  description: string;
  price: string;
  currency: string;
}

/**
 * Edit one catalogue product.
 *
 * The fields are exactly the ones `ProductUpdateSerializer` accepts. The price
 * is separate on purpose: prices are versioned rows, not a column, so a change
 * is written through `/products/{id}/prices/` and only when it differs from the
 * current one - editing a name must not mint a redundant price row. SKU and
 * category are shown nowhere because the API treats both as immutable.
 */
function EditProductDialog({
  productId,
  canChangePrices,
  onClose,
  onSaved,
}: {
  productId: number;
  canChangePrices: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<EditProductForm | null>(null);
  const [originalPrice, setOriginalPrice] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    getProduct(productId)
      .then((product) => {
        if (!mounted) return;
        setForm({
          name: product.name,
          unit: product.unit,
          quantity_mode: product.quantity_mode,
          bottles_per_crate: product.bottles_per_crate?.toString() ?? "",
          is_stock_tracked: product.is_stock_tracked,
          is_active: product.is_active,
          description: product.description,
          price: product.current_price?.unit_price ?? "",
          currency: product.current_price?.currency ?? "ETB",
        });
        setOriginalPrice(product.current_price?.unit_price ?? "");
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!mounted) return;
        setFormError((caught as ApiError).message);
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [productId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const update = (patch: Partial<EditProductForm>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || !form) return;

    setFormError(null);
    setFieldErrors({});

    const price = form.price.trim();
    if (canChangePrices && price !== "" && !/^\d+(\.\d{1,2})?$/.test(price)) {
      setFieldErrors({ price: ["Enter a price like 120.00."] });
      return;
    }

    const crateSize = form.bottles_per_crate.trim();
    if (crateSize !== "" && (!/^\d+$/.test(crateSize) || Number(crateSize) < 2)) {
      setFieldErrors({
        bottles_per_crate: ["Enter a whole number of bottles, like 24, or leave it blank."],
      });
      return;
    }

    setSaving(true);
    try {
      await updateProduct(productId, {
        name: form.name.trim(),
        unit: form.unit.trim(),
        quantity_mode: form.quantity_mode,
        bottles_per_crate: crateSize === "" ? null : Number(crateSize),
        is_stock_tracked: form.is_stock_tracked,
        is_active: form.is_active,
        description: form.description,
      });
      if (canChangePrices && price !== "" && price !== originalPrice) {
        await setProductPrice(productId, { unit_price: price, currency: form.currency || "ETB" });
      }
      onSaved();
    } catch (caught) {
      const error = caught as ApiError;
      if (isValidationError(error) && error.details) {
        setFieldErrors(error.details);
      } else {
        setFormError(error.message);
      }
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Edit product"
        className="mt-12 w-full max-w-lg rounded border border-border bg-surface p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-ink">Edit product</h2>

        {loading ? (
          <p className="py-6 text-sm text-ink-secondary">Loading…</p>
        ) : !form ? (
          <div className="mt-4 flex flex-col gap-4">
            {formError && (
              <FormError
                error={
                  new ApiErrorClass(0, {
                    code: "form_error",
                    message: formError,
                    details: null,
                  })
                }
              />
            )}
            <div className="form-actions">
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4" noValidate>
            {formError && (
              <FormError
                error={
                  new ApiErrorClass(0, {
                    code: "form_error",
                    message: formError,
                    details: null,
                  })
                }
              />
            )}

            <Field
              label="Name"
              type="text"
              value={form.name}
              onChange={(value) => update({ name: value })}
              errors={fieldErrors.name ?? []}
              autoComplete="off"
              disabled={saving}
              autoFocus
            />

            <Field
              label="Unit"
              type="text"
              value={form.unit}
              onChange={(value) => update({ unit: value })}
              errors={fieldErrors.unit ?? []}
              autoComplete="off"
              disabled={saving}
            />

            <Field
              label="Bottles per crate"
              type="number"
              value={form.bottles_per_crate}
              onChange={(value) => update({ bottles_per_crate: value })}
              errors={fieldErrors.bottles_per_crate ?? []}
              autoComplete="off"
              disabled={saving}
              min={2}
              step={1}
              inputMode="numeric"
              hint="e.g. 24. Leave blank if this product is not sold by the crate."
            />

            <div className="field">
              <label htmlFor="edit-product-quantity-mode" className="field-label">
                Quantity mode
              </label>
              <select
                id="edit-product-quantity-mode"
                value={form.quantity_mode}
                onChange={(event) => update({ quantity_mode: event.target.value as QuantityMode })}
                className="control"
                disabled={saving}
                aria-invalid={(fieldErrors.quantity_mode?.length ?? 0) > 0}
              >
                <option value="WHOLE">Whole units (crates, bottles)</option>
                <option value="FRACTIONAL">Fractional units (kg, litre)</option>
              </select>
              {(fieldErrors.quantity_mode ?? []).map((message) => (
                <p key={message} className="field-error">
                  {message}
                </p>
              ))}
              <p className="field-hint">
                Whole units are counted in whole numbers; fractional units allow decimals.
              </p>
            </div>

            {canChangePrices && (
              <Field
                label="Selling price (ETB)"
                type="number"
                value={form.price}
                onChange={(value) => update({ price: value })}
                errors={fieldErrors.price ?? []}
                autoComplete="off"
                disabled={saving}
                min={0}
                step="0.01"
                inputMode="decimal"
                hint="Saving a new price keeps the previous one in history"
              />
            )}

            <div className="field">
              <label htmlFor="edit-product-description" className="field-label">
                Description
              </label>
              <textarea
                id="edit-product-description"
                value={form.description}
                onChange={(event) => update({ description: event.target.value })}
                className="control"
                disabled={saving}
              />
              {(fieldErrors.description ?? []).map((message) => (
                <p key={message} className="field-error">
                  {message}
                </p>
              ))}
            </div>

            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={form.is_stock_tracked}
                onChange={(event) => update({ is_stock_tracked: event.target.checked })}
                disabled={saving}
              />
              Track stock
            </label>

            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => update({ is_active: event.target.checked })}
                disabled={saving}
              />
              Active (available for sale)
            </label>

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={onClose} disabled={saving}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ProductsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const canManage = user?.permissions.includes("products.manage_products") ?? false;
  const canChangePrices = user?.permissions.includes("products.change_prices") ?? false;

  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [categories, setCategories] = useState<Array<{ id: number; name: string }>>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [count, setCount] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "true" | "false">("all");
  const [stockTrackedFilter, setStockTrackedFilter] = useState<"all" | "true" | "false">("all");
  const [categoryFilter, setCategoryFilter] = useState<number | "all">("all");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [categoriesError, setCategoriesError] = useState<ApiError | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const requestId = useRef(0);

  const fetchProducts = useCallback(async () => {
    const request = ++requestId.current;
    setLoading(true);
    setError(null);
    setProducts([]);
    setCount(0);
    try {
      const query: Record<string, string | number | boolean> = {
        page,
        page_size: pageSize,
      };
      if (search) query.search = search;
      if (activeFilter !== "all") query.active = activeFilter === "true";
      if (stockTrackedFilter !== "all") query.stock_tracked = stockTrackedFilter === "true";
      if (categoryFilter !== "all") query.category = categoryFilter;

      const response = await listProducts({ query });
      if (request !== requestId.current) return;
      setProducts(response.results);
      setPages(response.pages);
      setCount(response.count);
    } catch (caught) {
      if (request === requestId.current) setError(caught as ApiError);
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }, [page, pageSize, search, activeFilter, stockTrackedFilter, categoryFilter]);

  const fetchCategories = useCallback(async () => {
    try {
      const response = await listCategories({ query: { active: true } });
      setCategories(response.results);
    } catch (caught) {
      setCategoriesError(caught as ApiError);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchProducts();
  }, [fetchProducts]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchCategories();
  }, [fetchCategories]);

  const handleSearchSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= pages) {
      setPage(newPage);
    }
  };

  const handleCreateClick = () => {
    router.push("/inventory/products/new");
  };

  return (
    <section className="flex flex-col gap-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Products</h1>
          <p className="text-sm text-ink-secondary">
            Manage the product catalogue — add, edit, or retire products.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={handleCreateClick}
            className="btn btn-primary self-start sm:self-auto"
          >
            Add Product
          </button>
        )}
      </div>

      <form onSubmit={handleSearchSubmit} className="flex flex-col gap-4">
        <ProductFilters
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
            setPage(1);
          }}
          activeFilter={activeFilter}
          onActiveFilterChange={(value) => {
            setActiveFilter(value);
            setPage(1);
          }}
          stockTrackedFilter={stockTrackedFilter}
          onStockTrackedFilterChange={(value) => {
            setStockTrackedFilter(value);
            setPage(1);
          }}
          categoryFilter={categoryFilter}
          onCategoryFilterChange={(value) => {
            setCategoryFilter(value);
            setPage(1);
          }}
          categories={categories}
        />
      </form>

      {categoriesError && <FormError error={categoriesError} />}
      {error && <FormError error={error} />}

      {loading ? (
        <div className="flex items-center justify-center py-8 text-ink-secondary">
          Loading products…
        </div>
      ) : (
        <>
          <ProductsTable products={products} canManage={canManage} onEdit={setEditingId} />
          {pages > 1 && (
            <PaginationControls
              page={page}
              pages={pages}
              pageSize={pageSize}
              count={count}
              onPageChange={handlePageChange}
              onPageSizeChange={handlePageSizeChange}
            />
          )}
        </>
      )}

      {editingId !== null && (
        <EditProductDialog
          productId={editingId}
          canChangePrices={canChangePrices}
          onClose={() => setEditingId(null)}
          onSaved={() => {
            setEditingId(null);
            void fetchProducts();
          }}
        />
      )}
    </section>
  );
}
