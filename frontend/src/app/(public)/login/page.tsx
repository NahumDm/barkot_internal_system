/**
 * The sign-in screen (spec §9.1, roadmap B3).
 *
 * A user on a temporary password is sent straight to `/change-password` rather
 * than to wherever they were going. The API refuses every other endpoint with
 * `password_change_required`, so letting them through would mean a dashboard
 * where every action fails for a reason the UI cannot explain.
 *
 * `useSearchParams` needs a Suspense boundary because this route is prerendered
 * and the query string is not known at build time. The form is therefore the
 * inner component, and the fallback is a static shell rather than a spinner -
 * a blank frame where the sign-in box belongs looks broken on a slow connection.
 */

"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { Field, FormError, FormShell } from "@/features/auth/form-parts";
import { safeNextPath } from "@/features/auth/next-path";
import { type ApiError } from "@/lib/api";

function SignInForm() {
  const { signIn } = useAuth();
  const router = useRouter();
  const requested = useSearchParams().get("next");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setError(null);
    try {
      const user = await signIn({ username, password });
      const destination = user.is_temporary_password ? "/change-password" : safeNextPath(requested);
      router.replace(destination);
    } catch (caught) {
      setError(caught as ApiError);
      setBusy(false);
    }
  }

  const fieldErrors = error?.details ?? {};

  return (
    <FormShell title="Sign in" subtitle="Barkot Bar & Restaurant">
      <form onSubmit={onSubmit} className="auth-form">
        <FormError error={error} variant="auth" />
        <Field
          label="Username"
          type="text"
          value={username}
          onChange={setUsername}
          errors={fieldErrors["username"] ?? []}
          autoComplete="username"
          placeholder="Enter your username"
          autoFocus
          disabled={busy}
          variant="auth"
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          errors={fieldErrors["password"] ?? []}
          autoComplete="current-password"
          placeholder="Enter your password"
          revealable
          disabled={busy}
          variant="auth"
        />
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </FormShell>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<FormShell title="Sign in" subtitle="Barkot Bar & Restaurant" />}>
      <SignInForm />
    </Suspense>
  );
}
