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
  "config/environments/.env.example": "sha256:763aa0ccd35c1796f6959868435e775b576d9683e31c62fad9ca475099a30085"
  "services/api/config/settings.py": "sha256:120775873521c402933065c3073b8f2d242589bca26b095f982952f6bb392f42"
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

When wallet identity verification is enabled, non-local deployments must set
`IDENTITY_VERIFICATION_TOKEN_KEY`. Rotate it with the active/previous key and
ID variables so stored wallet replay subjects remain decryptable; see the
[secret rotation runbook](../../../operations/SECRET-ROTATION.md).
