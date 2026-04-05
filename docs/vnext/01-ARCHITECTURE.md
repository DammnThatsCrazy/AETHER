# 01 — Architecture: As-Is vs To-Be

## Current architecture (v8.8.0) — summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                          SDK LAYER (v3.0)                           │
│  Web  │  iOS  │  Android  │  React Native  │  (witness signing TBD) │
└────────────────────────┬────────────────────────────────────────────┘
                         │  POST /v1/batch
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     INGESTION + ENRICHMENT                          │
│  FastAPI (31–35 routers, 246+ endpoints)                            │
│  IP geolocation │ consent gating │ rate limit │ schema validation   │
└────────────────────────┬────────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MEDALLION DATA LAKE                            │
│  Bronze (raw) → Silver (validated) → Gold (features, metrics)       │
│  S3 + ClickHouse + Redis (online features)                          │
└─────────────┬─────────────────────┬───────────────────────┬─────────┘
              ▼                     ▼                       ▼
     ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐
     │ NEPTUNE GRAPH  │   │   ML PIPELINE    │   │ INTELLIGENCE API │
     │ 40+ vertex     │   │ 9 models:        │   │ Profile /        │
     │ 48+ edge types │   │ intent/bot/sess  │   │ Population /     │
     │ H2H/H2A/A2H/   │   │ identity/journey │   │ Expectations /   │
     │ A2A layers     │   │ churn/LTV/anom   │   │ Behavioral /     │
     │                │   │ attribution      │   │ Intelligence     │
     └────────────────┘   └──────────────────┘   └──────────────────┘
              ▲                                           ▲
              │                                           │
     ┌────────┴───────────────────────────────────────────┴─────────┐
     │                     AGENT LAYER (v8.8)                       │
     │  KIRA (orchestrator) → 8 domain controllers                  │
     │  Intake │ Discovery │ Enrichment │ Verification │ Commit     │
     │  Recovery │ BOLT │ TRIGGER + LOOP runtime                    │
     │  StagedMutation → ReviewBatch → Human Approval → Commit      │
     └──────────────────────────────────────────────────────────────┘
                                │
                                ▼
     ┌──────────────────────────────────────────────────────────────┐
     │              SHIKI OPERATOR CONSOLE (React)                  │
     │  Review queue │ Mutation approval │ Trust dashboards         │
     └──────────────────────────────────────────────────────────────┘
```

### Key existing subsystems

| Subsystem | Location | Purpose |
|---|---|---|
| SDK ingestion | `Data Ingestion Layer/`, `Aether Mobile SDK/`, `packages/aether-*` | Cross-platform event capture |
| Lake | `Data Lake Architecture/`, `Backend Architecture/aether-backend/repositories/` | Medallion tiers + feature store |
| Graph | `Backend Architecture/aether-backend/shared/graph/` | Neptune client + in-memory fallback |
| ML | `ML Models/aether-ml/` | 9 models + training + optimization |
| Agent | `Agent Layer/agent_controller/` | KIRA + controllers + runtimes |
| Security | `security/model_extraction_defense/` | Watermark/canary/perturbation mesh |
| Scoring | `Backend Architecture/aether-backend/shared/scoring/` | Trust composite + bytecode risk |
| Intelligence | `Backend Architecture/aether-backend/services/intelligence/` | External API surfaces |
| Console | `apps/shiki/` | Operator review UI |

---

## Target architecture (post v-Next) — layered view

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SDK LAYER (witness signatures)                   │
│  Device-bound keypair · Signed event batches · Tamper-proof         │
└─────────┬───────────────────────────────────────────────────────────┘
          │  POST /v1/batch (signed)
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│              INGESTION + SIGNATURE VERIFICATION                     │
│  Verifier middleware · Weighted trust (signed=1.0, unsigned=0.5)    │
│  Quarantine tier for anomalous streams                              │
└─────────┬───────────────────────────────────────────────────────────┘
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   BITEMPORAL MEDALLION LAKE                         │
│  Bronze → Silver → Gold                                             │
│  Every row carries (valid_time, transaction_time) + hash chain      │
└─────┬─────────────────────────────┬──────────────────────────┬──────┘
      ▼                             ▼                          ▼
┌──────────────┐          ┌─────────────────┐         ┌────────────────┐
│ BITEMPORAL   │          │  ML + FM        │         │  COVERAGE      │
│ GRAPH        │◄─────────┤  AETHER-GPT     │         │  AUTOPILOT     │
│              │          │  (foundation)   │         │  (AL review    │
│ + Hyperedges │          │  ↓ finetune ↓   │         │  routing +     │
│ + Mission    │          │  9 task heads   │         │  DPO policy)   │
│ + Gap        │          │  + Hawkes TPP   │         │                │
│ + Balance    │          │  + Contrastive  │         └────────────────┘
│   Sheet      │          │  + Causal GNN   │
│ + CrossTenant│          └─────────────────┘
│   Reputation │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│              INTELLIGENCE API v2 (flag-gated surfaces)              │
│  /v2/missions/*    /v2/gaps/*    /v2/agents/*/balance-sheet         │
│  /v2/attestations/* /v2/coverage/* /v2/collusion/* /v2/federation/* │
│  (all wrapped in conformal abstention + DP noise + query budgets)   │
└─────────┬───────────────────────────────────────────────────────────┘
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     AGENT LAYER v9                                  │
│  KIRA → controllers (existing) + new:                               │
│  · Counterfactual Mutation Simulator                                │
│  · Shadow Lake Runtime (dry-run)                                    │
│  · Authority Band Policy Engine                                     │
│  · Causal Trust Propagator                                          │
│  · DPO policy head (learned from ReviewBatch outcomes)              │
└─────────┬───────────────────────────────────────────────────────────┘
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│              SHIKI OPERATOR CONSOLE v2                              │
│  + Mission replay UI   + Gap inbox   + Balance sheet               │
│  + Mutation diff preview (counterfactual)                          │
│  + Coverage debt dashboard   + Collusion alerts                    │
└─────────────────────────────────────────────────────────────────────┘
          ▲
          │
┌─────────┴───────────────────────────────────────────────────────────┐
│       CRYPTO ROOT (HSM / KMS — new infrastructure layer)            │
│  Witness root keys │ Attestation signing keys │ ZK circuits         │
│  Key rotation │ Threshold signatures │ On-chain revocation list     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component-level additions (delta from current)

| Layer | NEW component | Location | Depends on |
|---|---|---|---|
| SDK | Witness signer | `packages/aether-web/src/signing/`, platform-specific | Device keystore |
| Ingestion | Signature verifier middleware | `Backend Architecture/aether-backend/middleware/witness.py` | SDK signer |
| Lake | Bitemporal schema wrapper | `Backend Architecture/aether-backend/repositories/bitemporal.py` | Postgres/ClickHouse |
| Graph | New vertex types | `Backend Architecture/aether-backend/shared/graph/vnext_types.py` | Existing GraphClient |
| Graph | Hyperedge client | `Backend Architecture/aether-backend/shared/graph/hyperedge.py` | Existing GraphClient |
| ML | Graph FM (AETHER-GPT) | `ML Models/aether-ml/server/foundation.py` | Walk infrastructure |
| ML | Causal GNN trust | `ML Models/aether-ml/server/causal_trust.py` | DoWhy/EconML |
| ML | Hawkes TPP | `ML Models/aether-ml/server/hawkes.py` | PyTorch |
| ML | Contrastive fingerprint | `ML Models/aether-ml/server/contrastive_fp.py` | PyTorch |
| ML | Conformal wrapper | `ML Models/aether-ml/common/src/conformal.py` | All existing models |
| Scoring | Agent balance sheet | `Backend Architecture/aether-backend/shared/scoring/balance_sheet.py` | Trust score composite |
| Scoring | Authority band policy | `Backend Architecture/aether-backend/shared/scoring/authority.py` | Balance sheet |
| Scoring | Spectral integrity | `Backend Architecture/aether-backend/shared/scoring/spectral.py` | Graph Laplacian |
| Services | Mission graph | `Backend Architecture/aether-backend/services/missions/` | Graph + attribution |
| Services | Counterfactual | `Backend Architecture/aether-backend/services/counterfactual/` | Expectations + graph |
| Services | Attestations | `Backend Architecture/aether-backend/services/attestations/` | HSM/KMS |
| Services | Federation (PSI) | `Backend Architecture/aether-backend/services/federation/` | Crypto primitives |
| Services | Collusion | `Backend Architecture/aether-backend/services/collusion/` | Motif library + HGNN |
| Services | Coverage | `Backend Architecture/aether-backend/services/coverage/` | Controller runtime |
| Agent | Counterfactual simulator | `Agent Layer/agent_controller/simulation/counterfactual.py` | In-memory graph clone |
| Agent | Shadow lake runtime | `Agent Layer/agent_controller/runtime/shadow.py` | Existing LOOP |
| Agent | DPO policy learner | `Agent Layer/agent_controller/learning/dpo.py` | ReviewBatch history |
| Agent | Active-learning router | `Agent Layer/agent_controller/learning/al_router.py` | Committee ensemble |
| Crypto | Witness keys | `Backend Architecture/aether-backend/shared/crypto/witness.py` | KMS |
| Crypto | Attestation signing | `Backend Architecture/aether-backend/shared/crypto/attestation.py` | HSM |
| Crypto | ZK circuits | `Backend Architecture/aether-backend/shared/crypto/circuits/` | snarkjs/circom |
| Console | Mission/Gap/BS views | `apps/shiki/src/views/vnext/` | Intelligence v2 APIs |

---

## Data flow diagrams

### D1 — Mission reconstruction (P1)

```
Human submits objective                        Agent executes objective
        │                                              │
        ▼                                              ▼
┌───────────────┐                            ┌───────────────┐
│  Objective    │──── delegates to ─────────▶│  Agent task   │
│  (KIRA)       │                            │  lifecycle    │
└───────┬───────┘                            └───────┬───────┘
        │                                            │
        │ mission_id (new)                           │
        ▼                                            ▼
┌─────────────────────────────────────────────────────────┐
│              MISSION VERTEX (new)                       │
│  groups: objective, agent tasks, sub-agents, services,  │
│  payments (fiat/x402/onchain), protocol actions,        │
│  approvals, final outcome                               │
└─────────────┬───────────────────────────────────────────┘
              │ causal edges w/ weights:
              │   direct / assist / enabling /
              │   economic / approval / recovery
              ▼
┌─────────────────────────────────────────────────────────┐
│          Gold tier: mission_summary                     │
│  completion_probability │ realized_value │              │
│  unrealized_value │ friction_sources │ trust_drag       │
└─────────────────────────────────────────────────────────┘
              │
              ▼
       /v2/missions/*   ←── customer-facing API
```

### D2 — Counterfactual gap detection (P2)

```
Gold tier events ──────┐
Population cohorts ────┼─▶ Expectation Baseline Compiler
Behavioral twins ──────┤    (materializes expected_next_state
Archetypes ────────────┘     per entity type + conditions)
                                        │
                                        ▼
                          Expected next action/edge/time
                                        │
Observed entity path ─────▶  Deviation computation
                                        │
                                        ▼
                           Gap vertex (new type):
                           - entity_id
                           - expected_action
                           - gap_start_time
                           - unrealized_value_score
                           - recoverability_score
                           - deviation_from_self
                           - deviation_from_peer
                           - deviation_from_twin
                                        │
                                        ▼
                         Ranked Intervention Engine
                         (conformal-gated; abstains when OOD)
                                        │
                                        ▼
               Interventions:  escalate | reroute | prompt |
                              suppress | investigate
                                        │
                                        ▼
                         Closed-loop evaluator
                         (measures recovery rate → feedback)
```

### D3 — Witness signature flow (P7)

```
SDK init
  │
  ├─▶ Generate device-bound keypair (WebAuthn / Secure Enclave /
  │   Android KeyStore) — private key non-extractable
  │
  ├─▶ Register public key → POST /v1/devices/register
  │                            (returns device_id + nonce)
  ▼
SDK event batch
  │
  ├─▶ Canonicalize batch (sorted keys, trimmed floats)
  ├─▶ Sign canonical bytes with device key → signature
  ├─▶ POST /v1/batch with headers:
  │     X-AETHER-Device-ID, X-AETHER-Signature, X-AETHER-Nonce
  ▼
Verifier middleware
  │
  ├─▶ Load device public key (cached)
  ├─▶ Verify signature + nonce freshness + replay protection
  ├─▶ Attach {signed: true, weight: 1.0} to events
  │   (or {signed: false, weight: 0.5} with quarantine flag
  │    during grace period)
  ▼
Bronze tier (with signature metadata)
  │
  ▼
Downstream ML + graph mutations consume weights
```

### D4 — Agent credit + authority band (P3)

```
Agent task outcomes ─────┐
Reviewer approvals ──────┤
Confidence deltas ───────┼─▶ Balance Sheet Compiler
x402/onchain spend ──────┤    (per-agent, bitemporal,
Hire chain graph ────────┘     updated on-event)
                                        │
                                        ▼
                           AgentBalanceSheet vertex:
                           calibration_error, rework_rate,
                           spend_efficiency, hire_depth,
                           rollback_involvement, etc.
                                        │
                     ┌──────────────────┼────────────────────┐
                     ▼                  ▼                    ▼
         Causal GNN Trust      DPO Policy Net         ZK Attestation
         (A2A propagation)     (learned routing)      (signed proof)
                     │                  │                    │
                     └──────────────────┼────────────────────┘
                                        ▼
                            Authority Band Policy Engine
                         (computes scope + budgets per agent)
                                        │
                                        ▼
                     KIRA enforces at every action attempt
                     (hard ceilings; no model can override)
```

---

## Deployment topology (target)

```
┌──────────────────────────────────────────────────────────┐
│             AWS (primary, existing)                      │
│                                                          │
│  ┌───────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ ECS/EKS       │   │ SageMaker    │   │ CloudHSM    │  │
│  │ (backend +    │   │ (training +  │   │ (witness +  │  │
│  │  agent layer) │   │  endpoints)  │   │  attest     │  │
│  │               │   │              │   │  keys)      │  │
│  └───────────────┘   └──────────────┘   └─────────────┘  │
│                                                          │
│  ┌───────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ Neptune       │   │ S3 Lake      │   │ Secrets     │  │
│  │ (bitemporal + │   │ (bitemporal  │   │ Manager +   │  │
│  │  hyperedges)  │   │  partitions) │   │ KMS         │  │
│  └───────────────┘   └──────────────┘   └─────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Shadow Lake Account (ISOLATED, one-way data)     │   │
│  │  For P2 simulation + P4 dry-run + red-team        │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘

External:
  · QuickNode RPC (existing, multi-chain)
  · On-chain attestation registry (new, per-chain revocation lists)
  · PSI Federation endpoints (Phase 4 only, tenant-opt-in)
```

---

## Key architectural invariants (never violate)

1. **All graph writes go through StagedMutation** — no direct Gremlin writes from agents.
2. **All model outputs pass through conformal wrapper** — raw scores never leave the system.
3. **All external API responses carry DP-noise + k-anonymity guarantees** for aggregates.
4. **All mutation commits are bitemporal** — `transaction_time` is append-only, hash-chained.
5. **All cross-tenant queries go through federation service** — no shared cache across tenants.
6. **All new vertex/edge types are additive** — never change semantics of existing types.
7. **All feature flags default OFF** — turning on requires explicit tenant/env config.
8. **All new endpoints live under `/v2/`** — never modify `/v1/` response shapes.
