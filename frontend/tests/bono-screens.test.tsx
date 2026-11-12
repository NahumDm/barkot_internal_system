/**
 * Bono screens: role-aware controls and the independent report columns.
 *
 * These stub `fetch`, not the API module, so a wrong URL still fails. They also
 * prove what is *not* requested: a Barman's read-only ledger must not call the
 * employee register or product-catalogue endpoints to paint a form they cannot
 * use.
 */

import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BonoConfigurationPage from "@/features/bono/bono-configuration";
import BonoOverviewPage from "@/features/bono/bono-overview";
import BonoReportDetailPage from "@/features/bono/bono-report-detail";
import BonoReportsPage from "@/features/bono/bono-reports";
import { AuthProvider } from "@/features/auth/auth-provider";
import type { AuthUser } from "@/lib/api/auth";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/bono",
}));

const BASE_USER: AuthUser = {
  id: 4,
  username: "e2e-barman",
  display_name: "Bereket Barman",
  role: "barman",
  role_name: "Barman",
  permissions: ["bono.view_bono"],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const BONO_TYPE = {
  id: 1,
  code: "11111111-1111-1111-1111-111111111111",
  name: "House Bono",
  color: "#8E192F",
  selling_price: "100.00",
  currency: "ETB",
  is_active: true,
  notes: "",
  active_pairings: [],
  pending_review_count: 0,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
};

const SUMMARY = {
  operational_date: "2026-10-23",
  day_status: "OPEN",
  operations_locked: false,
  bono_totals: [
    {
      bono_type_id: 1,
      bono_code: BONO_TYPE.code,
      bono_name: "House Bono",
      bono_color: "#8E192F",
      initial_issued: 6,
      additional_issued: 1,
      total_issued: 7,
      transfers_in: 1,
      transfers_out: 1,
      lost: 1,
    },
  ],
  staff_balances: [
    {
      employee_id: 9,
      employee_name: "Abebe Bekele",
      employee_position: "Waiter",
      bono_type_id: 1,
      bono_name: "House Bono",
      bono_color: "#8E192F",
      issued: 7,
      transfers_in: 1,
      transfers_out: 1,
      lost: 1,
      balance: 5,
    },
  ],
  latest_report: null,
  in_progress_dates: [],
};

const REPORT = {
  id: 7,
  operational_date: "2026-10-23",
  revision: 1,
  corrects: null,
  correction_reason: "",
  status: "SUBMITTED",
  status_display: "Submitted",
  submitted_by_name: "Chaltu Cashier",
  submitted_at: "2026-10-23T18:00:00+00:00",
  approved_by_name: "",
  approved_at: null,
  rejected_by_name: "",
  rejected_at: null,
  rejection_reason: "",
  notes: "",
  sales_total: "400.00",
  cash_paid_total: "300.00",
  mobile_paid_total: "100.00",
  payments_total: "400.00",
  currency: "ETB",
  activity_generated_at: "2026-10-23T17:55:00+00:00",
  created_at: "2026-10-23T17:00:00+00:00",
  updated_at: "2026-10-23T18:00:00+00:00",
  bono_lines: [
    {
      id: 11,
      bono_type: 1,
      bono_code_snapshot: BONO_TYPE.code,
      bono_name_snapshot: "House Bono",
      bono_color_snapshot: "#8E192F",
      bono_price_snapshot: "100.00",
      currency: "ETB",
      initial_issued_quantity: 6,
      additional_issued_quantity: 1,
      total_issued_quantity: 7,
      transfers_in_quantity: 1,
      transfers_out_quantity: 1,
      lost_quantity: 1,
      used_quantity: 5,
      returned_quantity: 0,
      accounted_quantity: 6,
      discrepancy_quantity: 1,
      explanation: "One short",
    },
  ],
  product_lines: [
    {
      id: 21,
      product: 1,
      product_name_snapshot: "Heineken",
      product_sku_snapshot: "BEER-HEIN-001",
      bono_type: 1,
      bono_name_snapshot: "House Bono",
      bono_color_snapshot: "#8E192F",
      opening_quantity: "40.000",
      received_quantity: "0.000",
      other_addition_quantity: "0.000",
      sold_quantity: "5.000",
      breakage_quantity: "1.000",
      other_loss_quantity: "0.000",
      expected_closing_quantity: "34.000",
      physical_closing_quantity: "34.000",
      variance_quantity: "0.000",
      explanation: "",
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function page<T>(results: T[]) {
  return { count: results.length, page_size: 100, page: 1, pages: 1, results };
}

let requested: string[] = [];

function stubApi(
  routes: Array<[string, () => Response]>,
  permissions: string[] = ["bono.view_bono"],
): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: string | URL | Request) => {
      const { pathname } = new URL(String(input), "http://localhost");
      requested.push(pathname);
      const match = [...routes]
        .sort((left, right) => right[0].length - left[0].length)
        .find(([suffix]) => pathname.endsWith(suffix));
      if (match === undefined) {
        requested.push(`UNMATCHED ${pathname}`);
        throw new Error(`Unexpected request to ${pathname}`);
      }
      return match[1]();
    },
  );
  routes.push(["/auth/me/", () => jsonResponse({ user: { ...BASE_USER, permissions } })]);
}

function renderScreen(node: ReactNode) {
  return render(<AuthProvider>{node}</AuthProvider>);
}

beforeEach(() => {
  requested = [];
  document.cookie = "csrftoken=test";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Bono overview", () => {
  it("shows custody to a Barman without drawing or fetching an operations form", async () => {
    stubApi([
      ["/bono/summary/", () => jsonResponse(SUMMARY)],
      ["/bono/types/", () => jsonResponse(page([BONO_TYPE]))],
      ["/bono/issues/", () => jsonResponse(page([]))],
      ["/bono/transfers/", () => jsonResponse(page([]))],
      ["/bono/incidents/", () => jsonResponse(page([]))],
    ]);

    renderScreen(<BonoOverviewPage />);

    await screen.findByRole("heading", { name: "Custody and daily reconciliation" });
    expect(await screen.findByText("Abebe Bekele")).toBeInTheDocument();
    expect(screen.getByText("In staff custody")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Custody actions" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Prepare report" })).toBeNull();
    expect(requested.filter((path) => path.includes("/employees/"))).toEqual([]);
    expect(requested.filter((path) => path.includes("/products/"))).toEqual([]);
  });

  it("does not request configuration data for a role without configuration", async () => {
    stubApi([]);

    renderScreen(<BonoConfigurationPage />);

    await screen.findByText(/Your role does not include Bono configuration/);
    expect(requested.filter((path) => path.includes("/bono/"))).toEqual([]);
    expect(requested.filter((path) => path.includes("/products/"))).toEqual([]);
  });
});

describe("Bono reports", () => {
  it("offers report preparation to a Cashier and lists existing reports", async () => {
    stubApi(
      [["/bono/reports/", () => jsonResponse(page([REPORT]))]],
      ["bono.view_bono", "bono.submit_report"],
    );

    renderScreen(<BonoReportsPage />);

    await screen.findByRole("heading", { name: "Daily reports" });
    expect(await screen.findByText("Prepare a report")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
    expect(screen.getAllByText("Submitted").length).toBeGreaterThan(0);
  });

  it("offers approval only to a role that may approve", async () => {
    stubApi(
      [["/bono/reports/7/", () => jsonResponse(REPORT)]],
      ["bono.view_bono", "bono.approve_report"],
    );

    renderScreen(<BonoReportDetailPage reportId={7} />);

    await screen.findByRole("button", { name: "Approve report" });
    expect(screen.getByRole("button", { name: "Reject report" })).toBeInTheDocument();
    expect(screen.getByText("Bono accountability")).toBeInTheDocument();
    expect(screen.getByText("Heineken")).toBeInTheDocument();
  });

  it("keeps a submitted report read-only for a Cashier and hides money from a Barman", async () => {
    stubApi(
      [["/bono/reports/7/", () => jsonResponse(REPORT)]],
      ["bono.view_bono", "bono.submit_report"],
    );
    renderScreen(<BonoReportDetailPage reportId={7} />);
    await screen.findByText(
      "This report is waiting for the Owner. The day stays locked until it is approved or rejected.",
    );
    expect(screen.queryByRole("button", { name: "Approve report" })).toBeNull();

    cleanup();
    const withoutMoney = { ...REPORT };
    delete (withoutMoney as { sales_total?: string }).sales_total;
    delete (withoutMoney as { cash_paid_total?: string }).cash_paid_total;
    delete (withoutMoney as { mobile_paid_total?: string }).mobile_paid_total;
    delete (withoutMoney as { payments_total?: string }).payments_total;
    delete (withoutMoney as { currency?: string }).currency;
    stubApi([["/bono/reports/7/", () => jsonResponse(withoutMoney)]]);
    renderScreen(<BonoReportDetailPage reportId={7} />);
    await screen.findByText("Bono accountability");
    expect(screen.queryByText("Payments total")).toBeNull();
    expect(screen.queryByText("400.00 ETB")).toBeNull();
  });
});
