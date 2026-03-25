# Aether Web3 Coverage Audit

**Date:** 2026-03-25
**Scope:** Full-stack Web3 surface analysis across SDK, backend, graph, lake, providers, and intelligence layers
**Method:** Line-by-line repository inspection against Web3-native requirements
**Verdict:** Strong foundational infrastructure; missing the ontology/registry layer that would make it a Web3-native intelligence platform rather than a Web3-aware analytics tool

---

## 1. Current Architecture Inventory (Repo-Truth)

### Aggregate Counts

| Dimension | Count | Source Files |
|-----------|-------|-------------|
| Backend services (Python/FastAPI) | 29 routers | `Backend Architecture/aether-backend/routes.py`, service modules |
| API endpoints | 184 | Route registrations across all services |
| Provider adapters | 24 | `PROVIDER_MATRIX.md`, `shared/providers/` |
| Graph vertex types | 18 | `shared/graph/graph.py` VertexType enum + extended enums |
| Graph edge types | 33 | EdgeType enum across 4 layers (H2H, H2A, A2H, A2A) |
| SDK VM providers | 7 | `packages/web/src/web3/providers/` |
| SDK VM trackers | 7 | `packages/web/src/web3/tracking/` |
| Lake domains | 6 | market, onchain, social, identity, governance, tradfi |
| ML models | 11 | Intent, Bot, Session, Identity, Journey, Churn, LTV, Anomaly, Attribution, Bytecode Risk, Trust Score |
| Smart contract targets | 6 | EVM Solidity (2 contracts), Solana, SUI (Move), NEAR, Cosmos |

### Web3 SDK Layer (packages/web/src/web3/)

The SDK is a **Tier 2 thin client** by design. It detects wallets, ships raw events, and defers all classification to the backend.

**Providers implemented (7 VM families):**
- `evm-provider.ts` -- EIP-6963 multi-provider discovery + legacy `window.ethereum` fallback
- `svm-provider.ts` -- Solana wallet adapter detection (Phantom, Solflare, Backpack, Glow)
- `bitcoin-provider.ts` -- UniSat, Xverse, Leather, OKX Bitcoin wallet detection
- `move-provider.ts` -- Sui Wallet Standard, Martian, Ethos detection
- `near-provider.ts` -- NEAR Wallet Selector integration
- `tron-provider.ts` -- TronLink, TronWallet detection
- `cosmos-provider.ts` -- Keplr, Leap, Cosmostation detection

**EVM wallet types detected (12):** MetaMask, Coinbase, Brave, Rabby, Rainbow, Trust, Frame, Zerion, OKX, Ledger, Trezor, GridPlus

**EIP-6963 support:** Full. The EVM provider dispatches `eip6963:requestProvider` and listens for `eip6963:announceProvider` custom events, handling multi-wallet scenarios where users have multiple browser extensions active simultaneously.

**Method selector classifications (16):** transfer, swap, stake, mint, approve, custom, plus DeFi-specific selectors parsed from transaction data on the backend side.

**What the SDK does NOT do (by design):**
- No DeFi protocol classification at the client layer
- No portfolio aggregation
- No token balance resolution
- No wallet scoring or classification
- No chain registry or canonical chain ID resolution

### Backend Web3 Service (Backend Architecture/services/web3/)

**Files:** `web3_models.py`, `web3_service.py`, `web3_queries.py`

**9 API endpoints:**
1. `GET /v1/web3/wallets/{project_id}` -- Tracked wallets with classification and activity
2. `GET /v1/web3/chains/{project_id}` -- Chain distribution and volume
3. `GET /v1/web3/transactions/{project_id}` -- Multi-VM transaction history
4. `GET /v1/web3/defi/{project_id}` -- DeFi interaction analytics
5. `GET /v1/web3/portfolio/{project_id}/{user_id}` -- Cross-chain portfolio per user
6. `GET /v1/web3/whales/{project_id}` -- Whale activity feed
7. `GET /v1/web3/bridges/{project_id}` -- Bridge transaction tracking
8. `GET /v1/web3/exchanges/{project_id}` -- CEX deposit/withdrawal flows
9. `GET /v1/web3/perpetuals/{project_id}` -- Perpetuals/derivatives activity

**Enums defined in `web3_models.py`:**
- `VMType`: evm, svm, bitcoin, movevm, near, tvm, cosmos (7 values)
- `WalletClassification`: hot, cold, smart, exchange, protocol, multisig (6 values)
- `DeFiCategory`: dex, router, lending, staking, restaking, perpetuals, options, bridge, cex, yield, nft_marketplace, governance, payments, insurance, launchpad (15 values)

**Query engine status:** ClickHouse SQL templates are defined as docstrings. All query methods currently return empty lists (`return []`). The query shapes are correct but execution is not wired.

### On-Chain Action Recording

**6 action types:** DEPLOY, CALL, TRANSFER, UPGRADE, PAUSE, DESTROY
**7 VM targets:** EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos

Smart contract deployment targets exist in `Smart Contracts/`:
- EVM: `AnalyticsRewards.sol`, `RewardRegistry.sol` (Solidity)
- Solana: `Smart Contracts/programs/solana/`
- SUI: `Smart Contracts/programs/sui/` (Move)
- NEAR: `Smart Contracts/programs/near/`
- Cosmos: `Smart Contracts/programs/cosmos/`

### Oracle

Multi-chain proof signing for 7 VMs using secp256k1 ECDSA. Proofs are generated server-side and verified on-chain by the respective smart contracts.

### Graph Layer

**Infrastructure:** Neptune (production) via gremlinpython, in-memory fallback (local development)
**Vertex types (18):** USER, SESSION, PAGE_VIEW, EVENT, DEVICE, COMPANY, CAMPAIGN, EXTERNAL_DATA, DEVICE_FINGERPRINT, IP_ADDRESS, LOCATION, EMAIL, PHONE, WALLET, IDENTITY_CLUSTER, AGENT, SERVICE, CONTRACT, PROTOCOL, PAYMENT, ACTION_RECORD
**Edge layers:** H2H (human-to-human), H2A (human-to-agent), A2H (agent-to-human), A2A (agent-to-agent)
**Edge types:** 33 across 4 layers including HAS_SESSION, VIEWED_PAGE, TRIGGERED_EVENT, USED_DEVICE, BELONGS_TO, ATTRIBUTED_TO, RESOLVED_AS, ENRICHED_BY, and Web3-specific edges

### Data Lake

**Architecture:** Bronze/Silver/Gold medallion tiers
**6 domains:** market, onchain, social, identity, governance, tradfi
**Implementation:** Real ETL scheduler in `Data Lake Architecture/aether-Datalake-backend/`, TypeScript-based pipeline orchestration with S3 integration

### Provider Ecosystem (24 Adapters)

| Category | Providers | Status |
|----------|-----------|--------|
| Blockchain RPC | QuickNode, Alchemy, Infura, GenericRPC | Implemented |
| Block Explorer | Etherscan, Moralis | Implemented |
| Analytics | Dune Analytics | Implemented |
| Market Data | DeFiLlama, CoinGecko, Binance, Coinbase | Implemented |
| Identity | ENS, GitHub | Implemented |
| Governance | Snapshot | Implemented |
| Web3 Social | Farcaster, Lens Protocol | Implemented |
| On-chain Intel | Chainalysis, Nansen | Implemented |
| Social (Web2) | Twitter/X, Reddit | Implemented |
| Prediction Markets | Polymarket, Kalshi | Implemented |
| TradFi Data | Massive, Databento | Implemented |

All adapters extend a common `Provider` base class with `execute()` and `health_check()` methods, using real httpx HTTP calls.

### Behavioral Signals

**10 signal families** including Web3-aware signals:
- `wallet_friction` -- time from page load to wallet connection, failed connection attempts
- `cex_dex_transition` -- behavioral patterns when users move between centralized and decentralized exchange interactions
- `social_chain_lag` -- delay between social engagement (Farcaster/Lens activity) and on-chain actions

### Fraud Detection

- Sybil detection (graph-based identity clustering)
- Wallet age scoring
- Mixer/tumbler detection
- Velocity scoring (transaction frequency anomalies)
- Bytecode risk scoring (rule-based contract analysis)

### Profile 360

Unified user profile that includes wallet identifiers, graph context, lake data aggregation, and composite risk scoring. Profile merges on-chain identity (wallet addresses, ENS) with off-chain identity (email, phone, device fingerprints) through the IDENTITY_CLUSTER graph vertex.

### RWA Intelligence Graph

- 14 asset classes
- 8 chain targets
- Policy simulation engine
- Exposure graph (risk propagation across linked entities)
- Feature-flagged (7 flags, all default false)

---

## 2. What Already Works and Must Not Be Rebuilt

These subsystems are production-ready or architecturally sound. Rebuilding them would be destructive.

| Subsystem | Why It Must Not Be Rebuilt | Evidence |
|-----------|---------------------------|----------|
| SDK wallet providers (7 VMs) | Comprehensive multi-chain detection with EIP-6963, correct thin-client architecture | `packages/web/src/web3/providers/*.ts` |
| On-chain action recording | 6 action types across 7 VMs, smart contracts deployed | `Smart Contracts/`, backend action types |
| Oracle signing | Multi-chain secp256k1 ECDSA proof generation and verification | Oracle service + contract verifiers |
| Lake medallion architecture | Bronze/Silver/Gold tiers across 6 domains, real ETL pipeline | `Data Lake Architecture/aether-Datalake-backend/` |
| Provider adapters (all 24) | Real HTTP implementations with health checks, rate limiting, auth | `PROVIDER_MATRIX.md`, `shared/providers/` |
| Identity resolution framework | Graph-native clustering with WALLET, EMAIL, PHONE, DEVICE vertices | `shared/graph/graph.py`, IDENTITY_CLUSTER vertex |
| Behavioral signal engines | Web3-aware signal families already detecting wallet friction, CEX/DEX transitions | Signal pipeline in backend services |
| Graph infrastructure | Neptune + in-memory fallback, Gremlin query generation, 4-layer edge model | `shared/graph/graph.py`, GraphClient class |

---

## 3. Gap Analysis: What Is Missing

### Gap 1: No Canonical Chain Registry

**Current state:** The system uses `VMType` enums (evm, svm, bitcoin, movevm, near, tvm, cosmos) and raw `chain_id` strings. There is no structured entity representing individual chains like "ethereum-mainnet", "base", "arbitrum-one", "polygon-pos".

**Impact:** Cannot distinguish Ethereum mainnet from Arbitrum from Base at the graph level. Chain distribution analytics (`/v1/web3/chains/`) rely on raw `chainId` integers with no name resolution, no RPC endpoint mapping, no block time metadata, no native token identification.

**What exists:** `ChainDistribution` model has `chain_name: str` field but it is never populated from a registry.

### Gap 2: No Protocol Registry or Taxonomy

**Current state:** Protocols appear as free-text strings in `DeFiSummary.protocol`, `TransactionSummary.protocol`, and `DeFiPositionView.protocol`. There is no structured entity for protocols. The `PROTOCOL` vertex type exists in the graph but has no schema enforcement, no family classification, no version tracking, no fork/migration lineage.

**Impact:** "Uniswap v2", "Uniswap v3", "uniswap", and "UniswapV3" are treated as four different protocols. Cannot track protocol forks, migrations, or multi-chain deployments.

### Gap 3: No App/dApp/Frontend-Domain Registry

**Current state:** No graph vertex or database entity represents a frontend application or dApp. The SDK tracks `page.url` and `page.referrer` but these are raw strings with no mapping to application identities.

**Impact:** Cannot answer "which dApp frontends are users interacting with before on-chain actions?" Cannot attribute frontend sessions to protocol interactions.

### Gap 4: No Frontend-to-Protocol Attribution

**Current state:** The SDK ships wallet events and transaction events independently. There is no join between "user was on app.uniswap.org" (page view) and "user called Uniswap Router" (transaction). The `WalletEvent` and `TransactionEvent` types share a `sessionId` but no explicit protocol attribution field.

**Impact:** Cannot build funnel analytics from frontend discovery through on-chain execution. Frontend domain to contract address mapping does not exist.

### Gap 5: No Contract Classification Pipeline

**Current state:** Contracts are recorded via DEPLOY and CALL action types. The graph has a `CONTRACT` vertex type. However, there is no pipeline that takes a contract address, resolves its bytecode, identifies its standard (ERC-20, ERC-721, ERC-1155, etc.), maps it to a protocol, or classifies its function.

**Impact:** A CALL edge to a contract address carries no semantic meaning beyond "this wallet interacted with this contract." Cannot distinguish a DEX swap from a lending deposit from an NFT mint at the graph level.

### Gap 6: No Canonical Token Registry

**Current state:** `TokenHolding` model has `symbol`, `name`, `contract_address`, `decimals`. But there is no canonical token registry that maps across chains, tracks token standards (ERC-20, SPL, CW-20), handles wrapped variants, or maintains pricing metadata.

**Impact:** The same token bridged across chains appears as multiple unrelated entries. Cannot aggregate cross-chain token exposure. No standard-level classification (fungible, NFT, semi-fungible).

### Gap 7: No Governance Depth

**Current state:** Snapshot is an implemented provider. The lake has a `governance` domain. But there are no graph vertex types for PROPOSAL, VOTE, or DELEGATION. Governance data is flat -- ingested into the lake but not structured for graph queries.

**Impact:** Cannot answer "how does this wallet vote?" or "what governance power does this identity cluster hold?" Cannot track delegation chains or voting patterns as graph traversals.

### Gap 8: No Bridge Route Tracking

**Current state:** `BridgeEvent` model exists with `source_chain`, `dest_chain`, `bridge`, `token`, `amount`, `status`. The `/v1/web3/bridges/` endpoint is defined. But bridge events are flat records with no graph representation, no route optimization data, and no cross-chain tx correlation.

**Impact:** Cannot track a token's full journey across chains. Cannot correlate source and destination transactions. Bridge data lives in ClickHouse queries only, not in the graph.

### Gap 9: No DEX Pool/Market/Vault/Strategy Objects

**Current state:** `DeFiCategory` enum includes `dex`, `yield`, `lending`, `staking`. But there are no structured objects for specific pools (Uniswap ETH/USDC on Ethereum), vaults (Yearn yvUSDC), or strategies (Convex stETH). These are all collapsed into the `DeFiSummary` aggregate.

**Impact:** Cannot track individual pool performance, TVL changes, or user position history at the pool level. Position-level analytics are impossible without pool identity.

### Gap 10: No Protocol Migration Tracking

**Current state:** No mechanism to track when users migrate from Uniswap v2 to v3, from Compound v2 to v3, from Aave v2 to v3. Protocol versions are free-text strings with no lineage.

**Impact:** Cannot measure protocol migration velocity, retention, or churn at the protocol version level.

### Gap 11: No Completeness/Confidence States on Graph Objects

**Current state:** Graph vertices and edges have `properties: dict[str, Any]` and `created_at: str`. There is no `completeness_score`, `confidence`, `data_source`, or `staleness` metadata on any graph object.

**Impact:** Cannot distinguish a WALLET vertex created from a single SDK event (low confidence) from one enriched by Chainalysis + ENS + Nansen data (high confidence). Cannot prioritize enrichment or flag stale data.

### Gap 12: No Chain-Family Canonical Action Normalization

**Current state:** Each VM tracker ships raw transaction data with VM-specific fields. The backend receives these as generic event properties. There is no canonical action schema that normalizes "a token transfer" across EVM (ERC-20 transfer), Solana (SPL token transfer), Bitcoin (UTXO spend), and Cosmos (bank send).

**Impact:** Cross-chain analytics require manual per-VM parsing. Cannot build unified action feeds or cross-chain behavioral patterns without a normalization layer.

### Gap 13: No Deployer/Multisig Entity Tracking

**Current state:** `WalletClassification` includes `multisig` as a value but there is no structured entity for multisig wallets (Safe, Squads, etc.) or contract deployer identities. A DEPLOY edge connects a WALLET to a CONTRACT but deployer reputation, multisig signers, and deployment patterns are not tracked.

**Impact:** Cannot assess contract trust by deployer history. Cannot track multisig governance structures.

### Gap 14: No NFT Collection Objects

**Current state:** `DeFiCategory` includes `nft_marketplace`. But there are no NFT collection entities, no floor price tracking, no trait analysis, and no collection-level graph vertices.

**Impact:** NFT interactions are visible only as generic contract calls. Cannot distinguish minting from trading from staking at the collection level.

### Gap 15: No Exchange/Venue Account Tracking

**Current state:** `ExchangeFlow` model tracks aggregate deposit/withdrawal flows per exchange. But there is no entity representing a user's CEX account, no deposit address attribution, and no on-chain/off-chain identity linking through exchange withdrawal patterns.

**Impact:** Cannot close the loop between CEX deposits and the exchange accounts they belong to. Exchange flow analytics are aggregate-only.

### Gap 16: No Domain Registry

**Current state:** ENS is an implemented provider for name resolution. But there is no registry of Web3 domains (ENS, Unstoppable Domains, .sol names, .lens handles). Domain ownership is stored as a flat `ens` field on `WalletInfo`, not as a graph entity.

**Impact:** Cannot track domain trading, expiry, or multi-domain identity patterns. Domain resolution is one-way (wallet to name) with no reverse index.

---

## 4. Severity Classification

| Severity | Gap | Rationale |
|----------|-----|-----------|
| **P0 -- Foundational** | No chain registry | Every Web3 query depends on knowing what chain an event belongs to. Without canonical chain IDs, all cross-chain analytics are string-matching hacks. |
| **P0 -- Foundational** | No protocol registry | Protocol identity is the semantic backbone of DeFi analytics. Without it, the 15-value DeFiCategory enum is just a label with no backing ontology. |
| **P0 -- Foundational** | No completeness/confidence states | Without confidence metadata, the graph cannot be trusted for decision-making. Every enrichment pass is flying blind. |
| **P1 -- Structural** | No contract classification pipeline | This is the bridge between raw on-chain data and meaningful analytics. Without it, transactions are opaque. |
| **P1 -- Structural** | No canonical action normalization | Cross-chain behavioral analysis is the platform's differentiator. Without normalization, each VM is an island. |
| **P1 -- Structural** | No token registry | Token identity spans chains, standards, and wrapped variants. Without a registry, portfolio views are fragmented. |
| **P1 -- Structural** | No app/dApp registry | Frontend attribution is a core product promise. Without app entities, the SDK's page view data cannot connect to protocol interactions. |
| **P2 -- Feature** | No frontend-to-protocol attribution | Depends on app registry + contract classification. High value but blocked by P0/P1 gaps. |
| **P2 -- Feature** | No governance depth | Snapshot data is available via provider. Structuring it as graph objects is a feature extension, not a foundation fix. |
| **P2 -- Feature** | No bridge route tracking | BridgeEvent model exists. Promoting it to graph objects with cross-chain correlation is incremental. |
| **P2 -- Feature** | No DEX pool/vault/strategy objects | Requires protocol registry first. High analytical value but depends on P0 completion. |
| **P2 -- Feature** | No protocol migration tracking | Requires protocol registry with version lineage. Pure feature work once registry exists. |
| **P3 -- Enrichment** | No deployer/multisig tracking | Incremental enrichment of existing WALLET and CONTRACT vertices. |
| **P3 -- Enrichment** | No NFT collection objects | Requires contract classification pipeline. Incremental once pipeline exists. |
| **P3 -- Enrichment** | No exchange/venue account tracking | Requires identity resolution advances. Incremental enrichment. |
| **P3 -- Enrichment** | No domain registry | ENS provider exists. Promoting domains to first-class graph entities is incremental. |

---

## 5. Ranked Implementation Order

The following order is derived from dependency analysis: each item unblocks subsequent items.

### Phase 1: Registry Foundation (Weeks 1-4)

**1. Chain Registry**
- Create `ChainRegistry` with canonical chain definitions (chain_id, vm_type, name, slug, native_token, block_time, rpc_endpoints, explorer_urls)
- Seed with all chains the platform currently encounters (Ethereum, Polygon, Arbitrum, Optimism, Base, BSC, Avalanche, Solana, Bitcoin, Sui, NEAR, Tron, Cosmos Hub, Osmosis, SEI)
- Wire into `ChainDistribution` model to replace raw chain_id with resolved chain entities
- Add CHAIN vertex type to graph

**2. Protocol Registry**
- Create `ProtocolRegistry` with canonical protocol definitions (slug, name, family, version, category, deployed_chains, contract_addresses, website, logo)
- Seed from DeFiLlama protocol list (existing provider) + manual curation for top 200 protocols
- Add PROTOCOL vertex schema enforcement (currently exists as untyped vertex)
- Track protocol versions and fork lineage (uniswap-v2 -> uniswap-v3, compound-v2 -> compound-v3)

**3. Token Registry**
- Create `TokenRegistry` with canonical token definitions (symbol, name, standard, contract_addresses_by_chain, decimals_by_chain, coingecko_id, is_wrapped, canonical_token)
- Seed from CoinGecko (existing provider) for top 1000 tokens
- Wire into `TokenHolding` model for cross-chain deduplication
- Add TOKEN vertex type to graph

**4. Confidence/Completeness Metadata**
- Add `confidence: float`, `completeness: float`, `data_sources: list[str]`, `last_enriched: datetime`, `staleness_seconds: int` to all Vertex and Edge dataclasses
- Define confidence scoring rules per vertex type (e.g., WALLET with only SDK data = 0.3, + ENS = 0.5, + Chainalysis = 0.8)
- Add `needs_enrichment()` method to Vertex class

### Phase 2: Classification and Normalization (Weeks 5-8)

**5. Contract Classification Pipeline**
- Input: contract address + chain
- Step 1: Resolve bytecode via RPC provider (QuickNode/Alchemy/Infura)
- Step 2: Identify token standard (ERC-20, ERC-721, ERC-1155, etc.) via function selector matching
- Step 3: Match to protocol registry via known contract address tables
- Step 4: If unknown, classify by bytecode similarity or ABI pattern
- Output: CONTRACT vertex enriched with protocol, token standard, and DeFiCategory
- Wire as enrichment step in event ingestion pipeline

**6. Chain-Family Canonical Action Normalization**
- Define canonical action schema: `{ action_type, from, to, token, amount, protocol, chain, vm, raw_data }`
- Implement per-VM normalizers that transform raw transaction events into canonical actions
- Actions: TRANSFER, SWAP, PROVIDE_LIQUIDITY, REMOVE_LIQUIDITY, BORROW, REPAY, STAKE, UNSTAKE, MINT, BURN, APPROVE, BRIDGE, VOTE, DELEGATE, DEPLOY, UPGRADE
- Wire into event ingestion between raw event receipt and graph/lake write

**7. App/dApp Registry**
- Create `AppRegistry` with dApp definitions (slug, name, frontend_domains, protocol_slugs, category, chains)
- Seed from manual curation for top 100 dApps
- Add APP vertex type to graph with HOSTS_FRONTEND edges to domains and USES_PROTOCOL edges to protocols

### Phase 3: Graph Expansion (Weeks 9-12)

**8. New Vertex Types**
- CHAIN (from chain registry)
- TOKEN (from token registry)
- APP (from app registry)
- POOL (DEX liquidity pools, identified by contract classification)
- VAULT (yield vaults, identified by contract classification)
- PROPOSAL (governance proposals, from Snapshot provider data)
- VOTE (governance votes, from Snapshot provider data)
- NFT_COLLECTION (from contract classification)
- BRIDGE_ROUTE (from bridge event correlation)

**9. New Edge Types**
- DEPLOYED_ON (CONTRACT -> CHAIN)
- LISTED_ON (TOKEN -> CHAIN)
- PART_OF_PROTOCOL (CONTRACT -> PROTOCOL)
- FORKED_FROM (PROTOCOL -> PROTOCOL)
- MIGRATED_TO (PROTOCOL -> PROTOCOL)
- PROVIDES_LIQUIDITY (WALLET -> POOL)
- DEPOSITED_IN (WALLET -> VAULT)
- VOTED_ON (WALLET -> PROPOSAL)
- DELEGATED_TO (WALLET -> WALLET, governance delegation)
- BRIDGED_VIA (WALLET -> BRIDGE_ROUTE)
- USED_APP (SESSION -> APP)
- MINTED_FROM (WALLET -> NFT_COLLECTION)

### Phase 4: Provider Depth Integration (Weeks 13-16)

**10. Dune Breadth Integration**
- Existing Dune provider adapter is implemented
- Expand with pre-built query templates for: protocol TVL time series, DEX volume by pool, bridge flow aggregates, governance participation rates
- Schedule as lake ingestion jobs in the Bronze tier
- Promote aggregates to Silver/Gold with chain/protocol registry joins

**11. DeFiLlama Protocol Depth**
- Existing DeFiLlama adapter is implemented
- Expand coverage: TVL by chain, yields by pool, fees by protocol, stablecoin flows
- Wire into protocol registry for automatic TVL enrichment
- Add PROTOCOL vertex properties: current_tvl, tvl_7d_change, fee_revenue_30d

### Phase 5: Intelligence Integration (Weeks 17-20)

**12. Frontend Domain Attribution**
- Join SDK page view events (url, referrer) with app registry (frontend_domains)
- Create SESSION -> APP edges on match
- Create APP -> PROTOCOL -> CONTRACT attribution chains
- Enable funnel analytics: frontend visit -> wallet connect -> transaction -> protocol interaction

**13. Governance Depth**
- Parse Snapshot provider data into PROPOSAL and VOTE vertices
- Create edges: WALLET -> VOTED_ON -> PROPOSAL, WALLET -> DELEGATED_TO -> WALLET
- Track voting power, delegation chains, and participation rates per identity cluster

**14. Protocol Migration Tracking**
- Use protocol registry version lineage (FORKED_FROM, MIGRATED_TO edges)
- Detect migration events when a wallet stops interacting with protocol v(N) and starts interacting with v(N+1)
- Track migration velocity, cohort analysis by migration timing

**15. Profile/Population/ML Feature Integration**
- Add Web3 features to ML feature pipeline: protocol diversity score, chain hop frequency, DeFi sophistication index, governance participation rate, bridge usage patterns
- Feed into existing models (Intent Prediction, Churn Prediction, LTV Prediction)
- Add new model candidates: Protocol Affinity Prediction, Chain Migration Prediction

---

## 6. Dependency Graph

```
Chain Registry ─────────┬──> Contract Classification ──> App Registry
                        │                                    │
Protocol Registry ──────┤                                    v
                        ├──> Canonical Action Normalization  Frontend Attribution
Token Registry ─────────┤
                        │
Confidence Metadata ────┘
        │
        v
   Graph Expansion ──> Dune Breadth ──> DeFiLlama Depth
        │
        v
   Governance Depth ──> Protocol Migration ──> ML Feature Integration
```

No item can begin before its upstream dependencies are complete. The chain/protocol/token registries and confidence metadata are the critical path.

---

## 7. Effort Estimates

| Item | Scope | Estimate | Dependencies |
|------|-------|----------|-------------|
| Chain Registry | New module + seed data + graph vertex | 1 week | None |
| Protocol Registry | New module + DeFiLlama seed + graph schema | 2 weeks | Chain Registry |
| Token Registry | New module + CoinGecko seed + cross-chain dedup | 2 weeks | Chain Registry |
| Confidence Metadata | Vertex/Edge dataclass changes + scoring rules | 1 week | None |
| Contract Classification | Bytecode analysis + selector matching + protocol join | 3 weeks | Protocol Registry, Token Registry |
| Action Normalization | Per-VM normalizers + canonical schema + pipeline wiring | 2 weeks | Chain Registry |
| App/dApp Registry | New module + manual seed + graph vertex | 1 week | Protocol Registry |
| Graph Expansion (9 vertex types, 12 edge types) | Schema + factories + query builders | 2 weeks | All registries |
| Dune Breadth | Query templates + scheduling + lake integration | 2 weeks | Chain Registry, Protocol Registry |
| DeFiLlama Depth | Extended adapter + protocol enrichment wiring | 1 week | Protocol Registry |
| Frontend Attribution | Page view to app join + session edges | 1 week | App Registry |
| Governance Depth | Snapshot parsing + PROPOSAL/VOTE vertices + edges | 2 weeks | Protocol Registry |
| Protocol Migration | Version lineage detection + cohort analysis | 1 week | Protocol Registry v2 |
| ML Feature Integration | Feature engineering + model retraining | 3 weeks | All of the above |

**Total estimated effort:** 24 weeks (6 months) for full implementation, with the registry foundation (Phase 1) deliverable in 4 weeks and providing immediate analytical value.

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Registry data staleness | High | Medium | Automated refresh from DeFiLlama/CoinGecko on daily schedule; staleness field on all registry entries |
| Contract classification accuracy | Medium | High | Start with known-address lookup (high confidence), fall back to bytecode pattern matching (medium confidence), flag unknowns for manual review |
| Action normalization edge cases | High | Medium | Define canonical actions conservatively; ship unclassified actions with `action_type: UNKNOWN` and raw data preserved |
| Graph vertex explosion | Medium | Medium | Gate new vertex types behind feature flags (same pattern as RWA Intelligence Graph); monitor Neptune vertex counts |
| Provider rate limit pressure from enrichment | Medium | Low | Existing provider rate limiting is implemented; enrichment runs are batch with backoff |
| Backward compatibility of graph schema | Low | High | New vertex/edge types are additive; existing queries are not affected; version the graph schema |

---

## 9. What the Registries Unlock

Once the chain/protocol/token/app registries exist with confidence metadata, the following queries become possible that are currently impossible:

1. "What protocols does this user interact with across all chains?" (requires protocol registry + contract classification)
2. "What is this user's total token exposure including bridged variants?" (requires token registry with canonical token dedup)
3. "Which dApp frontends drive the most on-chain volume for Uniswap?" (requires app registry + frontend attribution)
4. "How confident are we in this wallet's identity cluster?" (requires confidence metadata)
5. "Show me all users who migrated from Compound v2 to v3 in the last 30 days." (requires protocol registry + migration tracking)
6. "What is the governance participation rate for wallets that also use DeFi lending?" (requires governance depth + protocol classification)
7. "Which chains is this token available on and what is the aggregate balance across all chains?" (requires token registry + chain registry)

---

## 10. Architecture Principles for Implementation

1. **Registry-first, not service-first.** Every new analytical capability must be backed by a canonical registry entry. Free-text protocol names, chain IDs, and token symbols must resolve to registry entities or be flagged as unresolved.

2. **Confidence is a first-class property.** Every graph vertex and edge must carry a confidence score, a list of data sources that contributed to it, and a staleness timestamp. Queries must be filterable by minimum confidence.

3. **Additive graph evolution.** New vertex and edge types are added; existing types are never removed or renamed. The graph schema is append-only. Feature flags gate new capabilities.

4. **Normalization at ingestion, not query time.** Canonical action normalization happens when events enter the pipeline, not when users query the data. This ensures the lake and graph contain normalized data.

5. **Provider data feeds registries, registries feed graph, graph feeds profiles.** The data flow is: Provider -> Lake (Bronze) -> Registry (enrichment) -> Lake (Silver/Gold) + Graph (vertices/edges) -> Profile 360 + ML Features.

---

## 11. File-Level Change Map

| File / Module | Change Type | Description |
|---------------|-------------|-------------|
| `Backend Architecture/aether-backend/shared/graph/graph.py` | Modify | Add new VertexType entries (CHAIN, TOKEN, APP, POOL, VAULT, PROPOSAL, VOTE, NFT_COLLECTION, BRIDGE_ROUTE). Add new EdgeType entries (12 new types). Add confidence/completeness fields to Vertex and Edge dataclasses. |
| `Backend Architecture/services/web3/web3_models.py` | Modify | Add ChainEntity, ProtocolEntity, TokenEntity, AppEntity Pydantic models. Add CanonicalAction model with normalized action schema. Add confidence fields to existing response models. |
| `Backend Architecture/services/web3/web3_service.py` | Modify | Wire new registry endpoints. Add contract classification endpoint. |
| `Backend Architecture/services/web3/web3_queries.py` | Modify | Add registry-aware queries that join on canonical chain/protocol/token IDs. |
| `Backend Architecture/aether-backend/shared/registries/` | Create | New module: `chain_registry.py`, `protocol_registry.py`, `token_registry.py`, `app_registry.py`. Seed data + CRUD + refresh scheduling. |
| `Backend Architecture/aether-backend/shared/classifiers/` | Create | New module: `contract_classifier.py`, `action_normalizer.py`. Bytecode analysis, selector matching, per-VM normalization. |
| `Data Lake Architecture/aether-Datalake-backend/` | Modify | Add Dune query templates for protocol/pool/governance data. Add DeFiLlama expanded endpoints. Add registry table schemas for Silver/Gold tiers. |
| `packages/web/src/web3/index.ts` | No change | SDK remains a thin client. No registry logic at the client layer. |
| `packages/web/src/web3/providers/*.ts` | No change | Wallet providers are already comprehensive. |

---

## 12. Success Criteria

The Web3 coverage gaps are closed when:

1. **Every chain ID in the system resolves to a canonical chain entity** with name, VM type, native token, and metadata. Zero unresolved chain IDs in production data.

2. **Every contract interaction can be attributed to a protocol** with at least medium confidence (>0.5). Unclassified contracts are flagged and queued for manual review.

3. **Every token holding can be deduplicated across chains** through canonical token identity. Cross-chain portfolio totals are accurate.

4. **Every graph vertex carries a confidence score** between 0.0 and 1.0 with a list of contributing data sources. Queries can filter by minimum confidence.

5. **Cross-chain action queries return normalized results** where a "token transfer" means the same thing regardless of whether it happened on Ethereum, Solana, or Cosmos.

6. **Frontend sessions can be attributed to protocols** through the app registry and domain matching, enabling funnel analytics from page view to on-chain action.

7. **The Profile 360 view includes Web3 intelligence features** (protocol diversity, chain hop frequency, DeFi sophistication) that feed ML models for intent and churn prediction.

8. **Zero regressions in existing functionality.** All 184 current endpoints continue to work. All 24 provider adapters remain operational. SDK wallet detection is unchanged. Graph queries against existing vertex/edge types return identical results.
