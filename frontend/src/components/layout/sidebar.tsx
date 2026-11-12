"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Ref } from "react";
import {
  ArrowUpDown,
  Banknote,
  BarChart3,
  Boxes,
  CircleMinus,
  ClipboardCheck,
  ClipboardList,
  ContactRound,
  LayoutDashboard,
  Package,
  PackagePlus,
  Receipt,
  Scale,
  Settings,
  ShoppingCart,
  SlidersHorizontal,
  Tags,
  Ticket,
  TriangleAlert,
  Users,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-provider";
import { useT } from "@/lib/i18n/context";
import { visibleNavGroups } from "./nav";

const iconByHref: Record<string, LucideIcon> = {
  "/dashboard": LayoutDashboard,
  "/sales": ShoppingCart,
  "/sales/transactions": Receipt,
  "/bono": Ticket,
  "/bono/reports": ClipboardList,
  "/bono/configuration": SlidersHorizontal,
  "/inventory": Boxes,
  "/inventory/products": Package,
  "/inventory/categories": Tags,
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
  "/employees": ContactRound,
  "/reports": BarChart3,
  "/settings": Settings,
};

export function Sidebar({
  open = false,
  onClose,
  id,
  asideRef,
}: Readonly<{
  open?: boolean;
  onClose?: () => void;
  id?: string;
  asideRef?: Ref<HTMLElement>;
}>) {
  const pathname = usePathname();
  const { user } = useAuth();
  const t = useT();
  const groups = visibleNavGroups(user?.permissions ?? [], user?.role);

  return (
    <>
      {/*
        The backdrop only exists on narrow screens; CSS hides it entirely at
        960px and above so the desktop sidebar keeps the layout it always had.
        It is `aria-hidden`: it is a pointer affordance, and Escape and the close
        button already offer keyboard users the same exit.
      */}
      <div
        className={`sidebar-backdrop${open ? " is-open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={asideRef}
        id={id}
        className={`sidebar flex h-screen w-64 shrink-0 flex-col bg-sidebar text-white${
          open ? " is-open" : ""
        }`}
      >
        <div className="brand border-b border-white/10 px-4 py-5">
          <span className="brand-logo">
            <Image
              src="/images/barkot-mark.png"
              alt="Barkot logo"
              width={48}
              height={48}
              unoptimized
            />
          </span>
          <p className="brand-name text-lg font-bold tracking-widest">BARKOT</p>
          <p className="brand-sub text-sm text-white/60">{t("app.brandSub")}</p>
          <button
            type="button"
            data-drawer-close
            className="sidebar-close"
            aria-label={t("app.closeNavigation")}
            onClick={onClose}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {groups.map((group, groupIndex) => (
            <div key={groupIndex} className="mb-4">
              {group.heading ? (
                <p className="nav-group px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  {t(group.heading)}
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
                          "nav-item mb-1 flex items-center gap-3 rounded px-2 py-2 text-sm",
                          active
                            ? "active bg-white/10 font-medium text-white"
                            : "text-white/70 hover:bg-white/5 hover:text-white",
                        ].join(" ")}
                      >
                        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                        {t(item.label)}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
