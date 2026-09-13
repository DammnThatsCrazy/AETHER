---
title: Cross Domain Tradfi Web2 Audit
slug: archive/audits/cross_domain_tradfi_web2_audit
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Cross-Domain TradFi/Web2 Audit

## Current Architecture (Repo-Truth)

### Service Inventory
- **30 backend services**, **213 endpoints**, **24 providers**
- Microservice topology: ingestion, identity, graph, commerce, fraud, attribution, rwa, consent, admin, profile, web3, lake

### Graph Infrastructure
- **44 vertex types**, **70+ edge types**, **4 relationship layers**
- Neptune-backed property graph with configurable traversal depths
- Relationship layers: ownership, interaction, similarity, temporal

### Identity Resolution
- Core entities: **User**, **Company**, **IdentityCluster**
- Linking signals: email, phone, wallet_address, device_fingerprint, IP
- Deterministic and probabilistic resolution with confidence scoring
- Merge/split operations with full audit trail

### Commerce
- **PaymentRecord** with full lifecycle tracking
- **x402 micropayments** for API monetization
- **FeeElimination** engine for subsidized access patterns
- Stripe, crypto, and hybrid payment rails

### RWA (Real-World Assets)
- **14 asset classes**: real_estate, private_credit, treasury, commodity, art, collectible, carbon_credit, ip_royalty, infrastructure, agriculture, insurance, trade_finance, equipment, invoice
- **7 policy types**: accreditation, jurisdiction, holding_period, concentration, redemption, transfer_restriction, compliance_check
- **11 cashflow types**: coupon, dividend, rental, royalty, interest, principal, distribution, redemption, fee, rebate, performance
- **6 exposure types**: direct, synthetic, wrapped, pooled, leveraged, hedged

### Fraud Detection
- **9 composable signals**: bot_score, sybil_score, velocity_score, wallet_age_score, geographic_score, behavioral_score, device_score, transaction_score, network_score
- Rule engine with threshold-based and ML-based scoring
- Real-time and batch evaluation modes

### Attribution
- **5 models**: first_touch, last_touch, linear, time_decay, multi_touch
- Configurable lookback windows and conversion definitions
- Channel and campaign hierarchy support

### Ingestion Pipeline
- **SDK events**: page_view, click, custom (arbitrary payload)
- **API feeds**: dune, strategy, custom_api
- **Batch ingestion**: up to 500 events per request
- Schema validation, deduplication, and dead-letter routing

### Admin and Billing
- **Tenant management** with isolation guarantees
- **Billing plans**: free, pro, enterprise
- Usage metering, rate limiting, and quota enforcement

### Consent and Privacy
- **GDPR DSR** (Data Subject Requests): access, erasure, portability, rectification
- **Purpose-based consent**: analytics, marketing, personalization, third_party_sharing
- Consent receipts with timestamp and version tracking

### Web3 Coverage
- **31 chains**, **40+ protocols**, **24 apps**
- Method selector classification for transaction categorization
- Migration tracking across chains and protocols
- DEX, lending, staking, bridge, and NFT activity normalization

### Provider Registry
- **Massive**: alt data feeds (social, sentiment, alternative signals)
- **Databento**: institutional market data (equities, futures, options)
- **CoinGecko**: crypto market data (prices, volumes, market caps)
- **Binance**: exchange data (orderbook, trades, funding rates)
- **Coinbase**: exchange data (prices, trades, custody events)

### Data Lake
- **6 domains**: market, onchain, social, identity, governance, tradfi
- **3 tiers**: Bronze (raw), Silver (cleaned/normalized), Gold (aggregated/enriched)
- Partitioned by domain, source, and ingestion date
- Schema evolution with backward compatibility

---

## What Must NOT Be Rebuilt

### Identity Resolution Engine
- **Action**: Extend with new signal types (brokerage account, bank account, KYC identity)
- **Do NOT**: Replace the resolution algorithm, merge logic, or cluster management
- **Reason**: The probabilistic/deterministic dual-mode resolver is battle-tested and handles billions of link evaluations

### Graph Infrastructure
- **Action**: Add new vertex types (financial_account, instrument, institution) and edge types (holds_position, executes_trade, custodies_for)
- **Do NOT**: Replace Neptune backend or change traversal engine
- **Reason**: Neptune handles the current 44 vertex types and 70+ edge types at scale; adding more is incremental

### Ingestion Pipeline
- **Action**: Add new event types (quote_lookup, order_placed, trade_executed) and feed sources (brokerage_feed, bank_feed, market_data_feed)
- **Do NOT**: Replace the SDK event schema, batch processor, or dead-letter routing
- **Reason**: The pipeline already handles schema validation, dedup, and routing for arbitrary payloads

### Web3 Registries
- **Action**: Reuse the registry pattern (chain_registry, protocol_registry, app_registry) for TradFi equivalents (venue_registry, instrument_registry, institution_registry)
- **Do NOT**: Build a separate registry framework
- **Reason**: The registry pattern (enum + metadata + validation) is proven and consistent

### RWA Service
- **Action**: It already models TradFi-adjacent assets (treasury, private_credit, trade_finance); extend with pure TradFi instruments
- **Do NOT**: Create a parallel asset modeling service
- **Reason**: RWA's 14 asset classes, 7 policy types, and 11 cashflow types overlap significantly with TradFi modeling needs

### Fraud Engine
- **Action**: Add new signals (wash_trading_score, front_running_score, insider_trading_score, account_takeover_score)
- **Do NOT**: Replace the composable signal architecture or scoring pipeline
- **Reason**: The 9-signal composable engine is designed for extension; new signals plug in without changing the aggregation logic

### Commerce Service
- **Action**: Extend payment types to include ACH, wire, brokerage sweep, margin call
- **Do NOT**: Replace PaymentRecord, x402, or FeeElimination
- **Reason**: The payment lifecycle model generalizes to any rail; new rails are additive

### Profile 360 Composer
- **Action**: Add new data source adapters (brokerage_profile, bank_profile, advisor_profile)
- **Do NOT**: Replace the composition engine or rendering pipeline
- **Reason**: The composer already handles multi-source profile assembly with conflict resolution

---

## Gap Analysis (16 Gaps)

### Gap 1: No Brokerage/Bank/Custodian Entity Types
- **Current state**: Company vertex exists but is not specialized for financial institutions
- **Impact**: Cannot distinguish between a SaaS vendor and a broker-dealer in the graph
- **Required**: Specialized vertex types with regulatory metadata (CRD number, LEI, charter type)

### Gap 2: No Financial Account Model
- **Current state**: No representation of balances, positions, or portfolio state
- **Impact**: Cannot track user holdings, calculate exposure, or reconstruct portfolio history
- **Required**: Account entity with type taxonomy, balance snapshots, and position tracking

### Gap 3: No Market Instrument Model
- **Current state**: No representation of stocks, ETFs, options, bonds, or funds
- **Impact**: Cannot reference what users hold, trade, or are exposed to
- **Required**: Instrument registry with identifiers (CUSIP, ISIN, FIGI, ticker), classification, and metadata

### Gap 4: No Trade Lifecycle Model
- **Current state**: No representation of orders, executions, or settlements
- **Impact**: Cannot track trading activity, calculate realized P&L, or detect patterns
- **Required**: Full order-to-settlement lifecycle with status tracking and venue attribution

### Gap 5: No TradFi Identity Signals
- **Current state**: Identity resolution uses email, phone, wallet, fingerprint, IP only
- **Impact**: Cannot link users across brokerage accounts, bank accounts, or KYC records
- **Required**: New signal types: brokerage_account_owner, bank_account_holder, kyc_identity, tax_id_match

### Gap 6: No Business Application Entity Types
- **Current state**: No CRM, support, billing, or product analytics objects
- **Impact**: Cannot model Web2 application data (Salesforce contacts, Zendesk tickets, Stripe customers)
- **Required**: Application entity types with source system attribution and cross-reference linking

### Gap 7: No Pre-Trade Behavioral Events
- **Current state**: SDK captures page_view, click, custom but no financial intent signals
- **Impact**: Cannot track quote lookups, watchlist additions, order ticket interactions, or chart engagement
- **Required**: New event types in the ingestion pipeline with financial context fields

### Gap 8: No Funding Flow Tracking
- **Current state**: PaymentRecord exists but no ACH/wire/card-to-brokerage-to-wallet flow modeling
- **Impact**: Cannot trace the path of money from bank to brokerage to crypto wallet
- **Required**: Funding flow edges in the graph connecting accounts across rails with timing and amount

### Gap 9: No Legal/Beneficial Owner Distinction
- **Current state**: Graph has OWNS_WALLET but no differentiation between legal owner, beneficial owner, authorized user
- **Impact**: Cannot model trusts, custodial accounts, omnibus structures, or corporate ownership
- **Required**: Owner type taxonomy with relationship edges and regulatory classification

### Gap 10: No Advisor/Broker/Agent Relationship Modeling
- **Current state**: No representation of advisory relationships, broker assignments, or agent authority
- **Impact**: Cannot track who advises whom, discretionary vs. non-discretionary, or fiduciary obligations
- **Required**: Relationship edges with role, authority level, and temporal validity

### Gap 11: No Compliance/Risk Path Reasoning Across Domains
- **Current state**: Fraud engine scores individual signals but cannot traverse cross-domain compliance paths
- **Impact**: Cannot answer "does this person's bank activity connect to suspicious on-chain behavior?"
- **Required**: Graph traversal queries that cross domain boundaries with compliance-aware edge weighting

### Gap 12: No Point-in-Time Portfolio/Account Reconstruction
- **Current state**: No temporal versioning of account or position state
- **Impact**: Cannot answer "what did this portfolio look like on date X?" or perform historical analysis
- **Required**: Bi-temporal model (effective_at + observed_at) with version counters and snapshot reconstruction

### Gap 13: No Market Data Ingestion Pipeline
- **Current state**: Massive and Databento providers exist in the registry but no ingestion jobs consume their data
- **Impact**: Provider integrations are dormant; no price, volume, or reference data flows into the lake
- **Required**: Ingestion jobs per provider with scheduling, normalization, and lake routing

### Gap 14: No Corporate Action Tracking
- **Current state**: No representation of splits, dividends, mergers, spin-offs, or reorganizations
- **Impact**: Cannot adjust position history, calculate total return, or maintain accurate cost basis
- **Required**: Corporate action event model with instrument linkage and position adjustment logic

### Gap 15: No Cross-Domain Join Scoring
- **Current state**: Identity resolution operates within signal types; no confidence score for bank-to-brokerage-to-wallet chains
- **Impact**: Cannot express "we are 87% confident this bank account holder is also this wallet owner"
- **Required**: Cross-domain join model with transitive confidence decay and evidence aggregation

### Gap 16: No Household/Family Entity Grouping
- **Current state**: IdentityCluster groups signals for one person; no multi-person household concept
- **Impact**: Cannot model family accounts, household-level exposure, or related-person compliance checks
- **Required**: Household entity with membership edges, role designations, and aggregate metrics

---

## Ranked Implementation Order

### P0 — Foundation
**Timeline**: Must ship before any TradFi/Web2 features are usable

| Component | Description | Gaps Addressed |
|-----------|-------------|----------------|
| Entity model expansion | Add institution, fund, desk, strategy, issuer vertex types with regulatory metadata | Gap 1 |
| Financial account model | Account types, balances, positions with type taxonomy | Gap 2 |
| Instrument registry | Stocks, ETFs, options, bonds, funds with identifier mapping (CUSIP, ISIN, FIGI) | Gap 3 |
| Graph expansion | New vertex types, edge types, and traversal patterns for TradFi entities | Gap 1, 2, 3 |

**Dependencies**: None (builds on existing graph and registry patterns)
**Validation**: Can create a financial institution, open an account, register an instrument, and link them in the graph

### P1 — Core
**Timeline**: Immediately after P0; enables primary use cases

| Component | Description | Gaps Addressed |
|-----------|-------------|----------------|
| Trade lifecycle model | Orders, executions, settlements with full status tracking | Gap 4 |
| TradFi identity signals | Brokerage account owner, bank account holder, KYC identity linking | Gap 5 |
| Business application entities | CRM, support, billing, product analytics objects with source attribution | Gap 6 |
| Owner type taxonomy | Legal owner, beneficial owner, authorized user, custodian distinctions | Gap 9 |

**Dependencies**: P0 (entity model, account model, instrument registry)
**Validation**: Can record a trade, link it to an identity, associate it with a business application, and distinguish owner types

### P2 — Depth
**Timeline**: After P1; adds operational depth and compliance capability

| Component | Description | Gaps Addressed |
|-----------|-------------|----------------|
| Market data pipeline | Activate Massive/Databento ingestion with scheduling and lake routing | Gap 13 |
| Compliance graph reasoning | Cross-domain traversal queries with compliance-aware weighting | Gap 11 |
| Funding flow tracking | ACH/wire/card-to-brokerage-to-wallet flow edges with timing | Gap 8 |
| Pre-trade behavioral events | Quote lookup, watchlist, order ticket, chart interaction events | Gap 7 |
| Advisor/broker/agent relationships | Advisory edges with role, authority, and temporal validity | Gap 10 |
| Corporate action tracking | Splits, dividends, mergers with position adjustment | Gap 14 |

**Dependencies**: P1 (trade lifecycle, identity signals, owner types)
**Validation**: Can ingest market data, trace a funding flow from bank to wallet, detect compliance-relevant paths, and track pre-trade intent

### P3 — Intelligence
**Timeline**: After P2; enables advanced analytics and ML

| Component | Description | Gaps Addressed |
|-----------|-------------|----------------|
| Cross-domain join scoring | Transitive confidence decay across bank-brokerage-wallet chains | Gap 15 |
| Point-in-time reconstruction | Bi-temporal model with effective_at/observed_at/as_of/version | Gap 12 |
| Household/family grouping | Multi-person entity with membership, roles, and aggregate metrics | Gap 16 |
| Full ML integration | Feature store population from all new entity types and relationships | All |

**Dependencies**: P2 (compliance graph, funding flows, market data)
**Validation**: Can score cross-domain identity joins, reconstruct historical portfolios, group households, and feed ML models with full-spectrum features
