---
title: Aether Frontend Architecture & Designer Handoff
slug: architecture/frontend
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - frontend/aether/src/
  - frontend/kyber/src/
  - frontend/shared/src/
canonical_owner: frontend@aether
estimated_read_minutes: 35
toc_depth: 4
last_synced_commit: "1c1b7416"
---

# Aether Frontend Architecture & Designer Handoff

---

## ⚠️ Two Frontends — Critical Distinction

There are two separate frontend applications. **Do not mix them up.**

| App | Directory | Audience | Purpose |
|-----|-----------|----------|---------|
| **Aether** | `frontend/aether/` | External paying tenants / customers / clients | Self-service: sign up, install SDK, manage API keys, view their own intelligence graph, entity profiles, campaigns, geographic intelligence |
| **Kyber** | `frontend/kyber/` | Internal Aether team / operators only | Operator mission control: monitor real tenants, diagnose system health, approve agent actions, and review entity clusters |

### What belongs where

**Aether (customer-facing) contains:**
- Auth flows (signup, login, SSO, billing) — login / verify-email / SSO
  consume trust-plane **session grants** (durable, revocable `sess_` tokens
  sent as `Authorization: Bearer`; see `features/auth/grant.ts` and
  `sessionLogin` in `features/auth/auth-context.tsx`) and fall back to the
  legacy `api_key` response shape only when the backend trust-plane flag is
  off; signup skips the API-key reveal step when a session is issued
- The intelligence **graph canvas** showing the tenant's users, organizations, and AI agents — layer/overlay toggles (H2H/H2A/A2H/A2A, risk, trust, campaign, economic, fraud), path finder with multi-hop traversal modes (Shortest / Strongest / K-Shortest), cluster panel, and cluster drill-down to Cluster360; summary strip (entity/relationship/cluster/risk-alert counts), truncation warning when entity set exceeds 200, replay mode with date picker, observation-class node styling (solid/dashed/dotted borders), Recommendation/Prediction outcome panel in Inspector, **PathInspector** panel (shown in right panel when a path is active — Overview/Hops/Evidence/Score tabs, save-to-investigation action)
- **Cluster360** (`/clusters/:clusterId`) — 7-tab cluster surface: Overview (type, state, formation reason, confidence, risk score, properties), Members (paginated DataTable with confidence + join date), Timeline (merge/split/growth events), Economic (revenue, spend, LTV, value tier, top-member breakdown), Campaigns (attributed campaigns, top channel, conversion rate), Risk (aggregate score, fraud network link, alert count, evidence refs, high-risk members), Geography (country distribution bars, concentration score)
- **Semantic zoom** — graph canvas supports server-backed macro→cluster→entity zoom: macro level uses a `depth: 1` query scoped to cluster node types (the backend minimum depth is 1; depth-0 is rejected); clicking a cluster fetches depth-1 member expansion via `useGraphZoom(tenantId?)`
- **Entity Profile360** panels — what tenants drill into when they click a graph node
- **Geographic Intelligence** view — their users by location
- **Social Intelligence** panels — their users' social platform presence
- **Recommendation cards** — pending retargeting / campaign actions for the tenant to approve
- **Suggestion feed** — OODA-driven prioritised recommendations with helpful/not helpful/dismiss feedback
- Campaign management, attribution dashboards, Campaign 360 (`/campaigns/:id`) — per-campaign overview, population, clusters, conversions, and attribution with referral/source-class rollups; communication rates expose governed value state, sample sufficiency, Wilson uncertainty, and lineage, and the tenant UI withholds values that do not meet the registry minimum sample
- Profile360 and Journey Explorer source evidence — journey steps surface AI provider/product, mediation type, verification, confidence, classifier version, attribution eligibility, and attributed net revenue when backed by active credits; excluded crawler/scanner noise remains counted in journey quality metadata
- API key management, plan management, usage metering
- Webhook endpoint management — add/test/delete outbound delivery endpoints
- **Notification center** — paginated inbox for notification-intelligence and agent alerts with severity filtering, read/acknowledge state, and quiet-hours/timezone preference persistence (`pages/notifications/notification-center-page.tsx`)
- **Continue-on-phone** — continuation creation, recent mobile activity, and resume surfaces backed by the `/v1/continuations` and `/v1/client-sync` planes (`features/continuation/`)

**Kyber (internal operator console) contains:**
- Mission dashboard — real-time system health across all tenants
- **Intelligence Operating System** (`/intelligence-os`) — graph-centric operator workspace that keeps relationship context, evidence, investigation memory, governed decisions, supervised actions, verification, and learning in one continuous surface
- Noesis — operator graph view of cross-tenant entity relationships; graph explorer at `/noesis/graph`, fleet graph at `/noesis/fleet`
- **Fleet Graph** (`/noesis/fleet`) — tenant portfolio comparison table showing per-tenant operational envelope (graph node count, fraud network count, SDK health score, status); privileged operator tenant-entry modal with access reason, purpose enum, and duration; active operator session banner with exit action; all actions immutably audited via `POST /v1/kyber/operator/tenant-entry`
- Live event stream — raw event firehose for debugging
- Entity admin — manage any entity across any tenant
- Command center — controller management; behind `enableAgentCommandCenter`, one-person-ops live panels: worker/runtime health strip (queue depth, workers, stale, active/failed/stuck runs), run history with stuck highlighting, briefings feed with on-demand generation, compressed ops alerts, and a confirm-gated kill switch (`/v1/agent/health`, `/v1/agent/runs`, `/v1/agent/briefings`, `/v1/agent/ops/alerts`)
- **Operator continuation panel** — operator-side continuation creation and recent mobile activity for governed action handoff (`features/continuation/`)
- **Command receipts** — durable receipt visibility (`verified | executed_unverified | denied | failed | expired`) for governed mobile actions, surfaced on the commands page (`features/kyber-ops/command-receipts.tsx`)
- Diagnostics — circuit breakers, error tracking, dependency health
- Review / approval workflows — human-in-the-loop agent approvals; approval commits staged graph mutations when staged-mutation review is enabled (badge + submitting/error modal states)
- **OODA Suggestion Command Center** — cross-tenant suggestion feed with evidence drawer, policy panel, and outcome tracker
- **Suggestion review queue** — approve, reject, or suppress suggestions with reason capture
- **ML Operations** — model fleet health, artifact status, and extraction defense monitoring
- **Measurement Overview** — spend, attributed revenue, ROAS, data quality, and connector health across all tenants (`/measurement/overview`)
- **Attribution Studio** — per-conversion attribution runs, model selection, backfill controls; reads `?campaign_id=` URL param to pre-filter runs and surface a "Compare in Campaign 360 →" contextual link (`/measurement/attribution`)
- **Journey Explorer** — chronological journey timeline with attribution weight annotations (`/measurement/journeys`)
- **Conversion Explorer** — canonical conversion detail, revenue history, attribution drill-down (`/measurement/conversions`)
- **Campaign Intelligence** — campaign hierarchy, performance metrics, spend/ROAS time-series (`/measurement/campaigns`)
- **Campaign 360** — full per-campaign drill-down: overview metrics, population funnel (observed→resolved→engaged→converted→attributed), identity clusters, entities, journeys, conversions, attribution model comparison, graph anchor, quality/freshness diagnostics (`/measurement/campaigns/:campaignId`); launched via "Campaign 360 →" links in Campaign Intelligence rows and Profile360 attribution panel
- **Campaign Registry** (v8.11.0+) — canonical campaign list with origin/platform/status filters, alias management, external references view (`/campaign-intelligence/registry`)
- **Campaign Sources** (v8.11.0+) — connected ad platform sources with sync controls and health indicators (`/campaign-intelligence/sources`)
- **Mapping Review** (v8.11.0+) — unresolved/ambiguous attribution evidence queue; resolve/ignore actions create durable aliases and trigger reprocessing (`/campaign-intelligence/mapping-review`)
- **Campaign Quality** (v8.11.0+) — measurement mapping rate gauges and quality metrics (`/campaign-intelligence/quality`)
- **Custom Campaign** (v8.11.0+) — creation form for custom (non-platform) campaigns (`/campaign-intelligence/new`)
- **Measurement Operations** — connector and source-classification health, classifier-version coverage, repair status, tenant drill-down, and confirm-gated restart/backfill/recompute/repair actions (`/kyber/measurement`)
- Lab — backend-supported test and replay tools

**Shared (`frontend/shared/` — npm package `@aether/ui`):**
- Design system components used by both Aether and Kyber
- **Olympus brand rendering boundary:** `packages/brand` (`@olympus/brand`)
  owns framework-free identity, provider, entity, status, token, motion, and
  responsive metadata. `@aether/ui` owns the React renderers (`AetherLockup`,
  `KyberLockup`, `NavigationIcon`, `ProviderMark`, `EntityAvatar`, semantic
  indicators, and surfaces). Applications consume those renderers rather than
  embedding marks, provider assets, raw navigation glyphs, or per-route visual
  theme forks. Unreviewed provider marks render the named neutral fallback.
  See the [Aether consumer matrix](brand-system/aether-consumer-matrix.md),
  [brand-system architecture](brand-system/architecture.md), and
  [migration guide](brand-system/migration.md).
- `TimeWindowSelector`, `FreshnessIndicator`, `EvidenceDrawer`, `UsageBar`, `Toast`, etc.
- **Canonical value display** (`frontend/shared/src/value/`): `ValueDisplay`, `USDValue`, `NativeValueBreakdown`, `ValuationWarning` + `formatUSD` / `formatNativeValue` / `formatAetherValue`. USD-first with native drilldown; absent/unpriced values render "Value unavailable", never `$0.00`. All financial values must render through these — enforced by `scripts/validate_frontend_value_display.py`. See [`FINANCIAL_VALUE_SEMANTICS.md`](source-of-truth/FINANCIAL_VALUE_SEMANTICS.md).
- Graph layer type contracts: `RelationshipLayer` (`H2H | H2A | A2H | A2A`), `RELATIONSHIP_LAYERS`, `LAYER_DESCRIPTIONS`, `EDGE_LAYER_MAP`, `classifyEdgeType`, `countEdgesByLayer` — shared between Aether and Kyber graph health features
- **Path intelligence types** (Phase 20): `PathClassification`, `PathNode`, `PathEdge`, `PathScoreBreakdown`, `RelationshipPath`, `PathExplanation`, `TraversalSnapshot`, `PathQuery`, `PathQueryResponse`, `NodeExpansionRequest`, `NodeExpansionResponse`, `DeepTraversalJob` — canonical TS contracts in `packages/shared/operational-intelligence.ts`, mirroring the Pydantic models exactly

### Runtime data-truth contract

Aether and Kyber are live API clients in every normal environment. Their
production entrypoints cannot import mocks, fixtures, test factories, or
`msw/browser`. Environment configuration is explicit and fail-closed:
`local`, `staging`, and `production` are the normal values, while `test` is
injected by automation. Invalid configuration renders only the startup error
surface.

Every data-bearing route distinguishes loading, successful-empty, populated,
and error/unavailable. Permission or capability-disabled is separate where
applicable. A request failure never becomes an empty array, a healthy status, a
zero metric, or example records. Missing evidence renders unavailable or
insufficient-sample.

Demo records are created only by the versioned backend seed engine. Normal
frontend/backend startup never seeds, and demo disclosure is driven by backend
tenant provenance. A scoped startup migration unregisters only legacy
`mockServiceWorker.js` registrations and removes only their caches.

---

## What Aether Is (Canonical Framing)

Aether is **intelligence graph infrastructure** for organizations operating in an increasingly autonomous world.

It is NOT a marketing platform, CDP, analytics dashboard, or spyware. It is operational intelligence — the connective infrastructure layer that transforms fragmented operational signals into governed, relationship-aware understanding.

Operators use Aether to:
- **Understand operational behavior** across every entity type interacting with their systems
- **Unify fragmented intelligence** from disconnected platforms, identifiers, and event streams
- **Resolve identities** across systems — the same human appearing in Shopify, Farcaster, Plaid, and Twitter is one entity
- **Map relationships** between humans, organizations, AI agents, and operational systems
- **Detect hidden patterns and operational risk** — fraud clusters, behavioral anomalies, attribution gaps
- **Coordinate decisions** in environments where autonomous systems are increasingly involved

The platform serves e-commerce companies, SaaS businesses, financial institutions, Web3 protocols, media platforms, and any organization that needs to understand the entities it operates alongside. **There is no Web2 vs. Web3 distinction in the product.** An entity is an entity. Intelligence is intelligence.

---

## Core Mental Model

**Everything starts with the graph.** A graph node is an entity — a human, an organization, an AI agent, or a system. Edges are relationships. When you click a node, you see that entity's Profile360. The profile has tabs. Every data point on every tab traces back to a graph relationship.

The graph is the primary navigation surface. It opens on load. Profile tabs are drilldowns. The system compounds in value over time: more events → richer relationships → stronger attribution → better intelligence.

The defining moment the product must create is when an operator realizes:
- A high-value customer is connected to a fraud cluster through 2 hops they couldn't see before
- The same person appearing in three disconnected systems is now a single resolved entity with a complete behavioral history
- An abandoned journey that looked like churn is actually recoverable — the entity is still active on another platform
- Cross-platform behavior finally becomes explainable: this customer converted through TikTok → Reddit → email → purchase

The UX must surface these moments. **The graph makes the invisible visible.**

---

## Navigation Model

The intelligence graph is the primary surface. Entity profiles are drilldowns from selected graph nodes.

```
/graph                           → graph canvas, full tenant entity graph
/graph?focus={entity_id}         → graph canvas centered on entity + 1-hop neighbors
/profile/{entity_id}             → full-screen Profile360 for selected entity
/profile/{entity_id}/{tab}       → Profile360 at a specific tab
/geo                             → geographic intelligence view (global)
/geo/{level}/{geo_id}            → geographic drill-down at country/state/metro/city
/deployments                     → external agent deployments (flag-gated, observation-only)
/payment-rails                   → payment rail observability (flag-gated, observation-only)
/ai-efficiency                   → AI efficiency dashboard (flag-gated; proposals only)
```

Campaign360 gains a **Targeting Intelligence** tab and Cluster360 a
**Targeting Impact** tab (flag-gated; observation-only — "Aether does not
execute this campaign"); the suggestion feed renders targeting cards with an
implementation-package export action.

Card-linked (crypto-card) observability nests inside existing surfaces
rather than adding a route: `/payment-rails` renders a **Card-linked
Activity** section (`pages/payment-rails/card-linked-section.tsx` —
program/basis/source/network filters, basis badges that keep top-up and
spend visually distinct, a "never processes card payments" boundary
notice) and Campaign360 gains a **Card-linked Outcomes** tab
(`pages/campaigns/card-linked-outcomes-tab.tsx` — top-up users/volume
separated from spend users/volume, an attribution-basis badge
`direct`/`temporal`/`probabilistic`/`benchmark_only`/`insufficient_evidence`,
and a "correlation-based labels are never causal claims" caption). Both
render a not-enabled EmptyState when the backend flags are off.

Kyber additionally exposes `/agent-telemetry` (external agent telemetry fleet
diagnostics; gated by the `enableExternalAgentTelemetry` feature flag),
`/payment-rails` (payment rail fleet health; gated by `enablePaymentRails`),
and `/ai-efficiency` (AI efficiency fleet health; gated by `enableAiEfficiency`), and `/targeting` (targeting fleet health, leakage queue, recompute controls; gated by `enableTargetingIntelligence`).

Kyber's `/payment-rails` page also hosts a **Card-linked Payment Rails**
diagnostics section (`pages/payment-rails/card-linked-diagnostics-section.tsx`;
gated by `enableCardLinkedPaymentRails`): PaymentScan catalog freshness,
coverage by source/basis, basis-support-by-source, reconciliation state and
conflicts, privacy gates (region/consent suppressions, blocked-PII attempts),
basis-mislabeling warnings, and the card-linked release-gate check list.

- **Desktop (≥1280px):** Graph canvas + side panel (40% width) visible simultaneously
- **Tablet (768–1279px):** Panel overlays graph as a drawer
- **Mobile (<768px):** Entity list replaces graph canvas; profile is full-screen

---

## Four Entity Classes

All four are first-class. No entity class is privileged over another in the UI.

| Entity Class | Represents | Node Shape | Node Color | Size Encodes |
|---|---|---|---|---|
| **Human / Individual** | Any person — customer, employee, creator, trader | Circle | Operational tier (high-value = amber/gold, standard = blue, flagged = red) | Lifetime operational value (LTV) |
| **Organization** | E-commerce company, SaaS business, DAO, brand, marketplace, media entity, NGO, government body | Rectangle | Industry/domain sector palette | Revenue or transaction volume range |
| **AI Agent** | Any autonomous agent operating within a governed system | Diamond | Operator entity's tier color | Execution count or spending |
| **System / Device** | Infrastructure nodes — devices, applications, services, infrastructure | Hexagon (small) | Neutral gray | Event throughput |

### Organization Sub-Types (rectangle variants)

| Sub-Type | Indicator | Example Entities |
|---|---|---|
| E-Commerce Company | Cart icon | Shopify store, D2C brand, Amazon seller |
| SaaS Company | Gear icon | Software product, subscription service |
| Marketplace | Grid icon | Amazon, eBay, Airbnb, Etsy |
| Media Entity / Creator | Signal icon | YouTube channel, TikTok account, Substack |
| Governance Org | Shield icon | DAO, NGO, cooperative, government agency |
| Exchange | Chart icon | DEX, CEX, stock exchange, forex platform |
| Yield Platform | Stack icon | Staking protocol, savings account, robo-advisor |

Node size scales continuously within each class based on the relevant operational metric. Size encoding must be legible at the graph scale — use minimum and maximum node sizes rather than raw linear mapping.

---

## Graph View Modes

Four progressive views selectable from a persistent toolbar chip group.

| Mode | What It Shows | When to Use |
|---|---|---|
| **Relationship Map** | 1–2 hop network of all connected entities and relationship types | Default — shows who is connected to whom |
| **Attribution Web** | Full acquisition path: campaigns → channels → touchpoints → this entity | Diagnosing how an entity was acquired |
| **Journey Flow** | Time-animated overlay: which edges were active during each conversion stage | Diagnosing funnel drop-off or churn |
| **Geographic Intelligence** | Entities and relationships mapped across a geographic hierarchy (global → city) | Understanding geographic distribution and segment performance |

Geographic Intelligence is a **first-class operational surface**, not a filter on the existing graph. It has its own URL, its own view state, and its own panel content.

---

## Edge Encoding

Every edge in the graph encodes relationship metadata visually.

| Property | Encodes | Values |
|---|---|---|
| **Width** | Relationship volume or interaction count | Thin = rare; thick = high-frequency |
| **Color** | Relationship category | Financial = green; Social = blue; Attribution = red; Delegation = orange; Governance = purple; Operational = neutral gray |
| **Opacity** | Confidence score | 0.3 = inferred; 0.6 = probable; 1.0 = deterministic |
| **Arrow direction** | Directional flows | Transfer, delegation, referral, attribution |

Clicking an edge opens a **Relationship Detail Overlay**: relationship type label, confidence score, first seen date, last seen date, and total interaction count.

---

## Geographic Intelligence View

Geographic Intelligence answers: *where are our entities, what patterns emerge by geography, and how do relationships and operational outcomes differ across regions?*

### Drill-Down Hierarchy

```
Global  →  Country  →  State/Region  →  Metro/District  →  City  →  Town
```

### At Each Level, Show

- Entity count and tier distribution (heatmap choropleth)
- Demographic signals aggregated across entities (income distribution, age range, platform mix) — aggregated only, never individual PII
- Relationship density (avg edges per entity, cross-geography edge %)
- Attribution performance: ROAS, conversion rate, CPA for active campaigns
- Anomaly flags: unusual churn concentration, fraud cluster density, location anomaly spikes
- Segment comparison: how this geography compares to global tenant average on key metrics

### Key Interactions

| Interaction | Result |
|---|---|
| Click into a region | Zooms to next hierarchy level; panel updates |
| Select entities in region | Opens filtered graph showing those entities + relationships |
| Create segment from region | Saves geographic segment for campaign or export (role-gated) |
| Compare geographies | Side-by-side panel for up to 3 geographic segments on any metric |
| Toggle overlay metric | Switch choropleth between entity density, relationship density, attribution performance, anomaly distribution |
| Time window selector | Available at every level: 30d / 60d / 90d / Lifetime |

**Mobile:** Geographic Intelligence renders as a drill-down list on mobile (Country → State → City). The choropleth map requires tablet or desktop.

---

## Profile360 Tab Specifications

Tabs are entity-type-aware. The tab set is dynamically determined by the entity's `kind` field from the backend. Every tab has a 30d / 60d / 90d / Lifetime time window selector and a freshness indicator.

### Human / Individual Profile360

| Tab | Key Intelligence | Key Data Sources |
|---|---|---|
| **Identity** | Verified identifiers (email, phone, wallet), device cluster, session continuity, KYC level, consent state | IdentityCluster, KYC, consent_enforcement |
| **Financial** | Bank accounts (via Plaid), brokerage positions, credit signal, income range, P2P payment activity; onchain portfolio as sub-section only when wallets are linked | Plaid, brokerages, credit bureaus, PayPal/Venmo/CashApp, Moralis (conditional) |
| **Social** | All platform handles, follower counts, engagement rate, influence tier: Twitter, Instagram, TikTok, Reddit, YouTube, LinkedIn, Discord, GitHub, Farcaster, Lens, Spotify, Telegram | Social providers (all 12 platforms) |
| **Relationships** | Organizations this entity is a customer/subscriber/employee/member of; co-investor relationships; referral relationships | CustomerRelationship edges, graph traversal |
| **Geo & Temporal** | Location history by city (primary/secondary/rare), 24×7 activity heatmap, active streaks, connection type, anomaly flags | GeoIP, ASN enrichment, gold_location_history, gold_temporal_heatmap |
| **Journey** | Campaign attribution path, funnel position, ROAS per campaign, time-to-convert by stage, retarget score, pending recommendation cards | gold_attribution, gold_journey_economics |
| **Intelligence** | Operational risk score, trust score, behavioral signals with evidence, anomaly flags, ML model outputs | signal_translator, ML models, IntelligenceProfile |

### Organization Profile360 (e-commerce, SaaS, marketplace, standard business)

| Tab | Key Intelligence |
|---|---|
| **Overview** | Entity name, subtype classification (ecommerce / saas / marketplace / dao / etc.), sector, jurisdiction, employee range, revenue range |
| **Operations** | Dynamically rendered by subtype: e-commerce entities show GMV, AOV, conversion rate, cart abandonment, repeat purchase rate; SaaS entities show MRR, ARR, churn rate, NRR, NPS; both sections appear if entity operates across both models |
| **Customer Intelligence** | Customer count range, segment breakdown, avg LTV, 90-day retention rate, top customer entity graph refs (masked by role) |
| **Social Presence** | All company social accounts across every platform, follower reach, content engagement metrics |
| **Relationships** | Investors, partners, key customers, owned/authorized agents, employee and contractor relationships |
| **Intelligence** | Operational risk score, anomaly flags, fraud relationship signals, behavioral patterns |

### Onchain Entity Profile360 (DAO, DEX, protocol, staking platform)

Shown only when entity `kind` is `governance_org`, `exchange`, `yield_platform`, `dao`, `dex`, or `staking_platform` with verified onchain activity.

| Tab | Key Intelligence |
|---|---|
| **Protocol Overview** | TVL history across 30/60/90/lifetime windows, transaction volume, fee revenue |
| **Governance** | Proposals created/voted on, participation rate, major token holder relationships |
| **Security** | Audit records, exploit history (if any), contract upgrade proxy pattern |
| **Integrations** | Composing protocols, bridge routes, liquidity relationships |

### AI Agent Profile360

| Tab | Key Intelligence |
|---|---|
| **Operator** | Owner entity, deploying entity, delegation scope, authorization chain (visual chain diagram) |
| **Execution** | Run count, success rate, spending to date, error rate, last active timestamp |
| **Policy** | Authorized capabilities, spending limits per period, policy log |
| **Economic** | Revenue and costs attributed to agent actions; PAYS/CONSUMES graph edges |

---

## Component Architecture

```
<GraphCanvas>                        — primary surface (force-directed graph)
  <NodeRenderer entity={node}>       — shape/color/size by entity class and kind
  <EdgeRenderer edges={edges}>       — width=volume, color=relation type, opacity=confidence
  <MiniMap>                          — overview thumbnail when graph is large (>50 nodes)
  <ViewModeSelector>                 — Relationship Map | Attribution Web | Journey Flow | Geographic
  <GraphSearchBar>                   — search by entity name, ID, or identifier
  <GraphToolbar>                     — path mode toggle, traversal mode selector (Shortest/Strongest/K-Shortest),
                                       target-node selector, K-paths input (when k_shortest mode is active)

<ProfilePanel entity={selected}>     — right-side panel, 40% viewport width on desktop
  <EntityHeader>                     — name, kind badge, operational tier indicator, freshness dot
  <TabNav tabs={availableTabs}>      — tab set determined by entity kind
  <TabContent tab={active}>
    <DataSection title value freshness source />
    <TimeWindowSelector />           — 30d | 60d | 90d | Lifetime; switches all panels simultaneously
    <GraphEdgeList>                  — related entities with quick-navigate
    <EvidenceDrawer signal={}>       — expands signal detail with evidence_refs
  </TabContent>

<PathInspector path={RelationshipPath}>  — shown in right panel instead of ProfilePanel when a path is active
  <Tab: Overview>                    — classification badge (observed/causal/attributed/inferred/correlated/mixed),
                                       layer_sequence badges, path_confidence + evidence_coverage score bars,
                                       hop_count / source_id / target_id / computed_at metadata grid
  <Tab: Hops>                        — vertical breadcrumb: node kind badge → label → edge type/confidence/layer → next node
  <Tab: Evidence>                    — why_connected narrative, supporting_evidence list, contradictory_evidence list;
                                       "Load explanation" button triggers POST /v1/graph/paths/explain
  <Tab: Score>                       — PathScoreBreakdown: geometric_mean, min_edge, hop_penalty, causality_penalty, overall
  <SaveToInvestigation button>       — calls POST /v1/investigations/{case_id}/snapshot with path_id + snapshot_id

<GeographicView>                     — full-screen geographic surface
  <ChoroplethMap level={geo_level}>
  <GeoPanel geo={selected}>
    <MetricToggle>                   — entity density | relationship density | attribution | anomaly
    <SegmentBuilder>                 — create reusable geographic segment
    <ComparePanel geos={[...]} />    — side-by-side comparison, up to 3 geographies

<RoleGate role={analystRole}>        — masks PII fields based on analyst_role JWT claim
<FreshnessIndicator computed_at>     — live (green) / recent (amber) / stale (red + Refresh)
<RecommendationCard rec={}>          — Approve / Reject / Edit; never auto-executes
```

---

## Data Freshness States

Every panel header must show the `computed_at` timestamp and the freshness indicator. Stale data is always shown with a flag — never silently displayed as current.

| State | Threshold | Visual |
|---|---|---|
| **Live** | < 5 minutes since `computed_at` | Green dot in panel header |
| **Recent** | 5–15 minutes | Amber dot in panel header |
| **Stale** | > 15 minutes | Red dot + "Refresh" action button |

Clicking "Refresh" triggers a re-fetch of the specific panel's data only — it does not reload the full graph or other panels.

---

## Role-Based PII Behavior

The active role is displayed persistently in the application header. Masked fields render as masked strings (not hidden), so the analyst knows data exists but is access-controlled.

| Field | analyst_readonly | analyst_standard | analyst_compliance |
|---|---|---|---|
| Email | j\*\*\*@gmail.com | j\*\*\*@gmail.com | Full email |
| Phone | +1 \*\*\*-\*\*78 | +1 \*\*\*-\*\*78 | Full phone |
| Name | James T. | James T. | Full name |
| Date of birth | Age range (35–44) | Age range (35–44) | Exact date |
| SSN / Tax ID | Never displayed | Never displayed | Never displayed |
| Financial account | Last 4 digits only | Last 4 digits only | Last 4 digits only |
| Wallet address | 0x1234...abcd | 0x1234...abcd | Full address |
| Export profile | Disabled | Enabled | Enabled |
| Approve retarget | Disabled | Enabled | Enabled |
| Unmask PII | Disabled | Disabled | Enabled |

All unmask, export, approve, and flag actions are written to the consent audit log.

---

## Key Interaction Patterns

| Interaction | Behavior |
|---|---|
| Graph node click | Loads Profile360 panel on the right (40% viewport width on desktop) |
| Panel expand button | Transitions to full-screen Profile360 |
| Edge click | Relationship detail overlay: type label, confidence score, first/last seen date |
| Node right-click / long-press | Context menu: View Profile, View 2-hop neighbors, Add to watchlist, Flag for review |
| Time window chip | Switches ALL panels on the active tab simultaneously; never reloads the graph |
| Signal badge click | Expands evidence drawer showing source event_ids and last_detected timestamp |
| Recommendation card | Displays recommended action, reasoning array, confidence score, and Approve / Reject / Edit controls; Approve triggers human-authorized execution only |
| Stale indicator | Clicking "Refresh" triggers a re-fetch of the specific panel's data only |

**Intelligence never auto-executes.** Recommendations surface for analyst review. No retargeting, campaign execution, or data export happens without explicit human approval. The UI enforces this as a hard constraint, not a soft preference.

---

## Responsive Behavior

| Breakpoint | Layout |
|---|---|
| Desktop ≥1280px | Graph canvas full left, Profile360 panel right (40%); both visible simultaneously |
| Tablet 768–1279px | Graph canvas full width; Profile360 slides over as overlay drawer |
| Mobile <768px | Graph replaced by entity list view (sortable by tier, relationship count, freshness); Profile360 is full-screen; time window uses compact chip selector |

Graph rendering is tablet and desktop only. Mobile degrades gracefully to a relationship list showing the selected entity's 1-hop connections.

---

## API → UI Binding

Every Profile360 panel maps to a backend sub-resource endpoint. The frontend binds panel components to these routes:

| Panel | Endpoint | Window-aware |
|---|---|---|
| Sessions | `GET /v1/profile/{id}/sessions` | No |
| Devices | `GET /v1/profile/{id}/devices` | No |
| Financial (Web2) | `GET /v1/profile/{id}/web2` | No |
| Social intelligence | `GET /v1/profile/{id}/social-intelligence` | Yes |
| Tier | `GET /v1/profile/{id}/tier` | Yes |
| Asset composition | `GET /v1/profile/{id}/asset-composition` | Yes |
| PNL | `GET /v1/profile/{id}/pnl` | Yes |
| Trading profile | `GET /v1/profile/{id}/trading-profile` | Yes |
| Location history | `GET /v1/profile/{id}/location-history` | Yes |
| Temporal heatmap | `GET /v1/profile/{id}/temporal-heatmap` | Yes |
| Journey economics | `GET /v1/profile/{id}/journey-economics` | Yes |
| Funnel | `GET /v1/profile/{id}/funnel` | Yes |
| Time-to-convert | `GET /v1/profile/{id}/time-to-convert` | Yes |
| Retarget recommendations | `GET /v1/profile/{id}/retarget-recommendations` | No |
| Relationships | `GET /v1/profile/{id}/relationships` | No |
| Graph | `GET /v1/entities/{id}/graph` | No |
| Protocol metrics | `GET /v1/profile/{id}/protocol-metrics` | Yes |
| Governance activity | `GET /v1/profile/{id}/governance-activity` | Yes |
| Intelligence | `GET /v1/profile/{id}/intelligence` | No |
| Geographic summary | `GET /v1/geo/summary` | Yes |
| Path query | `POST /v1/graph/paths` | No |
| Node expansion | `POST /v1/graph/paths/expand` | No |
| Path explanation | `POST /v1/graph/paths/explain` | No |
| Create snapshot | `POST /v1/graph/snapshots` | No |
| Get snapshot | `GET /v1/graph/snapshots/{id}` | No |
| Compare snapshots | `POST /v1/graph/snapshots/{id}/compare` | No |
| Async deep traversal | `POST /v1/graph/paths/jobs` | No |
| Deep traversal job status | `GET /v1/graph/paths/jobs/{id}` | No |
| Link snapshot to investigation | `POST /v1/investigations/{case_id}/snapshot` | No |

All window-aware endpoints accept `?window=30d|60d|90d|lifetime`. The time window selector updates all window-aware panels on the active tab simultaneously.

### API error contract and correlation

Both REST clients (`frontend/aether/src/lib/api/rest/client.ts`,
`frontend/kyber/src/lib/api/rest/client.ts`) parse backend failures through
`parseProblemDetails` from `@aether/ui` (`frontend/shared/src/problem-details.ts`),
which normalizes the canonical RFC-7807-compatible body and both legacy error
shapes into one structure. The canonical `ProblemDetails` **type** stays in
`@aether/shared` (`packages/shared/problem-details.ts`) and is imported type-only;
the runtime parser lives in `@aether/ui` because that ESM library is bundled from
source by the app builds, whereas `@aether/shared` compiles to CommonJS and only
its types are resolvable by the app rollup builds. `RestClientError` therefore
carries a stable machine `code`, a `retryable` flag, the full parsed `problem`,
and the server-echoed correlation ID. Clients send `X-Correlation-ID` on every request; the backend
honors it and echoes both `X-Correlation-ID` and `X-Request-ID` on responses,
so one ID traces a request across frontend logs, backend logs, jobs, and audit
records.

---

## Social Intelligence Panel Detail

The Social tab shows all 12 platforms in a unified grid layout. Platforms with no linked account are shown as grayed-out "Connect" placeholders — never hidden — so operators understand the complete coverage picture.

| Platform | Role Support | Key Metrics Shown |
|---|---|---|
| Twitter / X | Creator + Consumer | Followers, verified, engagement rate |
| YouTube | Creator + Consumer | Subscribers, total views, content count |
| Instagram | Creator + Consumer | Followers, verified, post count |
| TikTok | Creator + Consumer | Followers, total views, engagement rate |
| Reddit | Consumer (primarily) | Karma, subreddits moderated |
| LinkedIn | Professional | Connections, verified employment |
| Spotify | Creator + Consumer | Monthly listeners (creator), listening signals (consumer) |
| Telegram | Creator (channels) | Channel subscribers |
| Discord | Consumer (guilds) | Guild memberships |
| GitHub | Creator | Followers, public repos, stars |
| Farcaster | Creator + Consumer | Followers, FID |
| Lens | Creator + Consumer | Followers, profile ID |

Influence level (High / Medium / Low) is computed cross-platform: High = `total_followers_deduped > P80 AND engagement_rate > P75`. It is displayed prominently at the top of the Social tab with the deduped total follower count.

---

## Financial Panel Detail (Human Entities)

The Financial tab uses a two-tier layout:

**Tier 1 — Holdings (requires `financial_holdings` consent):**
- Bank accounts (via Plaid): institution name, account type, masked balance, last sync date
- Brokerage positions: broker name, asset class breakdown, total value (masked by role)
- Credit signal: score band (not exact score), derogatory count, last bureau refresh date
- Income range estimate: "$75k–$100k" (never exact)
- P2P payment summary: platforms connected, estimated monthly volume, primary use (personal/business/mixed)

**Tier 2 — Behavioral Signals (requires `financial_signals` consent):**
- Spend tier (Ultra High / High / Mid / Low)
- Savings behavior (Active saver / Balanced / Spending-first)
- Investment risk profile (Aggressive / Moderate / Conservative)
- Top spend categories (e.g., "Software & SaaS", "Travel", "Food & Beverage")
- Has recurring investment (boolean indicator)

If entity has linked wallets, an onchain portfolio sub-section renders below the Web2 financial data with asset composition and PNL data.

---

## Behavioral Signals Panel Detail

Signals are shown as cards in the Intelligence tab. Each card has:
- Signal name (e.g., "At-Risk of Churn")
- Sentiment badge: Positive (green) / Caution (amber) / Negative (red) / Informational (blue)
- Short description (one sentence)
- Confidence percentage
- Last detected timestamp
- Click → evidence drawer (expands to show source `evidence_refs` and triggering event IDs)

Signals are grouped by category: Universal → Social + Content → Financial + Operational → Onchain (conditional — only shown for entities with linked wallet activity).

---

## Recommendation Cards

Recommendation cards appear in the Journey tab when `status = 'pending_review'`. Each card shows:
- Recommended platform and action (e.g., "Retarget on Meta Ads")
- Recommended creative theme derived from behavioral signals
- Estimated bid (CPA target)
- Confidence score (0–1)
- Reasoning array: 2–4 bullet points explaining why this recommendation was generated
- Three action buttons: **Approve**, **Reject**, **Edit**

Approve triggers human-authorized execution via the backend executor. The card status updates to `executing` → `executed` or `failed`. This flow is irreversible — the UI must confirm before calling approve.

---

## Design Principles

1. **Graph-first navigation** — the canvas opens first; profile tabs are the drilldown panel, never the entry point
2. **Entity-agnostic rendering** — the graph and profile system work identically for a Shopify merchant, a DAO, a TikTok creator, and an enterprise SaaS company
3. **Four time windows everywhere** — every time-based chart has a `30d / 60d / 90d / Lifetime` selector; never missing
4. **Data freshness is always visible** — every panel shows a live/recent/stale indicator with `computed_at`; stale data triggers a visual flag, not silent display
5. **PII is role-gated by default** — the system masks by default; unmasking requires elevated role; masking state is obvious without being obtrusive
6. **Intelligence never auto-executes** — recommendations surface for analyst review; the UI enforces this as a hard constraint
7. **Every data point is explainable** — every signal, score, and relationship has a source reference (evidence_refs) that can be expanded

**Design voice:** Operators should feel informed, capable, and in control. They should feel operational awareness — relationships and patterns they couldn't see before are now visible. The interface reduces cognitive load. Nothing executes without their approval.

**What to avoid:** Decorative elements, unexplained data, information density without hierarchy, any framing that suggests the system operates on the user's behalf without consent.

---

## Existing Component Inventory (Kyber)

These components exist and should be extended — not replaced.

| Component | Path | Notes |
|---|---|---|
| Graph canvas | `apps/kyber/src/components/graph/graph-canvas.tsx` | Cytoscape-backed; extend node/edge renderers for new entity types |
| Entity 360 page | `apps/kyber/src/pages/entities/entity-360.tsx` | Profile360 aggregation point |
| Entity 360 view | `apps/kyber/src/components/entities/entity-360-view.tsx` | Tab layout; extend tab set with Social, Financial, Geo |
| Entity list table | `apps/kyber/src/components/entities/entity-list-table.tsx` | Extend for new entity kinds; add kind badge column |
| Score card | `apps/kyber/src/components/entities/entity-score-card.tsx` | Trust/risk/anomaly — reuse as-is |
| Timeline components | `apps/kyber/src/components/timelines/` | Reuse for Journey tab events |
| WebSocket hook | `apps/kyber/src/hooks/use-websocket.ts` | Reuse for live freshness updates |
| API endpoints | `apps/kyber/src/lib/api/endpoints.ts` | Extend with all new Profile360 sub-resource routes |

Type contracts for all new sub-resources are in `packages/shared/`. The frontend imports from that package — do not duplicate types in `apps/kyber`.

---

## New Components Required

| Component | Purpose | Priority |
|---|---|---|
| `SocialIntelligencePanel` | 12-platform grid with influence level + deduped total | High |
| `FinancialPanel` | Two-tier layout (holdings + signals) with role gating | High |
| `GeoTemporalPanel` | Location history table + 24×7 heatmap | High |
| `BehavioralSignalCard` | Signal card with sentiment badge + evidence drawer | High |
| `RecommendationCard` | Pending action card with Approve/Reject/Edit | High |
| `GeographicView` | Full-screen choropleth + drill-down hierarchy | Medium |
| `OrganizationOpsPanel` | E-commerce / SaaS operations panel (subtype-routed) | Medium |
| `AgentProfile` | 4-tab agent profile (Operator, Execution, Policy, Economic) | Medium |
| `FreshnessIndicator` | Dot + timestamp + Refresh button | High (shared) |
| `RoleGate` | PII masking wrapper with role-based field rendering | High (shared) |
| `TimeWindowSelector` | 30d / 60d / 90d / Lifetime chip group | High (shared) |
| `EvidenceDrawer` | Expandable signal evidence panel | Medium |
| `DelegationChainDiagram` | Linear chain visualization for agent operator flow | Low |

## Agentic Commerce Components (Kyber, v8.9.0)

Commerce control plane components in `frontend/kyber/src/`:

**Feature modules** (`src/features/`): `settlement`, `policies`, `facilitators`,
`resources` (new, v8.9.0) alongside existing `commerce`, `approvals`, `entitlements`.

**API adapters** (`src/lib/api/`): `commerce.ts` (consolidated), plus modular
`approvals.ts`, `entitlements.ts`, `resources.ts`, `settlement.ts`, `policies.ts`,
`facilitators.ts`.

**Zod schemas** (`src/lib/schemas/`): `commerce.ts` (consolidated), plus modular
domain re-exports.

**Component suites:**
| Directory | Components | Owner pages |
|---|---|---|
| `components/commerce/` | SpendTimeline, RevenueCard, TreasuryPanel, RailBreakdown, FeeEliminationGauge | Mission, Live |
| `components/approvals/` | ApprovalQueue, ApprovalCard, DecisionForm, EvidencePanel, EscalationRouter, GraphImpactPreview | Review |
| `components/entitlements/` | EntitlementList, EntitlementDetail, ReuseHistory, RevokeDialog | Entities |
| `components/economics/` | ClusterEconomicsView, FacilitatorPerformance, SettlementStatusStrip | Live, Diagnostics |

All commerce modules call their API adapters in normal runtime. Reusable
synthetic records, when needed by unit/component tests, live only in test-only
paths and cannot be imported by a production entrypoint.

## Reward Enablement Components (A6, v8.10.0)

Attribution-verified reward eligibility UI. Aether never holds or distributes rewards; these pages surface eligibility decisions and action payloads for tenant systems to execute.

### Aether (tenant) pages — `frontend/aether/src/pages/rewards/`

| Page | Route | Purpose |
|---|---|---|
| `campaign-builder-page.tsx` | `/rewards/campaigns/new` | 5-step wizard: basics → attribution model → rules → rail config → review |
| `decisions-page.tsx` | `/rewards/decisions` | Table of eligible/ineligible/blocked decisions with attribution + fraud summary |
| `approval-queue-page.tsx` | `/rewards/approvals` | Approve/reject pending manual-approval actions with attribution evidence |
| `rail-setup-page.tsx` | `/rewards/rails` | Rail configuration wizard with test-connection; supports recommend_only, manual_approval, manual_export, tenant_webhook, onchain_claim |

**No-custody copy rules enforced in UI**: "Verify eligibility" (not "send reward"), "Generate proof for tenant contract" (not "Aether pays"), "Tenant executes reward" (not "Aether distributes").

### Kyber (operator) pages — `frontend/kyber/src/pages/rewards/`

| Page | Route | Purpose |
|---|---|---|
| `rewards-health-page.tsx` | `/rewards/health` | System-wide stats: active campaigns, eligible decisions (24h/7d), blocked fraud/consent, pending approvals, webhook delivery failures |
| `rewards-drilldown-page.tsx` | `/rewards/drilldown` | Per-tenant drilldown: campaigns, decisions, proofs, payloads, audit log |

**API hooks**: `useRewardsHealthStats()` → `GET /v1/admin/kyber/rewards/health`, tenant-scoped data via `useRewardsCampaigns()` / `useRewardDecisions()`.

---

## Notification Intelligence Components (Kyber, v8.8.0)

Operator-facing and end-user notification components in `apps/kyber/src/features/notifications/`:

| Component / Hook | Purpose |
|---|---|
| `OperatorNotificationPanel` | Operator review queue — SLA countdown, severity badge, expandable detail, action bar |
| `OperatorActionBar` | Approve / Suppress / Escalate / Annotate with inline annotation textarea; RBAC-gated |
| `NotificationLifecycleBadge` | Color-coded lifecycle state: detected→validated→queued→operator_review→approved→propagated→suppressed→expired |
| `AuditTrailTimeline` | Vertical timeline rendered from `audit_trail[]`; shows actor, state, timestamp, annotation |
| `ChannelSettingsPage` | Self-serve channel management — list, toggle active, test, remove |
| `ChannelConnectModal` | Tabbed wizard: Slack OAuth / Discord webhook / Telegram bot / HTTPS webhook |
| `ChannelTypeIcon` | SVG icons for Slack, Discord, Telegram, Webhook channel types |
| `ChannelSeverityFilter` | P0/P1/P2/P3/info multi-select checkbox group |
| `useIntelligenceNotifications` | Polls `/v1/notifications/intelligence?state=operator_review` (10 s); bridges to `NotificationContext` |
| `useNotificationChannels` | CRUD for channel management; includes `getSlackConnectUrl()` for OAuth initiation |

---

## Continuation Plane & Command Receipts (v8.12.0)

Cross-device handoff and governed-action visibility added by the mobile-productization program:

- **Aether** (`frontend/aether/src/features/continuation/`): `continue-on-phone.tsx`
  (create continuation, copy handoff link, resume), `recent-activity.tsx` (recent
  mobile activity), `use-client-sync.ts` (client-sync consumption),
  `use-continuations.ts` — wired to `/v1/continuations` + `/v1/client-sync`.
- **Kyber** (`frontend/kyber/src/features/continuation/`):
  `operator-continuation-panel.tsx` + `continuation-create-button.tsx` against
  `/v1/kyber/continuations`; command receipts
  (`features/kyber-ops/command-receipts.tsx`) read durable
  `verified | executed_unverified | denied | failed | expired` states from the
  kyber command plane.
- **Client-sync consumption** distinguishes fresh/offline/stale; no offline mutation.

---

## Kyber Manifest-Driven Provider UI (shipped, WS3)

A Kyber operator surface for the Universal Provider Runtime, shipped in the
follow-on program (PR-D), gated by `KYBER_PROVIDER_RUNTIME_UI_ENABLED`
(default OFF; the admin provider-connections routes are also served when the
health flag `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED` is on, since the S3
providers/certify/tenants routes are the UI's data). The UI is
**manifest-driven**: forms, fields, and validation render from the installed
plugin's `ProviderManifest` rather than connector-specific code, so a new
provider plugin gains operator UI without a frontend change.

Shipped scope:

- **Provider catalog** — installed plugins + legacy connectors, consumed from
  `GET /v1/admin/kyber/provider-connections/providers` via the
  `{providers, count}` envelope contract
  (`frontend/kyber/src/features/provider-connections/use-provider-manifest.ts`).
  Entry validation is per-entry tolerant: a single malformed plugin manifest
  is skipped and surfaced as a failed-entry status, never taking down the
  whole catalog.
- **Connection lifecycle** — create / configure / credential / test / confirm /
  sync against the runtime tenant surface
  (`/v1/provider-connections/*`), with config fields validated against the
  manifest (`frontend/kyber/src/pages/provider-connections/provider-connections-page.tsx`).
- **Migration views** — projection list/apply against the tenant-scoped
  migration routes (`GET /v1/provider-connections/migrations`,
  `GET`/`POST /v1/provider-connections/{connection_id}/migrations` — the
  apply route takes a `connection_id`, not a `connector_type`), gated by
  `AETHER_PROVIDER_MIGRATIONS_ENABLED` (see `BACKEND-API.md`).
- **Routing + nav** — the lazy route `/provider-connections` mounts
  `ProviderConnectionsPage`
  (`frontend/kyber/src/app/router.tsx`); the sidebar entry is gated by
  `enableProviderRuntime`
  (`frontend/kyber/src/components/layout/sidebar.tsx`). The frontend route is
  not a grant — the backend still gates `/v1/admin/kyber/provider-connections/*`.

The surface is additive and flag-gated; disabling the flags keeps the route
present but inert (the backend gates the admin data routes). Unit coverage
lives in `frontend/kyber/src/test/unit/` (`provider-manifest-hooks.test.ts`,
`provider-manifest-schemas.test.ts`, `capability-state-surface.test.tsx`).

---

## URL Structure

```
/graph                               — graph canvas default
/graph?focus={entity_id}             — graph centered on entity
/graph?focus={id}&depth=2            — 2-hop neighborhood
/profile/{entity_id}                 — profile (entity type inferred from backend)
/profile/{entity_id}/identity        — identity tab
/profile/{entity_id}/financial       — financial tab
/profile/{entity_id}/social          — social tab
/profile/{entity_id}/relationships   — relationships tab
/profile/{entity_id}/geo             — geo & temporal tab
/profile/{entity_id}/journey         — journey tab
/profile/{entity_id}/intelligence    — intelligence tab
/profile/{entity_id}/operations      — organization operations tab
/geo                                 — geographic intelligence (global)
/geo/country/{country_code}          — country level
/geo/state/{state_id}               — state/region level
/geo/metro/{metro_id}               — metro/district level
/geo/city/{city_id}                 — city level

/fraud-networks                      — fraud network list
/fraud-networks/:networkId           — network detail (graph, members, evidence, case)
/fraud-networks/flow-trace           — flow-of-funds trace builder
/fraud-networks/flow-trace/:traceId  — trace detail with paths
```

---

## Kyber Fraud Workspace

The fraud workspace lives under `/fraud-networks` in Kyber and consists of:

| Page | Component | Description |
|------|-----------|-------------|
| `FraudNetworksPage` | `pages/fraud/fraud-networks-page.tsx` | List of fraud networks with status/risk filter and build modal |
| `FraudNetworkDetailPage` | `pages/fraud/fraud-network-detail-page.tsx` | Network detail: graph canvas, members table, evidence tray, case panel |
| `FlowTracePage` | `pages/fraud/flow-trace-page.tsx` | Trace builder + recent traces list + trace result with paths |
| `FraudDecisionsPage` | `pages/fraud/fraud-decisions-page.tsx` | Durable fraud decision review queue: filter by risk tier / decision / review state; review (confirmed_fraud / dispute / review_clear) and suppress actions with reason capture; wired to `GET /v1/fraud/decisions`, `POST /v1/fraud/decisions/{id}/review`, `POST /v1/fraud/decisions/{id}/suppress` |

Supporting components:

| Component | File | Purpose |
|-----------|------|---------|
| `EntityNodeDrawer` | `components/fraud/entity-node-drawer.tsx` | Slide-out showing entity identity, risk score, and action buttons |
| `EdgeDrawer` | `components/fraud/edge-drawer.tsx` | Slide-out showing transfer details and evidence for a graph edge |
| `FraudEvidenceTray` | `components/fraud/fraud-evidence-tray.tsx` | Expandable evidence list with type badges |
| `CaseAttachmentPanel` | `components/fraud/case-attachment-panel.tsx` | Create investigation case or attach network to existing case |
| `FlowTracePaths` | `components/fraud/flow-trace-paths.tsx` | Path list with pattern tags, hop count, and risk score bar |

All components use `useQuery` / `useMutation` from `@aether/ui`, the `api.fraudNetworks` and `api.flowTrace` domain objects from `endpoints.ts`, and the hooks in `features/fraud/use-fraud.ts`.

---

## Delivery & Connector Pages (v9.1.0)

### Aether (tenant) — Delivery History

**File:** `frontend/aether/src/pages/connectors/delivery-history.tsx`

`DeliveryHistoryPage` provides tenants with a paginated view of their outbound `DeliveryIntent` records and their associated per-provider jobs, attempt details, and provider receipts.

| Feature | Detail |
|---------|--------|
| Intents list | Paginated (10 per page), shows source type, channels, created timestamp, and state badge |
| State badges | PENDING / SCHEDULED / DELIVERED / FAILED mapped via `STATE_VARIANT` to success/warning/danger/default |
| Expandable jobs | Click an intent card to load `DeliveryJob` rows: provider, attempt count, external ID, created timestamp |
| Attempt detail | Expand a job row to see individual `DeliveryAttempt` records: outcome, HTTP status, latency, error message, started-at |
| Provider receipt | External ID rendered as a clickable link when `external_url` is present |
| Dead-letter message | When job state is `dead_letter`, shows "Contact support to replay" — tenants cannot self-replay |
| Empty states | Loading spinner, empty state (no records), and error state are all handled |
| API | `GET /v1/delivery/intents` → `GET /v1/delivery/jobs` → `GET /v1/delivery/jobs/{id}/attempts` + `/receipt` |

### Aether (tenant) — Connectors Page Health Labels

**File:** `frontend/aether/src/pages/connectors/connectors-page.tsx`

The `healthLabel(connector)` function maps `sync_status` + `secret_configured` to a human-readable label. **Critical invariant: never returns "Connected" when `secret_configured` is absent or false.**

| `sync_status` | `secret_configured` | Label returned |
|---------------|---------------------|----------------|
| `healthy` | `true` | Connected |
| `healthy` | falsy | Credentials Missing |
| `error` | any | Error |
| `rate_limited` | any | Rate Limited |
| `credentials_invalid` | any | Credentials Invalid |
| `credentials_missing` | any | Credentials Missing |
| `revoked` | any | Revoked |
| `permission_missing` | any | Permission Missing |
| `never_synced` | any | Never Synced |
| (other) | any | Unconfigured |

The `connectorCapabilityState` helper maps every state above onto the shared `CapabilityState` matrix, rendered via `CapabilityStateBadge` with honest tones.

### Kyber (operator) — Delivery Operations

**File:** `frontend/kyber/src/pages/delivery/delivery-ops.tsx`

`DeliveryOpsPage` is an operator cross-tenant delivery management surface with two tabs:

| Tab | Content |
|-----|---------|
| All Jobs | Filterable list (by tenant ID, provider/adapter type, job state); columns: job ID, tenant, provider, state badge, attempt count, created, external ID with link |
| Dead Letter | Jobs in `dead_letter` state with last error summary; "Replay" button opens a confirmation dialog before calling `POST /v1/delivery/jobs/{id}/replay` |

Pagination: 20 jobs per page with Previous/Next controls. Replay requires explicit operator confirmation via modal dialog — no action taken without approval.

The `api.delivery` namespace in `frontend/aether/src/lib/api/endpoints.ts` and `frontend/kyber/src/lib/api/endpoints.ts` exposes:
- `listIntents(params)` → `GET /v1/delivery/intents`
- `listJobs(params)` → `GET /v1/delivery/jobs`
- `getReceipt(jobId)` → `GET /v1/delivery/jobs/{id}/receipt`
- `listAttempts(jobId)` → `GET /v1/delivery/jobs/{id}/attempts`
- `listLinks(params)` → `GET /v1/delivery/links`

## Economic & Interoperability Intelligence Pages (v8.12.0)

Observation-only surfaces for the stablecoin, derivatives, and
interoperability domains. Feature-flagged-off backends return 404, which
both apps render as an honest "not enabled" empty state rather than an
error. Every page states its no-execution boundary in the header copy.

### Aether (tenant) — `frontend/aether/src/pages/{stablecoins,derivatives,interop}/`

| Route | Page |
|-------|------|
| `/stablecoins` | Assets, peg valuations with depeg badges, flow aggregates |
| `/stablecoins/:assetId` | Deployments + recent observations with finality status |
| `/derivatives` | Linked accounts, positions, P&L snapshots, reconciliation variances |
| `/derivatives/accounts/:accountId` | Orders, fills, positions for one read-only account |
| `/interoperability` | Cross-chain messages, paths, providers with honest `ImplementationStatus` |
| `/interoperability/messages/:messageId` | Lifecycle timeline, delivery attempts, asset legs |

Hooks live in `features/{stablecoins,derivatives,interop}/`; endpoint
groups in `lib/api/endpoints.ts` parse the raw `{items, count}` responses
(these backend routes do not use the APIResponse envelope). Shared
helpers (`components/domain-intelligence.tsx`) provide the
`NotEnabledOrError` state, stat tiles, and status badge variants.

### Kyber (operator) — `frontend/kyber/src/pages/{stablecoins,derivatives,interop}/`

| Route | Page |
|-------|------|
| `/stablecoins/ops` | Registry status + seed action, finality checkpoints, reconciliation review |
| `/derivatives/ops` | Adapter fleet (honest `ImplementationStatus`), checkpoints, stream gaps, variances, conformance trigger |
| `/interoperability/ops` | Provider health, correlation health, security-policy drift, governed-scan trigger |

Gated client-side by the `kyberStablecoinOps` / `kyberDerivativesOps` /
`kyberInteropOps` feature flags (default OFF) via a shared `FlagGate`;
Zod schemas in `lib/schemas/economic-ops.ts` parse the raw admin payloads.
