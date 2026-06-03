---
title: App Routing & Domains
slug: operations/app-routing-domains
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# App Routing & Domains

Recommended (configurable) subdomain layout. All app→API wiring is env-driven
(`VITE_API_BASE_URL`, app-specific `VITE_*_ENV`); nothing is hardcoded.

| Subdomain | Surface | Notes |
| --- | --- | --- |
| `app.[domain]` | Aether tenant app | `VITE_AETHER_ENV=production` |
| `kyber.[domain]` or `internal.[domain]` | Kyber operator console | Operator-gated; not public |
| `demo.[domain]` | Demo App | Synthetic, closed demo (`VITE_DEMO_ENV`) |
| `api.[domain]` | Backend API | `/v1/*`, `/v1/health`, `/openapi.json` |
| `docs.[domain]` | Docs site | Built from `frontend/docs` (tiered P/C/I) |
| `status.[domain]` | Status page | Backed by tenant-safe `/v1/status` |

## Config

- Set each frontend's `VITE_API_BASE_URL` to `https://api.[domain]`.
- Set `CORS_ORIGINS` (backend) to the app/demo/docs origins.
- `AETHER_DEMO_APP_URL`, app/kyber URLs are env-driven for cross-links.

See [Domain & DNS Readiness](DOMAIN-DNS-READINESS.md) and
[Squarespace Website Readiness](SQUARESPACE-WEBSITE-READINESS.md).
