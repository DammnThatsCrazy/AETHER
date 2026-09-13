---
title: Module Index
slug: archive/audits/module_index
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Aether Module Index v8.7.0

Complete inventory of all modules, services, packages, and system layers.

---

## Backend Services (31)

| # | Service | Prefix | Endpoints | Purpose | Category |
|---|---------|--------|-----------|---------|----------|
| 1 | admin | `/v1/admin` | 7 | Tenant management, API keys, billing | Core |
| 2 | agent | `/v1/agent` | 12 | Autonomous task orchestration, audit trail | Core |
| 3 | analytics | `/v1/analytics` | 6 | Event queries, dashboards, GraphQL, WebSocket | Core |
| 4 | analytics_automation | `/v1/analytics-automation` | 5 | Automated analytics pipelines | Core |
| 5 | attribution | `/v1/attribution` | 5 | Multi-touch attribution (5 models) | Core |
| 6 | behavioral | `/v1/behavioral` | 5 | 10 behavioral signal engines | Intelligence |
| 7 | campaign | `/v1/campaigns` | 7 | Campaign lifecycle, touchpoints | Core |
| 8 | commerce | `/v1/commerce` | 4 | Payments, agent hiring, fee elimination | Intelligence Graph |
| 9 | consent | `/v1/consent` | 4 | GDPR consent, DSR requests | Core |
| 10 | crossdomain | `/v1/crossdomain` | 34 | TradFi/Web2 accounts, instruments, trades, compliance, fusion | Cross-Domain |
| 11 | diagnostics | `/v1/diagnostics` | 6 | System diagnostics, health | Core |
| 12 | expectations | `/v1/expectations` | 10 | Negative-space intelligence, contradictions | Intelligence |
| 13 | fraud | `/v1/fraud` | 5 | 9-signal fraud scoring | Core |
| 14 | gateway | `/v1/health` | 5 | Health checks, root metadata, metrics | Core |
| 15 | identity | `/v1/identity` | 4 | Profile CRUD, identity merge, graph | Core |
| 16 | ingestion | `/v1/ingest` | 3 | SDK event intake, external feeds | Core |
| 17 | intelligence | `/v1/intelligence` | 5 | Wallet risk, protocol analytics, clusters | Intelligence Graph |
| 18 | lake | `/v1/lake` | 7 | Bronze/Silver/Gold medallion data lake | Intelligence Graph |
| 19 | ml_serving | `/v1/ml` | 4 | Model registry, prediction, features | Core |
| 20 | notification | `/v1/notifications` | 5 | Webhooks, alerts | Core |
| 21 | onchain | `/v1/onchain` | 5 | On-chain actions, RPC gateway, chain listener | Intelligence Graph |
| 22 | oracle | `/v1/oracle` | 4 | Multi-chain cryptographic proofs (7 VMs) | Intelligence Graph |
| 23 | population | `/v1/population` | 11 | Macro-to-micro group intelligence | Intelligence |
| 24 | profile | `/v1/profile` | 8 | Profile 360 omniview | Intelligence |
| 25 | providers | `/v1/providers` | 8 | BYOK provider gateway (24 adapters) | Intelligence Graph |
| 26 | resolution | `/v1/resolution` | 8 | Identity resolution, clustering, admin review | Core |
| 27 | rewards | `/v1/rewards` | 8 | On-chain reward distribution | Core |
| 28 | rwa | `/v1/rwa` | 13 | Real-world asset intelligence | Intelligence |
| 29 | traffic | `/v1/traffic` | 5 | Traffic source tracking | Core |
| 30 | web3 | `/v1/web3` | 29 | Web3 coverage registries, classification, migration | Web3 Coverage |
| 31 | x402 | `/v1/x402` | 4 | HTTP 402 micropayment capture | Intelligence Graph |

## Shared Infrastructure

| Module | Location | Purpose |
|--------|----------|---------|
| auth | `shared/auth/auth.py` | API key validation (SHA-256 + Redis), JWT, TenantContext |
| cache | `shared/cache/cache.py` | Redis (redis.asyncio) with in-memory fallback |
| events | `shared/events/events.py` | Kafka (aiokafka) event producer/consumer |
| graph | `shared/graph/graph.py` | Neptune (gremlinpython) — 52 vertex types, 90+ edge types |
| logger | `shared/logger/logger.py` | Structured JSON logging, Prometheus metrics |
| privacy | `shared/privacy/` | Data classification, access control, DSAR, retention |
| providers | `shared/providers/` | 24 provider adapters, BYOK key vault |
| rate_limit | `shared/rate_limit/limiter.py` | Redis INCR+EXPIRE token bucket |

## SDKs (4 platforms)

| SDK | Location | Language | Version |
|-----|----------|----------|---------|
| Web | `packages/web/` | TypeScript | 8.7.0 |
| iOS | `packages/ios/` | Swift | 8.7.0 |
| Android | `packages/android/` | Kotlin | 8.7.0 |
| React Native | `packages/react-native/` | TypeScript | 8.7.0 |

## Data / Lake / ML

| Module | Location | Purpose |
|--------|----------|---------|
| Data Lake | `Data Lake Architecture/` | Medallion architecture (Bronze/Silver/Gold) |
| Data Ingestion | `Data Ingestion Layer/` | TypeScript SDK event processing |
| ML Models | `ML Models/aether-ml/` | 9 model configs, 2 scorers, feature pipeline |

## Infrastructure / Deployment

| Module | Location | Purpose |
|--------|----------|---------|
| AWS Deployment | `AWS Deployment/aether-aws/` | Terraform, CloudFormation, Lambda |
| CI/CD | `cicd/aether-cicd/` | GitHub Actions stages, SDK publishing |
| Docker Compose | `docker-compose.yml` | Local development stack |
| Staging Deploy | `deploy/staging/` | Docker Compose staging + bootstrap |
| Observability | `deploy/observability/` | Grafana dashboards, Prometheus alerts |

## Compliance / Security

| Module | Location | Purpose |
|--------|----------|---------|
| GDPR & SOC2 | `GDPR & SOC2/aether-compliance/` | Consent manager, DSR engine, audit |
| Privacy Control Plane | `shared/privacy/` | Classification, access control, retention |
| Extraction Defense | `security/model_extraction_defense/` | 6-component ML protection |
| Smart Contracts | `Smart Contracts/` | Solidity contracts, ABIs |

## Graph Vertex Types (52)

**Behavioral (8):** User, Session, PageView, Event, Device, Company, Campaign, ExternalData
**Identity (7):** DeviceFingerprint, IPAddress, Location, Email, Phone, Wallet, IdentityCluster
**Intelligence Graph (6):** Agent, Service, Contract, Protocol, Payment, ActionRecord
**Web3 Coverage (18):** Chain, Token, TokenPosition, Pool, Vault, Market, Strategy, App, FrontendDomain, GovernanceSpace, GovernanceProposal, BridgeRoute, NftCollection, DeployerEntity, MarketVenue, ContractSystem, ProtocolVersion, UnknownContract
**Cross-Domain (16):** Institution, FinancialAccount, Instrument, Order, Execution, Position, BalanceSnapshot, CashMovement, ComplianceAction, BusinessEvent, Household, LegalEntity, FundEntity, Desk, Sector, CorporateAction

## Provider Adapters (24)

**Blockchain RPC (4):** QuickNode, Alchemy, Infura, Generic RPC
**Block Explorer (2):** Etherscan, Moralis
**Social (2):** Twitter/X, Reddit
**Analytics (1):** Dune Analytics
**Market Data (4):** DeFiLlama, CoinGecko, Binance, Coinbase
**Prediction Markets (2):** Polymarket, Kalshi
**Web3 Social (2):** Farcaster, Lens Protocol
**Identity Enrichment (2):** ENS, GitHub
**Governance (1):** Snapshot
**On-chain Intelligence (2):** Chainalysis, Nansen
**TradFi Data (2):** Massive, Databento
