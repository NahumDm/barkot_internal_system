"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowUpDown,
  Banknote,
  BarChart3,
  Boxes,
  CircleMinus,
  ClipboardCheck,
  LayoutDashboard,
  Package,
  PackagePlus,
  Receipt,
  Scale,
  Settings,
  ShoppingCart,
  TriangleAlert,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { BarkotLogo } from "../brand/logo";
import { navGroups } from "./nav";

const iconByHref: Record<string, LucideIcon> = {
  "/dashboard": LayoutDashboard,
  "/sales": ShoppingCart,
  "/sales/transactions": Receipt,
  "/inventory": Boxes,
  "/inventory/products": Package,
  "/inventory/receive": PackagePlus,
  "/inventory/counts": ClipboardCheck,
  "/inventory/movements": ArrowUpDown,
  "/inventory/breakage": TriangleAlert,
  "/finance": Wallet,
  "/finance/expenses": Receipt,
  "/finance/balance": Scale,
  "/payroll/employees": Users,
  "/payroll/runs": Banknote,
  "/payroll/deductions": CircleMinus,
  "/reports": BarChart3,
  "/settings": Settings,
};

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col bg-sidebar text-ivory">
      <div className="border-b border-ivory/10 px-4 py-5">
        <div className="rounded-lg bg-cream p-2">
          <BarkotLogo variant="compact" className="mx-auto h-9 w-auto" />
        </div>
        <p className="mt-2 text-center text-xs text-ivory/60">Bar &amp; Restaurant</p>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {navGroups.map((group, groupIndex) => (
          <div key={groupIndex} className="mb-4">
            {group.heading ? (
              <p className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-ivory/45">
                {group.heading}
              </p>
            ) : null}
            <ul>
              {group.items.map((item) => {
                const active = pathname === item.href;
                const Icon = iconByHref[item.href] ?? LayoutDashboard;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={[
                        "mb-1 flex items-center gap-3 rounded px-2 py-2 text-sm transition-colors",
                        active
                          ? "bg-ivory/10 font-medium text-ivory"
                          : "text-ivory/65 hover:bg-ivory/10 hover:text-ivory",
                      ].join(" ")}
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
