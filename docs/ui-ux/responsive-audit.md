# Responsive audit — phone-width shell repair

Scope: the shared application frame (sidebar + header + content) below the 960px
breakpoint. No business logic, roles, CSRF/auth or data flows were touched, and
the Barkot brand (palette, type, logo, icons, cards) is unchanged.

## 1. Summary

At phone widths the persistent 256px sidebar pushed the content out of the
viewport, so every route scrolled horizontally. The frame now collapses the
sidebar into an off-canvas drawer at `< 960px`: a hamburger opens it, a backdrop
or the close button or `Escape` dismisses it, following a link closes it and
moves focus to the new page, and the page behind it does not scroll. At `>= 960px`
the layout is exactly what it was before.

## 2. Root cause

Single root cause, confirmed with a live-browser probe (not a guess):

- `AppShell` rendered a fixed `aside.sidebar` with a hard `w-64` (256px) and
  `shrink-0` at all viewport widths, with no breakpoint to collapse it and no
  toggle to hide it. A 256px column plus the content's own minimum width exceeds
  a phone viewport, so `documentElement.scrollWidth > clientWidth` (117px at
  390px wide).
- Because the sidebar was never removed from the flow, the header (which held the
  only candidate for a toggle) had no hamburger to expose.
- The leftover overflow after removing the sidebar was not shell chrome: the only
  other wide element at 320–390px lives inside the tables' existing
  `overflow-x-auto` wrappers, which scroll internally and do not overflow the page.

## 3. Evidence

Measured with a Playwright probe against the real shell, signed in as an owner
with the full permission set (`stubSignedIn`):

| Route (390px)          | Before overflow | After overflow |
| ---------------------- | --------------: | -------------: |
| /dashboard             |            116px |             0px |
| /sales/transactions    |            116px |             0px |
| /inventory/products    |            116px |             0px |
| /finance/expenses      |            116px |             0px |

- Breakpoint: at 959px `aside` is `visibility:hidden` and `.nav-toggle` is
  `display:flex`; at 960px and 961px `aside` is `visible` and `.nav-toggle` is
  `display:none`.
- Full sweep: **19 routes × 3 phone widths (320/360/390) = 57 checks, 0 overflow
  failures** after the change.
- Screenshots: `docs/ui-ux/responsive-audit/before/` and
  `docs/ui-ux/responsive-audit/after/` (390px and 1280px, plus
  `after/drawer-open-390.png`). The before set shows the sideways scroll; the
  after set is flush at 390px and identical to desktop at 1280px.

## 4. Changes

- `frontend/src/app/globals.css`: a responsive block at
  `@media (max-width: 959.98px)` turns `.sidebar` into a `position:fixed`
  drawer (`translateX(-100%)`, `visibility:hidden`, `z-index:50`); `.is-open`
  slides it in. Adds `.sidebar-backdrop` (`z-index:40`) and `.sidebar-close`.
  `visibility` is delayed only when hiding (`transition: transform 200ms ease,
  visibility 0s linear 200ms`; `transition-delay:0s` when open) so the drawer can
  take focus the instant it opens while the slide-out still completes before it
  leaves the accessibility tree. A `prefers-reduced-motion` block drops the
  transitions. Base rules hide `.nav-toggle`/`.sidebar-close`/`.sidebar-backdrop`.
- `frontend/src/components/layout/app-shell.tsx`: `"use client"` frame. Owns
  `menuOpen`; effects close the drawer and focus `<main>` on route change, handle
  `Escape` (close + return focus to the toggle), lock body scroll while open, and
  focus the drawer's close button when it opens. `<main>` is `tabIndex={-1}` so it
  can receive focus.
- `frontend/src/components/layout/sidebar.tsx`: accepts `open`, `onClose`, `id`,
  `asideRef`; renders the backdrop and the `.sidebar-close` button and toggles the
  `is-open` class. One nav tree in both modes (no duplicated permission-sensitive
  markup). Links intentionally have no `onClick`; closing rides the pathname.
- `frontend/src/components/layout/header.tsx`: `"use client"`; adds the
  `.nav-toggle` button (`Menu` icon, `aria-label="Open navigation"`,
  `aria-expanded`, `aria-controls`) and `px-4 sm:px-6`.
- `frontend/tests/e2e/responsive.spec.ts`: regression spec — drawer below 960,
  backdrop/close dismissal, follow-link close + focus, persistent sidebar at
  `>= 960`, and no horizontal overflow at phone widths (portrait and landscape).

## 5. Verification

- `frontend/tests/e2e/responsive.spec.ts` against a production build:
  **6 passed (1.9m)**.
- `frontend/tests/smoke.spec.ts`: **4 passed (36.7s)** — home redirect, the 18
  sidebar links, and the product/category route shells still render.
- Live probe on the dev server: open/`Escape`/backdrop/navigate all correct;
  focus lands on the drawer on open, returns to the toggle on `Escape`, and lands
  on `<main>` after navigation; `body` scroll locks while open.
- `npx tsc --noEmit` exit 0; `npx prettier --check` clean on every changed file.

## 6. Remaining risks

Confirmed:

- `eslint` could not be run in this environment (the process hangs even on a
  single file), so lint status is unverified here.
- The e2e runner in this environment is far slower than an isolated Playwright
  script (`goto` ~20–30s vs ~2.5s) and `webServer` build+start can exceed
  Playwright's 300s readiness cap; the suite above was run with `--workers=1`,
  generous timeouts, and a manually started production server.

Assumed (not separately tested):

- Focus behavior was verified in Chromium only. The pattern used (delayed
  `visibility` + `focus()` in `requestAnimationFrame`) is standard, but Firefox
  and Safari were not exercised.
- Touch gestures (swipe to close) were not implemented or requested; dismissal is
  button/Escape/backdrop only.
- The dev database is empty (0 products, 0 categories), so table-heavy states were
  judged by the shell/`overflow-x-auto` wrappers rather than populated data.
