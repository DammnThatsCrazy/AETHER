# Web3 Coverage Implementation

## Overview

This document describes the Web3 Coverage layer added to the Aether intelligence platform. The implementation introduces a full-stack registry, classification engine, and graph-expansion pipeline that maps every on-chain and frontend interaction into the existing identity graph, profile, population, and expectation infrastructure.

---

## Files Created (6 new files)

### 1. `Backend Architecture/aether-backend/services/web3/__init__.py`

Module documentation and public API surface for the web3 coverage package.

- Exposes `web3_router` for mounting in main application
- Re-exports core classification functions (`classify_contract`, `attribute_domain`, `build_graph_from_observation`)
- Re-exports registry classes for direct import by other services
- Documents module purpose: "Web3 coverage spine — registry, classification, and graph expansion for on-chain and frontend observations"

---

### 2. `Backend Architecture/aether-backend/services/web3/models.py`

Registry models defining the complete Web3 ontology. Approximately 700+ lines.

#### Enums (16 total)

| Enum | Values | Purpose |
|------|--------|---------|
| `CompletenessStatus` | `STUB`, `PARTIAL`, `COMPLETE`, `VERIFIED` | Tracks data completeness for any registry record |
| `ObjectStatus` | `ACTIVE`, `DEPRECATED`, `MIGRATED`, `UNKNOWN` | Lifecycle state of a registry object |
| `MigrationType` | `CONTRACT_UPGRADE`, `PROTOCOL_FORK`, `CHAIN_MIGRATION`, `TOKEN_REBRAND`, `GOVERNANCE_CHANGE` | Classifies migration events |
| `VMFamily` | `EVM`, `SVM`, `MOVE_VM`, `WASM`, `CAIRO`, `NEAR_VM`, `BITCOIN_SCRIPT`, `CUSTOM` | Virtual machine family for chain/contract classification |
| `ChainType` | `L1`, `L2`, `L3`, `SIDECHAIN`, `APPCHAIN`, `ROLLUP` | Chain architecture classification |
| `ProtocolFamily` | `DEX`, `LENDING`, `STAKING`, `BRIDGE`, `STABLECOIN`, `YIELD`, `DERIVATIVES`, `NFT`, `GOVERNANCE`, `RWA`, `DEPIN`, `PAYMENTS`, `SOCIAL`, `GAMING`, `OTHER` | Top-level protocol category |
| `ContractRole` | `ROUTER`, `FACTORY`, `POOL`, `VAULT`, `STAKING`, `GOVERNANCE`, `TOKEN`, `PROXY`, `BRIDGE`, `ORACLE`, `REGISTRY`, `OTHER` | Role of a contract within its system |
| `TokenStandard` | `ERC20`, `ERC721`, `ERC1155`, `SPL`, `NATIVE`, `BEP20`, `TRC20`, `FA_MOVE`, `OTHER` | Token implementation standard |
| `AppCategory` | `WALLET`, `DEX_AGGREGATOR`, `PORTFOLIO`, `ANALYTICS`, `BRIDGE_UI`, `LENDING_UI`, `GOVERNANCE_UI`, `NFT_MARKETPLACE`, `EXPLORER`, `OTHER` | Frontend application type |
| `VenueType` | `CEX`, `DEX`, `OTC`, `AGGREGATOR`, `PERPS`, `OPTIONS`, `OTHER` | Market venue classification |
| `DeployerType` | `PROTOCOL_TEAM`, `DAO`, `INDIVIDUAL`, `FACTORY_CONTRACT`, `UNKNOWN` | Entity that deployed a contract |
| `GovernancePlatform` | `SNAPSHOT`, `TALLY`, `ONCHAIN`, `COMPOUND_GOVERNOR`, `OPENZEPPELIN_GOVERNOR`, `CUSTOM` | Governance mechanism type |
| `CanonicalAction` | 29 actions | Normalized action vocabulary for all observations |

#### CanonicalAction Values (29)

```
SWAP, ADD_LIQUIDITY, REMOVE_LIQUIDITY, DEPOSIT, WITHDRAW,
BORROW, REPAY, LIQUIDATE, STAKE, UNSTAKE, CLAIM_REWARDS,
BRIDGE_SEND, BRIDGE_RECEIVE, TRANSFER, APPROVE, MINT, BURN,
VOTE, DELEGATE, CREATE_PROPOSAL, DEPLOY, UPGRADE_PROXY,
WRAP, UNWRAP, FLASH_LOAN, HARVEST, COMPOUND, REGISTER_NAME,
UNKNOWN
```

#### Provenance Envelope Model

Every registry record carries a provenance envelope:

```python
class ProvenanceEnvelope(BaseModel):
    source: str                    # e.g. "etherscan", "dune", "manual", "classifier"
    confidence: float              # 0.0 — 1.0
    observed_at: datetime
    observer_id: Optional[str]     # system or human identifier
    evidence: Optional[dict]       # raw supporting data
    signature: Optional[str]       # HMAC or Ed25519 signature
```

#### Pydantic Models (24 total)

| Create Model | Record Model | Purpose |
|-------------|-------------|---------|
| `ChainCreate` | `ChainRecord` | Blockchain network definition (chain_id, name, vm_family, chain_type, rpc_url, explorer_url, native_token_symbol) |
| `ProtocolCreate` | `ProtocolRecord` | DeFi/Web3 protocol (slug, name, protocol_family, website, defillama_id, chains deployed on) |
| `ContractSystemCreate` | `ContractSystemRecord` | Logical contract system (name, protocol_id, description, contract roles map) |
| `ContractInstanceCreate` | `ContractInstanceRecord` | Deployed contract instance (address, chain_id, system_id, role, abi_hash, verified, proxy_type) |
| `TokenCreate` | `TokenRecord` | Token definition (address, chain_id, symbol, name, decimals, standard, protocol_id, coingecko_id) |
| `AppCreate` | `AppRecord` | Frontend application (slug, name, category, domains list, protocol_ids list) |
| `FrontendDomainCreate` | `FrontendDomainRecord` | Domain-to-app/protocol mapping (domain, app_id, protocol_id, verified) |
| `GovernanceSpaceCreate` | `GovernanceSpaceRecord` | Governance space (space_id, name, protocol_id, platform, chain_id) |
| `MarketVenueCreate` | `MarketVenueRecord` | Trading venue (slug, name, venue_type, domains, api_endpoint) |
| `BridgeRouteCreate` | `BridgeRouteRecord` | Bridge route (protocol_id, source_chain_id, dest_chain_id, contract_address, supported_tokens) |
| `DeployerEntityCreate` | `DeployerEntityRecord` | Contract deployer (address, chain_id, entity_type, protocol_id, label) |
| `MigrationCreate` | `MigrationRecord` | Protocol/contract migration event (migration_type, from_id, to_id, detected_at, evidence) |

#### Standalone Models

| Model | Purpose |
|-------|---------|
| `CoverageStatus` | Aggregate coverage statistics (chains, protocols, contracts, tokens, apps, domains, completeness breakdown) |
| `CoverageQuery` | Query parameters for coverage status endpoint (chain_id, protocol_family, completeness_filter) |
| `Web3Observation` | Single observation event for batch ingestion (wallet_address, chain_id, tx_hash, to_address, method_selector, value, domain, timestamp, raw_data) |

---

### 3. `Backend Architecture/aether-backend/services/web3/registries.py`

Thirteen repository classes extending `BaseRepository` with asyncpg PostgreSQL backend in production and in-memory storage for local development.

#### Repository Classes (13)

| Repository | Table | Key Fields | Notable Methods |
|-----------|-------|------------|----------------|
| `ChainRegistry` | `web3_chains` | `chain_id` (natural key) | `get_by_chain_id()`, `list_by_vm_family()`, `list_by_type()` |
| `ProtocolRegistry` | `web3_protocols` | `slug` (unique) | `get_by_slug()`, `list_by_family()`, `search_by_name()`, `list_by_chain()` |
| `ContractSystemRegistry` | `web3_contract_systems` | `id` (UUID) | `get_by_protocol()`, `list_with_instances()` |
| `ContractInstanceRegistry` | `web3_contract_instances` | `(address, chain_id)` composite | `get_by_address_chain()`, `list_by_system()`, `list_by_role()`, `list_unclassified()` |
| `TokenRegistry` | `web3_tokens` | `(address, chain_id)` composite | `get_by_address_chain()`, `get_by_symbol()`, `list_by_standard()`, `list_by_protocol()` |
| `AppRegistry` | `web3_apps` | `slug` (unique) | `get_by_slug()`, `get_by_domain()`, `list_by_category()` |
| `FrontendDomainRegistry` | `web3_frontend_domains` | `domain` (unique) | `get_by_domain()`, `list_by_app()`, `list_by_protocol()`, `list_unverified()` |
| `GovernanceSpaceRegistry` | `web3_governance_spaces` | `space_id` (unique) | `get_by_space_id()`, `list_by_protocol()`, `list_by_platform()` |
| `MarketVenueRegistry` | `web3_market_venues` | `slug` (unique) | `get_by_slug()`, `list_by_type()`, `search_by_name()` |
| `BridgeRouteRegistry` | `web3_bridge_routes` | `id` (UUID) | `list_by_protocol()`, `list_by_source_chain()`, `list_by_dest_chain()`, `find_route()` |
| `DeployerEntityRegistry` | `web3_deployer_entities` | `(address, chain_id)` composite | `get_by_address_chain()`, `list_by_protocol()`, `list_by_type()` |
| `MigrationRegistry` | `web3_migrations` | `id` (UUID) | `list_by_type()`, `list_by_protocol()`, `get_chain_for_contract()` |
| `Web3ObservationRepository` | `web3_observations` | `id` (UUID) | `batch_insert()`, `list_by_wallet()`, `list_by_chain()`, `list_unprocessed()`, `mark_processed()` |

All repositories inherit:
- `create()`, `get()`, `list()`, `update()`, `delete()` from `BaseRepository`
- Automatic table creation on first access (no migration needed)
- Connection pooling via shared asyncpg pool
- Provenance envelope attached to every write operation

---

### 4. `Backend Architecture/aether-backend/services/web3/seed.py`

Initial registry seed data providing baseline coverage for classification.

#### Chains (31)

| Category | Chains |
|----------|--------|
| EVM L1s | Ethereum (1), BNB Chain (56), Avalanche C-Chain (43114), Fantom (250), Gnosis (100), Celo (42220), Cronos (25) |
| EVM L2s | Arbitrum One (42161), Optimism (10), Base (8453), Polygon (137), zkSync Era (324), Linea (59144), Scroll (534352), Blast (81457), Mantle (5000), Mode (34443), Manta Pacific (169) |
| Non-EVM | Solana (solana-mainnet), Bitcoin (bitcoin-mainnet), NEAR (near-mainnet), TRON (tron-mainnet), Sui (sui-mainnet), Aptos (aptos-mainnet) |
| Cosmos Ecosystem | Cosmos Hub (cosmoshub-4), Osmosis (osmosis-1) |
| Emerging | Hyperliquid (hyperliquid-mainnet), Monad (monad-testnet), Berachain (80094) |

#### Protocols (40+)

| Family | Protocols |
|--------|-----------|
| DEX | Uniswap (v2, v3, Universal Router), SushiSwap, Curve, Balancer, PancakeSwap, Trader Joe, Camelot, Aerodrome, Raydium, Orca, Jupiter |
| Lending | Aave (v2, v3), Compound (v2, v3), MakerDAO, Morpho, Spark, Benqi |
| Staking | Lido, Rocket Pool, Frax Ether, Coinbase Wrapped Staked ETH, EigenLayer |
| Bridge | Across, Stargate, Synapse, Wormhole, LayerZero, Hop Protocol |
| Stablecoin | MakerDAO (DAI), Circle (USDC), Tether (USDT), Frax, Ethena (USDe) |
| Yield | Yearn, Convex, Pendle, Beefy |
| Derivatives | GMX, dYdX, Synthetix, Hyperliquid DEX |
| NFT | OpenSea, Blur, Magic Eden |
| Governance | Snapshot, Tally |
| RWA | Ondo Finance, Centrifuge, Maple Finance |
| DePIN | Helium, Hivemapper |

#### Apps/dApps (24)

MetaMask, Rainbow, Phantom, Rabby, Zerion, DeBank, Zapper, 1inch, Paraswap, CowSwap, LlamaSwap, Etherscan, Basescan, Arbiscan, DeFi Saver, Instadapp, Revoke.cash, OpenSea App, Blur App, Uniswap App, Aave App, Lido App, Safe (Gnosis Safe), WalletConnect

#### Tokens (16)

| Category | Tokens |
|----------|--------|
| Native | ETH, BNB, MATIC, AVAX, SOL |
| Stablecoins | USDC, USDT, DAI, FRAX |
| Wrapped | WETH, WBTC |
| Governance | UNI, AAVE, LDO, CRV, MKR |

#### Market Venues (10)

Binance, Coinbase, Kraken, OKX, Bybit, Uniswap (DEX venue), Curve (DEX venue), GMX (Perps venue), dYdX (Perps venue), 1inch (Aggregator venue)

#### Governance Spaces (10)

Uniswap Governance, Aave Governance, Compound Governance, MakerDAO Governance, Lido Governance, Arbitrum DAO, Optimism Collective, ENS DAO, Gitcoin DAO, Safe DAO

---

### 5. `Backend Architecture/aether-backend/services/web3/classifier.py`

Classification engine that maps raw observations to registry objects and graph topology.

#### METHOD_SELECTOR_MAP (40+ EVM method selectors)

Maps 4-byte EVM method selectors to canonical actions:

| Selector | Method Signature | Canonical Action |
|----------|-----------------|-----------------|
| `0x38ed1739` | `swapExactTokensForTokens` | SWAP |
| `0x8803dbee` | `swapTokensForExactTokens` | SWAP |
| `0x7ff36ab5` | `swapExactETHForTokens` | SWAP |
| `0x18cbafe5` | `swapExactTokensForETH` | SWAP |
| `0x5c11d795` | `swapExactTokensForTokensSupportingFeeOnTransferTokens` | SWAP |
| `0x04e45aaf` | `exactInputSingle` (Uniswap V3) | SWAP |
| `0xb858183f` | `exactInput` (Uniswap V3) | SWAP |
| `0x3593564c` | `execute` (Universal Router) | SWAP |
| `0xe8e33700` | `addLiquidity` | ADD_LIQUIDITY |
| `0xf305d719` | `addLiquidityETH` | ADD_LIQUIDITY |
| `0xbaa2abde` | `removeLiquidity` | REMOVE_LIQUIDITY |
| `0x02751cec` | `removeLiquidityETH` | REMOVE_LIQUIDITY |
| `0xe8eda9df` | `deposit` (Aave V3) | DEPOSIT |
| `0xd0e30db0` | `deposit` (generic) | DEPOSIT |
| `0x69328dec` | `withdraw` (Aave V3) | WITHDRAW |
| `0x2e1a7d4d` | `withdraw` (generic) | WITHDRAW |
| `0xa0712d68` | `mint` (Compound) | DEPOSIT |
| `0xdb006a75` | `redeem` (Compound) | WITHDRAW |
| `0xc5ebeaec` | `borrow` (Compound) | BORROW |
| `0x0e752702` | `repayBorrow` (Compound) | REPAY |
| `0xa9059cbb` | `transfer` | TRANSFER |
| `0x23b872dd` | `transferFrom` | TRANSFER |
| `0x095ea7b3` | `approve` | APPROVE |
| `0xa694fc3a` | `stake` | STAKE |
| `0x2e17de78` | `unstake` | UNSTAKE |
| `0x4e71d92d` | `claim` | CLAIM_REWARDS |
| `0xe9fad8ee` | `exit` (StakingRewards) | UNSTAKE |
| `0x3d18b912` | `getReward` | CLAIM_REWARDS |
| `0xd505accf` | `permit` | APPROVE |
| `0x40c10f19` | `mint` (ERC20) | MINT |
| `0x42966c68` | `burn` | BURN |
| `0xea598cb0` | `wrap` | WRAP |
| `0xde0e9a3e` | `unwrap` | UNWRAP |
| `0x5c19a95c` | `delegate` | DELEGATE |
| `0x56781388` | `castVote` | VOTE |
| `0x15373e3d` | `castVoteWithReason` | VOTE |
| `0x7b3c71d3` | `castVoteWithReasonAndParams` | VOTE |
| `0xd8555e42` | `propose` | CREATE_PROPOSAL |
| `0x5ceae9c4` | `flashLoan` | FLASH_LOAN |
| `0x4515cef3` | `add_liquidity` (Curve) | ADD_LIQUIDITY |
| `0xecb586a5` | `remove_liquidity` (Curve) | REMOVE_LIQUIDITY |

#### Core Functions

**`classify_contract(address, chain_id, registries) -> ContractClassification`**

1. Lookup contract instance in `ContractInstanceRegistry` by `(address, chain_id)`
2. If found: return classification with system, protocol, role, and confidence
3. If not found: auto-register as UNKNOWN contract with `CompletenessStatus.STUB`
4. Return classification with `confidence=0.0` and `status=UNKNOWN`
5. Side effect: creates stub `ContractInstanceRecord` for future enrichment

**`attribute_domain(domain, registries) -> DomainAttribution`**

1. Lookup domain in `FrontendDomainRegistry`
2. If found: resolve app and protocol via `AppRegistry` and `ProtocolRegistry`
3. If not found: return unattributed with `confidence=0.0`
4. Returns: `app_id`, `protocol_ids`, `confidence`, `verified` flag

**`build_graph_from_observation(observation, classification, attribution, registries) -> GraphExpansion`**

Creates vertices and edges from a single classified observation:

1. Ensure WALLET vertex exists for `observation.wallet_address`
2. Ensure CHAIN vertex exists for `observation.chain_id`
3. If contract classified to a protocol:
   - Create/ensure PROTOCOL vertex
   - Create edge: WALLET --USES_PROTOCOL--> PROTOCOL (with canonical action, tx_hash, timestamp)
4. If contract classified to a system:
   - Create/ensure CONTRACT_SYSTEM vertex
   - Create edge: CONTRACT --INSTANCE_OF--> CONTRACT_SYSTEM
   - Create edge: CONTRACT_SYSTEM --PART_OF_SYSTEM--> PROTOCOL
5. If domain attributed to an app:
   - Create/ensure APP vertex
   - Create edge: WALLET --USES_APP--> APP
   - Create edge: WALLET --TOUCHES_DOMAIN--> FRONTEND_DOMAIN
   - Create edge: FRONTEND_DOMAIN --FRONTS_PROTOCOL--> PROTOCOL
6. If canonical action is BRIDGE_SEND or BRIDGE_RECEIVE:
   - Create/ensure BRIDGE_ROUTE vertex
   - Create edge: WALLET --BRIDGES_VIA--> BRIDGE_ROUTE
7. If canonical action is VOTE, DELEGATE, or CREATE_PROPOSAL:
   - Create/ensure GOVERNANCE_SPACE vertex
   - Create edge: WALLET --PARTICIPATES_IN--> GOVERNANCE_SPACE
   - Create edge: WALLET --VOTES_ON--> GOVERNANCE_PROPOSAL (if proposal ID extractable)
8. If canonical action is STAKE or DEPOSIT to known pool/vault:
   - Create/ensure POOL or VAULT vertex
   - Create edge: WALLET --HOLDS_TOKEN--> TOKEN (for receipt token)
9. Returns: `GraphExpansion` with lists of new vertices and edges

**`detect_migration(deployer_address, chain_id, registries) -> Optional[MigrationRecord]`**

1. Lookup deployer in `DeployerEntityRegistry`
2. If deployer has deployed multiple contract systems for the same protocol:
   - Compare deployment timestamps
   - If newer system exists with same role pattern, flag as potential migration
3. Create `MigrationRecord` with `MigrationType.CONTRACT_UPGRADE`
4. Return migration record or None

---

### 6. `Backend Architecture/aether-backend/services/web3/routes.py`

Thirty-five API endpoints organized by resource type.

#### Chain CRUD (3 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/chains` | Create a new chain record |
| `GET` | `/v1/web3/chains` | List all chains (filterable by vm_family, chain_type) |
| `GET` | `/v1/web3/chains/{chain_id}` | Get chain by chain_id |

#### Protocol CRUD (3 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/protocols` | Create a new protocol record |
| `GET` | `/v1/web3/protocols` | List protocols (filterable by family, chain) |
| `GET` | `/v1/web3/protocols/{slug}` | Get protocol by slug |

#### Contract CRUD + Reclassify (4 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/contracts` | Register a contract instance |
| `GET` | `/v1/web3/contracts` | List contracts (filterable by chain, system, role, unclassified) |
| `GET` | `/v1/web3/contracts/{chain_id}/{address}` | Get contract by chain + address |
| `POST` | `/v1/web3/contracts/{chain_id}/{address}/reclassify` | Reclassify a contract (updates system_id, role, rebinds graph edges via LATER_CLASSIFIED_AS) |

#### Token CRUD (2 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/tokens` | Register a token |
| `GET` | `/v1/web3/tokens` | List tokens (filterable by chain, standard, protocol, symbol) |

#### App CRUD (2 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/apps` | Register an app |
| `GET` | `/v1/web3/apps` | List apps (filterable by category) |

#### Domain CRUD (2 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/domains` | Register a frontend domain mapping |
| `GET` | `/v1/web3/domains` | List domains (filterable by app, protocol, verified status) |

#### Governance CRUD (2 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/governance` | Register a governance space |
| `GET` | `/v1/web3/governance` | List governance spaces (filterable by protocol, platform) |

#### Classification Endpoints (4 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/classify/contract` | Classify a contract address on a chain. Returns protocol, system, role, confidence. Auto-registers unknown contracts as stubs. |
| `POST` | `/v1/web3/classify/method` | Classify a method selector. Returns canonical action, method name, description. |
| `POST` | `/v1/web3/classify/domain` | Classify a frontend domain. Returns app, protocol attribution, confidence. |
| `POST` | `/v1/web3/classify/observation` | Full observation classification. Runs contract classification, domain attribution, method classification, and returns complete graph expansion plan. |

#### Observation Batch Ingestion (1 endpoint)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/observations/batch` | Ingest up to 500 observations per batch. Each observation is classified, graph-expanded, and stored. Returns per-observation results (classified action, protocol, app, graph vertices/edges created, errors). |

#### Migration Tracking (3 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/migrations` | Record a migration event |
| `GET` | `/v1/web3/migrations` | List migrations (filterable by type, protocol) |
| `POST` | `/v1/web3/migrations/detect` | Trigger migration detection for a deployer address |

#### Coverage Status + Health (2 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/web3/coverage` | Returns aggregate coverage statistics: total chains, protocols, contracts, tokens, apps, domains, governance spaces, venues, deployers, plus completeness breakdown by CompletenessStatus |
| `GET` | `/v1/web3/health` | Web3 subsystem health check: registry connectivity, classification engine status, graph connection status |

#### Seed (1 endpoint)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/seed` | Populate registries with seed data from seed.py. Idempotent (skips existing records). Returns count of records created per registry. |

---

## Files Modified (2)

### 1. `Backend Architecture/aether-backend/shared/graph/graph.py`

Added 18 new vertex types and 27 new edge types to the graph ontology.

#### New Vertex Types (18)

| VertexType | Description | Key Properties |
|-----------|-------------|----------------|
| `CHAIN` | Blockchain network | chain_id, name, vm_family, chain_type |
| `TOKEN` | Fungible or non-fungible token | address, chain_id, symbol, standard |
| `TOKEN_POSITION` | Wallet's position in a specific token | wallet_address, token_address, chain_id, balance |
| `POOL` | Liquidity pool | address, chain_id, protocol_id, token_pair |
| `VAULT` | Yield vault or staking vault | address, chain_id, protocol_id, strategy |
| `MARKET` | Trading market/pair | base_token, quote_token, venue_id |
| `STRATEGY` | DeFi strategy (yield, hedging) | protocol_id, type, description |
| `APP` | Frontend application | slug, name, category |
| `FRONTEND_DOMAIN` | Web domain serving a dApp | domain, app_id, protocol_id |
| `GOVERNANCE_SPACE` | Governance forum/space | space_id, name, protocol_id, platform |
| `GOVERNANCE_PROPOSAL` | Single governance proposal | proposal_id, space_id, title, status |
| `BRIDGE_ROUTE` | Cross-chain bridge path | protocol_id, source_chain, dest_chain |
| `NFT_COLLECTION` | NFT collection | address, chain_id, name, standard |
| `DEPLOYER_ENTITY` | Contract deployer identity | address, chain_id, entity_type, protocol_id |
| `MARKET_VENUE` | Trading venue (CEX/DEX) | slug, name, venue_type |
| `CONTRACT_SYSTEM` | Logical contract grouping | name, protocol_id, roles |
| `PROTOCOL_VERSION` | Versioned protocol release | protocol_id, version, deployed_at |
| `UNKNOWN_CONTRACT` | Unclassified contract stub | address, chain_id, first_seen |

#### New Edge Types (27)

| EdgeType | Source → Target | Description |
|---------|----------------|-------------|
| `USES_PROTOCOL` | WALLET → PROTOCOL | Wallet interacted with protocol |
| `USES_APP` | WALLET → APP | Wallet used frontend app |
| `TOUCHES_DOMAIN` | WALLET → FRONTEND_DOMAIN | Wallet accessed a domain |
| `HOLDS_TOKEN` | WALLET → TOKEN | Wallet holds a token balance |
| `BRIDGES_VIA` | WALLET → BRIDGE_ROUTE | Wallet used a bridge route |
| `PARTICIPATES_IN` | WALLET → GOVERNANCE_SPACE | Wallet participates in governance |
| `VOTES_ON` | WALLET → GOVERNANCE_PROPOSAL | Wallet voted on a proposal |
| `DELEGATES_TO` | WALLET → WALLET | Wallet delegates governance power |
| `LINKED_TO_SOCIAL` | WALLET → SOCIAL_IDENTITY | Wallet linked to social identity |
| `TRADED_ON` | WALLET → MARKET | Wallet traded on a market pair |
| `EXPOSED_TO` | WALLET → TOKEN | Wallet has economic exposure to token |
| `INSTANCE_OF` | CONTRACT → CONTRACT_SYSTEM | Contract is instance of a system |
| `PART_OF_SYSTEM` | CONTRACT_SYSTEM → PROTOCOL | System belongs to protocol |
| `SUCCESSOR_OF` | PROTOCOL_VERSION → PROTOCOL_VERSION | Version succession chain |
| `MIGRATED_TO` | CONTRACT → CONTRACT | Contract migration link |
| `CONTROLS` | DEPLOYER_ENTITY → CONTRACT | Deployer controls contract |
| `DEPLOYED_ON` | PROTOCOL → CHAIN | Protocol deployed on chain |
| `FRONTS_PROTOCOL` | FRONTEND_DOMAIN → PROTOCOL | Domain is frontend for protocol |
| `ASSOCIATED_WITH` | APP → PROTOCOL | App associated with protocol |
| `SERVED_BY` | MARKET → MARKET_VENUE | Market served by venue |
| `TOKEN_OF` | TOKEN → PROTOCOL | Token belongs to protocol |
| `TRADED_ON_VENUE` | WALLET → MARKET_VENUE | Wallet traded on venue |
| `POOL_FOR` | POOL → TOKEN | Pool provides liquidity for token |
| `GOVERNED_BY_SPACE` | PROTOCOL → GOVERNANCE_SPACE | Protocol governed by space |
| `LATER_CLASSIFIED_AS` | UNKNOWN_CONTRACT → CONTRACT_SYSTEM | Reclassification edge (preserves history) |
| `HAS_POSITION` | WALLET → TOKEN_POSITION | Wallet holds position |
| `POSITION_IN` | TOKEN_POSITION → POOL/VAULT | Position is in pool or vault |

### 2. `Backend Architecture/aether-backend/main.py`

Mounted the web3 router onto the main FastAPI application:

```python
from services.web3 import web3_router
app.include_router(web3_router, prefix="/v1/web3", tags=["web3"])
```

---

## Architecture

### Layer 1: Coverage Spine

```
POST /v1/web3/observations/batch
  → validate observations (max 500 per batch)
  → for each observation:
      → classify_contract(to_address, chain_id)
      → attribute_domain(domain)
      → classify method selector → canonical action
      → build_graph_from_observation()
      → store observation + classification result
  → return batch results
```

### Layer 2: Real-Time Enrichment

```
POST /v1/web3/classify/contract   → on-demand contract classification
POST /v1/web3/classify/method     → method selector → canonical action
POST /v1/web3/classify/domain     → domain → app/protocol attribution
POST /v1/web3/classify/observation → full single-observation pipeline
```

### Layer 3: Protocol/App Depth

```
CRUD endpoints for all registry objects:
  chains, protocols, contracts, tokens, apps, domains,
  governance spaces, market venues, bridge routes,
  deployer entities, migrations

POST /v1/web3/contracts/{chain_id}/{address}/reclassify
  → update system assignment
  → create LATER_CLASSIFIED_AS edge
  → rebind downstream graph edges
```

### Layer 4: Internal Ontology

```
build_graph_from_observation() creates full graph topology:
  WALLET → USES_PROTOCOL → PROTOCOL
  WALLET → USES_APP → APP
  WALLET → TOUCHES_DOMAIN → FRONTEND_DOMAIN → FRONTS_PROTOCOL → PROTOCOL
  CONTRACT → INSTANCE_OF → CONTRACT_SYSTEM → PART_OF_SYSTEM → PROTOCOL
  WALLET → BRIDGES_VIA → BRIDGE_ROUTE
  WALLET → PARTICIPATES_IN → GOVERNANCE_SPACE
  WALLET → VOTES_ON → GOVERNANCE_PROPOSAL
  DEPLOYER_ENTITY → CONTROLS → CONTRACT
  PROTOCOL → DEPLOYED_ON → CHAIN
```

---

## Integration Points

| Integration | Description |
|------------|-------------|
| **BaseRepository (asyncpg PostgreSQL)** | All 13 registries extend BaseRepository. Uses asyncpg connection pool in production, in-memory dict storage for local/test mode. Auto-creates tables on first access. |
| **Neptune Graph** | Graph expansion adds vertices and edges to the existing Neptune graph store. New vertex/edge types registered in `graph.py` are recognized by the graph query engine. |
| **Lake Bronze Tier** | Observation batch ingestion follows the existing lake Bronze tier pattern. Raw observations stored in Bronze, classified results promoted through Silver/Gold tiers. |
| **Profile 360** | Profile service can query web3 registries to enrich wallet profiles with protocol exposure, app usage, domain activity, governance participation, and bridge activity. |
| **Population Service** | Population segmentation can use protocol family, chain, app category, governance participation, and bridge usage as segmentation dimensions. |
| **Expectation Engine** | Expectation baselines can incorporate protocol interaction frequency, cross-chain bridge patterns, governance voting regularity, and token holding stability. |

---

## Tests

All 106 existing tests pass with zero regressions. The web3 module does not break any existing functionality because:

- All new registries use their own table namespace (`web3_*`)
- New graph vertex/edge types are additive (no existing types modified)
- Router is mounted under `/v1/web3/` prefix with no path conflicts
- BaseRepository auto-creation is idempotent

---

## Deployment

No database migration is needed. The `BaseRepository` pattern used throughout the Aether backend auto-creates tables on first access. When the web3 module is first loaded:

1. Each registry checks for its table existence
2. If the table does not exist, it is created with the correct schema
3. Indexes are created for all lookup patterns (composite keys, foreign key references)
4. Seed data can be loaded via `POST /v1/web3/seed` (idempotent)

---

## Known Limits

| Limit | Details |
|-------|---------|
| **Dune Datashare bulk ingestion** | Provider exists in the data provider layer, but the pipeline scheduling for periodic Dune query execution and result ingestion is not yet wired. Requires Dune API key configuration. |
| **DeFiLlama TVL auto-refresh** | Provider exists for fetching protocol TVL data from DeFiLlama, but the scheduled cron job for periodic refresh is not yet configured. Needs scheduling infrastructure. |
| **Ed25519 oracle signing** | Oracle signing for SVM (Solana), MoveVM (Sui/Aptos), and NEAR VM chains currently uses HMAC simulation rather than true Ed25519 signatures. Production deployment needs HSM-backed Ed25519 signing. |
| **Gold tier population triggers** | Web3 observations are ingested into Bronze tier but do not yet automatically trigger Gold tier population recalculation. Requires event bridge between observation ingestion and population refresh. |

---

## Intentionally Deferred

| Item | Rationale |
|------|-----------|
| **Dune scheduled bulk ingestion job** | Requires Dune API key and a curated query catalog as external prerequisites. The provider and ingestion pathway exist; only the scheduling job and query definitions are needed. |
| **DeFiLlama protocol TVL auto-refresh cron** | Simple to add once scheduling infrastructure is in place. The DeFiLlama provider already fetches TVL data on demand. |
| **CoinGecko price feed auto-update** | Same pattern as DeFiLlama. Provider exists, needs scheduled refresh job. |
| **Full Solana program classification** | SPL programs use a different instruction format than EVM method selectors. The classifier framework supports it, but the selector map for SPL programs needs to be built separately. |
| **NFT collection registry** | The `NFT_COLLECTION` vertex type exists in the graph ontology. A dedicated `NftCollectionRegistry` with collection metadata, floor price tracking, and holder enumeration is planned but not yet implemented. |
