# Barkot Management System — Backend

Django 5.2.x LTS + Django REST Framework 3.18.x. Modular monolith, one deployable.

## Layout

- `config/` — Django project settings, root URLconf, WSGI/ASGI entrypoints.
- `apps/<domain>/` — one Django app per business domain. Owns its own models, serializers, views, services and tests.
- `requirements/` — pinned dependency definitions.
- `tests/` — cross-domain and system-level tests.
- `manage.py` — standard Django management entrypoint.

## Domain dependency rule

Dependencies flow inward toward business rules and data:

```
core  <-  everything (shared enums, base models, money/time utilities, errors)
accounts, users, products, audit  <-  core
sales  <-  products, inventory, finance, audit
inventory  <-  products, audit
finance  <-  sales, inventory, payroll
payroll  <-  users, finance, audit
reports  <-  all domains, read-only, never owns source truth
```

Views and controllers orchestrate use cases. Multi-step financial or inventory calculations belong in services, not in serializers (spec §8.2).

## API

Versioned REST + JSON under `/api/v1/`. Django session auth with secure HttpOnly cookies and CSRF for the web MVP (spec §9.1).

## Status

Placeholder structure only. No models, endpoints or auth yet.
