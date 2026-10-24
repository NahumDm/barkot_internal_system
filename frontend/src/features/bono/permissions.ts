"use client";

import { useAuth } from "@/features/auth/auth-provider";

/**
 * What the signed-in account may do in Bono, for presentation only.
 *
 * The server re-checks every request against the role matrix. This hook only
 * keeps an action a person may never take off their screen, and it separates
 * "still checking" from "not allowed" so a slow session lookup does not read as
 * a refusal.
 */
export interface BonoPermissions {
  checking: boolean;
  view: boolean;
  configure: boolean;
  operate: boolean;
  submit: boolean;
  approve: boolean;
  deduct: boolean;
}

export function useBonoPermissions(): BonoPermissions {
  const { status, user } = useAuth();
  const granted = user?.permissions ?? [];
  const has = (codename: string) => granted.includes(codename);

  return {
    checking: status === "checking",
    view: has("bono.view_bono"),
    configure: has("bono.manage_configuration"),
    operate: has("bono.manage_operations"),
    submit: has("bono.submit_report"),
    approve: has("bono.approve_report"),
    deduct: has("payroll.create_deduction"),
  };
}
