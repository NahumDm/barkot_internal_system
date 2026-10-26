'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import { DEFAULT_LOCALE, getStoredLocale, setStoredLocale, type Locale } from './index';
import en from './locales/en.json';
import am from './locales/am.json';

const dictionaries: Record<Locale, Record<string, string>> = { en, am };

interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, fallback?: string) => string;
}

const I18nContext = createContext<I18nContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {},
  t: (k, f) => f ?? k,
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    setLocaleState(getStoredLocale());
  }, []);

  const setLocale = (l: Locale) => {
    setLocaleState(l);
    setStoredLocale(l);
    if (typeof document !== 'undefined') document.documentElement.lang = l === 'am' ? 'am' : 'en';
  };

  const t = (key: string, fallback?: string) => {
    const dict = dictionaries[locale] ?? dictionaries.en;
    return dict[key] ?? dictionaries.en[key] ?? fallback ?? key;
  };

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

export function useT() {
  return useI18n().t;
}