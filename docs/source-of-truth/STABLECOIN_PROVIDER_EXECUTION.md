# Stablecoin Provider Execution and Backfill

Stablecoin provider execution is tenant-scoped and observation-first. Configured connectors pass rows into `StablecoinProviderIngestionRunner`, which validates tenant identity, source execution identity, deployment registry resolution, and source manifest identity before writing through the canonical Bronze to Silver to observation pipeline.

## Execution identity

Every execution requires `tenant_id`, `provider`, `source_execution_id`, and `source_manifest_id`. Repeated executions are distinct, checkpoints are keyed by tenant/provider/execution, and provider health records include rows observed, accepted, rejected, and explicit failure state.

## Dry run and verification

`scripts/stablecoin_backfill.py` supports `--dry-run`, `--verify-only`, `--tenant-id`, `--asset-id`, `--deployment-id`, `--chain-id`, `--source`, `--start`, `--end`, `--limit`, `--resume-from`, `--rollback-tag`, `--source-execution-id`, `--source-manifest-id`, and `--input-json`. Dry-run and verify-only modes do not write Bronze, Silver, observation, health, or checkpoint records.

## Rollback

Rollback is scoped by tenant, provider, and source execution. It deletes only matching Bronze, Silver, and durable observation rows, then marks the matching checkpoint `rolled_back`. Rollback does not mutate graph state directly.

## Provider failures

Provider failures are recorded as failed health records. A timeout, credential error, or provider exception must not be represented as a healthy empty dataset.
