/**
 * The protected-route guard (spec §9.1, roadmap B2, B3).
 *
 * Protected pages render nothing at all until the session is known. That is the
 * whole design: the alternative - render the page and redirect once the check
 * comes back - shows a cashier a flash of a screen they are not authorised for,
 * which is both ugly and a small information leak about what exists.
 *
 * The guard waits for the answer rather than guessing, so `unavailable` is a
 * retry rather than a redirect. Sending someone to `/login` because the API
 * happened to be down teaches them that their password is the problem.
 *
 * There are three ways out, and each means something different for the user:
 * signed out goes to `/login` with the attempted path so signing in returns
 * there; a temporary password goes to `/change-password`, because the API
 * refuses every other endpoint with `password_change_required` and a user parked
 * on the dashboard would find every action failing for no visible reason.
 *
 * The attempted path travels to `/login` as `next` so signing in can return the
 * user to where they were going, instead of dumping them on the dashboard
 * because they followed a link to a sale.
 */

"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth, type AuthStatus } from "./auth-provider";

export function RequireAuth({ children }: Readonly<{ children: ReactNode }>) {
  const { status, user, problem, refresh } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const mustChangePassword = status === "authenticated" && user?.is_temporary_password === true;

  useEffect(() => {
    if (status === "anonymous") {
      const next = pathname ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
      return;
    }
    if (mustChangePassword) {
      router.replace("/change-password");
    }
  }, [status, mustChangePassword, pathname, router]);

  // The change screen sits outside this group precisely so it stays reachable
  // while it is the one thing required.
  if (status !== "authenticated" || mustChangePassword) {
    return <GuardNotice status={status} problem={problem} onRetry={() => void refresh()} />;
  }

  return <>{children}</>;
}

function GuardNotice({
  status,
  problem,
  onRetry,
}: Readonly<{ status: AuthStatus; problem: string | null; onRetry: () => void }>) {
  if (status === "unavailable") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-6 text-center">
        <h1 className="text-xl font-semibold text-ink">Cannot reach the server</h1>
        <p className="max-w-md text-sm text-ink-secondary">
          {problem ?? "The session could not be checked."} This is usually temporary.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="rounded border border-border bg-surface px-4 py-2 text-sm font-medium text-ink"
        >
          Try again
        </button>
      </div>
    );
  }

  const message =
    status === "anonymous"
      ? "Redirecting to sign in…"
      : status === "checking"
        ? "Checking your session…"
        : "Setting up your account…";

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <p className="text-sm text-ink-secondary">{message}</p>
    </div>
  );
}
