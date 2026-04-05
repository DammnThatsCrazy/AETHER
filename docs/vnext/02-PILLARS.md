# 02 — Pillars (Full Detail)

Each pillar below has: purpose, feature flag name, new files, API contract, data model, acceptance criteria, and explicit backward-compatibility guarantees. Build order defined in `07-BUILD-SEQUENCE.md`.

**Preservation guarantee** (applies to every pillar):
- SDK event ingestion pipeline remains fully functional
- Agent controller automation (KIRA, LOOP, BOLT, TRIGGER, 8 controllers) remains intact
- External data-provider API feeds continue working unchanged
- Shiki operator console remains the primary graph-management UI (extended with new views, never replaced)

---

## P0 — Foundation

**Purpose:** Establish cryptographic + temporal substrate that every other pillar depends on.

**Feature flag:** Always on (foundation; not flaggable).

**Deliverables:**
1. Bitemporal schema additions to all Neptune vertices/edges and Gold-tier tables
2. Witness signature verifier middleware on ingestion
3. SBOM + signed artifact pipeline
4. Conformal abstention wrapper for all 9 existing models
5. Doc drift reconciliation (README 35 vs arch 31 routers)

**New files:**
- `Backend Architecture/aether-backend/shared/bitemporal/schema.py`
- `Backend Architecture/aether-backend/shared/bitemporal/as_of_query.py`
- `Backend Architecture/aether-backend/shared/provenance/signatures.py`
- `Backend Architecture/aether-backend/shared/provenance/hash_chain.py`
- `Backend Architecture/aether-backend/middleware/witness_verifier.py`
- `ML Models/aether-ml/common/src/conformal.py`
- `security/provenance/sdk_verifier.py`
- `.github/workflows/sbom.yml`
- `scripts/sign_artifacts.sh`

**Migration approach:** Additive columns on existing tables; no existing column touched. Default values backfilled lazily.

**API contract:** None net-new (middleware). Signed events accepted via new headers; unsigned events accepted with degraded weight during grace period.

**Acceptance criteria:**
- All existing tests still pass
- New bitemporal columns present on all relevant tables
- Signature verifier rejects tampered payloads; accepts valid ones
- Conformal wrapper returns `(score, lower, upper, abstain)` for every model
- SBOM generated for every container build; cosign signatures attached
- `docs/ARCHITECTURE.md` and `README.md` router counts reconciled

**Preservation:** SDK continues to post to `/v1/batch`; existing unsigned path works (grace period). External data-provider APIs unchanged. Agents unaffected.

---

## P1 — Causal Mission Graph

**Purpose:** First-class `Mission` object binding goal → delegated tasks → sub-agents → services → payments (fiat/x402/on-chain) → protocol actions → outcome, with causal edge weights and replay.

**Feature flag:** `vnext.mission_graph.enabled` (per-tenant).

**New files:**
- `Backend Architecture/aether-backend/services/missions/__init__.py`
- `Backend Architecture/aether-backend/services/missions/routes.py`
- `Backend Architecture/aether-backend/services/missions/models.py`
- `Backend Architecture/aether-backend/services/missions/reconstruct.py`
- `Backend Architecture/aether-backend/services/missions/causal_weights.py`
- `Backend Architecture/aether-backend/services/missions/replay.py`
- `Backend Architecture/aether-backend/shared/graph/mission_vertex.py`
- `ML Models/aether-ml/features/mission_features.py`
- `apps/shiki/src/views/vnext/missions/` (UI)

**Data model (new vertex):**
- `Mission`: `{mission_id, initiator_actor_id, declared_objective, started_at, completed_at, status, realized_value, unrealized_value, friction_score, completion_probability}`
- New edge types: `PART_OF_MISSION`, `CAUSED_OUTCOME`, `ASSISTED_OUTCOME`, `ENABLED_OUTCOME`, `ECONOMIC_DEPENDENCY`

**API contract (new, under `/v2/missions/`):**
- `POST /v2/missions/reconstruct` — given objective_id, build Mission from events
- `GET /v2/missions/{id}` — full mission graph
- `GET /v2/missions/{id}/replay?as_of=<timestamp>` — bitemporal replay
- `GET /v2/missions/{id}/counterfactual?swap=<actor_id>` — what-if analysis
- `GET /v2/missions/search?initiator_id=&status=&time_range=` — list missions

**Acceptance criteria:**
- Reconstruction handles missions with 50+ events across 3+ payment rails
- Causal weights sum to 1.0 per outcome
- Replay at any historical timestamp returns consistent state
- Counterfactual swap produces valid delta report
- Mission query P95 latency <800ms
- Conformal wrapper emits confidence band on every causal weight

**Preservation:** Existing `/v1/attribution/*` endpoints unchanged. Mission graph composes from existing events + graph edges; does not require new data sources. External data-provider feeds continue flowing into events that become Mission parts.

---

## P2 — Counterfactual Intelligence Runtime

**Purpose:** Absence-aware scoring. Detects expected-but-absent actions; ranks interventions; measures recovery in closed loop.

**Feature flag:** `vnext.counterfactual.enabled` + sub-flags per surface.

**New files:**
- `Backend Architecture/aether-backend/services/counterfactual/routes.py`
- `Backend Architecture/aether-backend/services/counterfactual/baselines.py`
- `Backend Architecture/aether-backend/services/counterfactual/gaps.py`
- `Backend Architecture/aether-backend/services/counterfactual/interventions.py`
- `Backend Architecture/aether-backend/services/counterfactual/evaluator.py`
- `ML Models/aether-ml/features/counterfactual_features.py`
- `apps/shiki/src/views/vnext/gaps/` (Gap Inbox UI)

**Data model (new vertex):**
- `Gap`: `{gap_id, entity_id, expected_action, expected_edge, gap_opened_at, unrealized_value, recoverability, deviation_from_self, deviation_from_peer, deviation_from_twin, intervention_id, closed_at, recovery_outcome}`

**API contract (new, under `/v2/gaps/` and `/v2/interventions/`):**
- `GET /v2/gaps?entity_id=&cohort=&min_unrealized=` — ranked gaps for entity/cohort
- `GET /v2/gaps/{id}` — gap detail + suggested interventions
- `POST /v2/interventions/{gap_id}/execute` — trigger intervention (agents or humans)
- `GET /v2/interventions/{id}/outcome` — closed-loop measurement

**Acceptance criteria:**
- Baselines compile from Gold tier nightly; stored per archetype
- Gap detection runs incrementally on Silver tier
- Intervention ranking returns conformal-gated confidence
- False-positive rate <15% in pilot evaluation
- Recovery measurement loop records outcomes with bitemporal provenance

**Preservation:** Extends `/v1/expectations/*` and `/v1/behavioral/*` — does not replace them. Existing expectation signals continue flowing. Shiki's existing views remain; Gap Inbox is a new view.

---

## P3 — Agent Credit & Delegation Underwriting

**Purpose:** Per-agent balance sheet + dynamic authority bands + causal reputation propagation + ZK-portable attestations.

**Feature flag:** `vnext.agent_credit.enabled`, `vnext.authority_bands.enforced`, `vnext.attestations.issue`.

**New files:**
- `Backend Architecture/aether-backend/services/underwriter/routes.py`
- `Backend Architecture/aether-backend/services/underwriter/balance_sheet.py`
- `Backend Architecture/aether-backend/services/underwriter/authority_bands.py`
- `Backend Architecture/aether-backend/services/underwriter/attestations.py`
- `Backend Architecture/aether-backend/shared/crypto/eip712.py`
- `Backend Architecture/aether-backend/shared/crypto/zk_circuit.py`
- `Backend Architecture/aether-backend/shared/crypto/hsm_client.py`
- `ML Models/aether-ml/server/causal_trust.py`
- `ML Models/aether-ml/server/dpo_policy.py`
- `apps/shiki/src/views/vnext/agents/balance-sheet/` (UI)

**Data model (new vertices + edges):**
- `AgentBalanceSheet`: `{agent_id, calibration_error, rework_rate, spend_efficiency, hire_depth, rollback_involvement, authority_utilization, as_of}`
- `AuthorityBand`: `{agent_id, band_name, max_spend, max_hire_depth, max_onchain_value, expires_at}`
- `Attestation`: `{agent_id, threshold, proof_hash, chain_id, expires_at, revoked}`
- New edges: `HAS_BALANCE_SHEET`, `HAS_AUTHORITY`, `HAS_ATTESTATION`, `CAUSAL_TRUST_EDGE`

**API contract (new, under `/v2/agents/` and `/v2/attestations/`):**
- `GET /v2/agents/{id}/balance-sheet?as_of=` — bitemporal agent record
- `GET /v2/agents/{id}/authority` — current scoped authority
- `POST /v2/attestations/issue` — generate EIP-712/ZK attestation
- `GET /v2/attestations/{hash}/verify` — verification endpoint
- `POST /v2/attestations/{hash}/revoke` — on-chain revocation

**Acceptance criteria:**
- Balance sheet updates within 5 minutes of task outcome event
- Authority bands enforced at every agent action attempt by KIRA
- Causal GNN trust scores produced nightly via DoWhy/EconML
- EIP-712 attestations signed with HSM key; nonce + expiry + chain-id bound
- DPO trainer consumes ReviewBatch outcomes; retrains weekly

**Preservation:** Existing `TrustScoreComposite` unchanged; balance sheet wraps it. KIRA continues routing; now also consults authority bands. Existing hire-chain edges preserved; new `CAUSAL_TRUST_EDGE` is additive. Agent automation flow untouched — agents just gain scoped authority checks.

---

## P4 — Coverage Autopilot

**Purpose:** Self-healing graph via active-learning routed review queue + DPO-learned discovery/verification policy.

**Feature flag:** `vnext.coverage_autopilot.enabled`, `vnext.active_learning.route`, `vnext.dpo.policy_learning`.

**New files:**
- `Backend Architecture/aether-backend/services/coverage/routes.py`
- `Backend Architecture/aether-backend/services/coverage/debt_model.py`
- `Backend Architecture/aether-backend/services/coverage/sufficiency.py`
- `Agent Layer/agent_controller/learning/active_learning.py`
- `Agent Layer/agent_controller/learning/dpo_trainer.py`
- `Agent Layer/agent_controller/learning/information_gain.py`
- `Backend Architecture/aether-backend/shared/scoring/spectral.py`
- `apps/shiki/src/views/vnext/coverage/` (Debt Dashboard UI)

**Data model additions:**
- New field on `StagedMutation`: `expected_information_gain: float`
- New vertex type: `CoverageDebt` (per-registry debt metric)
- New edge: `REVIEWED_BY` (reviewer → mutation, outcome)

**API contract (new, under `/v2/coverage/`):**
- `GET /v2/coverage/debt` — current debt per registry/entity type
- `GET /v2/coverage/queue?prioritize_by=information_gain` — active-learning routed queue
- `POST /v2/coverage/feedback` — record approval outcome for AL retrain

**Acceptance criteria:**
- AL committee of 5 models trained on historical ReviewBatch outcomes
- Information-gain scoring routes top-N mutations to humans; rest auto-approved under policy cap
- Spectral Laplacian drift monitored weekly per IdentityCluster
- Auto-approval rate capped (default: 90% for Class 1/2 mutations, 0% for Class 3/4/5)
- DPO trainer retrains weekly; KIRA policy updated via safe deployment
- Review load drops ≥60% in pilot within 30 days

**Preservation:** Existing Discovery/Enrichment/Verification/Commit/Recovery/BOLT/TRIGGER controllers unchanged — Coverage Autopilot layers on top. StagedMutation flow preserved; AL just prioritizes the queue. Shiki's existing ReviewBatch UI remains primary; Coverage Dashboard is additive.

---

## P5 — Collusion & Synthetic Ecosystem Detection

**Purpose:** Graph motifs + temporal community anomaly + economic circularity + cross-surface contradiction.

**Feature flag:** `vnext.collusion.enabled`, `vnext.hypergraph.enabled`.

**New files:**
- `Backend Architecture/aether-backend/services/coordination/routes.py`
- `Backend Architecture/aether-backend/services/coordination/motifs.py`
- `Backend Architecture/aether-backend/services/coordination/temporal_community.py`
- `Backend Architecture/aether-backend/services/coordination/circularity.py`
- `Backend Architecture/aether-backend/shared/graph/hyperedge.py`
- `Backend Architecture/aether-backend/shared/motifs/library.py`
- `ML Models/aether-ml/server/hgnn.py` (Hypergraph Neural Network)
- `apps/shiki/src/views/vnext/collusion/` (UI)

**Data model:**
- New vertex type: `HyperEdge` (N-ary relationships)
- New vertex type: `SuspiciousSubgraph`
- New edges: `PARTICIPATES_IN` (vertex → hyperedge), `MATCHES_MOTIF`

**API contract (new, under `/v2/collusion/`):**
- `GET /v2/collusion/alerts?severity=&cohort=` — current alerts
- `GET /v2/collusion/subgraph/{id}` — suspicious subgraph detail
- `POST /v2/collusion/motifs/evaluate` — run library against subgraph
- `GET /v2/collusion/circularity/{entity_id}` — economic circularity score

**Acceptance criteria:**
- Motif library includes ≥10 patterns with unit tests
- Temporal community detection runs hourly on streaming A2A edges
- Hypergraph extension works on existing Neptune without schema break
- False-positive rate tracked; tuned with operator feedback
- All alerts gated by conformal confidence band

**Preservation:** Existing fraud + anomaly pipelines unchanged. Hyperedges are additive. Existing graph traversals continue working (hyperedges are typed vertices).

---

## P6 — AETHER-GPT (Graph Foundation Model)

**Purpose:** Self-supervised transformer pretrained on typed random walks; universal entity encoder; thin finetune heads for each downstream task.

**Feature flag:** `vnext.foundation_model.serve`, `vnext.foundation_model.finetune_heads`.

**New files:**
- `ML Models/aether-ml/server/foundation/walker.py`
- `ML Models/aether-ml/server/foundation/pretrain.py`
- `ML Models/aether-ml/server/foundation/encoder.py`
- `ML Models/aether-ml/server/foundation/finetune.py`
- `ML Models/aether-ml/server/foundation/README.md`
- `ML Models/aether-ml/training/configs/foundation_config.py`

**Training objective:**
- Masked-edge prediction
- Next-vertex prediction
- Edge-type contrastive loss
- DP-SGD for privacy (ε ≤ 8 budget)

**API contract (new, under `/v2/embeddings/`):**
- `POST /v2/embeddings/encode` — returns 256-d vector for given vertex_id
- **No raw embeddings exposed externally** — only downstream task outputs

**Acceptance criteria:**
- Pretrain completes on full graph; checkpoint < 500MB
- Frozen encoder drops in as feature source for identity/churn/LTV heads
- Downstream tasks match or beat current model AUC with 10× fewer labels
- Neural Cleanse + STRIP pass before promotion to registry
- DP epsilon budget documented per tenant

**Preservation:** All 9 existing models continue to serve as champions. FM-finetuned heads deploy as challengers via existing MLflow champion/challenger pattern. No existing inference path disrupted.

---

## P7 — Provenance Substrate

**Purpose:** Cryptographic + temporal substrate: witness signatures, bitemporal graph, ZK attestations. (Largely delivered in P0; extended here.)

**Feature flag:** `vnext.witness_signatures.enforced`, `vnext.zk_attestations.enabled`.

**New files (beyond P0):**
- `Backend Architecture/aether-backend/shared/crypto/circuits/trust_threshold.circom`
- `Backend Architecture/aether-backend/shared/crypto/threshold_sig.py`
- `Backend Architecture/aether-backend/shared/crypto/revocation_registry.py`
- On-chain contract: `Smart Contracts/attestation_registry/` (new, EIP-712 + revocation list)

**Acceptance criteria:**
- Bitemporal queries return consistent historical state
- Witness signature verification works on all SDK platforms
- EIP-712 attestations verifiable by external smart contracts
- ZK circuit audited by third party (gated for production)
- Revocation list queryable on-chain

**Preservation:** Unsigned event path remains functional with grace period. On-chain contracts are new deployments; do not touch existing contracts.

---

## P8 — Federated Cross-Tenant Identity (PSI)

**Purpose:** Privacy-preserving cross-tenant identity + reputation sharing via Private Set Intersection.

**Feature flag:** `vnext.federation.enabled` (per-tenant; requires contractual opt-in).

**New files:**
- `Backend Architecture/aether-backend/services/federation/routes.py`
- `Backend Architecture/aether-backend/services/federation/psi_protocol.py`
- `Backend Architecture/aether-backend/services/federation/bloom_filter.py`
- `Backend Architecture/aether-backend/services/federation/aggregator.py`

**Data model:**
- New vertex type: `CrossTenantReputation`
- New edge: `MATCHES_GLOBAL` (local IdentityCluster → CrossTenantReputation)

**API contract (new, under `/v2/federation/`):**
- `POST /v2/federation/publish` — publish Bloom-filtered key set
- `GET /v2/federation/reputation/{global_id}` — cross-tenant reputation w/ DP noise
- `POST /v2/federation/opt-in` — tenant contract acknowledgment

**Acceptance criteria:**
- Malicious-security PSI protocol (not semi-honest)
- Per-tenant salt rotation every 30 days
- Minimum-k intersection rule enforced (k=50 default)
- DP noise on intersection sizes
- Byzantine-tolerant aggregation (tolerates 1/3 malicious tenants)

**Preservation:** IdentityCluster schema untouched; federation adds cross-tenant layer above it. Per-tenant data isolation preserved — raw identities never cross tenant boundaries.

---

## P9 — Safety Mesh

**Purpose:** Conformal abstention everywhere + neuro-symbolic bytecode risk prover.

**Feature flag:** `vnext.conformal.mandatory`, `vnext.symbolic_prover.enabled`.

**New files:**
- `ML Models/aether-ml/common/src/conformal.py` (delivered in P0, extended here)
- `Backend Architecture/aether-backend/shared/scoring/bytecode_gnn.py`
- `Backend Architecture/aether-backend/shared/scoring/symbolic_prover.py`
- `security/adversarial_training/pgd_pipeline.py`

**API contract:**
- Existing ML endpoints gain response fields: `lower_bound`, `upper_bound`, `abstained` (additive)
- `POST /v2/bytecode/prove` — returns `(risk_score, formal_proof | counterexample)`

**Acceptance criteria:**
- Every ML response carries calibrated confidence band
- Abstention triggers escalation to human review
- Symbolic prover verifies ≥10 known-risky patterns
- Adversarial training improves fraud/bot model robustness ≥20% vs PGD attack

**Preservation:** Existing bytecode rule-based scoring remains. Neuro-symbolic prover runs alongside and adds proof obligations. Abstention is additive — existing callers see new fields but can ignore them.

---

## P10 — Temporal Event Intelligence

**Purpose:** Continuous-time event modeling via Neural Hawkes / Transformer Hawkes. Feeds TRIGGER scheduler with intensity-driven wakes.

**Feature flag:** `vnext.hawkes.enabled`, `vnext.hawkes.trigger_integration`.

**New files:**
- `ML Models/aether-ml/server/hawkes/model.py`
- `ML Models/aether-ml/server/hawkes/training.py`
- `ML Models/aether-ml/server/hawkes/serve.py`
- `Agent Layer/agent_controller/runtime/hawkes_integration.py`

**API contract (new, under `/v2/temporal/`):**
- `GET /v2/temporal/intensity/{entity_id}` — λ_k(t | history) per event type
- `GET /v2/temporal/next_event/{entity_id}` — predicted next event w/ time + confidence

**Acceptance criteria:**
- Transformer Hawkes model beats existing LSTM journey prediction on NLL
- Intensity API P95 latency <100ms
- TRIGGER integration gated behind flag; existing cron/webhook wakes still work
- Log-likelihood evaluation published per retrain

**Preservation:** Existing LSTM journey prediction remains as champion. Hawkes deploys as challenger via MLflow. TRIGGER continues with cron/webhook wakes; Hawkes intensity is a new additive wake source.

---

## Pillar dependency graph

```
P0 Foundation (blocking)
  │
  ├─▶ P7 Provenance (extension of P0)
  │     │
  │     └─▶ P3 Agent Credit ─▶ ZK attestations
  │
  ├─▶ P9 Safety Mesh ──▶ conformal wrappers used by all
  │
  ├─▶ P1 Mission Graph
  │     │
  │     └─▶ P2 Counterfactual Runtime
  │
  ├─▶ P4 Coverage Autopilot (internal first)
  │
  ├─▶ P10 Temporal Intelligence
  │
  ├─▶ P6 Graph FM (can start pretraining early, integrate later)
  │
  ├─▶ P3 Agent Credit (depends on P1 causal weights)
  │
  ├─▶ P5 Collusion Detection (depends on P3 balance sheets)
  │
  └─▶ P8 Federation (last; depends on P3 reputation)
```
