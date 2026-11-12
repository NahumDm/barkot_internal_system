/**
 * Display formatting for payroll (spec §14).
 *
 * Two of these are here because getting them wrong is invisible until it is
 * expensive. `monthKeyOf` reads a `YYYY-MM-DD` period as a month without going
 * through `Date`, so the server's `2026-10-01` cannot become September 30 in a
 * browser ahead of UTC. `currentMonthKey` reads the local calendar rather than
 * `toISOString()` for the same reason in the other direction: at 22:00 on the
 * 31st in Addis Ababa, UTC is already the next month, and the screen would open
 * on a month nobody is paying.
 *
 * Money stays a string until it is printed. Every figure arrives as a `Decimal`
 * serialised by DRF, and `Number("18000.00")` losing the trailing zeros is a
 * display concern, not a rounding one: the arithmetic already happened on the
 * server.
 */

/** `18000` / `"18000.00"` → `"18,000.00 ETB"`. */
export function money(value: string | number, currency = "ETB"): string {
  const amount = Number(value);
  const formatted = Number.isFinite(amount)
    ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value);
  return `${formatted} ${currency}`;
}

/** `"2026-10-01"` or `"2026-10"` → `"2026-10"`. */
export function monthKeyOf(periodMonth: string): string {
  const [year, month] = periodMonth.split("-");
  return `${year}-${month}`;
}

/** `"2026-10"` / `"2026-10-01"` → `"October 2026"`. */
export function monthLabel(periodMonth: string): string {
  const [year, month] = periodMonth.split("-").map(Number);
  return new Date(year, (month || 1) - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/** The local calendar month, as `"2026-10"`. */
export function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** Move a `"YYYY-MM"` key by whole months, wrapping into the neighbouring year. */
export function shiftMonthKey(key: string, delta: number): string {
  const [year, month] = key.split("-").map(Number);
  const moved = new Date(year, (month || 1) - 1 + delta, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * A `"YYYY-MM"` key as the first day of that month — what `POST /payroll/runs/`
 * asks for. The server normalises any date in the month to the first, so this is
 * the shape a form should send rather than "today", which would silently move a
 * generated run to the wrong period whenever it was generated late.
 */
export function monthToPeriod(key: string): string {
  return `${key}-01`;
}

/** Today's date in the local calendar, as a `YYYY-MM-DD` value input. */
export function todayISO(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * An audit timestamp as a date a person reads.
 *
 * The server sends an aware `DateTimeField`, so converting in the browser
 * gives the day it was approved *here*, which is the day the person who
 * approved it remembers. An unparseable value falls back to the raw string
 * rather than rendering "Invalid Date" — the audit trail should survive a
 * display problem.
 */
export function dateStamp(value: string | null): string {
  if (!value) return "";

  // A date-only value has no time zone of its own, and `new Date("2026-10-01")`
  // parses it as UTC midnight — which is 30 September in the Americas. Building
  // it from local parts instead keeps the day the server meant.
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    return new Date(Number(year), Number(month) - 1, Number(day)).toLocaleDateString();
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString();
}

/** `payroll_item` → `payroll item`, for turning field errors into sentences. */
export function fieldLabel(field: string): string {
  return field.replace(/_/g, " ");
}
