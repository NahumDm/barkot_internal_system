"use client";

import { useEffect, useState, type ReactNode } from "react";

import { DateRangeFilter } from "@/components/date-range-filter";
import {
  getDashboard,
  type DashboardInventory,
  type DashboardPayroll,
  type DashboardResponse,
  type DashboardSales,
} from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import type { FinanceBalance } from "@/lib/api/finance";
import { useAuth } from "@/features/auth/auth-provider";
import { dateStamp, money, monthLabel, todayISO } from "@/features/payroll/format";
import {
  EmptyNote,
  ErrorBanner,
  LoadingNote,
  PageHeader,
  StatusChip,
} from "@/features/payroll/parts";

/**
 * The dashboard (roadmap C6): one screen over the whole business, read back
 * from the domains that own it so it cannot disagree with them (spec §6.2).
 *
 * The server gates each section on the role and answers `null` for the ones it
 * refuses — but `null` is also how a permitted section with no data arrives
 * (an Owner before the first payroll run exists has no run, not a denied one).
 * The session's own permission list tells the two apart, exactly as the reports
 * screen already does: presentation only, since the server refuses the number
 * either way and every figure drawn here still comes from the wire.
 *
 * Dates are honest about the local calendar: the default period is this month
 * in the browser, built the same way the payroll helpers build `YYYY-MM-01`.
 */

function monthStartToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const granted = user?.permissions ?? [];
  const canViewSales = granted.includes("sales.view_sales");
  const canViewInventory = granted.includes("inventory.view_inventory");
  const canViewFinance = granted.includes("finance.view_reports");
  const canViewPayroll = granted.includes("payroll.view_payroll");

  const initialStart = monthStartToday();
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(todayISO());
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getDashboard(start, end)
      .then((value) => {
        if (active) {
          setData(value);
          setError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setError(value as ApiError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [start, end]);

  const changeStart = (value: string) => {
    setLoading(true);
    setStart(value);
  };
  const changeEnd = (value: string) => {
    setLoading(true);
    setEnd(value);
  };
  const resetToMonth = () => {
    setLoading(true);
    setStart(initialStart);
    setEnd(todayISO());
  };

  return (
    <section className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        blurb="The position of the business for the period, read straight from each domain."
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <DateRangeFilter start={start} end={end} onStart={changeStart} onEnd={changeEnd} />
        <button type="button" onClick={resetToMonth} className="btn btn-secondary">
          This month
        </button>
      </div>
      <ErrorBanner error={error} />
      {loading && <LoadingNote label="Loading dashboard..." />}
      {data && !loading && (
        <>
          <MetricsGrid data={data} />
          <div className="panels grid gap-4 lg:grid-cols-2">
            {data.sales ? (
              <SalesPanel sales={data.sales} />
            ) : canViewSales ? (
              <SectionNote>No sales recorded for this period.</SectionNote>
            ) : (
              <SectionNote>Sales are not shown for your role.</SectionNote>
            )}
            {data.inventory ? (
              <InventoryPanel inventory={data.inventory} />
            ) : canViewInventory ? (
              <SectionNote>No stock to show for this period.</SectionNote>
            ) : (
              <SectionNote>Stock is not shown for your role.</SectionNote>
            )}
            {data.finance ? (
              <FinancePanel finance={data.finance} />
            ) : canViewFinance ? (
              <SectionNote>Nothing recorded for this period yet.</SectionNote>
            ) : (
              <SectionNote>Finance is not shown for your role.</SectionNote>
            )}
            {data.payroll ? (
              <PayrollPanel payroll={data.payroll} />
            ) : canViewPayroll ? (
              <SectionNote>No payroll run has been generated yet.</SectionNote>
            ) : (
              <SectionNote>Payroll is not shown for your role.</SectionNote>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function MetricsGrid({ data }: { data: DashboardResponse }) {
  const metrics: { label: string; value: string }[] = [];

  if (data.sales) {
    metrics.push(
      { label: "Takings", value: money(data.sales.total) },
      { label: "Cash", value: money(data.sales.cash) },
      { label: "Mobile banking", value: money(data.sales.mobile_banking) },
      { label: "Transactions", value: String(data.sales.transactions) },
    );
  }
  if (data.inventory) {
    metrics.push(
      { label: "In stock", value: data.inventory.in_stock_total },
      { label: "Products", value: String(data.inventory.products) },
    );
  }
  if (data.finance) {
    metrics.push(
      { label: "Net result", value: money(data.finance.net, data.finance.currency) },
      {
        label: "Approved expenses",
        value: money(data.finance.expenses_total, data.finance.currency),
      },
    );
  }
  if (data.payroll) {
    metrics.push({ label: "Latest run net", value: money(data.payroll.net_total) });
  }

  return (
    <div className="kpi-grid grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric) => (
        <Metric key={metric.label} label={metric.label} value={metric.value} />
      ))}
    </div>
  );
}

function SalesPanel({ sales }: { sales: DashboardSales }) {
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">Sales</h2>
          <p className="panel-sub text-xs text-ink-secondary">
            {sales.transactions} transaction{sales.transactions === 1 ? "" : "s"} totalling{" "}
            {money(sales.total)}
          </p>
        </div>
        <a
          href="/sales"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          Open sales
        </a>
      </div>
      {sales.recent.length === 0 ? (
        <EmptyNote>No sales in this period.</EmptyNote>
      ) : (
        <div className="mt-3 space-y-2">
          {sales.recent.map((sale) => (
            <div
              key={sale.id}
              className="panel-row flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0 last:pb-0"
            >
              <div className="text-sm">
                <p className="font-medium text-ink">{sale.reference}</p>
                <p className="text-xs text-ink-secondary">{dateStamp(sale.sold_at)}</p>
              </div>
              <div className="text-right text-sm">
                <p className="panel-row-value font-medium text-ink">
                  {money(sale.total, sale.currency)}
                </p>
                <p className="text-xs text-ink-secondary">{sale.payment_status_display}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function InventoryPanel({ inventory }: { inventory: DashboardInventory }) {
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">Inventory</h2>
          <p className="panel-sub text-xs text-ink-secondary">As of {dateStamp(inventory.as_of)}</p>
        </div>
        <a
          href="/inventory"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          Open inventory
        </a>
      </div>
      <dl className="panel-list-lg mt-3 space-y-3 text-sm">
        <Line label="In stock" value={inventory.in_stock_total} />
        <Line label="Products" value={String(inventory.products)} />
      </dl>
    </section>
  );
}

function FinancePanel({ finance }: { finance: FinanceBalance }) {
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">Finance</h2>
          <p className="panel-sub text-xs text-ink-secondary">
            {dateStamp(finance.period_start)} – {dateStamp(finance.period_end)}
          </p>
        </div>
        <a
          href="/reports"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          Open reports
        </a>
      </div>
      <dl className="mt-3 space-y-3 text-sm">
        <Line label="Income" value={money(finance.income.total, finance.currency)} />
        <Line label="Approved expenses" value={money(finance.expenses_total, finance.currency)} />
        <Line label="Approved payroll" value={money(finance.payroll_total, finance.currency)} />
        <Line label="Net result" value={money(finance.net, finance.currency)} />
      </dl>
      {Object.entries(finance.expense_breakdown).length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wider text-ink-secondary">
            Expenses by category
          </p>
          <dl className="mt-2 space-y-2 text-sm">
            {Object.entries(finance.expense_breakdown).map(([category, total]) => (
              <Line key={category} label={category} value={money(total, finance.currency)} />
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}

function PayrollPanel({ payroll }: { payroll: DashboardPayroll }) {
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">Payroll</h2>
          <p className="panel-sub text-xs text-ink-secondary">{monthLabel(payroll.period_month)}</p>
        </div>
        <a
          href="/payroll/runs"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          Open payroll
        </a>
      </div>
      <div className="mt-3 space-y-3 text-sm">
        <StatusChip status={payroll.status} display={payroll.status_display} />
        <dl className="space-y-3">
          <Line label="Gross" value={money(payroll.gross_total)} />
          <Line label="Deductions" value={money(payroll.deduction_total)} />
          <Line label="Net pay" value={money(payroll.net_total)} />
        </dl>
        <p className="text-xs text-ink-secondary">
          {payroll.approved_by_username
            ? `Approved by ${payroll.approved_by_username}${
                payroll.approved_at ? ` on ${dateStamp(payroll.approved_at)}` : ""
              }.`
            : "Generated but not approved yet."}
        </p>
      </div>
    </section>
  );
}

/**
 * A panel slot that has nothing to draw — either because the role is not
 * granted the section or because the section is genuinely empty. The two read
 * differently, which is the whole reason the caller consults the session's
 * permission list before landing here.
 */
function SectionNote({ children }: { children: ReactNode }) {
  return (
    <section className="section-note rounded border border-dashed border-border bg-surface/50 p-4 text-sm text-ink-secondary">
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article
      className={`kpi ${label === "Takings" ? "takings" : ""} rounded border border-border bg-surface p-4`.trim()}
    >
      <p className="kpi-label text-xs font-medium uppercase tracking-wider text-ink-secondary">
        {label}
      </p>
      <p className="kpi-value mt-2 text-xl font-semibold text-ink">{value}</p>
    </article>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-row flex items-center justify-between border-b border-border pb-2 last:border-0 last:pb-0">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}
