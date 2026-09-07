---
title: Deployment Profile Matrix
slug: productization/economic-interoperability-intelligence/deployment-profile-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/config/settings.py
  - .env.example
canonical_owner: platform@aether
source_hashes:
  ".env.example": "sha256:f2b34f3728895a4eac7f089e33e49c708f4dfb83989a4fdb7c08f7dbd571c0ba"
  "Backend Architecture/aether-backend/config/settings.py": "sha256:27f7b15209c14a857112fd3dfff3558ebd9e45c21def782d4dd63ccecfc0aa3c"
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

Env blocks are documented in `.env.example`
(`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
`KYBER_*_OPS_ENABLED`); `Settings.__post_init__` rejects incoherent
combinations (LayerZero without adapters).
