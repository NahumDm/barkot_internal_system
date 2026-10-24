"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  createBonoIncident,
  createBonoIssue,
  createBonoTransfer,
  type BonoIncidentKind,
  type BonoIssueKind,
  type BonoType,
} from "@/lib/api/bono";
import { listEmployees, type Employee } from "@/lib/api/employees";
import { listProducts, type ProductListItem } from "@/lib/api/products";
import { BonoColorDot } from "./parts";

type Action = "issue" | "transfer" | "lost" | "broken";

const ACTION_LABELS: Record<Action, string> = {
  issue: "Issue Bono to staff",
  transfer: "Transfer Bono between staff",
  lost: "Record lost Bono",
  broken: "Record broken bottle",
};

const BOTTLE_UNITS = new Set(["bottle", "bottles", "btl"]);

function isBottleProduct(product: ProductListItem): boolean {
  return (
    product.is_active &&
    product.is_stock_tracked &&
    product.quantity_mode === "WHOLE" &&
    BOTTLE_UNITS.has(product.unit.trim().toLowerCase())
  );
}

function messageOf(error: unknown): string {
  if (typeof error === "string") return error;
  const message = (error as { message?: unknown }).message;
  return typeof message === "string" && message ? message : "That action could not be recorded.";
}

/**
 * Custody actions for the current operational day.
 *
 * The server owns every rule - sufficient custody, equal selling price, no
 * activity on a submitted day - and this panel leaves those errors intact
 * instead of predicting them. Hiding the form on a locked day is presentation:
 * a stale tab that still submits gets the authoritative refusal.
 */
export function BonoOperationsPanel({
  date,
  types,
  locked,
  onChanged,
}: Readonly<{
  date: string;
  types: BonoType[];
  locked: boolean;
  onChanged: () => void;
}>) {
  const [action, setAction] = useState<Action>("issue");
  const [issueKind, setIssueKind] = useState<BonoIssueKind>("INITIAL");
  const [bonoTypeId, setBonoTypeId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [toEmployeeId, setToEmployeeId] = useState("");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      listEmployees({ archived: "false", page_size: 200 }),
      listProducts({ query: { active: true, stock_tracked: true, page_size: 200 } }),
    ])
      .then(([employeePage, productPage]) => {
        if (!active) return;
        setEmployees(employeePage.results);
        setProducts(productPage.results.filter(isBottleProduct));
        setError(null);
      })
      .catch((value: unknown) => {
        if (active) setError(messageOf(value));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const needsStaff = action === "issue" || action === "transfer" || action === "lost";
  const needsType = action !== "broken";
  const needsProduct = action === "broken";
  const needsReason = action !== "issue";
  const hasTypes = types.some((type) => type.is_active);

  function resetMessage() {
    setError(null);
    setSuccess("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    resetMessage();
    const parsedQuantity = Number(quantity);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity < 1) {
      setError("Enter a whole number of Bonos.");
      return;
    }
    if (needsType && !bonoTypeId) {
      setError("Choose a Bono type.");
      return;
    }
    if (needsStaff && !employeeId) {
      setError("Choose a staff member.");
      return;
    }
    if (action === "transfer" && (!toEmployeeId || toEmployeeId === employeeId)) {
      setError("Choose a different staff member to receive the Bonos.");
      return;
    }
    if (needsProduct && !productId) {
      setError("Choose the broken product.");
      return;
    }
    if (needsReason && !reason.trim()) {
      setError("A reason is required.");
      return;
    }

    setSaving(true);
    try {
      if (action === "issue") {
        await createBonoIssue({
          operational_date: date,
          bono_type: Number(bonoTypeId),
          employee: Number(employeeId),
          kind: issueKind,
          quantity: parsedQuantity,
          note: note.trim(),
        });
      } else if (action === "transfer") {
        await createBonoTransfer({
          operational_date: date,
          bono_type: Number(bonoTypeId),
          from_employee: Number(employeeId),
          to_employee: Number(toEmployeeId),
          quantity: parsedQuantity,
          reason: reason.trim(),
          note: note.trim(),
        });
      } else {
        const kind: BonoIncidentKind = action === "lost" ? "LOST_BONO" : "BROKEN_BOTTLE";
        await createBonoIncident({
          operational_date: date,
          kind,
          bono_type: action === "lost" ? Number(bonoTypeId) : null,
          product: action === "broken" ? Number(productId) : null,
          responsible_employee: action === "lost" ? Number(employeeId) : null,
          quantity: parsedQuantity,
          reason: reason.trim(),
          notes: note.trim(),
        });
      }
      setSuccess("Recorded. The day ledger is up to date.");
      setQuantity("1");
      setReason("");
      setNote("");
      onChanged();
    } catch (value) {
      setError(messageOf(value));
    } finally {
      setSaving(false);
    }
  }

  if (locked) {
    return (
      <section className="rounded border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold text-ink">Custody actions</h2>
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          This day&apos;s report has been submitted, so Bono custody is locked. A report rejected by
          the Owner reopens the day for correction.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold text-ink">Custody actions</h2>
      <p className="mt-1 text-sm text-ink-secondary">
        Record a hand-out, a hand-over between staff, or a loss. Each action is append-only and
        attributed to the signed-in manager.
      </p>

      {loading ? (
        <p className="mt-4 text-sm text-ink-secondary">Loading staff and products...</p>
      ) : null}
      {error ? (
        <p role="alert" className="form-error mt-4">
          {messageOf(error)}
        </p>
      ) : null}
      {success ? (
        <p
          role="status"
          className="mt-4 rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950"
        >
          {success}
        </p>
      ) : null}

      {!loading ? (
        <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={handleSubmit}>
          <label className="text-sm font-medium text-ink sm:col-span-2">
            Action
            <select
              className="control mt-1.5"
              value={action}
              onChange={(event) => {
                setAction(event.target.value as Action);
                resetMessage();
              }}
            >
              {(Object.keys(ACTION_LABELS) as Action[]).map((value) => (
                <option key={value} value={value}>
                  {ACTION_LABELS[value]}
                </option>
              ))}
            </select>
          </label>

          {action === "issue" ? (
            <label className="text-sm font-medium text-ink">
              Issue kind
              <select
                className="control mt-1.5"
                value={issueKind}
                onChange={(event) => setIssueKind(event.target.value as BonoIssueKind)}
              >
                <option value="INITIAL">Initial issue</option>
                <option value="ADDITIONAL">Additional issue</option>
              </select>
            </label>
          ) : null}

          {needsType ? (
            <label className="text-sm font-medium text-ink">
              Bono type
              <select
                className="control mt-1.5"
                value={bonoTypeId}
                onChange={(event) => setBonoTypeId(event.target.value)}
                disabled={!hasTypes}
              >
                <option value="">{hasTypes ? "Choose a Bono type" : "No active Bono types"}</option>
                {types
                  .filter((type) => type.is_active)
                  .map((type) => (
                    <option key={type.id} value={type.id}>
                      {type.name} - {type.selling_price} {type.currency}
                    </option>
                  ))}
              </select>
            </label>
          ) : null}

          {needsProduct ? (
            <label className="text-sm font-medium text-ink">
              Broken product
              <select
                className="control mt-1.5"
                value={productId}
                onChange={(event) => setProductId(event.target.value)}
              >
                <option value="">
                  {products.length ? "Choose a product" : "No bottle products"}
                </option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name} ({product.sku})
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {needsStaff ? (
            <label className="text-sm font-medium text-ink">
              {action === "transfer" ? "From staff member" : "Responsible staff member"}
              <select
                className="control mt-1.5"
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
              >
                <option value="">
                  {employees.length ? "Choose a staff member" : "No active staff found"}
                </option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name} - {employee.position}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {action === "transfer" ? (
            <label className="text-sm font-medium text-ink">
              To staff member
              <select
                className="control mt-1.5"
                value={toEmployeeId}
                onChange={(event) => setToEmployeeId(event.target.value)}
              >
                <option value="">Choose a staff member</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name} - {employee.position}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="text-sm font-medium text-ink">
            Quantity
            <input
              type="number"
              min="1"
              step="1"
              className="control mt-1.5"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
          </label>

          {needsReason ? (
            <label className="text-sm font-medium text-ink sm:col-span-2">
              Reason
              <input
                type="text"
                className="control mt-1.5"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                placeholder={
                  action === "transfer"
                    ? "Why the Bonos moved"
                    : "What happened to the Bonos or stock"
                }
              />
            </label>
          ) : null}

          <label className="text-sm font-medium text-ink sm:col-span-2">
            Note <span className="font-normal text-ink-secondary">(optional)</span>
            <textarea
              className="control mt-1.5"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={1000}
            />
          </label>

          <div className="sm:col-span-2">
            {types.length === 0 ? (
              <p className="mb-3 text-sm text-ink-secondary">
                No Bono types exist yet. An owner must configure at least one type before custody
                can be recorded.
              </p>
            ) : null}
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving || (needsType && !hasTypes)}
            >
              {saving ? "Recording..." : ACTION_LABELS[action]}
            </button>
          </div>
        </form>
      ) : null}

      {!loading && action !== "broken" && types.length > 0 ? (
        <p className="mt-4 text-xs text-ink-secondary">
          A transfer never creates a new Bono: it moves one already in staff custody. Example:{" "}
          <BonoColorDot color={types[0]?.color ?? "#111827"} label={types[0]?.name ?? "Bono"} />
        </p>
      ) : null}
    </section>
  );
}
