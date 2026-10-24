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
    items: [{ label: "Dashboard", href: "/dashboard" }],
  },
  {
    heading: "Sales",
    items: [
      { label: "Sales", href: "/sales", permissions: ["sales.view_sales"] },
      { label: "Transactions", href: "/sales/transactions", permissions: ["sales.view_sales"] },
    ],
  },
  {
    heading: "Bono",
    items: [
      { label: "Overview", href: "/bono", permissions: ["bono.view_bono"] },
      { label: "Daily Reports", href: "/bono/reports", permissions: ["bono.view_bono"] },
      {
        label: "Configuration",
        href: "/bono/configuration",
        permissions: ["bono.manage_configuration"],
      },
    ],
  },
  {
    heading: "Inventory",
    items: [
      { label: "Overview", href: "/inventory", permissions: ["inventory.view_inventory"] },
      { label: "Products", href: "/inventory/products", permissions: ["products.view_products"] },
      {
        label: "Categories",
        href: "/inventory/categories",
        permissions: ["products.manage_categories"],
      },
      {
        label: "Receive Stock",
        href: "/inventory/receive",
        permissions: ["inventory.receive_stock"],
      },
      {
        label: "Stock Count",
        href: "/inventory/counts",
        permissions: ["inventory.complete_stock_count"],
      },
      {
        label: "Stock Movements",
        href: "/inventory/movements",
        permissions: ["inventory.view_inventory"],
      },
      {
        label: "Breakage & Waste",
        href: "/inventory/breakage",
        permissions: ["inventory.record_breakage"],
      },
    ],
  },
  {
    heading: "Finance",
    items: [
      { label: "Overview", href: "/finance", permissions: ["finance.view_reports"] },
      { label: "Expenses", href: "/finance/expenses", permissions: ["finance.view_reports"] },
      { label: "Balance", href: "/finance/balance", permissions: ["finance.view_reports"] },
    ],
  },
  {
    heading: "Payroll",
    items: [
      { label: "Employees", href: "/payroll/employees", permissions: ["payroll.view_payroll"] },
      { label: "Payroll", href: "/payroll/runs", permissions: ["payroll.view_payroll"] },
      { label: "Deductions", href: "/payroll/deductions", permissions: ["payroll.view_payroll"] },
    ],
  },
  {
    heading: "Staff",
    items: [
      {
        label: "Employee Register",
        href: "/employees",
        permissions: ["users.manage_employees"],
      },
    ],
  },
  { items: [{ label: "Reports", href: "/reports", permissions: ["finance.view_reports"] }] },
  {
    items: [
      {
        label: "Settings",
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
export function visibleNavGroups(granted: readonly string[]): NavGroup[] {
  const allowed = new Set(granted);
  return navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          !item.permissions || item.permissions.some((permission) => allowed.has(permission)),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
