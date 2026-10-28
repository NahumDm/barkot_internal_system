"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { useT } from "@/lib/i18n/context";
import { EmptyNote, ErrorBanner, LoadingNote, PageHeader } from "@/features/payroll/parts";
import {
  archiveEmployee,
  createEmployee,
  listEmployees,
  restoreEmployee,
  updateEmployee,
  uploadEmployeeDocument,
  type ContractType,
  type Employee,
  type EmployeeUpdateInput,
} from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

/**
 * The employee register: who works here, kept independently of logins (spec §5).
 *
 * **No account is created from this screen.** Registering someone records a
 * person, not a login; the `username` column exists only to show the rare row
 * that does have one, and nothing here can grant or revoke access.
 *
 * **Archive instead of delete.** There is no delete button because there is no
 * delete endpoint: a person who has left is archived (history stays, payroll
 * rows keep pointing at them) and can be restored. The two calls are
 * idempotent, so a double-click is a second no-op rather than an error.
 *
 * **The document is chosen, not linked.** A file input per row posts straight
 * to the upload endpoint, which validates PDF content and size and stores the
 * file under a name of its own; the table only ever shows "{t("employee.pdfOnFile")}" and
 * that stored name. There is no URL to render and none is invented here.
 *
 * One form serves create and edit, in the same locked-then-unlocked way the
 * deduction register does it: pressing Edit prefills the fields and switches
 * the submit to PATCH, so the two writes cannot drift in what they accept or
 * in how a refusal is shown.
 */

const CONTRACT_TYPES: { value: ContractType; label: string }[] = [
  { value: "FULL_TIME", label: "Full-time" },
  { value: "PART_TIME", label: "Part-time" },
  { value: "CONTRACT", label: "Contract" },
  { value: "TEMPORARY", label: "Temporary" },
  { value: "INTERN", label: "Intern" },
];

type Filter = "active" | "archived" | "all";

const EMPTY_FORM = {
  full_name: "",
  position: "",
  phone_number: "",
  start_date: "",
  contract_type: "FULL_TIME" as ContractType,
  contract_end_date: "",
  notes: "",
  address: "",
  emergency_contact: "",
};

export default function EmployeeRegister() {
  const { status, user } = useAuth();
  const checking = status === "checking";
  const isOwner = user?.role?.toUpperCase() === "OWNER";
  const canManage =
    isOwner && (user?.permissions?.includes("users.manage_employees") ?? false);
  const t = useT();

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<Filter>("active");
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);

  // Pressing Edit populates the form above the table. On a laptop the table is
  // already scrolled into view, so without this the only visible change happens
  // off-screen and the button looks broken. Moving the form into view (and
  // focusing its first field) makes the edit state unmistakable.
  useEffect(() => {
    if (!editing) return;
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    nameInputRef.current?.focus({ preventScroll: true });
  }, [editing]);

  // The success/error banner sits above the form and would otherwise be just
  // outside the viewport after a save. `nearest` scrolls only as far as needed.
  useEffect(() => {
    if (!saved && !error) return;
    feedbackRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [saved, error]);

  const refresh = useCallback(
    () =>
      listEmployees({
        ...(filter === "all" ? {} : { archived: filter === "archived" ? "true" : "false" }),
        page_size: 100,
      }).then((page) => {
        setEmployees(page.results);
        setReady(true);
      }),
    [filter],
  );

  useEffect(() => {
    if (checking || !canManage) return;
    refresh().catch((value: unknown) => setError(value as ApiError));
  }, [checking, canManage, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(null);
    const body = {
      full_name: form.full_name.trim(),
      position: form.position.trim(),
      phone_number: form.phone_number.trim(),
      start_date: form.start_date,
      contract_type: form.contract_type,
      contract_end_date: form.contract_end_date || null,
      notes: form.notes.trim(),
      address: form.address.trim(),
      emergency_contact: form.emergency_contact.trim(),
    };
    try {
      if (editing) {
        const updated = await updateEmployee(editing.id, body satisfies EmployeeUpdateInput);
        setEditing(null);
        setSaved(t("employee.updated").replace("{name}", updated.full_name));
      } else {
        const created = await createEmployee(body);
        setSaved(t("employee.added").replace("{name}", created.full_name));
      }
      setForm(EMPTY_FORM);
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  function startEdit(employee: Employee): void {
    setEditing(employee);
    setForm({
      full_name: employee.full_name,
      position: employee.position,
      phone_number: employee.phone_number,
      start_date: employee.start_date ?? "",
      contract_type: employee.contract_type,
      contract_end_date: employee.contract_end_date ?? "",
      notes: employee.notes,
      address: employee.address,
      emergency_contact: employee.emergency_contact,
    });
    setError(null);
    setSaved(null);
  }

  function cancelEdit(): void {
    setEditing(null);
    setForm(EMPTY_FORM);
    setError(null);
  }

  async function toggleArchived(employee: Employee): Promise<void> {
    setError(null);
    setSaved(null);
    try {
      if (employee.is_archived) {
        const restored = await restoreEmployee(employee.id);
        setSaved(t("employee.restored").replace("{name}", restored.full_name));
      } else {
        const archived = await archiveEmployee(employee.id);
        setSaved(t("employee.archivedMsg").replace("{name}", archived.full_name));
      }
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    }
  }

  async function uploadFor(employee: Employee, file: File | undefined): Promise<void> {
    if (!file) return;
    setError(null);
    setSaved(null);
    try {
      await uploadEmployeeDocument(employee.id, file);
      setSaved(t("employee.pdfOnFileFor").replace("{name}", employee.full_name));
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    }
  }

  const header = (
    <PageHeader
      eyebrow={t("employee.eyebrow")}
      title={t("employee.title")}
      blurb={t("employee.blurb")}
    />
  );

  if (!checking && !canManage) {
    return (
      <section className="space-y-6">
        {header}
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          {t("employee.noAccess")}
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      {header}
      <div ref={feedbackRef} className="space-y-3" aria-live="polite">
        <ErrorBanner error={error} />
        {saved && (
          <p className="rounded border border-success/30 bg-success/10 p-3 text-sm text-success">
            {saved}
          </p>
        )}
      </div>

      <form
        ref={formRef}
        onSubmit={submit}
        className="scroll-mt-4 grid gap-3 rounded border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-3 sm:col-span-2 lg:col-span-4">
          <h2 className="text-sm font-semibold text-ink">
            {editing ? t("employee.editing").replace("{name}", editing.full_name) : t("employee.registerNew")}
          </h2>
          {editing && (
            <span className="font-mono text-xs text-ink-secondary">
              Employee ID {editing.employee_id}
            </span>
          )}
        </div>
        <label className="field-label">
          {t("employee.fullName")}
          <input
            ref={nameInputRef}
            required
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          {t("employee.position")}
          <input
            required
            value={form.position}
            onChange={(event) => setForm({ ...form, position: event.target.value })}
            placeholder={t("employee.positionPlaceholder")}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          {t("employee.phoneOptional")}
          <input
            value={form.phone_number}
            onChange={(event) => setForm({ ...form, phone_number: event.target.value })}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          {t("employee.address")}
          <input
            value={form.address}
            onChange={(event) => setForm({ ...form, address: event.target.value })}
            className="control mt-1.5"
            placeholder={t("employee.addressPlaceholder")}
          />
        </label>
        <label className="field-label">
          {t("employee.emergencyContact")}
          <input
            value={form.emergency_contact}
            onChange={(event) => setForm({ ...form, emergency_contact: event.target.value })}
            className="control mt-1.5"
            placeholder={t("employee.emergencyContactPlaceholder")}
          />
        </label>
        <label className="field-label">
          {t("employee.started")}
          <input
            required
            type="date"
            value={form.start_date}
            onChange={(event) => setForm({ ...form, start_date: event.target.value })}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          {t("employee.contractType")}
          <select
            value={form.contract_type}
            onChange={(event) =>
              setForm({ ...form, contract_type: event.target.value as ContractType })
            }
            className="control mt-1.5"
          >
            {CONTRACT_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {t(`employee.contractType.${option.value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          {t("employee.contractEndsOptional")}
          <input
            type="date"
            value={form.contract_end_date}
            onChange={(event) => setForm({ ...form, contract_end_date: event.target.value })}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label sm:col-span-2">
          {t("employee.notesOptional")}
          <input
            value={form.notes}
            onChange={(event) => setForm({ ...form, notes: event.target.value })}
            className="control mt-1.5"
          />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-4 lg:justify-self-end">
          {editing && (
            <button type="button" onClick={cancelEdit} className="btn btn-secondary">
              {t("common.cancel")}
            </button>
          )}
          <button type="submit" disabled={saving} className="btn btn-primary">
            {saving ? t("common.saving") : editing ? t("employee.saveChanges") : t("employee.addToRegister")}
          </button>
        </div>
      </form>

      <div className="flex flex-wrap items-center gap-3">
        <label className="field-label">
          {t("employee.showing")}
          <select
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value as Filter);
              setReady(false);
            }}
            className="control mt-1.5"
          >
            <option value="active">{t("employee.currentStaff")}</option>
            <option value="archived">{t("employee.archivedLeft")}</option>
            <option value="all">{t("employee.everyone")}</option>
          </select>
        </label>
      </div>

      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("employee.colEmployeeId")}</th>
              <th className="px-3 py-3">{t("employee.colFullName")}</th>
              <th className="px-3 py-3">{t("employee.colPosition")}</th>
              <th className="px-3 py-3">{t("employee.colPhone")}</th>
              <th className="px-3 py-3">{t("employee.colAddress")}</th>
              <th className="px-3 py-3">{t("employee.colStarted")}</th>
              <th className="px-3 py-3">{t("employee.colContract")}</th>
              <th className="px-3 py-3">{t("employee.colStatus")}</th>
              <th className="px-3 py-3">{t("employee.colDocument")}</th>
              <th className="px-3 py-3">{t("employee.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((employee) => (
              <tr key={employee.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3 text-ink-secondary font-mono text-xs">
                  {employee.employee_id}
                </td>
                <td className="px-3 py-3 font-medium text-ink">{employee.full_name}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.position}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.phone_number || "—"}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.address || "—"}</td>
                <td className="px-3 py-3 text-ink-secondary">{employee.start_date ?? "—"}</td>

                <td className="px-3 py-3 text-ink-secondary">
                  {employee.contract_type_display}
                  {employee.contract_end_date ? ` · until ${employee.contract_end_date}` : ""}
                </td>
                <td className="px-3 py-3">
                  <span
                    className={`inline-block rounded bg-canvas px-2 py-1 text-xs font-semibold ${
                      employee.is_archived ? "text-danger" : "text-success"
                    }`}
                  >
                    {employee.is_archived ? t("employee.archived") : t("employee.active")}
                  </span>
                </td>
                <td className="px-3 py-3 text-ink-secondary">
                  {employee.has_document ? (
                    <a
                      href={`/api/v1/employees/${employee.id}/document/view/`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand underline text-xs font-semibold"
                      title={employee.document_filename}
                    >
                      {t("employee.pdfOnFile")}
                    </a>
                  ) : (
                    t("employee.none")
                  )}
                  <label className="ml-3 inline-flex cursor-pointer items-center">
                    <span className="text-xs font-semibold text-brand underline">
                      {employee.has_document ? t("employee.replace") : t("employee.upload")}
                    </span>
                    <input
                      type="file"
                      accept="application/pdf,.pdf"
                      className="sr-only"
                      onChange={(event) => {
                        void uploadFor(employee, event.target.files?.[0]);
                        event.target.value = "";
                      }}
                    />
                  </label>
                </td>
                <td className="px-3 py-3">
                  <div className="flex flex-wrap gap-2">
                    {!employee.is_archived && (
                      <button
                        type="button"
                        onClick={() => startEdit(employee)}
                        className="btn btn-secondary"
                      >
                        {t("employee.edit")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void toggleArchived(employee)}
                      className="btn btn-ghost"
                    >
                      {employee.is_archived ? t("employee.restore") : t("employee.archive")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!ready ? (
          error ? (
            <EmptyNote>{t("employee.loadError")}</EmptyNote>
          ) : (
            <LoadingNote label={t("employee.loading")} />
          )
        ) : (
          employees.length === 0 && (
            <EmptyNote>
              {filter === "archived"
                ? t("employee.noArchived")
                : t("employee.noOneYet")}
            </EmptyNote>
          )
        )}
      </div>
    </section>
  );
}
