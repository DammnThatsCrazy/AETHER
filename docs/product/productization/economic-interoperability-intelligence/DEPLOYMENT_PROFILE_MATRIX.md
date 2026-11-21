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
  "config/environments/.env.example": "sha256:058e146412b243d493f04872ab2d504a793bc10859474f6141867e027656480f"
  "infra/aws/terraform/modules/ecs/main.tf": "sha256:867cc96ca6b3b0020680e4b9402ed3462a0e4191b61b2fc374d03d44a606fc08"
  "infra/aws/terraform/modules/secrets/main.tf": "sha256:29607ea44951c132385a375626cb9dafd213a9f26fb87ce8d1694b6fd74524da"
  "infra/aws/terraform/modules/secrets/outputs.tf": "sha256:5c5a051e56e3e00f811c86663f6a2e8a9f8fd34df133723fef76e7ea1338f816"
  "infra/aws/terraform/modules/secrets/rotation.tf": "sha256:c6c06da21c6ccd01468741102529c59a17ffc0e0b9c230df08d49869a3858589"
  "scripts/bootstrap_aws_secrets.py": "sha256:ae5e53eee269aad3fa855ad2b2494d99738b32532fe6101cf9d2f86134f81d9c"
  "scripts/lib/preflight_env.py": "sha256:e465c85941e68d7e0375827096a51a2783a03e99606d137090a4bec9582fbc94"
  "scripts/release/check_staging_task_definition_contract.py": "sha256:4b3f1c7c917710b145b834163c3136d0915279f57d58315cd4ba9fa201a0566b"
  "services/api/config/settings.py": "sha256:4dbf92aee80b79b23df58288eba721af626ef74dae5a8ad84c39699bb642699e"
---

# Deployment Profile Matrix

All flags default OFF; enabling is per-capability and per-domain.

| Capability | Local (in-memory) | Staging | Production |
|---|---|---|---|
| Stablecoin ingestion/valuation/flows | ✅ works (in-memory stores) | Postgres via Alembic | blocked on staging validation |
| Stablecoin finality (live chains) | fixture-driven only | needs RPC credentials | blocked |
| Derivatives runtime + simulator | ✅ full conformance locally | Postgres via Alembic | blocked on venue adapters |
| Derivatives streams | local asyncio transport | Kafka topics not provisioned | blocked |
| Prediction-market observation (Polymarket, Kalshi) | ✅ normalize + store, in-memory | Postgres via Alembic; venue flags; submitted payloads only, no live polling | blocked |
| Interop lifecycle/correlation | ✅ fixture-driven | Postgres via Alembic | blocked |
| Public agent marketplace catalog | OFF by default; bounded parser tests | opt-in observer with durable store | opt-in observer with durable store |
| LayerZero live scanning | ❌ (CREDENTIAL_GATED) | needs per-chain RPC | blocked |
| Gold materialization | in-memory GoldRepository | ClickHouse not provisioned | blocked |
| Frontend surfaces | ✅ against local backend | flag-gated | flag-gated |

Env blocks are documented in `config/environments/.env.example`
(`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_PREDICTION_MARKET_*`, `AETHER_INTEROP_*`,
`AETHER_AGENT_MARKETPLACE_CATALOG_*`, `AETHER_AGENT_BEHAVIOR_JOBS_*`,
`KYBER_*_OPS_ENABLED`); `Settings.__post_init__` rejects incoherent
combinations (LayerZero without adapters).

When wallet identity verification is enabled, non-local deployments must set
`IDENTITY_VERIFICATION_TOKEN_KEY`. AWS ECS reads it from
`aether/identity-verification-token-key` and mounts the previous value from
`aether/identity-verification-token-key-previous` during rotation. The
`identity_verification_secrets_enabled` Terraform input gates both task mounts.
For the first rollout, apply with the input false, populate both secrets, then
create a fresh reviewed plan with it true; the promotion workflow verifies
both `AWSCURRENT` versions using metadata only. Keep both key materials
available until stored wallet replay subjects have been re-encrypted or
expired; see the [secret rotation runbook](../../../operations/SECRET-ROTATION.md).
