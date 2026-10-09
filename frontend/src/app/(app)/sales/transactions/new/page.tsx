"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { listProducts, type ProductListItem } from "@/lib/api/products";
import { createSale, type SaleLineInput, type PaymentInput } from "@/lib/api/sales";
import {
  type ApiError,
  type ErrorDetails,
  isValidationError,
  ApiError as ApiErrorClass,
} from "@/lib/api/errors";
import { Field, FormError, FormShell } from "@/features/auth/form-parts";

interface GroupedProduct {
  categoryId: number;
  categoryName: string;
  products: ProductListItem[];
}

const selectClasses = "rounded border border-border bg-surface px-3 py-2 text-sm text-ink";

export default function NewSalePage() {
  const router = useRouter();

  const [groupedProducts, setGroupedProducts] = useState<GroupedProduct[]>([]);
  const [productsLoading, setProductsLoading] = useState(true);

  const [lines, setLines] = useState<SaleLineInput[]>([
    { product: 0, quantity: "", unit_price: undefined },
  ]);
  const [payments, setPayments] = useState<PaymentInput[]>([{ method: "CASH", amount: "" }]);

  /**
   * Validation messages keyed by API field path, e.g. `lines.0.quantity`.
   *
   * Starts empty, and stays that way until the API answers with details, so it
   * is a sparse map: reading a key that has no entry gives `undefined`, not an
   * empty array. Every read below therefore goes through `?? []` or `?.length`.
   * Reading one directly (`fieldErrors[key].length`) crashes the screen on first
   * render, before the cashier has typed anything, which is exactly what happened
   * until the live E2E suite visited this page for the first time.
   */
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let mounted = true;
    listProducts({ query: { active: true, stock_tracked: true, page_size: 500 } })
      .then((response) => {
        if (!mounted) return;
        const products = response.results;
        const grouped: Record<number, GroupedProduct> = {};
        for (const p of products) {
          if (!grouped[p.category]) {
            grouped[p.category] = {
              categoryId: p.category,
              categoryName: p.category_name,
              products: [],
            };
          }
          grouped[p.category].products.push(p);
        }
        setGroupedProducts(
          Object.values(grouped).sort((a, b) => a.categoryName.localeCompare(b.categoryName)),
        );
        setProductsLoading(false);
      })
      .catch(() => {
        if (mounted) setProductsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleLineChange = (index: number, field: keyof SaleLineInput, value: string | number) => {
    setLines((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
    if (fieldErrors[`lines.${index}.${field}`]?.length) {
      setFieldErrors((prev) => ({ ...prev, [`lines.${index}.${field}`]: [] }));
    }
  };

  const handlePaymentChange = (index: number, field: keyof PaymentInput, value: string) => {
    setPayments((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
    if (fieldErrors[`payments.${index}.${field}`]?.length) {
      setFieldErrors((prev) => ({ ...prev, [`payments.${index}.${field}`]: [] }));
    }
  };

  const addLine = () => {
    setLines((prev) => [...prev, { product: 0, quantity: "", unit_price: undefined }]);
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

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    try {
      const cleanedLines = lines
        .filter((l) => l.product && l.quantity)
        .map((l) => ({
          product: Number(l.product),
          quantity: l.quantity,
          unit_price: l.unit_price ? String(l.unit_price) : undefined,
        }));

      const cleanedPayments = payments
        .filter((p) => p.method && p.amount)
        .map((p) => ({
          method: p.method,
          amount: String(p.amount),
        }));

      await createSale({
        lines: cleanedLines,
        payments: cleanedPayments,
      });
      router.push("/sales");
    } catch (caught) {
      const error = caught as ApiError;
      if (isValidationError(error) && error.details) {
        setFieldErrors(error.details);
      } else {
        setFormError(error.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (productsLoading) {
    return (
      <FormShell title="New Sale" subtitle="Loading products…">
        <div className="flex items-center justify-center py-8 text-ink-secondary">Loading…</div>
      </FormShell>
    );
  }

  return (
    <FormShell title="New Sale" subtitle="Record a sale with lines and payments.">
      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <FormError
          error={
            formError
              ? new ApiErrorClass(0, { code: "form_error", message: formError, details: null })
              : null
          }
        />

        <section>
          <h2 className="text-lg font-semibold text-ink mb-4">Lines</h2>
          <div className="flex flex-col gap-3">
            {lines.map((line, index) => (
              <div key={index} className="flex flex-col sm:flex-row gap-3 items-end">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-col gap-1">
                    <label className="text-sm font-medium text-ink">Product</label>
                    <select
                      value={String(line.product)}
                      onChange={(e) => handleLineChange(index, "product", Number(e.target.value))}
                      autoComplete="off"
                      className={selectClasses}
                      aria-invalid={(fieldErrors[`lines.${index}.product`] ?? []).length > 0}
                    >
                      <option value="0">Select a product</option>
                      {groupedProducts.map((group) => (
                        <optgroup key={group.categoryId} label={group.categoryName}>
                          {group.products.map((p) => (
                            <option key={p.id} value={String(p.id)}>
                              {p.name} ({p.sku}) —{" "}
                              {p.current_price
                                ? `${p.current_price.unit_price} ${p.current_price.currency}`
                                : "no price"}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                    {(fieldErrors[`lines.${index}.product`] ?? []).map((message) => (
                      <p key={message} className="text-xs text-danger">
                        {message}
                      </p>
                    ))}
                  </div>
                </div>
                <div className="w-32">
                  <Field
                    label="Qty"
                    type="number"
                    value={line.quantity}
                    onChange={(value) => handleLineChange(index, "quantity", value)}
                    errors={fieldErrors[`lines.${index}.quantity`] ?? []}
                    autoComplete="off"
                  />
                </div>
                <div className="w-40">
                  <Field
                    label="Unit Price (optional)"
                    type="number"
                    value={line.unit_price ?? ""}
                    onChange={(value) => handleLineChange(index, "unit_price", value)}
                    errors={fieldErrors[`lines.${index}.unit_price`] ?? []}
                    autoComplete="off"
                    hint="Leave blank for current price"
                  />
                </div>
                {lines.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeLine(index)}
                    className="text-danger hover:text-danger/80 text-sm"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={addLine}
            className="rounded border border-border bg-surface px-4 py-2 text-sm text-ink hover:bg-surface/50 self-start"
          >
            Add Line
          </button>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-ink mb-4">Payments</h2>
          <div className="flex flex-col gap-3">
            {payments.map((payment, index) => (
              <div key={index} className="flex flex-col sm:flex-row gap-3 items-end">
                <div className="w-48">
                  <div className="flex flex-col gap-1">
                    <label className="text-sm font-medium text-ink">Method</label>
                    <select
                      value={payment.method}
                      onChange={(e) => handlePaymentChange(index, "method", e.target.value)}
                      className={selectClasses}
                      aria-invalid={(fieldErrors[`payments.${index}.method`] ?? []).length > 0}
                    >
                      <option value="CASH">Cash</option>
                      <option value="MOBILE_BANKING">Mobile Banking</option>
                    </select>
                    {(fieldErrors[`payments.${index}.method`] ?? []).map((message) => (
                      <p key={message} className="text-xs text-danger">
                        {message}
                      </p>
                    ))}
                  </div>
                </div>
                <div className="w-48">
                  <Field
                    label="Amount"
                    type="number"
                    value={payment.amount}
                    onChange={(value) => handlePaymentChange(index, "amount", value)}
                    errors={fieldErrors[`payments.${index}.amount`] ?? []}
                    autoComplete="off"
                  />
                </div>
                {payments.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removePayment(index)}
                    className="text-danger hover:text-danger/80 text-sm"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={addPayment}
            className="rounded border border-border bg-surface px-4 py-2 text-sm text-ink hover:bg-surface/50 self-start"
          >
            Add Payment
          </button>
        </section>

        <FormError
          error={
            formError
              ? new ApiErrorClass(0, { code: "form_error", message: formError, details: null })
              : null
          }
        />

        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-brand px-4 py-2 text-sm font-medium text-ivory transition-colors hover:bg-brand-deep disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {submitting ? "Recording Sale…" : "Record Sale"}
        </button>
      </form>
    </FormShell>
  );
}
