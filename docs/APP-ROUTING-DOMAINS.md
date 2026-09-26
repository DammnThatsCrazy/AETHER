---
title: App Routing & Domains
slug: operations/app-routing-domains
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# App Routing & Domains

Canonical public layout for the first release. All app→API wiring is
env-driven (`VITE_API_BASE_URL`, app-specific `VITE_*_ENV`); the checked-in
production defaults match these domains and staging overrides them through
Amplify/Terraform variables.

| Subdomain | Surface | Notes |
| --- | --- | --- |
| `www.olympuslabsml.com` | Olympus Labs marketing website | Corporate/company, research, resources, and contact |
| `aether.olympuslabsml.com` | Aether marketing shell | Product, connections, perspectives, trust, developers, proof, and pilot paths |
| `app.olympuslabsml.com` | Aether tenant app | `VITE_AETHER_ENV=production`; authenticated customer surface |
| `kyber.olympuslabsml.com` | Kyber operator console | No public DNS or public marketing link by default; internal routing only |
| `demo.[domain]` | Demo App | Synthetic, closed demo (`VITE_DEMO_ENV`) |
| `api.olympuslabsml.com` | Backend API | `/v1/*`, `/health`, `/ready`, `/openapi.json` |
| `docs.olympuslabsml.com` | Public documentation | Built from `frontend/docs` (tiered P/C/I) |
| `status.olympuslabsml.com` | Public status page | Reads the verified API `/health` payload and reports component states |

## Config

- Set the tenant app's `VITE_API_BASE_URL` and `VITE_AETHER_ENDPOINT` to
  `https://api.olympuslabsml.com` in production. Terraform injects those values
  into the Amplify `aether-app` build.
- Set `CORS_ORIGINS` (backend) to the exact Aether, status, and approved
  operator origins. Terraform derives the canonical production list and accepts
  an explicit staging override.
- Staging alone may also set `CORS_PREVIEW_ORIGIN_SUFFIX` (the preview Amplify
  app's default domain), which allows exactly `https://pr-<N>.<suffix>` for
  per-PR previews. The backend refuses to start with it in production.
- Set the status app's `VITE_STATUS_API_URL` only after the API certificate,
  DNS, and CORS path have been verified. An empty value must remain visibly
  unverified, not green.
- The status app's docs and Aether contact links are also environment-driven:
  staging resolves them to `docs.staging.olympuslabsml.com` and
  `aether.staging.olympuslabsml.com`, while production resolves them to
  `docs.olympuslabsml.com` and `aether.olympuslabsml.com`. They must not send a
  staging visitor to an unprovisioned production origin.
- `AETHER_DEMO_APP_URL`, app/kyber URLs are env-driven for cross-links.

See [Domain & DNS Readiness](DOMAIN-DNS-READINESS.md) and
[Squarespace Website Readiness](SQUARESPACE-WEBSITE-READINESS.md).
