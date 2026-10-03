"use client";

import { useEffect, useState, type FormEvent, type ChangeEvent } from "react";
import { useRouter } from "next/navigation";

import { createProduct, listCategories, type Category } from "@/lib/api/products";
import {
  type ApiError,
  type ErrorDetails,
  isValidationError,
  ApiError as ApiErrorClass,
} from "@/lib/api/errors";
import { Field, FormError, FormShell } from "@/features/auth/form-parts";

export default function NewProductPage() {
  const router = useRouter();

  const [categories, setCategories] = useState<Category[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);

  const [formData, setFormData] = useState({
    category: "",
    name: "",
    sku: "",
    unit: "bottle",
    is_stock_tracked: true,
    description: "",
  });

  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let mounted = true;
    listCategories({ query: { active: true } })
      .then((response) => {
        if (mounted) {
          setCategories(response.results);
          setCategoriesLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setCategoriesLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleChange = (name: string, value: string | boolean) => {
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
    if (fieldErrors[name]?.length) {
      setFieldErrors((prev) => ({ ...prev, [name]: [] }));
    }
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    try {
      const product = await createProduct({
        ...formData,
        category: Number(formData.category),
        is_stock_tracked: formData.is_stock_tracked,
      });
      router.push(`/inventory/products`);
    } catch (caught) {
      const error = caught as ApiError;
      if (isValidationError(error) && error.details) {
        setFieldErrors(error.details as ErrorDetails);
      } else {
        setFormError(error.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (categoriesLoading) {
    return (
      <FormShell title="Add Product" subtitle="Loading categories…">
        <div className="flex items-center justify-center py-8 text-ink-secondary">Loading…</div>
      </FormShell>
    );
  }

  return (
    <FormShell title="Add Product" subtitle="Create a new sellable product in the catalogue.">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <FormError
          error={
            formError
              ? new ApiErrorClass(0, { code: "form_error", message: formError, details: null })
              : null
          }
        />

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-ink">Category</label>
          <select
            value={formData.category}
            onChange={(e) => handleChange("category", e.target.value)}
            autoComplete="off"
            className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
            aria-invalid={fieldErrors.category.length > 0}
          >
            <option value="">Select a category</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
          {fieldErrors.category.map((message) => (
            <p key={message} className="text-xs text-danger">
              {message}
            </p>
          ))}
        </div>

        <Field
          label="Name"
          type="text"
          value={formData.name}
          onChange={(value) => handleChange("name", value)}
          errors={fieldErrors.name ?? []}
          autoComplete="off"
          autoFocus
          disabled={submitting}
          hint="Unique within the selected category"
        />

        <Field
          label="SKU"
          type="text"
          value={formData.sku}
          onChange={(value) => handleChange("sku", value)}
          errors={fieldErrors.sku ?? []}
          autoComplete="off"
          disabled={submitting}
          hint="Stable internal code, never reused"
        />

        <Field
          label="Unit"
          type="text"
          value={formData.unit}
          onChange={(value) => handleChange("unit", value)}
          errors={fieldErrors.unit ?? []}
          autoComplete="off"
          disabled={submitting}
          hint="e.g. bottle, crate, kg, litre"
        />

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            name="is_stock_tracked"
            id="is_stock_tracked"
            checked={formData.is_stock_tracked}
            onChange={(e) => handleChange("is_stock_tracked", e.target.checked)}
            disabled={submitting}
            className="rounded border-border text-ink focus:ring-ink"
          />
          <label htmlFor="is_stock_tracked" className="text-sm text-ink">
            Track stock in inventory ledger
          </label>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-ink">Description</label>
          <textarea
            value={formData.description}
            onChange={(e) => handleChange("description", e.target.value)}
            autoComplete="off"
            disabled={submitting}
            className="rounded border border-border bg-surface px-3 py-2 text-sm text-ink"
            aria-invalid={fieldErrors.description.length > 0}
          />
          {fieldErrors.description.map((message) => (
            <p key={message} className="text-xs text-danger">
              {message}
            </p>
          ))}
        </div>

        <button
          type="submit"
          disabled={submitting || !formData.category}
          className="rounded bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {submitting ? "Creating…" : "Create Product"}
        </button>
      </form>
    </FormShell>
  );
}
