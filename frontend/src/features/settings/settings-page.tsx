"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  createStaffUser,
  getSiteSettings,
  listRoles,
  listStaffUsers,
  updateSiteSettings,
  updateStaffUser,
  type RoleSummary,
  type SiteSettings,
  type SiteSettingsUpdateInput,
  type StaffUser,
  type StaffUserUpdateInput,
} from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { dateStamp } from "@/features/payroll/format";
import {
  EmptyNote,
  ErrorBanner,
  LoadingNote,
  PageHeader,
  StatusChip,
} from "@/features/payroll/parts";

/**
 * The settings screen (roadmap C5, spec §9.2): staff accounts, the business
 * roles catalogue and the system settings row — the Owner-only admin surface.
 *
 * Like every screen, it is a projection of what the API already decided. The
 * permissions gate below is convenience (a Manager should not be handed a form
 * the server will reject), and the backend remains the authority: each action
 * surfaces the 403/`validation_error` it gets back. There is no "delete" — the
 * backend has none, accounts are deactivated, so the audit trail never loses a
 * referent.
 */

export default function SettingsPage() {
  const { status, user } = useAuth();
  const granted = user?.permissions ?? [];
  const canManageUsers = granted.includes("accounts.manage_users");
  const canManageRoles = granted.includes("accounts.manage_roles");
  const canManageSettings = granted.includes("accounts.manage_settings");
  const allowed = canManageUsers || canManageRoles || canManageSettings;
  const checking = status === "checking";

  return (
    <section className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        blurb="Staff accounts, business roles and system configuration."
      />
      {checking ? (
        <LoadingNote label="Checking access..." />
      ) : !allowed ? (
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include account settings. Ask an owner if you need access.
        </div>
      ) : (
        <div className="space-y-6">
          {canManageUsers && <UsersSection selfId={user?.id ?? 0} />}
          {canManageRoles && <RolesSection />}
          {canManageSettings && <SystemSection />}
        </div>
      )}
    </section>
  );
}

function UsersSection({ selfId }: { selfId: number }) {
  const [users, setUsers] = useState<StaffUser[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [roles, setRoles] = useState<RoleSummary[]>([]);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [refresh, setRefresh] = useState(0);

  const [username, setUsername] = useState("");
  const [newRole, setNewRole] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<ApiError | null>(null);

  useEffect(() => {
    let active = true;
    listStaffUsers({
      query: {
        page_size: 200,
        role: roleFilter || undefined,
        active: activeFilter || undefined,
        search: search.trim() || undefined,
      },
    })
      .then((value) => {
        if (active) {
          setUsers(value.results);
          setError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setError(value as ApiError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [search, activeFilter, roleFilter, refresh]);

  useEffect(() => {
    let active = true;
    listRoles({ query: { page_size: 200 } })
      .then((value) => {
        if (active) {
          setRoles(value.results);
          setNewRole((current) => current || (value.results[0]?.code ?? ""));
        }
      })
      .catch(() => {
        if (active) setRoles([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const changeSearch = (value: string) => {
    setLoading(true);
    setSearch(value);
  };
  const changeActive = (value: string) => {
    setLoading(true);
    setActiveFilter(value);
  };
  const changeRole = (value: string) => {
    setLoading(true);
    setRoleFilter(value);
  };

  const applyUpdated = (updated: StaffUser) => {
    setUsers((current) =>
      current === null ? current : current.map((u) => (u.id === updated.id ? updated : u)),
    );
  };

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await createStaffUser({
        username,
        role: newRole,
        email: email || undefined,
        phone_number: phone || undefined,
        password: password || undefined,
      });
      setUsername("");
      setEmail("");
      setPhone("");
      setPassword("");
      setSearch("");
      setActiveFilter("");
      setRoleFilter("");
      setLoading(true);
      setRefresh((value) => value + 1);
    } catch (value) {
      setCreateError(value as ApiError);
    } finally {
      setCreating(false);
    }
  };

  const roleOptions = roles.map((role) => ({
    value: role.code,
    label: role.name,
  }));

  return (
    <section className="space-y-4">
      <div className="rounded border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">Staff accounts</h2>
        <p className="text-xs text-ink-secondary">
          Accounts who can sign in. Deactivate instead of deleting, so the audit trail keeps its
          referent.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <TextInput
            label="Search"
            value={search}
            onChange={changeSearch}
            placeholder="Name or login name"
          />
          <Select
            label="Role"
            value={roleFilter}
            onChange={changeRole}
            options={roleOptions}
            placeholder="All roles"
          />
          <Select
            label="Status"
            value={activeFilter}
            onChange={changeActive}
            options={[
              { value: "", label: "Active and inactive" },
              { value: "true", label: "Active only" },
              { value: "false", label: "Inactive only" },
            ]}
          />
        </div>
        <div className="mt-4">
          <ErrorBanner error={error} />
          {loading && <LoadingNote label="Loading staff accounts..." />}
          {!loading && users && users.length === 0 && (
            <EmptyNote>No staff accounts match.</EmptyNote>
          )}
          {!loading && users && users.length > 0 && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-ink-secondary">
                  <Th>User</Th>
                  <Th>Role</Th>
                  <Th>Contact</Th>
                  <Th>Status</Th>
                  <Th>Last login</Th>
                  <Th className="text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <UserRow
                    key={user.id}
                    user={user}
                    roles={roles}
                    isSelf={user.id === selfId}
                    onChanged={applyUpdated}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="rounded border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">Add a staff member</h2>
        <p className="text-xs text-ink-secondary">
          Pick a role from the catalogue. Leave the password blank to create a locked account.
        </p>
        <form onSubmit={submitCreate} className="mt-3 space-y-3">
          <ErrorBanner error={createError} />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <TextInput
              label="Login name"
              value={username}
              onChange={setUsername}
              placeholder="e.g. selam"
            />
            <Select
              label="Role"
              value={newRole}
              onChange={setNewRole}
              options={roleOptions}
              disabled={roles.length === 0}
              placeholder="Loading roles..."
            />
            <TextInput
              label="Email"
              value={email}
              onChange={setEmail}
              type="email"
              placeholder="Optional"
            />
            <TextInput label="Phone" value={phone} onChange={setPhone} placeholder="Optional" />
            <TextInput
              label="Temporary password"
              value={password}
              onChange={setPassword}
              type="password"
              placeholder="Leave blank to lock"
            />
          </div>
          <div className="flex justify-end">
            <ActionButton disabled={creating || roles.length === 0}>
              {creating ? "Creating..." : "Create staff account"}
            </ActionButton>
          </div>
        </form>
      </div>
    </section>
  );
}

function UserRow({
  user,
  roles,
  isSelf,
  onChanged,
}: {
  user: StaffUser;
  roles: RoleSummary[];
  isSelf: boolean;
  onChanged: (updated: StaffUser) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftRole, setDraftRole] = useState(user.role);
  const [draftEmail, setDraftEmail] = useState(user.email);
  const [draftPhone, setDraftPhone] = useState(user.phone_number);
  const [draftActive, setDraftActive] = useState(user.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const roleOptions = roles.map((role) => ({
    value: role.code,
    label: role.name,
  }));

  const openEdit = () => {
    setDraftRole(user.role);
    setDraftEmail(user.email);
    setDraftPhone(user.phone_number);
    setDraftActive(user.is_active);
    setError(null);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setError(null);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const input: StaffUserUpdateInput = {
        role: draftRole,
        email: draftEmail,
        phone_number: draftPhone,
      };
      if (!isSelf) input.is_active = draftActive;
      onChanged(await updateStaffUser(user.id, input));
      setEditing(false);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {error && (
        <tr>
          <td colSpan={6} className="py-2">
            <p className="rounded border border-danger/30 bg-danger/10 p-2 text-sm text-danger">
              {error.message}
            </p>
          </td>
        </tr>
      )}
      <tr className="border-b border-border last:border-0">
        <td className="py-2 pr-3">
          <p className="font-medium text-ink">
            {user.display_name}
            {isSelf && <span className="text-ink-secondary"> (you)</span>}
          </p>
          <p className="text-xs text-ink-secondary">{user.username}</p>
          {user.is_temporary_password && (
            <p className="text-xs text-ink-secondary">Temporary password — reset on sign-in</p>
          )}
        </td>
        <td className="py-2 pr-3">
          {editing ? (
            <Select
              label="Role"
              value={draftRole}
              onChange={setDraftRole}
              options={roleOptions}
              disabled={isSelf || saving}
            />
          ) : (
            <span className="text-ink">{user.role_name}</span>
          )}
        </td>
        <td className="py-2 pr-3">
          {editing ? (
            <div className="space-y-2">
              <TextInput label="Email" value={draftEmail} onChange={setDraftEmail} type="email" />
              <TextInput label="Phone" value={draftPhone} onChange={setDraftPhone} />
            </div>
          ) : (
            <span className="text-ink-secondary">
              {user.email || "—"}
              {user.phone_number ? ` · ${user.phone_number}` : ""}
            </span>
          )}
        </td>
        <td className="py-2 pr-3">
          {editing ? (
            <label className="flex flex-col gap-1 text-xs font-medium text-ink-secondary">
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draftActive}
                  disabled={isSelf || saving}
                  onChange={(event) => setDraftActive(event.target.checked)}
                  className="accent-ink"
                />
                Active
              </span>
              {isSelf && <span>Your own status cannot be changed here.</span>}
            </label>
          ) : (
            <StatusChip
              status={user.is_active ? "ACTIVE" : "INACTIVE"}
              display={user.is_active ? "Active" : "Inactive"}
            />
          )}
        </td>
        <td className="py-2 pr-3 text-ink-secondary">
          {user.last_login ? dateStamp(user.last_login) : "Never"}
        </td>
        <td className="py-2 text-right">
          {editing ? (
            <div className="flex justify-end gap-2">
              <ActionButton onClick={cancelEdit} disabled={saving} secondary>
                Cancel
              </ActionButton>
              <ActionButton onClick={save} disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </ActionButton>
            </div>
          ) : (
            <ActionButton onClick={openEdit} secondary>
              Edit
            </ActionButton>
          )}
        </td>
      </tr>
    </>
  );
}

function RolesSection() {
  const [roles, setRoles] = useState<RoleSummary[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listRoles({ query: { page_size: 200 } })
      .then((value) => {
        if (active) {
          setRoles(value.results);
          setError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setError(value as ApiError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="space-y-4 rounded border border-border bg-surface p-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">Roles</h2>
        <p className="text-xs text-ink-secondary">
          The fixed business-role catalogue (spec §9.2) and what each role may do.
        </p>
      </div>
      <ErrorBanner error={error} />
      {loading && <LoadingNote label="Loading roles..." />}
      {roles && !loading && roles.length === 0 && <EmptyNote>No roles found.</EmptyNote>}
      {roles && !loading && roles.length > 0 && (
        <div className="space-y-3">
          {roles.map((role) => (
            <article key={role.code} className="rounded border border-border bg-canvas p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-ink">{role.name}</p>
                  <p className="text-xs text-ink-secondary">{role.description}</p>
                </div>
                <span className="rounded border border-border px-2 py-1 text-xs font-semibold text-ink-secondary">
                  {role.code}
                </span>
              </div>
              {role.permissions.length === 0 ? (
                <p className="mt-2 text-xs text-ink-secondary">No permissions granted.</p>
              ) : (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {role.permissions.map((permission) => (
                    <li
                      key={permission}
                      className="rounded bg-surface px-2 py-1 text-xs text-ink-secondary"
                    >
                      {permission}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function SystemSection() {
  const [settings, setSettings] = useState<SiteSettings | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    getSiteSettings()
      .then((value) => {
        if (active) {
          setSettings(value);
          setError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setError(value as ApiError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const onSaved = (updated: SiteSettings) => {
    setSettings(updated);
    setSaved(true);
  };

  return (
    <section className="space-y-4 rounded border border-border bg-surface p-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">System</h2>
        <p className="text-xs text-ink-secondary">
          Session and password policy applied across every staff account.
        </p>
      </div>
      <ErrorBanner error={error} />
      {saved && <p className="text-sm text-success">Saved.</p>}
      {loading && <LoadingNote label="Loading system settings..." />}
      {settings && !loading && (
        <SystemForm key={settings.updated_at} settings={settings} onSaved={onSaved} />
      )}
    </section>
  );
}

function SystemForm({
  settings,
  onSaved,
}: {
  settings: SiteSettings;
  onSaved: (value: SiteSettings) => void;
}) {
  const [sessionTimeout, setSessionTimeout] = useState(String(settings.session_timeout_minutes));
  const [maxAge, setMaxAge] = useState(String(settings.password_max_age_days));
  const [forceChange, setForceChange] = useState(settings.require_password_change_for_new_users);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const input: SiteSettingsUpdateInput = {
        session_timeout_minutes: Number(sessionTimeout),
        password_max_age_days: Number(maxAge),
        require_password_change_for_new_users: forceChange,
      };
      onSaved(await updateSiteSettings(input));
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBanner error={error} />
      <div className="grid gap-3 sm:grid-cols-2">
        <NumberInput
          label="Session timeout (minutes)"
          value={sessionTimeout}
          min={1}
          onChange={setSessionTimeout}
        />
        <NumberInput label="Password max age (days)" value={maxAge} min={0} onChange={setMaxAge} />
      </div>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          checked={forceChange}
          onChange={(event) => setForceChange(event.target.checked)}
          className="accent-ink"
        />
        Require new users to change their temporary password on first sign-in
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-ink-secondary">
          {settings.updated_by
            ? `Last changed by ${settings.updated_by} on ${dateStamp(settings.updated_at)}.`
            : "Never modified."}
        </p>
        <ActionButton disabled={saving}>{saving ? "Saving..." : "Save settings"}</ActionButton>
      </div>
    </form>
  );
}

function TextInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "email" | "password";
}) {
  return (
    <label className="text-xs font-medium text-ink-secondary">
      {label}
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-full rounded border border-border bg-canvas px-2 py-1.5 text-sm text-ink"
      />
    </label>
  );
}

function NumberInput({
  label,
  value,
  min,
  onChange,
}: {
  label: string;
  value: string;
  min: number;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-xs font-medium text-ink-secondary">
      {label}
      <input
        type="number"
        min={min}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-full rounded border border-border bg-canvas px-2 py-1.5 text-sm text-ink"
      />
    </label>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  disabled,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="text-xs font-medium text-ink-secondary">
      {label}
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-full rounded border border-border bg-canvas px-2 py-1.5 text-sm text-ink disabled:opacity-50"
      >
        {placeholder !== undefined && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  secondary,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  return (
    <button
      type={onClick ? "button" : "submit"}
      onClick={onClick}
      disabled={disabled}
      className={
        secondary
          ? "rounded border border-border bg-canvas px-3 py-1.5 text-sm font-medium text-ink hover:text-ink-secondary disabled:opacity-50"
          : "rounded bg-brand px-3 py-1.5 text-sm font-medium text-canvas disabled:opacity-50"
      }
    >
      {children}
    </button>
  );
}

function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <th className={`py-1.5 pr-3 font-medium ${className}`}>{children}</th>;
}
