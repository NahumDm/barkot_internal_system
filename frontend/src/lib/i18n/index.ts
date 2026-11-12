export type Locale = 'en' | 'am';

export const LOCALES: Locale[] = ['en', 'am'];
export const DEFAULT_LOCALE: Locale = 'en';

export const LOCALE_LABELS: Record<Locale, string> = {
  en: 'English',
  am: 'አማርኛ',
};

export function getStoredLocale(): Locale {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  const v = window.localStorage.getItem('locale');
  return v === 'am' ? 'am' : 'en';
}

export function setStoredLocale(locale: Locale) {
  if (typeof window !== 'undefined') window.localStorage.setItem('locale', locale);
}