"use client";

import { useEffect, useState } from "react";

import { listStockMovements, type StockMovement } from "@/lib/api/inventory";
import type { ApiError } from "@/lib/api/errors";

export default function MovementList() {
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    listStockMovements({ query: { page_size: 100 } })
      .then((response) => setMovements(response.results))
      .catch((value: unknown) => setError(value as ApiError));
  }, []);

  return (
    <section className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          Inventory
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Stock movements</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          Append-only history of every stock change.
        </p>
      </div>
      {error && <p className="form-error">{error.message}</p>}
      <div className="overflow-x-auto rounded border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-canvas text-xs uppercase tracking-wider text-ink-secondary">
            <tr>
              <th className="px-3 py-3">When</th>
              <th className="px-3 py-3">Product</th>
              <th className="px-3 py-3">Kind</th>
              <th className="px-3 py-3">Quantity</th>
              <th className="px-3 py-3">Reason</th>
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
        {movements.length === 0 && !error && (
          <p className="p-6 text-center text-sm text-ink-secondary">No stock movements found.</p>
        )}
      </div>
    </section>
  );
}
