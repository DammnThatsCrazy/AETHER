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
last_synced_commit: faed118
---
# Aether Frontend Architecture & Designer Handoff

---

## ⚠️ Two Frontends — Critical Distinction

There are two separate frontend applications. **Do not mix them up.**

| App | Directory | Audience | Purpose |
|-----|-----------|----------|---------|
| **Aether** | `frontend/aether/` | External paying tenants / customers / clients | Self-service: sign up, install SDK, manage API keys, view their own intelligence graph, entity profiles, campaigns, geographic intelligence |
| **Kyber** | `frontend/kyber/` | Internal Aether team / operators only | Operator mission control: monitor all tenants, diagnose system health, approve agent actions, review entity clusters, run lab fixtures |

### What belongs where

**Aether (customer-facing) contains:**
- Auth flows (signup, login, SSO, billing)
- The intelligence **graph canvas** showing the tenant's users, organizations, and AI agents
- **Entity Profile360** panels — what tenants drill into when they click a graph node
- **Geographic Intelligence** view — their users by location
- **Social Intelligence** panels — their users' social platform presence
- **Recommendation cards** — pending retargeting / campaign actions for the tenant to approve
- Campaign management, attribution dashboards
- API key management, plan management, usage metering

**Kyber (internal operator console) contains:**
- Mission dashboard — real-time system health across all tenants
- Noesis — operator graph view of cross-tenant entity relationships
- Live event stream — raw event firehose for debugging
- Entity admin — manage any entity across any tenant
- Command center — controller management
- Diagnostics — circuit breakers, error tracking, dependency health
- Review / approval workflows — human-in-the-loop agent approvals
- Lab — test fixtures and replay

**Shared (`frontend/shared/` — npm package `@aether/ui`):**
- Design system components used by both Aether and Kyber
- `TimeWindowSelector`, `FreshnessIndicator`, `EvidenceDrawer`, `UsageBar`, `Toast`, etc.

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
```

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

<ProfilePanel entity={selected}>     — right-side panel, 40% viewport width on desktop
  <EntityHeader>                     — name, kind badge, operational tier indicator, freshness dot
  <TabNav tabs={availableTabs}>      — tab set determined by entity kind
  <TabContent tab={active}>
    <DataSection title value freshness source />
    <TimeWindowSelector />           — 30d | 60d | 90d | Lifetime; switches all panels simultaneously
    <GraphEdgeList>                  — related entities with quick-navigate
    <EvidenceDrawer signal={}>       — expands signal detail with evidence_refs
  </TabContent>

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

All window-aware endpoints accept `?window=30d|60d|90d|lifetime`. The time window selector updates all window-aware panels on the active tab simultaneously.

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
```
