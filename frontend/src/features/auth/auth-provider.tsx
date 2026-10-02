/**
 * Who is signed in, and the one place that knows (spec §9.1, roadmap B2).
 *
 * The session lives in an HttpOnly cookie, so there is nothing to hold: this
 * provider asks `/auth/me/` once and keeps the answer. That makes the check
 * authoritative rather than inferred, which matters because the cookie's mere
 * presence proves nothing - it can be expired, revoked, or belong to a session
 * Django has already discarded.
 *
 * The fourth state is the one worth reading twice. `unavailable` is not
 * `anonymous`: a 500 or a dead network must not be reported to the user as
 * "your session expired, please sign in", because signing in again will not fix
 * it and the message sends them somewhere useless. Only `not_authenticated` -
 * the code the API reserves for exactly that - means anonymous.
 */

"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  isNotAuthenticated,
  type AuthUser,
  type LoginInput,
  currentUser,
  login,
  logout,
} from "@/lib/api";

export type AuthStatus = "checking" | "authenticated" | "anonymous" | "unavailable";

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  /** Why the session check failed, when `status` is `unavailable`. */
  problem: string | null;
  /** Adopt a signed-in user without a second round trip. */
  signIn: (input: LoginInput) => Promise<AuthUser>;
  /** End the session and drop the user. Nothing is stored locally to clear. */
  signOut: () => Promise<void>;
  /** Re-ask `/auth/me/`, used by the retry button. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const acceptUser = useCallback((signedIn: AuthUser) => {
    setUser(signedIn);
    setProblem(null);
    setStatus("authenticated");
  }, []);

  const rejectSession = useCallback((error: unknown) => {
    setUser(null);
    if (isNotAuthenticated(error)) {
      setProblem(null);
      setStatus("anonymous");
      return;
    }
    setProblem(
      error instanceof Error
        ? error.message
        : "The session could not be checked. Try again in a moment.",
    );
    setStatus("unavailable");
  }, []);

  // State is only touched from the promise's own callbacks, never synchronously
  // in the effect body, so mounting does not render twice before the request is
  // even sent. The `cancelled` flag covers StrictMode's double-mount and an
  // unmount mid-flight, which would otherwise set state on a dead component.
  useEffect(() => {
    let cancelled = false;

    void currentUser().then(
      (signedIn) => {
        if (!cancelled) acceptUser(signedIn);
      },
      (error: unknown) => {
        if (!cancelled) rejectSession(error);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [acceptUser, rejectSession]);

  const refresh = useCallback(async () => {
    setStatus("checking");
    try {
      acceptUser(await currentUser());
    } catch (error) {
      rejectSession(error);
    }
  }, [acceptUser, rejectSession]);

  const signIn = useCallback(
    async (input: LoginInput) => {
      const signedIn = await login(input);
      acceptUser(signedIn);
      return signedIn;
    },
    [acceptUser],
  );

  const signOut = useCallback(async () => {
    await logout();
    setUser(null);
    setProblem(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, problem, signIn, signOut, refresh }),
    [status, user, problem, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Read the session.
 *
 * Throws rather than returning null when there is no provider: a component that
 * silently got `undefined` would render as signed-out and quietly show a
 * redirect loop, which is a far worse failure than a stack trace at mount.
 */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return value;
}
