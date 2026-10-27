/**
 * Employee register API client (spec §5).
 *
 * The register is the roster of who works here, kept independently of login
 * accounts: creating a person here creates no user and grants no access. Three
 * shapes mirror the backend serializers.
 *
 * **No document URL, ever.** The upload endpoint stores the PDF outside the web
 * root under a server-generated name; the API reports only whether one is on
 * file (`has_document`) and its stored filename. Exposing a link would be
 * inventing a route the system does not have — a screen shows "PDF on file",
 * and a filename that came from the uploader's disk is never trusted or
 * echoed back as something to render.
 *
 * **Archiving replaces deletion.** There is no delete endpoint and therefore
 * no delete wrapper here; `archiveEmployee` is how someone leaves, and
 * `restoreEmployee` brings them back. Payroll rows already recorded keep
 * pointing at the archived person, which is the whole point.
 */

import { apiFetch, type RequestOptions } from "./client";
import { type PaginatedResponse } from "./finance";

/** Contract kinds the register tracks (`apps.core.enums.ContractType`). */
export type ContractType = "FULL_TIME" | "PART_TIME" | "CONTRACT" | "TEMPORARY" | "INTERN";

/** One person in the register. Everything here is stored or derived server-side. */
export interface Employee {
  id: number;
  employee_id: string;
  full_name: string;
  position: string;
  phone_number: string;
  /** ISO date, or `null` when employment has no recorded start. */
  start_date: string | null;
  contract_type: ContractType;
  contract_type_display: string;
  /** ISO date for fixed-term contracts; `null` means open-ended. */
  contract_end_date: string | null;
  is_archived: boolean;
  archived_at: string | null;
  notes: string;
  /** Linked login account, `null` for almost every row. */
  user: number | null;
  /** The linked login name, `""` when this person has no account. */
  username: string;
  has_document: boolean;
  /** The server-generated stored name — not the uploader's filename. */
  document_filename: string;
  address: string;
  emergency_contact: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeCreateInput {
  full_name: string;
  position: string;
  /** Required on create; may be blank. */
  start_date: string;
  phone_number?: string;
  /** Defaults to `FULL_TIME` server-side. */
  contract_type?: ContractType;
  /** ISO date, or `null`/omitted for an open-ended contract. */
  contract_end_date?: string | null;
  notes?: string;
  address?: string;
  /** Optional on create: the register only requires name, position and start date. */
  emergency_contact?: string;
}

/** Every field optional so a one-field edit does not restate the rest. */
export interface EmployeeUpdateInput {
  full_name?: string;
  position?: string;
  phone_number?: string;
  start_date?: string;
  contract_type?: ContractType;
  /** An explicit `null` clears a fixed-term end date; absent leaves it alone. */
  contract_end_date?: string | null;
  notes?: string;
  address?: string;
  emergency_contact?: string;
}

export interface EmployeeFilters {
  /** `true` lists only people who have left, `false` only people who have not. */
  archived?: "true" | "false";
  page?: number;
  page_size?: number;
}

export function listEmployees(
  filters: EmployeeFilters = {},
  options: RequestOptions = {},
): Promise<PaginatedResponse<Employee>> {
  return apiFetch<PaginatedResponse<Employee>>("/employees/", {
    ...options,
    query: { ...options.query, ...filters },
  });
}

export function getEmployee(id: number, options: RequestOptions = {}): Promise<Employee> {
  return apiFetch<Employee>(`/employees/${id}/`, options);
}

/** Register a new staff member. Creates no login account. */
export function createEmployee(
  input: EmployeeCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Employee> {
  return apiFetch<Employee>("/employees/", { ...options, method: "POST", body: input });
}

/** Edit a register record. Send only the fields that changed. */
export function updateEmployee(
  id: number,
  input: EmployeeUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Employee> {
  return apiFetch<Employee>(`/employees/${id}/`, { ...options, method: "PATCH", body: input });
}

/**
 * Mark someone as having left. Idempotent: archiving an archived record is a
 * no-op that returns 200 with the record unchanged.
 */
export function archiveEmployee(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Employee> {
  return apiFetch<Employee>(`/employees/${id}/archive/`, { ...options, method: "POST" });
}

/** Bring an archived record back onto the register. Also idempotent. */
export function restoreEmployee(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Employee> {
  return apiFetch<Employee>(`/employees/${id}/restore/`, { ...options, method: "POST" });
}

/**
 * Put a contract PDF on file against one record, replacing any previous one.
 *
 * The file must be a real PDF: the server checks the extension, the `%PDF-`
 * content header and a size limit before anything is written, and stores it
 * under a name of its own. Refuses with `validation_error` otherwise.
 */
export function viewEmployeeDocument(
  id: number,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Response> {
  return fetch(
    new URL(`/employees/${id}/document/view/`, process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1").toString(),
    {
      method: "GET",
      credentials: "include",
      headers: new Headers({ Accept: "application/pdf" }),
      signal: options.signal,
    },
  );
}

export function uploadEmployeeDocument(
  id: number,
  file: File,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Employee> {
  const form = new FormData();
  form.append("document", file);
  return apiFetch<Employee>(`/employees/${id}/document/`, {
    ...options,
    method: "POST",
    body: form,
  });
}
