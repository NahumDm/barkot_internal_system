# ADR-0002 — Python Runtime 3.14 (deviation from spec §5)

- **Status:** Accepted
- **Date:** 2026-09-28
- **Decision makers:** User, implementation agent
- **Spec version referenced:** BARKOT-SAS-001 v1.0.0

## Context

BARKOT-SAS-001 §5 pins "Python 3.13.x". The machine used for this Phase 0A baseline has Python 3.14.6 (CPython) installed and it is the user's preferred local runtime. All backend dependencies (Django 5.2.17, DRF 3.18.1, psycopg 3.3.6, django-filter, drf-spectacular, pytest/Django, ruff 0.11.13, mypy 1.20.2, django-stubs) install and pass under 3.14 with cp314 wheels; the Docker image uses `python:3.14-slim`.

## Decision

1. Local development, CI and the backend image use **Python 3.14**.
2. A similar alignment applies to the frontend toolchain: **Node.js 24 LTS** (v24.14.1) with Next.js 16.3.x, React 19.3.x, TypeScript 5.9.x, Tailwind CSS 4.3.x — all validated against live registries at baseline time.
3. Lockfiles (`backend/requirements/requirements.lock`, `frontend/package-lock.json`) pin exact resolved versions so Docker builds are reproducible regardless of local interpreter.

## Consequences

- **Positive:** uses current stable tooling; the CI matrix and Dockerfile are the enforcement point.
- **Negative:** the deviation must be captured in the user-maintained spec v1.1.0 (spec §5 text updated by the author). No dependency brick walls today; CI would surface any future package that drops cp314 support.