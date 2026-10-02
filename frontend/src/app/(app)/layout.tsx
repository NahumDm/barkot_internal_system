import type { ReactNode } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { RequireAuth } from "@/features/auth/require-auth";

/**
 * Every page in this group is signed-in-only.
 *
 * The guard is outside `AppShell` deliberately: the sidebar is navigation, and
 * rendering it while the session is still being checked would offer a user a
 * menu of screens they might not be allowed to open. `(public)` holds the pages
 * that must work without a session; a page that belongs to the application
 * belongs here, where being protected is the default rather than a step.
 */
export default function ProtectedLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
