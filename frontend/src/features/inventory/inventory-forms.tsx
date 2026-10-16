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
import { crateLabel, crateSize } from "@/lib/crates";

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
          lines: [
            {
              product: Number(product),
              quantity: crate ? cratesToBottles(quantity) : quantity,
              unit_cost: crate ? crateCostToBottleCost(amount) : amount,
              currency: "ETB",
            },
          ],
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
  const selectedProduct = products.find((item) => String(item.id) === product);
  const wholeUnits = selectedProduct?.quantity_mode === "WHOLE";
  const crate = crateSize(selectedProduct);

  /**
   * The receiving screen counts in crates (that is how the delivery arrives),
   * but the ledger is kept in bottles. Breakage and counts stay in bottles
   * because that is what the bar actually handles and counts at the shelf.
   */
  function cratesToBottles(raw: string): string {
    if (!crate) return raw;
    const crates = Number(raw);
    return Number.isFinite(crates) ? String(crates * crate) : raw;
  }

  /** Crate cost → per-bottle cost so stock valuation matches the ledger unit. */
  function crateCostToBottleCost(raw: string): string {
    if (!crate) return raw;
    const cost = Number(raw);
    return Number.isFinite(cost) ? (cost / crate).toFixed(2) : raw;
  }

  const typedQuantity = Number(quantity);
  const hasTypedQuantity = quantity.trim() !== "" && Number.isFinite(typedQuantity);
  const quantityHint = crate
    ? `1 crate = ${crate} bottles${
        hasTypedQuantity
          ? mode === "receive"
            ? ` · = ${typedQuantity * crate} bottles`
            : ` · = ${crateLabel(typedQuantity, crate)}`
          : ""
      }`
    : wholeUnits
      ? `Whole units only (${selectedProduct?.unit ?? "units"}).`
      : "Decimals allowed.";

  const quantityLabel =
    mode === "receive"
      ? crate
        ? "Quantity (crates)"
        : "Quantity"
      : crate
        ? "Quantity wasted (bottles)"
        : "Quantity wasted";

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
      {error && <p className="form-error">{error.message}</p>}
      {!count && (
        <form onSubmit={submit} className="space-y-4 rounded border border-border bg-surface p-4">
          {mode === "receive" && (
            <label className="field-label">
              Supplier
              <input
                required
                value={supplier}
                onChange={(event) => setSupplier(event.target.value)}
                className="control mt-1.5"
              />
            </label>
          )}
          {mode === "breakage" && (
            <label className="field-label">
              Reason
              <input
                required
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="control mt-1.5"
              />
            </label>
          )}
          <label className="field-label">
            Product
            <select
              required
              value={product}
              onChange={(event) => setProduct(event.target.value)}
              className="control mt-1.5"
            >
              {products.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.sku})
                </option>
              ))}
            </select>
          </label>
          {mode !== "count" && (
            <label className="field-label">
              {quantityLabel}
              <input
                required
                min={wholeUnits ? "1" : "0.001"}
                step={wholeUnits ? "1" : "0.001"}
                inputMode={wholeUnits ? "numeric" : "decimal"}
                type="number"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="control mt-1.5"
              />
              <span className="field-hint">{quantityHint}</span>
            </label>
          )}
          {mode === "receive" && (
            <label className="field-label">
              {crate ? "Price per crate (ETB)" : "Unit price (ETB)"}
              <input
                required
                min="0"
                step="0.01"
                type="number"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                className="control mt-1.5"
              />
              <span className="field-hint">
                {crate
                  ? `Price paid to the supplier for one crate of ${crate} bottles.`
                  : `Price paid to the supplier for one ${selectedProduct?.unit ?? "unit"}.`}
              </span>
            </label>
          )}
          {mode === "count" && (
            <p className="rounded bg-canvas p-3 text-sm text-ink-secondary">
              Open a count to snapshot expected stock, then enter the physical quantity.
            </p>
          )}
          <div className="form-actions">
            <button disabled={saving || !product} className="btn btn-primary" type="submit">
              {saving ? "Saving..." : mode === "count" ? "Open count" : "Save record"}
            </button>
          </div>
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
              <p className="font-medium text-ink">
                {crate
                  ? `${crateLabel(Number(count.items[0]?.expected_quantity ?? 0), crate)}`
                  : count.items[0]?.expected_quantity}
              </p>
            </div>
            <div>
              <span className="text-ink-secondary">Variance</span>
              <p className="font-medium text-ink">
                {count.items[0]?.variance}
                {crate ? " bottles" : ""}
              </p>
            </div>
          </div>
          {count.status === "DRAFT" && (
            <div className="flex flex-col gap-4">
              <label className="field-label">
                {crate ? "Physical quantity (bottles)" : "Physical quantity"}
                <input
                  required
                  min={wholeUnits ? "1" : "0.001"}
                  step={wholeUnits ? "1" : "0.001"}
                  inputMode={wholeUnits ? "numeric" : "decimal"}
                  type="number"
                  value={quantity}
                  onChange={(event) => setQuantity(event.target.value)}
                  className="control mt-1.5"
                />
                <span className="field-hint">{quantityHint}</span>
              </label>
              <button
                disabled={saving || quantity === ""}
                onClick={finishCount}
                className="btn btn-primary self-start"
              >
                Complete count
              </button>
            </div>
          )}
          {count.status === "COMPLETED" && (
            <button
              disabled={saving}
              onClick={approveCount}
              className="btn bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50"
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
