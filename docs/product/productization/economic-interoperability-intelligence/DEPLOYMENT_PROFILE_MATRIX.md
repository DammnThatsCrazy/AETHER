---
title: Deployment Profile Matrix
slug: productization/economic-interoperability-intelligence/deployment-profile-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/config/settings.py
  - config/environments/.env.example
canonical_owner: platform@aether
source_hashes:
  "config/environments/.env.example": "sha256:e23cb524843194e974d5ac68613c594dcb5f0712d8b65310a2123bf4a8271655"
  "services/backend/config/settings.py": "sha256:fe764b5c58609cf4f7e5a66bce005d79f533c6568bc6977a6ab4d42df0ae2b61"
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
| LayerZero live scanning | ❌ (CREDENTIAL_GATED) | needs per-chain RPC | blocked |
| Gold materialization | in-memory GoldRepository | ClickHouse not provisioned | blocked |
| Frontend surfaces | ✅ against local backend | flag-gated | flag-gated |

Env blocks are documented in `config/environments/.env.example`
(`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
`KYBER_*_OPS_ENABLED`); `Settings.__post_init__` rejects incoherent
combinations (LayerZero without adapters).
