/**
 * Tests for payroll's display formatting.
 *
 * The cases here are the ones that fail *silently* in production: a month read
 * as the wrong month, a day shifted by a browser's UTC offset, a figure that
 * loses its decimals. Each is asserted against the value a person in Addis
 * Ababa would read, not against whatever the machine's clock happens to say.
 */

import { describe, expect, it } from "vitest";

import {
  currentMonthKey,
  dateStamp,
  fieldLabel,
  money,
  monthKeyOf,
  monthLabel,
  monthToPeriod,
  shiftMonthKey,
  todayISO,
} from "@/features/payroll/format";

describe("month keys", () => {
  it("reads a period's first day as its month", () => {
    expect(monthKeyOf("2026-10-01")).toBe("2026-10");
  });

  it("passes a bare month key through unchanged", () => {
    expect(monthKeyOf("2026-10")).toBe("2026-10");
  });

  it("renders a period as the month a person would say", () => {
    expect(monthLabel("2026-10-01")).toBe(
      new Date(2026, 9, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    );
  });

  it("turns a month key into the first day the API asks for", () => {
    expect(monthToPeriod("2026-10")).toBe("2026-10-01");
  });
});

describe("shifting months", () => {
  it("steps backwards into the previous year", () => {
    expect(shiftMonthKey("2026-01", -1)).toBe("2025-12");
  });

  it("steps forwards into the next year", () => {
    expect(shiftMonthKey("2026-12", 1)).toBe("2027-01");
  });

  it("stays put for a zero step", () => {
    expect(shiftMonthKey("2026-10", 0)).toBe("2026-10");
  });

  it("crosses months that are not thirty-one days long", () => {
    expect(shiftMonthKey("2026-02", 1)).toBe("2026-03");
  });
});

describe("the current month", () => {
  it("is a bare year and month", () => {
    expect(currentMonthKey()).toMatch(/^\d{4}-\d{2}$/);
  });

  it("is today's date, which is what a date input expects", () => {
    expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(todayISO().startsWith(currentMonthKey())).toBe(true);
  });
});

describe("stamps", () => {
  it("keeps a date-only value on the day the server meant", () => {
    // `new Date("2026-10-01")` parses as UTC midnight, which is 30 September in
    // any zone behind UTC. Building from local parts is the only way the day
    // survives, and this asserts the local construction rather than a literal so
    // the test is correct whatever zone it runs in.
    expect(dateStamp("2026-10-01")).toBe(new Date(2026, 9, 1).toLocaleDateString());
  });

  it("renders an aware timestamp as a date", () => {
    expect(dateStamp("2026-10-06T09:15:00+00:00")).toBe(new Date(2026, 9, 6).toLocaleDateString());
  });

  it("shows the raw value rather than 'Invalid Date'", () => {
    expect(dateStamp("not a date")).toBe("not a date");
  });

  it("renders nothing for an absent stamp", () => {
    expect(dateStamp(null)).toBe("");
    expect(dateStamp("")).toBe("");
  });
});

describe("money", () => {
  it("prints two decimals with the currency", () => {
    expect(money("18000.00")).toBe(
      `${(18000).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} ETB`,
    );
  });

  it("accepts an explicit currency", () => {
    expect(money("0.5", "ETB")).toContain("0.50 ETB");
  });

  it("does not invent a number out of garbage", () => {
    expect(money("n/a")).toBe("n/a ETB");
  });
});

describe("field labels", () => {
  it("turns a serializer field name into a phrase", () => {
    expect(fieldLabel("monthly_wage")).toBe("monthly wage");
    expect(fieldLabel("non_field_errors")).toBe("non field errors");
  });
});
