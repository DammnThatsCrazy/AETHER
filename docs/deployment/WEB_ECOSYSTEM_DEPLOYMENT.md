---
title: Web Ecosystem — Deployment Contract
slug: deployment/web-ecosystem-deployment
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "0.1.0"
canonical_owner: frontend@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Web Ecosystem — Deployment Contract

Deployment contract for the public marketing and service surfaces built by the
[Web Ecosystem program](../plans/WEB_ECOSYSTEM_PHASES.md):
`frontend/olympus-marketing`, `frontend/aether-marketing`, `frontend/docs`,
`frontend/status`, and the protected `frontend/aether` application.

This document is an engineering contract, not marketing copy. Read it as the
spec a deployer must satisfy and the honest inventory of what does **not** exist
yet. The public shells are static, prerendered sites; their Amplify hosting and
Terraform wiring are implemented, but **no credentialed AWS apply or live
origin verification has run**.

## 1. Canonical origins and current evidence

The Olympus + Aether web ecosystem targets a fixed set of canonical origins.
The repository now contains the Amplify application definitions, branch builds,
custom-domain associations, status app, CORS wiring, and profile controls for
those origins. The checkout has not performed a credentialed AWS plan/apply,
so none of the domains below may be described as live yet. Staging reuses the
verified `*.staging.olympuslabsml.com` associations already present in Amplify,
with Squarespace authoritative for DNS; production-lean is the controlled
`*.olympuslabsml.com` custom-domain promotion shape.

Kyber stays internal. `kyber.olympuslabsml.com` is declared only so the topology
is explicit; public marketing never links to it.

## 2. Public surfaces and their advertised hosts

| Workspace | Advertised host | Surface |
| --- | --- | --- |
| `frontend/aether-marketing` (`@aether/aether-marketing`) | `https://aether.olympuslabsml.com` | Aether public marketing: platform, solutions, developers, integrations, security, pricing, resources, public auth-threshold routes |
| `frontend/olympus-marketing` (`@olympus/olympus-marketing`) | `https://www.olympuslabsml.com` (apex redirects here) | Olympus Labs corporate marketing |
| `frontend/docs` | `https://docs.olympuslabsml.com` | Public documentation |
| `frontend/status` | `https://status.olympuslabsml.com` | Public status page backed by the verified API health payload |
| `frontend/aether` | `https://app.olympuslabsml.com` | Protected end-user tenant application |
| `frontend/kyber` | No public host by default | Internal operator application; no public DNS or marketing link |

The two marketing shell builds run the same pipeline:

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

## 3. Amplify hosting configuration

The public surfaces are defined in the root `amplify.yml` and the Terraform
`local.amplify_apps` map. Each app builds from the monorepo root with its
app-specific `appRoot`, installs the root lockfile, runs the workspace build,
and publishes that workspace's `dist/` directory. The managed apps are:

- `olympus-marketing` → `www`;
- `aether-marketing` → `aether`;
- `docs` → `docs`;
- `aether-app` → `app`; and
- `status` → `status`.

Staging sets `amplify_custom_domain_enabled = true` for
`staging.olympuslabsml.com` and records each app's default domain plus the
reviewed association outputs in SSM. The state-reconciliation workflow imports
the five existing associations before planning, so Terraform cannot create a
second owner or detach the live targets. `production-lean` enables the reviewed
custom-domain associations under `olympuslabsml.com` and exports their DNS
targets for Squarespace. The apex remains on Squarespace and redirects to the `www` surface;
the Route 53 hosted-zone path is an explicit opt-in. `kyber` is not an Amplify
app and receives no public DNS record unless the explicit internal DNS controls
are enabled.

The prerendered marketing bundles retain the following delivery guarantees:

- **No blanket rewrites.** The output is prerendered; a blanket
  rewrite to `/index.html` is explicitly rejected because it would shadow the
  prerendered per-route shells. A catch-all 404 fallback is also omitted: there
  is no authored/prerendered `404.html` in the build to point one at, and a
  rewrite to a nonexistent destination would be a dangling rule. Unknown paths
  therefore fall through to the host's own 404 — the honest default for a fully
  prerendered site.
- **Only the required client fallbacks are rewired.** Terraform gives
  `frontend/aether` and `frontend/docs` their SPA fallback because those apps
  resolve route content at runtime. The Aether marketing app receives targeted
  `/login`, `/signup`, and `/forgot-password` fallbacks for its auth threshold.
  Olympus marketing and status receive no catch-all rewrite, so their
  prerendered route heads and fail-closed status root remain intact.
- **Security headers** on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **Immutable caching** for `/assets/(.*)`: Vite content-hashes those filenames,
  so `Cache-Control: public, max-age=31536000, immutable` is safe. Cache rules
  mirror the tenant app config (`frontend/aether/vercel.json`) for `/assets/*`.
- No API rewrite, no `framework` field, no trailing-slash/clean-url mutation.

Known limitation recorded here rather than hidden: the Aether marketing
auth-threshold routes are direct-linkable on the managed Amplify deployment
through the three targeted fallbacks, but a pure static host without those
rules returns its default 404. The client-side `*` not-found route and any
unlisted marketing path still fall through to the host's default 404. Serving
those paths with a custom static 404 shell is future work, not fabricated in
this phase.

## 4. Environment contract (`VITE_*`)

Both shells read six site-topology origins at build time from
`src/lib/env.ts` (canonical defaults live in that file and are mirrored below)
plus two analytics variables from `src/lib/analytics.ts`. A full annotated
template ships as `frontend/<shell>/.env.example`.

| Variable | Default (target origin) | Meaning |
| --- | --- | --- |
| `VITE_OLYMPUS_SITE_URL` | `https://olympuslabsml.com` | Olympus Labs corporate marketing origin |
| `VITE_AETHER_MARKETING_URL` | `https://aether.olympuslabsml.com` | Aether public marketing origin |
| `VITE_AETHER_APP_URL` | `https://app.olympuslabsml.com` | Protected Aether tenant application origin |
| `VITE_KYBER_URL` | `https://kyber.olympuslabsml.com` | Olympus internal Kyber origin; never linked from public marketing |
| `VITE_AETHER_DOCS_URL` | `https://docs.olympuslabsml.com` | Aether documentation origin |
| `VITE_AETHER_STATUS_URL` | `https://status.olympuslabsml.com` | Public status origin; remains unverified until the API, TLS, DNS, and structured health payload are connected |
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

## 6. Provisioning sequence

The repository implementation is now complete for the web layer. External
evidence starts with AWS authentication and a reviewed Terraform plan; no
credentialed apply has occurred from this checkout.

1. Authenticate the AWS account and confirm the intended account and region
   before touching infrastructure.
2. Run the repository checks and a credentialed plan with the staging profile.
   Staging uses the real Aurora path with auto-pause (`0` minimum ACU), no NAT
   gateway, the verified staging Amplify custom domains, and the staging status
   health URL (`https://api.staging.olympuslabsml.com/health`).
3. Apply only the checksum-bound plan through the repository's Terraform
   promotion workflow.
4. Execute the staging lifecycle: wake, migrate, publish the protected tenant
   and Kyber artifacts, verify the API and all five staging Amplify domains,
   run smoke/load checks, prove rollback, then sleep the environment. If the
   status API URL is still unset, the status page must remain explicitly
   **not yet verified**, not green.
5. After staging evidence and cost observation, create and review a separate
   production-lean plan. That profile enables the reviewed custom-domain
   association under `olympuslabsml.com`, keeps Kyber without public DNS, and
   requires a verified status health origin before promotion.
6. Enable analytics only as a separate, deliberate configuration change after
   a property owner and budget are known; it is off in the release profiles.

The tenant app and Kyber deploy machinery remain in the same Terraform and
workflow system as the public shells. Kyber is an internal operator surface:
there is no public Amplify app or Route 53 record by default, and a request to
the Kyber hostname must not expose a public application.

## 7. Status evidence boundary

`frontend/status` is a buildable public status application and is wired as the
fifth Amplify app. It consumes the backend health endpoint configured through
`VITE_STATUS_API_URL` and applies a fail-closed display policy:

- an unset URL means **Status not yet verified**;
- a non-success or unhealthy structured payload means **degraded**;
- an unreachable endpoint means **incident**; and
- only a structured healthy payload can display **operational**.

The Olympus footer link may point to the status origin as part of the public
information architecture, but the live status claim remains external evidence:
certificate, DNS, CORS, API reachability, and payload shape all have to be
verified in staging before the page can be treated as operational.

## 8. Coverage and follow-up

Focused shell tests, type checks, production builds, the launch-pack content
loader, the status fail-closed behavior, and the Terraform/profile validators
cover the implemented web layer. The remaining release work is credentialed:
verify the deployed domain matrix and API health contract in staging, capture
the smoke/load/rollback/sleep evidence, observe cost, and then promote the
reviewed production-lean profile. This document must not be used to imply that
those live checks have already run.
