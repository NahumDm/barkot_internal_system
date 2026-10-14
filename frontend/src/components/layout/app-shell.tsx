"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { Header } from "./header";
import { Sidebar } from "./sidebar";

/**
 * The application frame: sidebar, header, scrolling content.
 *
 * Below 960px the sidebar is replaced by an off-canvas drawer (the mandatory
 * breakpoint, §7); at 960px and above it is the persistent column it has always
 * been. The open/closed state lives here because both the header's hamburger and
 * the sidebar's own close button drive the same drawer.
 *
 * The drawer is one `<aside>` in both modes, shown and hidden by CSS
 * (`globals.css`), not by rendering two copies: a second navigation tree would
 * be a second thing to keep in step with the permission matrix.
 */
export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const menuOpenRef = useRef(menuOpen);

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  // Mirror the open flag into a ref, in an effect rather than during render so
  // the route-change effect that follows neither reads a value React has not
  // committed yet nor lists `menuOpen` and mistakes opening for navigating.
  useEffect(() => {
    menuOpenRef.current = menuOpen;
  }, [menuOpen]);

  // Follow the link, then get out of the way: close the drawer and put focus at
  // the top of the new page rather than leaving it on a link the drawer hid.
  useEffect(() => {
    if (!menuOpenRef.current) return;
    setMenuOpen(false);
    const frame = requestAnimationFrame(() => mainRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  // Escape closes and returns focus to the control that opened the drawer.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      triggerRef.current?.focus();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  // No background scrolling behind an open drawer.
  useEffect(() => {
    if (!menuOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [menuOpen]);

  // Move focus into the drawer when it opens, so keyboard users land inside it.
  // The frame matters: the drawer's `visibility` flips in the same commit, and a
  // `focus()` that runs before the browser has recalculated that style lands on
  // an element it still considers unfocusable and silently does nothing.
  useEffect(() => {
    if (!menuOpen) return;
    const frame = requestAnimationFrame(() => {
      asideRef.current?.querySelector<HTMLElement>("[data-drawer-close]")?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [menuOpen]);

  return (
    <div className="app flex min-h-screen bg-background">
      <Sidebar open={menuOpen} onClose={closeMenu} id="app-navigation" asideRef={asideRef} />
      <div className="app-body flex min-w-0 flex-1 flex-col">
        <Header
          onMenuToggle={() => setMenuOpen((value) => !value)}
          menuOpen={menuOpen}
          drawerId="app-navigation"
          triggerRef={triggerRef}
        />
        <main
          ref={mainRef}
          tabIndex={-1}
          className="main flex-1 overflow-y-auto p-4 outline-none sm:p-6"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
