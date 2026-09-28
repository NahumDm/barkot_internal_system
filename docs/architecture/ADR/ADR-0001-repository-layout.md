# ADR-0001 — Repository Layout

- **Status:** Accepted
- **Date:** 2026-09-28
- **Decision makers:** User, implementation agent
- **Spec version referenced:** BARKOT-SAS-001 v1.0.0 (author-maintained; user updates to v1.1.0 to record these deviations)

## Context

BARKOT-SAS-001 §25 mandates an app-deployables monorepo ("apps/web", "apps/api", "infra"). The project is a small, commercially focused system where simple, conventional layouts reduce cognitive load. §25 is understood as prescriptive about *architecture* — web and API are independent deployables sharing infrastructure — not necessarily about exact path names.

## Decision

1. Top-level layout is `frontend/ backend/ infrastructure/` (deviation from §25 path names).
2. `src/` within the frontend (Next.js convention) and `apps/<domain>/` within the backend remain exactly as the spec describes.
3. Containers are built from `backend/` and `frontend/` Dockerfiles (dev/prod targets); `infrastructure/docker/` and `infrastructure/nginx/` hold image definitions, Nginx site configuration and operational scripts. Ops artifacts are not duplicated as separate deployables.
4. Frontend and backend are fully separable (independent manifests, no root `package.json`, no workspaces). The root `Makefile` is a *task runner only* — an orchestration convenience, never a runtime dependency.
5. The P08 boundary marker `apps/integrations/` exists as an empty application (spec §6.2, §25.1).
6. Tests live inside each Django app (`apps/<domain>/tests/`); cross-domain and system tests live in `backend/tests/integration/`.

## Consequences

- **Positive:** conventional and IDE-friendly; CI gates are trivially parallel (backend vs frontend job); no monorepo tooling tax.
- **Negative:** the layout deviates from the letter of §25, so BARKOT-SAS-001 must be aligned in the user-maintained v1.1.0 (ADR-0001 is the authoritative record of the deviation meanwhile).
- Reference implementation: commit `b3b6a79` (Phase 0A scaffold).