# Architecture Decision Records

Architecturally significant decisions that record a specification deviation, a constraint, or a later reversal. The active BARKOT-SAS-001 file is the primary contract; ADRs capture why the repository deviates or what the human must reconcile in the next spec revision.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| ADR-0001 | [Repository layout](ADR-0001-repository-layout.md) — `frontend/ backend/ infrastructure/` vs spec §25 | Accepted |
| ADR-0002 | [Python runtime 3.14](ADR-0002-python-runtime.md) — deviation from spec §5 | Accepted |

## Conventions

- Filename scheme: `ADR-NNNN-lower-kebab-slug.md`.
- Status values: **Proposed**, **Accepted**, **Superseded by ADR-NNNN**.
- The user maintains BARKOT-SAS-001 by hand; any deviation that needs the spec's v1.1.0 text updated *must* also be recorded here first.