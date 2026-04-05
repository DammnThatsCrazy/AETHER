# 05 — Testing Strategy

Comprehensive test strategy covering unit, integration, contract, adversarial, load, and preservation testing. Every pillar ships with tests; nothing merges without green.

---

## Test pyramid for v-Next

```
                      ╱ ╲
                     ╱   ╲           Adversarial (~1%)
                    ╱ ADV ╲          - Red-team, extraction,
                   ╱───────╲           poisoning, prompt injection
                  ╱         ╲
                 ╱    E2E    ╲       End-to-end (~4%)
                ╱─────────────╲       - Full user journey, Shiki UI,
               ╱               ╲        agent workflows
              ╱    Contract     ╲    Contract (~10%)
             ╱───────────────────╲    - API schemas, OpenAPI, graph
            ╱                     ╲     edge/vertex contracts
           ╱      Integration       ╲ Integration (~25%)
          ╱───────────────────────────╲  - Service ↔ DB, service ↔
         ╱                             ╲  service, middleware chains
        ╱             Unit              ╲ Unit (~60%)
       ╱───────────────────────────────── ╲ - Pure functions, models,
                                            utilities, pipelines
```

---

## Test types per pillar

| Test Type | Scope | Target coverage | Tools |
|---|---|---|---|
| Unit | Pure logic, models, utilities | ≥85% on new code | pytest, jest, cargo test |
| Integration | Service ↔ DB ↔ cache ↔ graph | ≥70% | pytest-asyncio, testcontainers |
| Contract | API schemas, graph types | 100% of new endpoints | schemathesis, pact |
| E2E | Full workflow through Shiki | Per pillar, at least 1 happy path | playwright |
| Adversarial | Extraction, poisoning, injection | Per pillar, per threat class | custom red-team suite |
| Preservation | Backward compatibility | 100% of existing endpoints | Existing test suite + new regression |
| Load | Latency + throughput under load | Per new endpoint | locust, k6 |
| Security | SAST, secret scan, SBOM | Per commit | gitleaks, bandit, semgrep, cosign |

---

## Preservation tests (critical for non-breaking guarantee)

Every new PR must include preservation tests that prove existing behavior is unchanged:

### Backend preservation
```
tests/preservation/
├── test_v1_endpoint_shapes.py         # Snapshot tests of all /v1 responses
├── test_existing_graph_types.py        # Existing vertex/edge types intact
├── test_existing_mlflow_models.py      # Existing models still register + serve
├── test_agent_controller_workflow.py   # KIRA routing still works
├── test_staged_mutation_flow.py        # Approval workflow intact
├── test_ingestion_pipeline.py          # Bronze → Silver → Gold still flows
└── test_shiki_routes.py                # Existing Shiki pages load
```

### Schema preservation
```
tests/schema/
├── test_no_column_drops.py             # Alembic migration inspection
├── test_no_vertex_type_removals.py     # Neptune schema diff
├── test_no_breaking_openapi.py         # OpenAPI v1 spec unchanged
└── test_response_compat.py             # Field additions only, no removals
```

### External integration preservation
```
tests/preservation/external/
├── test_data_provider_adapters.py      # External data feed ingestion works
├── test_webhook_receivers.py           # Webhook endpoints unchanged
└── test_sdk_batch_compat.py            # SDK batch format backward compat
```

---

## Unit test requirements

For every new module in v-Next, ship unit tests covering:

| Category | Required tests |
|---|---|
| Models / dataclasses | Construction, serialization, validation |
| Pure functions | Input/output table, edge cases, error paths |
| ML models | Fit/predict on toy data, reproducibility w/ seeds |
| Graph operations | Vertex/edge creation, traversal, bitemporal queries |
| Crypto primitives | Key generation, signing, verification, revocation |
| Feature flags | Flag resolution (env > tenant > default) |
| Middleware | Request pass-through, flag-off behavior |

---

## Integration test scenarios per pillar

### P0 Foundation
- Bitemporal query returns correct as-of state
- Witness signature verifier accepts valid sig, rejects tampered
- Hash chain integrity: tamper detection on append-only ledger
- Conformal wrapper returns coverage band for every model
- SBOM generated on build; cosign signature validates

### P1 Mission Graph
- Reconstruct mission from 50-event trace across 3 payment rails
- Causal weights sum to 1.0 per outcome
- Bitemporal replay produces consistent state at any timestamp
- Counterfactual swap produces valid delta
- Query P95 latency < 800ms under load

### P2 Counterfactual Runtime
- Baseline compiler produces per-archetype expected transitions
- Gap detector identifies missing action in known-synthetic data
- Intervention engine ranks by conformal-gated confidence
- Closed-loop evaluator records recovery outcome

### P3 Agent Credit
- Balance sheet updates within 5 min of task outcome
- Authority band enforcement blocks over-budget actions
- EIP-712 attestation verifies on external solidity contract
- ZK attestation proves threshold without revealing sub-scores
- DPO trainer produces valid policy gradient on sample reviews

### P4 Coverage Autopilot
- AL committee ranks mutations by information gain
- Auto-approval ceiling enforced (0% for Class 3/4/5)
- Spectral drift detects synthetic sybil invasion
- DPO retrain improves policy on holdout set

### P5 Collusion Detection
- Motif library detects circular hire chain in synthetic data
- Temporal community anomaly flags coordinated burst
- Hyperedge traversal returns participating vertices
- Circularity score correctly classifies known wash behavior

### P6 AETHER-GPT
- Walker produces typed random walks over graph
- Pretrain loss decreases on held-out set
- Frozen encoder embeddings cluster by known entity type
- Finetune head matches or beats existing model AUC
- Neural Cleanse passes on promoted checkpoint

### P7 Provenance
- Witness signature across all SDK platforms (web/iOS/Android/RN)
- Bitemporal query consistency across 3 transactions
- ZK circuit compiles + verifies
- Revocation list updates propagate on-chain

### P8 Federation
- PSI protocol computes intersection without raw disclosure
- DP noise bounds intersection size leakage
- Byzantine aggregator tolerates 1/3 malicious tenants

### P9 Safety Mesh
- Conformal abstention triggers on OOD input
- Symbolic prover produces formal proof for safe contract
- Adversarial training improves PGD-attack accuracy ≥20%

### P10 Temporal Intelligence
- Hawkes model beats LSTM on held-out NLL
- Intensity API returns valid λ_k(t) per event type
- TRIGGER wake on intensity threshold crossing

---

## Contract tests

Every new `/v2/` endpoint:
- OpenAPI spec committed before implementation
- Schemathesis property-based tests run on CI
- Response shape snapshot stored in `tests/contracts/`
- Backward-compat additions only (new optional fields allowed)

Every new graph type:
- Vertex schema committed to `docs/INTELLIGENCE-GRAPH.md`
- Edge type registered with allowed (from, to) vertex pairs
- Contract test verifies existing traversals still work

---

## Adversarial test suite

Runs quarterly + on security-labeled PRs:

| Test | What it does |
|---|---|
| `test_model_extraction.py` | Simulates extraction attacks on all ML endpoints; measures watermark detection rate |
| `test_membership_inference.py` | Runs MIA attack on Profile + embedding APIs |
| `test_adversarial_examples.py` | PGD attack on fraud/bot/anomaly models |
| `test_prompt_injection.py` | Injection attempts against KIRA + BOLT |
| `test_graph_poisoning.py` | Inject synthetic sybils; verify detection |
| `test_reviewer_collusion.py` | Simulate compromised reviewer; verify anomaly detection |
| `test_supply_chain.py` | Verify signed artifacts, SBOM integrity |
| `test_replay_attacks.py` | x402 + witness signature + attestation replay |

---

## Load / performance tests

| Endpoint | SLO | Test |
|---|---|---|
| `/v2/missions/{id}` | P95 < 800ms | 500 req/s, 5 min |
| `/v2/missions/{id}/replay` | P95 < 2s | 50 req/s, 5 min |
| `/v2/gaps?entity_id=` | P95 < 500ms | 200 req/s, 5 min |
| `/v2/agents/{id}/balance-sheet` | P95 < 300ms | 500 req/s, 5 min |
| `/v2/embeddings/encode` | P95 < 100ms | 1000 req/s, 5 min |
| `/v2/temporal/intensity/{id}` | P95 < 100ms | 1000 req/s, 5 min |
| Witness signature verifier | P95 < 5ms overhead | 5000 req/s, 5 min |

---

## Coverage gates

| Gate | Requirement |
|---|---|
| New code unit coverage | ≥85% |
| New endpoint contract coverage | 100% |
| Preservation tests on existing endpoints | 100% pass |
| Security tests | 100% pass before merge |
| Adversarial tests | 100% pass before phase promotion |
| E2E happy-path per pillar | 1 test minimum |

---

## Test data strategy

| Source | Use |
|---|---|
| Synthetic data generator | Unit + integration tests |
| Fixtures in `tests/fixtures/vnext/` | Reproducible test scenarios |
| Anonymized prod slice (Gold tier sample) | Load testing only; never in unit tests |
| Red-team adversarial corpus | Security tests; checked into repo |

**Never in tests:** raw PII, production keys, real customer identifiers.

---

## Running tests locally

```
# Unit tests
make test-unit

# Integration tests (requires docker-compose up)
make test-integration

# Contract tests
make test-contract

# Preservation tests (critical)
make test-preservation

# Full suite
make test-all

# Adversarial suite (slow)
make test-adversarial

# Coverage report
make coverage
```

---

## CI test gates (see 06-CICD.md for full pipeline)

| Stage | Tests run | Blocking? |
|---|---|---|
| Pre-commit | lint, format, gitleaks, type check | Yes |
| PR open | unit, integration, contract, preservation | Yes |
| PR security label | adversarial suite | Yes |
| Merge to integration | all above + load | Yes |
| Promotion to main | all + e2e + manual security review | Yes |
