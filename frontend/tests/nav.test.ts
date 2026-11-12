import { describe, expect, it } from "vitest";
import { navGroups, visibleNavGroups } from "@/components/layout/nav";

describe("sidebar navigation (UX §3.1, spec §7.4)", () => {
  const flat = navGroups.flatMap((group) => group.items);

  it("defines exactly 23 nav items", () => {
    expect(flat).toHaveLength(23);
  });

  it("covers every normative route of spec §7.4 plus the category manager, register and Bono", () => {
    const routes = new Set(flat.map((item) => item.href));
    expect(routes).toEqual(
      new Set([
        "/dashboard",
        "/sales",
        "/sales/transactions",
        "/bono",
        "/bono/reports",
        "/bono/configuration",
        "/inventory",
        "/inventory/products",
        "/inventory/categories",
        "/inventory/receive",
        "/inventory/counts",
        "/inventory/movements",
        "/inventory/breakage",
        "/finance",
        "/finance/expenses",
        "/finance/balance",
        "/finance/additional-income",
        "/payroll/employees",
        "/payroll/runs",
        "/payroll/deductions",
        "/employees",
        "/reports",
        "/settings",
      ]),
    );
  });

  it("keeps hrefs unique", () => {
    const hrefs = flat.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("orders sections per UX §3.1 with Bono after sales", () => {
    const groupings = navGroups.map((group) => group.heading ?? group.items[0].label);
    expect(groupings).toEqual([
      "nav.dashboard",
      "nav.sales",
      "nav.bono",
      "nav.inventory",
      "nav.finance",
      "nav.payroll",
      "nav.staff",
      "nav.reports",
      "nav.settings",
    ]);
  });
});

/**
 * Visibility per role, mirroring backend/apps/accounts/permissions.py. The
 * point is that the menu follows the capability the screen enforces, so a role
 * that would only meet a refusal never sees the door.
 */
describe("sidebar visibility by role", () => {
  const PERMISSIONS = {
    barman: [
      "products.view_products",
      "inventory.view_inventory",
      "inventory.receive_stock",
      "inventory.record_breakage",
      "bono.view_bono",
    ],
    cashier: [
      "products.view_products",
      "inventory.view_inventory",
      "inventory.complete_stock_count",
      "sales.view_sales",
      "sales.create_sale",
      "bono.view_bono",
      "bono.submit_report",
    ],
    manager: [
      "products.view_products",
      "inventory.view_inventory",
      "inventory.complete_stock_count",
      "sales.view_sales",
      "sales.create_sale",
      "inventory.receive_stock",
      "inventory.record_breakage",
      "inventory.approve_adjustment",
      "sales.void_sale",
      "finance.view_reports",
      "finance.create_expense",
      "finance.approve_expense",
      "finance.manage_expense_categories",
      "payroll.view_payroll",
      "payroll.create_deduction",
      "bono.view_bono",
      "bono.manage_operations",
      "users.manage_employees",
      "audit.view_audit_log",
    ],
    owner: [
      "products.view_products",
      "products.manage_categories",
      "products.manage_products",
      "products.change_prices",
      "inventory.view_inventory",
      "inventory.receive_stock",
      "inventory.record_breakage",
      "inventory.complete_stock_count",
      "inventory.approve_adjustment",
      "sales.view_sales",
      "sales.create_sale",
      "sales.void_sale",
      "finance.view_reports",
      "finance.create_expense",
      "finance.approve_expense",
      "finance.manage_expense_categories",
      "payroll.view_payroll",
      "payroll.generate_run",
      "payroll.approve_run",
      "payroll.mark_paid",
      "payroll.create_deduction",
      "payroll.manage_payroll_employees",
      "bono.view_bono",
      "bono.manage_configuration",
      "bono.manage_operations",
      "bono.submit_report",
      "bono.approve_report",
      "users.manage_employees",
      "audit.view_audit_log",
      "accounts.manage_users",
      "accounts.manage_roles",
      "accounts.manage_settings",
    ],
  };

  const hrefsFor = (permissions: string[], role?: string) =>
    visibleNavGroups(permissions, role)
      .flatMap((group) => group.items)
      .map((item) => item.href);

  it("keeps the dashboard visible to every role, even a bare session", () => {
    expect(hrefsFor([])).toEqual(["/dashboard"]);
  });

  it("gives the owner every destination (spec §7.4)", () => {
    expect(hrefsFor(PERMISSIONS.owner, "OWNER")).toHaveLength(23);
  });

  it("hides settings from a manager but keeps their finance, payroll and reports work", () => {
    const hrefs = hrefsFor(PERMISSIONS.manager, "MANAGER");
    expect(hrefs).not.toContain("/settings");
    expect(hrefs).toContain("/finance");
    expect(hrefs).toContain("/payroll/runs");
    expect(hrefs).not.toContain("/employees");
    expect(hrefs).not.toContain("/finance/additional-income");
    expect(hrefs).toContain("/reports");
    expect(hrefs).toContain("/bono");
    expect(hrefs).toContain("/bono/reports");
    expect(hrefs).not.toContain("/bono/configuration");
    expect(hrefs).toHaveLength(18);
  });

  it("hides finance, payroll, reports and settings from a cashier", () => {
    const hrefs = hrefsFor(PERMISSIONS.cashier, "CASHIER");
    expect(hrefs).toEqual([
      "/dashboard",
      "/sales",
      "/sales/transactions",
      "/bono",
      "/bono/reports",
      "/inventory",
      "/inventory/products",
      "/inventory/counts",
      "/inventory/movements",
    ]);
    expect(hrefs).not.toContain("/bono/configuration");
  });

  it("gives a barman Bono read access but no Sales, stock count, finance or settings", () => {
    const hrefs = hrefsFor(PERMISSIONS.barman, "BARMAN");
    expect(hrefs).not.toContain("/inventory/counts");
    expect(hrefs).not.toContain("/sales");
    expect(hrefs).not.toContain("/finance");
    expect(hrefs).not.toContain("/payroll/runs");
    expect(hrefs).not.toContain("/reports");
    expect(hrefs).not.toContain("/settings");
    expect(hrefs).not.toContain("/bono/configuration");
    expect(hrefs).toEqual([
      "/dashboard",
      "/bono",
      "/bono/reports",
      "/inventory",
      "/inventory/products",
      "/inventory/receive",
      "/inventory/movements",
      "/inventory/breakage",
    ]);
  });

  it("drops a group once every item in it is hidden", () => {
    const headings = visibleNavGroups(PERMISSIONS.cashier, "CASHIER").map(
      (group) => group.heading ?? group.items[0].label,
    );
    expect(headings).toEqual(["nav.dashboard", "nav.sales", "nav.bono", "nav.inventory"]);
  });
});
