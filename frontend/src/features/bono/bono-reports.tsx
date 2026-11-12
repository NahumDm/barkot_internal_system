"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n/context";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createBonoReport,
  listBonoReports,
  type BonoReport,
  type BonoReportStatus,
} from "@/lib/api/bono";
import type { ApiError } from "@/lib/api/errors";
import { useBonoPermissions } from "./permissions";
import {
  BonoPageHeader,
  BonoStatusBadge,
  EmptyNote,
  LoadingNote,
  formatDay,
  formatTimestamp,
  localDay,
} from "./parts";

const STATUS_OPTIONS: Array<{ value: "" | BonoReportStatus; label: string }> = [
  { value: "", label: "common.allStatuses" },
  { value: "DRAFT", label: "bono.status.DRAFT" },
  { value: "SUBMITTED", label: "bono.status.SUBMITTED" },
  { value: "APPROVED", label: "bono.status.APPROVED" },
  { value: "REJECTED", label: "bono.status.REJECTED" },
];

export default function BonoReportsPage() {
  const permissions = useBonoPermissions();
  const router = useRouter();
  const t = useT();
  const [reports, setReports] = useState<BonoReport[]>([]);
  const [status, setStatus] = useState<"" | BonoReportStatus>("");
  const [date, setDate] = useState("");
  const [createDate, setCreateDate] = useState(localDay());
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [createError, setCreateError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await listBonoReports({
        status: status || undefined,
        date: date || undefined,
      });
      setReports(page.results);
      setError(null);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setLoading(false);
    }
  }, [date, status]);

  useEffect(() => {
    let active = true;
    listBonoReports({ status: status || undefined, date: date || undefined })
      .then((page) => {
        if (!active) return;
        setReports(page.results);
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
  }, [date, status]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const report = await createBonoReport({ operational_date: createDate });
      router.push(`/bono/reports/${report.id}`);
    } catch (value) {
      setCreateError(value as ApiError);
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="space-y-6">
      <BonoPageHeader
        eyebrow={t("common.bono")}
        title={t("bono.reportsTitle")}
        description={t("bono.reportsBlurb")}
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setLoading(true);
              void load();
            }}
          >
            {t("common.refresh")}
          </button>
        }
      />

      {permissions.submit ? (
        <form
          onSubmit={handleCreate}
          className="rounded border border-border bg-surface p-5"
          aria-labelledby="prepare-bono-report"
        >
          <h2 id="prepare-bono-report" className="text-lg font-semibold text-ink">
            {t("bono.prepareReportHeading")}
          </h2>
          <p className="mt-1 text-sm text-ink-secondary">{t("bono.prepareReportBlurb")}</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium text-ink">
              {t("bono.operationalDate")}
              <input
                type="date"
                className="control mt-1.5"
                value={createDate}
                onChange={(event) => setCreateDate(event.target.value)}
                required
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={creating || !createDate}>
              {creating ? t("bono.opening") : t("bono.openDailyReport")}
            </button>
          </div>
          {createError ? (
            <p role="alert" className="form-error mt-3">
              {createError.message}
            </p>
          ) : null}
        </form>
      ) : null}

      <div className="flex flex-wrap items-end gap-3 rounded border border-border bg-surface p-4">
        <label className="text-sm font-medium text-ink">
          {t("bono.filterStatus")}
          <select
            className="control mt-1.5"
            value={status}
            onChange={(event) => {
              setLoading(true);
              setStatus(event.target.value as "" | BonoReportStatus);
            }}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-ink">
          {t("bono.operationalDate")}
          <input
            type="date"
            className="control mt-1.5"
            value={date}
            onChange={(event) => {
              setLoading(true);
              setDate(event.target.value);
            }}
          />
        </label>
        {date ? (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setLoading(true);
              setDate("");
            }}
          >
            {t("bono.clearDate")}
          </button>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="form-error">
          {error.message}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("bono.colOperationalDate")}</th>
              <th className="px-3 py-3">{t("bono.colRevision")}</th>
              <th className="px-3 py-3">{t("bono.colStatus")}</th>
              <th className="px-3 py-3">{t("bono.colSubmitted")}</th>
              <th className="px-3 py-3">{t("bono.colApproved")}</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {reports.map((report) => (
              <tr key={report.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3 font-medium text-ink">
                  {formatDay(report.operational_date)}
                </td>
                <td className="px-3 py-3 text-ink-secondary">
                  {report.revision}
                  {report.corrects ? (
                    <span className="ml-1 text-xs">
                      {t("bono.corrects").replace("{n}", String(report.corrects))}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-3">
                  <BonoStatusBadge status={report.status} label={t(`bono.status.${report.status}`)} />
                </td>
                <td className="px-3 py-3 text-ink-secondary">
                  {report.submitted_at
                    ? `${report.submitted_by_name || "—"} · ${formatTimestamp(report.submitted_at)}`
                    : "—"}
                </td>
                <td className="px-3 py-3 text-ink-secondary">
                  {report.approved_at
                    ? `${report.approved_by_name || "—"} · ${formatTimestamp(report.approved_at)}`
                    : "—"}
                </td>
                <td className="px-3 py-3 text-right">
                  <Link href={`/bono/reports/${report.id}`} className="btn btn-secondary">
                    {t("bono.open")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading ? <LoadingNote label={t("bono.loadingDailyReports")} /> : null}
        {!loading && reports.length === 0 ? (
          <EmptyNote>{t("bono.noReportsMatch")}</EmptyNote>
        ) : null}
      </div>
    </section>
  );
}
