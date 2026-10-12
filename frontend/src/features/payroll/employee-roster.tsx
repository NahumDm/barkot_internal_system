"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createPayrollEmployee,
  listPayrollEmployees,
  listPayrollProfiles,
  type PayrollEmployee,
  type PayrollProfile,
} from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

import { money } from "./format";
import { usePayrollPermissions } from "./permissions";
import { EmptyNote, ErrorBanner, LoadingNote, NoAccessNote, PageHeader, StatusChip } from "./parts";

/**
 * Who is on monthly payroll, and the form that puts someone there (spec §14.2).
 *
 * The roster and the options list are two endpoints on purpose. `/employees/`
 * is a payroll resource and needs `payroll.view_payroll`; `/profiles/` lists
 * staff who are *not* on payroll yet and needs `payroll.manage_payroll_employees`,
 * because the only screen that reads it is this form. Fetching the second one
 * without the second permission would earn a 403 on a page that otherwise works,
 * so it is only asked for when the form is drawn.
 *
 * Adding someone is not an edit of the person: the profile stays where it is and
 * payroll takes a wage snapshot of it. That is why the form has a wage field and
 * nothing else — name, position, phone and start date are already the profile's,
 * and copying them here would give the same person two addresses.
 *
 * `ready` covers both requests because the screen is one screen: if either half
 * failed, saying "no one is on payroll yet" under a banner that says the request
 * failed would be answering a question nobody asked. The staff select holds a
 * *preference* rather than a chosen id, so a roster that shrinks underneath it
 * falls back to the first option with nothing to repair afterwards.
 */
export default function EmployeeRoster() {
  const { checking, view: canView, manageEmployees } = usePayrollPermissions();

  const [employees, setEmployees] = useState<PayrollEmployee[]>([]);
  const [profiles, setProfiles] = useState<PayrollProfile[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [profileChoice, setProfileChoice] = useState("");
  const [wage, setWage] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const refresh = useCallback((): Promise<unknown> => {
    const employeePage = listPayrollEmployees({ query: { page_size: 100 } });
    const profilePage = manageEmployees
      ? listPayrollProfiles({ query: { page_size: 100 } })
      : Promise.resolve(null);

    return Promise.all([employeePage, profilePage]).then(([staff, options]) => {
      setEmployees(staff.results);
      if (options) setProfiles(options.results);
      setReady(true);
    });
  }, [manageEmployees]);

  useEffect(() => {
    if (checking || !canView) return;
    refresh().catch((value: unknown) => setError(value as ApiError));
  }, [checking, canView, refresh]);

  const profileId =
    profileChoice && profiles.some((option) => String(option.id) === profileChoice)
      ? profileChoice
      : String(profiles[0]?.id ?? "");

  const noOneWaiting = ready && profiles.length === 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const created = await createPayrollEmployee({
        profile: Number(profileId),
        monthly_wage: wage,
      });
      setWage("");
      setSaved(`${created.full_name} now earns ${money(created.monthly_wage)} a month.`);
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  const header = (
    <PageHeader
      eyebrow="Payroll"
      title="Employees"
      blurb="Who is on monthly payroll, and for how much."
    />
  );

  if (!checking && !canView) {
    return (
      <section className="space-y-6">
        {header}
        <NoAccessNote />
      </section>
    );
  }

  return (
    <section className="space-y-6">
      {header}
      <ErrorBanner error={error} />
      {saved && (
        <p className="rounded border border-success/30 bg-success/10 p-3 text-sm text-success">
          {saved}
        </p>
      )}

      {manageEmployees && ready && (
        <form
          onSubmit={submit}
          className="grid gap-3 rounded border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
        >
          <label className="text-sm text-ink sm:col-span-2">
            Staff member
            <select
              required
              value={profileId}
              onChange={(event) => setProfileChoice(event.target.value)}
              className="control mt-1"
            >
              <option value="" disabled>
                Select staff member
              </option>
              {profiles.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.full_name} — {option.position}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-ink">
            Monthly wage (ETB)
            <input
              required
              min="0"
              step="0.01"
              type="number"
              value={wage}
              onChange={(event) => setWage(event.target.value)}
              className="control mt-1"
            />
          </label>
          <div className="flex items-end">
            <button
              disabled={saving || noOneWaiting || !profileId}
              type="submit"
              className="btn btn-primary w-full"
            >
              {saving ? "Adding..." : "Add to payroll"}
            </button>
          </div>
          {noOneWaiting && (
            <p className="text-xs text-ink-secondary sm:col-span-2 lg:col-span-4">
              Every active staff member is already on payroll. New names arrive from Settings.
            </p>
          )}
        </form>
      )}

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">Full name</th>
              <th className="px-3 py-3">Position</th>
              <th className="px-3 py-3">Phone</th>
              <th className="px-3 py-3">Started</th>
              <th className="px-3 py-3">Monthly wage</th>
              <th className="px-3 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((employee) => (
              <tr key={employee.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3 font-medium text-ink">{employee.full_name}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.position}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.phone_number}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.start_date}</td>
                <td className="px-3 py-3">{money(employee.monthly_wage, employee.currency)}</td>
                <td className="px-3 py-3">
                  <StatusChip status={employee.status} display={employee.status_display} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!ready ? (
          error ? (
            <EmptyNote>Payroll employees could not be loaded. See the message above.</EmptyNote>
          ) : (
            <LoadingNote label="Loading payroll employees..." />
          )
        ) : (
          employees.length === 0 && <EmptyNote>No one is on payroll yet.</EmptyNote>
        )}
      </div>
    </section>
  );
}
