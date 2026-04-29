# AETHER v-Next Build Specification

> Branch: `claude/explore-ml-improvements-Mr3Kz`
> Safety: zero breaking changes. Every capability additive, flag-gated, rollbackable.
> Retains: SDKs, agent automation, external data-provider APIs, Shiki graph management, Web2/Web3/x402.

## Design Principles

1. **Compose, don't duplicate.** Every new capability is a thin layer on existing services, not a parallel subsystem.
2. **Stream-first.** Use existing Kafka + WebSocket for real-time materialization. Batch only where streaming is architecturally impossible.
3. **Feature-store-first.** New intelligence surfaces extend `features/pipeline.py` with new feature families that automatically flow to existing `POST /v1/ml/predict`. No new serving infrastructure.
4. **One failure surface per capability.** When something breaks, exactly one file is the root cause.
5. **No research bets in v1.** Foundation Model pretraining, ZK circuits, PSI federation, DPO policy training — all deferred until live data volume and tenant count justify them. Instrument now, train later.

## What ships (6 capabilities)

Subsystem prefixes used below: `BE/` = `Backend Architecture/aether-backend/`, `ML/` = `ML Models/aether-ml/`, `AG/` = `Agent Layer/`, `SK/` = `apps/shiki/src/`, `PS/` = `packages/shared/`.

| # | Capability | Single failure surface | Extends |
|---|---|---|---|
| 1 | Bitemporal + Witness Signatures | `BE/shared/bitemporal/mixin.py` + `BE/middleware/witness_verifier.py` | `BE/shared/graph/graph.py`, ingestion middleware, `PS/events.ts` |
| 2 | Conformal Abstention + Explainability | `ML/common/src/conformal.py` | All 9 model `predict()` methods, `ML/serving/src/api.py` |
| 3 | Mission Graph (stream-materialized) | `AG/shared/graph/composer.py` + `ML/features/mission_features.py` | Attribution service, `AG/models/objectives.py`, graph edges |
| 4 | Agent Balance Sheet + EIP-712 Attestations | `ML/features/balance_sheet_features.py` + `BE/services/oracle/` extension | `BE/shared/scoring/trust_score.py`, EventBus, KIRA, oracle |
| 5 | Coverage Autopilot (AL router) | `AG/agent_controller/learning/al_router.py` | ReviewBatcher, StagedMutation (`AG/shared/graph/staging.py`) |
| 6 | Collusion Motif Detection | `BE/shared/motifs/library.py` | `BE/shared/graph/graph.py` traversals, `BE/services/fraud/`, `BE/shared/scoring/anomaly_config.py` |

Per-capability ADRs live in [`adr/`](./adr/) — each one pins the interface, build sequence, failure modes, and rollback path.

## What's deferred (instrument now, build later)

| Item | Why deferred | What we instrument now |
|---|---|---|
| Foundation Model pretrain | Needs billions of graph walks; data volume insufficient | Build the walker (`foundation/walker.py`), don't pretrain |
| DPO policy trainer | Needs 1k+ ReviewBatch labeled outcomes | Collect labels with every ReviewBatch outcome event |
| ZK attestations (Groth16/Plonk) | Circuit audit 2-3 months + external firm | Ship EIP-712 signed attestations now (90% of value) |
| PSI Federation | Needs 3+ tenants opted in; malicious-security PSI is a research project | Scaffold `services/federation/` with types only |
| Hawkes TPP | Must prove NLL beats LSTM before replacing | Build model, register as challenger, don't integrate into TRIGGER |
| Causal GNN (DoWhy/EconML) | Complex; requires explicit causal graph specification | Extend existing Shapley attribution weights instead |

## What's added vs. the prior spec (gaps filled)

| Gap | How addressed |
|---|---|
| Graph query performance / Neptune cache | `shared/graph/composer.py` includes Redis-cached materialized subgraph views |
| Model decision rollback | `StagedMutation` gains `rollback_mutation_id` linking to reverse mutation |
| SDK schema versioning | `packages/shared/schema-version.ts` already exports schema version; witness types added as optional extension |
| Real-time alerting for Shiki | New Shiki `alerts-panel.tsx` component consuming existing WebSocket in `analytics/` |
| Cold-start for new tenants | Conformal wrapper abstains on all predictions until calibration set reaches minimum size; explicit cold-start flag per tenant |
| Data drift monitoring | New feature in `features/pipeline.py`: PSI (Population Stability Index) per feature family, alert on drift > threshold |
| Cost circuit breakers | Extend existing `shared/rate_limit/budget_policies.py` with per-capability cost caps |
| Distributed tracing through KIRA | Propagate `objective_id` as OpenTelemetry trace context through entire agent lifecycle |
| Feature store versioning | `features/registry.py` already exists; add schema hash per feature family version |
| Explainability for reviewers | Conformal wrapper outputs `top_features` + `evidence_ids` linking to `StagedMutation.supporting_fact_ids` |
