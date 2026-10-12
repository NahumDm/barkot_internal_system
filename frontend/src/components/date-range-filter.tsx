"use client";

import { useId } from "react";

/**
 * The From/To date pair, and the single-date field it is built from, shared by
 * the dashboard, reports and balance screens so the filter reads the same
 * everywhere.
 *
 * The control stays a native `<input type="date">`: the picker, keyboard entry
 * and the `YYYY-MM-DD` value the API expects are all the browser's, and nothing
 * here replaces them. What this adds is layout - a label that sits on the
 * input's own line with a real gap instead of being glued to it - and a
 * `title` that spells the date out, since a locale-formatted `10/01/2026` reads
 * differently depending on where the person is.
 */

export function DateField({
  label,
  value,
  onChange,
  className,
}: Readonly<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}>) {
  const id = useId();

  return (
    <div className={className ? `date-field ${className}` : "date-field"}>
      <label className="date-field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        title={readableDate(value)}
        className="control date-input"
      />
    </div>
  );
}

export function DateRangeFilter({
  start,
  end,
  onStart,
  onEnd,
}: Readonly<{
  start: string;
  end: string;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
}>) {
  return (
    <div className="date-range">
      <DateField label="From" value={start} onChange={onStart} />
      <DateField label="To" value={end} onChange={onEnd} />
    </div>
  );
}

/**
 * `"2026-10-01"` -> `"01 Oct 2026"`.
 *
 * Built from the local calendar parts, not `new Date(iso)`, so a date-only
 * value is not read as UTC midnight and shown as the previous day.
 */
export function readableDate(value: string): string {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!parts) return value;

  const [, year, month, day] = parts;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const name = months[Number(month) - 1];
  if (!name) return value;

  return `${day} ${name} ${year}`;
}
