"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n/context";
import { useCallback, useEffect, useState } from "react";

import {
  getBonoDaySummary,
  listBonoIncidents,
  listBonoIssues,
  listBonoTransfers,
  listBonoTypes,
  type BonoDaySummary,
  type BonoIncident,
  type BonoIssue,
  type BonoTransfer,
  type BonoType,
} from "@/lib/api/bono";
import type { ApiError } from "@/lib/api/errors";
import { useBonoPermissions } from "./permissions";
import { BonoLostFollowUp } from "./bono-follow-up";
import { BonoOperationsPanel } from "./bono-operations";
import {
  BonoColorDot,
  BonoPageHeader,
  BonoStatusBadge,
  EmptyNote,
  LoadingNote,
  formatDay,
  formatTimestamp,
  localDay,
} from "./parts";

interface MovementRow {
  key: string;
  at: string;
  action: string;
  bono: string;
  color: string;
  people: string;
  quantity: number;
  detail: string;
  status: string | null;
}

function movementRows(
  t: (key: string) => string,
  issues: BonoIssue[],
  transfers: BonoTransfer[],
  incidents: BonoIncident[],
): MovementRow[] {
  const rows: MovementRow[] = [
    ...issues.map((issue) => ({
      key: `issue-${issue.id}`,
      at: issue.occurred_at,
      action:
        issue.kind === "INITIAL"
          ? t("bono.movement.initialIssue")
          : t("bono.movement.additionalIssue"),
      bono: issue.bono_name_snapshot,
      color: issue.bono_color_snapshot,
      people: issue.employee_name,
      quantity: issue.quantity,
      detail: issue.note || "—",
      status: null,
    })),
    ...transfers.map((transfer) => ({
      key: `transfer-${transfer.id}`,
      at: transfer.occurred_at,
      action: t("bono.movement.transfer"),
      bono: transfer.bono_name_snapshot,
      color: transfer.bono_color_snapshot,
      people: `${transfer.from_employee_name} to ${transfer.to_employee_name}`,
      quantity: transfer.quantity,
      detail: transfer.reason,
      status: null,
    })),
    ...incidents.map((incident) => ({
      key: `incident-${incident.id}`,
      at: incident.occurred_at,
      action:
        incident.kind === "LOST_BONO"
          ? t("bono.movement.lostBono")
          : t("bono.movement.brokenBottle"),
      bono:
        incident.kind === "LOST_BONO"
          ? incident.bono_name_snapshot
          : (incident.product_name ?? t("bono.movement.productFallback")),
      color: incident.bono_color_snapshot || "#6b5a5e",
      people: incident.responsible_employee_name ?? "—",
      quantity: incident.quantity,
      detail: incident.reason,
      status: incident.resolution_status,
    })),
  ];
  return rows.sort((left, right) => right.at.localeCompare(left.at));
}

function Kpi({ label, value, note }: Readonly<{ label: string; value: string; note: string }>) {
  return (
    <div className="rounded border border-border bg-surface p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      <p className="mt-1 text-xs text-ink-secondary">{note}</p>
    </div>
  );
}

export default function BonoOverviewPage() {
  const permissions = useBonoPermissions();
  const t = useT();
  const [date, setDate] = useState(localDay());
  const [summary, setSummary] = useState<BonoDaySummary | null>(null);
  const [types, setTypes] = useState<BonoType[]>([]);
  const [issues, setIssues] = useState<BonoIssue[]>([]);
  const [transfers, setTransfers] = useState<BonoTransfer[]>([]);
  const [incidents, setIncidents] = useState<BonoIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    try {
      const [day, typePage, issuePage, transferPage, incidentPage] = await Promise.all([
        getBonoDaySummary(date),
        listBonoTypes(),
        listBonoIssues({ date }),
        listBonoTransfers({ date }),
        listBonoIncidents({ date }),
      ]);
      setSummary(day);
      setDate(day.operational_date);
      setTypes(typePage.results);
      setIssues(issuePage.results);
      setTransfers(transferPage.results);
      setIncidents(incidentPage.results);
      setError(null);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getBonoDaySummary(date),
      listBonoTypes(),
      listBonoIssues({ date }),
      listBonoTransfers({ date }),
      listBonoIncidents({ date }),
    ])
      .then(([day, typePage, issuePage, transferPage, incidentPage]) => {
        if (!active) return;
        setSummary(day);
        setDate(day.operational_date);
        setTypes(typePage.results);
        setIssues(issuePage.results);
        setTransfers(transferPage.results);
        setIncidents(incidentPage.results);
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
  }, [date]);

  const issued = summary?.bono_totals.reduce((total, row) => total + row.total_issued, 0) ?? 0;
  const custody = summary?.staff_balances.reduce((total, row) => total + row.balance, 0) ?? 0;
  const lost = summary?.bono_totals.reduce((total, row) => total + row.lost, 0) ?? 0;
  const rows = movementRows(t, issues, transfers, incidents);
  const latest = summary?.latest_report ?? null;

  return (
    <section className="space-y-6">
      <BonoPageHeader
        eyebrow={t("common.bono")}
        title={t("bono.overviewTitle")}
        description={t("bono.overviewDescription")}
        actions={
          <>
            <label className="text-sm font-medium text-ink">
              <span className="sr-only">{t("bono.operationalDate")}</span>
              <input
                type="date"
                className="control"
                value={date}
                onChange={(event) => {
                  setLoading(true);
                  setDate(event.target.value);
                }}
              />
            </label>
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
          </>
        }
      />

      {error ? (
        <p role="alert" className="form-error">
          {error.message}
        </p>
      ) : null}
      {loading && !summary ? <LoadingNote label={t("bono.loadingLedger")} /> : null}

      {summary ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-medium text-ink">{formatDay(summary.operational_date)}</span>
            <span
              className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${
                summary.operations_locked
                  ? "bg-canvas text-ink-secondary"
                  : "bg-emerald-100 text-emerald-900"
              }`}
            >
              {summary.operations_locked ? t("bono.custodyLocked") : t("bono.openForCustody")}
            </span>
            {summary.in_progress_dates.length > 0 ? (
              <span className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-950">
                {t("bono.unreportedActivity").replace(
                  "{dates}",
                  summary.in_progress_dates.map(formatDay).join(", "),
                )}
              </span>
            ) : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              label={t("bono.kpi.issuedToday")}
              value={String(issued)}
              note={t("bono.kpi.issuedTodayNote")}
            />
            <Kpi
              label={t("bono.kpi.inCustody")}
              value={String(custody)}
              note={t("bono.kpi.inCustodyNote")}
            />
            <Kpi
              label={t("bono.kpi.lostToday")}
              value={String(lost)}
              note={t("bono.kpi.lostTodayNote")}
            />
            <Kpi
              label={t("bono.kpi.dailyReport")}
              value={latest ? t(`bono.status.${latest.status}`) : t("bono.kpi.notStarted")}
              note={
                latest
                  ? t("bono.kpi.revision").replace("{n}", String(latest.revision))
                  : t("bono.kpi.requiredBeforeSignoff")
              }
            />
          </div>

          <div className="rounded border border-border bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-ink">{t("bono.dailyReportHeading")}</h2>
                <p className="mt-1 text-sm text-ink-secondary">
                  {latest
                    ? t("bono.revisionIs")
                        .replace("{n}", String(latest.revision))
                        .replace("{status}", t(`bono.status.${latest.status}`))
                    : t("bono.noReportPrepared")}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {latest ? (
                  <BonoStatusBadge status={latest.status} label={t(`bono.status.${latest.status}`)} />
                ) : null}
                {latest ? (
                  <Link href={`/bono/reports/${latest.id}`} className="btn btn-secondary">
                    {t("bono.viewReport")}
                  </Link>
                ) : null}
                {permissions.submit &&
                (!latest || latest.status === "DRAFT" || latest.status === "REJECTED") ? (
                  <Link href="/bono/reports" className="btn btn-primary">
                    {latest ? t("bono.continueReport") : t("bono.prepareReport")}
                  </Link>
                ) : null}
              </div>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <div className="overflow-x-auto rounded border border-border bg-surface">
              <div className="border-b border-border p-4">
                <h2 className="text-lg font-semibold text-ink">{t("bono.byTypeHeading")}</h2>
              </div>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
                  <tr>
                    <th className="px-3 py-3">{t("bono.colBono")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colInitial")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colAdditional")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colIn")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colOut")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colLost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.bono_totals.map((row) => (
                    <tr key={row.bono_type_id} className="border-b border-border last:border-0">
                      <td className="px-3 py-3 font-medium text-ink">
                        <BonoColorDot color={row.bono_color} label={row.bono_name} />
                      </td>
                      <td className="px-3 py-3 text-right">{row.initial_issued}</td>
                      <td className="px-3 py-3 text-right">{row.additional_issued}</td>
                      <td className="px-3 py-3 text-right">{row.transfers_in}</td>
                      <td className="px-3 py-3 text-right">{row.transfers_out}</td>
                      <td className="px-3 py-3 text-right">{row.lost}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {summary.bono_totals.length === 0 ? (
                <EmptyNote>{t("bono.noActivity")}</EmptyNote>
              ) : null}
            </div>

            <div className="overflow-x-auto rounded border border-border bg-surface">
              <div className="border-b border-border p-4">
                <h2 className="text-lg font-semibold text-ink">{t("bono.staffCustody")}</h2>
              </div>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
                  <tr>
                    <th className="px-3 py-3">{t("bono.colStaff")}</th>
                    <th className="px-3 py-3">{t("bono.colBono")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colIssued")}</th>
                    <th className="px-3 py-3 text-right">{t("bono.colBalance")}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.staff_balances.map((row) => (
                    <tr
                      key={`${row.employee_id}-${row.bono_type_id}`}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-3 py-3">
                        <p className="font-medium text-ink">{row.employee_name}</p>
                        <p className="text-xs text-ink-secondary">{row.employee_position}</p>
                      </td>
                      <td className="px-3 py-3">
                        <BonoColorDot color={row.bono_color} label={row.bono_name} />
                      </td>
                      <td className="px-3 py-3 text-right">{row.issued}</td>
                      <td className="px-3 py-3 text-right font-semibold text-ink">{row.balance}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {summary.staff_balances.length === 0 ? (
                <EmptyNote>{t("bono.noStaffHolder")}</EmptyNote>
              ) : null}
            </div>
          </div>

          {permissions.operate ? (
            <BonoOperationsPanel
              date={summary.operational_date}
              types={types}
              locked={summary.operations_locked}
              onChanged={() => {
                setLoading(true);
                void load();
              }}
            />
          ) : null}

          <div className="overflow-x-auto rounded border border-border bg-surface">
            <div className="border-b border-border p-4">
              <h2 className="text-lg font-semibold text-ink">{t("bono.movementsTitle")}</h2>
              <p className="mt-1 text-sm text-ink-secondary">{t("bono.movementsBlurb")}</p>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
                <tr>
                  <th className="px-3 py-3">{t("bono.mvColTime")}</th>
                  <th className="px-3 py-3">{t("bono.mvColAction")}</th>
                  <th className="px-3 py-3">{t("bono.mvColBonoProduct")}</th>
                  <th className="px-3 py-3">{t("bono.mvColStaff")}</th>
                  <th className="px-3 py-3 text-right">{t("bono.mvColQty")}</th>
                  <th className="px-3 py-3">{t("bono.mvColDetail")}</th>
                  <th className="px-3 py-3">{t("bono.mvColStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key} className="border-b border-border last:border-0">
                    <td className="px-3 py-3 whitespace-nowrap text-ink-secondary">
                      {formatTimestamp(row.at)}
                    </td>
                    <td className="px-3 py-3 font-medium text-ink">{row.action}</td>
                    <td className="px-3 py-3">
                      <BonoColorDot color={row.color} label={row.bono} />
                    </td>
                    <td className="px-3 py-3 text-ink-secondary">{row.people}</td>
                    <td className="px-3 py-3 text-right">{row.quantity}</td>
                    <td className="max-w-xs px-3 py-3 text-ink-secondary">{row.detail}</td>
                    <td className="px-3 py-3">
                      {row.status ? (
                        <span className="inline-flex rounded bg-canvas px-2 py-0.5 text-xs font-semibold text-ink-secondary">
                          {t(`bono.incidentStatus.${row.status}`)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 ? <EmptyNote>{t("bono.noMovements")}</EmptyNote> : null}
          </div>

          {permissions.operate ? (
            <BonoLostFollowUp
              incidents={incidents}
              locked={summary.operations_locked}
              canDeduct={permissions.deduct}
              onChanged={() => {
                setLoading(true);
                void load();
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
