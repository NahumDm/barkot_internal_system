"use client";

import { useEffect, useState } from "react";

import { listInventoryProducts } from "@/lib/api/inventory";
import type { ProductListItem } from "@/lib/api/products";
import type { ApiError } from "@/lib/api/errors";
import { crateLabel, crateSize, parseBottles } from "@/lib/crates";
import { useT } from "@/lib/i18n/context";

/** The "On hand" wording: crates for a crated product, raw quantity otherwise. */
function onHandLabel(product: ProductListItem): string {
  const crate = crateSize(product);
  const bottles = parseBottles(product.current_stock);
  if (crate === null || bottles === null) return product.current_stock ?? "-";
  const label = crateLabel(bottles, crate);
  return bottles % crate === 0 ? `${label} (${bottles} bottles)` : label;
}

export default function InventoryOverview() {
  const t = useT();
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listInventoryProducts()
      .then((response) => {
        if (active) {
          setProducts(response.results);
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
  }, []);

  return (
    <section className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          {t("inventory.eyebrow")}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{t("inventory.stockOverviewTitle")}</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          {t("inventory.stockOverviewBlurb")}
        </p>
      </div>
      {error && <p className="form-error">{error.message}</p>}
      {loading && <p className="text-sm text-ink-secondary">{t("inventory.loadingStock")}</p>}
      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("inventory.colName")}</th>
              <th className="px-3 py-3">{t("inventory.colSku")}</th>
              <th className="px-3 py-3">{t("inventory.colUnit")}</th>
              <th className="px-3 py-3">{t("inventory.colOnHand")}</th>
              <th className="px-3 py-3">{t("inventory.colPrice")}</th>
            </tr>
          </thead>
          <tbody>
            {products.map((product) => (
              <tr key={product.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3 font-medium text-ink">{product.name}</td>
                <td className="px-3 py-3 font-mono text-ink-secondary">{product.sku}</td>
                <td className="px-3 py-3 text-ink-secondary">{product.unit}</td>
                <td className="px-3 py-3 font-semibold text-ink">{onHandLabel(product)}</td>
                <td className="px-3 py-3 text-ink-secondary">
                  {product.current_price
                    ? `${product.current_price.unit_price} ${product.current_price.currency}${
                        crateSize(product) ? t("inventory.perBottle") : ""
                      }`
                    : t("inventory.unpriced")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && products.length === 0 && !error && (
          <p className="p-6 text-center text-sm text-ink-secondary">{t("inventory.noTrackedProducts")}</p>
        )}
      </div>
    </section>
  );
}
