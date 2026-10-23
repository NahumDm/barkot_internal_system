"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import {
  createProduct,
  listCategories,
  setProductPrice,
  type Category,
  type QuantityMode,
} from "@/lib/api/products";
import {
  type ApiError,
  type ErrorDetails,
  isValidationError,
  ApiError as ApiErrorClass,
} from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { Field, FormError } from "@/features/auth/form-parts";

export default function NewProductPage() {
  const router = useRouter();
  const { status, user } = useAuth();
  const canManage = user?.permissions.includes("products.manage_products") ?? false;
  const canChangePrices = user?.permissions.includes("products.change_prices") ?? false;

  const [categories, setCategories] = useState<Category[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    category: "",
    name: "",
    sku: "",
    unit: "bottle",
    quantity_mode: "WHOLE",
    bottles_per_crate: "",
    is_stock_tracked: true,
    description: "",
    price: "",
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
      .catch((caught: unknown) => {
        if (mounted) {
          setCategoriesError((caught as ApiError).message);
          setCategoriesLoading(false);
        }
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

    const price = formData.price.trim();
    if (canChangePrices && price !== "" && !/^\d+(\.\d{1,2})?$/.test(price)) {
      setFieldErrors({ price: ["Enter a price like 120.00."] });
      setSubmitting(false);
      return;
    }

    const crateSize = formData.bottles_per_crate.trim();
    if (crateSize !== "" && (!/^\d+$/.test(crateSize) || Number(crateSize) < 2)) {
      setFieldErrors({
        bottles_per_crate: ["Enter a whole number of bottles, like 24, or leave it blank."],
      });
      setSubmitting(false);
      return;
    }

    try {
      const product = await createProduct({
        category: Number(formData.category),
        name: formData.name,
        sku: formData.sku,
        unit: formData.unit,
        quantity_mode: formData.quantity_mode as QuantityMode,
        bottles_per_crate: crateSize === "" ? null : Number(crateSize),
        is_stock_tracked: formData.is_stock_tracked,
        description: formData.description,
      });
      if (canChangePrices && price !== "") {
        try {
          await setProductPrice(product.id, { unit_price: price, currency: "ETB" });
        } catch (caught) {
          const error = caught as ApiError;
          setFormError(
            `The product was created, but its price could not be saved: ${error.message} ` +
              "Open the product to set the price.",
          );
          setSubmitting(false);
          return;
        }
      }
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

  if (status === "checking") {
    return (
      <section className="flex items-center justify-center py-8 text-ink-secondary">
        Checking access...
      </section>
    );
  }

  if (!canManage) {
    return (
      <section className="space-y-4">
        <header>
          <h1 className="page-title text-2xl font-semibold tracking-tight text-ink">Add Product</h1>
        </header>
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include managing the product catalogue. Ask an owner if you need
          access.
        </div>
      </section>
    );
  }

  if (categoriesLoading) {
    return (
      <section className="flex items-center justify-center py-8 text-ink-secondary">
        Loading…
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-6">
      <header>
        <h1 className="page-title text-2xl font-semibold tracking-tight text-ink">Add Product</h1>
        <p className="page-subtitle mt-1 text-sm text-ink-secondary">
          Create a new sellable product in the catalogue.
        </p>
      </header>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {categoriesError && <p className="form-error">{categoriesError}</p>}
        <FormError
          error={
            formError
              ? new ApiErrorClass(0, { code: "form_error", message: formError, details: null })
              : null
          }
        />

        <div className="field">
          <label className="field-label">Category</label>
          <select
            value={formData.category}
            onChange={(e) => handleChange("category", e.target.value)}
            autoComplete="off"
            className="control"
            aria-invalid={(fieldErrors.category?.length ?? 0) > 0}
          >
            <option value="">Select a category</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
          {(fieldErrors.category ?? []).map((message) => (
            <p key={message} className="field-error">
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

        <Field
          label="Bottles per crate"
          type="number"
          value={formData.bottles_per_crate}
          onChange={(value) => handleChange("bottles_per_crate", value)}
          errors={fieldErrors.bottles_per_crate ?? []}
          autoComplete="off"
          disabled={submitting}
          min={2}
          step={1}
          inputMode="numeric"
          hint="e.g. 24. Leave blank if this product is not sold by the crate."
        />

        <div className="field">
          <label className="field-label">Quantity mode</label>
          <select
            value={formData.quantity_mode}
            onChange={(e) => handleChange("quantity_mode", e.target.value)}
            disabled={submitting}
            className="control"
            aria-invalid={(fieldErrors.quantity_mode?.length ?? 0) > 0}
          >
            <option value="WHOLE">Whole units (e.g. crates, bottles)</option>
            <option value="FRACTIONAL">Fractional units (e.g. kg, litre)</option>
          </select>
          {(fieldErrors.quantity_mode ?? []).map((message) => (
            <p key={message} className="field-error">
              {message}
            </p>
          ))}
          <p className="field-hint">
            Whole units are counted in whole numbers only; fractional units allow decimals.
          </p>
        </div>

        {canChangePrices && (
          <Field
            label="Selling price (ETB)"
            type="number"
            value={formData.price}
            onChange={(value) => handleChange("price", value)}
            errors={fieldErrors.price ?? []}
            autoComplete="off"
            disabled={submitting}
            min={0}
            step="0.01"
            inputMode="decimal"
            hint="Optional. A product needs a price before it can be sold."
          />
        )}

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

        <div className="field">
          <label className="field-label">Description</label>
          <textarea
            value={formData.description}
            onChange={(e) => handleChange("description", e.target.value)}
            autoComplete="off"
            disabled={submitting}
            className="control"
            aria-invalid={(fieldErrors.description?.length ?? 0) > 0}
          />
          {(fieldErrors.description ?? []).map((message) => (
            <p key={message} className="field-error">
              {message}
            </p>
          ))}
        </div>

        <div className="form-actions">
          <button
            type="submit"
            disabled={submitting || !formData.category}
            className="btn btn-primary"
          >
            {submitting ? "Creating…" : "Create Product"}
          </button>
        </div>
      </form>
    </section>
  );
}
