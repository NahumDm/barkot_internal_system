export interface NavItem {
  label: string;
  href: string;
}

export interface NavGroup {
  heading?: string;
  items: NavItem[];
}

/**
 * Single source of truth for the sidebar (UX §3.1) covering the 17
 * normative routes of spec §7.4.
 */
export const navGroups: NavGroup[] = [
  { items: [{ label: "Dashboard", href: "/dashboard" }] },
  {
    heading: "Sales",
    items: [
      { label: "Sales", href: "/sales" },
      { label: "Transactions", href: "/sales/transactions" },
    ],
  },
  {
    heading: "Inventory",
    items: [
      { label: "Overview", href: "/inventory" },
      { label: "Products", href: "/inventory/products" },
      { label: "Receive Stock", href: "/inventory/receive" },
      { label: "Stock Count", href: "/inventory/counts" },
      { label: "Stock Movements", href: "/inventory/movements" },
      { label: "Breakage & Waste", href: "/inventory/breakage" },
    ],
  },
  {
    heading: "Finance",
    items: [
      { label: "Overview", href: "/finance" },
      { label: "Expenses", href: "/finance/expenses" },
      { label: "Balance", href: "/finance/balance" },
    ],
  },
  {
    heading: "Payroll",
    items: [
      { label: "Employees", href: "/payroll/employees" },
      { label: "Payroll", href: "/payroll/runs" },
      { label: "Deductions", href: "/payroll/deductions" },
    ],
  },
  { items: [{ label: "Reports", href: "/reports" }] },
  { items: [{ label: "Settings", href: "/settings" }] },
];
