"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listSales, type SaleListItem, type Payment } from "@/lib/api/sales";
import { type ApiError } from "@/lib/api/errors";
import { Field, FormError } from "@/features/auth/form-parts";

const PAGE_SIZE = 20;

function formatMoney(amount: string, currency: string): string {
  return `${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/**
 * How a sale was paid, as a person would say it.
 *
 * A sale can be split across tenders, so the distinct methods are listed rather
 * than showing only the first; "Cash + Mobile Banking" is what actually
 * happened, and collapsing it to "Cash" would misreport the till.
 */
function paymentMethodLabel(payments: Payment[]): string {
  const labels = Array.from(
    new Set(
      payments.filter((payment) => !payment.voided_at).map((payment) => payment.method_display),
    ),
  );
  return labels.length > 0 ? labels.join(" + ") : "—";
}

function StatusBadge({ status }: { status: "COMPLETED" | "VOIDED" }) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
        status === "COMPLETED" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
      }`}
    >
      {status}
    </span>
  );
}

function TransactionRow({ sale }: { sale: SaleListItem }) {
  return (
    <tr className="border-b border-border hover:bg-surface/50">
      <td className="px-3 py-2 font-mono text-sm text-ink">{sale.reference}</td>
      <td className="px-3 py-2 text-sm text-ink">{formatDateTime(sale.sold_at)}</td>
      <td className="px-3 py-2 text-sm text-ink">{paymentMethodLabel(sale.payments)}</td>
      <td className="px-3 py-2 text-sm text-ink">{formatMoney(sale.total, sale.currency)}</td>
      <td className="px-3 py-2 text-sm">
        <StatusBadge status={sale.status} />
      </td>
      <td className="px-3 py-2 text-sm text-ink-secondary">{sale.payment_status_display}</td>
    </tr>
  );
}

export default function SalesTransactionsPage() {
  const [sales, setSales] = useState<SaleListItem[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [count, setCount] = useState(0);
  const pageSize = PAGE_SIZE;
  const [searchInput, setSearchInput] = useState("");
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
    void fetchSales();
  }, [fetchSales]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= pages) setPage(newPage);
  };

  const start = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, count);

  return (
    <section className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Transactions</h1>
        <p className="text-sm text-ink-secondary">
          Every recorded sale, with the payment method used to settle it.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchInput);
          setPage(1);
        }}
        className="flex flex-col gap-3 sm:flex-row sm:items-center"
      >
        <div className="min-w-0 flex-1">
          <Field
            label="Search"
            type="search"
            value={searchInput}
            onChange={setSearchInput}
            errors={[]}
            autoComplete="off"
            hint="Search by reference"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(event) => {
            setStatusFilter(event.target.value as "all" | "COMPLETED" | "VOIDED");
            setPage(1);
          }}
          className="control control--inline"
        >
          <option value="all">All statuses</option>
          <option value="COMPLETED">Completed</option>
          <option value="VOIDED">Voided</option>
        </select>
      </form>

      {error && <FormError error={error} />}

      {loading ? (
        <div className="flex items-center justify-center py-8 text-ink-secondary">
          Loading transactions…
        </div>
      ) : sales.length === 0 ? (
        <div className="py-8 text-center text-ink-secondary">No transactions found.</div>
      ) : (
        <>
          <div className="overflow-x-auto rounded border border-border bg-surface">
            <table className="w-full text-left">
              <thead className="border-b border-border bg-surface">
                <tr>
                  {["Reference", "Date & time", "Method", "Amount", "Status", "Payment"].map(
                    (heading) => (
                      <th
                        key={heading}
                        className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-ink-secondary"
                      >
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {sales.map((sale) => (
                  <TransactionRow key={sale.id} sale={sale} />
                ))}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div className="flex flex-col items-center justify-between gap-3 px-3 py-3 text-sm text-ink-secondary sm:flex-row">
              <span>
                Showing {start}–{end} of {count}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handlePageChange(page - 1)}
                  disabled={page === 1}
                  className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-40 hover:bg-surface/50"
                >
                  ‹ Prev
                </button>
                <span className="px-2 py-1 text-ink">
                  Page {page} of {pages}
                </span>
                <button
                  onClick={() => handlePageChange(page + 1)}
                  disabled={page === pages}
                  className="rounded border border-border bg-surface px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-40 hover:bg-surface/50"
                >
                  Next ›
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
