"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useT } from "@/lib/i18n/context";

import { DateField, DateRangeFilter } from "@/components/date-range-filter";
import {
  financialPdfUrl,
  getFinancialReport,
  getPayrollReport,
  getStockBalance,
  getStockVariance,
  payrollPdfUrl,
  stockBalancePdfUrl,
  stockVariancePdfUrl,
  type PayrollReport,
  type StockBalanceReport,
  type StockVarianceReport,
} from "@/lib/api";
import { type ApiError } from "@/lib/api/errors";
import type { FinanceBalance } from "@/lib/api/finance";
import { useAuth } from "@/features/auth/auth-provider";
import { dateStamp, money, monthLabel, todayISO } from "@/features/payroll/format";
import { EmptyNote, ErrorBanner, LoadingNote, StatusChip } from "@/features/payroll/parts";

/**
 * The reports page (spec §15): three read-only tabs over a shared date range,
 * each with its data read back from the domain that owns it and its own export.
 *
 * Nothing is computed here. The financial tab renders the exact object the
 * balance screen renders, the inventory tabs read the ledger and approved
 * counts, and the payroll tab reads run rows — the screen is a projection of
 * what the domains already decided, so it cannot disagree with them (spec §6.2).
 *
 * Exports are plain anchors to a URL carrying ``export=pdf``. The backend
 * answers with ``Content-Disposition: attachment``, so the browser downloads
 * the file; the URL is same-origin, so the session cookie travels with it.
 */

type Tab = "financial" | "inventory" | "payroll";

function monthStartToday(): { start: string; end: string } {
  const now = new Date();
  const start = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  return { start, end: todayISO() };
}

export default function ReportsPage() {
  const t = useT();
  const { status, user } = useAuth();
  const canView = user?.permissions.includes("finance.view_reports") ?? false;
  const checking = status === "checking";

  const initialPeriod = monthStartToday();
  const [tab, setTab] = useState<Tab>("financial");
  const [start, setStart] = useState(initialPeriod.start);
  const [end, setEnd] = useState(initialPeriod.end);
  const [asOf, setAsOf] = useState(todayISO());

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            {t("reports.eyebrow")}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{t("reports.title")}</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            {t("reports.blurb")}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <TabButton
            active={tab === "financial"}
            label="Financial"
            onClick={() => setTab("financial")}
          />
          <TabButton
            active={tab === "inventory"}
            label="Inventory"
            onClick={() => setTab("inventory")}
          />
          <TabButton active={tab === "payroll"} label="Payroll" onClick={() => setTab("payroll")} />
        </div>
      </div>

      {checking ? (
        <LoadingNote label="Checking access..." />
      ) : !canView ? (
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include reports. Ask an owner if you need access.
        </div>
      ) : (
        <>
          {tab === "financial" && (
            <FinancialTab start={start} end={end} onStart={setStart} onEnd={setEnd} />
          )}
          {tab === "inventory" && (
            <InventoryTab
              period={{ start, end, onStart: setStart, onEnd: setEnd }}
              asOf={asOf}
              onAsOf={setAsOf}
            />
          )}
          {tab === "payroll" && (
            <PayrollTab start={start} end={end} onStart={setStart} onEnd={setEnd} />
          )}
        </>
      )}
    </section>
  );
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded px-3 py-1.5 text-sm font-medium ${
        active ? "bg-ink text-canvas" : "bg-surface text-ink-secondary hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}

function DownloadPdf({ href, label = "Download PDF" }: { href: string; label?: string }) {
  return (
    <a href={href} className="btn btn-secondary">
      {label}
    </a>
  );
}

function FinancialTab({
  start,
  end,
  onStart,
  onEnd,
}: {
  start: string;
  end: string;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
}) {
  const [balance, setBalance] = useState<FinanceBalance | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getFinancialReport(start, end)
      .then((value) => {
        if (active) {
          setBalance(value);
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
    setBalance(null);
    setError(null);
    onStart(value);
  };
  const changeEnd = (value: string) => {
    setLoading(true);
    setBalance(null);
    setError(null);
    onEnd(value);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <DateRangeFilter start={start} end={end} onStart={changeStart} onEnd={changeEnd} />
        <DownloadPdf href={financialPdfUrl(start, end)} />
      </div>
      <ErrorBanner error={error} />
      {loading && <LoadingNote label="Loading financial report..." />}
      {balance && !loading && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Income (cash)" value={money(balance.income.cash, balance.currency)} />
            <Metric
              label="Income (mobile banking)"
              value={money(balance.income.mobile_banking, balance.currency)}
            />
            <Metric
              label="Approved expenses"
              value={money(balance.expenses_total, balance.currency)}
            />
            <Metric
              label="Approved payroll"
              value={money(balance.payroll_total, balance.currency)}
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Income</h2>
              <dl className="mt-4 space-y-3 text-sm">
                <Line label="Cash" value={money(balance.income.cash, balance.currency)} />
                <Line
                  label="Mobile banking"
                  value={money(balance.income.mobile_banking, balance.currency)}
                />
                <Line label="Total" value={money(balance.income.total, balance.currency)} />
              </dl>
            </section>
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Net result</h2>
              <dl className="mt-4 space-y-3 text-sm">
                <Line label="Income" value={money(balance.income.total, balance.currency)} />
                <Line label="Expenses" value={money(balance.expenses_total, balance.currency)} />
                <Line label="Payroll" value={money(balance.payroll_total, balance.currency)} />
                <Line label="Balance" value={money(balance.net, balance.currency)} />
              </dl>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function InventoryTab({
  period,
  asOf,
  onAsOf,
}: {
  period: {
    start: string;
    end: string;
    onStart: (value: string) => void;
    onEnd: (value: string) => void;
  };
  asOf: string;
  onAsOf: (value: string) => void;
}) {
  const [balance, setBalance] = useState<StockBalanceReport | null>(null);
  const [balanceError, setBalanceError] = useState<ApiError | null>(null);
  const [balanceLoading, setBalanceLoading] = useState(true);
  const [variance, setVariance] = useState<StockVarianceReport | null>(null);
  const [varianceError, setVarianceError] = useState<ApiError | null>(null);
  const [varianceLoading, setVarianceLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getStockBalance(asOf)
      .then((value) => {
        if (active) {
          setBalance(value);
          setBalanceError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setBalanceError(value as ApiError);
      })
      .finally(() => {
        if (active) setBalanceLoading(false);
      });
    return () => {
      active = false;
    };
  }, [asOf]);

  useEffect(() => {
    let active = true;
    getStockVariance(period.start, period.end)
      .then((value) => {
        if (active) {
          setVariance(value);
          setVarianceError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setVarianceError(value as ApiError);
      })
      .finally(() => {
        if (active) setVarianceLoading(false);
      });
    return () => {
      active = false;
    };
  }, [period.start, period.end]);

  const changeAsOf = (value: string) => {
    setBalanceLoading(true);
    setBalance(null);
    setBalanceError(null);
    onAsOf(value);
  };
  const changeStart = (value: string) => {
    setVarianceLoading(true);
    setVariance(null);
    setVarianceError(null);
    period.onStart(value);
  };
  const changeEnd = (value: string) => {
    setVarianceLoading(true);
    setVariance(null);
    setVarianceError(null);
    period.onEnd(value);
  };

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded border border-border bg-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Stock balance</h2>
            <p className="text-xs text-ink-secondary">Ledger stock vs the latest approved count.</p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <DateField label="As of" value={asOf} onChange={changeAsOf} />
            <DownloadPdf href={stockBalancePdfUrl(asOf)} />
          </div>
        </div>
        <ErrorBanner error={balanceError} />
        {balanceLoading && <LoadingNote label="Loading stock balance..." />}
        {balance && !balanceLoading && (
          <>
            <p className="text-sm text-ink-secondary">
              In stock: <span className="font-medium text-ink">{balance.in_stock_total}</span>{" "}
              across {balance.products} product{balance.products === 1 ? "" : "s"}.
            </p>
            {balance.rows.length === 0 ? (
              <EmptyNote>No stock movements before this date.</EmptyNote>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs text-ink-secondary">
                      <Th>SKU</Th>
                      <Th>Product</Th>
                      <Th className="text-right">Ledger</Th>
                      <Th className="text-right">Last counted</Th>
                      <Th>Last counted on</Th>
                      <Th className="text-right">Delta</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {balance.rows.map((row) => (
                      <tr key={row.product_id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3 text-ink-secondary">{row.sku}</td>
                        <td className="py-2 pr-3 text-ink">{row.name}</td>
                        <td className="py-2 pr-3 text-right text-ink">{row.ledger_balance}</td>
                        <td className="py-2 pr-3 text-right text-ink">
                          {row.last_counted ?? (
                            <span className="text-ink-secondary">not counted</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-ink-secondary">
                          {row.last_counted_on ? dateStamp(row.last_counted_on) : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right text-ink">{row.delta ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      <section className="space-y-4 rounded border border-border bg-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Inventory variance</h2>
            <p className="text-xs text-ink-secondary">
              Approved counts where counted differed from expected.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <DateRangeFilter
              start={period.start}
              end={period.end}
              onStart={changeStart}
              onEnd={changeEnd}
            />
            <DownloadPdf href={stockVariancePdfUrl(period.start, period.end)} />
          </div>
        </div>
        <ErrorBanner error={varianceError} />
        {varianceLoading && <LoadingNote label="Loading variances..." />}
        {variance && !varianceLoading && (
          <>
            {variance.lines === 0 ? (
              <EmptyNote>No approved variances in this period.</EmptyNote>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs text-ink-secondary">
                      <Th>Count</Th>
                      <Th>Status</Th>
                      <Th>Counted on</Th>
                      <Th>SKU</Th>
                      <Th>Product</Th>
                      <Th className="text-right">Expected</Th>
                      <Th className="text-right">Counted</Th>
                      <Th className="text-right">Variance</Th>
                      <Th>Note</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {variance.rows.map((row) => (
                      <tr key={row.stock_count_id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3 text-ink-secondary">#{row.stock_count_id}</td>
                        <td className="py-2 pr-3">
                          <StatusChip status={row.status} display={row.status} />
                        </td>
                        <td className="py-2 pr-3 text-ink-secondary">
                          {dateStamp(row.counted_on)}
                        </td>
                        <td className="py-2 pr-3 text-ink-secondary">{row.sku}</td>
                        <td className="py-2 pr-3 text-ink">{row.name}</td>
                        <td className="py-2 pr-3 text-right text-ink">{row.expected_quantity}</td>
                        <td className="py-2 pr-3 text-right text-ink">{row.counted_quantity}</td>
                        <td className="py-2 pr-3 text-right font-medium text-ink">
                          {row.variance}
                        </td>
                        <td className="py-2 pr-3 text-ink-secondary">{row.note || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function PayrollTab({
  start,
  end,
  onStart,
  onEnd,
}: {
  start: string;
  end: string;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
}) {
  const [report, setReport] = useState<PayrollReport | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getPayrollReport(start, end)
      .then((value) => {
        if (active) {
          setReport(value);
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
    setReport(null);
    setError(null);
    onStart(value);
  };
  const changeEnd = (value: string) => {
    setLoading(true);
    setReport(null);
    setError(null);
    onEnd(value);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <DateRangeFilter start={start} end={end} onStart={changeStart} onEnd={changeEnd} />
        <DownloadPdf href={payrollPdfUrl(start, end)} />
      </div>
      <ErrorBanner error={error} />
      {loading && <LoadingNote label="Loading payroll report..." />}
      {report && !loading && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <Metric label="Runs" value={String(report.summary.runs)} />
            <Metric
              label="Gross total"
              value={money(report.summary.gross_total, report.currency)}
            />
            <Metric
              label="Deduction total"
              value={money(report.summary.deduction_total, report.currency)}
            />
            <Metric label="Net total" value={money(report.summary.net_total, report.currency)} />
          </div>
          {report.rows.length === 0 ? (
            <EmptyNote>No payroll runs in this period.</EmptyNote>
          ) : (
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Runs</h2>
              <div className="overflow-x-auto">
                <table className="mt-3 w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs text-ink-secondary">
                      <Th>Month</Th>
                      <Th>Status</Th>
                      <Th className="text-right">Employees</Th>
                      <Th className="text-right">Gross</Th>
                      <Th className="text-right">Deductions</Th>
                      <Th className="text-right">Net</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row) => (
                      <tr key={row.run_id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3 text-ink">{monthLabel(row.period_month)}</td>
                        <td className="py-2 pr-3">
                          <StatusChip status={row.status} display={row.status_display} />
                        </td>
                        <td className="py-2 pr-3 text-right text-ink">{row.employees}</td>
                        <td className="py-2 pr-3 text-right text-ink">
                          {money(row.gross_total, row.currency)}
                        </td>
                        <td className="py-2 pr-3 text-right text-ink">
                          {money(row.deduction_total, row.currency)}
                        </td>
                        <td className="py-2 pr-3 text-right font-medium text-ink">
                          {money(row.net_total, row.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">By status</h2>
              <dl className="mt-4 space-y-3 text-sm">
                {report.summary.by_status.length === 0 ? (
                  <EmptyNote>No runs in this period.</EmptyNote>
                ) : (
                  report.summary.by_status.map((bucket) => (
                    <Line
                      key={bucket.status}
                      label={`${bucket.status_display} (${bucket.runs})`}
                      value={money(bucket.net_total, report.currency)}
                    />
                  ))
                )}
              </dl>
            </section>
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Deductions by type</h2>
              <dl className="mt-4 space-y-3 text-sm">
                {Object.entries(report.deductions).length === 0 ? (
                  <EmptyNote>No deductions in this period.</EmptyNote>
                ) : (
                  Object.entries(report.deductions).map(([label, value]) => (
                    <Line key={label} label={label} value={money(value, report.currency)} />
                  ))
                )}
              </dl>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-ink-secondary">{label}</p>
      <p className="mt-2 text-xl font-semibold text-ink">{value}</p>
    </article>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border pb-2 last:border-0 last:pb-0">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}

function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <th className={`py-1.5 pr-3 font-medium ${className}`}>{children}</th>;
}
