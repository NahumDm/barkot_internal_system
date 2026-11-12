/**
 * Guards the locale dictionaries against drift.
 *
 * `useT` falls back to the raw key when a translation is missing, which shows
 * the English key on screen instead of a word - easy to miss in review. These
 * assertions fail the build when a key is added to one locale but not the other,
 * when a translation is blank, or when an interpolation placeholder (like
 * `{name}`) is dropped, since a missing placeholder would render a sentence with
 * a hole where the value should be.
 */

import { describe, expect, it } from "vitest";

import am from "@/lib/i18n/locales/am.json";
import en from "@/lib/i18n/locales/en.json";

type Dict = Record<string, string>;

const enDict = en as Dict;
const amDict = am as Dict;
const enKeys = Object.keys(enDict).sort();
const amKeys = Object.keys(amDict).sort();

/** Every `{token}` used for interpolation inside a value. */
function placeholders(value: string): string[] {
  return [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
}

describe("locale dictionaries", () => {
  it("defines the same keys in English and Amharic", () => {
    expect(amKeys).toEqual(enKeys);
  });

  it("has a non-empty value for every key in both locales", () => {
    for (const key of enKeys) {
      expect(enDict[key].trim(), `en.${key}`).not.toBe("");
      expect(amDict[key]?.trim(), `am.${key}`).not.toBe("");
    }
  });

  it("keeps interpolation placeholders identical between locales", () => {
    for (const key of enKeys) {
      expect(placeholders(amDict[key] ?? ""), `am.${key}`).toEqual(
        placeholders(enDict[key]),
      );
    }
  });

  it("actually translates the English values into Amharic script", () => {
    // A handful of values are identical on purpose (brand names like "Bono",
    // or symbols), so only flag a mass copy where most values match verbatim.
    const identical = enKeys.filter((key) => enDict[key] === amDict[key]);
    expect(identical.length / enKeys.length).toBeLessThan(0.05);
  });
});
