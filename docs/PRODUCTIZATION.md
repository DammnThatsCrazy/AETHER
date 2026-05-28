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

### 🔴 Blocker 1 — Tenant Onboarding UI

**What's missing:** There is no UI for a new customer to create a tenant, configure their SDK, and get API keys. The only current path is direct PostgreSQL + API calls, which requires engineering support.

**Required:**
- `/signup` flow: org name, industry sector, contact info → create tenant record
- API key generation and display (one-time reveal)
- SDK snippet generator: show a 5-line JS/Python SDK installation with the tenant's key pre-filled
- Provider key configuration UI: allow non-engineer analysts to add BYOK provider credentials via a form (maps to existing `/v1/providers/keys` endpoint)

**Estimated effort:** 2–3 weeks (frontend + 2–3 backend endpoints)

---

### 🔴 Blocker 2 — SDK Installation Guide for Web2-First Companies

**What's missing:** All existing SDK documentation assumes the operator is tracking on-chain events or Web3 wallets. There is no guide for a Web2 e-commerce company or SaaS business to integrate Aether with zero blockchain context.

**Required:**
- `docs/SDK-WEB2-QUICKSTART.md` — Step-by-step guide for a Web2 operator: install SDK, instrument checkout events, configure Plaid for financial data, configure Meta Ads for attribution, view first entity in Profile360 within 24 hours
- Web2 event taxonomy documentation: what events to track (page_view, checkout, signup, session_start) vs. Web3 events (swap, stake, vote)
- Smoke test for Web2-only tenant path (current `smoke_test.py` assumes on-chain events)

**Estimated effort:** 3–5 days

---

### 🔴 Blocker 3 — Graph Visualization Frontend

**What's missing:** The Kyber app has Profile360 components (entity cards, timeline, identity tabs) but no graph canvas. An operator cannot see the intelligence graph — they can only look up individual entities by ID.

**Required:**
- Force-directed graph canvas (Cytoscape.js or Sigma.js) with node shapes/colors per entity class
- 1-hop and 2-hop neighborhood expansion from any node
- Profile360 panel slide-in on node click
- Four view modes: Relationship Map, Attribution Web, Journey Flow, Geographic Intelligence
- See `docs/FRONTEND-ARCHITECTURE.md` for full specification

**Estimated effort:** 4–6 weeks (graph canvas is the highest-effort frontend item)

---

### 🟡 High Priority 4 — API Key Management UI

**What's missing:** Analysts need to configure provider keys (Plaid, credit bureaus, ad platforms) without engineering intervention. The backend BYOK vault exists; there's no UI over it.

**Required:** Simple key management page: list configured providers, show last-tested status, add/rotate/revoke keys via form.

**Estimated effort:** 1 week

---

### 🟡 High Priority 5 — Webhook Configuration UI

**What's missing:** Customers need to configure event ingestion endpoints (where their application sends events to Aether). Currently requires direct API configuration.

**Required:** Webhook management page: create endpoint, show endpoint URL, view recent deliveries and errors, configure retry policy.

**Estimated effort:** 1 week

---

### 🟡 High Priority 6 — Data Freshness SLA Documentation + Alerting

**What's missing:** No documented SLA for how fresh Profile360 data is. Operators have no visibility when gold tables are lagging or when a provider adapter is failing silently.

**Required:**
- SLA document: gold tables refreshed every 15 minutes (Provider adapters: nightly sync, on-demand trigger available)
- Internal alerting: alert when any gold table compute job lags > 30 minutes
- Surface provider health status in API key management UI (last successful sync, error count)
- `/v1/providers/health` endpoint (backend exists; surface it in the UI)

**Estimated effort:** 3–5 days

---

### 🟠 Medium Priority 7 — Demo Tenant with Synthetic Data

**What's missing:** No safe way to show a prospect what Aether looks like with real data. Production tenants are isolated; a demo requires a pre-populated sandbox tenant.

**Required:** Synthetic entity generator that creates 500–1,000 realistic (non-PII) entities with relationships, journey histories, social profiles, and behavioral signals. Runnable against the demo tenant via a seed script.

**Estimated effort:** 1 week

---

### 🟠 Medium Priority 8 — `/v1/capabilities` Endpoint

**What's missing:** Operators cannot programmatically discover which Profile360 sub-resources are available for their tenant (depends on which providers they've configured). This makes SDK integration opaque.

**Required:** `GET /v1/capabilities` → returns which profile sub-resources are available, which providers are configured and healthy, and which consent purposes have been granted by the tenant.

**Estimated effort:** 2–3 days

---

### 🟠 Medium Priority 9 — Billing Integration

**What's missing:** No usage-based billing. Revenue cannot be collected.

**Required:** Stripe metered billing integration: track API calls per tenant per day, generate monthly invoice based on usage tier, surface usage dashboard in tenant admin UI.

**Estimated effort:** 2–3 weeks

---

## Recommended First-Customer Onboarding Path

**Target first customer profile:** A Web2 e-commerce company (Shopify-based, $5M–$50M GMV, no blockchain activity) that wants to understand customer behavior across their Shopify store, email campaigns, and Meta/Google ad spend.

### What they would get on Day 1

1. Install Aether SDK in their Shopify store (5 lines of JS)
2. Connect Plaid to pull bank account signals (optional, higher consent tier)
3. Connect Meta Ads and Google Ads via BYOK provider keys
4. Start seeing entities in Profile360 within 24 hours of first events
5. Social tab (if they've linked social accounts for their customers) — Twitter, Instagram, YouTube via BYOK
6. Journey Economics: ROAS per campaign, funnel drop-off analysis
7. Intelligence tab: churn risk signals, LTV predictions, behavioral patterns

### What they would NOT get on Day 1 (honest scope)

- Graph visualization (blocked until frontend is built)
- On-chain intelligence (no wallets to link)
- Credit bureau signals (requires `credit` consent from their end-users)
- Real-time streaming (15-minute gold table refresh is the current SLA)

### 5 Actions Before First Customer Signs

1. **Build tenant onboarding UI** (Blocker 1) — without this, every customer requires engineering support to onboard
2. **Write Web2 SDK quickstart** (Blocker 2) — without this, the first engineer at the customer will be confused within 10 minutes
3. **Fix smoke_test.py for Web2-only path** — run the smoke test against a Web2-only tenant to confirm no hidden dependencies on on-chain events
4. **Add `/v1/tenant/onboard` endpoint** — creates tenant, generates API key, returns SDK snippet in one call
5. **Document data freshness SLA** — customers will ask "how fresh is this data?" on day 1; have a written answer

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
