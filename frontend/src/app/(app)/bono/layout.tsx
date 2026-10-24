"use client";

import type { ReactNode } from "react";

import { useBonoPermissions } from "@/features/bono/permissions";

/**
 * The Bono section is readable to every role holding `bono.view_bono`.
 *
 * A bookmark or hand-typed URL must not paint a custody ledger whose every
 * request answers 403, so the whole subtree is guarded here. Individual actions
 * are still gated by their own permissions; Barman sees the ledger, not the
 * controls.
 */
export default function BonoLayout({ children }: Readonly<{ children: ReactNode }>) {
  const permissions = useBonoPermissions();

  if (permissions.checking) {
    return <p className="text-sm text-ink-secondary">Checking access...</p>;
  }

  if (!permissions.view) {
    return (
      <section className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Bono</p>
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include viewing Bono. Ask an owner if you need access.
        </div>
      </section>
    );
  }

  return <>{children}</>;
}
