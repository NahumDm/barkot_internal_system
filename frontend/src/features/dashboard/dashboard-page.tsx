"use client";

import Link from "next/link";
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
import { useT } from "@/lib/i18n/context";
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
  const t = useT();
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
    setData(null);
    setError(null);
    setStart(value);
  };
  const changeEnd = (value: string) => {
    setLoading(true);
    setData(null);
    setError(null);
    setEnd(value);
  };
  const resetToMonth = () => {
    setLoading(true);
    setData(null);
    setError(null);
    setStart(initialStart);
    setEnd(todayISO());
  };

  return (
    <section className="space-y-6">
      <PageHeader
        eyebrow={t("dashboard.eyebrow")}
        title={t("dashboard.title")}
        blurb={t("dashboard.blurb")}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <DateRangeFilter start={start} end={end} onStart={changeStart} onEnd={changeEnd} />
        <button type="button" onClick={resetToMonth} className="btn btn-secondary">
          {t("dashboard.thisMonth")}
        </button>
      </div>
      <ErrorBanner error={error} />
      {loading && <LoadingNote label={t("dashboard.loading")} />}
      {data && !loading && (
        <>
          <MetricsGrid data={data} />
          <div className="panels grid gap-4 lg:grid-cols-2">
            {data.sales ? (
              <SalesPanel sales={data.sales} />
            ) : canViewSales ? (
              <SectionNote>{t("dashboard.noSales")}</SectionNote>
            ) : (
              <SectionNote>{t("dashboard.salesNotShown")}</SectionNote>
            )}
            {data.inventory ? (
              <InventoryPanel inventory={data.inventory} />
            ) : canViewInventory ? (
              <SectionNote>{t("dashboard.noStock")}</SectionNote>
            ) : (
              <SectionNote>{t("dashboard.stockNotShown")}</SectionNote>
            )}
            {data.finance ? (
              <FinancePanel finance={data.finance} />
            ) : canViewFinance ? (
              <SectionNote>{t("dashboard.noFinance")}</SectionNote>
            ) : (
              <SectionNote>{t("dashboard.financeNotShown")}</SectionNote>
            )}
            {data.payroll ? (
              <PayrollPanel payroll={data.payroll} />
            ) : canViewPayroll ? (
              <SectionNote>{t("dashboard.noPayroll")}</SectionNote>
            ) : (
              <SectionNote>{t("dashboard.payrollNotShown")}</SectionNote>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function MetricsGrid({ data }: { data: DashboardResponse }) {
  const t = useT();
  const metrics: { label: string; value: string }[] = [];

  if (data.sales) {
    metrics.push(
      { label: t("dashboard.takings"), value: money(data.sales.total) },
      { label: t("dashboard.cash"), value: money(data.sales.cash) },
      { label: t("dashboard.mobileBanking"), value: money(data.sales.mobile_banking) },
      { label: t("dashboard.transactions"), value: String(data.sales.transactions) },
    );
  }
  if (data.inventory) {
    metrics.push(
      { label: t("dashboard.inStock"), value: data.inventory.in_stock_total },
      { label: t("dashboard.products"), value: String(data.inventory.products) },
    );
  }
  if (data.finance) {
    metrics.push(
      { label: t("dashboard.netResult"), value: money(data.finance.net, data.finance.currency) },
      {
        label: t("dashboard.approvedExpenses"),
        value: money(data.finance.expenses_total, data.finance.currency),
      },
    );
  }
  if (data.payroll) {
    metrics.push({ label: t("dashboard.latestRunNet"), value: money(data.payroll.net_total) });
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
  const t = useT();
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">{t("dashboard.salesTitle")}</h2>
          <p className="panel-sub text-xs text-ink-secondary">
            {sales.transactions} transaction{sales.transactions === 1 ? "" : "s"} totalling{" "}
            {money(sales.total)}
          </p>
        </div>
        <Link
          href="/sales"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          {t("dashboard.openSales")}
        </Link>
      </div>
      {sales.recent.length === 0 ? (
        <EmptyNote>{t("dashboard.noSalesInPeriod")}</EmptyNote>
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
  const t = useT();
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">{t("dashboard.inventoryTitle")}</h2>
          <p className="panel-sub text-xs text-ink-secondary">As of {dateStamp(inventory.as_of)}</p>
        </div>
        <Link
          href="/inventory"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          {t("dashboard.openInventory")}
        </Link>
      </div>
      <dl className="panel-list-lg mt-3 space-y-3 text-sm">
        <Line label={t("dashboard.inStock")} value={inventory.in_stock_total} />
        <Line label={t("dashboard.products")} value={String(inventory.products)} />
      </dl>
    </section>
  );
}

function FinancePanel({ finance }: { finance: FinanceBalance }) {
  const t = useT();
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">{t("dashboard.financeTitle")}</h2>
          <p className="panel-sub text-xs text-ink-secondary">
            {dateStamp(finance.period_start)} – {dateStamp(finance.period_end)}
          </p>
        </div>
        <Link
          href="/reports"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          {t("dashboard.openReports")}
        </Link>
      </div>
      <dl className="mt-3 space-y-3 text-sm">
        <Line label={t("dashboard.income")} value={money(finance.income.total, finance.currency)} />
        <Line label={t("dashboard.approvedExpenses")} value={money(finance.expenses_total, finance.currency)} />
        <Line label={t("dashboard.approvedPayroll")} value={money(finance.payroll_total, finance.currency)} />
        <Line label={t("dashboard.netResult")} value={money(finance.net, finance.currency)} />
      </dl>
      {Object.entries(finance.expense_breakdown).length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wider text-ink-secondary">
            {t("dashboard.expensesByCategory")}
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
  const t = useT();
  return (
    <section className="panel rounded border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="panel-title text-sm font-semibold text-ink">{t("dashboard.payrollTitle")}</h2>
          <p className="panel-sub text-xs text-ink-secondary">{monthLabel(payroll.period_month)}</p>
        </div>
        <Link
          href="/payroll/runs"
          className="btn-outline text-sm font-medium text-ink hover:text-ink-secondary"
        >
          {t("dashboard.openPayroll")}
        </Link>
      </div>
      <div className="mt-3 space-y-3 text-sm">
        <StatusChip status={payroll.status} display={payroll.status_display} />
        <dl className="space-y-3">
          <Line label={t("dashboard.gross")} value={money(payroll.gross_total)} />
          <Line label={t("dashboard.deductions")} value={money(payroll.deduction_total)} />
          <Line label={t("dashboard.netPay")} value={money(payroll.net_total)} />
        </dl>
        <p className="text-xs text-ink-secondary">
          {payroll.approved_by_username
            ? `Approved by ${payroll.approved_by_username}${
                payroll.approved_at ? ` on ${dateStamp(payroll.approved_at)}` : ""
              }.`
            : "Generated but not approved yet."}
        </p>
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
