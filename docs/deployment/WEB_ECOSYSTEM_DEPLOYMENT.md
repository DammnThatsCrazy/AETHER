---
title: Web Ecosystem — Deployment Contract
slug: deployment/web-ecosystem-deployment
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "8.12.0"
canonical_owner: frontend@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Web Ecosystem — Deployment Contract

Deployment contract for the two public marketing shells built by the
[Web Ecosystem program](../plans/WEB_ECOSYSTEM_PHASES.md):
`frontend/aether-marketing` and `frontend/olympus-marketing`.

This document is an engineering contract, not marketing copy. Read it as the
spec a deployer must satisfy and the honest inventory of what does **not** exist
yet. The shells are static, prerendered sites; their hosting is configured but
**nothing in this document is deployed**.

## 1. Canonical origins are TARGET origins only

The Olympus + Aether web ecosystem targets a fixed set of canonical origins.
Every one of them is a **target** for a future deploy. None is served by this
repository today, none has a live TLS certificate provisioned here, and none has
a CNAME/alias record owned by these shells. This repository deliberately holds
no live-deploy machinery for the marketing shells: no DNS records, no wiring
into the tenant app's S3/Terraform/deploy.yml paths (those are live machinery
for the tenant application and Kyber and are untouched), and no claim that
traffic is being served.

Kyber stays internal. `kyber.olympuslabs.com` is declared only so the topology
is explicit; public marketing never links to it.

## 2. The two shells and their advertised hosts

| Workspace | Advertised host | Surface |
| --- | --- | --- |
| `frontend/aether-marketing` (`@aether/aether-marketing`) | `https://aether.olympuslabs.com` | Aether public marketing: platform, solutions, developers, integrations, security, pricing, resources, public auth-threshold routes |
| `frontend/olympus-marketing` (`@olympus/olympus-marketing`) | `https://olympuslabs.com` | Olympus Labs corporate marketing |

Both builds run the same pipeline:

```bash
npm run build   # = tsc --noEmit && vite build && node scripts/prerender.mjs
```

Artifact layout produced into each workspace's `dist/`:

- `dist/index.html` — built SPA entry (home).
- `dist/<route>/index.html` — a prerendered static shell per non-home route
  (head rewritten at build time; see `scripts/prerender.mjs` and the workspace
  `seo-data.json` manifest). `aether-marketing` prerenders platform capability
  and solution deep routes; `olympus-marketing` prerenders every section
  including `products/aether`.
- `dist/robots.txt` — `aether-marketing` disallows the quiet auth-threshold
  routes (`/login`, `/signup`, `/forgot-password`); `olympus-marketing` allows
  all.
- `dist/sitemap.xml` — home + every prerendered route.
- `dist/assets/*` — content-hashed Vite build output.
- `dist/*.svg` — brand identity marks copied from `publicDir`.

Because every sitemap route is a real static file, the host must **serve files
as-is** and must **not** apply an SPA-style catch-all rewrite to `/index.html`
(such a rewrite would shadow the prerendered deep shells and serve the home head
to crawlers).

## 3. Static-hosting configuration (`vercel.json`)

Each shell carries a provider-agnostic static config at
`frontend/<shell>/vercel.json`. The two files are structurally identical:

- **No rewrites and no redirects.** The output is prerendered; a blanket
  rewrite to `/index.html` is explicitly rejected because it would shadow the
  prerendered per-route shells. A catch-all 404 fallback is also omitted: there
  is no authored/prerendered `404.html` in the build to point one at, and a
  rewrite to a nonexistent destination would be a dangling rule. Unknown paths
  therefore fall through to the host's own 404 — the honest default for a fully
  prerendered site.
- **Security headers** on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **Immutable caching** for `/assets/(.*)`: Vite content-hashes those filenames,
  so `Cache-Control: public, max-age=31536000, immutable` is safe. Cache rules
  mirror the tenant app config (`frontend/aether/vercel.json`) for `/assets/*`.
- No API rewrite, no `framework` field, no trailing-slash/clean-url mutation.

Known limitation recorded here rather than hidden: SPA-only routes that are not
prerendered — the Aether auth-threshold pages (`/login`, `/signup`,
`/forgot-password`) and the client-side `*` not-found route — are reachable via
in-app client navigation only. A direct deep link to one of those paths on a
pure static host returns the host's default 404. Serving those routes with a
custom static 404 / threshold shell is future work, not fabricated in this
phase.

## 4. Environment contract (`VITE_*`)

Both shells read six site-topology origins at build time from
`src/lib/env.ts` (canonical defaults live in that file and are mirrored below)
plus two analytics variables from `src/lib/analytics.ts`. A full annotated
template ships as `frontend/<shell>/.env.example`.

| Variable | Default (target origin) | Meaning |
| --- | --- | --- |
| `VITE_OLYMPUS_SITE_URL` | `https://olympuslabs.com` | Olympus Labs corporate marketing origin |
| `VITE_AETHER_MARKETING_URL` | `https://aether.olympuslabs.com` | Aether public marketing origin |
| `VITE_AETHER_APP_URL` | `https://app.olympuslabs.com` | Protected Aether tenant application origin |
| `VITE_KYBER_URL` | `https://kyber.olympuslabs.com` | Olympus internal Kyber origin; never linked from public marketing |
| `VITE_AETHER_DOCS_URL` | `https://docs.olympuslabs.com` | Aether documentation origin |
| `VITE_AETHER_STATUS_URL` | `https://status.olympuslabs.com` | Planned public status origin (see STATUS-GAP below) |
| `VITE_ANALYTICS_PROVIDER` | `off` | `off` \| `plausible` \| `ga4` |
| `VITE_ANALYTICS_PROPERTY_ID` | *(empty)* | Plausible site domain or GA4 measurement id |

Notes:

- Every origin is a **target origin**. Setting these values configures what
  links, canonicals, and sitemap URLs the build would emit; it publishes
  nothing.
- The tenant backend is not involved in these shells. They hold no API base URL
  and no credential material.
- The `VITE_KYBER_URL` key exists so the topology is explicit and so Kyber can
  never be invented ad hoc; it must stay unlinked from public pages.

## 5. Analytics contract

`frontend/<shell>/src/lib/analytics.ts` (near-identical copies per workspace —
duplicated by convention, not lifted to `frontend/shared`) is the whole of the
analytics story:

- **OFF by default.** `resolveAnalytics` enables analytics only when the
  provider is exactly `plausible` or `ga4` **and** the property id is non-empty.
  Unknown/empty providers normalize to `off`; missing or whitespace-only
  property ids disable. The resolver never throws.
- **Env adapter.** `analyticsFromEnv()` reads `VITE_ANALYTICS_PROVIDER` and
  `VITE_ANALYTICS_PROPERTY_ID`; an unconfigured build resolves to
  `{ enabled: false, provider: 'off', propertyId: '' }`.
- **Injection is inert unless enabled.** `initAnalytics(...)` returns
  immediately when disabled. When deliberately enabled it injects the provider
  script (Plausible async script or the GA4 gtag bootstrap) defensively —
  guarding `document`/`window`, deduping via a `data-analytics-provider`
  attribute, and swallowing failures so a blocked third-party script can never
  break a shell. Each shell's `src/app/main.tsx` calls
  `initAnalytics(analyticsFromEnv())` as its first side effect; with no env vars
  the net behavior is that nothing is injected.
- This is **configuration surface, not a live claim**. No analytics property is
  provisioned, and no script loads in the default build.

## 6. "To deploy" — procedure only

The steps below are a **procedure** for whoever provisions a static host later.
They are not a record of something already done, and origin/TLS/Route53 work is
out of scope until infrastructure exists.

1. Produce the artifact: from the shell workspace run `npm run build`, which
   emits the `dist/` layout from section 2.
2. Point a provider static host at that `dist/` directory:
   - **Static host (Vercel-style):** apply `frontend/<shell>/vercel.json` as-is.
     Confirm the security headers and the immutable `/assets/(.*)` cache header
     are honored, and confirm no platform setting injects a catch-all rewrite.
   - **Object store + CDN (S3 + CloudFront-style):** upload `dist/` to the
     bucket, map the CDN origin to it, replicate the two header rules from
     `vercel.json` as CloudFront response-headers policies (immutable cache for
     `/assets/*`, security headers for the remaining paths), and leave unknown
     paths to the default 403/404 error response.
3. Provision the advertised host's TLS certificate and DNS as the owning infra
   work — deliberately **not** included here.
4. If analytics is wanted on a real deploy, set `VITE_ANALYTICS_PROVIDER` and
   `VITE_ANALYTICS_PROPERTY_ID` at build time; otherwise leave them off.

The tenant app / Kyber live-deploy machinery (AWS Deployment/, Terraform,
deploy workflows) is intentionally not referenced: those paths deploy the
tenant application and Kyber, not these shells.

## 7. STATUS-GAP: the status origin is planned, not real

`status.olympuslabs.com` is a **planned origin**. The real status source today
is the tenant-safe backend status surface (`/v1/status*` API) described in
[App Routing & Domains](../APP-ROUTING-DOMAINS.md); it is owned by the tenant
deployable, not by the marketing shells.

- The Olympus shell's footer **"Service status"** link (authored in
  `frontend/olympus-marketing/src/content/sections.ts`) is env-driven through
  `VITE_AETHER_STATUS_URL`, so it can later point at a real, public status page
  without a code change.
- **No public status page is fabricated in this phase.** The marketing shells
  must not present `status.olympuslabs.com` as a live surface. Until a real
  status page is deployed, that footer link resolves to a target origin only.

## 8. Known coverage gap: marketing shells are outside data-truth/domain checks

`scripts/validate_frontend_data_truth.py` enforces source/bundle data-truth
boundaries for `aether` and `kyber` only; there is no equivalent covering the
marketing shells, and no `frontend-data-truth`/domain-check manifest exists for
either marketing workspace yet. The marketing shells also have no route-state /
value-display matrix of the kind the tenant applications carry. This document is
the record of that gap: it exists, it is intentional for this phase, and it
should be closed before any shell is promoted to a live origin. Phase 7 of the
[Web Ecosystem program](../plans/WEB_ECOSYSTEM_PHASES.md) is the acceptance
point that must revisit this.
