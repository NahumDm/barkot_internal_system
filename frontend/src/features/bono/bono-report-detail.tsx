"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  approveBonoReport,
  correctBonoReport,
  getBonoReport,
  refreshBonoReport,
  rejectBonoReport,
  submitBonoReport,
  updateBonoReport,
  type BonoReportDetail,
} from "@/lib/api/bono";
import type { ApiError } from "@/lib/api/errors";
import { useBonoPermissions } from "./permissions";
import {
  BonoPageHeader,
  BonoStatusBadge,
  LoadingNote,
  formatDay,
  formatMoney,
  formatQuantity,
  formatTimestamp,
} from "./parts";

interface BonoCount {
  used: string;
  returned: string;
  explanation: string;
}

interface ProductCount {
  physical: string;
  explanation: string;
}

function messageOf(value: unknown): string {
  return (value as ApiError).message || "That action could not be completed.";
}

function isEditable(report: BonoReportDetail, canSubmit: boolean): boolean {
  return canSubmit && (report.status === "DRAFT" || report.status === "REJECTED");
}

export default function BonoReportDetailPage({ reportId }: Readonly<{ reportId: number }>) {
  const permissions = useBonoPermissions();
  const router = useRouter();
  const [report, setReport] = useState<BonoReportDetail | null>(null);
  const [notes, setNotes] = useState("");
  const [bonoCounts, setBonoCounts] = useState<Record<number, BonoCount>>({});
  const [productCounts, setProductCounts] = useState<Record<number, ProductCount>>({});
  const [rejectReason, setRejectReason] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [success, setSuccess] = useState("");

  function hydrate(value: BonoReportDetail) {
    setReport(value);
    setNotes(value.notes);
    setBonoCounts(
      Object.fromEntries(
        value.bono_lines.map((line) => [
          line.id,
          {
            used: String(line.used_quantity),
            returned: String(line.returned_quantity),
            explanation: line.explanation,
          },
        ]),
      ),
    );
    setProductCounts(
      Object.fromEntries(
        value.product_lines.map((line) => [
          line.id,
          {
            physical: line.physical_closing_quantity ?? "",
            explanation: line.explanation,
          },
        ]),
      ),
    );
  }

  useEffect(() => {
    let active = true;
    getBonoReport(reportId)
      .then((value) => {
        if (!active) return;
        hydrate(value);
        setError(null);
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
  }, [reportId]);

  const editable = report ? isEditable(report, permissions.submit) : false;

  function collectUpdate() {
    if (!report) throw new Error("Report has not loaded.");
    const bonoLines = report.bono_lines.map((line) => {
      const entry = bonoCounts[line.id] ?? {
        used: String(line.used_quantity),
        returned: String(line.returned_quantity),
        explanation: line.explanation,
      };
      const used = Number(entry.used || 0);
      const returned = Number(entry.returned || 0);
      if (!Number.isInteger(used) || used < 0 || !Number.isInteger(returned) || returned < 0) {
        throw new Error("Used and returned Bonos must be whole, non-negative numbers.");
      }
      return {
        id: line.id,
        used_quantity: used,
        returned_quantity: returned,
        explanation: entry.explanation.trim(),
      };
    });
    const productLines = report.product_lines.map((line) => {
      const entry = productCounts[line.id] ?? {
        physical: line.physical_closing_quantity ?? "",
        explanation: line.explanation,
      };
      if (entry.physical !== "" && Number.isNaN(Number(entry.physical))) {
        throw new Error("Physical closing quantities must be numbers.");
      }
      return {
        id: line.id,
        physical_closing_quantity: entry.physical === "" ? null : entry.physical,
        explanation: entry.explanation.trim(),
      };
    });
    return { notes: notes.trim(), bono_lines: bonoLines, product_lines: productLines };
  }

  async function saveDraft(): Promise<BonoReportDetail | null> {
    if (!report) return null;
    setActionError(null);
    setSuccess("");
    try {
      const input = collectUpdate();
      setBusy("save");
      const updated = await updateBonoReport(report.id, input);
      hydrate(updated);
      setSuccess("Draft saved.");
      return updated;
    } catch (value) {
      setActionError(messageOf(value));
      return null;
    } finally {
      setBusy("");
    }
  }

  async function runAction(
    label: string,
    action: () => Promise<BonoReportDetail>,
    successMessage: string,
  ) {
    setBusy(label);
    setActionError(null);
    setSuccess("");
    try {
      const updated = await action();
      hydrate(updated);
      setSuccess(successMessage);
    } catch (value) {
      setActionError(messageOf(value));
    } finally {
      setBusy("");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await saveDraft();
    if (!saved) return;
    await runAction(
      "submit",
      () => submitBonoReport(saved.id),
      "Report submitted for Owner review.",
    );
  }

  async function handleReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!report) return;
    if (!rejectReason.trim()) {
      setActionError("A rejection reason is required.");
      return;
    }
    await runAction(
      "reject",
      () => rejectBonoReport(report.id, { reason: rejectReason.trim() }),
      "Report rejected and returned to the Cashier.",
    );
    setRejectReason("");
  }

  async function handleCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!report) return;
    if (!correctionReason.trim()) {
      setActionError("A correction reason is required.");
      return;
    }
    setBusy("correct");
    setActionError(null);
    try {
      const revision = await correctBonoReport(report.id, { reason: correctionReason.trim() });
      router.push(`/bono/reports/${revision.id}`);
    } catch (value) {
      setActionError(messageOf(value));
    } finally {
      setBusy("");
    }
  }

  if (loading && !report) {
    return <LoadingNote label="Loading the daily report..." />;
  }

  if (error || !report) {
    return (
      <section className="space-y-4">
        <p role="alert" className="form-error">
          {error?.message ?? "That report could not be found."}
        </p>
        <Link href="/bono/reports" className="btn btn-secondary">
          Back to daily reports
        </Link>
      </section>
    );
  }

  const totalIssued = report.bono_lines.reduce((sum, line) => sum + line.total_issued_quantity, 0);
  const totalUsed = report.bono_lines.reduce((sum, line) => sum + line.used_quantity, 0);
  const totalLost = report.bono_lines.reduce((sum, line) => sum + line.lost_quantity, 0);
  const totalDiscrepancy = report.bono_lines.reduce(
    (sum, line) => sum + line.discrepancy_quantity,
    0,
  );
  const currency = report.currency ?? "ETB";
  const hasMoney = report.sales_total !== undefined;

  return (
    <section className="space-y-6">
      <BonoPageHeader
        eyebrow={`Bono report${report.revision > 1 ? ` · revision ${report.revision}` : ""}`}
        title={formatDay(report.operational_date)}
        description={
          report.corrects
            ? `This revision corrects report #${report.corrects}. The earlier revision stays unchanged in history.`
            : "Product stock lines remain independent; a shared Bono total never decides an individual product's sales."
        }
        actions={
          <>
            <BonoStatusBadge status={report.status} label={report.status_display} />
            <Link href="/bono/reports" className="btn btn-secondary">
              All reports
            </Link>
          </>
        }
      />

      {actionError ? (
        <p role="alert" className="form-error">
          {actionError}
        </p>
      ) : null}
      {success ? (
        <p
          role="status"
          className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950"
        >
          {success}
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Issued
          </p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalIssued}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Used</p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalUsed}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Lost</p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalLost}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Unexplained
          </p>
          <p
            className={`mt-1 text-2xl font-semibold ${
              totalDiscrepancy === 0 ? "text-ink" : "text-brand"
            }`}
          >
            {totalDiscrepancy}
          </p>
        </div>
      </div>

      <div className="grid gap-4 rounded border border-border bg-surface p-5 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Prepared by
          </p>
          <p className="mt-1 text-sm text-ink">{report.submitted_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.submitted_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Approved by
          </p>
          <p className="mt-1 text-sm text-ink">{report.approved_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.approved_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Rejected by
          </p>
          <p className="mt-1 text-sm text-ink">{report.rejected_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.rejected_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Activity read at
          </p>
          <p className="mt-1 text-sm text-ink">{formatTimestamp(report.activity_generated_at)}</p>
        </div>
        {report.rejection_reason ? (
          <div className="md:col-span-2 xl:col-span-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-950">
            <span className="font-semibold">Rejection reason:</span> {report.rejection_reason}
          </div>
        ) : null}
        {report.correction_reason ? (
          <div className="md:col-span-2 xl:col-span-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
            <span className="font-semibold">Correction reason:</span> {report.correction_reason}
          </div>
        ) : null}
      </div>

      {hasMoney ? (
        <div className="grid gap-4 rounded border border-border bg-surface p-5 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Sales
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.sales_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Cash paid
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.cash_paid_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Mobile paid
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.mobile_paid_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Payments total
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.payments_total, currency)}
            </p>
          </div>
          <p className="text-xs text-ink-secondary sm:col-span-2 xl:col-span-4">
            These are the existing sales and payment totals for the day. They are not inferred from
            Bono usage.
          </p>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <div className="border-b border-border p-4">
          <h2 className="text-lg font-semibold text-ink">Bono accountability</h2>
          <p className="mt-1 text-sm text-ink-secondary">
            Issued = initial plus additional. Unexplained = issued - used - returned - lost. A
            transfer moves custody but does not create a new Bono.
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">Bono type</th>
              <th className="px-3 py-3 text-right">Issued</th>
              <th className="px-3 py-3 text-right">Transferred in</th>
              <th className="px-3 py-3 text-right">Transferred out</th>
              <th className="px-3 py-3 text-right">Lost</th>
              <th className="px-3 py-3 text-right">Used</th>
              <th className="px-3 py-3 text-right">Returned</th>
              <th className="px-3 py-3 text-right">Unexplained</th>
              <th className="px-3 py-3">Explanation</th>
            </tr>
          </thead>
          <tbody>
            {report.bono_lines.map((line) => {
              const entry = bonoCounts[line.id] ?? {
                used: String(line.used_quantity),
                returned: String(line.returned_quantity),
                explanation: line.explanation,
              };
              const used = Number(entry.used || 0);
              const returned = Number(entry.returned || 0);
              const discrepancy = line.total_issued_quantity - used - returned - line.lost_quantity;
              return (
                <tr key={line.id} className="border-b border-border align-top last:border-0">
                  <td className="px-3 py-3 font-medium text-ink">
                    <span className="inline-flex items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="inline-block h-3 w-3 rounded-full border border-black/10"
                        style={{ backgroundColor: line.bono_color_snapshot }}
                      />
                      {line.bono_name_snapshot}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right" title="Initial plus additional issues">
                    {line.total_issued_quantity}
                    <span className="block text-xs text-ink-secondary">
                      {line.initial_issued_quantity} + {line.additional_issued_quantity}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right">{line.transfers_in_quantity}</td>
                  <td className="px-3 py-3 text-right">{line.transfers_out_quantity}</td>
                  <td className="px-3 py-3 text-right">{line.lost_quantity}</td>
                  <td className="px-3 py-3 text-right">
                    {editable ? (
                      <input
                        type="number"
                        min="0"
                        step="1"
                        aria-label={`Used ${line.bono_name_snapshot}`}
                        className="control h-9 w-24 text-right"
                        value={entry.used}
                        onChange={(event) =>
                          setBonoCounts((current) => ({
                            ...current,
                            [line.id]: { ...entry, used: event.target.value },
                          }))
                        }
                      />
                    ) : (
                      line.used_quantity
                    )}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {editable ? (
                      <input
                        type="number"
                        min="0"
                        step="1"
                        aria-label={`Returned ${line.bono_name_snapshot}`}
                        className="control h-9 w-24 text-right"
                        value={entry.returned}
                        onChange={(event) =>
                          setBonoCounts((current) => ({
                            ...current,
                            [line.id]: { ...entry, returned: event.target.value },
                          }))
                        }
                      />
                    ) : (
                      line.returned_quantity
                    )}
                  </td>
                  <td
                    className={`px-3 py-3 text-right font-semibold ${
                      discrepancy === 0 ? "text-ink" : "text-brand"
                    }`}
                  >
                    {discrepancy}
                  </td>
                  <td className="px-3 py-3">
                    {editable ? (
                      <input
                        type="text"
                        aria-label={`Explanation ${line.bono_name_snapshot}`}
                        className="control h-9 min-w-52"
                        value={entry.explanation}
                        onChange={(event) =>
                          setBonoCounts((current) => ({
                            ...current,
                            [line.id]: { ...entry, explanation: event.target.value },
                          }))
                        }
                      />
                    ) : (
                      line.explanation || "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {report.bono_lines.length === 0 ? (
          <p className="p-6 text-center text-sm text-ink-secondary">
            No Bono activity was recorded for this date.
          </p>
        ) : null}
      </div>

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <div className="border-b border-border p-4">
          <h2 className="text-lg font-semibold text-ink">Product stock reconciliation</h2>
          <p className="mt-1 text-sm text-ink-secondary">
            Each product is counted on its own. Opening, receipts, sales and breakage come from the
            existing stock ledger.
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">Product</th>
              <th className="px-3 py-3 text-right">Opening</th>
              <th className="px-3 py-3 text-right">Received</th>
              <th className="px-3 py-3 text-right">Sold</th>
              <th className="px-3 py-3 text-right">Breakage</th>
              <th className="px-3 py-3 text-right">Expected</th>
              <th className="px-3 py-3 text-right">Physical</th>
              <th className="px-3 py-3 text-right">Variance</th>
              <th className="px-3 py-3">Explanation</th>
            </tr>
          </thead>
          <tbody>
            {report.product_lines.map((line) => {
              const entry = productCounts[line.id] ?? {
                physical: line.physical_closing_quantity ?? "",
                explanation: line.explanation,
              };
              const variance =
                entry.physical === ""
                  ? null
                  : Number(entry.physical) - Number(line.expected_closing_quantity);
              return (
                <tr key={line.id} className="border-b border-border align-top last:border-0">
                  <td className="px-3 py-3">
                    <p className="font-medium text-ink">{line.product_name_snapshot}</p>
                    <p className="font-mono text-xs text-ink-secondary">
                      {line.product_sku_snapshot}
                    </p>
                    {line.bono_name_snapshot ? (
                      <p className="mt-1 inline-flex items-center gap-1 text-xs text-ink-secondary">
                        <span
                          aria-hidden="true"
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: line.bono_color_snapshot }}
                        />
                        {line.bono_name_snapshot}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-right">{formatQuantity(line.opening_quantity)}</td>
                  <td className="px-3 py-3 text-right">{formatQuantity(line.received_quantity)}</td>
                  <td className="px-3 py-3 text-right">{formatQuantity(line.sold_quantity)}</td>
                  <td className="px-3 py-3 text-right">{formatQuantity(line.breakage_quantity)}</td>
                  <td className="px-3 py-3 text-right font-medium text-ink">
                    {formatQuantity(line.expected_closing_quantity)}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {editable ? (
                      <input
                        type="number"
                        min="0"
                        step="0.001"
                        aria-label={`Physical closing ${line.product_name_snapshot}`}
                        className="control h-9 w-28 text-right"
                        value={entry.physical}
                        onChange={(event) =>
                          setProductCounts((current) => ({
                            ...current,
                            [line.id]: { ...entry, physical: event.target.value },
                          }))
                        }
                      />
                    ) : (
                      formatQuantity(line.physical_closing_quantity)
                    )}
                  </td>
                  <td
                    className={`px-3 py-3 text-right font-semibold ${
                      variance === null || variance === 0 ? "text-ink" : "text-brand"
                    }`}
                  >
                    {variance === null ? "—" : formatQuantity(variance)}
                  </td>
                  <td className="px-3 py-3">
                    {editable ? (
                      <input
                        type="text"
                        aria-label={`Product explanation ${line.product_name_snapshot}`}
                        className="control h-9 min-w-52"
                        value={entry.explanation}
                        onChange={(event) =>
                          setProductCounts((current) => ({
                            ...current,
                            [line.id]: { ...entry, explanation: event.target.value },
                          }))
                        }
                      />
                    ) : (
                      line.explanation || "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {report.product_lines.length === 0 ? (
          <p className="p-6 text-center text-sm text-ink-secondary">
            No product was paired to a Bono type during this day.
          </p>
        ) : null}
      </div>

      <div className="rounded border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold text-ink">Notes</h2>
        {editable ? (
          <textarea
            className="control mt-3"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            aria-label="Report notes"
          />
        ) : (
          <p className="mt-2 whitespace-pre-wrap text-sm text-ink-secondary">
            {report.notes || "No notes."}
          </p>
        )}
      </div>

      {editable ? (
        <div className="flex flex-wrap items-center gap-2 rounded border border-border bg-surface p-5">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void saveDraft()}
            disabled={busy !== ""}
          >
            {busy === "save" ? "Saving..." : "Save draft"}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() =>
              void runAction(
                "refresh",
                () => refreshBonoReport(report.id),
                "Activity refreshed from the Bono and stock ledgers.",
              )
            }
            disabled={busy !== ""}
          >
            {busy === "refresh" ? "Refreshing..." : "Refresh activity"}
          </button>
          <form onSubmit={handleSubmit} className="inline">
            <button type="submit" className="btn btn-primary" disabled={busy !== ""}>
              {busy === "submit" ? "Submitting..." : "Submit for Owner review"}
            </button>
          </form>
          <p className="text-xs text-ink-secondary">
            Submitting locks Bono custody for this date. Every product line needs a physical count.
          </p>
        </div>
      ) : null}

      {report.status === "SUBMITTED" && permissions.approve ? (
        <div className="grid gap-4 rounded border border-border bg-surface p-5 xl:grid-cols-2">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void runAction("approve", () => approveBonoReport(report.id), "Report approved.");
            }}
          >
            <h2 className="text-lg font-semibold text-ink">Approve</h2>
            <p className="mt-1 text-sm text-ink-secondary">
              Approval freezes this revision. If it turns out to be wrong, start an explicit
              correction instead of editing it.
            </p>
            <button type="submit" className="btn btn-primary mt-3" disabled={busy !== ""}>
              {busy === "approve" ? "Approving..." : "Approve report"}
            </button>
          </form>
          <form onSubmit={handleReject}>
            <h2 className="text-lg font-semibold text-ink">Reject</h2>
            <p className="mt-1 text-sm text-ink-secondary">
              A rejection reopens the day for the Cashier. The reason is shown to them.
            </p>
            <input
              type="text"
              className="control mt-3"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="What must be corrected?"
              aria-label="Rejection reason"
            />
            <button type="submit" className="btn btn-secondary mt-3" disabled={busy !== ""}>
              {busy === "reject" ? "Rejecting..." : "Reject report"}
            </button>
          </form>
        </div>
      ) : null}

      {report.status === "APPROVED" && permissions.approve ? (
        <form onSubmit={handleCorrection} className="rounded border border-border bg-surface p-5">
          <h2 className="text-lg font-semibold text-ink">Start a correction</h2>
          <p className="mt-1 text-sm text-ink-secondary">
            The approved report stays immutable. A new draft revision is opened, linked back to this
            one, and must go through submission and approval again.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="min-w-64 flex-1 text-sm font-medium text-ink">
              Correction reason
              <input
                type="text"
                className="control mt-1.5"
                value={correctionReason}
                onChange={(event) => setCorrectionReason(event.target.value)}
                placeholder="Why this approved report must be revised"
              />
            </label>
            <button type="submit" className="btn btn-secondary" disabled={busy !== ""}>
              {busy === "correct" ? "Opening..." : "Open correction"}
            </button>
          </div>
        </form>
      ) : null}

      {report.status === "SUBMITTED" && !permissions.approve ? (
        <p className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          This report is waiting for the Owner. The day stays locked until it is approved or
          rejected.
        </p>
      ) : null}
      {report.status === "APPROVED" && !permissions.approve ? (
        <p className="rounded border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
          This report is approved and immutable. Ask the Owner to start a correction if something is
          wrong.
        </p>
      ) : null}
    </section>
  );
}
