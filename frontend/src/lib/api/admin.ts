/**
 * The accounts admin API client (roadmap C5, spec §9.2).
 *
 * Three groups of calls: staff users (list/create/update — there is no delete;
 * an account is deactivated instead), the read-only role catalogue, and the
 * singleton system-settings row. All of them are Owner-only on the server; the
 * page gates on the same permissions before it draws a form.
 *
 * Invalid input is refused by Django with a `validation_error` envelope. The
 * create/update helpers surface that as an `ApiError` with `.details` keyed by
 * field name, which the settings form renders against the offending input.
 */

import { get, patch, post, type RequestOptions } from "./client";
import type { PaginatedResponse } from "./finance";

/** One staff account, as the Owner's admin screen sees it. */
export interface StaffUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  role_name: string;
  email: string;
  phone_number: string;
  is_active: boolean;
  is_staff: boolean;
  is_temporary_password: boolean;
  last_login: string | null;
}

/** Body of `POST /users/`. `role` is the stable code, not an id. */
export interface StaffUserCreateInput {
  username: string;
  role: string;
  email?: string;
  phone_number?: string;
  /** Omit it to create a locked account that cannot sign in yet. */
  password?: string;
}

/** Partial body of `PATCH /users/{id}/`. */
export interface StaffUserUpdateInput {
  role?: string;
  email?: string;
  phone_number?: string;
  is_active?: boolean;
}

/** One business role from the fixed catalogue, with its resolved grants. */
export interface RoleSummary {
  code: string;
  name: string;
  description: string;
  is_staff_role: boolean;
  permissions: string[];
}

/** The singleton system settings row. `updated_at`/`updated_by` are read-only provenance. */
export interface SiteSettings {
  session_timeout_minutes: number;
  password_max_age_days: number;
  require_password_change_for_new_users: boolean;
  updated_at: string;
  updated_by: string | null;
}

/** Fields the Owner may change on the settings row. */
export interface SiteSettingsUpdateInput {
  session_timeout_minutes?: number;
  password_max_age_days?: number;
  require_password_change_for_new_users?: boolean;
}

export function listStaffUsers(
  options: RequestOptions = {},
): Promise<PaginatedResponse<StaffUser>> {
  return get<PaginatedResponse<StaffUser>>("/users/", options);
}

export function createStaffUser(
  input: StaffUserCreateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StaffUser> {
  return post<StaffUser>("/users/", input, options);
}

export function updateStaffUser(
  id: number,
  input: StaffUserUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<StaffUser> {
  return patch<StaffUser>(`/users/${id}/`, input, options);
}

export function listRoles(options: RequestOptions = {}): Promise<PaginatedResponse<RoleSummary>> {
  return get<PaginatedResponse<RoleSummary>>("/roles/", options);
}

export function getSiteSettings(): Promise<SiteSettings> {
  return get<SiteSettings>("/settings/");
}

export function updateSiteSettings(
  input: SiteSettingsUpdateInput,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<SiteSettings> {
  return patch<SiteSettings>("/settings/", input, options);
}
