/**
 * Set a new password (spec §9.3, roadmap B3).
 *
 * Two audiences. A user on a temporary password arrives here from sign-in or
 * from the guard, and the API will refuse every other endpoint until they leave.
 * Anyone else may use it voluntarily, which is why it sits in the public group
 * and renders without the application shell — a user who cannot use the
 * application must not be able to be blocked by it.
 *
 * On success the API returns the refreshed user with `is_temporary_password`
 * cleared, and the session stays signed in: the backend rotates the session key
 * but keeps it valid, and the CSRF token is unaffected. So the returned user is
 * adopted directly rather than re-fetched — and adopting it is what stops the
 * guard from bouncing the user straight back here.
 */

"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { Field, FormError, FormShell } from "@/features/auth/form-parts";
import { type ApiError, changePassword } from "@/lib/api";

export default function ChangePasswordPage() {
  const { adoptUser, user } = useAuth();
  const router = useRouter();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const forced = user?.is_temporary_password === true;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setError(null);
    try {
      const updated = await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirm: confirmation,
      });
      adoptUser(updated);
      router.replace("/dashboard");
    } catch (caught) {
      setError(caught as ApiError);
      setBusy(false);
    }
  }

  const fieldErrors = error?.details ?? {};

  return (
    <FormShell
      title="Set a new password"
      subtitle={
        forced
          ? "Your password was set by somebody else. Choose your own to continue."
          : "Choose a new password for your account."
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <FormError error={error} />
        <Field
          label="Current password"
          type="password"
          value={currentPassword}
          onChange={setCurrentPassword}
          errors={fieldErrors["current_password"] ?? []}
          autoComplete="current-password"
          autoFocus
          disabled={busy}
        />
        <Field
          label="New password"
          type="password"
          value={newPassword}
          onChange={setNewPassword}
          errors={fieldErrors["new_password"] ?? []}
          autoComplete="new-password"
          disabled={busy}
        />
        <Field
          label="Confirm new password"
          type="password"
          value={confirmation}
          onChange={setConfirmation}
          errors={fieldErrors["new_password_confirm"] ?? []}
          autoComplete="new-password"
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-brand px-4 py-2 text-sm font-medium text-ivory transition-colors hover:bg-brand-hover disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          {busy ? "Saving…" : "Set password"}
        </button>
      </form>
    </FormShell>
  );
}
