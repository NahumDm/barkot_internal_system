/**
 * The shared account menu in the top-right of the application shell (UX §3.1).
 *
 * One menu for Owner, Manager, Cashier and Barman alike: it is the same code for
 * every role because the menu itself is role-independent. What a role can reach
 * inside the application is the sidebar's job, decided by the permissions the
 * API reports - not by this component.
 *
 * Three items. "My Profile" shows only the fields `/auth/me/` already returns,
 * so the profile view cannot drift from what the server knows and no new
 * endpoint or schema is invented to feed it. "Change Password" is a link into
 * the existing password-change workflow (spec §9.3). "Log Out" POSTs to
 * `/auth/logout/` with the CSRF token, and only navigates to the sign-in screen
 * after the server confirms the session is gone - a failed logout surfaces as
 * an in-menu error rather than as a fake client-side sign-out.
 *
 * Accessibility is deliberate: the trigger is a disclosure button
 * (`aria-haspopup`/`aria-expanded`), the panel is a `role="menu"`, items are
 * `role="menuitem"` and reachable by arrow keys, Escape closes without leaving
 * the page, and the profile panel is a modal dialog that traps focus on the
 * close button and returns it to the trigger when dismissed.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, KeyRound, LogOut, User as UserIcon, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { useT } from "@/lib/i18n/context";
import { ApiError, isSessionEnded } from "@/lib/api";

function describeLogoutError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Signing out failed. Check your connection and try again.";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function AccountMenu() {
  const { user, signOut } = useAuth();
  const t = useT();
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const menuId = useId();
  const profileTitleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const profileCloseRef = useRef<HTMLButtonElement>(null);

  function closeMenu() {
    setOpen(false);
    setLogoutError(null);
  }

  async function handleLogout() {
    if (busy) return;
    setBusy(true);
    setLogoutError(null);
    try {
      await signOut();
    } catch (caught) {
      if (!isSessionEnded(caught)) {
        // The server is reachable and the session is still ours: say so and
        // stay signed in. Signing out "optimistically" in the browser while the
        // server keeps the session alive is exactly the failure this guard is
        // for - the user would be redirected, then silently signed back in.
        setLogoutError(describeLogoutError(caught));
        setBusy(false);
        return;
      }
      // The server answered that there is no session to end (it already
      // expired, or was flushed elsewhere). The login screen is the honest
      // destination; the provider re-checks `/auth/me/` on the next protected
      // visit and settles into whichever state the server actually is in.
    }
    router.replace("/login");
  }

  // Close on a click outside, or Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: globalThis.MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
      setLogoutError(null);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // Focus the first item when the menu opens, so keyboard users are inside it.
  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [open]);

  // Modal profile dialog: focus the close button while open, return focus to
  // the trigger when dismissed, Escape closes.
  useEffect(() => {
    if (!profileOpen) return;
    // Captured now, not read in the cleanup: the ref's current node could have
    // moved on by then, and the focus this returns should go to the trigger the
    // dialog was opened from.
    const trigger = triggerRef.current;
    profileCloseRef.current?.focus();
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setProfileOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      trigger?.focus();
    };
  }, [profileOpen]);

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu();
      triggerRef.current?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[(current + step + items.length) % items.length]?.focus();
  }

  function openProfile() {
    closeMenu();
    setProfileOpen(true);
  }

  // The guard renders nothing until a user is known, but the component must not
  // assume it. This check sits after the hooks, not before them: an early return
  // above them would change the hook order between the unauthenticated and
  // authenticated renders and crash React.
  if (!user) return null;

  return (
    <div className="account-menu">
      <button
        ref={triggerRef}
        type="button"
        id={menuId}
        className="account-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? `${menuId}-menu` : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="account-menu-avatar" aria-hidden="true">
          {initials(user.display_name || user.username)}
        </span>
        <span className="account-menu-identity">
          <span className="account-menu-name">{user.display_name || user.username}</span>
          <span className="account-menu-role">{user.role_name || user.role}</span>
        </span>
        <ChevronDown className="account-menu-chevron" aria-hidden="true" />
      </button>

      {open ? (
        <div
          ref={menuRef}
          id={`${menuId}-menu`}
          role="menu"
          aria-labelledby={menuId}
          className="account-menu-panel"
          onKeyDown={onMenuKeyDown}
        >
          <button type="button" role="menuitem" className="account-menu-item" onClick={openProfile}>
            <UserIcon aria-hidden="true" />
            {t("account.myProfile")}
          </button>
          <Link
            role="menuitem"
            href="/change-password"
            className="account-menu-item"
            onClick={closeMenu}
          >
            <KeyRound aria-hidden="true" />
            {t("account.changePassword")}
          </Link>
          <button
            type="button"
            role="menuitem"
            className="account-menu-item"
            disabled={busy}
            onClick={() => void handleLogout()}
          >
            <LogOut aria-hidden="true" />
            {busy ? t("account.signingOut") : t("account.logOut")}
          </button>
          {logoutError ? (
            <p role="alert" className="account-menu-error">
              {logoutError}
            </p>
          ) : null}
        </div>
      ) : null}

      {profileOpen ? (
        <div className="account-dialog-backdrop" onClick={() => setProfileOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={profileTitleId}
            className="account-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="account-dialog-head">
              <h2 id={profileTitleId}>{t("account.myProfile")}</h2>
              <button
                ref={profileCloseRef}
                type="button"
                aria-label="Close profile"
                className="account-dialog-close"
                onClick={() => setProfileOpen(false)}
              >
                <X aria-hidden="true" />
              </button>
            </div>
            <dl className="account-dialog-list">
              <div>
                <dt>Name</dt>
                <dd>{user.display_name || "—"}</dd>
              </div>
              <div>
                <dt>Username</dt>
                <dd>{user.username}</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>{user.role_name || user.role}</dd>
              </div>
              <div>
                <dt>Email</dt>
                <dd>{user.email || "—"}</dd>
              </div>
              <div>
                <dt>Phone</dt>
                <dd>{user.phone_number || "—"}</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </div>
  );
}
