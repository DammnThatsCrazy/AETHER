# Aether Execution Tracker

All remaining work tracked in one file. No workstream exists outside this tracker.

## Phase 0 — Baseline Lock
- [x] P0.1 Freeze baseline — tests pass, compile clean, docs valid
- [x] P0.2 Create EXECUTION_TRACKER.md

## Phase 1 — Provider Completion and Canonical Raw Ingestion
- [x] P1.1 Lens connector — GraphQL via api-v2.lens.dev, health check via ping query
- [x] P1.2 GitHub connector — REST API v3, PAT auth, repo/org/user events
- [x] P1.3 ENS connector — The Graph subgraph, GraphQL wallet-to-name resolution
- [x] P1.4 Snapshot connector — GraphQL governance data, proposals/votes/spaces
- [x] P1.5 Chainalysis path — real client, blocked_by_contract when unconfigured
- [x] P1.6 Nansen path — real client, blocked_by_contract when unconfigured
- [x] P1.7 Massive path — real client, blocked_by_contract when unconfigured
- [x] P1.8 Databento path — real client, blocked_by_contract when unconfigured
- [ ] P1.9 Canonicalize all provider outputs — source_tag, idempotency
- [ ] P1.10 Validate PROVIDER_MATRIX.md against implementation
- **Gate:** All providers implemented or explicitly marked blocked by credentials/contracts

## Phase 2 — Lake Formation and Durability
- [ ] P2.1 Bronze repositories — immutable raw persistence
- [ ] P2.2 Silver repositories — validation, dedup, normalization
- [ ] P2.3 Gold repositories — metrics, features, highlights
- [ ] P2.4 Wire ingestion endpoints to Bronze
- [ ] P2.5 Replay and backfill support
- [ ] P2.6 Source-tag auditing
- [ ] P2.7 Rollback by source_tag/run
- [ ] P2.8 Compaction and retention
- [ ] P2.9 Data quality checks
- **Gate:** Bronze/Silver/Gold real, replayable, auditable, quality-checked

## Phase 3 — Feature Materialization
- [ ] P3.1 Offline feature tables
- [ ] P3.2 Scheduled feature jobs
- [ ] P3.3 Redis online feature serving
- [ ] P3.4 Offline/online feature parity checks
- [ ] P3.5 Feature lineage documentation
- **Gate:** Feature tables reproducible, scheduled, versioned

## Phase 4 — Graph Mutations and Graph-Derived Scoring
- [ ] P4.1 Enable graph flags in staging
- [ ] P4.2 Validate graph store wiring
- [ ] P4.3 Edge builders (wallet↔wallet, wallet↔protocol, wallet↔social, etc.)
- [ ] P4.4 Graph mutation jobs (batch, incremental, replay)
- [ ] P4.5 Wire graph-derived scoring
- [ ] P4.6 Graph audit and repair procedures
- **Gate:** Graph mutations and graph-derived features stable

## Phase 5 — ML Training, Registration, and Rollback
- [ ] P5.1 Training dataset builders
- [ ] P5.2 Scheduled training jobs
- [ ] P5.3 Drift-trigger hooks
- [ ] P5.4 Model artifact registration
- [ ] P5.5 Model versioning
- [ ] P5.6 Model rollback
- [ ] P5.7 Wire all 11 model tasks
- [ ] P5.8 ML observability
- **Gate:** At least one model trains, registers, serves, rolls back

## Phase 6 — Intelligence Outputs
- [ ] P6.1 Wallet risk scores
- [ ] P6.2 Protocol analytics
- [ ] P6.3 Identity clusters
- [ ] P6.4 Anomaly alerts
- [ ] P6.5 Output lineage documentation

## Phase 7 — Deployment Hardening
- [ ] P7.1 End-to-end smoke test
- [ ] P7.2 Operational runbooks
- [ ] P7.3 Deployment readiness checks
- [ ] P7.4 One-command acceptance path
- [ ] P7.5 Final production review
