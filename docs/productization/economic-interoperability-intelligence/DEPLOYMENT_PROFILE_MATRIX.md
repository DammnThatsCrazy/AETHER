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
last_synced_commit: "762619b6"
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
| Model runtime harness (`MODEL_RUNTIME_*`) | ✅ deterministic provider locally | flag-gated OFF (fail-closed) | flag-gated OFF (fail-closed) |

Env blocks are documented in `.env.example`
(`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
`KYBER_*_OPS_ENABLED`, `MODEL_RUNTIME_*`); `Settings.__post_init__` rejects
incoherent combinations (LayerZero without adapters). The model runtime
additionally enforces its own fail-closed rule in
`services/model_runtime/config.py`: enabling `MODEL_RUNTIME_ENABLED` in
staging/production requires a production-safe credential backend
(`env`/`aws_secrets`, never `in_memory`) and a real default provider (never
`deterministic`) — otherwise `ConfigError` at startup.
