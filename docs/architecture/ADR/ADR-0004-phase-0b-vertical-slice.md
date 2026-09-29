# ADR-0004 — Phase 0B was a vertical slice, not a horizontal phase

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decision makers:** Client (business scope), user, implementation agent
- **Spec version referenced:** BARKOT-SAS-001 v1.0.0
- **Related:** [ADR-0003](ADR-0003-phase-0b-scope-confirmations.md),
  [roadmap](../../roadmap.md)

## Context

Spec §28 defines seven phases as a horizontal sequence — Phase 1 is auth + users + products, Phase 2
is sales + inventory, Phase 3 finance, Phase 4 payroll — where each phase delivers working software
for one or two domains end to end.

The work carried out under the "Phase 0B" label did not follow that shape. What was actually built
in a single slice was:

- models **and** service layers for accounts, users, products, inventory, sales, finance, payroll
  and audit, and
- session authentication foundations with a four-role permission matrix,

with **no API endpoints and no frontend functionality** attached to any of it.

The commit is `35e3446`; the current state of record is `docs/roadmap.md`.

## Decision

Record the divergence explicitly rather than letting §28 be read literally.

The domain modelling and business rules of spec Phases 1–4 are **complete**. What remains for those
phases is the API surface, the frontend, and hardening — not the schema or the business logic.

## Consequences

**Positive**

- The expensive and irreversible part of the work is done and tested. 70 tests cover domain
  invariants (a sale moves stock exactly once, a void reverses it, payroll reconciles), the
  permission matrix, and production configuration guards.
- The business rules are proven in isolation before any interface was built on top of them, so a bug
  found in Phase B is unlikely to be a domain bug.
- The spec's own §8.2 principle is honoured directly: serializers validate and call a service; the
  service owns the transaction.

**Negative**

- Between 0B and the completion of Phase A there is a window in which the majority of the backend
  cannot be reached over HTTP. The OpenAPI schema has `paths: {}` and the only endpoints are the two
  health checks.
- A reader of spec §28 alone would conclude that Phases 1–4 are entirely upcoming. They are not.

**Mitigation**

- `docs/roadmap.md` maps every spec phase to its actual position, and states plainly that the
  backend work of Phases 1–4 is done.
- The root `README.md` status section reflects the same position.
- Phase A is deliberately small and its exit criteria are observable: a real user logging in over
  HTTP, and 401/403 on every protected route.

## Note on phase naming

"Phase 0B" is this project's working label for the domain-foundation slice. It is not in the
specification, and it is not intended to renumber §28. The roadmap is organised by remaining work
rather than by the spec's phase numbers, with an explicit mapping table between the two.

## Consequences for the v1.1.0 revision

The author should add to §28 a status column recording which phases are complete, partially complete
(domain only) or outstanding, so the horizontal sequence is not mistaken for a remaining-work list.
This is a documentation clarification, not a change of architecture, and is lower priority than
Phase A.
