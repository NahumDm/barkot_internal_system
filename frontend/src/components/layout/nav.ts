export interface NavItem {
  label: string;
  href: string;
  /**
   * Permission codenames, any one of which makes this destination visible to a
   * signed-in user. Absent means the item is always shown. Presentation only:
   * the API re-checks every request, this only keeps a screen a role cannot
   * open out of their menu.
   */
  permissions?: string[];
  /**
   * Hide the destination from everyone but the Owner. Used where the API is
   * gated by ownership rather than by a permission code (the employee register
   * and additional income), because the role matrix alone would also offer it
   * to the Manager and then answer their request with a refusal.
   */
  ownerOnly?: boolean;
}

export interface NavGroup {
  heading?: string;
  items: NavItem[];
}

/**
 * Single source of truth for the sidebar (UX §3.1) covering the 17
 * normative routes of spec §7.4, plus the employee register (`/employees`,
 * spec §5) which predates none of them but belongs to no domain group.
 *
 * Each item names the permissions of the screen behind it, taken from the
 * capability the server enforces for that screen rather than from a role name,
 * so the menu cannot drift from the role matrix in
 * `backend/apps/accounts/permissions.py`.
 */
export const navGroups: NavGroup[] = [
  {
    items: [{ label: "nav.dashboard", href: "/dashboard" }],
  },
  {
    heading: "nav.sales",
    items: [
      { label: "nav.sales", href: "/sales", permissions: ["sales.view_sales"] },
      { label: "nav.transactions", href: "/sales/transactions", permissions: ["sales.view_sales"] },
    ],
  },
  {
    heading: "nav.bono",
    items: [
      { label: "nav.overview", href: "/bono", permissions: ["bono.view_bono"] },
      { label: "nav.dailyReports", href: "/bono/reports", permissions: ["bono.view_bono"] },
      {
        label: "nav.configuration",
        href: "/bono/configuration",
        permissions: ["bono.manage_configuration"],
      },
    ],
  },
  {
    heading: "nav.inventory",
    items: [
      { label: "nav.overview", href: "/inventory", permissions: ["inventory.view_inventory"] },
      { label: "nav.products", href: "/inventory/products", permissions: ["products.view_products"] },
      {
        label: "nav.categories",
        href: "/inventory/categories",
        permissions: ["products.manage_categories"],
      },
      {
        label: "nav.receiveStock",
        href: "/inventory/receive",
        permissions: ["inventory.receive_stock"],
      },
      {
        label: "nav.stockCount",
        href: "/inventory/counts",
        permissions: ["inventory.complete_stock_count"],
      },
      {
        label: "nav.stockMovements",
        href: "/inventory/movements",
        permissions: ["inventory.view_inventory"],
      },
      {
        label: "nav.breakageWaste",
        href: "/inventory/breakage",
        permissions: ["inventory.record_breakage"],
      },
    ],
  },
  {
    heading: "nav.finance",
    items: [
      { label: "nav.overview", href: "/finance", permissions: ["finance.view_reports"] },
      { label: "nav.expenses", href: "/finance/expenses", permissions: ["finance.view_reports"] },
      { label: "nav.balance", href: "/finance/balance", permissions: ["finance.view_reports"] },
      {
        label: "nav.additionalIncome",
        href: "/finance/additional-income",
        permissions: ["finance.view_reports"],
        ownerOnly: true,
      },
    ],
  },
  {
    heading: "nav.payroll",
    items: [
      { label: "nav.employees", href: "/payroll/employees", permissions: ["payroll.view_payroll"] },
      { label: "nav.payroll", href: "/payroll/runs", permissions: ["payroll.view_payroll"] },
      { label: "nav.deductions", href: "/payroll/deductions", permissions: ["payroll.view_payroll"] },
    ],
  },
  {
    heading: "nav.staff",
    items: [
      {
        label: "nav.employeeRegister",
        href: "/employees",
        permissions: ["users.manage_employees"],
        ownerOnly: true,
      },
    ],
  },
  { items: [{ label: "nav.reports", href: "/reports", permissions: ["finance.view_reports"] }] },
  {
    items: [
      {
        label: "nav.settings",
        href: "/settings",
        permissions: ["accounts.manage_users", "accounts.manage_roles", "accounts.manage_settings"],
      },
    ],
  },
];

/**
 * The sidebar entries a user holding `granted` may see (UX §3.1).
 *
 * An item with no `permissions` is always shown; otherwise the user must hold
 * at least one of them. A group whose every item is hidden is dropped so its
 * heading does not float above nothing. Presentation only - the API decides
 * every request - but a screen a role cannot open should not be offered.
 */
export function visibleNavGroups(granted: readonly string[], role?: string): NavGroup[] {
  const allowed = new Set(granted);
  const isOwner = role?.toUpperCase() === "OWNER";
  return navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          (!item.ownerOnly || isOwner) &&
          (!item.permissions || item.permissions.some((permission) => allowed.has(permission))),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
