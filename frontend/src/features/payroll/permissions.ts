"use client";

import { useAuth } from "@/features/auth/auth-provider";

/**
 * What the signed-in account may do in payroll, for presentation only.
 *
 * The role matrix in `backend/apps/accounts.permissions` is the authority and
 * every endpoint asks it again; this hook exists so a button a user may never
 * press is not drawn in front of them (settings README: "hide or disable what a
 * role cannot do"). Nothing here is read from anywhere but the session the API
 * already returned, so it cannot disagree with the server's own answer — it can
 * only be *stale*, and every action below surfaces the 403 if it is.
 *
 * `checking` is separate from "has no permissions" because both would otherwise
 * render as an empty screen for the moment between navigation and `/auth/me/`
 * answering, which reads as "you are not allowed" when the truth is "not asked
 * yet".
 */
export interface PayrollPermissions {
  /** `/auth/me/` has not answered yet. */
  checking: boolean;
  /** `payroll.view_payroll` — runs, lines and the deduction history. */
  view: boolean;
  /** `payroll.manage_payroll_employees` — roster read and add-to-payroll. */
  manageEmployees: boolean;
  /** `payroll.generate_run` — create a month's run. */
  generate: boolean;
  /** `payroll.approve_run` — Owner: sign a generated run off. */
  approve: boolean;
  /** `payroll.mark_paid` — Owner: record that the money left. */
  markPaid: boolean;
  /** `payroll.create_deduction` — add to a line while the run is generated. */
  deduct: boolean;
}

export function usePayrollPermissions(): PayrollPermissions {
  const { status, user } = useAuth();
  const granted = user?.permissions ?? [];
  const has = (codename: string) => granted.includes(codename);

  return {
    checking: status === "checking",
    view: has("payroll.view_payroll"),
    manageEmployees: has("payroll.manage_payroll_employees"),
    generate: has("payroll.generate_run"),
    approve: has("payroll.approve_run"),
    markPaid: has("payroll.mark_paid"),
    deduct: has("payroll.create_deduction"),
  };
}
