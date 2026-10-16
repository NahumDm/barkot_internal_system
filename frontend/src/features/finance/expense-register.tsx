"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  approveExpense,
  archiveExpenseCategory,
  createExpense,
  createExpenseCategory,
  listExpenseCategories,
  listExpenses,
  updateExpenseCategory,
  type Expense,
  type ExpenseCategory,
} from "@/lib/api/finance";
import { type ApiError } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";

function money(value: string, currency: string): string {
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function CategoryManager({
  categories,
  onChanged,
  onError,
  canManage,
}: {
  categories: ExpenseCategory[];
  onChanged: () => Promise<void>;
  onError: (error: ApiError | null) => void;
  canManage?: boolean;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const startEdit = (category: ExpenseCategory) => {
    setEditingId(category.id);
    setCreating(false);
    setName(category.name);
    setDescription(category.description);
  };

  const startCreate = () => {
    setCreating(true);
    setEditingId(null);
    setName("");
    setDescription("");
  };

  const cancel = () => {
    setEditingId(null);
    setCreating(false);
    setName("");
    setDescription("");
  };

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingId === null || saving) return;
    setSaving(true);
    try {
      await updateExpenseCategory(editingId, { name, description });
      await onChanged();
      cancel();
      onError(null);
    } catch (value) {
      onError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function saveCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!creating || saving) return;
    setSaving(true);
    try {
      await createExpenseCategory({ name, description });
      await onChanged();
      cancel();
      onError(null);
    } catch (value) {
      onError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(category: ExpenseCategory) {
    if (
      category.is_active &&
      !confirm(
        `Delete the category "${category.name}"? It will no longer appear on new expenses, but past expenses keep it. You can restore it later.`,
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      if (category.is_active) {
        await archiveExpenseCategory(category.id);
      } else {
        await updateExpenseCategory(category.id, { is_active: true });
      }
      await onChanged();
      onError(null);
    } catch (value) {
      onError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded border border-border bg-surface p-4">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 className="text-lg font-semibold text-ink">Expense categories</h2>
        {canManage && (
          <div className="flex items-center gap-3">
            <p className="text-sm text-ink-secondary">
              Create, edit, or delete categories. Deleting hides them from new expenses.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={startCreate}
              disabled={saving || creating}
            >
              Add category
            </button>
          </div>
        )}
      </div>
      {!canManage && (
        <p className="mt-2 text-sm text-ink-secondary">
          You don’t have permission to manage expense categories.
        </p>
      )}
      <ul className="mt-3 divide-y divide-border">
        {canManage && creating && (
          <li className="py-3">
            <form onSubmit={saveCreate} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <label className="field-label flex-1">
                Name
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  className="control mt-1.5"
                />
              </label>
              <label className="field-label flex-1">
                Description
                <input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  className="control mt-1.5"
                />
              </label>
              <div className="form-actions">
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? "Saving..." : "Create"}
                </button>
                <button type="button" className="btn btn-ghost" onClick={cancel} disabled={saving}>
                  Cancel
                </button>
              </div>
            </form>
          </li>
        )}
        {categories.map((category) =>
          canManage && editingId === category.id ? (
            <li key={category.id} className="py-3">
              <form onSubmit={saveEdit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="field-label flex-1">
                  Name
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    required
                    className="control mt-1.5"
                  />
                </label>
                <label className="field-label flex-1">
                  Description
                  <input
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    className="control mt-1.5"
                  />
                </label>
                <div className="form-actions">
                  <button type="submit" className="btn btn-primary" disabled={saving}>
                    {saving ? "Saving..." : "Save"}
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={cancel} disabled={saving}>
                    Cancel
                  </button>
                </div>
              </form>
            </li>
          ) : (
            <li
              key={category.id}
              className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="font-medium text-ink">
                  {category.name}
                  {!category.is_active && (
                    <span className="ml-2 rounded bg-canvas px-2 py-0.5 text-xs font-semibold text-ink-secondary">
                      Deleted
                    </span>
                  )}
                </p>
                {category.description && (
                  <p className="text-sm text-ink-secondary">{category.description}</p>
                )}
              </div>
              {canManage && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => startEdit(category)}
                    disabled={saving}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => toggleActive(category)}
                    disabled={saving}
                  >
                    {category.is_active ? "Delete" : "Restore"}
                  </button>
                </div>
              )}
            </li>
          ),
        )}
      </ul>
      {canManage && categories.length === 0 && !creating && (
        <p className="mt-3 text-sm text-ink-secondary">No categories yet. Add the first one above.</p>
      )}
      {!canManage && categories.length === 0 && (
        <p className="mt-3 text-sm text-ink-secondary">No categories yet.</p>
      )}
    </section>
  );
}

export default function ExpenseRegister() {
  const { user } = useAuth();
  const canManageCategories = user?.permissions?.includes("finance.manage_expense_categories") ?? false;

  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [incurredOn, setIncurredOn] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = () =>
    Promise.all([listExpenseCategories(), listExpenses()]).then(([categoryPage, expensePage]) => {
      setCategories(categoryPage.results);
      setExpenses(expensePage.results);
      setCategory((current) => {
        if (current && categoryPage.results.some((item) => String(item.id) === current)) {
          return current;
        }
        return String(categoryPage.results.find((item) => item.is_active)?.id ?? "");
      });
    });

  useEffect(() => {
    refresh().catch((value: unknown) => setError(value as ApiError));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await createExpense({
        category: Number(category),
        description,
        amount,
        currency: "ETB",
        incurred_on: incurredOn,
      });
      setDescription("");
      setAmount("");
      setError(null);
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function approve(id: number) {
    try {
      await approveExpense(id);
      await refresh();
    } catch (value) {
      setError(value as ApiError);
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Finance</p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Expenses</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          Record expenses, then approve them before they affect the balance.
        </p>
      </div>
      {error && <p className="form-error">{error.message}</p>}
      <form
        onSubmit={submit}
        className="grid gap-3 rounded border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <label className="field-label">
          Description
          <input
            required
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          Amount (ETB)
          <input
            required
            min="0.01"
            step="0.01"
            type="number"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="control mt-1.5"
          />
        </label>
        <label className="field-label">
          Category
          <select
            required
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="control mt-1.5"
          >
            <option value="" disabled>
              Select category
            </option>
            {categories
              .filter((item) => item.is_active)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
        <label className="field-label">
          Incurred on
          <input
            required
            type="date"
            value={incurredOn}
            onChange={(event) => setIncurredOn(event.target.value)}
            className="control mt-1.5"
          />
        </label>
        <button
          disabled={saving || !category}
          type="submit"
          className="btn btn-primary sm:col-span-2 lg:col-span-4 lg:justify-self-end"
        >
          {saving ? "Saving..." : "Record expense"}
        </button>
      </form>
      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">Date</th>
              <th className="px-3 py-3">Description</th>
              <th className="px-3 py-3">Category</th>
              <th className="px-3 py-3">Amount</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {expenses.map((expense) => (
              <tr key={expense.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3">{expense.incurred_on}</td>
                <td className="px-3 py-3 font-medium text-ink">{expense.description}</td>
                <td className="px-3 py-3 text-ink-secondary">
                  {expense.category_name ||
                    categories.find((item) => item.id === expense.category)?.name ||
                    "Uncategorized"}
                </td>
                <td className="px-3 py-3">{money(expense.amount, expense.currency)}</td>
                <td className="px-3 py-3">
                  <span className="rounded bg-canvas px-2 py-1 text-xs font-semibold">
                    {expense.status_display}
                  </span>
                </td>
                <td className="px-3 py-3">
                  {expense.status === "RECORDED" && (
                    <button
                      onClick={() => approve(expense.id)}
                      className="text-sm font-semibold text-blue-700 hover:underline"
                    >
                      Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {expenses.length === 0 && (
          <p className="p-6 text-center text-sm text-ink-secondary">No expenses recorded.</p>
        )}
      </div>
      <CategoryManager categories={categories} onChanged={refresh} onError={setError} canManage={canManageCategories} />
    </section>
  );
}
