"use client";

import type { ApiError } from "@/lib/api/errors";
import { fieldLabel } from "./format";

/**
 * The pieces all three payroll screens share.
 *
 * Kept together so an error reads the same way whether it arrived from the
 * roster, the runs or the deductions — and so the field-error list is written
 * once. A `validation_error` puts its real text in `details` and only a
 * placeholder in `message`, so a banner that shows only `message` would tell a
 * user "The submitted data is invalid" and nothing else.
 */

export function PageHeader({
  eyebrow,
  title,
  blurb,
}: {
  eyebrow: string;
  title: string;
  blurb: string;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-brand">{eyebrow}</p>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      <p className="mt-1 text-sm text-ink-secondary">{blurb}</p>
    </div>
  );
}

export function ErrorBanner({ error }: { error: ApiError | null }) {
  if (!error) return null;

  const specifics = Object.entries(error.details ?? {}).flatMap(([field, messages]) =>
    messages.map((message) =>
      field === "non_field_errors" ? message : `${fieldLabel(field)}: ${message}`,
    ),
  );

  return (
    <div
      role="alert"
      className="rounded border border-danger/30 bg-danger/10 p-3 text-sm text-danger"
    >
      <p>{error.message}</p>
      {specifics.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {specifics.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const TONE_TEXT: Record<string, string> = {
  PAID: "text-success",
  APPROVED: "text-success",
  ACTIVE: "text-success",
  GENERATED: "text-warning",
  PENDING: "text-warning",
  TERMINATED: "text-danger",
  INACTIVE: "text-danger",
  CANCELLED: "text-danger",
};

/** A status as the server spelled it, tinted by what it means. */
export function StatusChip({ status, display }: { status: string; display: string }) {
  return (
    <span
      className={`inline-block rounded bg-canvas px-2 py-1 text-xs font-semibold ${TONE_TEXT[status] ?? "text-ink-secondary"}`}
    >
      {display}
    </span>
  );
}

/** Fills a table or a card while the first request is still in flight. */
export function LoadingNote({ label }: { label: string }) {
  return <p className="p-6 text-center text-sm text-ink-secondary">{label}</p>;
}

/** The empty state, which is a real state and not just a blank table. */
export function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="p-6 text-center text-sm text-ink-secondary">{children}</p>;
}

/**
 * What the screen says when the session has no payroll permissions.
 *
 * Distinct from an error banner on purpose: nothing failed, and telling someone
 * their session broke when the honest answer is "your role does not include
 * payroll" sends them to sign in again for no reason.
 */
export function NoAccessNote() {
  return (
    <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
      Your role does not include payroll. Ask an owner if you need access.
    </div>
  );
}
