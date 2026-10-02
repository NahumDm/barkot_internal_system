/**
 * Typed wrappers for the session endpoints (spec §9.1, roadmap B1).
 *
 * These return the unwrapped `user` rather than the `{ user: ... }` envelope so
 * callers hold the one thing they asked for. Login deliberately returns the
 * user instead of making the caller follow up with `/auth/me/`: the role and
 * permissions are needed immediately to decide what to render, and login is the
 * one request where the user is guaranteed to be waiting.
 */

import { get, post } from "./client";

/** Who is signed in, and what the UI may offer them. */
export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  /** The role's code, e.g. `owner`. Stable; use this for comparisons. */
  role: string;
  role_name: string;
  /** Effective permission codenames. Presentation only - the server re-checks. */
  permissions: string[];
  email: string;
  phone_number: string;
  is_temporary_password: boolean;
  last_login: string | null;
}

export interface LoginInput {
  username: string;
  password: string;
}

export interface ChangePasswordInput {
  current_password: string;
  new_password: string;
  new_password_confirm: string;
}

interface UserEnvelope {
  user: AuthUser;
}

export async function login(input: LoginInput): Promise<AuthUser> {
  const { user } = await post<UserEnvelope>("/auth/login/", input);
  return user;
}

/** Ends the session server-side. The client holds nothing to clear. */
export async function logout(): Promise<void> {
  await post<void>("/auth/logout/");
}

/** The current session's user, or an `ApiError` with `not_authenticated`. */
export async function currentUser(): Promise<AuthUser> {
  const { user } = await get<UserEnvelope>("/auth/me/");
  return user;
}

export async function changePassword(input: ChangePasswordInput): Promise<AuthUser> {
  const { user } = await post<UserEnvelope>("/auth/change-password/", input);
  return user;
}
