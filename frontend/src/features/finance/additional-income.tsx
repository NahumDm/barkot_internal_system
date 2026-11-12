"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  listAdditionalIncome,
  createAdditionalIncome,
  updateAdditionalIncome,
  deleteAdditionalIncome,
  type AdditionalIncome,
  type AdditionalIncomeCreateInput,
  type AdditionalIncomeUpdateInput,
} from "@/lib/api/finance";
import { type ApiError } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { useT } from "@/lib/i18n/context";

export default function AdditionalIncomePage() {
  const t = useT();
  const { user } = useAuth();
  const isOwner = user?.role === "OWNER" || user?.role === "owner";

  const [records, setRecords] = useState<AdditionalIncome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<AdditionalIncomeCreateInput & { id?: number }>({
    source: "",
    amount: "",
    currency: "ETB",
    income_date: new Date().toISOString().split("T")[0],
    note: "",
    payment_method: "CASH",
  });
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showDeleteId, setShowDeleteId] = useState<number | null>(null);
  const [deleteReason, setDeleteReason] = useState("Deleted by owner");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await listAdditionalIncome();
      setRecords(res.results);
    } catch (e) {
      setError((e as ApiError).message || t("finance.loading"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isOwner) load();
  }, [isOwner]);

  function resetForm() {
    setForm({
      source: "",
      amount: "",
      currency: "ETB",
      income_date: new Date().toISOString().split("T")[0],
      note: "",
      payment_method: "CASH",
    });
    setEditingId(null);
  }

  function startEdit(r: AdditionalIncome) {
    setEditingId(r.id);
    setForm({
      id: r.id,
      source: r.source,
      amount: r.amount,
      currency: r.currency as "ETB",
      income_date: r.income_date,
      note: r.note,
      payment_method: r.payment_method as "CASH" | "MOBILE_BANKING",
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        source: form.source.trim(),
        amount: form.amount,
        currency: form.currency,
        income_date: form.income_date,
        note: form.note.trim(),
        payment_method: form.payment_method,
      };
      if (editingId !== null) {
        await updateAdditionalIncome(editingId, payload as AdditionalIncomeUpdateInput);
      } else {
        await createAdditionalIncome(payload as AdditionalIncomeCreateInput);
      }
      resetForm();
      await load();
    } catch (e) {
      setError((e as ApiError).message || t("finance.saving"));
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete(id: number) {
    setSaving(true);
    setError(null);
    try {
      await deleteAdditionalIncome(id, { void_reason: deleteReason || "Deleted by owner" });
      setShowDeleteId(null);
      await load();
    } catch (e) {
      setError((e as ApiError).message || t("finance.delete"));
    } finally {
      setSaving(false);
    }
  }

  const total = records.reduce((s, r) => s + Number(r.amount || 0), 0);

  if (!isOwner) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-bold mb-4">{t("finance.additionalIncomeTitle")}</h1>
        <p>{t("employee.noAccess")}</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold mb-2">{t("finance.additionalIncomeTitle")}</h1>
      <p className="text-sm text-neutral-500 mb-6">{t("finance.additionalIncomeSubtitle")}</p>

      <div className="border p-4 mb-6 bg-white">
        <h2 className="font-bold mb-3">{editingId !== null ? t("finance.additionalIncomeEdit") : t("finance.additionalIncomeRegister")}</h2>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">{t("finance.incomeSource")}</label>
            <input
              required
              className="w-full border px-2 py-1 text-sm"
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
              placeholder="e.g. Customer Bottle Breakage"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">{t("finance.amountEtb")}</label>
            <input
              required
              type="number"
              step="0.01"
              min="0.01"
              className="w-full border px-2 py-1 text-sm"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">{t("finance.incomeDate")}</label>
            <input
              required
              type="date"
              className="w-full border px-2 py-1 text-sm"
              value={form.income_date}
              onChange={(e) => setForm({ ...form, income_date: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">{t("finance.paymentMethod")}</label>
            <select
              className="w-full border px-2 py-1 text-sm"
              value={form.payment_method}
              onChange={(e) => setForm({ ...form, payment_method: e.target.value })}
            >
              <option value="CASH">{t("finance.cash")}</option>
              <option value="MOBILE_BANKING">{t("finance.mobileBanking")}</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="block text-xs font-semibold mb-1">{t("finance.sourceNote")}</label>
            <textarea
              required
              rows={2}
              className="w-full border px-2 py-1 text-sm"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              placeholder="Why the income was received"
            />
          </div>
          <div className="md:col-span-2 flex gap-2">
            <button type="submit" disabled={saving} className="bg-black text-white px-4 py-2 text-sm font-medium hover:bg-neutral-800">
              {saving ? t("finance.saving") : editingId !== null ? t("finance.saveCategory") : t("finance.createCategory")}
            </button>
            {editingId !== null && (
              <button type="button" onClick={resetForm} className="border px-4 py-2 text-sm">{t("finance.cancel")}</button>
            )}
          </div>
        </form>
        {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
      </div>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-bold">{t("finance.records")}</h2>
        <div className="text-sm font-semibold">{t("finance.total")}: {Number(total).toFixed(2)} ETB</div>
      </div>

      {loading ? (
        <p>{t("finance.loading")}</p>
      ) : records.length === 0 ? (
        <p className="text-sm text-neutral-500">{t("finance.noAdditionalIncomeYet")}</p>
      ) : (
        <table className="w-full text-sm border-collapse border">
          <thead className="bg-neutral-100">
            <tr>
              <th className="border px-2 py-1 text-left">{t("finance.colDate")}</th>
              <th className="border px-2 py-1 text-left">{t("finance.incomeSource")}</th>
              <th className="border px-2 py-1 text-left">{t("finance.sourceNote")}</th>
              <th className="border px-2 py-1 text-left">{t("finance.amountEtb")}</th>
              <th className="border px-2 py-1 text-left">{t("finance.paymentMethod")}</th>
              <th className="border px-2 py-1 text-left">Created by</th>
              <th className="border px-2 py-1 text-left">{t("finance.colAction")}</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} className="even:bg-neutral-50">
                <td className="border px-2 py-1">{r.income_date}</td>
                <td className="border px-2 py-1">{r.source}</td>
                <td className="border px-2 py-1">{r.note}</td>
                <td className="border px-2 py-1">{Number(r.amount).toFixed(2)} ETB</td>
                <td className="border px-2 py-1">{r.payment_method}</td>
                <td className="border px-2 py-1">{r.created_by_name || "—"}</td>
                <td className="border px-2 py-1">
                  <button onClick={() => startEdit(r)} className="underline mr-2 text-xs">{t("finance.edit")}</button>
                  <button onClick={() => { setShowDeleteId(r.id); setDeleteReason("Deleted by owner"); }} className="underline text-xs text-red-700">{t("finance.delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showDeleteId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white p-6 max-w-md w-full shadow-xl border">
            <h3 className="font-bold mb-2">{t("finance.confirmDelete")}</h3>
            <p className="text-sm mb-3">{t("finance.deleteAdditionalIncome").replace("{id}", String(showDeleteId))}</p>
            <label className="block text-xs font-semibold mb-1">{t("finance.voidReason")}</label>
            <input className="w-full border px-2 py-1 text-sm mb-3" value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowDeleteId(null)} className="border px-3 py-1 text-sm">{t("finance.cancel")}</button>
              <button onClick={() => confirmDelete(showDeleteId)} disabled={saving} className="bg-red-700 text-white px-3 py-1 text-sm">{t("finance.confirmDelete")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
