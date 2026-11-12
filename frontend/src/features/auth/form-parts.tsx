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
import { Copyright, Eye, EyeOff } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ErrorCode, type ApiError } from "@/lib/api";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { useT } from "@/lib/i18n/context";

/**
 * The one message shown above a form.
 *
 * `role="alert"` so a screen reader announces a failure that arrives after the
 * user pressed the button, when their focus is still on the control they just
 * used and nothing else would be read out.
 */
export function FormError({
  error,
  variant = "app",
}: Readonly<{ error: ApiError | null; variant?: "app" | "auth" }>) {
  const t = useT();
  if (error === null) return null;
  return (
    <p role="alert" className={variant === "auth" ? "auth-error" : "form-error"}>
      {describe(error, t)}
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
export function describe(error: ApiError, t: (key: string, fallback?: string) => string = (k) => k): string {
  if (error.code === ErrorCode.Throttled) {
    return t("auth.tooManyAttempts");
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
  min,
  step,
  inputMode,
  revealable = false,
  variant = "app",
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
  min?: number;
  step?: number | string;
  inputMode?: "text" | "decimal" | "numeric";
  /**
   * Render a show/hide control inside the input for secret fields. The type is
   * switched between `password` and `text`; the value and caret are preserved by
   * React's controlled input, so toggling mid-typing does not lose the entry.
   */
  revealable?: boolean;
  /**
   * `"app"` styles the field for a white application surface (the default);
   * `"auth"` keeps the dark chrome that belongs to the sign-in card. The same
   * component serves both because the markup and the label/error wiring are
   * identical - only the surface it sits on differs.
   */
  variant?: "app" | "auth";
}>) {
  const id = useId();
  const errorId = `${id}-error`;
  const isAuth = variant === "auth";
  const t = useT();
  const [revealed, setRevealed] = useState(false);
  const resolvedType = revealable ? (revealed ? "text" : "password") : type;

  const input = (
    <input
      id={id}
      type={resolvedType}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      autoComplete={autoComplete}
      autoFocus={autoFocus}
      disabled={disabled}
      placeholder={placeholder}
      min={min}
      step={step}
      inputMode={inputMode}
      aria-invalid={errors.length > 0}
      aria-describedby={errors.length > 0 ? errorId : undefined}
      className={isAuth ? "auth-input" : "control"}
    />
  );

  return (
    <div className={isAuth ? "auth-field" : "field"}>
      <label htmlFor={id} className={isAuth ? undefined : "field-label"}>
        {label}
      </label>
      {revealable ? (
        <div className={isAuth ? "control-wrap control-wrap--auth" : "control-wrap"}>
          {input}
          <button
            type="button"
            className="password-toggle"
            onClick={() => setRevealed((current) => !current)}
            disabled={disabled}
            aria-pressed={revealed}
          >
            {revealed ? (
              <EyeOff aria-hidden="true" size={18} />
            ) : (
              <Eye aria-hidden="true" size={18} />
            )}
            <span className="sr-only">{revealed ? t("auth.hidePassword") : t("auth.showPassword")}</span>
          </button>
        </div>
      ) : (
        input
      )}
      {hint !== undefined && errors.length === 0 ? (
        <p className={isAuth ? "auth-hint" : "field-hint"}>{hint}</p>
      ) : null}
      {errors.map((message) => (
        <p key={message} id={errorId} className={isAuth ? "auth-field-error" : "field-error"}>
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
  const t = useT();
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const updateScale = () => {
      if (window.innerWidth <= 720) {
        setScale(1);
        return;
      }

      // The footer sits below the card, so its height comes off the vertical
      // budget before the card is scaled. Without it a short viewport would
      // scale the card to fill the screen and push the footer out of sight.
      setScale(Math.min(1, (window.innerWidth - 32) / 900, (window.innerHeight - 32 - 52) / 563));
    };

    updateScale();
    window.addEventListener("resize", updateScale);
    return () => window.removeEventListener("resize", updateScale);
  }, []);

  return (
    <main className="auth-page">
      <div className="auth-lang" aria-label={t("common.language")}>
        <LanguageSwitcher className="lang-switch lang-switch--auth" />
      </div>
      <div className="auth-decoration" aria-hidden="true">
        <span className="auth-blob auth-blob-top" />
        <span className="auth-blob auth-blob-bottom" />
        <span className="auth-bubble auth-bubble-one" />
        <span className="auth-bubble auth-bubble-two" />
        <span className="auth-bubble auth-bubble-three" />
        <span className="auth-bubble auth-bubble-four" />
      </div>
      <div className="auth-stage">
        <div
          className="auth-card-frame"
          style={{
            width: scale > 0.99 ? 900 : 900 * scale,
            height: scale > 0.99 ? 563 : 563 * scale,
          }}
        >
          <section className="auth-card" style={{ transform: `scale(${scale})` }}>
            <svg
              className="auth-wave"
              viewBox="0 0 900 563"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path d="M0 0H350C360 70 420 110 470 170C530 240 575 300 545 380C520 450 490 500 490 563H0Z" />
            </svg>
            <div className="auth-left">
              <Image
                className="auth-mark"
                src="/images/barkot-mark.png"
                alt={t("app.logoAlt")}                width={169}
                height={169}
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
      </div>
      <footer className="auth-page-footer">
        <Copyright aria-hidden="true" size={13} />
        <span>{t("common.copyright")}</span>
      </footer>
    </main>
  );
}
