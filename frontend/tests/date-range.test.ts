/**
 * Tests for the shared date filter's display helper.
 *
 * A native date input shows the date in whatever order the browser's locale
 * wants, so `10/01/2026` is a different day depending on where the person is.
 * `readableDate` is what the field offers instead - a spelled-out month that
 * cannot be misread - so the two ambiguous orderings are the cases that matter.
 */

import { describe, expect, it } from "vitest";

import { readableDate } from "@/components/date-range-filter";

describe("readableDate", () => {
  it("spells a date out so 10/01 and 01/10 cannot be confused", () => {
    expect(readableDate("2026-10-01")).toBe("01 Oct 2026");
    expect(readableDate("2026-01-10")).toBe("10 Jan 2026");
  });

  it("pads a single-digit day and month", () => {
    expect(readableDate("2026-03-05")).toBe("05 Mar 2026");
  });

  it("returns a value it cannot parse unchanged", () => {
    expect(readableDate("")).toBe("");
    expect(readableDate("not-a-date")).toBe("not-a-date");
  });
});
