"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  approveStockCount,
  completeStockCount,
  createBreakage,
  createGroupedStockReceipt,
  createStockCount,
  createStockReceipt,
  listInventoryProducts,
  listPriceGroups,
  type PriceGroup,
  type StockCount,
} from "@/lib/api/inventory";
import type { ProductListItem } from "@/lib/api/products";
import type { ApiError } from "@/lib/api/errors";
import { crateLabel, crateSize } from "@/lib/crates";
import { useAuth } from "@/features/auth/auth-provider";

type Mode = "receive" | "breakage" | "count";
type ReceiveSubMode = "standard" | "grouped";

interface GroupedRow {
  product_id: string;
  crates: string;
  crate_cost: string;
}

/** A product can only join a grouped crate receipt when it has a crate size. */
function isCrated(product: ProductListItem): boolean {
  return product.bottles_per_crate !== null && product.bottles_per_crate > 1;
}

/** Show the backend's field-level message when it has one. */
function describeError(error: ApiError): string {
  const details = error.details ? Object.values(error.details).flat() : [];
  return details[0] ?? error.message;
}

const REQUIRED_PERMISSION: Record<Mode, string> = {
  receive: "inventory.receive_stock",
  breakage: "inventory.record_breakage",
  count: "inventory.complete_stock_count",
};

export default function InventoryForm({ mode }: { mode: Mode }) {
  const { status, user } = useAuth();
  const granted = user?.permissions ?? [];
  const allowed = granted.includes(REQUIRED_PERMISSION[mode]);
  const canApprove = granted.includes("inventory.approve_adjustment");
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [priceGroups, setPriceGroups] = useState<PriceGroup[]>([]);
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("");
  const [amount, setAmount] = useState("");
  const [supplier, setSupplier] = useState("");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [count, setCount] = useState<StockCount | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Reused across retries of the same receipt, rotated after a successful save.
  // That is what lets the backend collapse a double-click into one movement.
  const receiptKey = useRef<string | null>(null);

  // Receiving mode: Standard vs Grouped
  const [receiveMode, setReceiveMode] = useState<ReceiveSubMode>("standard");
  const [selectedPriceGroup, setSelectedPriceGroup] = useState<string>("");
  const [groupedRows, setGroupedRows] = useState<GroupedRow[]>([
    { product_id: "", crates: "", crate_cost: "" },
  ]);

  // Stock count multi-product inputs: { [countItemId: number]: string }
  const [physicalCounts, setPhysicalCounts] = useState<Record<number, string>>({});
  const [countSelectionMode, setCountSelectionMode] = useState<"single" | "group">("single");
  const [countPriceGroup, setCountPriceGroup] = useState<string>("");

  useEffect(() => {
    Promise.all([listInventoryProducts(), listPriceGroups()])
      .then(([productsRes, groupsRes]) => {
        setProducts(productsRes.results);
        setPriceGroups(groupsRes);
        if (productsRes.results.length > 0) {
          setProduct(String(productsRes.results[0].id));
        }
        if (groupsRes.length > 0) {
          const firstReceivableGroup = groupsRes.find((group) =>
            group.products.some(
              (product) => product.bottles_per_crate !== null && product.bottles_per_crate > 1,
            ),
          );
          const firstReceivableProduct = firstReceivableGroup?.products.find(
            (product) => product.bottles_per_crate !== null && product.bottles_per_crate > 1,
          );

          setCountPriceGroup(groupsRes[0].selling_price);
          if (firstReceivableGroup && firstReceivableProduct) {
            setSelectedPriceGroup(firstReceivableGroup.selling_price);
            setGroupedRows([
              {
                product_id: String(firstReceivableProduct.id),
                crates: "",
                crate_cost: "",
              },
            ]);
          }
        }
      })
      .catch((value: unknown) => setError(value as ApiError));
  }, []);

  // Price groups that contain at least one product with a crate conversion.
  const receivablePriceGroups = useMemo(
    () =>
      priceGroups.filter((group) =>
        group.products.some(
          (product) => product.bottles_per_crate !== null && product.bottles_per_crate > 1,
        ),
      ),
    [priceGroups],
  );

  // Filter products matching selected price group
  const productsInSelectedPriceGroup = useMemo(() => {
    if (!selectedPriceGroup) return [];
    return products.filter(
      (p) =>
        isCrated(p) &&
        p.current_price?.unit_price &&
        p.current_price.unit_price === selectedPriceGroup,
    );
  }, [products, selectedPriceGroup]);

  // Products for count price group
  const productsInCountPriceGroup = useMemo(() => {
    if (!countPriceGroup) return [];
    return products.filter(
      (p) => p.current_price?.unit_price && p.current_price.unit_price === countPriceGroup,
    );
  }, [products, countPriceGroup]);

  function handlePriceGroupChange(newPrice: string) {
    setSelectedPriceGroup(newPrice);
    const matching = products.filter(
      (p) => isCrated(p) && p.current_price?.unit_price && p.current_price.unit_price === newPrice,
    );
    if (matching.length > 0) {
      setGroupedRows([
        {
          product_id: String(matching[0].id),
          crates: "",
          crate_cost: "",
        },
      ]);
    } else {
      setGroupedRows([{ product_id: "", crates: "", crate_cost: "" }]);
    }
  }

  function addGroupedRow() {
    const usedIds = new Set(groupedRows.map((r) => r.product_id));
    const nextProduct = productsInSelectedPriceGroup.find((p) => !usedIds.has(String(p.id)));
    setGroupedRows((prev) => [
      ...prev,
      {
        product_id: nextProduct ? String(nextProduct.id) : "",
        crates: "",
        crate_cost: "",
      },
    ]);
  }

  function removeGroupedRow(index: number) {
    if (groupedRows.length <= 1) return;
    setGroupedRows((prev) => prev.filter((_, i) => i !== index));
  }

  function updateGroupedRow(index: number, field: keyof GroupedRow, value: string) {
    setGroupedRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  }

  // Grouped receiving calculations
  const groupedTotals = useMemo(() => {
    let totalCrates = 0;
    let totalBottles = 0;
    let totalCost = 0;
    const errors: string[] = [];
    const seenProducts = new Set<string>();

    for (const row of groupedRows) {
      if (!row.product_id) {
        errors.push("Select a product for every row.");
        continue;
      }
      if (seenProducts.has(row.product_id)) {
        errors.push("Each product may appear only once. Combine rows instead.");
      }
      seenProducts.add(row.product_id);

      const prod = products.find((p) => String(p.id) === row.product_id);
      if (!prod || !isCrated(prod)) {
        errors.push("A selected product no longer has a bottles-per-crate conversion.");
        continue;
      }
      const cSize = prod.bottles_per_crate ?? 1;
      const cratesNum = Number(row.crates);
      const costNum = Number(row.crate_cost);

      if (row.crates.trim() !== "") {
        if (!Number.isFinite(cratesNum) || cratesNum <= 0) {
          errors.push(`Invalid crate quantity for ${prod?.name ?? "product"}.`);
        } else {
          totalCrates += cratesNum;
          totalBottles += cratesNum * cSize;
        }
      }

      if (row.crate_cost.trim() !== "") {
        if (!Number.isFinite(costNum) || costNum < 0) {
          errors.push(`Invalid cost for ${prod?.name ?? "product"}.`);
        } else if (Number.isFinite(cratesNum) && cratesNum > 0) {
          totalCost += costNum * cratesNum;
        }
      }
    }

    return {
      totalCrates,
      totalBottles,
      totalCost,
      errors: Array.from(new Set(errors)),
    };
  }, [groupedRows, products]);

  function currentReceiptKey(): string {
    receiptKey.current ??=
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return receiptKey.current;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      if (mode === "receive") {
        if (receiveMode === "grouped") {
          // Grouped Receiving submission
          if (groupedTotals.errors.length > 0) {
            throw new Error(groupedTotals.errors[0]);
          }
          if (groupedRows.some((r) => !r.product_id || !r.crates || !r.crate_cost)) {
            throw new Error("Please complete all product lines before saving.");
          }

          const res = await createGroupedStockReceipt({
            supplier_name: supplier,
            reference: reference || undefined,
            selling_price: selectedPriceGroup,
            idempotency_key: currentReceiptKey(),
            lines: groupedRows.map((row) => ({
              product: Number(row.product_id),
              crates: row.crates,
              crate_cost: row.crate_cost,
            })),
          });

          setSuccessMessage(
            `Receipt #${res.id} recorded: received ${groupedTotals.totalBottles} bottles across ${groupedRows.length} brand(s).`,
          );
          receiptKey.current = null;
          setSupplier("");
          setReference("");
          setGroupedRows([
            {
              product_id: String(productsInSelectedPriceGroup[0]?.id ?? ""),
              crates: "",
              crate_cost: "",
            },
          ]);
        } else {
          // Standard Receiving submission
          const res = await createStockReceipt({
            supplier_name: supplier,
            reference: reference || undefined,
            idempotency_key: currentReceiptKey(),
            lines: [
              {
                product: Number(product),
                quantity: crate ? cratesToBottles(quantity) : quantity,
                unit_cost: crate ? crateCostToBottleCost(amount) : amount,
                currency: "ETB",
              },
            ],
          });
          setSuccessMessage(`Receipt #${res.id} recorded successfully.`);
          receiptKey.current = null;
          setSupplier("");
          setReference("");
          setQuantity("");
          setAmount("");
        }
      } else if (mode === "breakage") {
        await createBreakage({ reason, lines: [{ product: Number(product), quantity }] });
        setSuccessMessage("Breakage record saved.");
        setReason("");
        setQuantity("");
      } else {
        // Mode === "count"
        const targetProductIds =
          countSelectionMode === "group"
            ? productsInCountPriceGroup.map((p) => p.id)
            : [Number(product)];

        if (targetProductIds.length === 0) {
          throw new Error("Select at least one product to count.");
        }

        const created = await createStockCount({ products: targetProductIds });
        setCount(created);
        const initialInputs: Record<number, string> = {};
        for (const item of created.items) {
          initialInputs[item.id] = "";
        }
        setPhysicalCounts(initialInputs);
      }
    } catch (value) {
      if (value instanceof Error && !("code" in value)) {
        setError({ code: "client_validation", message: value.message } as unknown as ApiError);
      } else {
        setError(value as ApiError);
      }
    } finally {
      setSaving(false);
    }
  }

  async function finishCount() {
    if (!count) return;
    setSaving(true);
    setError(null);
    try {
      const itemsPayload = count.items.map((it) => {
        const val = physicalCounts[it.id];
        if (val === undefined || val.trim() === "") {
          throw new Error(`Enter the physical count for ${it.product_name}.`);
        }
        return {
          item: it.id,
          counted_quantity: val.trim(),
        };
      });

      const completed = await completeStockCount(count.id, {
        items: itemsPayload,
      });
      setCount(completed);
      setSuccessMessage("Physical counts recorded. Review variances below.");
    } catch (value) {
      if (value instanceof Error && !("code" in value)) {
        setError({ code: "client_validation", message: value.message } as unknown as ApiError);
      } else {
        setError(value as ApiError);
      }
    } finally {
      setSaving(false);
    }
  }

  async function approveCount() {
    if (!count) return;
    setSaving(true);
    setError(null);
    try {
      const approved = await approveStockCount(count.id);
      setCount(approved);
      setSuccessMessage("Stock adjustment approved and ledger updated.");
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

  function cratesToBottles(raw: string): string {
    if (!crate) return raw;
    const crates = Number(raw);
    return Number.isFinite(crates) ? String(crates * crate) : raw;
  }

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

  // Stock count draft calculations
  const countDraftStats = useMemo(() => {
    if (!count) return null;
    let expectedTotal = 0;
    let physicalTotal = 0;
    let allEntered = true;
    let countEntered = 0;

    for (const item of count.items) {
      const exp = Number(item.expected_quantity);
      expectedTotal += Number.isFinite(exp) ? exp : 0;
      const raw = physicalCounts[item.id];
      if (raw !== undefined && raw.trim() !== "") {
        const num = Number(raw);
        if (Number.isFinite(num)) {
          physicalTotal += num;
          countEntered++;
        } else {
          allEntered = false;
        }
      } else {
        allEntered = false;
      }
    }

    const varianceTotal = physicalTotal - expectedTotal;
    return {
      expectedTotal,
      physicalTotal,
      varianceTotal,
      allEntered,
      countEntered,
      totalItems: count.items.length,
    };
  }, [count, physicalCounts]);

  if (status === "checking") {
    return (
      <section className="max-w-4xl space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="text-sm text-ink-secondary">Checking access...</p>
      </section>
    );
  }

  if (!allowed) {
    return (
      <section className="max-w-4xl space-y-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Inventory
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        </div>
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include this inventory action. Ask an owner if you need access.
        </div>
      </section>
    );
  }

  return (
    <section className="max-w-4xl space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          Inventory
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          All changes are recorded in the authoritative movement ledger.
        </p>
      </div>

      {error && <p className="form-error">{describeError(error)}</p>}
      {successMessage && (
        <div className="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm font-medium text-emerald-800">
          {successMessage}
        </div>
      )}

      {/* Mode switcher tabs for Receive Stock */}
      {mode === "receive" && !count && (
        <div className="flex border-b border-border">
          <button
            type="button"
            onClick={() => setReceiveMode("standard")}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              receiveMode === "standard"
                ? "border-ink text-ink"
                : "border-transparent text-ink-secondary hover:text-ink"
            }`}
          >
            Standard Receiving
          </button>
          <button
            type="button"
            onClick={() => setReceiveMode("grouped")}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              receiveMode === "grouped"
                ? "border-ink text-ink"
                : "border-transparent text-ink-secondary hover:text-ink"
            }`}
          >
            Grouped Receiving (Shared Selling Price)
          </button>
        </div>
      )}

      {/* -------------------- STANDARD RECEIVING FORM -------------------- */}
      {mode === "receive" && receiveMode === "standard" && !count && (
        <form onSubmit={submit} className="space-y-4 rounded border border-border bg-surface p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label">
              Supplier
              <input
                required
                value={supplier}
                onChange={(event) => setSupplier(event.target.value)}
                placeholder="e.g. BGI Ethiopia, Castel"
                className="control mt-1.5"
              />
            </label>
            <label className="field-label">
              Delivery Reference (Optional)
              <input
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                placeholder="e.g. DEL-10029"
                className="control mt-1.5"
              />
            </label>
          </div>

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
                  {item.bottles_per_crate ? ` · ${item.bottles_per_crate} btl/crate` : ""}
                  {item.current_price?.unit_price ? ` · ${item.current_price.unit_price} ETB` : ""}
                </option>
              ))}
            </select>
          </label>

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

          <div className="form-actions">
            <button disabled={saving || !product} className="btn btn-primary" type="submit">
              {saving ? "Saving..." : "Save record"}
            </button>
          </div>
        </form>
      )}

      {/* -------------------- GROUPED RECEIVING FORM -------------------- */}
      {mode === "receive" && receiveMode === "grouped" && !count && (
        <form onSubmit={submit} className="space-y-5 rounded border border-border bg-surface p-4">
          <div className="rounded border border-border bg-canvas p-3 text-xs text-ink-secondary">
            Receive multiple brands that sell at the same price per bottle in one delivery. Crates
            convert to bottles per brand, while retaining separate inventory SKUs and costs.
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="field-label">
              Supplier
              <input
                required
                value={supplier}
                onChange={(event) => setSupplier(event.target.value)}
                placeholder="e.g. BGI Ethiopia, Castel"
                className="control mt-1.5"
              />
            </label>
            <label className="field-label">
              Delivery Reference (Optional)
              <input
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                placeholder="e.g. GRP-DEL-2024-01"
                className="control mt-1.5"
              />
            </label>
          </div>

          {/* Shared Selling Price Group */}
          <div>
            <label className="field-label">
              Shared Selling Price Group (ETB / bottle)
              <select
                required
                value={selectedPriceGroup}
                onChange={(e) => handlePriceGroupChange(e.target.value)}
                className="control mt-1.5 font-medium"
              >
                {receivablePriceGroups.length === 0 && (
                  <option value="">No crate-configured products</option>
                )}
                {receivablePriceGroups.map((pg) => {
                  const eligible = pg.products.filter(
                    (product) =>
                      product.bottles_per_crate !== null && product.bottles_per_crate > 1,
                  );
                  return (
                    <option key={pg.selling_price} value={pg.selling_price}>
                      ETB {pg.selling_price} / bottle ({eligible.length} brand
                      {eligible.length === 1 ? "" : "s"}:{" "}
                      {eligible
                        .map((p) => p.name)
                        .slice(0, 3)
                        .join(", ")}
                      {eligible.length > 3 ? "..." : ""})
                    </option>
                  );
                })}
              </select>
              <span className="field-hint">
                Only products whose active selling price is ETB {selectedPriceGroup || "—"} can be
                received in this group.
              </span>
            </label>
          </div>

          {receivablePriceGroups.length === 0 && (
            <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              No active product has a bottles-per-crate conversion configured. Set a crate size on
              the product before using grouped receiving.
            </p>
          )}

          {/* Product Rows */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink">Products in this Receipt</h2>
              <button type="button" onClick={addGroupedRow} className="btn btn-secondary text-xs">
                + Add Product Line
              </button>
            </div>

            <div className="space-y-3">
              {groupedRows.map((row, idx) => {
                const rowProduct = products.find((p) => String(p.id) === row.product_id);
                const rowCrate = rowProduct?.bottles_per_crate ?? 1;
                const rowCratesNum = Number(row.crates) || 0;
                const rowCostNum = Number(row.crate_cost) || 0;
                const rowBottles = rowCratesNum * rowCrate;
                const unitCostEquivalent =
                  rowCostNum > 0 && rowCrate > 0 ? (rowCostNum / rowCrate).toFixed(2) : "0.00";

                return (
                  <div
                    key={idx}
                    className="relative rounded border border-border bg-surface p-3 transition-colors hover:border-ink/20"
                  >
                    <div className="grid gap-3 sm:grid-cols-12 sm:items-end">
                      <div className="sm:col-span-4">
                        <label className="field-label text-xs">
                          Brand / Product
                          <select
                            required
                            value={row.product_id}
                            onChange={(e) => updateGroupedRow(idx, "product_id", e.target.value)}
                            className="control mt-1 text-sm"
                          >
                            <option value="">-- Select brand --</option>
                            {productsInSelectedPriceGroup.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name} (
                                {item.bottles_per_crate
                                  ? `${item.bottles_per_crate} btl/crate`
                                  : item.unit}
                                )
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>

                      <div className="sm:col-span-3">
                        <label className="field-label text-xs">
                          Quantity (Crates)
                          <input
                            required
                            min="1"
                            step="1"
                            type="number"
                            placeholder="e.g. 3"
                            value={row.crates}
                            onChange={(e) => updateGroupedRow(idx, "crates", e.target.value)}
                            className="control mt-1 text-sm"
                          />
                        </label>
                      </div>

                      <div className="sm:col-span-4">
                        <label className="field-label text-xs">
                          Crate Cost (ETB)
                          <input
                            required
                            min="0"
                            step="0.01"
                            type="number"
                            placeholder="e.g. 720.00"
                            value={row.crate_cost}
                            onChange={(e) => updateGroupedRow(idx, "crate_cost", e.target.value)}
                            className="control mt-1 text-sm"
                          />
                        </label>
                      </div>

                      <div className="flex justify-end sm:col-span-1">
                        {groupedRows.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeGroupedRow(idx)}
                            className="btn btn-secondary px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50"
                            title="Remove line"
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Calculated row helper */}
                    {rowProduct && row.crates && (
                      <div className="mt-2 flex flex-wrap items-center gap-3 border-t border-border/60 pt-2 text-xs text-ink-secondary">
                        <span>
                          Conversion: <strong>{row.crates} crates</strong> ×{" "}
                          <strong>{rowCrate} btl/crate</strong> ={" "}
                          <strong className="text-ink">{rowBottles} bottles</strong>
                        </span>
                        <span>
                          · Selling: <strong>ETB {selectedPriceGroup}</strong> / bottle
                        </span>
                        {rowCostNum > 0 && (
                          <span>
                            · Valuation: <strong>{unitCostEquivalent} ETB / bottle</strong> (Line
                            total: ETB {(rowCostNum * rowCratesNum).toFixed(2)})
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Grouped Receiving Summary Box */}
          <div className="rounded border border-ink/20 bg-canvas p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Grouped Delivery Summary
            </h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-4">
              <div>
                <span className="text-xs text-ink-secondary">Selling Price</span>
                <p className="text-lg font-semibold text-ink">ETB {selectedPriceGroup}</p>
                <span className="text-xs text-ink-secondary">per bottle</span>
              </div>
              <div>
                <span className="text-xs text-ink-secondary">Total Crates</span>
                <p className="text-lg font-semibold text-ink">{groupedTotals.totalCrates} crates</p>
                <span className="text-xs text-ink-secondary">
                  {groupedRows.length} brand line(s)
                </span>
              </div>
              <div className="rounded bg-surface p-2 border border-border">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink">
                  Combined Total
                </span>
                <p className="text-xl font-bold text-ink" data-testid="grouped-combined-total">
                  {groupedTotals.totalBottles} <span className="text-sm font-normal">bottles</span>
                </p>
                <span className="text-xs text-ink-secondary">Saved as separate SKUs</span>
              </div>
              <div>
                <span className="text-xs text-ink-secondary">Est. Delivery Cost</span>
                <p className="text-lg font-semibold text-ink">
                  ETB {groupedTotals.totalCost.toFixed(2)}
                </p>
                <span className="text-xs text-ink-secondary">Authoritative ledger valuation</span>
              </div>
            </div>
          </div>

          {groupedTotals.errors.length > 0 && (
            <p className="text-xs text-red-600">{groupedTotals.errors[0]}</p>
          )}

          <div className="form-actions">
            <button
              disabled={
                saving || groupedTotals.errors.length > 0 || groupedTotals.totalBottles === 0
              }
              className="btn btn-primary"
              type="submit"
            >
              {saving ? "Saving Grouped Receipt..." : "Save Grouped Receipt"}
            </button>
          </div>
        </form>
      )}

      {/* -------------------- BREAKAGE FORM -------------------- */}
      {mode === "breakage" && (
        <form onSubmit={submit} className="space-y-4 rounded border border-border bg-surface p-4">
          <label className="field-label">
            Reason
            <input
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. Broken bottle, spilled, expired"
              className="control mt-1.5"
            />
          </label>
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
          <div className="form-actions">
            <button disabled={saving || !product} className="btn btn-primary" type="submit">
              {saving ? "Saving..." : "Save record"}
            </button>
          </div>
        </form>
      )}

      {/* -------------------- STOCK COUNT FORM -------------------- */}
      {mode === "count" && !count && (
        <form onSubmit={submit} className="space-y-4 rounded border border-border bg-surface p-4">
          <div className="flex border-b border-border pb-2 text-sm font-medium">
            <button
              type="button"
              onClick={() => setCountSelectionMode("single")}
              className={`mr-4 border-b-2 pb-1.5 ${
                countSelectionMode === "single"
                  ? "border-ink text-ink font-semibold"
                  : "border-transparent text-ink-secondary"
              }`}
            >
              Single Product
            </button>
            <button
              type="button"
              onClick={() => setCountSelectionMode("group")}
              className={`border-b-2 pb-1.5 ${
                countSelectionMode === "group"
                  ? "border-ink text-ink font-semibold"
                  : "border-transparent text-ink-secondary"
              }`}
            >
              Grouped by Selling Price
            </button>
          </div>

          {countSelectionMode === "single" ? (
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
          ) : (
            <div>
              <label className="field-label">
                Selling Price Group (ETB / bottle)
                <select
                  required
                  value={countPriceGroup}
                  onChange={(e) => setCountPriceGroup(e.target.value)}
                  className="control mt-1.5 font-medium"
                >
                  {priceGroups.map((pg) => (
                    <option key={pg.selling_price} value={pg.selling_price}>
                      ETB {pg.selling_price} ({pg.product_count} brand
                      {pg.product_count === 1 ? "" : "s"})
                    </option>
                  ))}
                </select>
              </label>

              <div className="mt-3 rounded border border-border bg-canvas p-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                  Brands Included in Count:
                </span>
                <ul className="mt-1.5 space-y-1 text-sm">
                  {productsInCountPriceGroup.map((p) => (
                    <li key={p.id} className="flex items-center justify-between text-ink">
                      <span>
                        {p.name} ({p.sku})
                      </span>
                      <span className="text-xs text-ink-secondary">
                        {p.bottles_per_crate ? `${p.bottles_per_crate} btl/crate` : p.unit}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <p className="rounded bg-canvas p-3 text-sm text-ink-secondary">
            Open a count to snapshot expected stock, then enter the physical count for each brand.
          </p>

          <div className="form-actions">
            <button
              disabled={
                saving ||
                (countSelectionMode === "single"
                  ? !product
                  : productsInCountPriceGroup.length === 0)
              }
              className="btn btn-primary"
              type="submit"
            >
              {saving ? "Opening count..." : "Open count"}
            </button>
          </div>
        </form>
      )}

      {/* -------------------- ACTIVE STOCK COUNT TABLE & APPROVAL -------------------- */}
      {count && (
        <section className="space-y-4 rounded border border-border bg-surface p-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <h2 className="font-semibold text-ink">
                Count #{count.id} · <span className="uppercase">{count.status}</span>
              </h2>
              <p className="text-xs text-ink-secondary">
                {count.items.length} product(s) covered · Snapshotted at{" "}
                {new Date(count.counted_at).toLocaleTimeString()}
              </p>
            </div>
            {count.status === "DRAFT" && countDraftStats && (
              <span
                className={`rounded px-2.5 py-1 text-xs font-semibold ${
                  countDraftStats.allEntered
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
              >
                {countDraftStats.countEntered} of {countDraftStats.totalItems} entered
              </span>
            )}
          </div>

          {/* Counts Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-canvas text-xs uppercase text-ink-secondary">
                <tr>
                  <th className="py-2.5 px-3">Product</th>
                  <th className="py-2.5 px-3">Crate Info</th>
                  <th className="py-2.5 px-3 text-right">Expected</th>
                  <th className="py-2.5 px-3">Physical Count (Bottles)</th>
                  <th className="py-2.5 px-3 text-right">Variance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {count.items.map((item) => {
                  const prod = products.find((p) => p.id === item.product);
                  const cSize = prod?.bottles_per_crate;
                  const expNum = Number(item.expected_quantity);
                  const expLabel =
                    cSize && cSize > 1
                      ? `${expNum} (${crateLabel(expNum, cSize)})`
                      : item.expected_quantity;

                  // For draft mode
                  const rawVal = physicalCounts[item.id] ?? "";
                  const hasPhysical = rawVal.trim() !== "" && Number.isFinite(Number(rawVal));
                  const varianceNum = hasPhysical ? Number(rawVal) - expNum : null;

                  return (
                    <tr key={item.id} className="hover:bg-canvas/50">
                      <td className="py-2.5 px-3 font-medium text-ink">{item.product_name}</td>
                      <td className="py-2.5 px-3 text-xs text-ink-secondary">
                        {cSize ? `${cSize} btl/crate` : "Individual units"}
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-ink">{expLabel}</td>
                      <td className="py-2.5 px-3">
                        {count.status === "DRAFT" ? (
                          <input
                            required
                            type="number"
                            min="0"
                            step="1"
                            aria-label={`Physical quantity for ${item.product_name}`}
                            placeholder="Enter count"
                            value={rawVal}
                            onChange={(e) => {
                              const val = e.target.value;
                              setPhysicalCounts((prev) => ({ ...prev, [item.id]: val }));
                            }}
                            className="control h-8 w-32 text-sm"
                          />
                        ) : (
                          <span className="font-medium text-ink">{item.counted_quantity}</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {count.status === "DRAFT" ? (
                          varianceNum !== null ? (
                            <span
                              className={`font-semibold ${
                                varianceNum === 0
                                  ? "text-ink-secondary"
                                  : varianceNum > 0
                                    ? "text-emerald-700"
                                    : "text-red-700"
                              }`}
                            >
                              {varianceNum > 0 ? `+${varianceNum}` : varianceNum}
                            </span>
                          ) : (
                            <span className="text-xs text-ink-secondary">—</span>
                          )
                        ) : (
                          <span
                            className={`font-semibold ${
                              Number(item.variance) === 0
                                ? "text-ink-secondary"
                                : Number(item.variance) > 0
                                  ? "text-emerald-700"
                                  : "text-red-700"
                            }`}
                          >
                            {Number(item.variance) > 0 ? `+${item.variance}` : item.variance}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>

              {/* Combined Summary Row */}
              <tfoot className="border-t-2 border-border bg-canvas font-semibold">
                <tr>
                  <td colSpan={2} className="py-3 px-3 uppercase text-xs tracking-wider text-ink">
                    Combined Group Summary
                  </td>
                  <td className="py-3 px-3 text-right text-ink">
                    {count.status === "DRAFT"
                      ? `${countDraftStats?.expectedTotal ?? 0} bottles`
                      : `${count.total_expected ?? "0"} bottles`}
                  </td>
                  <td className="py-3 px-3">
                    {count.status === "DRAFT" ? (
                      countDraftStats?.allEntered ? (
                        <span className="font-bold text-ink">
                          {countDraftStats.physicalTotal} bottles
                        </span>
                      ) : (
                        <span className="text-xs font-normal text-amber-700">
                          Incomplete ({countDraftStats?.countEntered} of{" "}
                          {countDraftStats?.totalItems} entered)
                        </span>
                      )
                    ) : (
                      <span className="font-bold text-ink">
                        {count.total_counted ?? "0"} bottles
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-right">
                    {count.status === "DRAFT" ? (
                      countDraftStats?.allEntered ? (
                        <span
                          className={`font-bold ${
                            countDraftStats.varianceTotal === 0
                              ? "text-ink-secondary"
                              : countDraftStats.varianceTotal > 0
                                ? "text-emerald-700"
                                : "text-red-700"
                          }`}
                        >
                          {countDraftStats.varianceTotal > 0
                            ? `+${countDraftStats.varianceTotal}`
                            : countDraftStats.varianceTotal}{" "}
                          bottles
                        </span>
                      ) : (
                        <span className="text-xs font-normal text-ink-secondary">
                          Pending all counts
                        </span>
                      )
                    ) : (
                      <span
                        className={`font-bold ${
                          Number(count.total_variance ?? 0) === 0
                            ? "text-ink-secondary"
                            : Number(count.total_variance ?? 0) > 0
                              ? "text-emerald-700"
                              : "text-red-700"
                        }`}
                      >
                        {Number(count.total_variance ?? 0) > 0
                          ? `+${count.total_variance}`
                          : count.total_variance}{" "}
                        bottles
                      </span>
                    )}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          {/* Action buttons */}
          {count.status === "DRAFT" && (
            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-ink-secondary">
                Physical count must be entered for all products before completing.
              </span>
              <button
                disabled={saving || !countDraftStats?.allEntered}
                onClick={finishCount}
                className="btn btn-primary"
              >
                {saving ? "Completing count..." : "Complete count"}
              </button>
            </div>
          )}

          {count.status === "COMPLETED" && (
            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-ink-secondary">
                Manager authorization required to post variance adjustment to the movement ledger.
              </span>
              {canApprove && (
                <button
                  disabled={saving}
                  onClick={approveCount}
                  className="btn bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50"
                >
                  {saving ? "Approving adjustment..." : "Approve adjustment"}
                </button>
              )}
            </div>
          )}

          {count.status === "APPROVED" && (
            <div className="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800">
              Adjustment posted to the authoritative ledger. All balances have been updated.
            </div>
          )}
        </section>
      )}
    </section>
  );
}
