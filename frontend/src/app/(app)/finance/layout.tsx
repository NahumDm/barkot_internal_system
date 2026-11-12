"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/features/auth/auth-provider";

/**
 * The finance section is readable only to roles holding `finance.view_reports`.
 *
 * The sidebar already hides these destinations, but a bookmark or a hand-typed
 * URL must not paint a balance screen whose every request answers 403. The
 * layout guards the whole subtree while each child keeps its own loading and
 * error states.
 */
export default function FinanceLayout({ children }: Readonly<{ children: ReactNode }>) {
  const { status, user } = useAuth();

  if (status === "checking") {
    return <p className="text-sm text-ink-secondary">Checking access...</p>;
  }

  if (!user?.permissions.includes("finance.view_reports")) {
    return (
      <section className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Finance</p>
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include viewing finance. Ask an owner if you need access.
        </div>
      </section>
    );
  }

  return <>{children}</>;
}
