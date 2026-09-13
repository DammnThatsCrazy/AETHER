# Stablecoin Intelligence Implementation Map

## PR1 delivered

- Backend contracts: `services/backend/services/stablecoins/models.py`
- Deployment registry: `services/backend/services/stablecoins/registry.py`
- Durable repositories: `services/backend/repositories/stablecoin_repos.py`
- Additive migration: `services/backend/migrations/2026_07_stablecoin_intelligence_foundation.sql`
- SDK shared contract: `packages/shared/stablecoin.ts`
- Source-of-truth docs: `docs/source-of-truth/STABLECOIN_DOMAIN.md`, `STABLECOIN_EVENT_REGISTRY.md`, `STABLECOIN_METRICS.md`
- Tests: `tests/unit/test_stablecoin_intelligence_foundation.py`

## PR2-PR4 dependency gates

- PR2 may build ingestion, Bronze/Silver promotion, verification, finality, reconciliation, Gold jobs, support intelligence, and alerts on these contracts.
- PR3 may build identity, graph, attribution, Profile360, public APIs, Aether UI, webhooks, and exports only after PR2 produces verified facts.
- PR4 may build Kyber operations, Olympus benchmarks, commercialization, security hardening, observability, staging validation, and release gates only after PR3 surfaces are contract-backed.

## PR2 delivered

- Ingestion and normalization: `services/backend/services/stablecoins/ingestion.py`
- Finality/reorganization correction foundation: `services/backend/services/stablecoins/finality.py`
- Reconciliation: `services/backend/services/stablecoins/reconciliation.py`
- Gold accounting materializer: `services/backend/services/stablecoins/aggregation.py`
- Support state machine: `services/backend/services/stablecoins/support.py`
- Alert evaluator: `services/backend/services/stablecoins/alerts.py`
- PR2 tests: `tests/unit/test_stablecoin_intelligence_pr2_pipeline.py`

## PR2 provider-execution layer

Delivered after the PR2 foundation:

- `services/backend/services/stablecoins/providers.py`: tenant-scoped provider execution runner with dry-run, explicit provider failure health, checkpoints, and execution-scoped rollback.
- `services/backend/services/stablecoins/rpc_observer.py`: read-only EVM receipt verification with tenant scope, deployment/log matching, receipt status handling, and threshold-based finality updates.
- `services/backend/services/stablecoins/solana_observer.py`: read-only Solana transaction verification with tenant scope, SPL mint matching, transaction-error handling, and slot-threshold finality updates.
- `services/backend/services/stablecoins/polling.py`: connector-neutral provider/finality polling scheduler with durable checkpoints and failed-provider health records.
- `scripts/stablecoin_backfill.py`: connector-neutral JSON backfill CLI supporting the required dry-run, tenant, asset, deployment, chain, source, window, limit, resume, verify-only, and rollback-tag arguments.
- `stablecoin_provider_health`, `stablecoin_ingestion_checkpoints`, and `stablecoin_polling_checkpoints` additive tables.
- Tests: `tests/unit/test_stablecoin_intelligence_provider_execution.py`, `tests/unit/test_stablecoin_intelligence_rpc_verification.py`, and `tests/unit/test_stablecoin_intelligence_solana_verification.py`, and `tests/unit/test_stablecoin_intelligence_polling_scheduler.py`.

## PR2 boundaries

PR2 now includes deterministic service foundations and a first provider-execution layer for connector-supplied rows. Concrete external connector implementations, production scheduler runtime wiring, real provider credential rollout, explorer/RPC disagreement comparison, Dune scheduling, Moralis, CoinGecko, DeFiLlama, graph projection workers, Profile360 product UI, Kyber UI, webhook delivery, export delivery, and commercial metering remain later workstreams.

## PR4 operations/governance slice

Delivered:

- `services/backend/services/stablecoins/operations.py`: Kyber tenant health, lineage, and audited remediation-intent capture.
- `services/backend/services/stablecoins/governance.py`: capability decisions, read-only metering, and governed benchmark publication.
- `services/backend/services/stablecoins/release_readiness.py`: explicit `NOT_READY` release matrix with blockers.
- `stablecoin_remediation_audit` and `stablecoin_market_benchmarks` additive tables.
- Release evidence reports under `reports/stablecoin-intelligence/`.

Boundaries:

- PR3 tenant-facing surfaces are still absent on this branch.
- PR4 does not implement operator UI, remediation workers, live Olympus market feeds, billing enforcement, staging validation, backup/restore, load, chaos, or GA readiness.

## PR3 identity/graph/Profile360 slice

Delivered:

- `services/backend/services/stablecoins/identity.py`: tenant-scoped wallet identity links with evidence, confidence, consent context, and unresolved wallet responses.
- `services/backend/services/stablecoins/graph_projector.py`: deterministic, tenant-scoped graph projection outbox records without direct Neptune mutation.
- `services/backend/services/stablecoins/profile360.py`: backend Profile360 composer that surfaces finalized payment summaries, unresolved wallets, unattributed activity, provenance, and drill links.
- `services/backend/services/stablecoins/routes.py`: feature-flagged tenant APIs for `/v1/profile/{profile_id}/stablecoins` and `/v1/stablecoins/observations`.
- Additive identity-link and graph-projection-outbox tables.

Boundaries:

- Frontend Stablecoin Intelligence product surfaces are not implemented in this slice.
- Webhook/export delivery and graph projection workers remain deferred.
