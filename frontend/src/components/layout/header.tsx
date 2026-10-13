"use client";

import type { Ref } from "react";
import { Menu } from "lucide-react";

import { AccountMenu } from "./account-menu";

export function Header({
  onMenuToggle,
  menuOpen = false,
  drawerId,
  triggerRef,
}: Readonly<{
  onMenuToggle?: () => void;
  menuOpen?: boolean;
  drawerId?: string;
  triggerRef?: Ref<HTMLButtonElement>;
}>) {
  return (
    <header className="topbar flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4 sm:px-6">
      <button
        ref={triggerRef}
        type="button"
        className="nav-toggle"
        aria-label="Open navigation"
        aria-expanded={menuOpen}
        aria-controls={drawerId}
        onClick={onMenuToggle}
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>
      <p className="topbar-text min-w-0 flex-1 truncate text-sm text-ink-secondary">
        Barkot Bar &amp; Restaurant
      </p>
      <AccountMenu />
    </header>
  );
}
