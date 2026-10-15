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
  - infra/aws/terraform/modules/ecs/main.tf
  - infra/aws/terraform/modules/secrets/main.tf
  - infra/aws/terraform/modules/secrets/outputs.tf
  - infra/aws/terraform/modules/secrets/rotation.tf
  - scripts/bootstrap_aws_secrets.py
  - scripts/lib/preflight_env.py
  - scripts/release/check_staging_task_definition_contract.py
canonical_owner: platform@aether
source_hashes:
  "config/environments/.env.example": "sha256:763aa0ccd35c1796f6959868435e775b576d9683e31c62fad9ca475099a30085"
  "infra/aws/terraform/modules/ecs/main.tf": "sha256:b4f885f14cd5a6fcda8d3b0ccc4b150dfcb097b0be9de28a78ddb5eb520e55f5"
  "infra/aws/terraform/modules/secrets/main.tf": "sha256:29607ea44951c132385a375626cb9dafd213a9f26fb87ce8d1694b6fd74524da"
  "infra/aws/terraform/modules/secrets/outputs.tf": "sha256:5c5a051e56e3e00f811c86663f6a2e8a9f8fd34df133723fef76e7ea1338f816"
  "infra/aws/terraform/modules/secrets/rotation.tf": "sha256:c6c06da21c6ccd01468741102529c59a17ffc0e0b9c230df08d49869a3858589"
  "scripts/bootstrap_aws_secrets.py": "sha256:ae514213615b5fd8d71bbe0d2cb3354369459f7b3c315f803448202a3c5f119c"
  "scripts/lib/preflight_env.py": "sha256:e465c85941e68d7e0375827096a51a2783a03e99606d137090a4bec9582fbc94"
  "scripts/release/check_staging_task_definition_contract.py": "sha256:9fdbde3d52bffc8ba703483eb86fe0c17d8353f62140f760eaf20439a36ade88"
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
`IDENTITY_VERIFICATION_TOKEN_KEY`. AWS ECS reads it from
`aether/identity-verification-token-key` and mounts the previous value from
`aether/identity-verification-token-key-previous` during rotation. Keep both
key materials available until stored wallet replay subjects have been
re-encrypted or expired; see the [secret rotation runbook](../../../operations/SECRET-ROTATION.md).
