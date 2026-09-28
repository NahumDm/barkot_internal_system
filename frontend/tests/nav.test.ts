import { describe, expect, it } from "vitest";
import { navGroups } from "@/components/layout/nav";

describe("sidebar navigation (UX §3.1, spec §7.4)", () => {
  const flat = navGroups.flatMap((group) => group.items);

  it("defines exactly 17 nav items", () => {
    expect(flat).toHaveLength(17);
  });

  it("covers every normative route of spec §7.4", () => {
    const routes = new Set(flat.map((item) => item.href));
    expect(routes).toEqual(
      new Set([
        "/dashboard",
        "/sales",
        "/sales/transactions",
        "/inventory",
        "/inventory/products",
        "/inventory/receive",
        "/inventory/counts",
        "/inventory/movements",
        "/inventory/breakage",
        "/finance",
        "/finance/expenses",
        "/finance/balance",
        "/payroll/employees",
        "/payroll/runs",
        "/payroll/deductions",
        "/reports",
        "/settings",
      ]),
    );
  });

  it("keeps hrefs unique", () => {
    const hrefs = flat.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("orders sections per UX §3.1 (dashboard, sales, inventory, finance, payroll, reports, settings)", () => {
    const groupings = navGroups.map((group) => group.heading ?? group.items[0].label);
    expect(groupings).toEqual([
      "Dashboard",
      "Sales",
      "Inventory",
      "Finance",
      "Payroll",
      "Reports",
      "Settings",
    ]);
  });
});
