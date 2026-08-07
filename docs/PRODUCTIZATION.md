---
title: Productization Gap Analysis — First Paying Customer
slug: productization
section: architecture
visibility: I
audience: [exec, architect]
status: stable
since_version: "8.8.0"
canonical_owner: product@aether
estimated_read_minutes: 15
toc_depth: 3
last_synced_commit: 739bd63c
---

# Productization Gap Analysis — First Paying Customer

This document assesses what's production-ready, what's blocking the first paying customer, and the recommended path to initial revenue. It is grounded in the actual codebase state — not aspirational.

---

## What's Production-Ready

The following subsystems are implemented, tested, and CI-verified:

> **Readiness terminology.** A ✅ in this section is a **code-state** claim:
> implemented, tested, and CI-verified. It is *not* a claim of production + scale
> readiness. The canonical readiness authority is the production status scorecard
> (`make production-status`, `scripts/production_status.py`) — currently **overall
> 3.77/5, pre-production**. Per the scorecard most areas below are **release-ready
> (4/5)** with minor gaps, and several carry release blockers: production
> infrastructure is not provisioned (deployment/cloud 3/5), ML model artifacts are
> not published (scale 3/5), and the external smart contract audit is outstanding.
> Only a few surfaces (Profile360 aggregator, customer frontend, campaign
> intelligence) score 5/5. Where this document and the scorecard disagree, the
> scorecard wins.

### Data Infrastructure
- ✅ Event ingestion pipeline (event lake, enrichment, ASN connection-type enrichment)
- ✅ ClickHouse gold-tier schemas (12 tables covering tiers, PNL, social, temporal, journeys, ad spend, financial accounts)
- ✅ Data freshness model: live / recent / stale thresholds with `computed_at` timestamps on all aggregated outputs
- ✅ Window-aware queries: 30d / 60d / 90d / lifetime across all gold tables
- ✅ S3 Iceberg lifetime rollup architecture (schema-level; not yet connected to nightly batch job)

### Entity Graph
- ✅ Neptune/Gremlin graph backend with 35+ VertexType and 50+ EdgeType definitions
- ✅ Unified entity taxonomy: governance_org, exchange, yield_platform, brand, marketplace, media_entity (Web2 + Web3 collapsed into domain-agnostic categories)
- ✅ Graph traversal (1-hop, 2-hop neighbor queries)
- ✅ Entity cluster detection via identity resolution
- ✅ Delegation record model

### Profile360 Aggregator
- ✅ 1,159-line additive aggregator layer supporting sessions, devices, platforms, wallets, financials, intelligence, loyalty, behavioral signals, attribution, relationships, graph, tier, asset composition, PNL, trading profile, location history, temporal heatmap, social intelligence, journey economics, device performance, funnel, retarget recommendations, web2 profile
- ✅ Sub-resource envelope pattern (consistent wire format across all endpoints)
- ✅ All 15 new profile sub-resource API endpoints registered

### External Provider Adapters
- ✅ 51 provider adapters across 17 categories (BYOK pattern — tenants bring their own keys)
- ✅ Social: Twitter, YouTube, Instagram, TikTok, Reddit, LinkedIn, Spotify, Telegram, Discord, GitHub, Farcaster, Lens (12 platforms)
- ✅ Brokerage: Alpaca, IBKR, Schwab, Fidelity, Robinhood, SoFi, Betterment, Vanguard, E*TRADE, TD Ameritrade, Webull (11 adapters)
- ✅ Open banking: Plaid
- ✅ Credit bureaus: Experian, Equifax, TransUnion
- ✅ Ad platforms: Twitter Ads, Google Ads, LinkedIn Ads, Meta Ads, TikTok Ads
- ✅ Market data, blockchain RPCs, block explorers, DEX intelligence, identity enrichment (existing)

### Intelligence Layer
- ✅ 6 ML models trained: identity resolution, churn prediction, LTV prediction, anomaly detection, campaign attribution, campaign optimization
- ✅ Signal translator: 20 behavioral signal templates (universal + social + financial + onchain)
- ✅ PNL calculator service
- ✅ Retarget recommendation engine (score → recommendation → review → execute)

### OODA Suggestion Intelligence
- ✅ Canonical `Suggestion` entity with 15 lifecycle statuses across 8 OODA phases (observe → orient → suggest → review → act → measure → learn → closed)
- ✅ Policy-governed lifecycle engine: approval gates for SECURITY / GOVERNANCE / IDENTITY / GRAPH_HEALTH / RELIABILITY classes and risk_score ≥ 0.7
- ✅ Priority scoring formula: weighted composite of impact (0.30), confidence (0.20), urgency (0.20), evidence quality (0.15), tenant value (0.15) minus reversibility-adjusted risk
- ✅ Tenant isolation enforced on every query, cache key, event, audit entry, and realtime channel
- ✅ 10 signal adapters: data quality, SDK health/drift, graph, profile360, notifications, recommendations, governance, reliability, Noesis
- ✅ Audit trail: every lifecycle transition appends an immutable `SuggestionAuditEvent`
- ✅ Outcome loop: MEASURED → LEARNED → CLOSED with feedback signals back to scoring
- ✅ Kyber OODA Command Center: cross-tenant feed, evidence drawer, policy panel, review queue (approve / reject / suppress)
- ✅ Aether tenant feed: title / summary / what / why / impact + helpful / not helpful / dismiss feedback
- ✅ Noesis read-only integration: `suggestion_lookup`, `suggestion_summary`, `suggestion_review_queue`, `suggestion_explain`, `suggestion_outcome_lookup` intents
- ✅ Realtime channels: `suggestions.feed`, `suggestions.review`, `suggestions.outcomes`
- ✅ Feature-flagged (`AETHER_SUGGESTIONS_ENABLED=false`); execution disabled by default (`AETHER_SUGGESTIONS_EXECUTION_ENABLED=false`)

### Security + Compliance
- ✅ Consent enforcement: registry-derived consent purposes (canonical set in `packages/shared/contracts/consent-registry.json`; base + explicit opt-in categories)
- ✅ PII masking: 3 analyst role tiers (readonly, standard, compliance) with field-level masking rules
- ✅ Tenant isolation (JWT-based, all queries scoped by tenant_id)
- ✅ GDPR/SOC2 architecture (consent audit log, data deletion hooks, PII-safe export)
- ✅ Authentication middleware
- ✅ BYOK key vault (no credentials in code)

### TypeScript Type Contracts
- ✅ 13 shared type packages covering all Profile360 sub-resources
- ✅ Canonical `Profile360Response` and `SubResourceEnvelope` contracts
- ✅ Domain-agnostic entity taxonomy aligned with backend

---

## Mobile, Continuity & Compliance Productization — Complete (M0–M8)

The turnkey productization program (M0–M8, delivered as PR #515 — one PR,
milestone-commit train, 21 commits, rebased onto `origin/main`) turned the
mobile and cross-device surfaces from scaffolds into a first-class, governed,
compliance-ready product plane. This section summarizes what was done, why it
matters, and what it means for the product moving forward.

### What was done (themes)

- **Mobile surfaces** — `GET /v1/mobile/config` + distribution profiles;
  `packages/mobile-ui` (theme, typed navigation); offline cache framework; Aether
  Mobile screens (Today / Copilot / Explore / Alerts / Account); Kyber Mobile
  operator screens (Pulse / Exceptions / Incidents / Runs / Reviews / Briefings);
  Aether desktop notification center with quiet-hours/timezone preference
  persistence.
- **Continuity** — redacted mobile notification projection (server-derived push
  titles/bodies, never raw payloads); continue-on-phone with all 10 sync event
  types wired + operator continuation router; desktop↔mobile handoff surfaces.
- **Governed mobile actions** — a mobile action adapter onto the *existing* kyber
  ops command plane (no second plane, no generic mutation channel), Tier 0–3 UI,
  step-up via the existing `StepUpService`, mobile-bound proof-key attestation,
  durable command receipts (`verified | executed_unverified | denied | failed | expired`).
- **Reliability** — permanent delivery-safety CI validator; lease-guarded
  delivery/jobs release (closes stale-worker split-brain double-delivery); inbox
  lost-update elimination; ops alerts no longer false-succeed with zero channels.
- **Compliance** — per-app Apple Privacy Manifest + Play Data Safety generated
  with an honest `deletion_mechanism`; mobile DSR erasure end to end
  (installations + kyber-bound device attestation); kyber mobile-actions
  tenant-scoped end to end; demo-seed guarded so seeded statuses are never
  mistaken for production truth.
- **Security** — enterprise-inquiry email body HTML-escaped (email XSS closed) +
  subject header-injection defense.

### Why it matters

Mobile was the largest unimplemented surface between the product and a first
paying customer using Aether from a phone. Cross-device continuity and governed
actions are how operators run the platform from anywhere without an ungoverned
mutation channel. Delivery reliability and DSR/compliance are hard prerequisites
for store submission and enterprise trust.

### Value

- The apps are **code-complete for a design-partner demo and store submission** —
  the remaining work is activation (credentials/accounts), not implementation.
- The new gates (`delivery-safety-check`, `mobile-compliance-check`) are part of
  `make ci-check`, so these invariants cannot silently regress.
- The M8 adversarial review (6 lenses, 30 findings, 0 refuted) hardened the
  delivery and compliance planes that every surface depends on.

### What it means moving forward

- The production-status scorecard remains **3.77/5, pre-production
  (release-shaped)**. The release-blockers are all external: smart-contract
  audit, production infra, zero `PARTNER_LIVE` economic providers, and the
  node-tar supply-chain critical (requires the Expo SDK 51→57 bump). They are
  tracked in `reports/mobile-productization/external-blockers.json`.
- Next milestones are **activation, not code**: hosted-CI native compile,
  credential provisioning (APNs / FCM / SES), store submission, and the
  documented physical-device matrix.

---

## What's Blocking First Paying Customer

The following items remain open. Items previously listed as blockers that are
now complete are documented in the "What's Production-Ready" section above.

### ✅ Previously Blocking — Now Resolved

| Item | Status | Notes |
|---|---|---|
| Tenant Onboarding UI | ✅ Shipped | 3-step signup (org, OTP, API key reveal), SSO, plan selection; onboarding health dashboard |
| Graph Visualization Frontend | ✅ Shipped | Cytoscape.js force-directed canvas with inspector, clustering, trust/risk overlays |
| API Key Management UI | ✅ Shipped | Full CRUD in Settings — create, reveal (one-time), revoke; platform tagging; permission scopes |
| Synthetic Demo Data | ✅ Shipped | `tests/load/generate_synthetic.py` — deterministic NDJSON across 5 scenarios |

---

### 🔴 Blocker 1 — E2E Tests for Onboarding Critical Path

**What's missing:** No Playwright/Cypress suite covering the signup → OTP → API key reveal → billing portal flow. Without automated coverage this critical path cannot be verified on every deploy.

**Required:** `frontend/aether/src/test/e2e/onboarding-critical-path.spec.ts` — signup, OTP verify, API key reveal, SDK snippet rendered, billing redirect. Edge cases: invalid email, expired OTP, plan change.

**Estimated effort:** 1–2 weeks

---

### 🟡 High Priority 2 — Webhook Configuration UI

**What's missing:** The backend webhook routes exist (`/v1/notifications/webhooks`) but there is no tenant-facing UI for creating and managing outbound webhook endpoints.

**Required:** Settings section showing configured webhooks, add/edit/delete form, test-ping button, recent delivery log with status and latency.

**Estimated effort:** 1 week

---

### 🟡 High Priority 3 — Stripe Billing Wire-Up

**What's missing:** `services/billing/providers/stripe_provider.py` contains a readiness stub — methods raise `ProviderDisabledError` instead of calling the Stripe API. Revenue cannot be collected programmatically.

**Required:** Wire `sync_tenant`, `create_usage_record`, and `export_invoices` to real Stripe API calls. Config keys (`STRIPE_SECRET_KEY`, `STRIPE_PRODUCT_MAPPING_JSON`) already in `.env.example`.

**Estimated effort:** 2–3 weeks

---

### 🟠 Medium Priority 4 — Infrastructure / External

| Item | Action |
|---|---|
| Production AWS infra | Run `scripts/bootstrap_aws_secrets.py` + Terraform |
| External smart contract audit | Commission Trail of Bits / OpenZeppelin before mainnet with real funds |
| ML model artifacts | Run training pipelines in `ML Models/aether-ml` and publish |
| Dune feeder persistent backend | Configure S3/Postgres; remove `AETHER_ENV` guard |
| Load baselines | `make load-smoke` against staging → `docs/LOAD-BASELINES.md` |
| Neptune capacity | Provision staging Neptune; replay synthetic merge workload |
| Agent Layer durable storage | Enable Redis per `docs/AGENT-LAYER-PRODUCTION.md` |

---

## Recommended First-Customer Onboarding Path

**Target first customer profile:** A Web2 e-commerce company (Shopify-based, $5M–$50M GMV, no blockchain activity) that wants to understand customer behavior across their Shopify store, email campaigns, and Meta/Google ad spend.

### What they would get on Day 1

1. Install Aether SDK in their Shopify store — see [SDK Web2 Quickstart](SDK-WEB2-QUICKSTART.md)
2. Connect Plaid to pull bank account signals (optional, higher consent tier)
3. Connect Meta Ads and Google Ads via BYOK provider keys (Settings → Provider Keys)
4. Start seeing entities in Profile360 within 15 minutes of first events
5. Social tab (if they've linked social accounts for their customers) — Twitter, Instagram, YouTube via BYOK
6. Journey Economics: ROAS per campaign, funnel drop-off analysis
7. Intelligence tab: churn risk signals, LTV predictions, behavioral patterns

### What they would NOT get on Day 1 (honest scope)

- On-chain intelligence (no wallets to link)
- Credit bureau signals (requires `credit` consent from their end-users)
- Real-time streaming (15-minute gold table refresh is the SLA — see [Data Freshness SLA](DATA-FRESHNESS-SLA.md))

### 3 Actions Before First Customer Signs

1. **Add E2E tests** (Blocker 1) — without CI coverage of the onboarding critical path, regressions will reach customers
2. **Commission smart contract audit** — required before mainnet deployment with real funds
3. **Provision production infrastructure** — AWS/Terraform must be live before accepting production traffic

---

## What Exists That Competitors Cannot Easily Replicate

1. **Entity-agnostic graph** — most intelligence platforms are domain-specific (marketing CDP, DeFi analytics, HR analytics). Aether's graph covers all entity types in one schema.
2. **ML models trained on multi-domain signals** — identity resolution, churn, LTV, attribution trained on Web2 + Web3 signals together.
3. **Consent-first architecture** — consent enforcement is a first-class system component, not a checkbox. GDPR/SOC2 compliance is structural, not bolted on.
4. **51-provider BYOK adapter registry** — the time to add a new data source is measured in hours, not months. Tenants bring their own credentials — Aether never holds customer API keys.
5. **Agentic entity model** — AI agents as first-class graph entities with delegation chains, spending limits, and execution traces. No competitor currently models this.

---

## Version Note

This document reflects the state of the codebase at commit `df45786` and the Phase 2 extension (PR #187 + Phase 3 entity-agnostic expansion). The "What's Production-Ready" framing was revised at the M8-F commit tip to be consistent with the canonical readiness scorecard (`make production-status`; overall 3.77/5, pre-production) — ✅ marks code-state (implemented + CI-verified), never a substitute for scorecard readiness. Provider counts: 51 providers, 17 categories. TypeScript contracts: 13 shared type packages. Gold schemas: 12 ClickHouse tables.
