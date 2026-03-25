# Web3 Coverage Ontology

> Canonical reference for the Aether Web3 object registry, taxonomy, confidence model, semantic event families, graph edge families, and migration-tracking model.
> Version: 1.0.0 | Date: 2026-03-25

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Registry Design Overview](#2-registry-design-overview)
3. [Shared Object Model Fields](#3-shared-object-model-fields)
4. [Registry Object Definitions](#4-registry-object-definitions)
   - 4.1 [Chain Registry](#41-chain-registry)
   - 4.2 [Protocol Registry](#42-protocol-registry)
   - 4.3 [Contract System Registry](#43-contract-system-registry)
   - 4.4 [Contract Instance Registry](#44-contract-instance-registry)
   - 4.5 [Token Registry](#45-token-registry)
   - 4.6 [App/dApp Registry](#46-appdapp-registry)
   - 4.7 [Frontend Domain Registry](#47-frontend-domain-registry)
   - 4.8 [Governance Space Registry](#48-governance-space-registry)
   - 4.9 [Market Venue Registry](#49-market-venue-registry)
   - 4.10 [Bridge Route Registry](#410-bridge-route-registry)
   - 4.11 [Deployer Entity Registry](#411-deployer-entity-registry)
   - 4.12 [Source Registry](#412-source-registry)
5. [Completeness States](#5-completeness-states)
6. [Confidence Model](#6-confidence-model)
7. [Chain / Protocol / App / Domain Taxonomy](#7-chain--protocol--app--domain-taxonomy)
8. [Canonical Action Families](#8-canonical-action-families)
9. [Graph Edge Families](#9-graph-edge-families)
10. [Migration-Tracking Model](#10-migration-tracking-model)
11. [Implementation Notes](#11-implementation-notes)

---

## 1. Design Principles

| Principle | Description |
|---|---|
| **Stable identity** | Every registry object carries a `stable_id` that never changes, even when the object is renamed, migrated, or deprecated. |
| **Multi-chain first** | All objects reference chains through `chain_id` foreign keys; no object assumes a single chain. |
| **Append-only provenance** | Observations are appended, never overwritten. Confidence and completeness are recomputed from the full provenance log. |
| **Source-tagged** | Every fact is tagged with the source that asserted it, enabling per-source confidence weighting. |
| **Migration-aware** | Objects can be deprecated or migrated while preserving full lineage to their successors. |
| **VM-agnostic actions** | On-chain actions are normalized into canonical action families that abstract across EVM, SVM, MoveVM, and other virtual machines. |

---

## 2. Registry Design Overview

The ontology is organized as a set of **typed registries**, each holding objects of a single kind. Every object conforms to a shared base schema (Section 3) and extends it with type-specific fields.

```
Source Registry
    |
    v
Chain Registry
    |
    +---> Protocol Registry
    |         |
    |         +---> Contract System Registry
    |         |         |
    |         |         +---> Contract Instance Registry
    |         |
    |         +---> Token Registry
    |         +---> Governance Space Registry
    |
    +---> App/dApp Registry
    |         |
    |         +---> Frontend Domain Registry
    |
    +---> Market Venue Registry
    +---> Bridge Route Registry
    +---> Deployer Entity Registry
```

Cross-registry references use stable foreign keys (`chain_id`, `protocol_id`, `system_id`, `entity_id`, etc.).

---

## 3. Shared Object Model Fields

Every registry object includes the following base fields.

| Field | Type | Required | Description |
|---|---|---|---|
| `stable_id` | `string (UUID v7)` | yes | Immutable identifier assigned at creation. Never reused. |
| `canonical_name` | `string` | yes | Current human-readable name. May change; `stable_id` remains fixed. |
| `aliases` | `string[]` | no | Alternative names, ticker symbols, former names. |
| `chain_linkage` | `chain_id[]` | conditional | Chains this object is associated with. Required for on-chain objects. |
| `version` | `uint32` | yes | Monotonically increasing version counter, incremented on every mutation. |
| `version_history` | `VersionEntry[]` | yes | Array of `{ version, changed_fields[], changed_by_source_id, changed_at }`. |
| `source_id` | `string` | yes | FK to Source Registry -- the source that last asserted or updated this record. |
| `source_tag` | `string` | no | Freeform tag for sub-source granularity (e.g., `"defillama:tvl"`, `"etherscan:abi"`). |
| `classification_confidence` | `float [0.0, 1.0]` | yes | How confident the system is in the object's type classification. |
| `identity_confidence` | `float [0.0, 1.0]` | conditional | How confident the system is that this object is correctly identified (applies to contracts, tokens, entities). |
| `source_confidence` | `float [0.0, 1.0]` | yes | Inherited from the Source Registry `confidence_baseline`, adjusted by freshness. |
| `completeness_status` | `CompletenessState` | yes | See Section 5. |
| `created_at` | `datetime (UTC)` | yes | Timestamp of first observation. |
| `updated_at` | `datetime (UTC)` | yes | Timestamp of most recent mutation. |
| `observed_at` | `datetime (UTC)` | yes | Timestamp of most recent external observation confirming this object still exists. |
| `status` | `enum` | yes | One of: `active`, `deprecated`, `migrated`. |
| `migrated_to_id` | `string` | conditional | If `status == migrated`, FK to the successor object. |
| `tags` | `string[]` | no | Freeform tags for ad-hoc classification. |
| `metadata` | `json` | no | Unstructured key-value store for fields not yet promoted to the schema. |

---

## 4. Registry Object Definitions

### 4.1 Chain Registry

Tracks every blockchain network the system covers.

| Field | Type | Required | Description |
|---|---|---|---|
| `chain_id` | `string` | yes | Stable identifier (e.g., `"ethereum"`, `"base"`, `"solana"`). For EVM chains, matches the CAIP-2 namespace where possible. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Ethereum Mainnet"`). |
| `chain_family` | `enum` | yes | One of: `evm`, `svm`, `bitcoin`, `movevm`, `near`, `tvm`, `cosmos`, `other`. |
| `vm_type` | `string` | yes | Virtual machine identifier (e.g., `"evm"`, `"sealevel"`, `"movevm"`, `"cosmwasm"`). |
| `evm_chain_id` | `uint64` | conditional | Numeric EVM chain ID. Required when `chain_family == evm`. |
| `native_token` | `string` | yes | Symbol of the native gas token (e.g., `"ETH"`, `"SOL"`). |
| `native_token_id` | `string` | no | FK to Token Registry for the native token. |
| `block_explorer_url` | `string` | no | Primary block explorer base URL. |
| `rpc_default` | `string` | no | Default public RPC endpoint. |
| `genesis_date` | `date` | no | Date the chain launched its mainnet. |
| `network_type` | `enum` | yes | `mainnet` or `testnet`. |
| `consensus_mechanism` | `string` | no | e.g., `"pos"`, `"pow"`, `"dpos"`, `"tendermint"`. |
| `parent_chain_id` | `string` | no | FK to parent chain for L2/L3 rollups. |
| `rollup_type` | `enum` | no | `optimistic`, `zk`, `validium`, `none`. |
| `da_layer` | `string` | no | Data availability layer (e.g., `"ethereum"`, `"celestia"`, `"eigenda"`). |
| `finality_seconds` | `uint32` | no | Estimated time to finality. |
| `status` | `enum` | yes | `active`, `deprecated`. |

#### Initial Seed Chains

| stable_id | canonical_name | chain_family | evm_chain_id | native_token |
|---|---|---|---|---|
| `ethereum` | Ethereum Mainnet | evm | 1 | ETH |
| `base` | Base | evm | 8453 | ETH |
| `arbitrum-one` | Arbitrum One | evm | 42161 | ETH |
| `optimism` | OP Mainnet | evm | 10 | ETH |
| `polygon` | Polygon PoS | evm | 137 | POL |
| `bnb-chain` | BNB Chain | evm | 56 | BNB |
| `gnosis` | Gnosis Chain | evm | 100 | xDAI |
| `solana` | Solana | svm | -- | SOL |
| `bitcoin` | Bitcoin | bitcoin | -- | BTC |
| `hyperliquid` | Hyperliquid L1 | evm | 999 | HYPE |
| `monad` | Monad | evm | TBD | MON |
| `sei` | Sei | evm | 1329 | SEI |
| `unichain` | Unichain | evm | TBD | ETH |
| `avalanche` | Avalanche C-Chain | evm | 43114 | AVAX |
| `fantom` | Fantom Opera | evm | 250 | FTM |
| `zksync-era` | zkSync Era | evm | 324 | ETH |
| `linea` | Linea | evm | 59144 | ETH |
| `scroll` | Scroll | evm | 534352 | ETH |
| `mantle` | Mantle | evm | 5000 | MNT |
| `blast` | Blast | evm | 81457 | ETH |
| `mode` | Mode Network | evm | 34443 | ETH |
| `celo` | Celo | evm | 42220 | CELO |
| `moonbeam` | Moonbeam | evm | 1284 | GLMR |
| `aurora` | Aurora | evm | 1313161554 | ETH |

---

### 4.2 Protocol Registry

Tracks every on-chain protocol (DeFi, NFT, gaming, etc.).

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol_id` | `string` | yes | Stable identifier (e.g., `"uniswap"`, `"aave"`). |
| `canonical_name` | `string` | yes | Human name. |
| `aliases` | `string[]` | no | Alternative names. |
| `protocol_family` | `enum` | yes | One of: `dex`, `lending`, `bridge`, `staking`, `governance`, `nft-marketplace`, `gaming`, `depin`, `payments`, `prediction-market`, `rwa`, `stablecoin`, `yield-aggregator`, `derivatives`, `insurance`, `launchpad`. |
| `protocol_subfamily` | `string` | no | Finer classification (e.g., `"amm"`, `"orderbook"`, `"clob"`, `"cdp"`, `"money-market"`). |
| `protocol_version` | `string` | no | Version label (e.g., `"v2"`, `"v3"`, `"v4"`). |
| `chains` | `chain_id[]` | yes | All chains this protocol is deployed on. |
| `primary_chain` | `chain_id` | no | The chain where the protocol originated or has the most TVL. |
| `contract_systems` | `system_id[]` | no | FK to Contract System Registry. |
| `website` | `string` | no | Official website URL. |
| `docs_url` | `string` | no | Documentation URL. |
| `governance_space_id` | `string` | no | FK to Governance Space Registry. |
| `deployer_entity_id` | `string` | no | FK to Deployer Entity Registry. |
| `tvl_source` | `string` | no | Source identifier for TVL data (e.g., `"defillama:uniswap"`). |
| `audit_reports` | `AuditEntry[]` | no | Array of `{ auditor, date, url, scope }`. |
| `license` | `string` | no | Code license (e.g., `"BUSL-1.1"`, `"MIT"`, `"GPL-3.0"`). |
| `status` | `enum` | yes | `active`, `deprecated`, `migrated`. |
| `migrated_to_id` | `string` | conditional | FK to successor protocol if `status == migrated`. |

---

### 4.3 Contract System Registry

Groups related contract instances into a logical system within a protocol on a specific chain.

| Field | Type | Required | Description |
|---|---|---|---|
| `system_id` | `string` | yes | Stable identifier. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Uniswap V3 Core (Ethereum)"`). |
| `protocol_id` | `string` | yes | FK to Protocol Registry. |
| `chain_id` | `string` | yes | FK to Chain Registry. |
| `contract_instances` | `instance_id[]` | yes | FK array to Contract Instance Registry. |
| `role` | `enum` | yes | One of: `router`, `factory`, `vault`, `pool`, `token`, `governance`, `proxy`, `registry`, `oracle`, `bridge`, `rewards`, `fee-collector`, `access-control`, `other`. |
| `abi_hash` | `bytes32` | no | Keccak256 hash of the canonical ABI. |
| `verified_source` | `boolean` | no | Whether source code is verified on an explorer. |
| `source_url` | `string` | no | URL to verified source code. |
| `deployer_address` | `string` | no | Address that deployed the system's primary contract. |
| `deployment_tx` | `string` | no | Transaction hash of the initial deployment. |

---

### 4.4 Contract Instance Registry

Tracks individual smart contract deployments.

| Field | Type | Required | Description |
|---|---|---|---|
| `instance_id` | `string` | yes | Stable identifier. |
| `address` | `string` | yes | On-chain address (hex for EVM, base58 for Solana, etc.). |
| `chain_id` | `string` | yes | FK to Chain Registry. |
| `system_id` | `string` | no | FK to Contract System Registry. |
| `protocol_id` | `string` | no | FK to Protocol Registry (denormalized for query convenience). |
| `role` | `enum` | yes | Same enum as Contract System `role`. |
| `label` | `string` | no | Human-readable label (e.g., `"USDC/ETH 0.3% Pool"`). |
| `deployed_at` | `datetime` | no | Block timestamp of deployment. |
| `deployed_by` | `string` | no | Deployer address. |
| `deployment_tx` | `string` | no | Deployment transaction hash. |
| `bytecode_hash` | `bytes32` | no | Keccak256 of deployed bytecode. |
| `is_proxy` | `boolean` | yes | Whether this contract is a proxy pattern. |
| `proxy_type` | `enum` | conditional | `transparent`, `uups`, `beacon`, `diamond`, `minimal`, `other`. Required if `is_proxy == true`. |
| `implementation_address` | `string` | conditional | Current implementation address. Required if `is_proxy == true`. |
| `implementation_history` | `ImplementationEntry[]` | no | Array of `{ address, upgraded_at, tx_hash }`. |
| `status` | `enum` | yes | `active`, `paused`, `destroyed`, `migrated`. |
| `migrated_to_id` | `string` | conditional | FK to successor instance if `status == migrated`. |

---

### 4.5 Token Registry

Tracks fungible and non-fungible tokens.

| Field | Type | Required | Description |
|---|---|---|---|
| `token_id` | `string` | yes | Stable identifier. |
| `symbol` | `string` | yes | Ticker symbol (e.g., `"USDC"`, `"UNI"`). |
| `name` | `string` | yes | Full token name. |
| `chain_id` | `string` | yes | FK to Chain Registry. |
| `address` | `string` | conditional | Contract address. Omitted for native tokens. |
| `standard` | `enum` | yes | `ERC20`, `ERC721`, `ERC1155`, `SPL`, `BEP20`, `native`, `CW20`, `FA`, `other`. |
| `decimals` | `uint8` | conditional | Token decimals. Required for fungible tokens. |
| `protocol_id` | `string` | no | FK to Protocol Registry (e.g., protocol that issues the token). |
| `is_stablecoin` | `boolean` | yes | Whether this token is pegged to a fiat currency or basket. |
| `stablecoin_peg` | `string` | conditional | Peg target (e.g., `"USD"`, `"EUR"`). Required if `is_stablecoin == true`. |
| `stablecoin_type` | `enum` | conditional | `fiat-backed`, `crypto-backed`, `algorithmic`, `hybrid`. Required if `is_stablecoin == true`. |
| `is_wrapped` | `boolean` | yes | Whether this is a wrapped representation of another token. |
| `underlying_token_id` | `string` | conditional | FK to the unwrapped token. Required if `is_wrapped == true`. |
| `is_lp_token` | `boolean` | no | Whether this token represents a liquidity position. |
| `is_receipt_token` | `boolean` | no | Whether this token represents a deposit receipt (e.g., aTokens, cTokens). |
| `coingecko_id` | `string` | no | CoinGecko API identifier. |
| `cmc_id` | `string` | no | CoinMarketCap identifier. |
| `total_supply_source` | `string` | no | Source for total supply data. |
| `logo_url` | `string` | no | URL to token logo. |
| `canonical_bridge_token_ids` | `token_id[]` | no | Bridged equivalents of this token on other chains. |

---

### 4.6 App/dApp Registry

Tracks user-facing applications that compose one or more protocols.

| Field | Type | Required | Description |
|---|---|---|---|
| `app_id` | `string` | yes | Stable identifier. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Uniswap Interface"`, `"MetaMask"`). |
| `aliases` | `string[]` | no | Alternative names. |
| `protocols` | `protocol_id[]` | no | FK array to Protocol Registry. |
| `frontend_domains` | `domain_id[]` | no | FK array to Frontend Domain Registry. |
| `frontend_sites` | `string[]` | no | Legacy: raw domain strings before domain registry linkage. |
| `category` | `enum` | yes | One of: `wallet`, `exchange`, `dex-aggregator`, `portfolio-tracker`, `governance-dashboard`, `nft-marketplace`, `bridge-ui`, `explorer`, `analytics`, `social`, `messaging`, `identity`, `developer-tool`, `other`. |
| `platform` | `enum[]` | no | `web`, `ios`, `android`, `desktop`, `browser-extension`, `cli`. |
| `deployer_entity_id` | `string` | no | FK to Deployer Entity Registry. |
| `chains` | `chain_id[]` | no | Chains supported by the app. |
| `open_source` | `boolean` | no | Whether the app frontend is open source. |
| `source_repo` | `string` | no | URL to source code repository. |

---

### 4.7 Frontend Domain Registry

Tracks web domains associated with dApps and protocols.

| Field | Type | Required | Description |
|---|---|---|---|
| `domain_id` | `string` | yes | Stable identifier. |
| `domain` | `string` | yes | Fully qualified domain (e.g., `"app.uniswap.org"`). |
| `app_id` | `string` | no | FK to App/dApp Registry. |
| `protocol_ids` | `protocol_id[]` | no | FK array to Protocol Registry. |
| `chain_ids` | `chain_id[]` | no | Chains accessible through this frontend. |
| `verified` | `boolean` | yes | Whether domain ownership has been verified against protocol/app records. |
| `verification_method` | `string` | no | How verification was performed (e.g., `"dns-txt"`, `"ens"`, `"manual"`). |
| `first_seen` | `datetime` | no | First observation timestamp. |
| `last_seen` | `datetime` | no | Most recent observation timestamp. |
| `ssl_issuer` | `string` | no | SSL certificate issuer. |
| `is_phishing` | `boolean` | no | Whether this domain has been flagged as a phishing site. |
| `flagged_by` | `string[]` | no | Sources that flagged this domain. |

---

### 4.8 Governance Space Registry

Tracks governance systems and spaces.

| Field | Type | Required | Description |
|---|---|---|---|
| `space_id` | `string` | yes | Stable identifier. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Uniswap Governance"`). |
| `protocol_id` | `string` | yes | FK to Protocol Registry. |
| `platform` | `enum` | yes | `snapshot`, `tally`, `onchain`, `governor-bravo`, `governor-alpha`, `compound-governor`, `openzeppelin-governor`, `custom`. |
| `chain_id` | `string` | conditional | FK to Chain Registry. Required for on-chain governance. |
| `token_id` | `string` | no | FK to Token Registry for the voting/governance token. |
| `quorum_threshold` | `string` | no | Quorum requirement (raw value or percentage). |
| `proposal_threshold` | `string` | no | Minimum tokens to submit a proposal. |
| `voting_delay` | `uint32` | no | Blocks or seconds before voting starts. |
| `voting_period` | `uint32` | no | Duration of voting in blocks or seconds. |
| `timelock_address` | `string` | no | Address of the timelock controller. |
| `delegate_count` | `uint32` | no | Number of active delegates. |
| `proposal_count` | `uint32` | no | Total proposals submitted. |
| `snapshot_space_ens` | `string` | conditional | ENS name for Snapshot spaces (e.g., `"uniswap.eth"`). |

---

### 4.9 Market Venue Registry

Tracks centralized and decentralized trading venues.

| Field | Type | Required | Description |
|---|---|---|---|
| `venue_id` | `string` | yes | Stable identifier. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Binance"`, `"Uniswap V3"`). |
| `venue_type` | `enum` | yes | `cex`, `dex`, `dex-aggregator`, `otc`, `derivatives`, `perpetuals`, `options`. |
| `chains` | `chain_id[]` | conditional | FK array. Required for DEX venues. |
| `protocol_id` | `string` | conditional | FK to Protocol Registry. Required for DEX venues. |
| `supported_pairs_count` | `uint32` | no | Number of trading pairs. |
| `api_provider` | `string` | no | API data source (e.g., `"ccxt"`, `"native"`). |
| `fee_structure` | `json` | no | Fee tiers and structure. |
| `kyc_required` | `boolean` | no | Whether KYC is required (CEX only). |
| `jurisdictions` | `string[]` | no | Operating jurisdictions. |

---

### 4.10 Bridge Route Registry

Tracks cross-chain bridge routes.

| Field | Type | Required | Description |
|---|---|---|---|
| `route_id` | `string` | yes | Stable identifier. |
| `bridge_protocol_id` | `string` | yes | FK to Protocol Registry (the bridge protocol). |
| `canonical_name` | `string` | no | Human label for the route (e.g., `"Ethereum -> Arbitrum via Stargate"`). |
| `source_chain_id` | `string` | yes | FK to Chain Registry. |
| `destination_chain_id` | `string` | yes | FK to Chain Registry. |
| `supported_tokens` | `token_id[]` | no | FK array of tokens that can be bridged on this route. |
| `avg_time_seconds` | `uint32` | no | Average bridge transfer time. |
| `min_amount` | `string` | no | Minimum bridge amount (in native units). |
| `max_amount` | `string` | no | Maximum bridge amount (in native units). |
| `fee_type` | `enum` | no | `flat`, `percentage`, `dynamic`. |
| `fee_value` | `string` | no | Fee amount or percentage. |
| `security_model` | `enum` | no | `multisig`, `optimistic`, `zk-proof`, `validator-set`, `native`. |
| `status` | `enum` | yes | `active`, `paused`, `deprecated`. |

---

### 4.11 Deployer Entity Registry

Tracks the teams, DAOs, multisigs, and individuals behind protocols.

| Field | Type | Required | Description |
|---|---|---|---|
| `entity_id` | `string` | yes | Stable identifier. |
| `canonical_name` | `string` | yes | Human name (e.g., `"Uniswap Labs"`, `"MakerDAO"`). |
| `type` | `enum` | yes | `team`, `multisig`, `dao`, `individual`, `foundation`, `unknown`. |
| `addresses` | `AddressEntry[]` | no | Array of `{ address, chain_id, label, role }`. |
| `protocols` | `protocol_id[]` | no | FK array of protocols this entity is associated with. |
| `known_members` | `MemberEntry[]` | no | Array of `{ name, role, public_profiles[] }`. Note: only publicly available information. |
| `incorporation_jurisdiction` | `string` | no | Legal jurisdiction. |
| `website` | `string` | no | Entity website. |
| `social_profiles` | `json` | no | Map of platform to handle (e.g., `{ "twitter": "@uniswap", "github": "Uniswap" }`). |

---

### 4.12 Source Registry

Tracks every data source the system uses, enabling per-source confidence weighting.

| Field | Type | Required | Description |
|---|---|---|---|
| `source_id` | `string` | yes | Stable identifier (e.g., `"etherscan"`, `"defillama"`, `"dune"`). |
| `canonical_name` | `string` | yes | Human name. |
| `source_type` | `enum` | yes | `rpc`, `explorer`, `dune`, `defillama`, `coingecko`, `sdk`, `manual`, `internal`, `subgraph`, `api`, `scraper`. |
| `confidence_baseline` | `float [0.0, 1.0]` | yes | Default confidence assigned to facts from this source. |
| `refresh_cadence` | `duration` | no | How often this source is polled (e.g., `"5m"`, `"1h"`, `"24h"`). |
| `chain_coverage` | `chain_id[]` | no | Chains this source covers. |
| `api_endpoint` | `string` | no | Base API URL. |
| `rate_limit` | `string` | no | Rate limit description (e.g., `"5 req/sec"`). |
| `requires_api_key` | `boolean` | no | Whether an API key is needed. |
| `data_lag_seconds` | `uint32` | no | Typical data lag from real-time. |
| `status` | `enum` | yes | `active`, `degraded`, `offline`, `deprecated`. |

---

## 5. Completeness States

Every registry object carries a `completeness_status` field representing how far along the normalization and classification pipeline the object has progressed. States are ordered; an object advances forward through them.

| State | Code | Description |
|---|---|---|
| **Raw Observed** | `raw_observed` | The object was detected from an on-chain event, log, or external feed. Only the address/identifier and chain are known. No classification has been applied. |
| **Minimally Normalized** | `minimally_normalized` | Basic fields have been populated: the address is checksummed, the chain is resolved, and a `stable_id` has been assigned. The object type may be inferred but is not yet confirmed. |
| **Partially Classified** | `partially_classified` | The object has been matched to a known type (e.g., ERC20 token, proxy contract) but not yet linked to a specific protocol or app. Some fields remain empty. |
| **Protocol Mapped** | `protocol_mapped` | The object has been linked to a protocol in the Protocol Registry. Contract role, protocol version, and related system are identified. |
| **App Mapped** | `app_mapped` | The object has been linked to an App/dApp in the App Registry. The user-facing context is known. |
| **Domain Mapped** | `domain_mapped` | The object has been associated with one or more frontend domains. Full user-facing context is established. |
| **High Confidence** | `high_confidence` | All applicable fields are populated, multiple sources agree, and both `classification_confidence` and `identity_confidence` exceed 0.85. |
| **Deprecated** | `deprecated` | The object is no longer active but is preserved for historical reference. |
| **Migrated** | `migrated` | The object has been superseded by a successor. The `migrated_to_id` field points to the replacement. |
| **Unknown Contract System** | `unknown_contract_system` | The object is a contract that has been observed interacting with known protocols but cannot be classified into any known contract system. Requires manual review or additional heuristics. |

### State Transitions

```
raw_observed
    |
    v
minimally_normalized
    |
    v
partially_classified
    |
    +---> protocol_mapped ---> app_mapped ---> domain_mapped ---> high_confidence
    |
    +---> unknown_contract_system (dead-end until reclassified)

Any state ---> deprecated
Any state ---> migrated
```

### Completeness Rules

1. An object **must not** skip states in the forward path (e.g., cannot go from `raw_observed` directly to `protocol_mapped`).
2. Transitions to `deprecated` or `migrated` are allowed from any state.
3. `unknown_contract_system` can transition back to `partially_classified` if new information arrives.
4. State transitions are logged in `version_history`.

---

## 6. Confidence Model

Every object carries three confidence dimensions plus freshness and provenance metadata.

### 6.1 Confidence Dimensions

| Dimension | Range | Description |
|---|---|---|
| `classification_confidence` | `[0.0, 1.0]` | Confidence that the object is correctly classified (e.g., that a contract is truly a "router" for a DEX). |
| `identity_confidence` | `[0.0, 1.0]` | Confidence that the object is correctly identified (e.g., that address `0xABC...` is truly Uniswap V3 Router). Applies to contracts, tokens, entities. |
| `source_confidence` | `[0.0, 1.0]` | Inherited from the Source Registry `confidence_baseline`, representing trust in the data source. |

### 6.2 Composite Confidence

The system computes a **composite confidence score** for each object:

```
composite_confidence = (
    w_classification * classification_confidence +
    w_identity * identity_confidence +
    w_source * source_confidence
) * freshness_decay(time_since_last_observation)
```

Default weights:
- `w_classification = 0.35`
- `w_identity = 0.35`
- `w_source = 0.30`

### 6.3 Freshness Decay

Confidence decays over time if the object is not re-observed.

```
freshness_decay(t) = max(0.5, 1.0 - (t / max_staleness))
```

Where:
- `t` = seconds since `observed_at`
- `max_staleness` = configurable per registry type (default: 7 days for tokens, 30 days for protocols, 90 days for chains)

The floor of 0.5 ensures that stale objects retain some confidence rather than being discarded.

### 6.4 Multi-Source Agreement

When multiple sources assert the same fact:

```
agreed_confidence = 1 - product(1 - source_confidence_i for each source i)
```

This approaches 1.0 as more independent sources agree.

### 6.5 Provenance Record

Every fact assertion is tracked with:

| Field | Type | Description |
|---|---|---|
| `source_id` | `string` | FK to Source Registry. |
| `source_tag` | `string` | Sub-source identifier. |
| `observed_at` | `datetime` | When the source provided this data. |
| `normalized_at` | `datetime` | When the system processed the observation. |
| `raw_payload_hash` | `bytes32` | Hash of the raw source response for audit. |
| `confidence_at_observation` | `float` | Source confidence at the time of observation. |

Provenance records are **append-only**. Historical provenance is never deleted.

---

## 7. Chain / Protocol / App / Domain Taxonomy

The ontology enforces a strict four-layer taxonomy that maps the Web3 stack from infrastructure to user-facing presentation.

```
Layer 1: CHAIN
    The blockchain network (infrastructure).
    Example: Ethereum, Solana, Base

        Layer 2: PROTOCOL
            The on-chain logic (smart contract system).
            Example: Uniswap V3, Aave V3, Lido
            - A protocol exists on one or more chains.
            - A protocol has one or more contract systems per chain.

                Layer 3: APP / dApp
                    The user-facing application.
                    Example: Uniswap Interface, MetaMask, Zapper
                    - An app composes one or more protocols.
                    - An app may operate across multiple chains.

                        Layer 4: FRONTEND DOMAIN
                            The web endpoint.
                            Example: app.uniswap.org, app.aave.com
                            - A domain belongs to one app.
                            - A domain may serve multiple protocols and chains.
```

### Taxonomy Rules

1. **Chain independence**: A protocol is conceptually independent of any single chain. The same protocol logic deployed on Ethereum and Arbitrum shares one `protocol_id` but has separate `system_id` entries per chain.

2. **Protocol composition**: An app can compose multiple protocols. For example, a DEX aggregator app routes through Uniswap, SushiSwap, and Curve.

3. **Domain uniqueness**: Each domain belongs to exactly one app. If a domain serves multiple protocols, those protocols are all composed by the same app.

4. **Chain families**: Chain families group chains by VM type, enabling VM-specific normalization logic:

| Chain Family | VM | Address Format | Tx Format |
|---|---|---|---|
| `evm` | EVM | 20-byte hex (0x...) | RLP-encoded |
| `svm` | Sealevel (Solana) | 32-byte base58 | Borsh-encoded |
| `bitcoin` | Bitcoin Script | bech32/base58check | Bitcoin tx |
| `movevm` | Move VM (Aptos/Sui) | 32-byte hex | BCS-encoded |
| `near` | NEAR VM | human-readable (alice.near) | Borsh-encoded |
| `tvm` | TON VM | 36-byte raw | Cell-encoded |
| `cosmos` | CosmWasm / Cosmos SDK | bech32 (cosmos1...) | Protobuf |

5. **Protocol families**: Every protocol is assigned exactly one `protocol_family` from the controlled vocabulary:

| Family | Description | Examples |
|---|---|---|
| `dex` | Decentralized exchange | Uniswap, Curve, Raydium |
| `lending` | Lending and borrowing | Aave, Compound, Morpho |
| `bridge` | Cross-chain bridge | Stargate, Across, Wormhole |
| `staking` | Liquid staking or native staking | Lido, Rocket Pool, Jito |
| `governance` | Governance-specific protocol | Snapshot, Tally |
| `nft-marketplace` | NFT trading | OpenSea, Blur, Magic Eden |
| `gaming` | On-chain gaming | Axie Infinity, Treasure |
| `depin` | Decentralized physical infrastructure | Helium, Render, Hivemapper |
| `payments` | Payment rails | Gnosis Pay, Sablier, Superfluid |
| `prediction-market` | Prediction markets | Polymarket, Azuro |
| `rwa` | Real-world assets | Ondo, Centrifuge, Maple |
| `stablecoin` | Stablecoin issuance | MakerDAO, Circle (USDC) |
| `yield-aggregator` | Yield optimization | Yearn, Beefy, Sommelier |
| `derivatives` | On-chain derivatives | dYdX, GMX, Synthetix |
| `insurance` | DeFi insurance | Nexus Mutual, InsurAce |
| `launchpad` | Token launch platforms | Pump.fun, Fjord Foundry |

---

## 8. Canonical Action Families

All on-chain actions are normalized into a controlled vocabulary of **canonical action families**. These abstract across VM-specific opcodes, function selectors, and instruction types.

| Action Family | Description | EVM Example | SVM Example |
|---|---|---|---|
| `transfer` | Move tokens between addresses | `ERC20.transfer()` | `spl_token::transfer` |
| `swap` | Exchange one token for another | `UniswapV3Router.exactInputSingle()` | `Raydium.swap()` |
| `add_liquidity` | Provide liquidity to a pool | `UniswapV2Router.addLiquidity()` | `Orca.deposit()` |
| `remove_liquidity` | Withdraw liquidity from a pool | `UniswapV2Router.removeLiquidity()` | `Orca.withdraw()` |
| `lend` | Supply assets to a lending protocol | `Aave.supply()` | `Solend.deposit()` |
| `borrow` | Borrow assets from a lending protocol | `Aave.borrow()` | `Solend.borrow()` |
| `repay` | Repay a borrowed position | `Aave.repay()` | `Solend.repay()` |
| `stake` | Lock tokens for staking rewards | `Lido.submit()` | `Marinade.deposit()` |
| `unstake` | Unlock staked tokens | `Lido.requestWithdrawals()` | `Marinade.unstake()` |
| `bridge` | Initiate a cross-chain transfer | `Stargate.swap()` | `Wormhole.transferTokens()` |
| `vote` | Cast a governance vote | `Governor.castVote()` | `spl_governance::cast_vote` |
| `delegate` | Delegate voting power | `ERC20Votes.delegate()` | `spl_governance::delegate` |
| `mint` | Create new tokens or NFTs | `ERC721.mint()` | `metaplex::create` |
| `burn` | Destroy tokens permanently | `ERC20.burn()` | `spl_token::burn` |
| `claim` | Claim rewards or airdrops | `MerkleDistributor.claim()` | `program.claim()` |
| `deposit` | Deposit into a vault or position | `Vault.deposit()` | `program.deposit()` |
| `withdraw` | Withdraw from a vault or position | `Vault.withdraw()` | `program.withdraw()` |
| `deploy_contract` | Deploy a new smart contract | `CREATE` / `CREATE2` opcode | `BPFLoader.deployProgram()` |
| `call_contract` | Generic contract interaction | `CALL` opcode | `program.instruction()` |
| `approve` | Approve token spending | `ERC20.approve()` | `spl_token::approve` |
| `list` | List an asset for sale | `Seaport.list()` | `MagicEden.list()` |
| `trade` | Execute an NFT/asset trade | `Seaport.fulfillOrder()` | `MagicEden.buy()` |
| `redeem` | Redeem a receipt token for underlying | `cToken.redeem()` | `program.redeem()` |

### Action Classification Rules

1. An on-chain transaction may map to **multiple** canonical actions (e.g., a swap that auto-bridges is both `swap` and `bridge`).
2. Unknown function calls default to `call_contract` with `classification_confidence < 0.5`.
3. Action classification is stored per-transaction, per-log-event, or per-instruction depending on the VM.
4. The `source_tag` on the action classification indicates which classifier produced it (e.g., `"4byte-directory"`, `"abi-match"`, `"ml-classifier"`).

---

## 9. Graph Edge Families

Semantic relationships between registry objects are modeled as typed directed edges. Each edge belongs to one of the following families.

### 9.1 Wallet-Centric Edges

| Edge Family | From | To | Description |
|---|---|---|---|
| `wallet_to_wallet` | Wallet | Wallet | Direct transfer between wallets. |
| `wallet_to_contract` | Wallet | Contract Instance | Wallet interacts with a contract. |
| `wallet_to_token` | Wallet | Token | Wallet holds or transacts a token. |
| `wallet_to_protocol` | Wallet | Protocol | Wallet has used a protocol (derived from wallet-to-contract + contract-to-protocol). |
| `wallet_to_app` | Wallet | App | Wallet has used an app (derived from wallet-to-protocol + protocol-to-app, or frontend attribution). |
| `wallet_to_domain` | Wallet | Frontend Domain | Wallet initiated a transaction from a specific frontend domain (requires frontend attribution). |
| `wallet_to_governance` | Wallet | Governance Space | Wallet has voted or delegated in a governance space. |
| `wallet_to_social` | Wallet | Social Profile | Wallet is linked to a social identity (ENS, Lens, Farcaster). |
| `wallet_to_exchange` | Wallet | Market Venue | Wallet has deposited to or withdrawn from an exchange. |
| `wallet_to_bridge` | Wallet | Bridge Route | Wallet has used a specific bridge route. |
| `wallet_to_rwa` | Wallet | Token (RWA) | Wallet holds a real-world asset token. |

### 9.2 Contract-Centric Edges

| Edge Family | From | To | Description |
|---|---|---|---|
| `contract_to_protocol` | Contract Instance | Protocol | Contract belongs to a protocol's contract system. |
| `contract_to_app` | Contract Instance | App | Contract is used by an app (derived from contract-to-protocol + protocol composition). |
| `contract_to_domain` | Contract Instance | Frontend Domain | Contract is accessible through a frontend domain. |
| `contract_to_deployer` | Contract Instance | Deployer Entity | Contract was deployed by an entity. |

### 9.3 Protocol-Centric Edges

| Edge Family | From | To | Description |
|---|---|---|---|
| `protocol_to_frontend` | Protocol | Frontend Domain | Protocol is served through a frontend. |
| `protocol_to_team` | Protocol | Deployer Entity | Protocol is built by an entity. |
| `protocol_to_governance` | Protocol | Governance Space | Protocol has a governance system. |
| `protocol_to_liquidity_venue` | Protocol | Market Venue | Protocol's token is traded on a venue. |
| `protocol_to_market_context` | Protocol | Market Data | Protocol is associated with market metrics (TVL, volume, fees). |

### Edge Metadata

Every edge instance carries:

| Field | Type | Description |
|---|---|---|
| `edge_id` | `string` | Unique identifier. |
| `edge_family` | `enum` | One of the families above. |
| `from_id` | `string` | FK to source object. |
| `to_id` | `string` | FK to target object. |
| `chain_id` | `string` | Chain where the relationship was observed. |
| `first_observed` | `datetime` | When the edge was first detected. |
| `last_observed` | `datetime` | When the edge was most recently confirmed. |
| `observation_count` | `uint32` | Number of times the edge has been observed. |
| `confidence` | `float [0.0, 1.0]` | Confidence in the edge's correctness. |
| `source_id` | `string` | FK to Source Registry. |
| `action_family` | `string` | Canonical action that created or reinforced this edge. |
| `metadata` | `json` | Edge-specific data (e.g., transfer amount, vote weight). |

---

## 10. Migration-Tracking Model

Protocol upgrades, forks, redeployments, and proxy updates are tracked as first-class migration events.

### Migration Record

| Field | Type | Required | Description |
|---|---|---|---|
| `migration_id` | `string` | yes | Stable identifier for the migration event. |
| `protocol_id` | `string` | yes | FK to Protocol Registry. |
| `from_version` | `string` | yes | Version label being migrated from (e.g., `"v2"`). |
| `to_version` | `string` | yes | Version label being migrated to (e.g., `"v3"`). |
| `from_contracts` | `instance_id[]` | yes | FK array of contract instances being retired. |
| `to_contracts` | `instance_id[]` | yes | FK array of contract instances being activated. |
| `from_systems` | `system_id[]` | no | FK array of contract systems being retired. |
| `to_systems` | `system_id[]` | no | FK array of contract systems being activated. |
| `migration_type` | `enum` | yes | `upgrade`, `fork`, `redeploy`, `proxy_update`, `chain_migration`, `governance_migration`. |
| `detected_at` | `datetime` | yes | When the system detected the migration. |
| `detected_by` | `string` | yes | Source or method that detected it (e.g., `"proxy_monitor"`, `"manual"`, `"defillama_tvl_shift"`). |
| `confirmed` | `boolean` | yes | Whether the migration has been confirmed by a human or high-confidence automated check. |
| `confirmation_source` | `string` | no | Who or what confirmed the migration. |
| `lineage_preserved` | `boolean` | yes | Whether the migration preserves the identity lineage (i.e., same protocol, new version vs. a true fork). |
| `description` | `string` | no | Human-readable description of what changed. |
| `announcement_url` | `string` | no | Link to official announcement. |
| `migration_tx` | `string` | no | Transaction hash that executed the migration (if applicable). |

### Migration Types

| Type | Description | Lineage Preserved |
|---|---|---|
| `upgrade` | Same protocol, new version. Contracts may or may not change. | Yes |
| `fork` | New protocol forked from an existing one. Different team or governance. | No (new protocol_id created) |
| `redeploy` | Same protocol, same version, but contracts redeployed (e.g., after a bug fix). | Yes |
| `proxy_update` | Proxy contract's implementation changed. Address stays the same. | Yes |
| `chain_migration` | Protocol moves primary activity from one chain to another. | Yes |
| `governance_migration` | Governance system changes (e.g., Snapshot to on-chain Governor). | Yes |

### Migration Effects

When a migration is confirmed:

1. **Source objects**: Set `status = migrated` and `migrated_to_id` pointing to successor.
2. **Successor objects**: Created with `completeness_status = protocol_mapped` (minimum) and linked back via `version_history`.
3. **Edge propagation**: Existing edges to source objects are duplicated to successor objects with `confidence = source_edge_confidence * 0.8` (reduced because the new context may differ).
4. **Token mapping**: If the migration involves token changes, `canonical_bridge_token_ids` and `underlying_token_id` fields are updated.

### Lineage Chain

Migrations form a directed acyclic graph (DAG) of protocol lineage:

```
Uniswap V1 --[upgrade]--> Uniswap V2 --[upgrade]--> Uniswap V3 --[upgrade]--> Uniswap V4
                                |
                                +--[fork]--> SushiSwap V1 --[upgrade]--> SushiSwap V2
```

The lineage chain is queryable by traversing `migrated_to_id` links forward or `migration.from_contracts` links backward.

---

## 11. Implementation Notes

### 11.1 ID Generation

- `stable_id` uses UUID v7 (time-ordered) for natural chronological sorting.
- Human-readable slugs (e.g., `"ethereum"`, `"uniswap"`) are stored as `canonical_name` slugified, used for convenience but never as primary keys.
- Cross-references always use `stable_id`, never slugs or addresses.

### 11.2 Storage Model

- Each registry maps to a dedicated table/collection.
- Provenance records are stored in a separate append-only table with FK to the parent object.
- Version history is stored inline for fast reads but also journaled for audit.

### 11.3 Indexing Strategy

| Index | Purpose |
|---|---|
| `(chain_id, address)` | Fast lookup of contracts and tokens by on-chain address. |
| `(protocol_id, chain_id)` | Find all contract systems for a protocol on a chain. |
| `(entity_id)` | Find all protocols and contracts associated with an entity. |
| `(domain)` | Resolve a frontend domain to its app and protocols. |
| `(status, completeness_status)` | Find objects needing further classification. |
| `(updated_at)` | Identify recently changed objects for incremental sync. |
| `(composite_confidence)` | Prioritize low-confidence objects for review. |

### 11.4 Update Cadence

| Registry | Default Refresh | Trigger |
|---|---|---|
| Chain | 24h | New chain detected or chain status change. |
| Protocol | 1h | TVL shift, new deployment, governance event. |
| Contract System | On-event | New contract deployed, proxy upgraded. |
| Contract Instance | On-event | State change, migration, destruction. |
| Token | 15m | Price feed, supply change, new listing. |
| App/dApp | 24h | Frontend change, new protocol integration. |
| Frontend Domain | 24h | SSL change, DNS change, phishing flag. |
| Governance Space | 1h | New proposal, vote cast. |
| Market Venue | 1h | New pair listed, API status change. |
| Bridge Route | 1h | Route status change, new token support. |
| Deployer Entity | 24h | New deployment, governance change. |
| Source | 1h | Health check, latency change. |

### 11.5 Deprecation Policy

1. Objects are never physically deleted.
2. Deprecated objects retain all fields and provenance.
3. Deprecated objects are excluded from active queries by default but remain queryable with explicit filter.
4. After 365 days in deprecated state, objects may be archived to cold storage but remain restorable.

### 11.6 Conflict Resolution

When two sources disagree on a field value:

1. The source with higher `confidence_baseline` wins.
2. If confidence is equal, the more recent observation wins.
3. If both are equally recent, the field is flagged for manual review and the `classification_confidence` is reduced by 0.2.
4. All conflicting assertions are preserved in provenance for audit.

---

*End of Web3 Coverage Ontology v1.0.0*
