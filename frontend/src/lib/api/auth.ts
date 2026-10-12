/**
 * Typed wrappers for the session endpoints (spec §9.1, roadmap B1).
 *
 * These return the unwrapped `user` rather than the `{ user: ... }` envelope so
 * callers hold the one thing they asked for. Login deliberately returns the
 * user instead of making the caller follow up with `/auth/me/`: the role and
 * permissions are needed immediately to decide what to render, and login is the
 * one request where the user is guaranteed to be waiting.
 */

import { get, post, type RequestOptions } from "./client";

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

/**
 * Ends the session server-side. The client holds nothing to clear.
 *
 * Accepts request options so logout participates in the session check's timeout
 * and abort strategy: a logout that hangs must surface as an error the menu can
 * show, never as a frozen menu with no way to retry.
 */
export async function logout(options: RequestOptions = {}): Promise<void> {
  await post<void>("/auth/logout/", undefined, options);
}

/**
 * The current session's user, or an `ApiError` with `not_authenticated`.
 *
 * Options let the auth provider bound this check with a deadline and cancel it
 * when it unmounts; without those the first-load guard has nothing to show
 * while a stalled request keeps it on "Checking your session…".
 */
export async function currentUser(options: RequestOptions = {}): Promise<AuthUser> {
  const { user } = await get<UserEnvelope>("/auth/me/", options);
  return user;
}

export async function changePassword(input: ChangePasswordInput): Promise<AuthUser> {
  const { user } = await post<UserEnvelope>("/auth/change-password/", input);
  return user;
}
