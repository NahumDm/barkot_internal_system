"use client";

import { Globe } from "lucide-react";
import { LOCALES, LOCALE_LABELS, type Locale } from "@/lib/i18n";
import { useI18n } from "@/lib/i18n/context";

/**
 * Language toggle (globe icon), a universal control for switching between the
 * supported locales. Clicking flips the current locale and every `t(...)` in
 * the tree re-renders with the other dictionary, so screens change language
 * immediately without a reload. The choice persists in `localStorage`.
 *
 * Used in the authenticated topbar and on the public auth screens.
 */
export function LanguageSwitcher({
  className = "lang-switch",
}: Readonly<{ className?: string }>) {
  const { locale, setLocale } = useI18n();
  const t = useI18n().t;

  const next: Locale = locale === "en" ? "am" : "en";
  const label = LOCALE_LABELS[next];

  const toggle = () => setLocale(next);

  return (
    <button
      type="button"
      className={className}
      onClick={toggle}
      aria-label={t("language.switchTo").replace("{label}", label)}
      title={t("language.switchTo").replace("{label}", label)}
    >
      <Globe className="h-5 w-5" aria-hidden="true" />
      <span className="lang-switch-code" aria-hidden="true">
        {LOCALE_LABELS[locale]}
      </span>
    </button>
  );
}

export const SUPPORTED_LOCALES = LOCALES;
