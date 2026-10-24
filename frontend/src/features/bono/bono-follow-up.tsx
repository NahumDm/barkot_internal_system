"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  deductBonoIncident,
  resolveBonoIncident,
  type BonoIncident,
  type BonoIncidentResolution,
} from "@/lib/api/bono";
import type { ApiError } from "@/lib/api/errors";
import {
  listPayrollEmployees,
  listPayrollItems,
  listPayrollRuns,
  type PayrollEmployee,
  type PayrollItem,
  type PayrollRun,
} from "@/lib/api/payroll";
import { BonoColorDot, formatMoney } from "./parts";

function messageOf(value: unknown): string {
  return (value as ApiError).message || "That follow-up could not be recorded.";
}

/**
 * The explicit outcome of a lost Bono.
 *
 * A lost token is never converted into a sale or breakage automatically. A
 * Manager may close it as reviewed with no financial consequence, or record a
 * deduction through the existing payroll line - which requires a reason and
 * remains subject to payroll's own state checks.
 */
function DeductionForm({
  incident,
  onDone,
  onCancel,
}: Readonly<{
  incident: BonoIncident;
  onDone: (message: string) => void;
  onCancel: () => void;
}>) {
  const [employees, setEmployees] = useState<PayrollEmployee[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [items, setItems] = useState<PayrollItem[]>([]);
  const [runId, setRunId] = useState("");
  const [itemId, setItemId] = useState("");
  const [amount, setAmount] = useState(
    (Number(incident.quantity) * Number(incident.bono_price_snapshot || 0)).toFixed(2),
  );
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([listPayrollEmployees(), listPayrollRuns({ status: "GENERATED", page_size: 100 })])
      .then(([employeePage, runPage]) => {
        if (!active) return;
        setEmployees(employeePage.results);
        setRuns(runPage.results);
        setError("");
      })
      .catch((value: unknown) => {
        if (active) setError(messageOf(value));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    listPayrollItems(Number(runId), { query: { page_size: 200 } })
      .then((page) => {
        if (!active) return;
        setItems(page.results);
        setItemId("");
        setError("");
      })
      .catch((value: unknown) => {
        if (active) setError(messageOf(value));
      })
      .finally(() => {
        if (active) setLoadingItems(false);
      });
    return () => {
      active = false;
    };
  }, [runId]);

  const payrollEmployee = employees.find(
    (employee) => employee.profile === incident.responsible_employee,
  );
  const eligibleItems = payrollEmployee
    ? items.filter((item) => item.employee === payrollEmployee.id)
    : [];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!itemId) {
      setError("Choose the payroll line to deduct from.");
      return;
    }
    if (!reason.trim()) {
      setError("A reason is required for a payroll deduction.");
      return;
    }
    if (!Number.isFinite(Number(amount)) || Number(amount) <= 0) {
      setError("Enter a deduction amount greater than zero.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await deductBonoIncident(incident.id, {
        payroll_item: Number(itemId),
        amount: Number(amount).toFixed(2),
        reason: reason.trim(),
      });
      onDone("Deduction recorded on the payroll line. The incident is marked deducted.");
    } catch (value) {
      setError(messageOf(value));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="mt-3 text-sm text-ink-secondary">Loading payroll...</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 rounded border border-border bg-canvas/40 p-3">
      <p className="text-sm font-semibold text-ink">Deduct through payroll</p>
      {!payrollEmployee ? (
        <p className="mt-2 text-sm text-ink-secondary">
          {incident.responsible_employee_name || "This staff member"} is not on payroll. Add them to
          payroll before recording a deduction.
        </p>
      ) : runs.length === 0 ? (
        <p className="mt-2 text-sm text-ink-secondary">
          No generated payroll run is open. Generate and leave a run unapproved before deducting.
        </p>
      ) : (
        <>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium text-ink">
              Payroll run
              <select
                className="control mt-1.5"
                value={runId}
                onChange={(event) => {
                  setRunId(event.target.value);
                  setItems([]);
                  setItemId("");
                  setLoadingItems(event.target.value !== "");
                }}
              >
                <option value="">Choose a generated run</option>
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.period_month.slice(0, 7)} · {run.status_display}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium text-ink">
              Payslip line
              <select
                className="control mt-1.5"
                value={itemId}
                onChange={(event) => setItemId(event.target.value)}
                disabled={!runId || loadingItems || eligibleItems.length === 0}
              >
                <option value="">
                  {!runId
                    ? "Choose a run first"
                    : loadingItems
                      ? "Loading lines..."
                      : eligibleItems.length === 0
                        ? "No line for this employee"
                        : "Choose a payslip line"}
                </option>
                {eligibleItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.full_name} · gross {formatMoney(item.gross_amount, item.currency)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium text-ink">
              Amount
              <input
                type="number"
                min="0.01"
                step="0.01"
                className="control mt-1.5"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </label>
            <label className="text-sm font-medium text-ink">
              Reason
              <input
                type="text"
                className="control mt-1.5"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Required on the payroll deduction"
              />
            </label>
          </div>
          <p className="mt-2 text-xs text-ink-secondary">
            The amount defaults to the Bono price times the lost quantity; change it if the Owner
            agreed a different recovery.
          </p>
        </>
      )}
      {error ? (
        <p role="alert" className="form-error mt-2">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={saving || !payrollEmployee || runs.length === 0}
        >
          {saving ? "Recording..." : "Record deduction"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ReviewForm({
  incident,
  onDone,
  onCancel,
}: Readonly<{
  incident: BonoIncident;
  onDone: (message: string) => void;
  onCancel: () => void;
}>) {
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!notes.trim()) {
      setError("Describe how the loss was resolved or why no deduction is being made.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await resolveBonoIncident(incident.id, {
        resolution_status: "RESOLVED" as Exclude<BonoIncidentResolution, "PENDING">,
        resolution_notes: notes.trim(),
      });
      onDone("Lost Bono marked reviewed with no payroll deduction.");
    } catch (value) {
      setError(messageOf(value));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 rounded border border-border bg-canvas/40 p-3">
      <p className="text-sm font-semibold text-ink">Close without a deduction</p>
      <p className="mt-1 text-xs text-ink-secondary">
        The Bono stays recorded as lost. It does not become a sale, breakage or payroll deduction
        unless you explicitly record one.
      </p>
      <label className="mt-2 block text-sm font-medium text-ink">
        Resolution note
        <input
          type="text"
          className="control mt-1.5"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="What the Owner decided"
        />
      </label>
      {error ? (
        <p role="alert" className="form-error mt-2">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn btn-secondary" disabled={saving}>
          {saving ? "Saving..." : "Mark reviewed"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function BonoLostFollowUp({
  incidents,
  locked,
  canDeduct,
  onChanged,
}: Readonly<{
  incidents: BonoIncident[];
  locked: boolean;
  canDeduct: boolean;
  onChanged: () => void;
}>) {
  const [windowId, setWindowId] = useState<number | null>(null);
  const [mode, setMode] = useState<"review" | "deduct">("review");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const lost = incidents.filter((incident) => incident.kind === "LOST_BONO");
  if (lost.length === 0) return null;

  function open(incident: BonoIncident, nextMode: "review" | "deduct") {
    setWindowId(incident.id);
    setMode(nextMode);
    setMessage("");
    setError("");
  }

  function done(text: string) {
    setWindowId(null);
    setMessage(text);
    onChanged();
  }

  return (
    <section className="rounded border border-border bg-surface">
      <div className="border-b border-border p-4">
        <h2 className="text-lg font-semibold text-ink">Lost Bono follow-up</h2>
        <p className="mt-1 text-sm text-ink-secondary">
          Recording a lost Bono never creates a sale, breakage or deduction by itself. The Owner and
          Manager decide each outcome explicitly.
        </p>
      </div>
      {message ? (
        <p
          role="status"
          className="m-4 rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950"
        >
          {message}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="form-error m-4">
          {error}
        </p>
      ) : null}
      <ul className="divide-y divide-border">
        {lost.map((incident) => (
          <li key={incident.id} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <BonoColorDot
                  color={incident.bono_color_snapshot || "#6b5a5e"}
                  label={incident.bono_name_snapshot || "Lost Bono"}
                />
                <p className="mt-1 text-sm text-ink">
                  {incident.quantity} lost ·{" "}
                  {incident.responsible_employee_name || "No staff member"} ·{" "}
                  {formatMoney(incident.bono_price_snapshot, "ETB")} each
                </p>
                <p className="text-xs text-ink-secondary">
                  {incident.reason}
                  {incident.resolution_notes ? ` · ${incident.resolution_notes}` : ""}
                </p>
                {incident.payroll_deduction_amount ? (
                  <p className="mt-1 text-xs font-medium text-ink">
                    Payroll deduction: {formatMoney(incident.payroll_deduction_amount, "ETB")}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex rounded bg-canvas px-2 py-0.5 text-xs font-semibold text-ink-secondary">
                  {incident.resolution_status}
                </span>
                {!locked &&
                incident.resolution_status === "PENDING" &&
                incident.payroll_deduction === null ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => open(incident, "review")}
                    >
                      Review
                    </button>
                    {canDeduct ? (
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => open(incident, "deduct")}
                      >
                        Deduct via payroll
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>
            {windowId === incident.id ? (
              mode === "deduct" ? (
                <DeductionForm
                  incident={incident}
                  onDone={done}
                  onCancel={() => setWindowId(null)}
                />
              ) : (
                <ReviewForm incident={incident} onDone={done} onCancel={() => setWindowId(null)} />
              )
            ) : null}
          </li>
        ))}
      </ul>
      {locked ? (
        <p className="border-t border-border p-4 text-sm text-ink-secondary">
          Follow-up is closed while this day&apos;s report is submitted.
        </p>
      ) : null}
    </section>
  );
}
