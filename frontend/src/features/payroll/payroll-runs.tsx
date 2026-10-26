"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useT } from "@/lib/i18n/context";

import {
  approvePayrollRun,
  generatePayrollRun,
  listPayrollItems,
  listPayrollRuns,
  markPayrollRunPaid,
  type PayrollItem,
  type PayrollRun,
} from "@/lib/api";
import { isInvalidStateTransition, type ApiError } from "@/lib/api/errors";

import {
  currentMonthKey,
  dateStamp,
  money,
  monthKeyOf,
  monthLabel,
  monthToPeriod,
  shiftMonthKey,
} from "./format";
import { usePayrollPermissions } from "./permissions";
import { EmptyNote, ErrorBanner, LoadingNote, NoAccessNote, PageHeader, StatusChip } from "./parts";

/**
 * A month of payroll: generate it, sign it off, record that it was paid
 * (spec §14.1).
 *
 * **The screen is organised around a month, not around a run list.** Payroll is
 * asked for as "what are we paying in October", so the month is the thing being
 * navigated and the run is whatever exists for it. Months with a run are offered
 * as chips because the picker alone gives no hint that anything has been
 * generated at all.
 *
 * **Paid and Pending are derived from the run's own status, not summed from the
 * lines.** The lifecycle advances every line together, so summing them would
 * agree with the run today and diverge the moment the model ever allowed a
 * partially paid run. Reading `status` states the one thing that is true:
 * whether the money has left.
 *
 * **Nothing is added up in this file.** Gross, deductions and net come from
 * `PayrollItem`, which recomputes them on save. Two implementations of the same
 * arithmetic is one too many, and the disagreement would show up as a payslip
 * nobody could explain.
 *
 * The lines are remembered *per run* rather than cleared when the month changes.
 * There is no effect that empties state: `itemsForRun` records which run the
 * rows belong to, and a row from a month that is no longer selected simply is
 * not shown. Clearing instead would mean writing synchronously inside an effect
 * to undo something the previous render had already made wrong.
 */
export default function PayrollRuns() {
  const t = useT();
  const {
    checking,
    view: canView,
    generate: canGenerate,
    markPaid,
    approve,
  } = usePayrollPermissions();

  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [runsReady, setRunsReady] = useState(false);
  const [items, setItems] = useState<PayrollItem[]>([]);
  const [itemsForRun, setItemsForRun] = useState<number | null>(null);
  const [month, setMonth] = useState<string>(currentMonthKey);
  const [error, setError] = useState<ApiError | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<"generate" | "approve" | "paid" | null>(null);

  const loadRuns = useCallback(
    () =>
      listPayrollRuns({ page_size: 100 }).then((page) => {
        setRuns(page.results);
        setRunsReady(true);
      }),
    [],
  );

  const loadItems = useCallback(
    (id: number) =>
      listPayrollItems(id, { query: { page_size: 100 } }).then((page) => {
        setItems(page.results);
        setItemsForRun(id);
      }),
    [],
  );

  useEffect(() => {
    if (checking || !canView) return;
    loadRuns().catch((value: unknown) => setError(value as ApiError));
  }, [checking, canView, loadRuns]);

  const run = useMemo(
    () => runs.find((candidate) => monthKeyOf(candidate.period_month) === month) ?? null,
    [runs, month],
  );
  const runId = run?.id ?? null;

  useEffect(() => {
    if (runId === null) return;
    loadItems(runId).catch((value: unknown) => setError(value as ApiError));
  }, [runId, loadItems]);

  const itemsLoading = runId !== null && itemsForRun !== runId;
  const shownItems = runId !== null && itemsForRun === runId ? items : [];

  /**
   * Run one lifecycle action and re-read what it changed.
   *
   * A 409 means someone else moved the run first — the screen is offering an
   * "Approve" the server has already refused — so the state is re-read even
   * though the write failed. Without that the stale buttons stay on screen and
   * the next click fails for the same reason.
   */
  async function perform(
    kind: "approve" | "paid",
    action: () => Promise<PayrollRun>,
  ): Promise<void> {
    setBusy(kind);
    setError(null);
    try {
      await action();
      await loadRuns();
      if (runId !== null) await loadItems(runId);
    } catch (value) {
      setError(value as ApiError);
      if (isInvalidStateTransition(value)) {
        await loadRuns().catch(() => undefined);
        if (runId !== null) await loadItems(runId).catch(() => undefined);
      }
    } finally {
      setBusy(null);
    }
  }

  async function generate(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy("generate");
    setError(null);
    try {
      // The server normalises any date in the month to its first day and
      // refuses a second run for the same period — which is why this is the
      // selected month rather than today.
      await generatePayrollRun({
        period: monthToPeriod(month),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      setNotes("");
      await loadRuns();
    } catch (value) {
      setError(value as ApiError);
      if (isInvalidStateTransition(value)) await loadRuns().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  }

  const header = (
    <PageHeader
      eyebrow="Payroll"
      title="Payroll runs"
      blurb="Generate a month, approve it, then record that it was paid."
    />
  );

  if (!checking && !canView) {
    return (
      <section className="space-y-6">
        {header}
        <NoAccessNote />
      </section>
    );
  }

  const paid = run && run.status === "PAID" ? Number(run.net_total) : 0;
  const pending = run ? Number(run.net_total) - paid : 0;
  const currency = run?.currency ?? "ETB";

  const audit = run
    ? [
        `Generated on ${dateStamp(run.generated_at)}`,
        run.approved_at && run.approved_by_username
          ? `Approved by ${run.approved_by_username} on ${dateStamp(run.approved_at)}`
          : null,
        run.paid_at ? `Paid on ${dateStamp(run.paid_at)}` : null,
      ]
        .filter((line): line is string => line !== null)
        .join(" · ")
    : "";

  return (
    <section className="space-y-6">
      {header}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="Previous month"
            onClick={() => setMonth((current) => shiftMonthKey(current, -1))}
            className="flex h-11 w-11 items-center justify-center rounded border border-border bg-surface text-ink hover:border-ink"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input
            type="month"
            aria-label="Month"
            value={month}
            onChange={(event) => {
              if (event.target.value) setMonth(event.target.value);
            }}
            className="control control--inline"
          />
          <button
            type="button"
            aria-label="Next month"
            onClick={() => setMonth((current) => shiftMonthKey(current, 1))}
            className="flex h-11 w-11 items-center justify-center rounded border border-border bg-surface text-ink hover:border-ink"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        {runs.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {runs.map((candidate) => {
              const key = monthKeyOf(candidate.period_month);
              const selected = key === month;
              return (
                <button
                  key={candidate.id}
                  type="button"
                  onClick={() => setMonth(key)}
                  className={`rounded border px-2 py-1 text-xs ${
                    selected
                      ? "border-ink bg-ink text-canvas"
                      : "border-border bg-surface text-ink-secondary hover:border-ink hover:text-ink"
                  }`}
                >
                  {monthLabel(candidate.period_month)}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <ErrorBanner error={error} />

      {!runsReady ? (
        error ? (
          <EmptyNote>Payroll could not be loaded. The message above says why.</EmptyNote>
        ) : (
          <div className="overflow-x-auto rounded border border-border bg-surface">
            <LoadingNote label="Loading payroll..." />
          </div>
        )
      ) : run ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: "Monthly payroll", value: money(run.net_total, currency) },
              { label: "Employees", value: itemsLoading ? "…" : String(shownItems.length) },
              { label: "Paid", value: money(paid, currency) },
              { label: "Pending", value: money(pending, currency) },
            ].map((card) => (
              <div key={card.label} className="rounded border border-border bg-surface p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                  {card.label}
                </p>
                <p className="mt-1 text-xl font-semibold tracking-tight text-ink">{card.value}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-border bg-surface p-4">
            <div className="text-sm">
              <StatusChip status={run.status} display={run.status_display} />
              <p className="mt-1 text-ink-secondary">{audit}</p>
              {run.notes && <p className="mt-1 text-ink-secondary">Notes: {run.notes}</p>}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {run.status === "GENERATED" &&
                (approve ? (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void perform("approve", () => approvePayrollRun(run.id))}
                    className="btn btn-primary"
                  >
                    {busy === "approve" ? "Approving..." : "Approve run"}
                  </button>
                ) : (
                  <span className="text-sm text-ink-secondary">
                    An owner approves this run before anything is paid.
                  </span>
                ))}

              {run.status === "APPROVED" &&
                (markPaid ? (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void perform("paid", () => markPayrollRunPaid(run.id))}
                    className="btn btn-primary"
                  >
                    {busy === "paid" ? "Recording..." : "Mark as paid"}
                  </button>
                ) : (
                  <span className="text-sm text-ink-secondary">
                    An owner records when the money is handed over.
                  </span>
                ))}

              {run.status === "PAID" && (
                <span className="text-sm text-ink-secondary">
                  Nothing left to do for this month.
                </span>
              )}
            </div>
          </div>

          <div className="overflow-x-auto rounded border border-border bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
                <tr>
                  <th className="px-3 py-3">Employee</th>
                  <th className="px-3 py-3">Position</th>
                  <th className="px-3 py-3">Basic wage</th>
                  <th className="px-3 py-3">Deductions</th>
                  <th className="px-3 py-3">Net pay</th>
                  <th className="px-3 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {shownItems.map((item) => (
                  <tr key={item.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-3 font-medium text-ink">{item.full_name}</td>
                    <td className="px-3 py-3 text-ink-secondary">{item.position}</td>
                    <td className="px-3 py-3">{money(item.gross_amount, item.currency)}</td>
                    <td className="px-3 py-3 text-ink-secondary">
                      {money(item.total_deductions, item.currency)}
                    </td>
                    <td className="px-3 py-3 font-semibold text-ink">
                      {money(item.net_amount, item.currency)}
                    </td>
                    <td className="px-3 py-3">
                      <StatusChip status={item.status} display={item.status_display} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {itemsLoading ? (
              <LoadingNote label="Loading payslips..." />
            ) : (
              shownItems.length === 0 && <EmptyNote>This run has no lines.</EmptyNote>
            )}
          </div>
        </>
      ) : (
        <form onSubmit={generate} className="space-y-4 rounded border border-border bg-surface p-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">
              Generate payroll for {monthLabel(month)}
            </h2>
            <p className="mt-1 text-sm text-ink-secondary">
              Gross pay is read from each employee&apos;s monthly wage at the moment of generation,
              so nothing about the month itself is typed in here.
            </p>
          </div>

          <label className="field-label">
            Notes (optional)
            <input
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Anything unusual about this month"
              className="control mt-1.5"
            />
          </label>

          {canGenerate ? (
            <button type="submit" disabled={busy !== null} className="btn btn-primary">
              {busy === "generate" ? "Generating..." : "Generate run"}
            </button>
          ) : (
            <p className="text-sm text-ink-secondary">
              Only an account with permission to generate payroll can create this month&apos;s run.
            </p>
          )}
        </form>
      )}
    </section>
  );
}
