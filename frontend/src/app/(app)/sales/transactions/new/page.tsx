"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { listProducts, type ProductListItem } from "@/lib/api/products";
import { createSale, type PaymentInput } from "@/lib/api/sales";
import { crateLabel, crateSize, parseBottles } from "@/lib/crates";
import {
  type ApiError,
  ApiError as ApiErrorClass,
  isInconsistentTotals,
  isInsufficientStock,
  isPermissionDenied,
  isRequestTimeout,
  isValidationError,
} from "@/lib/api/errors";
import { Field, FormError } from "@/features/auth/form-parts";

interface GroupedProduct {
  categoryId: number;
  categoryName: string;
  products: ProductListItem[];
}

interface SaleLine {
  product: number;
  quantity: string;
}

/**
 * The minimum fields a sale needs, kept deliberately small so an incomplete row
 * cannot be submitted by accident - the backend is the authority on price and
 * totals, so the form only sends what the catalogue cannot derive: which product
 * and how many.
 */
const EMPTY_LINE: SaleLine = { product: 0, quantity: "" };

/** How many decimal places the backend stores for a quantity (spec §13.1). */
const QUANTITY_SCALE = 3n;
const QUANTITY_DIVISOR = 10n ** QUANTITY_SCALE;

/**
 * Parse a decimal string into integer minor units without floating point.
 *
 * `Number("0.1") + Number("0.2")` is `0.30000000000000004`, and a till that
 * rounds like that will eventually disagree with the backend's `Decimal`
 * arithmetic by a cent. Working in `BigInt` cents keeps the previewed total
 * exact for every value the field can hold. Returns `null` when the string is
 * not a plain non-negative decimal, so a blank or malformed entry is caught
 * rather than silently treated as zero.
 */
function toMinorUnits(value: string, decimals: number): bigint | null {
  const trimmed = value.trim();
  if (trimmed === "" || !/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const [whole, fraction = ""] = trimmed.split(".");
  const padded = (fraction + "0".repeat(decimals)).slice(0, decimals);
  return BigInt(whole) * 10n ** BigInt(decimals) + BigInt(padded);
}

/**
 * `line = unit_price × quantity`, rounded half-up to two decimals.
 *
 * Mirrors `apps.core.money.quantize_money` (`ROUND_HALF_UP`) so the preview the
 * cashier reads matches the figure the server will store.
 */
function multiplyMoney(priceMinor: bigint, quantityMinor: bigint): bigint {
  return (priceMinor * quantityMinor + QUANTITY_DIVISOR / 2n) / QUANTITY_DIVISOR;
}

/** Render integer cents as `"1234.50"` for `Number(...)` formatting. */
function formatMinor(amount: bigint): string {
  const negative = amount < 0n;
  const absolute = negative ? -amount : amount;
  const whole = (absolute / 100n).toString();
  const fraction = (absolute % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}

/** Human-readable money with thousands separators, without touching the value. */
function displayMoney(amountMinor: bigint): string {
  return Number(formatMinor(amountMinor)).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** The current selling price of a catalogue product, if one is set. */
function currentPrice(
  product: ProductListItem | undefined,
): { unit_price: string; currency: string } | null {
  return product?.current_price ?? null;
}

/** One line's total, or `null` when the product or the quantity is not usable yet. */
function lineTotalMinor(line: SaleLine, byId: Map<number, ProductListItem>): bigint | null {
  const price = currentPrice(byId.get(line.product));
  const quantityMinor = toMinorUnits(line.quantity, Number(QUANTITY_SCALE));
  if (!price || quantityMinor === null) return null;
  const priceMinor = toMinorUnits(price.unit_price, 2);
  if (priceMinor === null) return null;
  return multiplyMoney(priceMinor, quantityMinor);
}

/** A line is only worth sending when it names a product and a positive quantity. */
function isSubmittableLine(line: SaleLine): boolean {
  const quantityMinor = toMinorUnits(line.quantity, Number(QUANTITY_SCALE));
  return line.product > 0 && quantityMinor !== null && quantityMinor > 0n;
}

/** A payment is only worth sending when it has a positive amount. */
function isSubmittablePayment(payment: PaymentInput): boolean {
  const amountMinor = toMinorUnits(payment.amount, 2);
  return amountMinor !== null && amountMinor > 0n;
}

/**
 * Turn an `ApiError` into a message that says what the user can actually do.
 *
 * The backend hands back a stable `code`; the wording is chosen here so a stock
 * refusal ("reduce the quantity") never reads the same as a network failure
 * ("try again"). `message` is only a fallback, for codes this screen has no
 * specific advice for.
 */
function describeSaleError(error: unknown): string {
  if (isInsufficientStock(error)) {
    return "Not enough stock for one or more products. Reduce the quantity and try again.";
  }
  if (isPermissionDenied(error)) {
    return "You do not have permission to record sales.";
  }
  if (isInconsistentTotals(error)) {
    return "The payments do not match the sale total. Check the amounts and try again.";
  }
  if (isRequestTimeout(error)) {
    return "The request timed out. Check your connection and try again.";
  }
  if (error instanceof ApiErrorClass) {
    const general = error.details?.["non_field_errors"];
    if (general && general.length > 0) return general.join(" ");
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

export default function NewSalePage() {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);

  const [groupedProducts, setGroupedProducts] = useState<GroupedProduct[]>([]);
  const [productsById, setProductsById] = useState<Map<number, ProductListItem>>(new Map());
  const [productsLoading, setProductsLoading] = useState(true);
  const [productsError, setProductsError] = useState<string | null>(null);

  const [lines, setLines] = useState<SaleLine[]>([{ ...EMPTY_LINE }]);
  const [payments, setPayments] = useState<PaymentInput[]>([{ method: "CASH", amount: "" }]);

  /**
   * Validation messages keyed by API field path, e.g. `lines.0.quantity`.
   *
   * Populated by the client's own checks before a request is sent and, for
   * anything the client cannot know, by the backend's `details` map after one
   * is. Both paths write the same keys so the rendering has one code path.
   */
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let mounted = true;
    listProducts({ query: { active: true, stock_tracked: true, page_size: 500 } })
      .then((response) => {
        if (!mounted) return;
        const byId = new Map(response.results.map((product) => [product.id, product]));
        setProductsById(byId);

        const grouped: Record<number, GroupedProduct> = {};
        for (const product of response.results) {
          if (!grouped[product.category]) {
            grouped[product.category] = {
              categoryId: product.category,
              categoryName: product.category_name,
              products: [],
            };
          }
          grouped[product.category].products.push(product);
        }
        setGroupedProducts(
          Object.values(grouped).sort((a, b) => a.categoryName.localeCompare(b.categoryName)),
        );
        setProductsLoading(false);
      })
      .catch((caught: unknown) => {
        if (!mounted) return;
        setProductsLoading(false);
        setProductsError(describeSaleError(caught as ApiError));
      });
    return () => {
      mounted = false;
    };
  }, []);

  const clearFieldError = (key: string) => {
    setFieldErrors((prev) => (prev[key]?.length ? { ...prev, [key]: [] } : prev));
  };

  const handleLineChange = (index: number, field: keyof SaleLine, value: string | number) => {
    setLines((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
    clearFieldError(`lines.${index}.${field}`);
  };

  const handlePaymentChange = (index: number, field: keyof PaymentInput, value: string) => {
    setPayments((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
    clearFieldError(`payments.${index}.${field}`);
  };

  const addLine = () => {
    setLines((prev) => [...prev, { ...EMPTY_LINE }]);
  };

  const removeLine = (index: number) => {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== index));
  };

  const addPayment = () => {
    setPayments((prev) => [...prev, { method: "CASH", amount: "" }]);
  };

  const removePayment = (index: number) => {
    if (payments.length <= 1) return;
    setPayments((prev) => prev.filter((_, i) => i !== index));
  };

  /** Run the client's own checks; returns the errors keyed like the API's. */
  const validate = (): { errors: Record<string, string[]>; summary: string | null } => {
    const errors: Record<string, string[]> = {};
    const seen = new Set<number>();
    let usableLines = 0;

    lines.forEach((line, index) => {
      const product = productsById.get(line.product);
      if (!line.product) {
        errors[`lines.${index}.product`] = ["Select a product."];
      } else if (!product) {
        errors[`lines.${index}.product`] = ["That product is no longer available."];
      } else if (seen.has(line.product)) {
        errors[`lines.${index}.product`] = [
          "This product is already on the sale. Combine the lines instead.",
        ];
      } else if (!currentPrice(product)) {
        errors[`lines.${index}.product`] = [
          "This product has no price set. Set one before selling it.",
        ];
      } else {
        seen.add(line.product);
      }

      const quantityMinor = toMinorUnits(line.quantity, Number(QUANTITY_SCALE));
      if (quantityMinor === null) {
        errors[`lines.${index}.quantity`] = ["Enter a quantity."];
      } else if (quantityMinor <= 0n) {
        errors[`lines.${index}.quantity`] = ["Quantity must be greater than zero."];
      } else if (
        productsById.get(line.product)?.quantity_mode === "WHOLE" &&
        quantityMinor % QUANTITY_DIVISOR !== 0n
      ) {
        errors[`lines.${index}.quantity`] = [
          "This product is counted in whole units; enter a whole number.",
        ];
      }

      if (!errors[`lines.${index}.product`] && !errors[`lines.${index}.quantity`]) usableLines += 1;
    });

    let usablePayments = 0;
    payments.forEach((payment, index) => {
      const amountMinor = toMinorUnits(payment.amount, 2);
      if (amountMinor === null) {
        errors[`payments.${index}.amount`] = ["Enter a payment amount."];
      } else if (amountMinor <= 0n) {
        errors[`payments.${index}.amount`] = ["Payment amount must be greater than zero."];
      } else {
        usablePayments += 1;
      }
    });

    if (usableLines === 0) {
      return { errors, summary: "Add at least one line with a product and a quantity." };
    }
    if (usablePayments === 0) {
      return { errors, summary: "Add at least one payment greater than zero." };
    }
    if (Object.keys(errors).length > 0) {
      return { errors, summary: "Some lines or payments still need attention." };
    }
    return { errors, summary: null };
  };

  const focusFirstInvalid = () => {
    requestAnimationFrame(() => {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    const { errors, summary } = validate();
    if (summary !== null || Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormError(summary ?? "Fix the highlighted fields before recording the sale.");
      focusFirstInvalid();
      return;
    }

    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    try {
      await createSale({
        lines: lines
          .filter(isSubmittableLine)
          .map((line) => ({ product: line.product, quantity: line.quantity.trim() })),
        payments: payments
          .filter(isSubmittablePayment)
          .map((payment) => ({ method: payment.method, amount: payment.amount.trim() })),
      });
      router.push("/sales");
    } catch (caught) {
      const error = caught as ApiError;
      setFieldErrors(error.details ?? {});
      setFormError(describeSaleError(error));
      setSubmitting(false);
      if (isValidationError(error)) focusFirstInvalid();
    }
  };

  if (productsLoading) {
    return (
      <section className="flex items-center justify-center py-8 text-ink-secondary">
        Loading…
      </section>
    );
  }

  const activeLines = lines.filter(isSubmittableLine);
  const parsedTotals = activeLines.map((line) => lineTotalMinor(line, productsById));
  const saleTotalMinor = parsedTotals.reduce<bigint>(
    (sum, value) => (value === null ? sum : sum + value),
    0n,
  );
  const paymentTotalMinor = payments.reduce<bigint>((sum, payment) => {
    const amount = toMinorUnits(payment.amount, 2);
    return amount === null ? sum : sum + amount;
  }, 0n);
  const currency =
    activeLines.map((line) => currentPrice(productsById.get(line.product))?.currency)[0] ?? "ETB";
  const hasProducts = groupedProducts.length > 0;
  const topLevelLineErrors = fieldErrors.lines ?? [];
  const topLevelPaymentErrors = fieldErrors.payments ?? [];

  return (
    <section className="flex flex-col gap-6">
      <header>
        <h1 className="page-title text-2xl font-semibold tracking-tight text-ink">New Sale</h1>
        <p className="page-subtitle mt-1 text-sm text-ink-secondary">
          Record a sale with lines and payments.
        </p>
      </header>

      <form ref={formRef} onSubmit={handleSubmit} className="flex flex-col gap-6" noValidate>
        <FormError
          error={
            formError
              ? new ApiErrorClass(0, { code: "form_error", message: formError, details: null })
              : null
          }
        />

        {productsError ? (
          <p role="alert" className="form-error">
            {productsError}
          </p>
        ) : null}

        <section>
          <h2 className="mb-4 text-lg font-semibold text-ink">Lines</h2>
          {!hasProducts ? (
            <p className="rounded border border-border bg-surface p-4 text-sm text-ink-secondary">
              No stock-tracked products are available to sell. Add a product first.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {lines.map((line, index) => {
                const product = productsById.get(line.product);
                const price = currentPrice(product);
                const lineTotal = lineTotalMinor(line, productsById);
                const crate = crateSize(product);
                const typedBottles = parseBottles(line.quantity);
                const quantityHint = crate
                  ? `1 crate = ${crate} bottles${
                      typedBottles !== null && typedBottles > 0
                        ? ` · = ${crateLabel(typedBottles, crate)}`
                        : ""
                    }`
                  : product?.quantity_mode === "WHOLE"
                    ? "Whole units only"
                    : undefined;
                return (
                  <div
                    key={index}
                    className="grid items-start gap-3 rounded border border-border bg-surface p-3 sm:grid-cols-[minmax(0,1fr)_6rem_9rem_9rem_auto]"
                  >
                    <div className="field">
                      <label htmlFor={`sale-line-product-${index}`} className="field-label">
                        Product
                      </label>
                      <select
                        id={`sale-line-product-${index}`}
                        value={String(line.product)}
                        onChange={(event) =>
                          handleLineChange(index, "product", Number(event.target.value))
                        }
                        autoComplete="off"
                        className="control"
                        aria-invalid={(fieldErrors[`lines.${index}.product`] ?? []).length > 0}
                      >
                        <option value="0">Select a product</option>
                        {groupedProducts.map((group) => (
                          <optgroup key={group.categoryId} label={group.categoryName}>
                            {group.products.map((item) => (
                              <option key={item.id} value={String(item.id)}>
                                {item.name} ({item.sku})
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                      {(fieldErrors[`lines.${index}.product`] ?? []).map((message) => (
                        <p key={message} className="field-error">
                          {message}
                        </p>
                      ))}
                    </div>

                    <Field
                      label={crate ? "Qty (bottles)" : "Qty"}
                      type="number"
                      value={line.quantity}
                      onChange={(value) => handleLineChange(index, "quantity", value)}
                      errors={fieldErrors[`lines.${index}.quantity`] ?? []}
                      autoComplete="off"
                      min={product?.quantity_mode === "WHOLE" ? 1 : 0.001}
                      step={product?.quantity_mode === "WHOLE" ? 1 : 0.001}
                      inputMode={product?.quantity_mode === "WHOLE" ? "numeric" : "decimal"}
                      hint={quantityHint}
                    />

                    <div className="field">
                      <span className="field-label">Unit price</span>
                      <span className="text-sm text-ink" aria-live="polite">
                        {price
                          ? `${displayMoney(toMinorUnits(price.unit_price, 2) ?? 0n)} ${price.currency}`
                          : "Not set"}
                      </span>
                      {crate ? <span className="field-hint">per bottle</span> : null}
                    </div>

                    <div className="field">
                      <span className="field-label">Line total</span>
                      <span className="text-sm font-medium text-ink" aria-live="polite">
                        {lineTotal === null ? "—" : `${displayMoney(lineTotal)} ${currency}`}
                      </span>
                    </div>

                    <div className="flex items-end sm:pt-6">
                      <button
                        type="button"
                        onClick={() => removeLine(index)}
                        disabled={lines.length <= 1}
                        className="btn btn-ghost"
                        aria-label={`Remove line ${index + 1}`}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {topLevelLineErrors.map((message) => (
            <p key={message} className="field-error mt-2">
              {message}
            </p>
          ))}
          <button
            type="button"
            onClick={addLine}
            disabled={!hasProducts}
            className="btn btn-ghost mt-3"
          >
            Add Line
          </button>
        </section>

        <section>
          <h2 className="mb-4 text-lg font-semibold text-ink">Payments</h2>
          <div className="flex flex-col gap-3">
            {payments.map((payment, index) => (
              <div
                key={index}
                className="grid items-start gap-3 rounded border border-border bg-surface p-3 sm:grid-cols-[12rem_12rem_auto]"
              >
                <div className="field">
                  <label htmlFor={`sale-payment-method-${index}`} className="field-label">
                    Method
                  </label>
                  <select
                    id={`sale-payment-method-${index}`}
                    value={payment.method}
                    onChange={(event) =>
                      handlePaymentChange(
                        index,
                        "method",
                        event.target.value as PaymentInput["method"],
                      )
                    }
                    className="control"
                    aria-invalid={(fieldErrors[`payments.${index}.method`] ?? []).length > 0}
                  >
                    <option value="CASH">Cash</option>
                    <option value="MOBILE_BANKING">Mobile Banking</option>
                  </select>
                  {(fieldErrors[`payments.${index}.method`] ?? []).map((message) => (
                    <p key={message} className="field-error">
                      {message}
                    </p>
                  ))}
                </div>

                <Field
                  label="Amount"
                  type="number"
                  value={payment.amount}
                  onChange={(value) => handlePaymentChange(index, "amount", value)}
                  errors={fieldErrors[`payments.${index}.amount`] ?? []}
                  autoComplete="off"
                  min={0.01}
                  step="0.01"
                  inputMode="decimal"
                />

                <div className="flex items-end sm:pt-6">
                  <button
                    type="button"
                    onClick={() => removePayment(index)}
                    disabled={payments.length <= 1}
                    className="btn btn-ghost"
                    aria-label={`Remove payment ${index + 1}`}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          {topLevelPaymentErrors.map((message) => (
            <p key={message} className="field-error mt-2">
              {message}
            </p>
          ))}
          <button type="button" onClick={addPayment} className="btn btn-ghost mt-3">
            Add Payment
          </button>
        </section>

        <section aria-label="Sale totals" className="rounded border border-border bg-surface p-4">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-sm text-ink-secondary">Sale total</span>
            <span className="text-xl font-semibold text-ink">
              {displayMoney(saleTotalMinor)} {currency}
            </span>
          </div>
          <div className="mt-1 flex items-baseline justify-between gap-4">
            <span className="text-sm text-ink-secondary">Payments entered</span>
            <span className="text-sm text-ink">
              {displayMoney(paymentTotalMinor)} {currency}
            </span>
          </div>
          {saleTotalMinor !== paymentTotalMinor ? (
            <p className="mt-2 text-xs text-ink-secondary">
              Payments do not match the sale total yet. The backend records the sale against the
              catalogue price, so adjust the amounts if this is not intentional.
            </p>
          ) : null}
        </section>

        <div className="form-actions">
          <button type="submit" disabled={submitting || !hasProducts} className="btn btn-primary">
            {submitting ? "Recording Sale…" : "Record Sale"}
          </button>
        </div>
      </form>
    </section>
  );
}
