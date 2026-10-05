"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  approveStockCount,
  completeStockCount,
  createBreakage,
  createStockCount,
  createStockReceipt,
  listInventoryProducts,
  type StockCount,
} from "@/lib/api/inventory";
import type { ProductListItem } from "@/lib/api/products";
import type { ApiError } from "@/lib/api/errors";

type Mode = "receive" | "breakage" | "count";

export default function InventoryForm({ mode }: { mode: Mode }) {
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("");
  const [amount, setAmount] = useState("");
  const [supplier, setSupplier] = useState("");
  const [reason, setReason] = useState("");
  const [count, setCount] = useState<StockCount | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listInventoryProducts()
      .then((response) => {
        setProducts(response.results);
        setProduct(String(response.results[0]?.id ?? ""));
      })
      .catch((value: unknown) => setError(value as ApiError));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      if (mode === "receive") {
        await createStockReceipt({
          supplier_name: supplier,
          lines: [{ product: Number(product), quantity, unit_cost: amount, currency: "ETB" }],
        });
        setSupplier("");
        setQuantity("");
        setAmount("");
      } else if (mode === "breakage") {
        await createBreakage({ reason, lines: [{ product: Number(product), quantity }] });
        setReason("");
        setQuantity("");
      } else {
        const created = await createStockCount({ products: [Number(product)] });
        setCount(created);
      }
      setError(null);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function finishCount() {
    if (!count) return;
    setSaving(true);
    try {
      const completed = await completeStockCount(count.id, {
        items: [{ item: count.items[0].id, counted_quantity: quantity }],
      });
      setCount(completed);
      setQuantity("");
      setError(null);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function approveCount() {
    if (!count) return;
    setSaving(true);
    try {
      setCount(await approveStockCount(count.id));
      setError(null);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  }

  const title =
    mode === "receive" ? "Receive stock" : mode === "breakage" ? "Breakage & waste" : "Stock count";
  return (
    <section className="max-w-3xl space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          Inventory
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          All changes are recorded in the authoritative movement ledger.
        </p>
      </div>
      {error && (
        <p className="rounded border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error.message}
        </p>
      )}
      {!count && (
        <form onSubmit={submit} className="space-y-4 rounded border border-border bg-surface p-4">
          {mode === "receive" && (
            <label className="block text-sm text-ink">
              Supplier
              <input
                required
                value={supplier}
                onChange={(event) => setSupplier(event.target.value)}
                className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
              />
            </label>
          )}
          {mode === "breakage" && (
            <label className="block text-sm text-ink">
              Reason
              <input
                required
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
              />
            </label>
          )}
          <label className="block text-sm text-ink">
            Product
            <select
              required
              value={product}
              onChange={(event) => setProduct(event.target.value)}
              className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
            >
              {products.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.sku})
                </option>
              ))}
            </select>
          </label>
          {mode !== "count" && (
            <label className="block text-sm text-ink">
              {mode === "receive" ? "Quantity" : "Quantity wasted"}
              <input
                required
                min="0.001"
                step="0.001"
                type="number"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
              />
            </label>
          )}
          {mode === "receive" && (
            <label className="block text-sm text-ink">
              Unit cost (ETB)
              <input
                required
                min="0"
                step="0.01"
                type="number"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
              />
            </label>
          )}
          {mode === "count" && (
            <p className="rounded bg-canvas p-3 text-sm text-ink-secondary">
              Open a count to snapshot expected stock, then enter the physical quantity.
            </p>
          )}
          <button
            disabled={saving || !product}
            className="rounded bg-ink px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-50"
            type="submit"
          >
            {saving ? "Saving..." : mode === "count" ? "Open count" : "Save record"}
          </button>
        </form>
      )}
      {count && (
        <section className="space-y-4 rounded border border-border bg-surface p-4">
          <h2 className="font-semibold text-ink">
            Count #{count.id} · {count.status}
          </h2>
          <div className="grid gap-3 sm:grid-cols-3 text-sm">
            <div>
              <span className="text-ink-secondary">Product</span>
              <p className="font-medium text-ink">{count.items[0]?.product_name}</p>
            </div>
            <div>
              <span className="text-ink-secondary">Expected</span>
              <p className="font-medium text-ink">{count.items[0]?.expected_quantity}</p>
            </div>
            <div>
              <span className="text-ink-secondary">Variance</span>
              <p className="font-medium text-ink">{count.items[0]?.variance}</p>
            </div>
          </div>
          {count.status === "DRAFT" && (
            <>
              <label className="block text-sm text-ink">
                Physical quantity
                <input
                  required
                  min="0"
                  step="0.001"
                  type="number"
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                  className="mt-1 w-full rounded border border-border bg-canvas px-3 py-2"
                />
              </label>
              <button
                disabled={saving || quantity === ""}
                onClick={finishCount}
                className="rounded bg-ink px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-50"
              >
                Complete count
              </button>
            </>
          )}
          {count.status === "COMPLETED" && (
            <button
              disabled={saving}
              onClick={approveCount}
              className="rounded bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              Approve adjustment
            </button>
          )}
          {count.status === "APPROVED" && (
            <p className="text-sm text-emerald-700">Adjustment posted to the ledger.</p>
          )}
        </section>
      )}
    </section>
  );
}
