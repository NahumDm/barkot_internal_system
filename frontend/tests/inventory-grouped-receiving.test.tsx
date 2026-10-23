/**
 * Grouped stock receiving screen (shared selling-price delivery).
 *
 * The backend is authoritative about prices and crate conversions; these tests
 * cover the screen's own job: showing the conversion, summing independent
 * product lines into one bottle total, keeping rows addable/removable, and
 * blocking an incomplete or invalid form before it is sent.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InventoryForm from "@/features/inventory/inventory-forms";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function page<T>(results: T[]) {
  return { count: results.length, page_size: 200, page: 1, pages: 1, results };
}

const PRICE_FROM = "2026-01-01T00:00:00+00:00";

const PRODUCTS = [
  {
    id: 1,
    category: 1,
    category_name: "Beer",
    name: "Heineken",
    sku: "BEER-HEIN-001",
    unit: "bottle",
    quantity_mode: "WHOLE",
    bottles_per_crate: 24,
    is_stock_tracked: true,
    is_active: true,
    current_price: {
      id: 1,
      unit_price: "100.00",
      currency: "ETB",
      effective_from: PRICE_FROM,
      is_active: true,
      created_at: PRICE_FROM,
    },
    current_stock: "0.000",
  },
  {
    id: 2,
    category: 1,
    category_name: "Beer",
    name: "Bedele",
    sku: "BEER-BEDE-001",
    unit: "bottle",
    quantity_mode: "WHOLE",
    bottles_per_crate: 20,
    is_stock_tracked: true,
    is_active: true,
    current_price: {
      id: 2,
      unit_price: "100.00",
      currency: "ETB",
      effective_from: PRICE_FROM,
      is_active: true,
      created_at: PRICE_FROM,
    },
    current_stock: "0.000",
  },
  {
    id: 3,
    category: 2,
    category_name: "Soft drinks",
    name: "Arada",
    sku: "SOFT-ARADA-001",
    unit: "bottle",
    quantity_mode: "WHOLE",
    bottles_per_crate: null,
    is_stock_tracked: true,
    is_active: true,
    current_price: {
      id: 3,
      unit_price: "50.00",
      currency: "ETB",
      effective_from: PRICE_FROM,
      is_active: true,
      created_at: PRICE_FROM,
    },
    current_stock: "0.000",
  },
];

const PRICE_GROUPS = [
  {
    selling_price: "100.00",
    currency: "ETB",
    product_count: 2,
    products: PRODUCTS.slice(0, 2).map((product) => ({
      id: product.id,
      name: product.name,
      sku: product.sku,
      bottles_per_crate: product.bottles_per_crate,
      is_crated: true,
      unit: product.unit,
      selling_price: "100.00",
      currency: "ETB",
    })),
  },
  {
    selling_price: "50.00",
    currency: "ETB",
    product_count: 1,
    products: [
      {
        id: 3,
        name: "Arada",
        sku: "SOFT-ARADA-001",
        bottles_per_crate: null,
        is_crated: false,
        unit: "bottle",
        selling_price: "50.00",
        currency: "ETB",
      },
    ],
  },
];

const RECEIPT = {
  id: 42,
  reference: "",
  supplier_name: "BGI Ethiopia",
  status: "COMPLETED",
  received_at: PRICE_FROM,
  completed_at: PRICE_FROM,
  notes: "",
  items: [],
  created_at: PRICE_FROM,
  updated_at: PRICE_FROM,
};

function stubApi(postResponse = RECEIPT): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const { pathname } = new URL(String(input), "http://localhost");
      if (pathname.endsWith("/inventory/receipts/price-groups/")) {
        return jsonResponse(PRICE_GROUPS);
      }
      if (pathname.endsWith("/products/")) {
        return jsonResponse(page(PRODUCTS));
      }
      if (pathname.endsWith("/inventory/receipts/grouped/")) {
        return jsonResponse(postResponse, 201);
      }
      throw new Error(`Unexpected request to ${pathname}`);
    }),
  );
}

async function renderGrouped() {
  render(<InventoryForm mode="receive" />);
  fireEvent.click(await screen.findByRole("button", { name: /Grouped Receiving/ }));
}

function combinedTotal(): string {
  return screen.getByTestId("grouped-combined-total").textContent!.replace(/\s+/g, " ").trim();
}

beforeEach(() => {
  document.cookie = "csrftoken=test";
  stubApi();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("grouped stock receiving", () => {
  it("keeps standard receiving as the default mode", async () => {
    render(<InventoryForm mode="receive" />);

    expect(await screen.findByLabelText(/Supplier/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save record" })).toBeInTheDocument();
    expect(screen.queryByText(/Shared Selling Price Group/)).not.toBeInTheDocument();
  });

  it("converts each brand's crates with its own bottle count and sums the bottles", async () => {
    await renderGrouped();

    fireEvent.click(screen.getByRole("button", { name: /Add Product Line/ }));

    const brands = screen.getAllByLabelText(/Brand \/ Product/) as HTMLSelectElement[];
    expect(brands.map((select) => select.value)).toEqual(["1", "2"]);

    const crates = screen.getAllByLabelText(/Quantity \(Crates\)/) as HTMLInputElement[];
    fireEvent.change(crates[0], { target: { value: "3" } });
    fireEvent.change(crates[1], { target: { value: "2" } });

    // 3 x 24 + 2 x 20 = 72 + 40 = 112 bottles, kept as separate lines.
    expect(await screen.findByText(/72 bottles/)).toBeInTheDocument();
    expect(screen.getByText(/40 bottles/)).toBeInTheDocument();
    expect(combinedTotal()).toBe("112 bottles");
  });

  it("removes a line and recalculates the combined total", async () => {
    await renderGrouped();
    fireEvent.click(screen.getByRole("button", { name: /Add Product Line/ }));

    const crates = screen.getAllByLabelText(/Quantity \(Crates\)/) as HTMLInputElement[];
    fireEvent.change(crates[0], { target: { value: "3" } });
    fireEvent.change(crates[1], { target: { value: "2" } });

    fireEvent.click(screen.getAllByTitle("Remove line")[1]);

    expect(screen.getAllByLabelText(/Quantity \(Crates\)/)).toHaveLength(1);
    expect(combinedTotal()).toBe("72 bottles");
  });

  it("shows a validation message and blocks saving for an invalid quantity", async () => {
    await renderGrouped();

    const crates = screen.getByLabelText(/Quantity \(Crates\)/) as HTMLInputElement;
    fireEvent.change(crates, { target: { value: "0" } });

    expect(await screen.findByText(/Invalid crate quantity for Heineken/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Grouped Receipt/ })).toBeDisabled();
  });

  it("sends the shared price group and each line's crates and cost", async () => {
    await renderGrouped();

    fireEvent.change(screen.getByLabelText(/Supplier/), {
      target: { value: "BGI Ethiopia" },
    });
    fireEvent.change(screen.getByLabelText(/Quantity \(Crates\)/), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText(/Crate Cost/), {
      target: { value: "720.00" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Save Grouped Receipt/ }));

    await waitFor(() => expect(screen.getByText(/Receipt #42 recorded/)).toBeInTheDocument());

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST",
    );
    expect(postCall).toBeDefined();
    const body = JSON.parse((postCall![1] as RequestInit).body as string);
    expect(body.selling_price).toBe("100.00");
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThan(10);
    expect(body.lines).toEqual([{ product: 1, crates: "3", crate_cost: "720.00" }]);
  });
});
