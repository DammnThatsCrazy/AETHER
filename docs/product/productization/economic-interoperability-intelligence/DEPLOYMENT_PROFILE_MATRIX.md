---
title: Deployment Profile Matrix
slug: productization/economic-interoperability-intelligence/deployment-profile-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/config/settings.py
  - config/environments/.env.example
canonical_owner: platform@aether
source_hashes:
  "config/environments/.env.example": "sha256:ddf6c04c4f42e49d017c7624a2554abbc282cde8719e5db6273f112d9d787955"
  "services/api/config/settings.py": "sha256:f7e9f04196ded6c4f4fa3a2ceb9fb80008483f39b7c6ef2834a102e2ea7a5225"
---

# Deployment Profile Matrix

All flags default OFF; enabling is per-capability and per-domain.

| Capability | Local (in-memory) | Staging | Production |
|---|---|---|---|
| Stablecoin ingestion/valuation/flows | ✅ works (in-memory stores) | Postgres via Alembic | blocked on staging validation |
| Stablecoin finality (live chains) | fixture-driven only | needs RPC credentials | blocked |
| Derivatives runtime + simulator | ✅ full conformance locally | Postgres via Alembic | blocked on venue adapters |
| Derivatives streams | local asyncio transport | Kafka topics not provisioned | blocked |
| Interop lifecycle/correlation | ✅ fixture-driven | Postgres via Alembic | blocked |
| Public agent marketplace catalog | OFF by default; bounded parser tests | opt-in observer with durable store | opt-in observer with durable store |
| LayerZero live scanning | ❌ (CREDENTIAL_GATED) | needs per-chain RPC | blocked |
| Gold materialization | in-memory GoldRepository | ClickHouse not provisioned | blocked |
| Frontend surfaces | ✅ against local backend | flag-gated | flag-gated |

Env blocks are documented in `config/environments/.env.example`
(`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
`AETHER_AGENT_MARKETPLACE_CATALOG_*`,
`KYBER_*_OPS_ENABLED`); `Settings.__post_init__` rejects incoherent
combinations (LayerZero without adapters).
