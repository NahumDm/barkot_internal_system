"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { useRouter } from "next/navigation";

import { listSales, voidSale, type SaleListItem } from "@/lib/api/sales";
import { type ApiError, isValidationError, isPermissionDenied, isNotFound } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { useT } from "@/lib/i18n/context";
import { Field, FormError } from "@/features/auth/form-parts";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

function formatMoney(amount: string, currency: string): string {
  return `${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function StatusBadge({ status }: { status: "COMPLETED" | "VOIDED" }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        status === "COMPLETED" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
      }`}
    >
      {status}
    </span>
  );
}

function PaymentStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        status === "PAID"
          ? "bg-green-100 text-green-800"
          : status === "PARTIAL"
            ? "bg-yellow-100 text-yellow-800"
            : "bg-slate-100 text-slate-800"
      }`}
    >
      {status}
    </span>
  );
}

function SaleRow({
  sale,
  onVoid,
  canVoid,
}: {
  sale: SaleListItem;
  onVoid: (id: number) => void;
  canVoid: boolean;
}) {
  const t = useT();
  return (
    <tr className="border-b border-border hover:bg-surface/50">
      <td className="px-3 py-2 text-sm text-ink font-mono">{sale.reference}</td>
      <td className="px-3 py-2 text-sm text-ink">{formatDate(sale.sold_at)}</td>
      <td className="px-3 py-2 text-sm text-ink">{formatMoney(sale.total, sale.currency)}</td>
      <td className="px-3 py-2 text-sm text-ink">{sale.item_count}</td>
      <td className="px-3 py-2 text-sm">
        <StatusBadge status={sale.status} />
      </td>
      <td className="px-3 py-2 text-sm">
        <PaymentStatusBadge status={sale.payment_status} />
      </td>
      {canVoid && (
        <td className="px-3 py-2 text-sm">
          {sale.status === "COMPLETED" && (
            <button
              onClick={() => onVoid(sale.id)}
              className="rounded border border-danger bg-surface px-2 py-1 text-xs font-medium text-danger hover:bg-danger/10"
            >
              {t("sales.voidAction")}
            </button>
          )}
        </td>
      )}
    </tr>
  );
}

function SalesTable({
  sales,
  onVoid,
  canVoid,
}: {
  sales: SaleListItem[];
  onVoid: (id: number) => void;
  canVoid: boolean;
}) {
  const t = useT();
  if (sales.length === 0) {
    return <div className="text-center py-8 text-ink-secondary">{t("sales.noSalesFound")}</div>;
  }

  return (
    <div className="overflow-x-auto rounded border border-border bg-surface">
      <table className="w-full text-left">
        <thead className="bg-surface border-b border-border">
          <tr>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colReference")}
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colDate")}
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colTotal")}
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colItems")}
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colStatus")}
            </th>
            <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
              {t("sales.colPayment")}
            </th>
            {canVoid && (
              <th className="px-3 py-2 text-xs font-semibold text-ink-secondary uppercase tracking-wider">
                {t("sales.colActions")}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {sales.map((sale) => (
            <SaleRow key={sale.id} sale={sale} onVoid={onVoid} canVoid={canVoid} />
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
  const t = useT();
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
              {size} {t("sales.perPage")}
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
          « {t("sales.first")}
        </button>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          ‹ {t("sales.prev")}
        </button>
        <span className="px-2 py-1 text-sm text-ink">
          {t("sales.pageOf").replace("{page}", String(page)).replace("{pages}", String(pages))}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page === pages}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          {t("sales.next")} ›
        </button>
        <button
          onClick={() => onPageChange(pages)}
          disabled={page === pages}
          className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/50"
        >
          {t("sales.last")} »
        </button>
      </div>
    </div>
  );
}

export default function SalesPage() {
  const router = useRouter();
  const { user } = useAuth();
  const t = useT();
  const canCreate = user?.permissions.includes("sales.create_sale") ?? false;
  const canVoid = user?.permissions.includes("sales.void_sale") ?? false;

  const [sales, setSales] = useState<SaleListItem[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [count, setCount] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "COMPLETED" | "VOIDED">("all");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  const fetchSales = useCallback(async () => {
    const request = ++requestId.current;
    setLoading(true);
    setError(null);
    setSales([]);
    setCount(0);
    try {
      const query: Record<string, string | number | boolean> = {
        page,
        page_size: pageSize,
      };
      if (search) query.search = search;
      if (statusFilter !== "all") query.status = statusFilter;

      const response = await listSales({ query });
      if (request !== requestId.current) return;
      setSales(response.results);
      setPages(response.pages);
      setCount(response.count);
    } catch (caught) {
      if (request === requestId.current) setError(caught as ApiError);
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }, [page, pageSize, search, statusFilter]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchSales();
  }, [fetchSales]);

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

  const handleVoid = async (id: number) => {
    if (!confirm("Are you sure you want to void this sale? This action cannot be undone.")) {
      return;
    }
    try {
      await voidSale(id, { reason: "Voided from sales list" });
      fetchSales();
    } catch (caught) {
      const error = caught as ApiError;
      if (isValidationError(error) || isPermissionDenied(error) || isNotFound(error)) {
        alert(error.message);
      } else {
        throw caught;
      }
    }
  };

  const handleCreateClick = () => {
    router.push("/sales/transactions/new");
  };

  return (
    <section className="flex flex-col gap-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{t("sales.title")}</h1>
          <p className="text-sm text-ink-secondary">{t("sales.subtitle")}</p>
        </div>
        {canCreate && (
          <button
            type="button"
            onClick={handleCreateClick}
            className="btn btn-primary self-start sm:self-auto"
          >
            {t("sales.newSale")}
          </button>
        )}
      </div>

      <form onSubmit={handleSearchSubmit} className="flex flex-col gap-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <Field
              label={t("sales.search")}
              type="search"
              value={search}
              onChange={(value) => {
                setSearch(value);
                setPage(1);
              }}
              errors={[]}
              autoComplete="off"
              hint={t("sales.searchByReference")}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as "all" | "COMPLETED" | "VOIDED");
                setPage(1);
              }}
              className="control control--inline"
            >
              <option value="all">{t("sales.allStatuses")}</option>
              <option value="COMPLETED">{t("sales.completed")}</option>
              <option value="VOIDED">{t("sales.voided")}</option>
            </select>
          </div>
        </div>
      </form>

      {error && <FormError error={error} />}

      {loading ? (
        <div className="flex items-center justify-center py-8 text-ink-secondary">
          Loading sales…
        </div>
      ) : (
        <>
          <SalesTable sales={sales} onVoid={handleVoid} canVoid={canVoid} />
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
