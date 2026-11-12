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
import { useT } from "@/lib/i18n/context";

interface BonoCount {
  used: string;
  returned: string;
  explanation: string;
}

interface ProductCount {
  physical: string;
  explanation: string;
}

function messageOf(value: unknown, fallback: string): string {
  return (value as ApiError).message || fallback;
}

function isEditable(report: BonoReportDetail, canSubmit: boolean): boolean {
  return canSubmit && (report.status === "DRAFT" || report.status === "REJECTED");
}

export default function BonoReportDetailPage({ reportId }: Readonly<{ reportId: number }>) {
  const t = useT();
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
    if (!report) throw new Error(t("bono.rd.notLoaded"));
    const bonoLines = report.bono_lines.map((line) => {
      const entry = bonoCounts[line.id] ?? {
        used: String(line.used_quantity),
        returned: String(line.returned_quantity),
        explanation: line.explanation,
      };
      const used = Number(entry.used || 0);
      const returned = Number(entry.returned || 0);
      if (!Number.isInteger(used) || used < 0 || !Number.isInteger(returned) || returned < 0) {
        throw new Error(t("bono.rd.usedInvalid"));
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
        throw new Error(t("bono.rd.physicalNotNumber"));
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
      setSuccess(t("bono.rd.draftSaved"));
      return updated;
    } catch (value) {
      setActionError(messageOf(value, t("bono.rd.actionFailed")));
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
      setActionError(messageOf(value, t("bono.rd.actionFailed")));
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
      t("bono.rd.submittedForReview"),
    );
  }

  async function handleReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!report) return;
    if (!rejectReason.trim()) {
      setActionError(t("bono.rd.rejectionReasonRequired"));
      return;
    }
    await runAction(
      "reject",
      () => rejectBonoReport(report.id, { reason: rejectReason.trim() }),
      t("bono.rd.rejectedReturned"),
    );
    setRejectReason("");
  }

  async function handleCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!report) return;
    if (!correctionReason.trim()) {
      setActionError(t("bono.rd.correctionReasonRequired"));
      return;
    }
    setBusy("correct");
    setActionError(null);
    try {
      const revision = await correctBonoReport(report.id, { reason: correctionReason.trim() });
      router.push(`/bono/reports/${revision.id}`);
    } catch (value) {
      setActionError(messageOf(value, t("bono.rd.actionFailed")));
    } finally {
      setBusy("");
    }
  }

  if (loading && !report) {
    return <LoadingNote label={t("bono.rd.loadingReport")} />;
  }

  if (error || !report) {
    return (
      <section className="space-y-4">
        <p role="alert" className="form-error">
          {error?.message ?? t("bono.rd.notFound")}
        </p>
        <Link href="/bono/reports" className="btn btn-secondary">
          {t("bono.rd.backToReports")}
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
        eyebrow={
          report.revision > 1
            ? t("bono.rd.eyebrowRevision").replace("{n}", String(report.revision))
            : t("bono.rd.eyebrow")
        }
        title={formatDay(report.operational_date)}
        description={
          report.corrects
            ? t("bono.rd.correctsDescription").replace("{n}", String(report.corrects))
            : t("bono.rd.description")
        }
        actions={
          <>
            <BonoStatusBadge status={report.status} label={t(`bono.status.${report.status}`)} />
            <Link href="/bono/reports" className="btn btn-secondary">
              {t("bono.rd.allReports")}
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
            {t("bono.colIssued")}
          </p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalIssued}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">{t("bono.rd.used")}</p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalUsed}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">{t("bono.colLost")}</p>
          <p className="mt-1 text-2xl font-semibold text-ink">{totalLost}</p>
        </div>
        <div className="rounded border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            {t("bono.rd.unexplained")}
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
            {t("bono.rd.preparedBy")}
          </p>
          <p className="mt-1 text-sm text-ink">{report.submitted_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.submitted_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            {t("bono.rd.approvedBy")}
          </p>
          <p className="mt-1 text-sm text-ink">{report.approved_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.approved_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            {t("bono.rd.rejectedBy")}
          </p>
          <p className="mt-1 text-sm text-ink">{report.rejected_by_name || "—"}</p>
          <p className="text-xs text-ink-secondary">{formatTimestamp(report.rejected_at)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            {t("bono.rd.activityReadAt")}
          </p>
          <p className="mt-1 text-sm text-ink">{formatTimestamp(report.activity_generated_at)}</p>
        </div>
        {report.rejection_reason ? (
          <div className="md:col-span-2 xl:col-span-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-950">
            <span className="font-semibold">{t("bono.rd.rejectionReasonLabel")}</span> {report.rejection_reason}
          </div>
        ) : null}
        {report.correction_reason ? (
          <div className="md:col-span-2 xl:col-span-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
            <span className="font-semibold">{t("bono.rd.correctionReasonLabel")}</span> {report.correction_reason}
          </div>
        ) : null}
      </div>

      {hasMoney ? (
        <div className="grid gap-4 rounded border border-border bg-surface p-5 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              {t("bono.rd.sales")}
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.sales_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              {t("bono.rd.cashPaid")}
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.cash_paid_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              {t("bono.rd.mobilePaid")}
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.mobile_paid_total, currency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              {t("bono.rd.paymentsTotal")}
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">
              {formatMoney(report.payments_total, currency)}
            </p>
          </div>
          <p className="text-xs text-ink-secondary sm:col-span-2 xl:col-span-4">
            {t("bono.rd.moneyNote")}
          </p>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <div className="border-b border-border p-4">
          <h2 className="text-lg font-semibold text-ink">{t("bono.rd.accountability")}</h2>
          <p className="mt-1 text-sm text-ink-secondary">{t("bono.rd.accountabilityBlurb")}</p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("bono.op.bonoType")}</th>
              <th className="px-3 py-3 text-right">{t("bono.colIssued")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.transferredIn")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.transferredOut")}</th>
              <th className="px-3 py-3 text-right">{t("bono.colLost")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.used")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.returned")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.unexplained")}</th>
              <th className="px-3 py-3">{t("bono.rd.explanation")}</th>
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
                  <td className="px-3 py-3 text-right" title={t("bono.kpi.issuedTodayNote")}>
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
                        aria-label={t("bono.rd.usedAria").replace("{name}", line.bono_name_snapshot)}
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
                        aria-label={t("bono.rd.returnedAria").replace("{name}", line.bono_name_snapshot)}
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
                        aria-label={t("bono.rd.explanationAria").replace("{name}", line.bono_name_snapshot)}
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
            {t("bono.rd.noBonoActivity")}
          </p>
        ) : null}
      </div>

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <div className="border-b border-border p-4">
          <h2 className="text-lg font-semibold text-ink">{t("bono.rd.productReconciliation")}</h2>
          <p className="mt-1 text-sm text-ink-secondary">{t("bono.rd.productReconciliationBlurb")}</p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("bono.rd.product")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.opening")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.received")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.sold")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.breakage")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.expected")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.physical")}</th>
              <th className="px-3 py-3 text-right">{t("bono.rd.variance")}</th>
              <th className="px-3 py-3">{t("bono.rd.explanation")}</th>
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
                        aria-label={t("bono.rd.physicalClosingAria").replace("{name}", line.product_name_snapshot)}
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
                        aria-label={t("bono.rd.productExplanationAria").replace("{name}", line.product_name_snapshot)}
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
            {t("bono.rd.noProductPaired")}
          </p>
        ) : null}
      </div>

      <div className="rounded border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold text-ink">{t("bono.rd.notes")}</h2>
        {editable ? (
          <textarea
            className="control mt-3"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            aria-label={t("bono.rd.reportNotesAria")}
          />
        ) : (
          <p className="mt-2 whitespace-pre-wrap text-sm text-ink-secondary">
            {report.notes || t("bono.rd.noNotes")}
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
            {busy === "save" ? t("bono.rd.saving") : t("bono.rd.saveDraft")}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() =>
              void runAction(
                "refresh",
                () => refreshBonoReport(report.id),
                t("bono.rd.activityRefreshed"),
              )
            }
            disabled={busy !== ""}
          >
            {busy === "refresh" ? t("bono.rd.refreshing") : t("bono.rd.refreshActivity")}
          </button>
          <form onSubmit={handleSubmit} className="inline">
            <button type="submit" className="btn btn-primary" disabled={busy !== ""}>
              {busy === "submit"
                ? t("bono.rd.submitting")
                : t("bono.rd.submitForReview")}
            </button>
          </form>
          <p className="text-xs text-ink-secondary">
            {t("bono.rd.submitLocksNote")}
          </p>
        </div>
      ) : null}

      {report.status === "SUBMITTED" && permissions.approve ? (
        <div className="grid gap-4 rounded border border-border bg-surface p-5 xl:grid-cols-2">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void runAction(
                "approve",
                () => approveBonoReport(report.id),
                t("bono.rd.reportApproved"),
              );
            }}
          >
            <h2 className="text-lg font-semibold text-ink">{t("bono.rd.approve")}</h2>
            <p className="mt-1 text-sm text-ink-secondary">{t("bono.rd.approveBlurb")}</p>
            <button type="submit" className="btn btn-primary mt-3" disabled={busy !== ""}>
              {busy === "approve" ? t("bono.rd.approving") : t("bono.rd.approveReport")}
            </button>
          </form>
          <form onSubmit={handleReject}>
            <h2 className="text-lg font-semibold text-ink">{t("bono.rd.reject")}</h2>
            <p className="mt-1 text-sm text-ink-secondary">{t("bono.rd.rejectBlurb")}</p>
            <input
              type="text"
              className="control mt-3"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder={t("bono.rd.whatMustBeCorrected")}
              aria-label={t("bono.rd.rejectAria")}
            />
            <button type="submit" className="btn btn-secondary mt-3" disabled={busy !== ""}>
              {busy === "reject" ? t("bono.rd.rejecting") : t("bono.rd.rejectReport")}
            </button>
          </form>
        </div>
      ) : null}

      {report.status === "APPROVED" && permissions.approve ? (
        <form onSubmit={handleCorrection} className="rounded border border-border bg-surface p-5">
          <h2 className="text-lg font-semibold text-ink">{t("bono.rd.startCorrection")}</h2>
          <p className="mt-1 text-sm text-ink-secondary">{t("bono.rd.startCorrectionBlurb")}</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="min-w-64 flex-1 text-sm font-medium text-ink">
              {t("bono.rd.correctionReason")}
              <input
                type="text"
                className="control mt-1.5"
                value={correctionReason}
                onChange={(event) => setCorrectionReason(event.target.value)}
                placeholder={t("bono.rd.reviseApprovedWhy")}
              />
            </label>
            <button type="submit" className="btn btn-secondary" disabled={busy !== ""}>
              {busy === "correct"
                ? t("bono.rd.openingCorrection")
                : t("bono.rd.openCorrection")}
            </button>
          </div>
        </form>
      ) : null}

      {report.status === "SUBMITTED" && !permissions.approve ? (
        <p className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          {t("bono.rd.waitingForOwner")}
        </p>
      ) : null}
      {report.status === "APPROVED" && !permissions.approve ? (
        <p className="rounded border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
          {t("bono.rd.approvedImmutable")}
        </p>
      ) : null}
    </section>
  );
}
