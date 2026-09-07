---
title: Aether End-User Lifecycle & Integration Management
slug: architecture/aether-end-user-lifecycle
section: architecture
visibility: I
audience: [architect, dev-senior, ai]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/shared/integration_contracts/catalog.py
  - Backend Architecture/aether-backend/shared/integration_contracts/experience.py
  - Backend Architecture/aether-backend/shared/certification/readiness.py
  - Backend Architecture/aether-backend/services/integrations/connectors/catalog_endpoints.py
  - frontend/aether/src/test/e2e/lifecycle.harness.ts
  - packages/shared/connector-taxonomy.ts
last_synced_commit: "8b1ca3dc"
estimated_read_minutes: 12
toc_depth: 3
---

# Aether End-User Lifecycle & Integration Management

> **Single-source spec.** This document is the in-repo capture of the canonical
> End-User Lifecycle & Integration Management spec (the program that was authored
> outside the repository and recorded as a gap in
> `docs/plans/ENDUSER_LIFECYCLE_PHASES.md`). It fixes the vocabulary, routes,
> state model, grouping, honesty, and acceptance contracts that the public
> discovery front door, the activation machine, the Settings → Integrations
> surface, readiness CTAs, and the Campaign/Profile 360 destinations must agree
> on. When another document contradicts this file, this file wins
> (docs/source-of-truth/README.md).

The lifecycle is one continuous loop, not a set of disconnected surfaces:

```text
Discover → Start → Connect → Resolve → Understand → Act → Measure → Expand → Connect
```

Every phrase in this doc is load-bearing: the UI copy tokens, the route names,
the data markers, and the telemetry event names below are **the** canonical
surface contract. UI and acceptance suites assert them verbatim. Engineering
tokens (CampaignSource, ConnectorConfig, `secret_ref`, provider manifest,
sync-source) stay internal unless an advanced surface requires them.

---

## 1. Canonical UX copy vocabulary (§6 / §33 / §34)

Public marketing, activation, and Settings must share one vocabulary. These are
the exact tokens; they appear verbatim in the acceptance suites and must appear
verbatim in the UI (case-sensitive where the UI title-cases them).

| Token | Surface usage |
|---|---|
| `Integrations` | Section/shell name in Settings; page heading on `/settings/integrations` |
| `Connect` | Primary action on a not-connected provider row and on connect/activation forms |
| `Manage` | Secondary/manage affordance once a provider is connected |
| `Advertising` | Experience-group section for ad platforms |
| `Commerce & Revenue` | Experience-group section for commerce/revenue connectors |
| `Customer & CRM` | Experience-group section for CRM connectors |
| `Communications` | Experience-group section for the derived comms cohort |
| `Analytics & Behavior` | Experience-group section for analytics connectors |
| `Connected` | Rendered state: credential + record evidence present, not yet Ready |
| `Needs attention` | Rendered state: degraded/revoked/actionable problem on a connection |
| `Ready` | Rendered state: health proven from evidence (never optimistic) |
| `Syncing` | In-flight state while a sync runs; never a freshness claim |

Copy invariants:

1. **No fabricated freshness.** `Ready` and `Syncing` are evidence-derived
   renderings of real state — never a UI assumption that a connector "probably
   works".
2. **Connected ≠ Ready.** Connecting records a secret and flips the record to
   Connected; it never fabricates Ready. Readiness resolves only after evidence
   (sync completion / reconciliation / health check).
3. **Engineering tokens stay internal.** No `CampaignSource`, `secret_ref`,
   provider-manifest, or sync-source vocabulary on customer surfaces.

## 2. Canonical route plan (§4.6 compatibility route plan)

| Route | Role | Resolution/redirect rule |
|---|---|---|
| `/login` | Auth front door for the tenant app | After auth the tenant resolver takes over |
| `/activation` | Intent-driven activation machine | Incomplete tenants land here (resolver) |
| `/activate` | Legacy alias of `/activation` | Redirects to `/activation` during compatibility |
| `/settings` | Settings shell | Hosts nested sections |
| `/settings/integrations` | Integrations manager (canonical) | Legacy `/integrations` redirects here during compatibility |
| `/campaigns` | Campaign 360 (resolved workspace root) | Complete tenants land here |
| `/profiles` | Profile 360 | Commerce/profile evidence visible post-sync |
| `/campaign-intelligence/sources` | Campaign sources directory | Connect is via Settings/Integrations advertising group |
| `/campaign-intelligence/mapping-review` | Mapping Review queue | Exception-driven; linked from campaign-quality readiness |
| `/campaign-intelligence/quality` | Campaign-quality readiness gate | Discloses open reviews and links into Mapping Review |

**Tenant-landing resolver contract.** An incomplete tenant (no activation
intent, no commerce/advertising/comms evidence) is resolved into `/activation`.
A complete tenant (live / value-proven / expansion-ready evidence) is resolved
into the workspace root (Campaign 360). The resolver never strands a tenant and
never routes by guesswork.

## 3. Connection-state projection

The backend owns a full `ConnectionState` machine and the 11-rung
`CredentialReadiness` ladder (`shared/certification/readiness.py`). Customer
surfaces render a small, honest projection of that state. The projection is the
vocabulary the acceptance suites assert:

| Rendered state | Meaning (evidence) |
|---|---|
| `not_connected` | No record, or record without configured secret |
| `connected` | Secret + record evidence present (credential configured, reconciliation passed where supported) |
| `syncing` | A sync is in flight (cursor advancing / initial backfill) |
| `ready` | Health proven from live evidence — sync completed / provider verified. **Never optimistic.** |
| `needs_attention` | Degraded/revoked/disabled/actionable — impact disclosed, Reconnect first-class |

Data-truth rule: a revoked or degraded credential must **never** render as
Ready; it renders Needs attention with the impact disclosed (e.g. "credential
revoked — reconnect to resume") and a first-class Reconnect action.

## 4. Readiness honesty ladder

Provider/credential readiness is the 11-member `CredentialReadiness` ladder in
`shared/certification/readiness.py`
(`replay_validated`, `credential_waiting`, `credential_supplied`,
`connection_validated`, `sandbox_validated`, `partner_live`, `degraded`,
`suspended`, `revoked`, `disabled`, `scaffolded`), ranked by
`readiness_rank(...)` (spaced by 10). The honesty invariants the platform enforces
(`validate_manifest` in `shared/integration_contracts/catalog.py`):

- env-enabled provider ⇒ readiness level ≥ 3 (`credential_supplied`);
- staging-enabled ⇒ level ≥ 4 (`sandbox_validated`);
- oauth2 authentication ⇒ scopes declared;
- webhook supported ⇒ scheme declared;
- incremental sync ⇒ cursor declared.

As of this writing all 36 catalog families sit honestly at
`credential_waiting`/`scaffolded` — the truthful dormant posture. Surfaces must
not advertise live capability they cannot demonstrate (§31 data truth).

## 5. Unified integration catalog (one id-space)

There is **one** customer catalog: a derived projection over the authoritative
backend manifest union in
`Backend Architecture/aether-backend/shared/integration_contracts/catalog.py`
(`ALL_MANIFESTS` = four-group union of 36 `family.product.capability`
identities), **never** a second storage model. It is exposed through
`/v1/integration-catalog` (33 visible entries; the 3 deferred credit bureaus are
scaffolded and hidden), `/v1/tenant-integrations[/{id}]`, and
`/v1/integration-readiness`.

| Catalog group | Families | Visible surface | Experience category |
|---|---|---|---|
| Connectors (`ingestion.connector`) | 21 (`slack`, `webhook`, `shopify`, `stripe`, `hubspot`, `salesforce`, `klaviyo`, `segment`, `posthog`, `ga4`, `jira`, `linear`, `zendesk`, `intercom`, `dune`, `sendgrid`, `customerio`, `mailchimp`, `postmark`, `iterable`, `braze`) | Settings/Integrations + activation connect steps | by product/category/comms cohort |
| Ad platforms (`ads.metrics`) | 7 (`google_ads`, `meta_ads`, `tiktok_ads`, `linkedin_ads`, `x_ads`, `reddit_ads`, `microsoft_ads`) | Advertising group | `advertising_campaigns` |
| Payment rails (`payment_rails.observe`) | 5 (`privy`, `stripe`, `coinbase`, `moonpay`, `bridge`) | observe-only | — |
| Deferred credit bureaus (`credit.report`) | 3 (`experian`, `equifax`, `transunion`) | hidden (scaffolded) | none (`null`) |

The TypeScript twin (`packages/shared/connector-taxonomy.ts`) is **generated**
from this union by `scripts/generate_connector_taxonomy.py` — never hand-edited.
It carries the descriptor taxonomy (a verbatim mirror of the six-layer corpus
enums) plus `CATALOG_GROUP_ORDER`, the four family arrays + counts, `CATALOG_GROUPS`,
`CATALOG_CATEGORIES`, `CATALOG_READINESS_STATES_PRESENT`, `CATALOG_ENTRIES`
(36 rows), and `EXPERIENCE_CATEGORY_*`. Tenant FE and marketing consume
identical ids from that one generated module.

## 6. Experience categories (ADR-0010)

`experience_category` is the additive grouping enum (8 members) defined in
`shared/integration_contracts/experience.py`:

`advertising_campaigns`, `commerce_revenue`, `crm_customer`,
`communications_lifecycle`, `analytics_behavior`, `social_community`,
`customer_support`, `work_operations`.

Resolution precedence (implemented once in `experience_category_for`, mirrored
by the generated TS, never hand-synced in UI):

1. **Product rule** — an `ads` product id derives `advertising_campaigns`.
2. **Category rule** — the manifest category (commerce/crm/… ) derives the bucket.
3. **Comms cohort rule** — manifests whose data outputs carry `comms.*`
   (ADR-C11) derive `communications_lifecycle`.
4. Deferred credit bureaus derive `null` (no experience bucket until deferred).

UI sections and empty-state recommendations are grouped by this derived
category, not by a hand-maintained list. The comms cohort members rendered under
the Communications group (`klaviyo`, `sendgrid`, `customerio`, `mailchimp`, …)
are asserted from the shared catalog.

## 7. Canonical telemetry (§5, funnel)

Public and app analytics use exactly these event names (no secrets in
telemetry). Funnel: marketing → signup → auth → activation → first data →
graph-ready → first insight.

`public.integration_viewed`, `public.signup_started`, `public.signup_handoff`,
`app.signup_completed`, `activation.started`, `activation.intent_selected`,
`activation.integration_opened`, `activation.integration_connected`,
`activation.integration_failed`, `activation.account_selected`,
`activation.sdk_verified`, `activation.initial_sync_started`,
`activation.initial_sync_completed`, `activation.readiness_reached`,
`activation.completed`, `integration.add_started`, `integration.add_completed`,
`integration.reconnected`, `integration.disabled`, `integration.removed`,
`integration.sync_manual`, `integration.error_viewed`,
`integration.recovery_started`, `integration.recovery_completed`.

## 8. Integration data markers

Stable data markers let acceptance suites assert on state without depending on
layout text. The lifecycle surfaces implement these; the suites consume them via
`frontend/aether/src/test/e2e/lifecycle.harness.ts` `MARKERS`.

| Marker | Value semantics |
|---|---|
| `data-lifecycle-catalog` | Wrapper on the Settings → Integrations catalog list |
| `data-provider-family="{family}"` | One catalog row; identifies its provider family (scoped under `data-lifecycle-catalog`) |
| `data-connection-state="{state}"` | Row's rendered state: `ready` \| `connected` \| `needs_attention` \| `syncing` \| `not_connected` |
| `data-connect-form="{family}"` + `data-credential-field="{field}"` | Connect/credential form field (family-scoped); e.g. `shopify`/`api_key`, `google_ads`/`customer_id`, `google_ads`/`refresh_token`, `meta_ads`/`access_token`, `klaviyo`/`api_key` |
| `data-account-picker` | Multi-account discovery/selection surface (radio account list) |
| `data-activation-intent="{intent}"` | Activation intent selector (e.g. `sell_online`) |

## 9. Acceptance suites (E2E A–E)

The executable acceptance spec is the Playwright lifecycle suites under
`frontend/aether/src/test/e2e/` (`lifecycle-A-…` … `lifecycle-E-…`), one serial
journey per seeded scenario tenant. They are gated on
`E2E_TENANT_EMAIL[_A.._E]` / `E2E_TENANT_PASSWORD[_A.._E]` (fallback to the
shared pair) and skip honestly without the R3/R4 integration environment. See
`docs/operations/ENDUSER_LIFECYCLE_E2E.md`.

| Suite | Scenario | Journey |
|---|---|---|
| A | E-commerce + ads first-time tenant | signup → activate → connect Shopify → connect Meta Ads → verify SDK → initial sync → readiness → enter Aether → Campaigns resolved; Profiles receive commerce/profile evidence |
| B | Returning expansion | Campaign 360 → contextual add advertising → Settings/Integrations → connect Google Ads → select account → sync → return |
| C | Communications | Settings/Integrations → Communications → connect Klaviyo → sync → Campaign 360 + Profile 360 comms facts present |
| D | Credential recovery | revoked → degraded → impact disclosed → reconnect → health restored (never Ready while revoked) |
| E | Mapping exception | ambiguous ad campaign → readiness review → Mapping Review → resolve → Campaign 360 canonical identity updates |

The Mapping Review surface is exception-driven and reachable from the
campaign-quality readiness gate. Resolution writes the evidence mapping onto the
canonical campaign identity (`#campaign-id-input`, Confirm resolution, status
filter group) so the resolved review leaves the open queue and lists under the
`resolved` filter.

## 10. Ownership and derivation rules

- **One id-space.** All consumer code (tenant FE, activation, marketing public
  directory, parity tests) reads provider/category identity from the generated
  `packages/shared/connector-taxonomy.ts` mirror or the backend manifest union —
  never a hand-copied list.
- **Derived, never re-derived by hand.** If the backend catalog or experience
  module changes, regenerate the TS twin (`python scripts/generate_connector_taxonomy.py`)
  and update the parity contract tests in `tests/contracts/`.
- **Honest everywhere.** Any surface that claims Connect/Ready/available must be
  backed by a manifest entry at the corresponding readiness level; dormant is
  the default until evidence exists.
- This spec's drift guard is the lifecycle acceptance suites + the parity
  contract tests; `docs/source-of-truth` is exempt from the docs_drift scanner
  by design, so changes here are reviewed, not auto-stamped.
