"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  createCategory,
  deleteCategory,
  listCategories,
  updateCategory,
  type Category,
} from "@/lib/api/products";
import { type ApiError, type ErrorDetails, isValidationError } from "@/lib/api/errors";
import { useAuth } from "@/features/auth/auth-provider";
import { Field } from "@/features/auth/form-parts";
import {
  EmptyNote,
  ErrorBanner,
  LoadingNote,
  PageHeader,
  StatusChip,
} from "@/features/payroll/parts";

/**
 * The category manager (roadmap B4): the grouping screen behind the product
 * catalogue. It is the only surface for ``products.manage_categories``, so the
 * permission gate below is convenience — the API refuses a write from any role
 * that does not hold it, and every action surfaces the refusal it gets back.
 *
 * The API allows deletion only while no product points at a category, so the
 * row disables delete once `product_count` is non-zero rather than letting the
 * user meet a refusal they could have been told about up front.
 */

export default function CategoriesPage() {
  const { status, user } = useAuth();
  const granted = user?.permissions ?? [];
  const allowed = granted.includes("products.manage_categories");
  const checking = status === "checking";

  return (
    <section className="space-y-6">
      <PageHeader
        eyebrow="Inventory"
        title="Categories"
        blurb="Group products into categories such as Beer or Spirits."
      />
      {checking ? (
        <LoadingNote label="Checking access..." />
      ) : !allowed ? (
        <div className="rounded border border-border bg-surface p-6 text-sm text-ink-secondary">
          Your role does not include managing product categories. Ask an owner if you need access.
        </div>
      ) : (
        <CategoryManager />
      )}
    </section>
  );
}

function CategoryManager() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    listCategories({ query: { page_size: 200 } })
      .then((value) => {
        if (active) {
          setCategories(value.results);
          setError(null);
        }
      })
      .catch((value: unknown) => {
        if (active) setError(value as ApiError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refresh]);

  const reload = () => {
    setLoading(true);
    setRefresh((value) => value + 1);
  };

  return (
    <section className="space-y-4">
      <div className="rounded border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">Categories</h2>
        <p className="text-xs text-ink-secondary">
          Inactive categories are hidden from pickers but keep their products.
        </p>
        <div className="mt-4">
          <ErrorBanner error={error} />
          {loading && <LoadingNote label="Loading categories..." />}
          {!loading && !error && categories.length === 0 && (
            <EmptyNote>No categories yet. Add the first one below.</EmptyNote>
          )}
          {!loading && categories.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-ink-secondary">
                    <Th>Name</Th>
                    <Th>Description</Th>
                    <Th>Order</Th>
                    <Th>Products</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((category) => (
                    <CategoryRow
                      key={category.id}
                      category={category}
                      onChanged={reload}
                      onDeleted={(id) =>
                        setCategories((current) => current.filter((item) => item.id !== id))
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <CategoryForm onCreated={reload} />
    </section>
  );
}

function CategoryRow({
  category,
  onChanged,
  onDeleted,
}: {
  category: Category;
  onChanged: () => void;
  onDeleted: (id: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(category.name);
  const [draftDescription, setDraftDescription] = useState(category.description);
  const [draftOrder, setDraftOrder] = useState(String(category.display_order));
  const [draftActive, setDraftActive] = useState(category.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const openEdit = () => {
    setDraftName(category.name);
    setDraftDescription(category.description);
    setDraftOrder(String(category.display_order));
    setDraftActive(category.is_active);
    setError(null);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setError(null);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await updateCategory(category.id, {
        name: draftName,
        description: draftDescription,
        display_order: Number(draftOrder) || 0,
        is_active: draftActive,
      });
      setEditing(false);
      onChanged();
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete the category "${category.name}"? This cannot be undone.`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteCategory(category.id);
      onDeleted(category.id);
    } catch (value) {
      setError(value as ApiError);
    } finally {
      setSaving(false);
    }
  };

  const hasProducts = category.product_count > 0;

  return (
    <>
      {error && (
        <tr>
          <td colSpan={6} className="py-2">
            <p className="form-error">{error.message}</p>
          </td>
        </tr>
      )}
      <tr className="border-b border-border last:border-0">
        <td className="py-2 pr-3">
          {editing ? (
            <input
              type="text"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              disabled={saving}
              autoComplete="off"
              className="control"
            />
          ) : (
            <span className="font-medium text-ink">{category.name}</span>
          )}
        </td>
        <td className="py-2 pr-3">
          {editing ? (
            <input
              type="text"
              value={draftDescription}
              onChange={(event) => setDraftDescription(event.target.value)}
              disabled={saving}
              autoComplete="off"
              className="control"
            />
          ) : (
            <span className="text-ink-secondary">{category.description || "—"}</span>
          )}
        </td>
        <td className="py-2 pr-3">
          {editing ? (
            <input
              type="number"
              value={draftOrder}
              onChange={(event) => setDraftOrder(event.target.value)}
              disabled={saving}
              className="control"
            />
          ) : (
            <span className="text-ink">{category.display_order}</span>
          )}
        </td>
        <td className="py-2 pr-3 text-ink">{category.product_count}</td>
        <td className="py-2 pr-3">
          {editing ? (
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={draftActive}
                onChange={(event) => setDraftActive(event.target.checked)}
                disabled={saving}
                className="accent-ink"
              />
              Active
            </label>
          ) : (
            <StatusChip
              status={category.is_active ? "ACTIVE" : "INACTIVE"}
              display={category.is_active ? "Active" : "Inactive"}
            />
          )}
        </td>
        <td className="py-2 text-right">
          {editing ? (
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={cancelEdit}
                disabled={saving}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button type="button" onClick={save} disabled={saving} className="btn btn-primary">
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <button type="button" onClick={openEdit} className="btn btn-secondary">
                Edit
              </button>
              <button
                type="button"
                onClick={remove}
                disabled={saving || hasProducts}
                title={hasProducts ? "Move or delete this category's products first." : undefined}
                className="btn btn-ghost"
              >
                Delete
              </button>
            </div>
          )}
        </td>
      </tr>
    </>
  );
}

function CategoryForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [displayOrder, setDisplayOrder] = useState("0");
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setFieldErrors({});
    try {
      await createCategory({
        name,
        description,
        display_order: Number(displayOrder) || 0,
        is_active: isActive,
      });
      setName("");
      setDescription("");
      setDisplayOrder("0");
      setIsActive(true);
      onCreated();
    } catch (value) {
      const caught = value as ApiError;
      if (isValidationError(caught) && caught.details) {
        setFieldErrors(caught.details as ErrorDetails);
      } else {
        setError(caught);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">Add a category</h2>
      <p className="text-xs text-ink-secondary">
        Names are unique, ignoring case. Lower display order sorts first.
      </p>
      <form onSubmit={submit} className="mt-3 space-y-3">
        <ErrorBanner error={error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Name"
            type="text"
            value={name}
            onChange={setName}
            errors={fieldErrors.name ?? []}
            autoComplete="off"
            disabled={saving}
            hint="e.g. Beer, Spirits, Soft drinks"
          />
          <Field
            label="Display order"
            type="number"
            value={displayOrder}
            onChange={setDisplayOrder}
            errors={fieldErrors.display_order ?? []}
            autoComplete="off"
            disabled={saving}
          />
        </div>
        <div className="field">
          <label className="field-label">Description</label>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            autoComplete="off"
            disabled={saving}
            className="control"
            aria-invalid={(fieldErrors.description?.length ?? 0) > 0}
          />
          {(fieldErrors.description ?? []).map((message) => (
            <p key={message} className="field-error">
              {message}
            </p>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
            disabled={saving}
            className="accent-ink"
          />
          Active
        </label>
        <div className="flex justify-end">
          <button type="submit" disabled={saving || !name.trim()} className="btn btn-primary">
            {saving ? "Creating..." : "Create category"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <th className={`py-1.5 pr-3 font-medium ${className}`}>{children}</th>;
}
