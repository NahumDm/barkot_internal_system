import type { ReactNode } from "react";

import type { BonoReportStatus } from "@/lib/api/bono";

/** Format money the way the rest of the app does: grouped, two decimals, code. */
export function formatMoney(
  amount: string | null | undefined,
  currency: string | undefined,
): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) return amount;
  return `${numeric.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${currency ?? ""}`.trim();
}

/** Format a decimal quantity without pretending every product is an integer. */
export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

/** A calendar date from the API (`YYYY-MM-DD`) without a timezone shift. */
export function formatDay(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(year, month - 1, day));
}

/** A timestamp from the API, in the browser's local timezone. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

/** The browser's local calendar day, used only to seed a date picker. */
export function localDay(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

const REPORT_TONES: Record<BonoReportStatus, string> = {
  DRAFT: "bg-canvas text-ink-secondary",
  SUBMITTED: "bg-amber-100 text-amber-900",
  APPROVED: "bg-emerald-100 text-emerald-900",
  REJECTED: "bg-red-100 text-red-900",
};

export function BonoStatusBadge({
  status,
  label,
}: Readonly<{ status: BonoReportStatus; label?: string }>) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${REPORT_TONES[status]}`}
    >
      {label ?? status}
    </span>
  );
}

export function BonoColorDot({ color, label }: Readonly<{ color: string; label: string }>) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className="inline-block h-3 w-3 shrink-0 rounded-full border border-black/10"
        style={{ backgroundColor: color }}
      />
      <span>{label}</span>
    </span>
  );
}

export function LoadingNote({ label }: Readonly<{ label: string }>) {
  return <p className="p-6 text-center text-sm text-ink-secondary">{label}</p>;
}

export function EmptyNote({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="empty-text p-6 text-center text-sm text-ink-secondary">{children}</p>;
}

export function BonoPageHeader({
  eyebrow,
  title,
  description,
  actions,
}: Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}>) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          {eyebrow}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-secondary">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
