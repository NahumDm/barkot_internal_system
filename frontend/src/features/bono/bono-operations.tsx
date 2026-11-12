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
import { useT } from "@/lib/i18n/context";

type Action = "issue" | "transfer" | "lost" | "broken";

const ACTION_LABELS: Record<Action, string> = {
  issue: "bono.op.issue",
  transfer: "bono.op.transfer",
  lost: "bono.op.lost",
  broken: "bono.op.broken",
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

function messageOf(error: unknown, fallback: string): string {
  if (typeof error === "string") return error;
  const message = (error as { message?: unknown }).message;
  return typeof message === "string" && message ? message : fallback;
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
  const t = useT();
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
        if (active) setError(messageOf(value, t("bono.op.actionFailed")));
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
      setError(t("bono.op.enterWholeNumber"));
      return;
    }
    if (needsType && !bonoTypeId) {
      setError(t("bono.op.chooseType"));
      return;
    }
    if (needsStaff && !employeeId) {
      setError(t("bono.op.chooseStaff"));
      return;
    }
    if (action === "transfer" && (!toEmployeeId || toEmployeeId === employeeId)) {
      setError(t("bono.op.chooseDifferentStaff"));
      return;
    }
    if (needsProduct && !productId) {
      setError(t("bono.op.chooseBrokenProduct"));
      return;
    }
    if (needsReason && !reason.trim()) {
      setError(t("bono.op.reasonRequired"));
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
      setSuccess(t("bono.op.recorded"));
      setQuantity("1");
      setReason("");
      setNote("");
      onChanged();
    } catch (value) {
      setError(messageOf(value, t("bono.op.actionFailed")));
    } finally {
      setSaving(false);
    }
  }

  if (locked) {
    return (
      <section className="rounded border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold text-ink">{t("bono.op.custodyActions")}</h2>
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          {t("bono.op.lockedNote")}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold text-ink">{t("bono.op.custodyActions")}</h2>
      <p className="mt-1 text-sm text-ink-secondary">{t("bono.op.blurb")}</p>

      {loading ? (
        <p className="mt-4 text-sm text-ink-secondary">{t("bono.op.loadingStaffProducts")}</p>
      ) : null}
      {error ? (
        <p role="alert" className="form-error mt-4">
          {messageOf(error, "")}
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
            {t("bono.op.action")}
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
                  {t(ACTION_LABELS[value])}
                </option>
              ))}
            </select>
          </label>

          {action === "issue" ? (
            <label className="text-sm font-medium text-ink">
              {t("bono.op.issueKind")}
              <select
                className="control mt-1.5"
                value={issueKind}
                onChange={(event) => setIssueKind(event.target.value as BonoIssueKind)}
              >
                <option value="INITIAL">{t("bono.movement.initialIssue")}</option>
                <option value="ADDITIONAL">{t("bono.movement.additionalIssue")}</option>
              </select>
            </label>
          ) : null}

          {needsType ? (
            <label className="text-sm font-medium text-ink">
              {t("bono.op.bonoType")}
              <select
                className="control mt-1.5"
                value={bonoTypeId}
                onChange={(event) => setBonoTypeId(event.target.value)}
                disabled={!hasTypes}
              >
                <option value="">
                  {hasTypes ? t("bono.op.chooseTypePlaceholder") : t("bono.op.noActiveTypes")}
                </option>
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
              {t("bono.op.brokenProduct")}
              <select
                className="control mt-1.5"
                value={productId}
                onChange={(event) => setProductId(event.target.value)}
              >
                <option value="">
                  {products.length ? t("bono.op.chooseProduct") : t("bono.op.noBottleProducts")}
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
              {action === "transfer"
                ? t("bono.op.fromStaff")
                : t("bono.op.responsibleStaff")}
              <select
                className="control mt-1.5"
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
              >
                <option value="">
                  {employees.length
                    ? t("bono.op.chooseStaffPlaceholder")
                    : t("bono.op.noStaffFound")}
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
              {t("bono.op.toStaff")}
              <select
                className="control mt-1.5"
                value={toEmployeeId}
                onChange={(event) => setToEmployeeId(event.target.value)}
              >
                <option value="">{t("bono.op.chooseStaffPlaceholder")}</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name} - {employee.position}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="text-sm font-medium text-ink">
            {t("bono.op.quantity")}
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
              {t("bono.op.reason")}
              <input
                type="text"
                className="control mt-1.5"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                placeholder={
                  action === "transfer"
                    ? t("bono.op.whyMoved")
                    : t("bono.op.whatHappened")
                }
              />
            </label>
          ) : null}

          <label className="text-sm font-medium text-ink sm:col-span-2">
            {t("bono.op.note")}{" "}
            <span className="font-normal text-ink-secondary">{t("bono.op.optional")}</span>
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
              <p className="mb-3 text-sm text-ink-secondary">{t("bono.op.noTypesYet")}</p>
            ) : null}
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving || (needsType && !hasTypes)}
            >
              {saving ? t("bono.op.recording") : t(ACTION_LABELS[action])}
            </button>
          </div>
        </form>
      ) : null}

      {!loading && action !== "broken" && types.length > 0 ? (
        <p className="mt-4 text-xs text-ink-secondary">
          {t("bono.op.transferHint")}{" "}
          <BonoColorDot
            color={types[0]?.color ?? "#111827"}
            label={types[0]?.name ?? t("bono.op.bonoFallback")}
          />
        </p>
      ) : null}
    </section>
  );
}
