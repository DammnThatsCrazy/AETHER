# Aether Backend API v8.7.1 — Endpoint Specification

## Overview

The thin-client architecture requires the backend to handle all processing that was previously done client-side. This document specifies all backend endpoints.

## Authentication

All endpoints require an API key passed as:
- Header: `Authorization: Bearer <api-key>`
- Or query parameter: `?apiKey=<api-key>`

## Event Ingestion

### POST /v1/events

Receives batched raw events from the Web SDK.

**Request:**
```json
{
  "batch": [
    {
      "id": "uuid-v4",
      "type": "track|screen|identify|conversion|wallet|transaction|consent",
      "event": "button_clicked",
      "timestamp": "2026-03-05T12:00:00.000Z",
      "sessionId": "uuid-v4",
      "anonymousId": "uuid-v4",
      "userId": "user-123",
      "properties": { "buttonId": "cta-hero" },
      "context": {
        "library": { "name": "@aether/sdk", "version": "8.7.0" },
        "fingerprint": { "id": "sha256-hash" },
        "locale": "en-US",
        "timezone": "America/New_York"
      }
    }
  ],
  "sentAt": "2026-03-05T12:00:05.000Z"
}
```

**Response:** `200 OK`
```json
{ "success": true, "accepted": 10 }
```

### POST /v1/batch

Receives batched raw events from iOS and Android SDKs. Same schema as `/v1/events`.

**Backend Processing (applies to both endpoints):**
- IP enrichment via MaxMind GeoLite2 (country, region, city, ASN, VPN/proxy detection)
- Identity resolution (deterministic + probabilistic cross-device matching)
- Device info derived from User-Agent headers
- Traffic source classification from UTM/referrer data
- Funnel step matching against server definitions
- ML scoring (intent prediction, bot detection)
- Heatmap grid building from coordinate events
- Rage click and dead click detection

---

### GET /v1/config

Returns SDK initialization configuration. Called once on `init()`.

**Query Parameters:**
- `apiKey` (required)
- `platform` (optional): `web|ios|android|react-native`

**Response:**
```json
{
  "featureFlags": {
    "dark-mode": true,
    "upload-limit": 50,
    "new-checkout": { "enabled": true, "variant": "treatment" }
  },
  "funnels": [
    {
      "id": "onboarding",
      "steps": ["signup_started", "email_verified", "profile_completed"]
    }
  ],
  "surveys": [
    {
      "id": "nps-q1",
      "type": "nps",
      "trigger": { "event": "purchase_completed", "delay": 5000 },
      "questions": [
        { "id": "q1", "text": "How likely are you to recommend us?", "type": "rating", "min": 0, "max": 10 }
      ]
    }
  ],
  "settings": {
    "batchSize": 10,
    "flushInterval": 5000,
    "samplingRate": 1.0
  }
}
```

---

## Transaction & Chain Endpoints

### POST /v1/tx/enrich

Classifies and enriches raw blockchain transaction data.

**Request:**
```json
{
  "txHash": "0xabc123...",
  "chainId": 1,
  "vm": "evm",
  "from": "0x1234...",
  "to": "0x5678...",
  "value": "1500000000000000000",
  "input": "0xa9059cbb000000...",
  "gasUsed": "21000",
  "gasPrice": "30000000000"
}
```

**Response:**
```json
{
  "txHash": "0xabc123...",
  "classification": {
    "type": "swap",
    "protocol": "Uniswap V3",
    "defiCategory": "dex",
    "methodName": "exactInputSingle"
  },
  "gasAnalytics": {
    "gasCostETH": "0.00063000",
    "gasCostUSD": 1.89
  },
  "walletLabels": {
    "from": { "label": "User Wallet", "type": "hot_wallet", "risk": "low" },
    "to": { "label": "Uniswap V3 Router", "type": "smart_contract", "risk": "low" }
  }
}
```

### GET /v1/chains/{chainId}

Returns chain metadata on demand.

**Response:**
```json
{
  "chainId": 1,
  "name": "Ethereum Mainnet",
  "vm": "evm",
  "nativeCurrency": { "name": "Ether", "symbol": "ETH", "decimals": 18 },
  "blockExplorer": "https://etherscan.io",
  "testnet": false
}
```

### GET /v1/protocols/{address}

Identifies a smart contract / protocol by address.

**Query Parameters:** `chainId` (required)

**Response:**
```json
{
  "address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
  "name": "Uniswap V2 Router",
  "protocol": "uniswap",
  "category": "dex",
  "version": "v2",
  "verified": true
}
```

---

## ML & Classification

### POST /v1/predict

ML inference endpoint (replaces client-side edge-ml).

**Request:**
```json
{
  "type": "intent|bot|session_score|identity|journey|churn|ltv|anomaly|attribution",
  "signals": {
    "scrollDepth": 0.75,
    "timeOnPage": 45,
    "clickCount": 12,
    "formInteractions": 3,
    "pagesViewed": 5,
    "sessionDuration": 180
  }
}
```

**Response:**
```json
{
  "type": "intent",
  "prediction": {
    "primaryIntent": "purchase",
    "confidence": 0.87,
    "signals": ["high_scroll_depth", "form_interaction", "product_views"]
  }
}
```

### POST /v1/classify-source

Classifies a traffic source from raw attribution data.

**Request:**
```json
{
  "referrer": "https://google.com/search?q=aether",
  "utmSource": "google",
  "utmMedium": "cpc",
  "utmCampaign": "brand-q1",
  "clickIds": { "gclid": "abc123" },
  "landingPage": "https://app.aether.io/pricing"
}
```

**Response:**
```json
{
  "channel": "paid_search",
  "source": "google",
  "medium": "cpc",
  "campaign": "brand-q1",
  "attribution": {
    "model": "last_click",
    "touchpoints": [
      { "source": "google", "medium": "cpc", "timestamp": "2026-03-05T11:55:00Z" }
    ]
  }
}
```

### Automatic Traffic Source Classification (v8.2.0)

`POST /v1/track/traffic-source` now automatically classifies raw SDK signals into source/medium/channel using the server-side `SourceClassifier`. No client-side classification logic is needed — SDKs ship raw referrer, UTM params, click IDs, and referrer domain; the backend resolves everything.

**Classification Priority Chain:**

| Priority | Signal | Confidence | Example |
|----------|--------|------------|---------|
| 1 | Click IDs | 1.0 | `gclid=abc` → google / cpc / Paid Search |
| 2 | UTM params | 0.95 | `utm_source=newsletter` → newsletter / email / Email |
| 3 | Referrer domain | 0.9 | `t.co` → twitter / social / Organic Social |
| 4 | No signals | 0.5 | → (direct) / (none) / Direct |

**Supported Click IDs (12):** `gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`

**Channel Categories:** Paid Search, Paid Social, Organic Search, Organic Social, Email, Display, Affiliate, Referral, Direct, Other

**SourceInfo model now includes:**
```json
{
  "source": "google",
  "medium": "cpc",
  "traffic_type": "Paid Search",
  "confidence": 1.0,
  "referrer_domain": "google.com",
  "click_ids": { "gclid": "abc123" }
}
```

### GET /v1/wallet-label/{address}

Returns risk assessment and label for a wallet address.

**Query Parameters:** `chainId` (optional)

**Response:**
```json
{
  "address": "0x1234...",
  "label": "Binance Hot Wallet",
  "type": "exchange",
  "risk": "low",
  "tags": ["cex", "high_volume", "verified"],
  "firstSeen": "2020-01-15",
  "transactionCount": 1500000
}
```

---

## Rewards

### GET /v1/rewards/{rewardId}/eligibility

Checks if a user is eligible for a specific reward.

**Query Parameters:** `userId` (required)

**Response:**
```json
{
  "eligible": true,
  "rewardId": "reward-abc",
  "reason": "completed_3_transactions",
  "expiresAt": "2026-04-01T00:00:00Z",
  "amount": "100",
  "token": "AETHER"
}
```

### GET /v1/rewards/{rewardId}/payload

Returns a pre-built transaction payload for on-chain claiming.

**Query Parameters:** `userId` (required), `chainId` (required)

**Response:**
```json
{
  "to": "0xRewardContract...",
  "data": "0x...",
  "value": "0",
  "chainId": 1,
  "nonce": "abc123",
  "signature": "0x...",
  "expiry": 1743868800
}
```

### POST /v1/rewards/{rewardId}/claim

Submits an on-chain claim for verification.

**Request:**
```json
{
  "txHash": "0xabc123...",
  "chainId": 1,
  "userId": "user-123"
}
```

**Response:**
```json
{
  "status": "pending",
  "claimId": "claim-xyz",
  "estimatedConfirmation": "2026-03-05T12:05:00Z"
}
```

---

## Identity Resolution

### GET /v1/resolution/cluster/{user_id}

Get the full identity cluster for a user — all merged profiles, linked devices, IPs, wallets, and emails.

**Response:**
```json
{
  "cluster_id": "clust-abc",
  "canonical_user_id": "user-123",
  "confidence": 1.0,
  "member_count": 3,
  "resolution_status": "auto_merged",
  "members": [
    { "user_id": "user-123", "role": "primary", "joined_at": "2026-01-15T..." },
    { "user_id": "anon-456", "role": "merged", "joined_at": "2026-02-01T..." },
    { "user_id": "anon-789", "role": "merged", "joined_at": "2026-03-01T..." }
  ],
  "linked_devices": [
    { "fingerprint_id": "a1b2c3...", "first_seen": "2026-01-15T...", "observations": 47 },
    { "fingerprint_id": "d4e5f6...", "first_seen": "2026-02-01T...", "observations": 23 }
  ],
  "linked_ips": [
    { "ip_hash": "abc123...", "ip_range": "192.168.1.0/24", "observations": 120 }
  ],
  "linked_wallets": [
    { "address": "0x1234...abcd", "vm": "evm", "ens": "user.eth" },
    { "address": "7nY4...Kx3p", "vm": "svm" }
  ],
  "linked_emails": [
    { "email_hash": "def456...", "domain": "gmail.com" }
  ]
}
```

### GET /v1/resolution/pending

List pending resolution decisions awaiting admin review.

**Query Parameters:** `limit` (optional, default: 50)

**Response:**
```json
{
  "data": [
    {
      "decision_id": "dec-123",
      "profile_a_id": "user-123",
      "profile_b_id": "anon-456",
      "composite_confidence": 0.82,
      "deterministic_match": false,
      "signals": { "fingerprint": 0.85, "ip_cluster": 0.78, "location": 0.6 },
      "created_at": "2026-03-05T12:00:00Z"
    }
  ]
}
```

### POST /v1/resolution/pending/{id}/approve

Admin approves a pending identity merge.

### POST /v1/resolution/pending/{id}/reject

Admin rejects a pending identity merge.

### GET /v1/resolution/audit/{decision_id}

Get the full audit trail for a resolution decision — includes all signal snapshots at decision time.

### GET /v1/resolution/config

Get the current resolution engine configuration.

**Response:**
```json
{
  "auto_merge_threshold": 0.95,
  "review_threshold": 0.70,
  "max_cluster_size": 50,
  "cooldown_hours": 24,
  "require_deterministic_for_auto": true,
  "allow_probabilistic_auto_merge": false
}
```

### PUT /v1/resolution/config

Update resolution engine configuration thresholds.

**Request:**
```json
{
  "auto_merge_threshold": 0.90,
  "review_threshold": 0.65,
  "max_cluster_size": 100
}
```

### POST /v1/resolution/batch

Trigger a batch probabilistic matching job for the tenant.

---

## Intelligence Graph Endpoints (Feature-Flagged)

Three service groups are available when Intelligence Graph feature flags are enabled. All endpoints below return `403 FEATURE_DISABLED` unless the corresponding env var is set to `true`.

> **Required env vars:** `IG_COMMERCE_LAYER=true`, `IG_ONCHAIN_LAYER=true`, `IG_X402_LAYER=true`

### Commerce Service (L3a)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/commerce/payments` | Record payment + create `PAYS` edge in graph |
| POST | `/v1/commerce/hires` | Record agent hire + create `HIRED` edge |
| GET | `/v1/commerce/fees/report` | Fee elimination report for tenant |
| GET | `/v1/commerce/agent/{id}/spend` | Agent spend history |

### On-Chain Service (L0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/onchain/actions` | Record an on-chain action |
| GET | `/v1/onchain/actions/{agent_id}` | List agent's on-chain actions |
| GET | `/v1/onchain/contracts/{address}` | Contract details + call graph |
| POST | `/v1/onchain/listener/configure` | Configure chain event listener |
| GET | `/v1/onchain/rpc/health` | RPC gateway health check |

### x402 Service (L3b)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/x402/capture` | Ingest captured x402 payment |
| GET | `/v1/x402/graph` | Economic graph snapshot |
| GET | `/v1/x402/agent/{id}` | Agent x402 history |
| POST | `/v1/x402/graph/snapshot` | Trigger graph snapshot rebuild |

### Agent Extensions (added to /v1/agent/)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/agent/register` | Register agent in the Intelligence Graph |
| POST | `/v1/agent/tasks/{id}/lifecycle` | Update task lifecycle state |
| POST | `/v1/agent/tasks/{id}/decision` | Record an agent decision |
| POST | `/v1/agent/tasks/{id}/feedback` | Submit feedback on task outcome |
| GET | `/v1/agent/{id}/graph` | Agent's full graph neighborhood |
| GET | `/v1/agent/{id}/trust` | Agent trust score + history |
| POST | `/v1/agent/{id}/a2h` | Record agent-to-human interaction (notification, recommendation, delivery, escalation) |

### Diagnostics Service (Admin Only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/diagnostics/health` | Quick health check (healthy/degraded/critical) |
| GET | `/v1/diagnostics/errors` | List tracked errors with filters |
| GET | `/v1/diagnostics/report` | Full diagnostics report with breakdowns |
| POST | `/v1/diagnostics/errors/{fingerprint}/resolve` | Mark error as resolved |
| POST | `/v1/diagnostics/errors/{fingerprint}/suppress` | Suppress alerts for known error |
| GET | `/v1/diagnostics/circuit-breakers` | List all circuit breaker states |

All diagnostics endpoints require `admin` permission.

**Query Parameters (GET /errors):**
- `service` (optional) — filter by service name
- `category` (optional) — filter by error category
- `severity` (optional) — filter by severity level
- `resolved` (optional) — filter by resolution status

### Provider Gateway (BYOK)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/providers/keys` | Store or update an encrypted BYOK API key |
| GET | `/v1/providers/keys` | List tenant's stored BYOK keys (masked) |
| DELETE | `/v1/providers/keys/{provider}` | Remove a BYOK key for a provider |
| GET | `/v1/providers/usage` | Provider usage statistics with optional category/provider filters |
| GET | `/v1/providers/usage/summary` | Tenant-wide usage summary across all providers |
| GET | `/v1/providers/health` | All providers with health status and circuit breaker states |
| GET | `/v1/providers/categories` | List all provider categories and supported provider names |
| POST | `/v1/providers/test` | Test a provider call (verifies BYOK key works) |

**Permissions:**
- Key management endpoints (`POST/GET/DELETE /keys`) require `admin` permission
- Usage endpoints (`GET /usage`, `GET /usage/summary`) require `billing` permission
- Health and categories endpoints require `admin` permission
- Test endpoint requires `admin` permission

**Provider Categories:**
- `blockchain_rpc` — QuickNode, Alchemy, Infura, Custom RPC
- `block_explorer` — Etherscan, Moralis
- `social_api` — Twitter, Reddit
- `analytics_data` — Dune Analytics

**Priority Chain (every provider call):**
1. Tenant BYOK key → 2. System default provider → 3. Fallback provider(s) → 4. ServiceUnavailableError

Feature flag: `PROVIDER_GATEWAY_ENABLED=false` (default). Zero impact until activated.

---

### Data Lake Service (v8.5.0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/lake/ingest` | Ingest provider data into Bronze tier (batch, source-tagged) |
| POST | `/v1/lake/rollback` | Rollback records by source_tag across specified tiers |
| GET | `/v1/lake/audit/{domain}/{source_tag}` | Query audit trail for a source_tag |
| POST | `/v1/lake/materialize` | Write Gold metric/feature/highlight |
| GET | `/v1/lake/gold/{domain}/{entity_id}` | Query Gold metrics for an entity |
| GET | `/v1/lake/quality/{domain}` | Run data quality checks on a domain's Bronze tier |
| GET | `/v1/lake/status` | Record counts per domain per tier |

**Domains:** `market`, `onchain`, `social`, `identity`, `governance`, `tradfi`

**Required fields for ingest:** `domain`, `source`, `source_tag`, `records[]`

**Permissions:** `write` for ingest/materialize, `read` for queries, `admin` for rollback/quality

---

### Intelligence Service (v8.5.0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/intelligence/wallet/{address}/risk` | Composite wallet risk score (trust scorer + graph + features) |
| GET | `/v1/intelligence/protocol/{id}/analytics` | Protocol-level analytics from Gold tier |
| GET | `/v1/intelligence/entity/{id}/cluster` | Identity cluster via graph relationships |
| GET | `/v1/intelligence/alerts` | Anomaly alerts from Gold tier |
| GET | `/v1/intelligence/wallet/{address}/profile` | Full wallet intelligence profile |

**Permissions:** `read` for all intelligence endpoints

---

### Profile 360 Service (v8.5.0)

Holistic user/entity omniview — composes data from all Aether subsystems into one canonical profile view. Does not duplicate data; aggregates from identity, analytics, consent, graph, intelligence, and lake subsystems.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/profile/{user_id}` | Full holistic profile (identity + identifiers + consent + timeline + graph + intelligence + lake + provenance) |
| GET | `/v1/profile/{user_id}/timeline` | Paginated event timeline with optional `event_type` filter |
| GET | `/v1/profile/{user_id}/graph` | Graph relationships (bounded to 50 neighbors) |
| GET | `/v1/profile/{user_id}/intelligence` | Risk scores + Gold-tier features + model outputs |
| GET | `/v1/profile/{user_id}/identifiers` | All linked wallets, emails, devices, sessions, social handles |
| GET | `/v1/profile/{user_id}/provenance` | Source attribution across identity, onchain, social data |
| GET | `/v1/profile/resolve` | Resolve any identifier to canonical profile_id (query params: `wallet`, `email`, `device`, `session`, `social`, `customer`) |
| GET | `/v1/profile/{user_id}/lake/{domain}` | Domain-specific Gold data (identity, market, onchain, social) |

**Query params:** `include_timeline`, `include_graph`, `include_intelligence`, `include_lake` (all default true), `timeline_limit` (1–500)

**Permissions:** `read` for all profile endpoints

---

### Population Intelligence Service (v8.5.0)

Macro-to-micro group intelligence. Supports segments, cohorts, clusters, communities, batches, archetypes, anomaly groups, lookalike groups, risk groups, and lifecycle groups.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/population/summary` | Population overview: total groups, type distribution, top groups |
| GET | `/v1/population/groups` | List all groups with optional `population_type` filter |
| GET | `/v1/population/trends` | Group creation over time |
| POST | `/v1/population/groups` | Create a new group (segment, cohort, cluster, community, etc.) |
| GET | `/v1/population/groups/{id}` | Group details with member count |
| GET | `/v1/population/groups/{id}/members` | Paginated members with `min_confidence` filter |
| POST | `/v1/population/groups/{id}/members` | Add members with basis, confidence, reason, source_tag |
| GET | `/v1/population/groups/{id}/intelligence` | Group intelligence summary (basis distribution, avg confidence) |
| GET | `/v1/population/compare` | Compare two groups: overlap, unique counts (`group_a`, `group_b` query params) |
| GET | `/v1/population/entity/{id}/memberships` | All groups an entity belongs to (enriched with names/types) |
| GET | `/v1/population/entity/{id}/explain/{pop_id}` | Explain why an entity is in a specific group |

**Group types:** `segment`, `cohort`, `cluster`, `community`, `batch`, `archetype`, `anomaly`, `lookalike`, `risk`, `lifecycle`

**Membership basis:** `rule`, `graph`, `ml_model`, `similarity`, `manual`, `inferred`

**Permissions:** `write` for create/add members, `read` for queries

---

### Expectation Engine Service (v8.5.0)

Negative-space intelligence: what should have happened but did not. Detects absence, contradiction, and source silence across macro/meso/micro levels.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/expectations/summary` | Population-wide expected vs actual summary |
| GET | `/v1/expectations/contradictions` | Top contradictions across the population |
| GET | `/v1/expectations/silence` | Source silence vs real behavior change (explicitly separated) |
| GET | `/v1/expectations/group/{pop_id}` | Group expectation view |
| GET | `/v1/expectations/group/{pop_id}/gaps` | Missing expected behaviors for a group |
| GET | `/v1/expectations/entity/{id}` | Full expectation scan for an entity (runs all detectors) |
| GET | `/v1/expectations/entity/{id}/signals` | Signals filtered by `signal_type` |
| GET | `/v1/expectations/entity/{id}/explain` | Why this entity is unusual — top signals with explanations |
| POST | `/v1/expectations/scan/{id}` | Trigger full expectation scan for an entity |
| GET | `/v1/expectations/signal/{id}` | Signal detail with full provenance |

**Signal types (ranked by business priority):** `identity_contradiction`, `relationship_contradiction`, `broken_sequence`, `missing_expected_action`, `missing_expected_edge`, `peer_deviation`, `self_deviation`, `cohort_anomaly`, `source_silence`, `temporal_contradiction`, `model_contradiction`, `graph_contradiction`

**Every signal includes:** `expected`, `observed`, `baseline_source`, `confidence`, `explanation`, `is_source_silence`, `severity`, `source_tag`

**Permissions:** `read` for queries, `write` for triggering scans

---

### Behavioral Continuity & Friction Service (v8.6.0)

Derived signals from data Aether already collects. 10 signal families detecting intent residue, wallet friction, identity deltas, sequence scars, source shadow, and more.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/behavioral/entity/{id}` | Full behavioral scan (all 10 engines) |
| GET | `/v1/behavioral/entity/{id}/signals` | Persisted signals filtered by `family` |
| POST | `/v1/behavioral/scan/{id}` | Trigger full behavioral scan |
| GET | `/v1/behavioral/summary` | Population behavioral signal distribution |
| GET | `/v1/behavioral/registry` | Signal definitions and output contracts |

**Signal families:** `intent_residue`, `wallet_friction`, `identity_delta`, `pre_post_continuity`, `sequence_scar`, `source_shadow`, `reward_near_miss`, `social_chain_lag`, `cex_dex_transition`, `behavioral_twin`

**Permissions:** `read` for queries, `write` for triggering scans

---

### RWA Intelligence Graph Service (v8.6.0)

Tokenized real-world asset observation, analysis, and scoring. Aether does NOT issue RWAs — this is intelligence only.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/rwa/assets` | Register an RWA asset as intelligence object |
| GET | `/v1/rwa/assets` | List assets with `asset_class` and `chain` filters |
| GET | `/v1/rwa/assets/{id}` | Full asset details |
| POST | `/v1/rwa/policies` | Register compliance/transfer-restriction policy |
| GET | `/v1/rwa/assets/{id}/policies` | Policies for an asset |
| POST | `/v1/rwa/simulate-transfer` | Simulate transfer policy check (whitelist, jurisdiction, holder cap, lockup, accreditation) |
| POST | `/v1/rwa/cashflows` | Record cashflow event (coupon, dividend, redemption, NAV update, attestation, etc.) |
| GET | `/v1/rwa/assets/{id}/cashflows` | Cashflow history filtered by `cashflow_type` |
| GET | `/v1/rwa/exposure/{entity_id}` | RWA exposure for wallet/entity (direct + inferred + concentration) |
| GET | `/v1/rwa/assets/{id}/reserve-credibility` | Reserve credibility score (attestation cadence + NAV freshness) |
| GET | `/v1/rwa/assets/{id}/redemption-pressure` | Redemption pressure score |
| POST | `/v1/rwa/holders` | Register holder record |
| GET | `/v1/rwa/assets/{id}/holders` | Asset holder list |

**Asset classes:** `tokenized_treasury`, `money_market_fund`, `private_credit`, `fund_interest`, `structured_credit`, `tokenized_deposit`, `real_estate`, `invoice_receivable`, `trade_finance`, `commodity`, `carbon_credit`, `tokenized_equity`, `tokenized_etf`

**Policy types:** `whitelist`, `accreditation`, `jurisdiction`, `lockup`, `holder_cap`, `secondary_transfer`, `aml_kyc`

**Permissions:** `write` for asset/policy/cashflow/holder creation, `read` for queries

---

All intelligence outputs are sourced from persisted lake data, graph relationships, and ML model scoring. No mock or synthetic data is returned.

---

### Web3 Coverage Service (v8.7.0)

Registry-first Web3 intelligence system with canonical chain/protocol/app/domain/token registries, contract classification, migration tracking, and graph-native coverage spine.

**Chain Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/chains` | Register a chain |
| `GET` | `/v1/web3/chains` | List chains (filter: `vm_family`) |
| `GET` | `/v1/web3/chains/{chain_id}` | Get chain details |

**Protocol Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/protocols` | Register a protocol |
| `GET` | `/v1/web3/protocols` | List protocols (filter: `family`, `chain`, search: `q`) |
| `GET` | `/v1/web3/protocols/{protocol_id}` | Get protocol details |

**Contract Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/contracts` | Register a contract instance |
| `GET` | `/v1/web3/contracts/{chain_id}/{address}` | Get contract details |
| `GET` | `/v1/web3/contracts/unclassified` | List unclassified contracts |
| `POST` | `/v1/web3/contracts/{chain_id}/{address}/reclassify` | Reclassify a contract |

**Token Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/tokens` | Register a token |
| `GET` | `/v1/web3/tokens` | List tokens (filter: `chain_id`, `stablecoins`) |

**App / Domain Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/apps` | Register an app/dApp |
| `GET` | `/v1/web3/apps` | List apps |
| `POST` | `/v1/web3/domains` | Register a frontend domain |
| `GET` | `/v1/web3/domains/{domain}` | Get domain attribution |

**Governance Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/governance/spaces` | Register a governance space |
| `GET` | `/v1/web3/governance/spaces` | List governance spaces |

**Classification**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/classify/contract` | Classify a contract address |
| `POST` | `/v1/web3/classify/method` | Map method selector to canonical action |
| `POST` | `/v1/web3/classify/domain` | Attribute a frontend domain |
| `POST` | `/v1/web3/classify/observation` | Classify a full Web3 observation |

**Observation Ingestion**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/observations/batch` | Bulk ingest Web3 observations (up to 500/batch) |

**Migration Tracking**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/migrations` | Record a protocol migration |
| `GET` | `/v1/web3/migrations/{protocol_id}` | List migrations for a protocol |
| `POST` | `/v1/web3/migrations/detect` | Detect if a new contract is a migration |

**Coverage & Administration**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/web3/coverage/status` | Aggregated coverage status across all registries |
| `GET` | `/v1/web3/coverage/health` | Quick health check (seeded/unseeded) |
| `POST` | `/v1/web3/seed` | Seed registries with initial data (admin) |

---

### Cross-Domain TradFi/Web2 Intelligence Service (v8.7.0)

Unified cross-domain business, TradFi, and Web intelligence graph with financial accounts, instruments, trade lifecycle, compliance, and identity fusion.

**Institutions**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/institutions` | Register an institution |
| `GET` | `/v1/crossdomain/institutions` | List institutions (filter: `institution_type`, search: `q`) |
| `GET` | `/v1/crossdomain/institutions/{institution_id}` | Get institution details |

**Accounts**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/accounts` | Register a financial account |
| `GET` | `/v1/crossdomain/accounts` | List accounts (filter: `owner`, `institution`, `account_type`) |
| `GET` | `/v1/crossdomain/accounts/{account_id}` | Get account details |
| `GET` | `/v1/crossdomain/accounts/{account_id}/positions` | List account positions |

**Instruments**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/instruments` | Register a market instrument |
| `GET` | `/v1/crossdomain/instruments` | List instruments (filter: `instrument_type`, `issuer`, search: `q`) |
| `GET` | `/v1/crossdomain/instruments/{instrument_id}` | Get instrument details |
| `GET` | `/v1/crossdomain/instruments/symbol/{symbol}` | Get instrument by ticker symbol |

**Positions / Orders / Executions / Balances / Cash**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/positions` | Record a position snapshot |
| `GET` | `/v1/crossdomain/positions/instrument/{instrument_id}` | List positions by instrument |
| `POST` | `/v1/crossdomain/orders` | Record a trade order |
| `GET` | `/v1/crossdomain/orders/{account_id}` | List orders by account |
| `POST` | `/v1/crossdomain/executions` | Record a trade execution |
| `GET` | `/v1/crossdomain/executions/order/{order_id}` | List executions by order |
| `GET` | `/v1/crossdomain/executions/account/{account_id}` | List executions by account |
| `POST` | `/v1/crossdomain/balances` | Record a balance snapshot |
| `GET` | `/v1/crossdomain/balances/{account_id}/latest` | Get latest balance |
| `POST` | `/v1/crossdomain/cash-movements` | Record a cash movement |
| `GET` | `/v1/crossdomain/cash-movements/{account_id}` | List cash movements |

**Compliance / Business Events**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/compliance/actions` | Record a compliance action |
| `GET` | `/v1/crossdomain/compliance/actions/{entity_id}` | List compliance actions for entity |
| `POST` | `/v1/crossdomain/events` | Record a business application event |
| `GET` | `/v1/crossdomain/events/entity/{entity_id}` | List events by entity |
| `GET` | `/v1/crossdomain/events/instrument/{instrument_id}` | List events by instrument |

**Cross-Domain Identity Links**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/links` | Create a cross-domain identity link |
| `GET` | `/v1/crossdomain/links/{entity_id}` | List identity links for entity |
| `GET` | `/v1/crossdomain/links/high-confidence` | List high-confidence cross-domain links |

**Fusion / Intelligence**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/crossdomain/fusion/exposure/{entity_id}` | Cross-domain exposure graph |
| `GET` | `/v1/crossdomain/fusion/profile/{entity_id}` | Unified cross-domain profile |
| `GET` | `/v1/crossdomain/coverage/status` | Coverage status across registries |
| `GET` | `/v1/crossdomain/coverage/health` | Quick health check |

---

## Error Responses

All endpoints return standard error format:

```json
{
  "error": {
    "code": "INVALID_API_KEY",
    "message": "The provided API key is invalid or expired",
    "status": 401
  }
}
```

Common error codes:
- `400` — `INVALID_REQUEST` — Malformed request body
- `400` — `FEATURE_DISABLED` — Intelligence Graph feature flag not enabled
- `401` — `INVALID_API_KEY` — Missing or invalid API key
- `403` — `FORBIDDEN` — API key lacks required permissions
- `404` — `NOT_FOUND` — Resource not found
- `429` — `RATE_LIMITED` — Too many requests
- `403` — `EXTRACTION_BLOCKED` — Extraction defense triggered (canary or risk score)
- `500` — `INTERNAL_ERROR` — Server error
- `503` — `CIRCUIT_OPEN` — Circuit breaker is open for the requested operation

---

## Model Extraction Defense (v8.3.1)

The extraction defense layer protects ML inference endpoints against model extraction and knowledge distillation attacks. Enabled via `ENABLE_EXTRACTION_DEFENSE=true`.

### Middleware Behavior

When enabled, all `/v1/predict/*` (ML serving API) and `/v1/ml/predict` (backend gateway) requests pass through the defense middleware:

1. **Rate limiting** — dual-axis sliding window (per-API-key + per-IP) with minute/hour/day windows. Exceeding limits returns `429`.
2. **Canary detection** — secret-seed trap inputs detect systematic input-space exploration. Triggers cooldown (`403`).
3. **Pattern analysis** — detects feature sweeps, similarity clustering, uniform probing, bot-like timing.
4. **Risk scoring** — EMA-smoothed score in `[0, 1]` drives response degradation across four tiers.

### Response Perturbation

Responses are modified based on the client's risk tier:

| Tier | Risk Score | Noise Multiplier | Effect |
|------|-----------|-------------------|--------|
| Normal | 0.0 – 0.3 | 1x | Minimal noise, near-original outputs |
| Elevated | 0.3 – 0.6 | 3x | Moderate noise added to probabilities |
| High | 0.6 – 0.8 | 8x | Aggressive noise, top-k clipping |
| Critical | 0.8 – 1.0 | 15x | Maximum degradation, may block |

### Defense Monitoring Endpoints (ML Serving API)

#### `GET /v1/defense/status`

Returns defense layer configuration and state.

```json
{
  "enabled": true,
  "output_noise": true,
  "watermark": true,
  "query_analysis": true,
  "canary_count": 50,
  "tracked_clients": 12
}
```

#### `GET /v1/defense/metrics`

Returns operational metrics snapshot including request counts, block reasons, risk tier distribution, and recent canary triggers.

#### `GET /v1/defense/risk-scores`

Returns current EMA risk scores for all tracked API keys.

#### `GET /v1/defense/canary-triggers`

Returns the last 50 canary detection events with API key (masked), IP, canary ID, and timestamp.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_EXTRACTION_DEFENSE` | `false` | Master switch |
| `ENABLE_OUTPUT_NOISE` | `true` | Enable output perturbation |
| `ENABLE_WATERMARK` | `true` | Enable probabilistic watermarking |
| `ENABLE_QUERY_ANALYSIS` | `true` | Enable pattern detection and risk scoring |
| `WATERMARK_SECRET_KEY` | (default) | Secret for watermark generation (change in production) |
| `CANARY_SECRET_SEED` | (default) | Seed for canary input generation (change in production) |
