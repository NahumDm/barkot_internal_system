/**
 * Form chrome shared by the sign-in and change-password screens.
 *
 * Both are small enough that their layout would otherwise be duplicated, and the
 * duplicated part is the part that has to look the same: an error that is
 * announced, and field errors that sit next to the input they belong to rather
 * than in a list at the top.
 */

"use client";

import { useId, type ReactNode } from "react";

import { ErrorCode, type ApiError } from "@/lib/api";

/**
 * The one message shown above a form.
 *
 * `role="alert"` so a screen reader announces a failure that arrives after the
 * user pressed the button, when their focus is still on the control they just
 * used and nothing else would be read out.
 */
export function FormError({ error }: Readonly<{ error: ApiError | null }>) {
  if (error === null) return null;
  return (
    <p
      role="alert"
      className="rounded border border-danger bg-surface px-3 py-2 text-sm text-danger"
    >
      {describe(error)}
    </p>
  );
}

/**
 * Turn an `ApiError` into something worth showing a user.
 *
 * A throttled sign-in is the case that needs its own wording. A5 allows five
 * attempts a minute, and the API reports the sixth as a refusal of this attempt -
 * so showing "those credentials were not accepted" would be a plain lie about a
 * password that may be entirely correct.
 */
export function describe(error: ApiError): string {
  if (error.code === ErrorCode.Throttled) {
    return "Too many sign-in attempts. Wait a minute, then try again.";
  }

  const general = error.details?.["non_field_errors"];
  if (general && general.length > 0) return general.join(" ");

  return error.message;
}

export function Field({
  label,
  type,
  value,
  onChange,
  errors,
  autoComplete,
  autoFocus,
  disabled,
  hint,
}: Readonly<{
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  errors: string[];
  autoComplete: string;
  autoFocus?: boolean;
  disabled?: boolean;
  hint?: string;
}>) {
  const id = useId();
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        disabled={disabled}
        aria-invalid={errors.length > 0}
        aria-describedby={errors.length > 0 ? errorId : undefined}
        className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
      />
      {hint !== undefined && errors.length === 0 ? (
        <p className="text-xs text-ink-secondary">{hint}</p>
      ) : null}
      {errors.map((message) => (
        <p key={message} id={errorId} className="text-xs text-danger">
          {message}
        </p>
      ))}
    </div>
  );
}

export function FormShell({
  title,
  subtitle,
  children,
}: Readonly<{ title: string; subtitle: string; children?: ReactNode }>) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <section className="w-full max-w-sm rounded border border-border bg-surface p-6">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 text-sm text-ink-secondary">{subtitle}</p>
        <div className="mt-6 flex flex-col gap-4">{children}</div>
      </section>
    </main>
  );
}
