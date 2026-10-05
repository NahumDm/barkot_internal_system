"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  approveExpense,
  createExpense,
  listExpenseCategories,
  listExpenses,
  type Expense,
  type ExpenseCategory,
} from "@/lib/api/finance";
import { type ApiError } from "@/lib/api/errors";

function money(value: string, currency: string): string {
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export default function ExpenseRegister() {
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
      setCategory((current) => current || String(categoryPage.results[0]?.id ?? ""));
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
      {error && (
        <p className="rounded border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error.message}
        </p>
      )}
      <form
        onSubmit={submit}
        className="grid gap-3 rounded border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <label className="text-sm text-ink">
          Description
          <input
            required
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
          />
        </label>
        <label className="text-sm text-ink">
          Amount (ETB)
          <input
            required
            min="0.01"
            step="0.01"
            type="number"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
          />
        </label>
        <label className="text-sm text-ink">
          Category
          <select
            required
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
          >
            <option value="" disabled>
              Select category
            </option>
            {categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-ink">
          Incurred on
          <input
            required
            type="date"
            value={incurredOn}
            onChange={(event) => setIncurredOn(event.target.value)}
            className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
          />
        </label>
        <button
          disabled={saving || !category}
          type="submit"
          className="rounded bg-ink px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2 lg:col-span-4 lg:justify-self-end"
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
                <td className="px-3 py-3 text-ink-secondary">{expense.category_name}</td>
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
    </section>
  );
}
