# 07 — Build Sequence (Step-by-Step for Claude Code)

This is the execution playbook. Execute top-to-bottom. Every step has explicit inputs, outputs, and a gate.

**Ordering principle:** Foundation → Safety → Composition → ML-heavy → Network.

---

## Phase 0 — Scaffolding (do this first)

### Step 0.1: Create feature-flag registry

**Files to create:**
- `Backend Architecture/aether-backend/shared/feature_flags/__init__.py`
- `Backend Architecture/aether-backend/shared/feature_flags/registry.py`
- `Backend Architecture/aether-backend/shared/feature_flags/resolver.py`
- `docs/vnext/feature-flags.md`

**Task:** Build a flag registry with enum-backed flags, env var override, tenant config override, default `False`.

**Gate:** Unit tests prove resolution priority (env > tenant > default).

### Step 0.2: Create vnext module skeletons (empty, to prevent import errors)

**Directories to create:**
```
Backend Architecture/aether-backend/services/missions/
Backend Architecture/aether-backend/services/counterfactual/
Backend Architecture/aether-backend/services/underwriter/
Backend Architecture/aether-backend/services/coverage/
Backend Architecture/aether-backend/services/coordination/
Backend Architecture/aether-backend/services/federation/
Backend Architecture/aether-backend/services/attestations/
Backend Architecture/aether-backend/shared/provenance/
Backend Architecture/aether-backend/shared/bitemporal/
Backend Architecture/aether-backend/shared/crypto/
Backend Architecture/aether-backend/shared/conformal/
Backend Architecture/aether-backend/shared/motifs/
Backend Architecture/aether-backend/shared/dp/
ML Models/aether-ml/server/foundation/
ML Models/aether-ml/server/hawkes/
ML Models/aether-ml/server/contrastive/
ML Models/aether-ml/server/causal_trust/
ML Models/aether-ml/server/dpo_policy/
Agent Layer/agent_controller/learning/
Agent Layer/agent_controller/shadow/
Agent Layer/agent_controller/simulation/
apps/shiki/src/views/vnext/
tests/preservation/
tests/vnext/
```

Each directory gets a `__init__.py` (or `index.ts`) + `README.md` stub.

**Gate:** `make test-all` still passes (directories are empty; nothing imports them yet).

### Step 0.3: Add preservation test harness

**Files to create:**
- `tests/preservation/conftest.py`
- `tests/preservation/test_v1_endpoint_shapes.py`
- `tests/preservation/test_existing_graph_types.py`
- `tests/preservation/test_existing_mlflow_models.py`
- `tests/preservation/test_agent_controller_workflow.py`
- `tests/preservation/test_staged_mutation_flow.py`
- `tests/preservation/test_ingestion_pipeline.py`
- `tests/preservation/test_shiki_routes.py`
- `tests/preservation/test_external_data_providers.py`

**Task:** Each test snapshots current behavior. These tests must pass throughout all of v-Next development.

**Gate:** All preservation tests pass on baseline.

### Step 0.4: Wire CI

**Files to create/modify:**
- `.github/workflows/vnext-ci.yml`
- `.github/workflows/vnext-security.yml`
- `.github/workflows/vnext-preservation.yml`
- `.github/workflows/vnext-ml.yml`
- `.github/workflows/vnext-contract-db.yml`
- Extend `.pre-commit-config.yaml` with vnext-specific hooks

**Gate:** CI passes on empty-pillar branch.

---

## Phase 1 — P0 Foundation

### Step 1.1: Bitemporal schema

**Files:**
- `Backend Architecture/aether-backend/shared/bitemporal/schema.py`
- `Backend Architecture/aether-backend/shared/bitemporal/as_of_query.py`
- `Backend Architecture/aether-backend/shared/bitemporal/temporal_edge.py`
- Alembic migration: `alembic/versions/vnext_001_bitemporal.py` (additive columns)

**Task:** Add `valid_from`, `valid_to`, `transaction_time`, `hash_prev` to all relevant tables. Wrap `GraphClient` to support `as_of` parameter. Hash-chain the transaction_time per partition.

**Tests:** Bitemporal query returns consistent as-of state; hash chain tamper-detects.

**Gate:** Preservation tests still pass. New bitemporal integration tests pass.

### Step 1.2: Witness signature verifier

**Files:**
- `Backend Architecture/aether-backend/shared/provenance/signatures.py`
- `Backend Architecture/aether-backend/shared/provenance/keys.py`
- `Backend Architecture/aether-backend/shared/provenance/hash_chain.py`
- `Backend Architecture/aether-backend/middleware/witness_verifier.py`

**Task:** Middleware checks `X-AETHER-Signature`, `X-AETHER-Device-ID`, `X-AETHER-Nonce` headers. Verifies signature against registered device key. Attaches weight to events (1.0 signed, 0.5 unsigned). Never rejects during grace period.

**Tests:** Valid sig accepted; tampered sig rejected; unsigned events pass with weight=0.5.

**Gate:** `POST /v1/batch` continues to accept unsigned events (preservation).

### Step 1.3: Conformal wrapper for all 9 models

**Files:**
- `ML Models/aether-ml/common/src/conformal.py`
- `ML Models/aether-ml/common/src/calibration.py`
- `ML Models/aether-ml/common/src/coverage.py`

**Task:** Build offline calibration on Gold tier. Wrap each model's predict method to return `(score, lower, upper, abstain)`. Abstain triggers when prediction set exceeds threshold.

**Tests:** Coverage guarantee holds on held-out set. Abstention correctly fires on OOD input.

**Gate:** All existing model endpoints still return their original fields; new fields additive.

### Step 1.4: SBOM + artifact signing pipeline

**Files:**
- `.github/workflows/sbom.yml`
- `scripts/sign_artifacts.sh`
- `scripts/generate_sbom.sh`

**Task:** CI generates CycloneDX SBOM per build. cosign signs every container. Deploy time verifies signature.

**Gate:** Unsigned artifacts refused at deploy.

### Step 1.5: Doc reconciliation

**Files to modify:**
- `README.md` (align router count)
- `docs/ARCHITECTURE.md` (align with actual)
- `docs/PRODUCTION-READINESS.md` (align)

**Task:** Reconcile 31/35 router count drift. Produce single source of truth.

**Gate:** No reader finds conflicting numbers across docs.

---

## Phase 2 — P7 Provenance (extended) + P9 Safety Mesh

### Step 2.1: HSM/KMS key infrastructure

**Files:**
- `Backend Architecture/aether-backend/shared/crypto/hsm_client.py`
- `Backend Architecture/aether-backend/shared/crypto/key_rotation.py`

**Task:** Abstract HSM interaction. Key generation, signing, rotation, revocation. Supports AWS CloudHSM + local dev fallback.

**Tests:** Key lifecycle works; rotation preserves old sig verification during grace.

### Step 2.2: EIP-712 attestations

**Files:**
- `Backend Architecture/aether-backend/shared/crypto/eip712.py`
- `Backend Architecture/aether-backend/services/attestations/routes.py`
- `Backend Architecture/aether-backend/services/attestations/issuer.py`
- `Smart Contracts/attestation_registry/AttestationRegistry.sol`

**Task:** Sign trust-threshold attestations with HSM key. Include nonce + expiry + chain-id. Solidity contract verifies.

**Tests:** Solidity test verifies attestation. Replay + cross-chain attempts blocked.

### Step 2.3: Conformal abstention mandatory

**Files to modify:**
- All existing ML endpoint handlers (add abstention gate)

**Task:** When abstention triggers, either (a) escalate to human if agent context, or (b) return 202 + abstention reason.

**Gate:** Every external ML response carries confidence band + abstention flag.

### Step 2.4: Neuro-symbolic bytecode prover

**Files:**
- `Backend Architecture/aether-backend/shared/scoring/bytecode_gnn.py`
- `Backend Architecture/aether-backend/shared/scoring/symbolic_prover.py`

**Task:** GNN over contract control-flow graph proposes risk patterns; Z3 SMT solver verifies as proof obligation. Output: `(risk_score, formal_proof | counterexample)`.

**Tests:** Known-risky contracts produce counterexamples; safe contracts produce proofs.

---

## Phase 3 — P4 Coverage Autopilot (internal first)

### Step 3.1: AL router skeleton

**Files:**
- `Agent Layer/agent_controller/learning/active_learning.py`
- `Agent Layer/agent_controller/learning/information_gain.py`

**Task:** Committee of 5 cheap classifiers. Information gain = disagreement + entropy. Gates mutation promotion.

**Tests:** Synthetic high-IG mutations route to humans; low-IG auto-approve (under policy cap).

### Step 3.2: DPO trainer

**Files:**
- `Agent Layer/agent_controller/learning/dpo_trainer.py`

**Task:** Consume ReviewBatch history as preference pairs. Weekly retrain of KIRA routing policy.

**Gate:** Never hot-swap policy without shadow evaluation.

### Step 3.3: Spectral integrity monitor

**Files:**
- `Backend Architecture/aether-backend/shared/scoring/spectral.py`

**Task:** Weekly compute Laplacian eigenvalues per IdentityCluster. Drift > threshold triggers re-verification.

**Tests:** Synthetic sybil injection detected.

### Step 3.4: Coverage debt dashboard

**Files:**
- `Backend Architecture/aether-backend/services/coverage/routes.py`
- `Backend Architecture/aether-backend/services/coverage/debt_model.py`
- `apps/shiki/src/views/vnext/coverage/`

**Task:** Expose coverage debt metrics to Shiki; prioritized review queue.

**Preservation:** Existing controllers unchanged. AL just prioritizes queue.

---

## Phase 4 — P1 Mission Graph

### Step 4.1: Mission vertex registration

**Files:**
- `Backend Architecture/aether-backend/shared/graph/mission_vertex.py`

**Task:** Register `Mission` vertex type + new edge types (`PART_OF_MISSION`, `CAUSED_OUTCOME`, etc.) via additive schema extension.

**Gate:** Existing graph traversals untouched.

### Step 4.2: Mission reconstruction

**Files:**
- `Backend Architecture/aether-backend/services/missions/reconstruct.py`
- `Backend Architecture/aether-backend/services/missions/models.py`

**Task:** From an objective_id, walk event provenance + A2A + H2A + A2H edges to reconstruct the full mission graph. Store summary in Gold.

**Tests:** 50-event mission across 3 payment rails reconstructs correctly.

### Step 4.3: Causal weight computation

**Files:**
- `Backend Architecture/aether-backend/services/missions/causal_weights.py`

**Task:** DML or causal-GNN estimator over mission paths. Weights: direct/assist/enabling/economic/approval/recovery. Sum to 1.0 per outcome.

**Tests:** Synthetic causal chain produces expected weight distribution.

### Step 4.4: Replay + counterfactual API

**Files:**
- `Backend Architecture/aether-backend/services/missions/replay.py`
- `Backend Architecture/aether-backend/services/missions/routes.py`

**Task:** `GET /v2/missions/{id}/replay?as_of=t` uses bitemporal query. `?swap=actor_id` produces counterfactual delta.

**Tests:** Replay produces consistent state; swap produces valid delta.

### Step 4.5: Shiki Mission views

**Files:**
- `apps/shiki/src/views/vnext/missions/`

**Task:** Mission timeline, causal chain viz, replay slider, counterfactual swap UI.

**Gate:** Existing Shiki views untouched.

---

## Phase 5 — P2 Counterfactual Runtime

### Step 5.1: Expectation baseline compiler

**Files:**
- `Backend Architecture/aether-backend/services/counterfactual/baselines.py`

**Task:** Nightly job materializes expected transitions per archetype from Gold. Stores as baseline policies.

### Step 5.2: Gap detector

**Files:**
- `Backend Architecture/aether-backend/services/counterfactual/gaps.py`

**Task:** Incremental comparison against baselines. Emits Gap vertices with deviation scores + unrealized value.

### Step 5.3: Intervention engine

**Files:**
- `Backend Architecture/aether-backend/services/counterfactual/interventions.py`

**Task:** Rank interventions by expected value. Conformal-gated. Suggestions only (v0); autonomous act later.

### Step 5.4: Closed-loop evaluator

**Files:**
- `Backend Architecture/aether-backend/services/counterfactual/evaluator.py`

**Task:** Post-intervention measurement. Recovery outcome recorded with bitemporal provenance.

### Step 5.5: Shiki Gap Inbox

**Files:**
- `apps/shiki/src/views/vnext/gaps/`

**Task:** Gap list ranked by unrealized_value × recoverability; intervention suggestions; evaluation results.

---

## Phase 6 — P10 Temporal Intelligence

### Step 6.1: Transformer Hawkes model

**Files:**
- `ML Models/aether-ml/server/hawkes/model.py`
- `ML Models/aether-ml/server/hawkes/training.py`

**Task:** Train Transformer Hawkes on Silver tier event streams. Beat LSTM journey model on NLL.

### Step 6.2: Intensity API

**Files:**
- `ML Models/aether-ml/server/hawkes/serve.py`
- `Backend Architecture/aether-backend/services/temporal/routes.py`

**Task:** Expose λ_k(t|history) + predicted next event.

### Step 6.3: TRIGGER integration

**Files:**
- `Agent Layer/agent_controller/runtime/hawkes_integration.py`

**Task:** Subscribe TRIGGER to intensity-threshold crossings. Flag-gated; cron/webhook wakes remain default.

**Preservation:** Existing LSTM stays as champion. Hawkes deploys as challenger.

---

## Phase 7 — P3 Agent Credit

### Step 7.1: Balance sheet compiler

**Files:**
- `Backend Architecture/aether-backend/services/underwriter/balance_sheet.py`
- `Backend Architecture/aether-backend/shared/scoring/balance_sheet.py`

**Task:** Per-agent metrics from tasks + approvals + spend + hires. Bitemporal; updated within 5 min of outcome event.

### Step 7.2: Causal GNN trust

**Files:**
- `ML Models/aether-ml/server/causal_trust/gnn.py`
- `ML Models/aether-ml/server/causal_trust/dml_estimator.py`

**Task:** DoWhy/EconML over A2A hire chain. Treatment: hire edge existence/weight. Outcome: violation rates.

### Step 7.3: Authority band policy engine

**Files:**
- `Backend Architecture/aether-backend/shared/scoring/authority.py`

**Task:** Maps balance sheet → authority band. Hard ceilings per band (not model-determined).

### Step 7.4: KIRA enforcement hook

**Files modified:**
- `Agent Layer/agent_controller/kira.py` (minimal additive edit)

**Task:** Check authority band at every agent action. Block if violated; escalate to human.

**Preservation:** Existing KIRA routing untouched; authority check is additive.

### Step 7.5: ZK attestation issuance

**Files:**
- `Backend Architecture/aether-backend/shared/crypto/circuits/trust_threshold.circom`
- `Backend Architecture/aether-backend/services/attestations/zk_issuer.py`

**Task:** Circom circuit for trust-threshold proof. Compile + audit gate before prod.

**Gate:** Third-party audit required before on-chain deployment.

---

## Phase 8 — P6 AETHER-GPT

### Step 8.1: Typed walker

**Files:**
- `ML Models/aether-ml/server/foundation/walker.py`

**Task:** Random walks over 48 edge types respecting RelationshipLayer filters.

### Step 8.2: Pretraining loop

**Files:**
- `ML Models/aether-ml/server/foundation/pretrain.py`
- `ML Models/aether-ml/training/configs/foundation_config.py`

**Task:** Transformer encoder. Masked-edge + next-vertex + contrastive objectives. DP-SGD.

### Step 8.3: Frozen encoder API

**Files:**
- `ML Models/aether-ml/server/foundation/encoder.py`

**Task:** `POST /v2/embeddings/encode` — never exposed externally; internal only for downstream heads.

### Step 8.4: Finetune thin heads

**Files:**
- `ML Models/aether-ml/server/foundation/finetune.py`

**Task:** Replace per-task feature engineering with FM embeddings. Deploy as challengers.

**Preservation:** All 9 existing models remain as champions.

---

## Phase 9 — P5 Collusion Detection

### Step 9.1: Motif library

**Files:**
- `Backend Architecture/aether-backend/shared/motifs/library.py`

**Task:** ≥10 patterns: circular hire, payment loop, coordinated timing, etc.

### Step 9.2: Hypergraph support

**Files:**
- `Backend Architecture/aether-backend/shared/graph/hyperedge.py`

**Task:** HyperEdge vertex + PARTICIPATES_IN edge. Captures DAO votes, multi-sig, x402 channels.

### Step 9.3: HGNN model

**Files:**
- `ML Models/aether-ml/server/hgnn.py`

**Task:** Hypergraph neural net for coordination detection.

### Step 9.4: Temporal community anomaly

**Files:**
- `Backend Architecture/aether-backend/services/coordination/temporal_community.py`

**Task:** Hourly streaming clustering on A2A edges; burst detection via Hawkes.

### Step 9.5: Shiki alerts UI

**Files:**
- `apps/shiki/src/views/vnext/collusion/`

**Task:** Alert list, subgraph viewer, motif match details.

---

## Phase 10 — P8 Federation (PSI)

### Step 10.1: PSI protocol

**Files:**
- `Backend Architecture/aether-backend/services/federation/psi_protocol.py`

**Task:** Malicious-security PSI. Bloom-filtered or encrypted key sets. Per-tenant salt rotation.

### Step 10.2: Byzantine aggregator

**Files:**
- `Backend Architecture/aether-backend/services/federation/aggregator.py`

**Task:** Tolerates 1/3 malicious tenants. DP noise on outputs.

### Step 10.3: CrossTenantReputation vertex

**Files:**
- (additive schema extension)

**Task:** Global reputation layer; local IdentityClusters link via `MATCHES_GLOBAL`.

**Gate:** Requires ≥3 tenant opt-ins before production enable.

---

## Final: Post-build validation

1. Run full test suite (unit + integration + contract + preservation + e2e + adversarial)
2. Verify all feature flags documented
3. Confirm all SBOMs signed
4. Verify no /v1 endpoint response changed (preservation)
5. Verify Shiki existing views + workflows intact
6. Verify agent automation flow works (KIRA + controllers + LOOP)
7. Verify SDK ingestion pipeline (signed + unsigned both work)
8. Verify external data provider feeds flow to Bronze
9. Run canary deploy to staging
10. Per-pillar smoke tests

---

## Completion checklist

- [ ] All 10 pillars implemented
- [ ] All feature flags default off
- [ ] All preservation tests pass
- [ ] All new tests pass
- [ ] Security gates pass (SBOM, signed, scanned)
- [ ] All endpoints in OpenAPI
- [ ] All models have model cards
- [ ] All new graph types documented
- [ ] Shiki v-Next views tested
- [ ] Rollback procedure documented per pillar
- [ ] Branch rebases cleanly onto main
