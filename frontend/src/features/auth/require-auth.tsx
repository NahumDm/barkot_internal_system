/**
 * The protected-route guard (spec §9.1, roadmap B2).
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
 * The attempted path travels to `/login` as `next` so signing in can return the
 * user to where they were going, instead of dumping them on the dashboard
 * because they followed a link to a sale.
 */

"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "./auth-provider";

export function RequireAuth({ children }: Readonly<{ children: ReactNode }>) {
  const { status, problem, refresh } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status !== "anonymous") return;
    const next = pathname ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`/login${next}`);
  }, [status, pathname, router]);

  if (status === "authenticated") return <>{children}</>;

  if (status === "unavailable") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-6 text-center">
        <h1 className="text-xl font-semibold text-ink">Cannot reach the server</h1>
        <p className="max-w-md text-sm text-ink-secondary">
          {problem ?? "The session could not be checked."} This is usually temporary.
        </p>
        <button
          type="button"
          onClick={() => void refresh()}
          className="rounded border border-border bg-surface px-4 py-2 text-sm font-medium text-ink"
        >
          Try again
        </button>
      </div>
    );
  }

  if (status === "anonymous") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <p className="text-sm text-ink-secondary">Redirecting to sign in…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <p className="text-sm text-ink-secondary">Checking your session…</p>
    </div>
  );
}
