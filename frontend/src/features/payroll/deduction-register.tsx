"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createPayrollDeduction,
  listPayrollDeductions,
  listPayrollItems,
  listPayrollRuns,
  type PayrollDeduction,
  type PayrollDeductionType,
  type PayrollItem,
  type PayrollRun,
} from "@/lib/api";
import { isInvalidStateTransition, type ApiError } from "@/lib/api/errors";

import { dateStamp, money, monthLabel } from "./format";
import { usePayrollPermissions } from "./permissions";
import { EmptyNote, ErrorBanner, LoadingNote, NoAccessNote, PageHeader } from "./parts";

/**
 * Every deduction taken off a payslip, and the form that records one (spec §14.2).
 *
 * **A run picker, then the people on it.** Deductions attach to a *line*, not to
 * a person, so the employee list cannot be fetched until a run is chosen — the
 * same staff member has one line per month, and deducting from last month's
 * would quietly change a payslip that has already been paid.
 *
 * **Only generated runs are offered.** `add_deduction` refuses anything past
 * `GENERATED`, because a signed payslip is not edited; the correction belongs in
 * the next run. Offering an approved run in the select would build a form whose
 * every submission is a 409.
 *
 * **The reason is a first-class column, not a tooltip.** A payslip line with no
 * explanation is what an employee queries, and a screen that cannot show the
 * reason cannot answer them — the API returns it for exactly that reason.
 *
 * The run and employee selects hold a *preference* and reduce it against the
 * runs and lines currently available, so a run that gets approved underneath the
 * form drops out of the list and the selection falls forward to the next legal
 * one. Repairing that with an effect would mean writing state that the previous
 * render already disagrees with.
 */
const DEDUCTION_TYPES: { value: PayrollDeductionType; label: string }[] = [
  { value: "ADVANCE", label: "Salary advance" },
  { value: "ABSENCE", label: "Absence" },
  { value: "LATE", label: "Tardiness" },
  { value: "OTHER", label: "Other" },
];

export default function DeductionRegister() {
  const { checking, view: canView, deduct } = usePayrollPermissions();

  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [deductions, setDeductions] = useState<PayrollDeduction[]>([]);
  const [ready, setReady] = useState(false);
  const [items, setItems] = useState<PayrollItem[]>([]);
  const [itemsForRun, setItemsForRun] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [runChoice, setRunChoice] = useState("");
  const [itemChoice, setItemChoice] = useState("");
  const [type, setType] = useState<PayrollDeductionType>("ADVANCE");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [occurredOn, setOccurredOn] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      Promise.all([
        listPayrollRuns({ page_size: 100 }),
        listPayrollDeductions({ page_size: 100 }),
      ]).then(([runPage, deductionPage]) => {
        setRuns(runPage.results);
        setDeductions(deductionPage.results);
        setReady(true);
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
    refresh().catch((value: unknown) => setError(value as ApiError));
  }, [checking, canView, refresh]);

  const generatedRuns = useMemo(
    () => runs.filter((candidate) => candidate.status === "GENERATED"),
    [runs],
  );

  const runId =
    runChoice && generatedRuns.some((candidate) => String(candidate.id) === runChoice)
      ? runChoice
      : String(generatedRuns[0]?.id ?? "");
  const selectedRunId = runId ? Number(runId) : null;

  useEffect(() => {
    if (selectedRunId === null) return;
    loadItems(selectedRunId).catch((value: unknown) => setError(value as ApiError));
  }, [selectedRunId, loadItems]);

  const itemsLoading = selectedRunId !== null && itemsForRun !== selectedRunId;
  const shownItems = selectedRunId !== null && itemsForRun === selectedRunId ? items : [];

  const itemId =
    itemChoice && shownItems.some((line) => String(line.id) === itemChoice)
      ? itemChoice
      : String(shownItems[0]?.id ?? "");

  const selectedLine = shownItems.find((line) => String(line.id) === itemId) ?? null;

  const runMonths = useMemo(() => {
    const months = new Map<number, string>();
    for (const run of runs) months.set(run.id, monthLabel(run.period_month));
    return months;
  }, [runs]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const created = await createPayrollDeduction({
        payroll_item: Number(itemId),
        deduction_type: type,
        amount,
        ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(occurredOn ? { occurred_on: occurredOn } : {}),
      });
      setAmount("");
      setReason("");
      setOccurredOn("");
      setSaved(
        `${money(created.amount, created.currency)} deducted from ${created.employee_name}.`,
      );
      await refresh();
      // The line's totals moved with it, so the run's columns would otherwise
      // keep showing the figures this write just changed.
      if (selectedRunId !== null) await loadItems(selectedRunId);
    } catch (value) {
      setError(value as ApiError);
      if (isInvalidStateTransition(value)) {
        await refresh().catch(() => undefined);
        if (selectedRunId !== null) await loadItems(selectedRunId).catch(() => undefined);
      }
    } finally {
      setSaving(false);
    }
  }

  const header = (
    <PageHeader
      eyebrow="Payroll"
      title="Deductions"
      blurb="What was taken off a payslip, and why — recorded against the run it belongs to."
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

  return (
    <section className="space-y-6">
      {header}
      <ErrorBanner error={error} />
      {saved && (
        <p className="rounded border border-success/30 bg-success/10 p-3 text-sm text-success">
          {saved}
        </p>
      )}

      {deduct && ready && (
        <>
          {generatedRuns.length === 0 ? (
            <div className="rounded border border-border bg-surface p-4 text-sm text-ink-secondary">
              No run is waiting for deductions. A deduction is recorded while a month&apos;s run is
              still generated; once it is approved the payslip is fixed and the correction belongs
              in the next run.
            </div>
          ) : (
            <form
              onSubmit={submit}
              className="grid gap-3 rounded border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-3"
            >
              <label className="text-sm text-ink">
                Run being adjusted
                <select
                  required
                  value={runId}
                  onChange={(event) => setRunChoice(event.target.value)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                >
                  <option value="" disabled>
                    Select run
                  </option>
                  {generatedRuns.map((run) => (
                    <option key={run.id} value={run.id}>
                      {monthLabel(run.period_month)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="text-sm text-ink">
                Employee
                <select
                  required
                  disabled={itemsLoading || shownItems.length === 0}
                  value={itemId}
                  onChange={(event) => setItemChoice(event.target.value)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <option value="" disabled>
                    {itemsLoading ? "Loading employees..." : "Select employee"}
                  </option>
                  {shownItems.map((line) => (
                    <option key={line.id} value={line.id}>
                      {line.full_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="text-sm text-ink">
                Type
                <select
                  required
                  value={type}
                  onChange={(event) => setType(event.target.value as PayrollDeductionType)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                >
                  {DEDUCTION_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="text-sm text-ink">
                Amount (ETB)
                <input
                  required
                  min="0.01"
                  step="0.01"
                  type="number"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                />
              </label>

              <label className="text-sm text-ink">
                Reason
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Why this was taken"
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                />
              </label>

              <label className="text-sm text-ink">
                Date (optional)
                <input
                  type="date"
                  value={occurredOn}
                  onChange={(event) => setOccurredOn(event.target.value)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                />
              </label>

              <p className="text-xs text-ink-secondary sm:col-span-2 lg:col-span-3">
                {selectedLine
                  ? `${selectedLine.full_name} is on ${money(selectedLine.gross_amount, selectedLine.currency)} gross with ${money(selectedLine.total_deductions, selectedLine.currency)} deducted so far — deductions cannot pass the gross.`
                  : "The date defaults to the run's period, and deductions cannot exceed the line's gross pay."}
              </p>

              <button
                type="submit"
                disabled={saving || !itemId}
                className="rounded bg-ink px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2 lg:col-span-3 lg:justify-self-end"
              >
                {saving ? "Recording..." : "Record deduction"}
              </button>
            </form>
          )}
        </>
      )}

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">Date</th>
              <th className="px-3 py-3">Employee</th>
              <th className="px-3 py-3">Type</th>
              <th className="px-3 py-3">Amount</th>
              <th className="px-3 py-3">Reason</th>
              <th className="px-3 py-3">Run</th>
            </tr>
          </thead>
          <tbody>
            {deductions.map((deduction) => (
              <tr key={deduction.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3 text-ink-secondary">
                  {dateStamp(deduction.occurred_on) || deduction.occurred_on}
                </td>
                <td className="px-3 py-3 font-medium text-ink">{deduction.employee_name}</td>
                <td className="px-3 py-3 text-ink-secondary">{deduction.deduction_type_display}</td>
                <td className="px-3 py-3 font-semibold text-ink">
                  {money(deduction.amount, deduction.currency)}
                </td>
                <td className="px-3 py-3 text-ink-secondary">{deduction.reason || "—"}</td>
                <td className="px-3 py-3 text-ink-secondary">
                  {runMonths.get(deduction.run) ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!ready ? (
          error ? (
            <EmptyNote>Deductions could not be loaded. See the message above.</EmptyNote>
          ) : (
            <LoadingNote label="Loading deductions..." />
          )
        ) : (
          deductions.length === 0 && <EmptyNote>No deductions have been recorded yet.</EmptyNote>
        )}
      </div>
    </section>
  );
}
