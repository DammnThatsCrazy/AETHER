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
last_synced_commit: df45786
---

# Productization Gap Analysis — First Paying Customer

This document assesses what's production-ready, what's blocking the first paying customer, and the recommended path to initial revenue. It is grounded in the actual codebase state — not aspirational.

---

## What's Production-Ready

The following subsystems are implemented, tested, and CI-verified:

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
- ✅ Consent enforcement: 8 consent purposes (analytics, marketing, web3, agent, commerce, personalization, credit, location)
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

This document reflects the state of the codebase at commit `df45786` and the Phase 2 extension (PR #187 + Phase 3 entity-agnostic expansion). Provider counts: 51 providers, 17 categories. TypeScript contracts: 13 shared type packages. Gold schemas: 12 ClickHouse tables.
