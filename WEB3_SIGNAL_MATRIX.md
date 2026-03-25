# Web3 Signal Matrix

## Overview

This document maps every Web3 signal type through the full Aether intelligence pipeline: from source inputs through registry joins, graph object creation, downstream model consumption, and provenance/confidence/completeness rules. Each signal type represents a distinct category of intelligence that the Web3 Coverage layer produces.

---

## Signal 1: Wallet to Protocol Usage

### Signal Definition

Maps a wallet's on-chain transactions to the protocols it interacts with, using method selector classification and contract registry lookup.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Signal source (the actor) |
| Protocol | Registry object + vertex | Signal target (the protocol used) |
| Contract Instance | Registry object | Intermediary (the contract transacted with) |
| Contract System | Registry object + vertex | Intermediary (logical grouping of contracts) |
| Chain | Registry object + vertex | Context (which chain the interaction occurred on) |

### Source Inputs

- **Primary**: Transaction observations via `POST /v1/web3/observations/batch`
  - `wallet_address`: the sending address
  - `to_address`: the contract address interacted with
  - `chain_id`: the chain on which the transaction occurred
  - `method_selector`: the 4-byte EVM method selector (first 4 bytes of calldata)
  - `tx_hash`: transaction hash for provenance
  - `timestamp`: block timestamp
- **Secondary**: Method selector from `METHOD_SELECTOR_MAP` in classifier.py

### Required Joins

1. `ContractInstanceRegistry.get_by_address_chain(to_address, chain_id)` — Resolve contract to its registered instance
2. `ContractInstanceRecord.system_id` → `ContractSystemRegistry.get(system_id)` — Resolve instance to its logical system
3. `ContractSystemRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Resolve system to its parent protocol
4. `METHOD_SELECTOR_MAP[method_selector]` — Resolve method selector to canonical action

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address, chain_id |
| PROTOCOL vertex | Vertex | slug, name, protocol_family |
| CONTRACT_SYSTEM vertex | Vertex | name, protocol_id |
| CHAIN vertex | Vertex | chain_id, name, vm_family |
| WALLET --USES_PROTOCOL--> PROTOCOL | Edge | canonical_action, tx_hash, timestamp, chain_id, confidence |
| CONTRACT --INSTANCE_OF--> CONTRACT_SYSTEM | Edge | role, verified |
| CONTRACT_SYSTEM --PART_OF_SYSTEM--> PROTOCOL | Edge | |
| PROTOCOL --DEPLOYED_ON--> CHAIN | Edge | |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Profile 360 — Protocol Exposure** | Aggregates USES_PROTOCOL edges per wallet to build protocol exposure vector. Shows which protocols a wallet uses, frequency, recency, and diversity across protocol families. |
| **Population — Protocol Cohorts** | Segments wallets by protocol usage. Creates populations like "Uniswap power users", "Aave borrowers", "multi-protocol DeFi users". Protocol family becomes a segmentation dimension. |
| **Trust Scoring** | Protocol diversity and interaction history feed into trust score calculation. Wallets interacting with verified protocols on multiple chains receive higher trust signals. |
| **Behavioral — wallet_friction** | Protocol interaction patterns (swap frequency, lending cycles, staking duration) feed into wallet friction behavioral models. Canonical actions provide normalized activity vocabulary. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.protocols[]` — Array of protocol slugs with usage counts, last interaction timestamp, canonical actions used, and chains. Queryable as "show me all protocols this wallet has used." |
| **Population** | `population.filters.protocol_slug`, `population.filters.protocol_family` — Population can be filtered by specific protocol or protocol family. Enables cohorts like "all wallets that used lending protocols in the last 30 days." |
| **Expectation** | `expectation.baselines.protocol_interaction_frequency` — Baseline established from historical protocol interaction cadence. Deviation triggers expectation violation (e.g., wallet that used Aave daily suddenly stops for 14 days). |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source attribution** | Every USES_PROTOCOL edge carries `provenance.source` = "observation_batch" or "classify_endpoint" |
| **Transaction evidence** | `provenance.evidence` includes `tx_hash`, `block_number`, `chain_id` for on-chain verification |
| **Observer identity** | `provenance.observer_id` records the ingestion pipeline or API caller that produced the classification |
| **Signature** | HMAC signature over (wallet_address, protocol_slug, canonical_action, tx_hash, timestamp) for tamper detection |
| **Immutability** | Once created, USES_PROTOCOL edges are append-only. Reclassification creates new edges with LATER_CLASSIFIED_AS provenance, preserving history. |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Contract found in registry with VERIFIED completeness | 0.95 | High confidence: contract is verified and mapped to a known protocol |
| Contract found in registry with COMPLETE completeness | 0.85 | Good confidence: contract is fully registered but not independently verified |
| Contract found in registry with PARTIAL completeness | 0.65 | Moderate confidence: contract is registered but some metadata is missing |
| Contract found in registry with STUB completeness | 0.30 | Low confidence: contract was auto-registered by classifier, no human verification |
| Contract not in registry (auto-registered as UNKNOWN) | 0.0 | No confidence: contract is completely unknown, UNKNOWN_CONTRACT vertex created |
| Method selector matches known swap/deposit/borrow | +0.10 bonus | Method selector match increases confidence that the protocol attribution is correct |
| Protocol has multiple verified contracts on same chain | +0.05 bonus | Ecosystem density increases confidence in individual contract attributions |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Contract exists as auto-registered unknown. No system or protocol assignment. Only address and chain_id known. |
| `PARTIAL` | Contract assigned to a system and protocol, but missing one or more of: ABI hash, proxy type, verified flag, deployer entity. |
| `COMPLETE` | Contract has system assignment, protocol assignment, role classification, ABI hash, proxy type (if applicable), and deployer entity. |
| `VERIFIED` | All COMPLETE criteria met, plus: contract verified on block explorer (Etherscan/Basescan), protocol team has confirmed assignment, or independent audit has validated classification. |

---

## Signal 2: Wallet to App Usage

### Signal Definition

Maps a wallet's frontend activity to the applications it uses, via SDK domain events and app registry lookup.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Signal source |
| App | Registry object + vertex | Signal target (the application used) |
| Frontend Domain | Registry object + vertex | Intermediary (the domain accessed) |
| Protocol | Registry object + vertex | Associated protocol(s) behind the app |

### Source Inputs

- **Primary**: SDK events from frontend instrumentation
  - `domain`: the web domain the wallet interacted with (e.g., "app.uniswap.org")
  - `wallet_address`: connected wallet address
  - `event_type`: SDK event type (page_view, connect_wallet, sign_transaction, etc.)
  - `referrer`: HTTP referrer domain
  - `timestamp`: event timestamp
- **Secondary**: Observation batch with `domain` field populated

### Required Joins

1. `FrontendDomainRegistry.get_by_domain(domain)` — Resolve domain to registered mapping
2. `FrontendDomainRecord.app_id` → `AppRegistry.get(app_id)` — Resolve domain to its parent app
3. `FrontendDomainRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Resolve domain to associated protocol
4. `AppRecord.protocol_ids[]` → `ProtocolRegistry.get(protocol_id)` for each — Resolve app to all associated protocols

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| APP vertex | Vertex | slug, name, category |
| FRONTEND_DOMAIN vertex | Vertex | domain, verified |
| WALLET --USES_APP--> APP | Edge | event_type, timestamp, session_id |
| WALLET --TOUCHES_DOMAIN--> FRONTEND_DOMAIN | Edge | timestamp, referrer |
| APP --ASSOCIATED_WITH--> PROTOCOL | Edge | |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Profile 360** | Builds app usage profile showing which frontends a wallet prefers, session frequency, and app category distribution |
| **Population — App Cohorts** | Creates populations segmented by app usage: "MetaMask users", "1inch power users", "multi-app DeFi users" |
| **Attribution** | Maps wallet activity back to the frontend that facilitated it, enabling attribution of on-chain actions to specific app experiences |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.apps[]` — Array of app slugs with usage counts, last seen timestamp, and primary event types |
| **Population** | `population.filters.app_slug`, `population.filters.app_category` — Filter populations by app or app category |
| **Expectation** | `expectation.baselines.app_session_frequency` — Baseline on how often a wallet connects to apps. Sudden cessation or dramatic increase triggers expectation deviation. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source attribution** | `provenance.source` = "sdk_event" or "observation_batch" depending on ingestion path |
| **Domain evidence** | `provenance.evidence` includes `domain`, `referrer`, `user_agent_hash` (hashed, not raw) |
| **SDK event chain** | Multiple SDK events from same session are linked via `session_id` in provenance |
| **No PII in provenance** | SDK events strip IP addresses and user agents before storage; only hashed fingerprints retained |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Domain registered and verified in FrontendDomainRegistry | 0.95 | Domain ownership confirmed |
| Domain registered but not verified | 0.70 | Domain is in registry but ownership not independently confirmed |
| Domain not in registry, matched by pattern (e.g., *.uniswap.org) | 0.40 | Pattern match only, could be phishing domain |
| Domain not in registry, no pattern match | 0.0 | Unknown domain, no attribution possible |
| SDK event includes wallet signature proving connection | +0.10 bonus | Cryptographic proof that wallet actually connected to domain |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Domain observed but not in registry. No app or protocol attribution. |
| `PARTIAL` | Domain in registry with app assignment, but protocol association missing or unverified. |
| `COMPLETE` | Domain has app assignment, protocol association, and all metadata (category, description). |
| `VERIFIED` | COMPLETE plus domain ownership verified (DNS TXT record, protocol team confirmation, or WHOIS match). |

---

## Signal 3: Wallet to Domain Attribution

### Signal Definition

Attributes a wallet's frontend domain interactions to the protocol that the domain serves, enabling protocol-level analytics from frontend activity data.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Signal source |
| Frontend Domain | Registry object + vertex | Observed domain |
| Protocol | Registry object + vertex | Attributed protocol |
| App | Registry object + vertex | App serving the domain (optional) |

### Source Inputs

- **Primary**: SDK `page_view` events with domain and referrer
  - `domain`: the domain visited
  - `referrer`: the referring domain (for attribution chain tracking)
  - `wallet_address`: connected wallet
  - `timestamp`: event timestamp
- **Secondary**: Observation batch with `domain` field

### Required Joins

1. `FrontendDomainRegistry.get_by_domain(domain)` — Primary domain lookup
2. `FrontendDomainRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Domain to protocol
3. `FrontendDomainRecord.app_id` → `AppRegistry.get(app_id)` — Domain to app (if applicable)
4. Referrer chain: `FrontendDomainRegistry.get_by_domain(referrer)` — Attribute referral path

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| FRONTEND_DOMAIN vertex | Vertex | domain, app_id, protocol_id |
| PROTOCOL vertex | Vertex | slug, name |
| WALLET --TOUCHES_DOMAIN--> FRONTEND_DOMAIN | Edge | timestamp, referrer, event_type |
| FRONTEND_DOMAIN --FRONTS_PROTOCOL--> PROTOCOL | Edge | verified, confidence |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Profile 360** | Domain touchpoints enrich wallet profile with frontend behavior layer |
| **Frontend Analytics** | Aggregated domain attribution data powers protocol-level frontend analytics: unique wallets per domain, session duration, referral sources |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.domains[]` — Domains touched with timestamps and attributed protocols |
| **Population** | `population.filters.domain_protocol` — Segment wallets by which protocol frontends they use |
| **Expectation** | `expectation.baselines.domain_diversity` — Baseline on number of distinct protocol frontends a wallet accesses |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "sdk_page_view" |
| **Referrer chain** | Full referrer chain stored in `provenance.evidence.referrer_chain[]` |
| **Domain verification** | `provenance.evidence.domain_verified` boolean indicates if domain ownership is confirmed |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Domain in registry, verified, protocol assigned | 0.95 | Verified domain with known protocol |
| Domain in registry, unverified, protocol assigned | 0.70 | Known mapping but not independently verified |
| Domain matches known protocol pattern but not in registry | 0.35 | Heuristic match only |
| Domain unknown, no pattern match | 0.0 | Cannot attribute |
| Referrer chain confirms protocol context | +0.10 bonus | Referral from known protocol domain increases confidence |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Domain observed but not in registry |
| `PARTIAL` | Domain in registry, protocol assigned, but verification pending |
| `COMPLETE` | Domain verified, protocol and app assigned, all metadata present |
| `VERIFIED` | COMPLETE plus DNS/WHOIS verification or protocol team confirmation |

---

## Signal 4: Contract Classification

### Signal Definition

Classifies any contract address on any supported chain into its parent contract system and protocol, forming the backbone of all protocol-level intelligence.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Contract Instance | Registry object | The specific deployed contract |
| Contract System | Registry object + vertex | Logical grouping (e.g., "Uniswap V3 Core") |
| Protocol | Registry object + vertex | Parent protocol |
| Chain | Registry object + vertex | Deployment chain |

### Source Inputs

- **Primary**: Transaction `to_address` from observations
  - `to_address`: contract address
  - `chain_id`: chain identifier
- **Secondary**: Direct classification via `POST /v1/web3/classify/contract`
- **Tertiary**: Contract deployment events (for auto-registration)

### Required Joins

1. `ContractInstanceRegistry.get_by_address_chain(to_address, chain_id)` — Primary lookup
2. `ContractInstanceRecord.system_id` → `ContractSystemRegistry.get(system_id)` — Instance to system
3. `ContractSystemRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — System to protocol
4. `ContractInstanceRecord.chain_id` → `ChainRegistry.get_by_chain_id(chain_id)` — Chain context

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| CONTRACT vertex (or UNKNOWN_CONTRACT) | Vertex | address, chain_id, role |
| CONTRACT_SYSTEM vertex | Vertex | name, protocol_id |
| PROTOCOL vertex | Vertex | slug, name, family |
| CHAIN vertex | Vertex | chain_id, name |
| CONTRACT --INSTANCE_OF--> CONTRACT_SYSTEM | Edge | role, confidence |
| CONTRACT_SYSTEM --PART_OF_SYSTEM--> PROTOCOL | Edge | |
| PROTOCOL --DEPLOYED_ON--> CHAIN | Edge | |

If contract is unknown:
| UNKNOWN_CONTRACT vertex | Vertex | address, chain_id, first_seen |

If contract is later reclassified:
| UNKNOWN_CONTRACT --LATER_CLASSIFIED_AS--> CONTRACT_SYSTEM | Edge | reclassified_at, old_confidence, new_confidence |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **All Intelligence APIs** | Contract classification is the foundation for every other signal. Without it, transactions are just address-to-address transfers with no semantic meaning. Every protocol usage, app attribution, and migration detection depends on contract classification. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | Contract classification feeds into every protocol-related profile field. Not directly exposed but is a prerequisite for all protocol-level profile enrichment. |
| **Population** | Contract classification enables protocol-based segmentation. All "users of protocol X" populations depend on accurate contract classification. |
| **Expectation** | Classification accuracy feeds into expectation confidence. Low-confidence classifications produce wider expectation bands. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Classification source** | `provenance.source` records whether classification came from registry lookup, auto-registration, or manual reclassification |
| **ABI evidence** | If contract ABI is available, `provenance.evidence.abi_hash` is stored for verification |
| **Reclassification chain** | When a contract is reclassified, the full chain of classifications is preserved via LATER_CLASSIFIED_AS edges |
| **Block explorer verification** | `provenance.evidence.explorer_verified` indicates if classification was confirmed against a block explorer |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Contract in registry, VERIFIED status, ABI confirmed | 0.98 | Highest confidence: independently verified |
| Contract in registry, COMPLETE status | 0.85 | Fully registered with all metadata |
| Contract in registry, PARTIAL status | 0.60 | Registered but incomplete metadata |
| Contract in registry, STUB status (auto-registered) | 0.25 | Auto-registered, no human verification |
| Contract not in registry | 0.0 | Unknown contract, auto-registered as stub |
| Contract is a known proxy pattern pointing to verified implementation | 0.90 | Proxy resolution adds confidence |
| Multiple contracts in same system are verified | +0.05 bonus | System-level verification lifts individual contract confidence |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Address and chain_id only. Auto-registered by classifier. No system, protocol, role, or ABI information. |
| `PARTIAL` | System and protocol assigned. Role classified. But missing one or more of: ABI hash, proxy type, deployer entity, verified flag. |
| `COMPLETE` | All fields populated: system, protocol, role, ABI hash, proxy type (if applicable), deployer entity, creation block. |
| `VERIFIED` | COMPLETE plus block explorer verification, protocol team confirmation, or audit validation. |

---

## Signal 5: Token Holdings

### Signal Definition

Tracks a wallet's token balances across chains and token types, creating the foundation for wealth analysis, LTV prediction, and portfolio exposure mapping.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Token holder |
| Token | Registry object + vertex | The held token |
| Token Position | Vertex | Specific balance record |
| Chain | Registry object + vertex | Chain context |
| Protocol | Registry object + vertex | Protocol that issued the token (if applicable) |

### Source Inputs

- **Primary**: RPC balance queries via node providers
  - `wallet_address`: the holder
  - `token_address`: the token contract (or native)
  - `chain_id`: the chain
  - `balance`: raw balance value
  - `block_number`: the block at which balance was queried
- **Secondary**: Dune Datashare snapshots (bulk balance data for major tokens)
- **Tertiary**: Transfer event logs (incremental balance tracking)

### Required Joins

1. `TokenRegistry.get_by_address_chain(token_address, chain_id)` — Resolve token metadata
2. `TokenRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Token to issuing protocol
3. `ChainRegistry.get_by_chain_id(chain_id)` — Chain context for native tokens
4. Price feed join (CoinGecko/DeFiLlama) for USD valuation

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| TOKEN vertex | Vertex | address, chain_id, symbol, standard |
| TOKEN_POSITION vertex | Vertex | balance, block_number, usd_value |
| WALLET --HOLDS_TOKEN--> TOKEN | Edge | balance, usd_value, last_updated |
| WALLET --HAS_POSITION--> TOKEN_POSITION | Edge | |
| TOKEN --TOKEN_OF--> PROTOCOL | Edge | (if token issued by known protocol) |
| WALLET --EXPOSED_TO--> TOKEN | Edge | exposure_usd, percentage_of_portfolio |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Profile 360** | Token holdings form the portfolio section of wallet profiles. Shows token diversity, concentration, stablecoin ratio, and total portfolio value. |
| **LTV Prediction** | Token holdings (especially liquid, high-market-cap tokens) are primary inputs to loan-to-value prediction models. Stablecoin holdings indicate lower risk profiles. |
| **Population — Wealth Tiers** | Wallets segmented into wealth tiers based on total holdings USD value. Enables populations like "whale wallets (>$1M)", "retail wallets (<$10K)". |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.tokens[]` — Array of token holdings with symbol, balance, USD value, chain, and percentage of portfolio. `profile.web3.portfolio_value_usd` — Total portfolio value. |
| **Population** | `population.filters.token_symbol`, `population.filters.portfolio_value_range`, `population.filters.stablecoin_ratio` — Segment by specific token, portfolio size, or stablecoin allocation. |
| **Expectation** | `expectation.baselines.portfolio_value`, `expectation.baselines.token_diversity` — Baselines on portfolio value and number of distinct tokens held. Sudden large drawdowns or concentration shifts trigger deviations. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "rpc_query", "dune_snapshot", or "transfer_event" |
| **Block evidence** | `provenance.evidence.block_number` and `provenance.evidence.block_hash` for point-in-time verification |
| **Staleness tracking** | `provenance.observed_at` tracks when balance was last confirmed. Balances older than configurable threshold are marked stale. |
| **Price source** | `provenance.evidence.price_source` and `provenance.evidence.price_timestamp` for USD valuation provenance |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Direct RPC balance query at recent block | 0.95 | Real-time on-chain data |
| Dune snapshot (daily) | 0.85 | High quality but up to 24h stale |
| Transfer event derived (cumulative) | 0.70 | Cumulative calculation may miss edge cases (internal transfers, rebasing tokens) |
| Token in registry with full metadata | +0.05 bonus | Known token increases confidence in balance interpretation |
| Balance is zero (confirmed) | 0.99 | Zero balances are easy to verify |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Token address observed in transaction but not in registry. Balance unknown. |
| `PARTIAL` | Token in registry with symbol and decimals. Balance queried but USD value unavailable (no price feed). |
| `COMPLETE` | Token fully registered, balance confirmed, USD value calculated, price source documented. |
| `VERIFIED` | COMPLETE plus balance cross-verified between two independent sources (e.g., RPC + Dune). |

---

## Signal 6: Governance Participation

### Signal Definition

Tracks a wallet's participation in protocol governance through voting, delegation, and proposal creation across on-chain and off-chain governance platforms.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Governance participant |
| Governance Space | Registry object + vertex | The governance forum |
| Governance Proposal | Vertex | Specific proposal voted on |
| Protocol | Registry object + vertex | The governed protocol |

### Source Inputs

- **Primary**: Snapshot API (off-chain votes)
  - `voter_address`: wallet that voted
  - `space_id`: Snapshot space identifier
  - `proposal_id`: proposal voted on
  - `choice`: vote choice
  - `voting_power`: voting power at snapshot block
  - `timestamp`: vote timestamp
- **Secondary**: On-chain vote events (Governor contracts)
  - `voter`: wallet address
  - `proposalId`: on-chain proposal ID
  - `support`: vote direction
  - `weight`: voting weight
  - Method selectors: `castVote` (0x56781388), `castVoteWithReason` (0x15373e3d)
- **Tertiary**: Delegation events
  - `delegator`: wallet delegating
  - `delegatee`: wallet receiving delegation
  - Method selector: `delegate` (0x5c19a95c)

### Required Joins

1. `GovernanceSpaceRegistry.get_by_space_id(space_id)` — Resolve space metadata
2. `GovernanceSpaceRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Space to protocol
3. For on-chain votes: `ContractInstanceRegistry.get_by_address_chain(governor_address, chain_id)` — Resolve governor contract to protocol

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| GOVERNANCE_SPACE vertex | Vertex | space_id, name, platform |
| GOVERNANCE_PROPOSAL vertex | Vertex | proposal_id, space_id, title, status |
| PROTOCOL vertex | Vertex | slug, name |
| WALLET --PARTICIPATES_IN--> GOVERNANCE_SPACE | Edge | first_vote, last_vote, vote_count |
| WALLET --VOTES_ON--> GOVERNANCE_PROPOSAL | Edge | choice, voting_power, timestamp |
| WALLET --DELEGATES_TO--> WALLET | Edge | token_address, delegation_amount, timestamp |
| PROTOCOL --GOVERNED_BY_SPACE--> GOVERNANCE_SPACE | Edge | platform, chain_id |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Profile 360** | Governance participation section shows which DAOs a wallet participates in, voting frequency, delegation status, and proposal creation history |
| **Community Populations** | Wallets segmented by governance activity level: active voters, delegates, proposal creators, passive holders |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.governance[]` — Array of governance spaces with vote count, last vote timestamp, delegation status, and voting power. `profile.web3.governance_score` — Aggregate governance activity score. |
| **Population** | `population.filters.governance_space`, `population.filters.governance_activity_level` — Segment by specific DAO or by activity level (active, occasional, passive, delegate). |
| **Expectation** | `expectation.baselines.governance_voting_regularity` — Baseline on voting frequency per governance cycle. Active voters who stop voting trigger expectation deviation. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "snapshot_api", "on_chain_vote_event", or "delegation_event" |
| **Vote evidence** | For Snapshot: `provenance.evidence.ipfs_hash` (Snapshot stores votes on IPFS). For on-chain: `provenance.evidence.tx_hash` and `provenance.evidence.log_index`. |
| **Delegation chain** | Full delegation chain tracked: if A delegates to B who delegates to C, all links are recorded |
| **Voting power snapshot** | `provenance.evidence.snapshot_block` records the block at which voting power was calculated |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| On-chain vote via verified governor contract | 0.98 | Cryptographically verifiable on-chain action |
| Snapshot vote with IPFS proof | 0.90 | Off-chain but cryptographically signed and IPFS-anchored |
| Snapshot vote without IPFS verification | 0.70 | Signed but not independently verified |
| Governance space in registry, verified | +0.05 bonus | Known governance space increases confidence |
| Delegation event on-chain | 0.95 | Verifiable on-chain delegation |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Governance space observed (e.g., from vote event) but not in registry. No protocol association. |
| `PARTIAL` | Space in registry with protocol assignment. Vote data available but voting power not yet resolved. |
| `COMPLETE` | Space fully registered, all votes tracked with voting power, delegation graph resolved, proposal metadata available. |
| `VERIFIED` | COMPLETE plus cross-verification between Snapshot API and on-chain records where both exist. |

---

## Signal 7: Bridge Activity

### Signal Definition

Tracks a wallet's cross-chain bridging activity, mapping bridge usage to specific bridge protocols and routes for cross-chain identity resolution and chain exposure analysis.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | Bridge user |
| Bridge Route | Registry object + vertex | The specific bridge path used |
| Protocol | Registry object + vertex | The bridge protocol |
| Chain (source) | Registry object + vertex | Origin chain |
| Chain (destination) | Registry object + vertex | Destination chain |

### Source Inputs

- **Primary**: Transaction observations to known bridge contracts
  - `wallet_address`: the bridging wallet
  - `to_address`: bridge contract address
  - `chain_id`: source chain
  - `method_selector`: bridge method (mapped to BRIDGE_SEND or BRIDGE_RECEIVE)
  - `value`: amount bridged
  - `tx_hash`: source chain transaction hash
- **Secondary**: Bridge protocol event logs (deposit/withdrawal events)
- **Tertiary**: Destination chain receive transactions (for completing bridge tracking)

### Required Joins

1. `ContractInstanceRegistry.get_by_address_chain(to_address, chain_id)` — Resolve bridge contract
2. Contract instance → system → protocol (standard classification chain)
3. `BridgeRouteRegistry.find_route(protocol_id, source_chain_id, dest_chain_id)` — Resolve specific bridge route
4. `ChainRegistry.get_by_chain_id(source_chain_id)` and `ChainRegistry.get_by_chain_id(dest_chain_id)` — Chain context

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| BRIDGE_ROUTE vertex | Vertex | protocol_id, source_chain, dest_chain |
| PROTOCOL vertex | Vertex | slug, name (bridge protocol) |
| CHAIN vertices (2) | Vertex | source and destination chains |
| WALLET --BRIDGES_VIA--> BRIDGE_ROUTE | Edge | amount, token, tx_hash, timestamp |
| WALLET --USES_PROTOCOL--> PROTOCOL | Edge | canonical_action=BRIDGE_SEND or BRIDGE_RECEIVE |
| BRIDGE_ROUTE --DEPLOYED_ON--> CHAIN | Edge | (for source chain) |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Cross-Chain Identity** | Bridge events are primary signals for linking wallet addresses across chains. Same wallet bridging from Chain A to Chain B establishes cross-chain identity relationship. |
| **Profile 360 — Chain Exposure** | Bridge activity reveals which chains a wallet is active on and how it moves assets between them. Builds chain exposure vector in profile. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.bridge_activity[]` — Array of bridge events with source/dest chain, protocol, amount, and timestamp. `profile.web3.chain_exposure[]` — Derived chain exposure from bridge + direct chain activity. |
| **Population** | `population.filters.bridge_protocol`, `population.filters.active_chains_count` — Segment by bridge protocol used or number of active chains. |
| **Expectation** | `expectation.baselines.bridge_frequency`, `expectation.baselines.bridge_volume` — Baselines on how often and how much a wallet bridges. Sudden large bridge events or new chain exposure triggers deviation. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "observation_batch" or "bridge_event_log" |
| **Cross-chain evidence** | `provenance.evidence` includes both source `tx_hash` and destination `tx_hash` when available |
| **Amount verification** | `provenance.evidence.amount` and `provenance.evidence.token` for bridge value tracking |
| **Route verification** | `provenance.evidence.bridge_route_id` links to specific BridgeRouteRecord |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Bridge contract verified, both source and dest tx confirmed | 0.95 | Full round-trip verification |
| Bridge contract verified, source tx only | 0.80 | Source confirmed but destination pending |
| Bridge contract in registry but PARTIAL completeness | 0.60 | Known bridge but incomplete metadata |
| Transaction to unknown contract classified as bridge by method selector | 0.35 | Method selector match only |
| Destination chain receive cannot be correlated | -0.15 penalty | Incomplete bridge tracking reduces confidence |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Bridge contract observed but not in registry. Route unknown. |
| `PARTIAL` | Bridge contract classified, protocol known, but route (source/dest chain pair) not yet registered. Or destination transaction not yet correlated. |
| `COMPLETE` | Full bridge event: source tx confirmed, bridge contract classified, route registered, destination tx correlated, amount and token documented. |
| `VERIFIED` | COMPLETE plus cross-verified between source chain event logs and destination chain receive logs. |

---

## Signal 8: Protocol Migration

### Signal Definition

Detects and tracks when a protocol deploys new contract versions, migrates to new chains, or undergoes governance-driven migration events. Preserves historical edges while creating succession links.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Contract (old) | Registry object + vertex | The deprecated contract |
| Contract (new) | Registry object + vertex | The successor contract |
| Protocol Version (old) | Vertex | Previous protocol version |
| Protocol Version (new) | Vertex | New protocol version |
| Deployer Entity | Registry object + vertex | The deployer (used for same-deployer detection) |
| Migration Record | Registry object | The migration event record |

### Source Inputs

- **Primary**: Deploy events (`CREATE` / `CREATE2` opcodes) detected on-chain
  - `deployer_address`: the address that deployed the new contract
  - `new_contract_address`: the newly deployed contract
  - `chain_id`: deployment chain
  - `block_number`: deployment block
- **Secondary**: Same-deployer detection via `detect_migration()` in classifier.py
- **Tertiary**: Manual migration recording via `POST /v1/web3/migrations`

### Required Joins

1. `DeployerEntityRegistry.get_by_address_chain(deployer_address, chain_id)` — Identify the deployer
2. `DeployerEntityRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Deployer to protocol
3. `ContractInstanceRegistry.list_by_system(system_id)` — Find all contracts in the same system
4. Compare deployment timestamps to detect succession pattern

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| CONTRACT vertex (old) | Vertex | address, chain_id, status=MIGRATED |
| CONTRACT vertex (new) | Vertex | address, chain_id, status=ACTIVE |
| PROTOCOL_VERSION vertex (old) | Vertex | version, deprecated_at |
| PROTOCOL_VERSION vertex (new) | Vertex | version, deployed_at |
| CONTRACT --MIGRATED_TO--> CONTRACT | Edge | migration_type, detected_at, evidence |
| PROTOCOL_VERSION --SUCCESSOR_OF--> PROTOCOL_VERSION | Edge | migration_type |
| DEPLOYER_ENTITY --CONTROLS--> CONTRACT (new) | Edge | deployed_at |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Migration Tracking API** | `GET /v1/web3/migrations` exposes migration history. Downstream systems can query for recent migrations to update their contract references. |
| **Historical Edge Rebinding** | When a contract is migrated, historical USES_PROTOCOL edges pointing to the old contract system are annotated with MIGRATED_TO links. New observations are routed to the new contract system. Graph queries can traverse migration chains. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.migration_exposure[]` — Tracks which protocol migrations a wallet has been affected by (e.g., wallet used Uniswap V2, Uniswap V3 deployed, wallet has not yet migrated). |
| **Population** | `population.filters.migrated_protocol`, `population.filters.migration_status` — Segment wallets by whether they have migrated to new protocol versions or remain on deprecated versions. |
| **Expectation** | `expectation.triggers.protocol_migration` — Migration events can trigger expectation recalculation for affected wallets. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "deploy_event", "same_deployer_detection", or "manual" |
| **Deploy evidence** | `provenance.evidence` includes `deployer_address`, `creation_tx_hash`, `block_number` for the new contract |
| **Succession chain** | Full succession chain preserved: V1 → V2 → V3, each link carrying its own provenance |
| **Detection method** | `provenance.evidence.detection_method` = "same_deployer", "proxy_upgrade", "governance_proposal", or "manual" |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Same deployer deploys new contract in same system, old contract deprecated | 0.90 | Strong migration signal |
| Proxy upgrade detected (implementation address changed) | 0.95 | On-chain proxy upgrade is definitive |
| Governance proposal references migration | 0.85 | Governance context supports migration interpretation |
| Same deployer, new contract, but old contract still active | 0.50 | Could be migration or parallel deployment |
| Manual migration recording | 0.80 | Human judgment, may lack on-chain evidence |
| Different deployer but same protocol team (verified) | 0.70 | Multisig or key rotation may change deployer |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Migration suspected (same deployer, new contract) but not confirmed. Old and new contracts identified but succession not verified. |
| `PARTIAL` | Migration confirmed. Old and new contracts linked. But migration type not classified or governance evidence not attached. |
| `COMPLETE` | Full migration record: type classified, old and new contracts linked, deployer entity identified, governance evidence (if applicable) attached, affected wallet count estimated. |
| `VERIFIED` | COMPLETE plus migration confirmed by protocol team, governance vote, or independent audit. Historical edges rebinding completed. |

---

## Signal 9: CEX-DEX Transition

### Signal Definition

Detects behavioral transitions between centralized exchange (CEX) and decentralized exchange (DEX) usage, combining the behavioral `cex_dex_transition` signal with the venue registry for graph-level attribution.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Wallet | Identity vertex | The transitioning user |
| Market Venue (CEX) | Registry object + vertex | Centralized exchange |
| Market Venue (DEX) | Registry object + vertex | Decentralized exchange |
| Market | Vertex | Specific trading pair/market |

### Source Inputs

- **Primary**: Behavioral engine `cex_dex_transition` signal
  - `wallet_address`: the wallet exhibiting transition behavior
  - `transition_direction`: CEX_TO_DEX or DEX_TO_CEX
  - `cex_venue_slug`: identified CEX (e.g., "binance", "coinbase")
  - `dex_protocol_slug`: identified DEX protocol (e.g., "uniswap", "curve")
  - `confidence`: behavioral model confidence
  - `evidence_window`: time period over which transition was detected
- **Secondary**: Venue registry enrichment
  - Direct CEX deposit/withdrawal address matching
  - On-chain DEX swap observations
- **Tertiary**: Exchange API data (if available) for CEX trade confirmation

### Required Joins

1. `MarketVenueRegistry.get_by_slug(cex_venue_slug)` — Resolve CEX venue metadata
2. `MarketVenueRegistry.get_by_slug(dex_venue_slug)` or `ProtocolRegistry.get_by_slug(dex_protocol_slug)` — Resolve DEX venue/protocol
3. Behavioral signal join: `cex_dex_transition` signal from behavioral engine provides the transition detection
4. Historical trade pattern analysis: compare CEX withdrawal patterns with DEX swap patterns over time

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| WALLET vertex | Vertex | address |
| MARKET_VENUE vertex (CEX) | Vertex | slug, name, venue_type=CEX |
| MARKET_VENUE vertex (DEX) | Vertex | slug, name, venue_type=DEX |
| WALLET --TRADED_ON_VENUE--> MARKET_VENUE (CEX) | Edge | first_seen, last_seen, estimated_volume |
| WALLET --TRADED_ON_VENUE--> MARKET_VENUE (DEX) | Edge | first_seen, last_seen, tx_count |
| WALLET --TRADED_ON--> MARKET | Edge | pair, venue_id, timestamp |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Behavioral Engines** | CEX-DEX transition is a first-class behavioral signal indicating evolving user sophistication, risk appetite change, or regulatory response. Feeds into behavioral clustering models. |
| **Fraud Detection** | Rapid CEX-to-DEX transitions (especially after large CEX withdrawals) can indicate fund obfuscation attempts. Combined with bridge activity, forms a key fraud detection feature. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.venue_usage[]` — Array of market venues used with type (CEX/DEX), first/last seen, and estimated activity level. `profile.behavioral.cex_dex_transition` — Transition direction and timeline. |
| **Population** | `population.filters.venue_type_preference`, `population.filters.transition_direction` — Segment wallets by venue preference (CEX-heavy, DEX-heavy, mixed) or by transition direction. |
| **Expectation** | `expectation.baselines.venue_type_ratio` — Baseline ratio of CEX vs DEX activity. Sudden shift triggers expectation deviation. `expectation.triggers.cex_dex_transition` — Transition event itself is an expectation trigger. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "behavioral_engine" for transition detection, "observation_batch" for individual venue interactions |
| **Behavioral evidence** | `provenance.evidence.behavioral_model_version`, `provenance.evidence.evidence_window_start`, `provenance.evidence.evidence_window_end` |
| **CEX attribution** | `provenance.evidence.cex_attribution_method` = "known_deposit_address", "withdrawal_pattern", or "exchange_api" |
| **DEX attribution** | `provenance.evidence.dex_tx_hashes[]` — List of on-chain DEX transactions supporting the attribution |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| CEX identified by known deposit address + DEX swaps on-chain | 0.90 | Strong evidence on both sides |
| CEX identified by withdrawal pattern (heuristic) + DEX swaps on-chain | 0.70 | CEX side is heuristic |
| Behavioral model confidence > 0.8 with supporting on-chain data | 0.80 | High-confidence behavioral detection with evidence |
| Behavioral model confidence 0.5-0.8 | 0.55 | Moderate behavioral signal |
| CEX or DEX venue not in registry | -0.15 penalty | Unknown venue reduces overall confidence |
| Multiple independent signals agree on transition | +0.10 bonus | Convergent evidence increases confidence |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Transition detected by behavioral model but venues not yet identified or confirmed. |
| `PARTIAL` | Transition detected, at least one venue (CEX or DEX) identified and in registry, but the other side is unconfirmed. |
| `COMPLETE` | Both CEX and DEX venues identified, in registry, transition direction confirmed, evidence window documented, supporting transaction hashes available. |
| `VERIFIED` | COMPLETE plus independent verification (e.g., CEX API confirmation, multiple behavioral model agreement, cross-reference with known exchange deposit addresses). |

---

## Signal 10: Deployer Entity Attribution

### Signal Definition

Attributes contract deployment transactions to known deployer entities (protocol teams, DAOs, factory contracts, or individuals), establishing the control relationship between deployers and the contracts they deploy.

### Object Types

| Object | Type | Role |
|--------|------|------|
| Deployer Entity | Registry object + vertex | The entity that deployed the contract |
| Contract | Registry object + vertex | The deployed contract |
| Protocol | Registry object + vertex | The protocol the deployer is associated with |
| Chain | Registry object + vertex | Deployment chain |

### Source Inputs

- **Primary**: Deploy transaction `from_address`
  - `deployer_address`: the address that sent the deployment transaction
  - `contract_address`: the newly deployed contract address
  - `chain_id`: deployment chain
  - `tx_hash`: deployment transaction hash
  - `block_number`: deployment block
- **Secondary**: Deployer registry lookup (for known protocol team addresses)
- **Tertiary**: Factory contract detection (contracts deployed by other contracts)

### Required Joins

1. `DeployerEntityRegistry.get_by_address_chain(deployer_address, chain_id)` — Identify the deployer
2. `DeployerEntityRecord.protocol_id` → `ProtocolRegistry.get(protocol_id)` — Deployer to protocol
3. `ContractInstanceRegistry.get_by_address_chain(contract_address, chain_id)` — Resolve the deployed contract
4. If deployer is a contract itself: `ContractInstanceRegistry.get_by_address_chain(deployer_address, chain_id)` — Check if deployer is a factory

### Graph Objects Created

| Object | Type | Properties |
|--------|------|-----------|
| DEPLOYER_ENTITY vertex | Vertex | address, chain_id, entity_type, protocol_id, label |
| CONTRACT vertex | Vertex | address, chain_id |
| PROTOCOL vertex | Vertex | slug, name |
| DEPLOYER_ENTITY --CONTROLS--> CONTRACT | Edge | deployed_at, tx_hash, block_number |
| CONTRACT --INSTANCE_OF--> CONTRACT_SYSTEM | Edge | role (inferred from deployer context) |
| CONTRACT_SYSTEM --PART_OF_SYSTEM--> PROTOCOL | Edge | (via deployer's protocol association) |

### Downstream Model Consumers

| Consumer | How Signal Is Used |
|----------|-------------------|
| **Protocol Trust** | Deployer attribution establishes the trust chain for a contract. Contracts deployed by verified protocol team addresses inherit protocol trust. Contracts deployed by unknown addresses start with zero trust. |
| **Contract Risk Scoring** | Deployer entity type is a primary input to contract risk scoring. PROTOCOL_TEAM and DAO deployers indicate lower risk. UNKNOWN deployers indicate higher risk. FACTORY_CONTRACT deployers inherit the factory's trust level. |

### Profile/Population/Expectation Consumers

| Layer | Consumption Pattern |
|-------|-------------------|
| **Profile** | `profile.web3.deployer_exposure[]` — For wallets that deploy contracts, tracks their deployment history and associated protocols. For all wallets, the deployer attribution of contracts they interact with feeds into risk exposure calculations. |
| **Population** | `population.filters.contract_deployer_type` — Segment wallets by the deployer entity types of the contracts they interact with. "Wallets that only interact with PROTOCOL_TEAM-deployed contracts" vs "wallets that interact with UNKNOWN-deployed contracts." |
| **Expectation** | `expectation.triggers.new_deployer_interaction` — Wallet interacting with contracts from a previously unseen deployer entity triggers expectation evaluation. |

### Provenance Rules

| Rule | Description |
|------|-------------|
| **Source** | `provenance.source` = "deploy_tx_analysis", "factory_detection", or "manual_registration" |
| **Deployment evidence** | `provenance.evidence` includes `deployer_address`, `creation_tx_hash`, `block_number`, `chain_id`, `bytecode_hash` |
| **Factory chain** | If deployed by a factory contract, `provenance.evidence.factory_address` and `provenance.evidence.factory_protocol_id` are recorded |
| **Label source** | `provenance.evidence.label_source` records where the deployer label came from (etherscan, manual, protocol registry) |
| **Multi-sig detection** | `provenance.evidence.is_multisig` boolean, `provenance.evidence.multisig_type` (e.g., "gnosis_safe") |

### Confidence Rules

| Condition | Confidence | Rationale |
|-----------|-----------|-----------|
| Deployer in registry, entity_type=PROTOCOL_TEAM, protocol verified | 0.95 | Known protocol team deployer |
| Deployer in registry, entity_type=DAO, verified multisig | 0.90 | Verified DAO deployment |
| Deployer in registry, entity_type=FACTORY_CONTRACT, factory is verified | 0.85 | Known factory contract pattern |
| Deployer in registry, entity_type=INDIVIDUAL, protocol association | 0.70 | Individual deployer with protocol association |
| Deployer in registry, entity_type=UNKNOWN | 0.30 | Registered but unclassified deployer |
| Deployer not in registry | 0.0 | Completely unknown deployer, auto-registered as stub |
| Deployer address matches known multisig pattern (Gnosis Safe) | +0.10 bonus | Multisig deployment indicates organizational control |
| Multiple contracts from same deployer all classified to same protocol | +0.05 bonus | Consistent deployment pattern increases confidence |

### Completeness Status Rules

| Status | Criteria |
|--------|----------|
| `STUB` | Deployer address observed from deployment transaction. Not in registry. No entity type, protocol, or label assigned. |
| `PARTIAL` | Deployer in registry with entity type assigned. Protocol association present. But missing one or more of: label, multisig detection, full deployment history. |
| `COMPLETE` | Deployer fully registered: entity type, protocol association, label, multisig status, complete deployment history (all contracts deployed by this address tracked). |
| `VERIFIED` | COMPLETE plus deployer identity independently verified (Etherscan label, protocol team confirmation, ENS name resolution, or governance proposal linking deployer to protocol). |

---

## Cross-Signal Dependencies

The following diagram shows how signals depend on each other:

```
Signal 4 (Contract Classification)
  └── Foundation for Signal 1 (Wallet → Protocol Usage)
  └── Foundation for Signal 7 (Bridge Activity)
  └── Foundation for Signal 9 (CEX-DEX Transition, DEX side)
  └── Foundation for Signal 10 (Deployer Entity Attribution)

Signal 10 (Deployer Entity Attribution)
  └── Feeds into Signal 8 (Protocol Migration, same-deployer detection)
  └── Feeds into Signal 4 (Contract Classification, trust level)

Signal 1 (Wallet → Protocol Usage)
  └── Feeds into Signal 6 (Governance Participation, protocol context)
  └── Feeds into Signal 9 (CEX-DEX Transition, DEX side)

Signal 2 (Wallet → App Usage)
  └── Feeds into Signal 3 (Wallet → Domain Attribution, app context)

Signal 3 (Wallet → Domain Attribution)
  └── Feeds into Signal 2 (Wallet → App Usage, protocol resolution)

Signal 5 (Token Holdings)
  └── Feeds into Signal 6 (Governance Participation, voting power)
  └── Feeds into Signal 7 (Bridge Activity, bridged amount valuation)

Signal 8 (Protocol Migration)
  └── Feeds back into Signal 4 (Contract Classification, successor resolution)
  └── Feeds back into Signal 1 (Wallet → Protocol Usage, edge rebinding)
```

---

## Aggregate Coverage Metrics

The `/v1/web3/coverage` endpoint returns aggregate metrics across all signals:

| Metric | Description |
|--------|-------------|
| `total_chains` | Number of registered chains |
| `total_protocols` | Number of registered protocols |
| `total_contract_instances` | Number of registered contract instances |
| `total_tokens` | Number of registered tokens |
| `total_apps` | Number of registered apps |
| `total_domains` | Number of registered frontend domains |
| `total_governance_spaces` | Number of registered governance spaces |
| `total_market_venues` | Number of registered market venues |
| `total_bridge_routes` | Number of registered bridge routes |
| `total_deployer_entities` | Number of registered deployer entities |
| `total_migrations` | Number of recorded migration events |
| `total_observations_processed` | Total observations ingested and classified |
| `completeness_breakdown` | Per-registry breakdown by CompletenessStatus (STUB/PARTIAL/COMPLETE/VERIFIED counts) |
| `classification_hit_rate` | Percentage of observations where contract was found in registry (not auto-registered as UNKNOWN) |
| `domain_attribution_rate` | Percentage of domain observations successfully attributed to an app or protocol |
