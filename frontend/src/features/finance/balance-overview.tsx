"use client";

import { useEffect, useState } from "react";

import { getFinanceBalance, type FinanceBalance } from "@/lib/api/finance";
import { type ApiError } from "@/lib/api/errors";

function monthPeriod(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const format = (date: Date) => date.toISOString().slice(0, 10);
  return { start: format(start), end: format(end) };
}

function money(value: string, currency = "ETB"): string {
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export default function BalanceOverview() {
  const initialPeriod = monthPeriod();
  const [start, setStart] = useState(initialPeriod.start);
  const [end, setEnd] = useState(initialPeriod.end);
  const [balance, setBalance] = useState<FinanceBalance | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getFinanceBalance(start, end)
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

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Finance
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Business balance</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            Income less approved expenses and payroll.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-medium text-ink-secondary">
            From
            <input
              type="date"
              value={start}
              onChange={(event) => {
                setLoading(true);
                setStart(event.target.value);
              }}
              className="mt-1 block rounded border border-border bg-surface px-2 py-1.5 text-sm text-ink"
            />
          </label>
          <label className="text-xs font-medium text-ink-secondary">
            To
            <input
              type="date"
              value={end}
              onChange={(event) => {
                setLoading(true);
                setEnd(event.target.value);
              }}
              className="mt-1 block rounded border border-border bg-surface px-2 py-1.5 text-sm text-ink"
            />
          </label>
        </div>
      </div>

      {error && (
        <p className="rounded border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error.message}
        </p>
      )}
      {loading && <p className="text-sm text-ink-secondary">Loading balance...</p>}
      {balance && !loading && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Income"
              value={money(balance.income.total, balance.currency)}
              tone="positive"
            />
            <Metric
              label="Approved expenses"
              value={money(balance.expenses_total, balance.currency)}
            />
            <Metric label="Payroll" value={money(balance.payroll_total, balance.currency)} />
            <Metric
              label="Business balance"
              value={money(balance.net, balance.currency)}
              tone="accent"
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Income by method</h2>
              <dl className="mt-4 space-y-3 text-sm">
                <Line label="Cash" value={money(balance.income.cash, balance.currency)} />
                <Line
                  label="Mobile banking"
                  value={money(balance.income.mobile_banking, balance.currency)}
                />
              </dl>
            </section>
            <section className="rounded border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Expenses by category</h2>
              <dl className="mt-4 space-y-3 text-sm">
                {Object.entries(balance.expense_breakdown).length === 0 ? (
                  <p className="text-ink-secondary">No approved expenses in this period.</p>
                ) : (
                  Object.entries(balance.expense_breakdown).map(([label, value]) => (
                    <Line key={label} label={label} value={money(value, balance.currency)} />
                  ))
                )}
              </dl>
            </section>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  const colors =
    tone === "positive" ? "text-success" : tone === "accent" ? "text-brand" : "text-ink";
  return (
    <article className="rounded border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-ink-secondary">{label}</p>
      <p className={`mt-2 text-xl font-semibold ${colors}`}>{value}</p>
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
