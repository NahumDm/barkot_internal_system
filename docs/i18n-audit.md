# Localization Audit (Phase 2)

## Scope
All frontend user-facing strings across roles (Owner, Manager, Barman, etc.) must be available in both English (`en`) and Amharic (`am`).

## Current state
- Infrastructure: `frontend/src/lib/i18n/` provider + `useT` hook wired in root layout.
- Dictionaries: `locales/en.json`, `locales/am.json` (empty scaffold).
- No strings migrated yet.

## Files with likely user-facing strings
See grep results: ~50 source files under `frontend/src` contain capitalized string literals, including all feature modules (bono, finance, inventory, payroll, sales, reports, settings, dashboard, employees) and layout/nav components.

## Next steps (Phase 3)
1. Extract string literals into namespaced keys (e.g. `nav.dashboard`, `sales.newTransaction`).
2. Populate both dictionaries with English + Amharic translations.
3. Replace literals with `t(key)` calls.
4. Add a test ensuring every key exists in both dictionaries and no raw English remains in JSX.

## Phase 4
Update README, write final summary, run tests, push.