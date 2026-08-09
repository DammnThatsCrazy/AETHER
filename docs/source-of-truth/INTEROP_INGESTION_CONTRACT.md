---
title: Interoperability Ingestion Contract
slug: source-of-truth/interop-ingestion-contract
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/interop/correlation.py
  - Backend Architecture/aether-backend/services/interop/lifecycle.py
  - Backend Architecture/aether-backend/services/interop/scan_worker.py
  - Backend Architecture/aether-backend/services/interop/publisher.py
  - Backend Architecture/aether-backend/services/interop/reconcile.py
  - Backend Architecture/aether-backend/services/interop/security.py
  - Backend Architecture/aether-backend/services/interop/graph_wiring.py
  - Backend Architecture/aether-backend/services/interop/metering.py
  - Backend Architecture/aether-backend/services/interop/providers/base.py
  - Backend Architecture/aether-backend/services/interop/providers/transport.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_v2.py
  - Backend Architecture/aether-backend/services/interop/providers/layerzero_abi.py
canonical_owner: platform@aether
last_synced_commit: 0df66e8c
---

# Interoperability Ingestion Contract

## Provider adapters

`InteropProviderAdapter` ABC: `scan(checkpoint)`, `decode_log`, `derive_path`,
`operational_state`, plus an honest `ImplementationStatus` descriptor. Every
adapter inherits `OperationalFieldsMixin`, which supervises `scan` as a
durable, resumable loop over the adapter's `_scan_cycle`: it initialises the
checkpoint, counts decode failures through `_decode_safely`, advances `runtime`
telemetry on success/failure, and counts reorg observations. The
`operational_state` view — `configured`, `credential_status`, `reachable`,
`latest_cursor`, `latest_observation_at`, `lag`, `decode_failures`,
`reorg_count`, `reconciliation_conflicts`, `dead_letter_count`, `last_success`,
`last_failure` — is derived from the persisted checkpoint, never a live call.

Registered adapters (all **seven** are `CREDENTIAL_GATED` — fixture-proven
decode + correlation, live scanning requires wired RPC endpoints, and none
claim provider-live status): **LayerZero V2**, **Wormhole**, **Axelar**,
**Chainlink CCIP**, **Hyperlane**, **IBC**, **deBridge**. Each ships an honest
`security_model()` for offline structural policy snapshots (LayerZero V2's
snapshot path additionally requires `eth_call` access to its receive
libraries, so its snapshots are skipped offline rather than fabricated).

## RPC transport

`services/interop/providers/transport.py` implements the injectable
`RpcClient` (EVM `eth_*` JSON-RPC: `EvmJsonRpcClient`) and `IbcRpcClient`
(CometBFT JSON-RPC: `CometBftRpcClient`) protocol seams with real HTTP callers
built on httpx. Live endpoints are external and credential-gated: clients are
constructed only at wiring time from configured endpoint URLs (secret-ref) and
are never touched in credentialless local runs — the adapter `scan` guard still
raises `NotImplementedError` while `rpc` is `None`. HTTP 429 raises
`RpcRateLimited` (with `retry_after` when a `Retry-After` header is present);
protocol-native rate-limit exceptions subclass it, so a live scan participates
in the same in-cycle resume contract fixture scans already exercise.

## Supervised scan worker

`services/interop/scan_worker.py` `ScanWorker.run_cycle` drives one adapter
through: load checkpoint -> supervised `scan` -> correlation ingest ->
dead-letter quarantine -> reconciliation evidence -> graph projection ->
security policy snapshot -> checkpoint persist -> event publish -> metering.
A cycle reports `skipped` (credential-gated guard), `rate_limited`
(`RpcRateLimited`), `error` (other failures, checkpoint not advanced), or `ok`.
The checkpoint (per-network cursors + `runtime` telemetry) is persisted under
`interop_provider_checkpoints.evidence` keyed `(tenant_id, provider_id,
network_id='*')`; a worker killed mid-cycle restarts from the last persisted
checkpoint — never from scratch — so the cursor never moves backward and a
re-run of the same checkpoint is idempotent. `build_interop_scan_coro` is the
poll loop registered in the runtime worker spec (gated on
`settings.interop.adapters_enabled`).

## Usage metering

`services/interop/metering.py` records billable `metering_evidence` records for
the dimensions the interop plane exposes: `interop_observations_ingested`,
`interop_messages_correlated`, `interop_reconciliation_runs`,
`interop_security_policy_snapshots`, and `interop_provider_cycles`.
`ScanWorker.run_cycle` calls `record_cycle_usage` after a successful cycle.
Metering is best-effort (a metering failure never breaks the scan flow) and
fail-closed on duplicates: a restart replay of the same checkpoint reproduces
the same dimension-scoped `dedupe_key`
(`interop:<dimension>:<provider>:<highest_cursor>`), which the metering service
records but marks non-billable — so checkpoint re-runs and retries can never
double-bill. Dimensions are measured here; pricing is not invented by this
service.

## Correlation & reorg

`CorrelationEngine.ingest_observation` joins source/verify/deliver legs in any
order under the provider correlation key, applies the lifecycle FSM, and emits
`interop_message_correlated` exactly once — when both source and destination
references are first present together. Scanning is checkpointed per
(provider, chain) with a confirmation horizon; in-horizon observations are
provisional, and a parent-hash mismatch (or head receding below the cursor) on
re-scan yields a `reorged` observation, rewinds the cursor below the fork, and
emits `interop_message_reorged`. Re-scanning the rewound window re-observes the
same event without duplicating the message row (conflict-key dedup). Aether
never relays, retries, or recovers messages.

## Event publish seam

`services/interop/publisher.py` `InteropEventPublisher` converts the canonical
`make_event()` dicts emitted by correlation, reconciliation and security into
shared `Event` objects and hands them to the shared `EventProducer`. The broker
(Kafka/SNS-SQS/staging, in-memory in local dev) is external; the publish call
is real on every environment, and a failed publish raises after the producer's
retries so checkpoints do not advance past an undelivered batch. Fine-grained
registry `event_name`s are carried in the payload; topics reuse the shared
`CANONICAL_ACTIVITY_INGESTED` plus the two notification-bound interop topics.

## Reconciliation evidence

`services/interop/reconcile.py` compares the source and destination legs of
one correlated message, records any variance as an immutable reconciliation
record plus `interop_reconciliation_variance_detected`, and advances the
adapter checkpoint's `reconciliation_conflicts` counter (surfaced via
`operational_state`). Observation-only: a variance is never repaired by Aether.

## Graph projection & security snapshots

`services/interop/graph_wiring.py` wires the previously-dead
`build_topology_mutations` / `build_message_mutations` builders into the scan
pipeline (provider/gateway/path topology in public scope, plus SENT_VIA_PATH /
SECURED_BY_POLICY edges), persisting through `foundation.persist_mutations`.
Gated on `settings.interop.graph_enabled`; a disabled projector is a no-op.
`SecurityPolicyService.snapshot_policy` is called at scan time by
`scan_security_policy_snapshots` (gated on the caller's flag), storing
content-hashed, immutable snapshots and emitting
`interop_security_policy_changed` on hash drift.

## Downstream consumption

Profile360 (`services/profile360_workers/workers.py`) `InteropActivityProjector`
listens on the interop topics and labels entity behavior profiles with
`cross_chain_activity`, keyed on the entity reference carried in
`interop_message_correlated` (initiator entity / source application); interop
events without an entity are skipped — a profile is never fabricated. The
silver projector (`services/silver/projectors/interop_projector.py`) projects
interop registry events into `silver_interop_facts`.
