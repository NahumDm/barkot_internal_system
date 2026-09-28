# integrations

**Empty adapter boundary — Phase 0A marker only. No adapters implemented.**

Architecture principle P08 (integration isolation): external providers are
reached through adapters, and business domains never depend directly on
provider-specific payload formats. This app exists so that boundary has a
home before any provider work begins (Phase 6).

Defined adapter slots per spec §16:

| Adapter | Purpose | MVP status |
| --- | --- | --- |
| Payment | Chapa payment + webhook verification + transaction status table | Optional / validate |
| Fiscal | Ethiopian e-invoicing — keep fiscal fields isolated from the core sale model | Boundary required |
| Email | SMTP notification (password reset / report delivery) | Optional |
| Object storage | S3-compatible uploads — store metadata/URLs only | Optional |

Placeholder to keep the boundary honest: no models, no services, no adapter
implementations until Phase 6.