"use client";

import { useEffect, useState } from "react";

import { listStockMovements, type StockMovement } from "@/lib/api/inventory";
import { useT } from "@/lib/i18n/context";
import type { ApiError } from "@/lib/api/errors";

export default function MovementList() {
  const t = useT();
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listStockMovements({ query: { page_size: 100 } })
      .then((response) => {
        if (active) setMovements(response.results);
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
          Inventory
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{t("inventory.movementsTitle")}</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          Append-only history of every stock change.
        </p>
      </div>
      {error && <p className="form-error">{error.message}</p>}
      {loading && <p className="text-sm text-ink-secondary">Loading movements...</p>}
      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">{t("inventory.mvColWhen")}</th>
              <th className="px-3 py-3">{t("inventory.mvColProduct")}</th>
              <th className="px-3 py-3">{t("inventory.mvColKind")}</th>
              <th className="px-3 py-3">{t("inventory.mvColQuantity")}</th>
              <th className="px-3 py-3">{t("inventory.mvColReason")}</th>
            </tr>
          </thead>
          <tbody>
            {movements.map((movement) => (
              <tr key={movement.id} className="border-b border-border last:border-0">
                <td className="px-3 py-3">{new Date(movement.occurred_at).toLocaleString()}</td>
                <td className="px-3 py-3 font-medium text-ink">{movement.product_name}</td>
                <td className="px-3 py-3">{movement.kind}</td>
                <td
                  className={`px-3 py-3 font-semibold ${movement.direction === "IN" ? "text-emerald-700" : "text-danger"}`}
                >
                  {movement.direction === "IN" ? "+" : "-"}
                  {movement.quantity}
                </td>
                <td className="px-3 py-3 text-ink-secondary">
                  {movement.reason || movement.source}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && movements.length === 0 && !error && (
          <p className="p-6 text-center text-sm text-ink-secondary">{t("inventory.noMovements")}</p>
        )}
      </div>
    </section>
  );
}
