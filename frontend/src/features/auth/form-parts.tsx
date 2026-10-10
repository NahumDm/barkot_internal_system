/**
 * Form chrome shared by the sign-in and change-password screens.
 *
 * Both are small enough that their layout would otherwise be duplicated, and the
 * duplicated part is the part that has to look the same: an error that is
 * announced, and field errors that sit next to the input they belong to rather
 * than in a list at the top.
 */

"use client";

import Image from "next/image";
import { useEffect, useId, useState, type ReactNode } from "react";

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
      className="auth-error"
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
  placeholder,
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
  placeholder?: string;
}>) {
  const id = useId();
  const errorId = `${id}-error`;

  return (
    <div className="auth-field">
      <label htmlFor={id}>
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
        placeholder={placeholder}
        aria-invalid={errors.length > 0}
        aria-describedby={errors.length > 0 ? errorId : undefined}
        className="auth-input"
      />
      {hint !== undefined && errors.length === 0 ? (
        <p className="auth-hint">{hint}</p>
      ) : null}
      {errors.map((message) => (
        <p key={message} id={errorId} className="auth-field-error">
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
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const updateScale = () => {
      if (window.innerWidth <= 720) {
        setScale(1);
        return;
      }

      setScale(Math.min(1, (window.innerWidth - 32) / 900, (window.innerHeight - 32) / 563));
    };

    updateScale();
    window.addEventListener("resize", updateScale);
    return () => window.removeEventListener("resize", updateScale);
  }, []);

  return (
    <main className="auth-page">
      <div className="auth-decoration" aria-hidden="true">
        <span className="auth-blob auth-blob-top" />
        <span className="auth-blob auth-blob-bottom" />
        <span className="auth-bubble auth-bubble-one" />
        <span className="auth-bubble auth-bubble-two" />
        <span className="auth-bubble auth-bubble-three" />
        <span className="auth-bubble auth-bubble-four" />
      </div>
      <div
        className="auth-card-frame"
        style={{ width: scale > 0.99 ? 900 : 900 * scale, height: scale > 0.99 ? 563 : 563 * scale }}
      >
      <section className="auth-card" style={{ transform: `scale(${scale})` }}>
        <svg className="auth-wave" viewBox="0 0 900 563" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0 0H350C360 70 420 110 470 170C530 240 575 300 545 380C520 450 490 500 490 563H0Z" />
        </svg>
        <div className="auth-left">
          <Image
            className="auth-mark"
            src="/images/barkot-mark.png"
            alt="Barkot logo"
            width={240}
            height={120}
            priority
            unoptimized
          />
          <Image
            className="auth-lockup"
            src="/images/barkot-lockup.png"
            alt="MURAA FI KITIFOO ISPEESHAALII BAARKOOT"
            width={900}
            height={300}
            priority
            unoptimized
          />
        </div>
        <div className="auth-form-panel">
          <h1>{title}</h1>
          {subtitle ? <p className="auth-subtitle">{subtitle}</p> : null}
          {children}
        </div>
      </section>
      </div>
    </main>
  );
}
