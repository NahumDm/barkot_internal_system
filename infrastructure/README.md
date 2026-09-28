# Infrastructure

Operational configuration, kept outside both applications so the frontend and backend stay independently deployable.

- `docker/` — container build definitions and image configuration.
- `nginx/` — reverse proxy and TLS termination. Routes the public origin to the Next.js server and `/api/v1/` to Django/Gunicorn.
- `scripts/` — operational automation such as backup, restore and deployment helpers.

## Target topology

Single commercially permitted VPS running Ubuntu 24.04 LTS, with Nginx on the host, Docker Compose for application services, and PostgreSQL 17.x as the system of record. PostgreSQL and Redis/Valkey are never exposed publicly. Redis/Valkey and Celery are added only when async work becomes real (spec §17, §18).

## Status

Placeholder structure only. No Docker or deployment configuration yet.
