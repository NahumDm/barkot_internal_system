"use client";

import { useCallback, useEffect, useState, type FormEvent, type ChangeEvent } from "react";
import { useRouter } from "next/navigation";

import { listProducts, listCategories, type ProductListItem } from "@/lib/api/products";
import { type ApiError } from "@/lib/api/errors";
import { Field, FormError } from "@/features/auth/form-parts";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

function formatPrice(price: { unit_price: string; currency: string } | null): string {
  if (!price) return "—";
  return `${Number(price.unit_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${price.currency}`;
}

function ProductRow({ product }: { product: ProductListItem }) {
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
            product.is_active ? "bg-success/15 text-success" : "bg-canvas text-ink-secondary"
          }`}
        >
          {product.is_active ? "Active" : "Retired"}
        </span>
      </td>
    </tr>
  );
}

function ProductsTable({
  products,
  emptyMessage = "No products found.",
}: {
  products: ProductListItem[];
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
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <ProductRow key={product.id} product={product} />
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
    <div className="flex flex-col sm:flex-row gap-3 mb-4">
      <div className="flex-1 min-w-0">
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
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
        >
          <option value="all">All statuses</option>
          <option value="true">Active only</option>
          <option value="false">Retired only</option>
        </select>
        <select
          value={stockTrackedFilter}
          onChange={(e) => onStockTrackedFilterChange(e.target.value as "all" | "true" | "false")}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
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
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
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

export default function ProductsPage() {
  const router = useRouter();

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

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    setError(null);
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
      setProducts(response.results);
      setPages(response.pages);
      setCount(response.count);
    } catch (caught) {
      setError(caught as ApiError);
    } finally {
      setLoading(false);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
    void fetchProducts();
  }, [fetchProducts]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchCategories();
  }, [fetchCategories]);

  const handleSearchSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setPage(1);
    fetchProducts();
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
    fetchProducts();
  };

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= pages) {
      setPage(newPage);
      fetchProducts();
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
        <button
          onClick={handleCreateClick}
          className="rounded bg-brand px-4 py-2 text-sm font-medium text-ivory transition-colors hover:bg-brand-deep"
        >
          Add Product
        </button>
      </div>

      <form onSubmit={handleSearchSubmit} className="flex flex-col gap-4">
        <ProductFilters
          search={search}
          onSearchChange={setSearch}
          activeFilter={activeFilter}
          onActiveFilterChange={setActiveFilter}
          stockTrackedFilter={stockTrackedFilter}
          onStockTrackedFilterChange={setStockTrackedFilter}
          categoryFilter={categoryFilter}
          onCategoryFilterChange={setCategoryFilter}
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
          <ProductsTable products={products} />
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
    </section>
  );
}
