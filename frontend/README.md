# Barkot Management System — Frontend

Next.js 16.x + TypeScript 5.9 + React 19.3 + Tailwind CSS 4.x.

Single application. `src/features/*` holds one folder per business domain; `src/app` holds routing only.
UI stack per the architecture spec (§7.1): Tailwind CSS 4.x with shadcn/ui components, Lucide React icons, Recharts, React Hook Form + Zod, optional TanStack React Query.

## Rules

- The backend is the only authority for balances, stock and permissions. The frontend renders and validates inputs (spec §7.2).
- One shared application shell and sidebar for every role. No per-role visual shells.
- Monochrome black/white/gray. Semantic colors only for state.
- Handle loading, empty, success, validation-error, system-error and permission-denied states explicitly.
- Never invent metrics, pages or workflows beyond the approved specifications.

## Status

Placeholder structure only. No implementation yet.
