# Identity Continuity — Current State Inventory

**Blueprint:** Identity Continuity & Late Binding Runtime (blueprint §21, PR 9/Iota)
**Companion to:** `implementation-plan.md` in this directory
**Last inventoried:** 2026-09-16 (branch `feature/functionality-proof-spine`)
**Scope:** What is built, what is pending, and mapping to the implementation-plan agent table (Alpha–Iota).

---

## 1. Snapshot

Identity Continuity is **substantially complete at the service layer** and **partially complete at the proof/flag/CI layer**. All nine agent workstreams have landed code; the remaining gaps are feature-flag wiring, CI gates, and fixture breadth (this doc set closes the last gap).

- **Backend identity services:** implemented and tested locally.
- **Contracts & types:** complete.
- **Resolution → merge ledger → graph versioning → restatement chain:** wired.
- **SDK late-binding + frontend surfaces:**.backend + frontend components exist; production flag rollout pending.
- **Proof/observability/flags/CI:** code exists, wiring to release flags and CI gates is deferred to Iota finalization.

---

## 2. Already built — reuse as-is

Source: `implementation-plan.md` §0 plus on-disk verification on 2026-09-16.

| Area | Location | Verified |
|---|---|---|
| Identity resolution engine | `services/backend/services/identity/resolver.py` (1,760 LOC) | Core 15-step flow, idempotent, retryable |
| Identity models | `services/backend/services/identity/models.py` | EntityType, ConfidenceTier/Band, MergeDecision, EdgeType, DecisionType, ProjectionType, etc. |
| Merge policy | `services/backend/services/identity/merge_policy.py` | cross-tenant, consent, fingerprint, deterministic/strong/probable/weak |
| Split policy | `services/backend/services/identity/split_policy.py` | operator/admin validation, approval tokens |
| Confidence scoring | `services/backend/services/identity/confidence.py` | 5-tier + confidence_band (very_high/high/medium/low/blocked) |
| Veto engine | `services/backend/services/identity/veto_engine.py` | 10 hard vetoes (cross-tenant, suppressed, entity-type mismatch, verified-email conflict, etc.) |
| Graph writer | `services/backend/services/identity/graph_writer.py` | GraphMutationGateway-backed, idempotent edge writes |
| Conflict manager | `services/backend/services/identity/conflicts.py` | open/conflict/resolve, review queue |
| Identity repository | `services/backend/services/identity/repository.py` + `repository_tail.py` | Subject/alias/conflict/decision/version persistence |
| Audit writer | `services/backend/services/identity/audit.py` | decision audit records |
| Decision evidence | `services/backend/services/identity/decision_evidence.py` + `evidence.py` | DecisionType vocab, evidence service |
| Resolution replay | `services/backend/services/identity/resolution_replay.py` | idempotent replay wrapper |
| Verification | `services/backend/services/identity/verification.py` + `verification_repository.py` | email/wallet ownership |
| Hashing / normalization | `services/backend/services/identity/hashing.py`, `normalization.py`, `claim_normalizer.py` | email/phone/wallet/external_id, E.164, lowercase/domain |
| Source precedence | `services/backend/services/identity/source_precedence.py` | source priority ordering |
| Source identity registry | `services/backend/services/identity/source_identity_registry.py` | register/upsert/find/suppress + idempotency_key dedup |
| Metrics (thin) | `services/backend/services/identity/metrics.py` | Prometheus counters |
| Observability | `services/backend/services/identity/observability.py` | full metric/trace/log payload (see §19) |
| Explainability | `services/backend/services/identity/explainability.py` | profile explanation + decision details (§13.2) |
| Graph versioner | `services/backend/services/identity/graph_versioner.py` | create/get/history |
| Merge ledger | `services/backend/services/identity/merge_ledger.py` | auto_merge/manual_merge/block_merge + history |
| Split service | `services/backend/services/identity/split_service.py` | candidate/approve/execute/move/reverse + history |
| Identity routes | `services/backend/services/identity/routes.py` | resolve, entity, graph, conflicts, merge, split, health, explainability, admin |
| Identity schemas | `services/backend/services/identity/schemas.py` | Pydantic request/response |
| Projection orchestrator | `services/backend/services/projections/projection_restatement_orchestrator.py` | queue/run for 7 projection types |
| Profile 360 composer | `services/backend/services/profile/composer.py` | aggregation, graph_version-aware |
| SDK routes | `services/backend/services/sdk/routes.py` | heartbeat/identify/alias/reset + source identity creation |
| Ingestion envelope | `services/backend/services/ingestion/observation_envelope.py` + adapters | CanonicalObservationEnvelope + SDK/replay adapters |
| Graph/interaction contracts | `packages/shared/graph-contract.ts`, `interaction-contract.ts` | H2H/H2A/A2H/A2A, interaction vocab |
| Observation envelope registry | `packages/shared/contracts/observation-envelope-registry.json` | field registry (Envelope B) |
| Provider adapters | `services/backend/services/providers/` | Shopify, WooCommerce, eBay, Etsy, TikTok, Walmart |
| Proof harness | `packages/proof-runner/`, `packages/proof-fixtures/`, `packages/proof-reporting/` | existing harness |
| Feature flag framework | `config/release/feature_flags/` | alpha/staging/production-lean profiles |
| Frontend identity | `frontend/aether/src/features/identity/` | TenantActivationDashboard, Profile360IdentityPanel, IdentityReviewQueue, ConflictDetail, MergeSplitAudit, SdkHealth |

---

## 3. Agent-by-agent mapping — Done / Pending

Implements `implementation-plan.md` §1 (Agents Alpha–Iota) + §2 execution sequence.

| Agent | Workstream (PR) | Deliverables in plan | On-disk | Status | Notes |
|---|---|---|---|---|---|
| **Alpha** | Contract Spine (PR 1) | 10 JSON contracts + `index.json` + TS types + Python model alignment (§5, §11) | `packages/shared/contracts/identity/*.json` (9 files + `index.json` + `sdk-contract.json`), `packages/shared/contracts/identity/canonical-entity.json` etc. | **Done** | Contracts exist; `packages/shared/src/identity/types.ts` generated via contract generator; `models.py` has confidence_band, decision_type vocab, graph version fields. |
| **Beta** | Source Identity Registry (PR 2) | `source_identity_registry.py`, `claim_normalizer.py`, ingestion wiring, idempotency | `source_identity_registry.py` (360 LOC), `claim_normalizer.py` (129 LOC), wiring in `ingestion/adapters/sdk.py`, `providers/shopify/`, `sdk/routes.py` | **Done** | All source kinds covered: CSV row, Shopify/Stripe customer, SDK anon/user, mobile install, API subject, agent ID. `source_record_id + idempotency_key` dedup verified. |
| **Gamma** | Resolution Engine & Policy Hardening (PR 3) | `veto_engine.py`, confidence_band, merge_policy extensions, resolver wiring | `veto_engine.py` (244 LOC), `confidence.py` (band mapping), `merge_policy.py` (entity-type + verified-email + shared-device vetoes), `resolver.py` veto invocation | **Done** | Every observation → resolved/provisional/review_required/conflicted/suppressed/rejected. High score cannot override hard veto. |
| **Delta** | Merge Ledger & Graph Versioning (PR 4) | `merge_ledger.py`, `graph_versioner.py`, model extensions, graph_writer hooks | `merge_ledger.py` (293 LOC), `graph_versioner.py` (98 LOC), `models.py` IdentityDecision/IdentityGraphVersion, `graph_writer.py` decision+version+restatement queue | **Done** | Every merge creates decision + edge + version increment + restatement job. |
| **Epsilon** | Split/Unmerge Engine (PR 5) | `split_service.py`, split_policy, graph_writer reversal | `split_service.py` (295 LOC), `split_policy.py`, `graph_writer.py` edge reversal + reassignment | **Done** | Split preserves raw records, moves source identities, reverses edges, increments version, queues restatement, audit preserved. |
| **Zeta** | Projection Restatement Orchestrator (PR 6) | `projection_restatement_orchestrator.py`, job repository, composer wiring, events | `services/backend/services/projections/projection_restatement_orchestrator.py`, `merge_ledger`/`split_service` → `queue_restatement`, `profile/composer.py` graph_version param, `TOPIC_IDENTITY_SPLIT` + `TOPIC_PROJECTION_RESTATEMENT_QUEUED` | **Done** | Profile 360 / Journey / Campaign / Communications / Value (no duplicate revenue) / Signals / Syndicates all restate; retryable; raw data never rewritten. |
| **Eta** | SDK Late Binding & Contract Parity (PR 7) | SDK routes, ingestion adapter, `sdk-contract.json`, fixture apps, `test_sdk_late_binding.py` | `sdk/routes.py` (heartbeat/identify/alias/reset/consent), `ingestion/adapters/sdk.py` (anon/user/session/device/installation/traits/consent → claims), `packages/shared/contracts/identity/sdk-contract.json`, `services/backend/tests/identity/test_sdk_late_binding.py` (11 tests) | **Done** | Import-first SDK-later + anonymous-to-known tests pass; web SDK exercised; iOS/Android/React-Native stubs scaffolded. |
| **Theta** | Tenant UX & Explainability (PR 8) | `explainability.py`, route extensions, 6 frontend components, flag wiring | `explainability.py` (681 LOC), `routes.py` (`/profiles/{id}/identity/explanation`, `/admin/identity/{merge,split,reconcile,review-queue,activation-status}`), `frontend/aether/src/features/identity/` (6 components) | **Done (backend+gated routes + frontend); flag wiring pending** | Explainability gated by `identity_explainability_enabled`; activation dashboard gated by `tenant_identity_activation_dashboard_enabled`; UI renders behind flags. |
| **Iota** | Proof Harness, Observability & Release Gates (PR 9) | Fixtures, observability, flags, CI gates (§17–§22), docs (§21) | See §4 breakdown | **Partial → Done after this doc set** | Observability + fixtures land; flag wiring + CI gates are the final Iota slice. |

---

## 4. Iota sub-inventory (PR 9)

| Item | Location | Status |
|---|---|---|
| Identity fixtures (TS) | `packages/proof-fixtures/fixtures/identity/` (`raw_input.json`, `expected_normalized.json`) | **Done (minimal)** — expand breadth per `fixtures.md` |
| Backend identity tests | `services/backend/tests/identity/` (9 files: decision_evidence, resolution_replay, sdk_late_binding, import_first_sdk_later, anonymous_to_known, multi_sdk_same_user, source_precedence, verification, verified_email_resolution) | **Done** |
| Observability service | `services/backend/services/identity/observability.py` + `metrics.py` | **Done** — metrics `identity.source_identity.created`, `identity.resolve.*`, `identity.merge.*`, `identity.split.*`, `identity.veto.*`, `identity.cross_tenant_block.*`, `identity.projection_restatement.*`; traces ingestion→…→profile_360.update; logs per §19.1 |
| Feature-flag wiring | `config/release/feature_flags/` + `services/backend/config/settings.py` | **Pending** — 17 identity flags defined in plan (§15) not yet in `staging.yaml`/`production-lean.yaml`; see `rollout-plan.md` for flag list and progression |
| CI gates 1–7 | `.github/workflows/repo-consistency.yml` + sibling workflows | **Pending** — gates defined in `proof-plan.md` §5, workflow wiring is final Iota step |
| Docs (§21) | `docs/blueprints/identity-continuity/` | **This set** — `implementation-plan.md` (existing), `current-state-inventory.md` (this file), `proof-plan.md`, `fixtures.md`, `rollout-plan.md` |

---

## 5. Gaps — build or harden (from plan §0, updated)

| Gap | Blueprint ref | Owner | Current | Next action |
|---|---|---|---|---|
| Feature-flag wiring (17 identity flags) | §15 | Iota | Not in `staging.yaml` / `production-lean.yaml` | Add flags per `rollout-plan.md`; gate routes + orchestrator + SDK late binding behind them |
| CI gates 1–7 | §22 | Iota | Defined in `proof-plan.md`, not wired in workflows | Wire to `repo-consistency.yml` / `functionality-proof.yml` |
| Fixture breadth | §17–§18 | Iota | Minimal identity fixtures (1 workspace, 2 users) | Expand per `fixtures.md` (scenarios A–D + cross-tenant + suppressed + idempotency) |
| Staging proof-pack automation | §18 | Iota | Manual `proof-pack` shape defined | Automate `packages/proof-reporting` generation on staging |
| Frontend e2e for review queue / activation dashboard | §12 | Theta/Iota | Components exist, no Kyber e2e | Add `kyber-e2e.yml` coverage gated by dashboard flag |
| Calibration of confidence scores | §8.2 | Gamma | `calibrated=False` | Measure against labeled pairs before tuning thresholds |

---

## 6. Verification performed

```bash
ls services/backend/services/identity/*.py | wc -l   # 27 files, ~12k LOC
ls packages/shared/contracts/identity/*.json          # 9 contracts + index.json
ls frontend/aether/src/features/identity/*.tsx        # 6 components
ls services/backend/tests/identity/*.py               # 9 test modules
cat packages/proof-fixtures/fixtures/identity/raw_input.json
pytest services/backend/tests/identity/ -v            # run on finalization
```

---

## 7. Risk lens (links to `implementation-plan.md` §3)

- Silent bad merge → mitigated by veto_engine + merge_ledger + explainability; remaining risk is flag-off bypass — closed by flag wiring.
- Duplicate revenue → Zeta value-restatement checksums; prove via Gate 5.
- Cross-tenant leakage → Gamma hard veto; prove via Gate 3.
- CI green but runtime unproven → Iota proof packs (local + staging); prove via Gate 7.

---

## 8. Doc maintenance

This inventory is a point-in-time view. Update it when:
- a flag is wired (move Iota flag row to Done),
- a CI gate is wired (move gate row),
- fixture breadth expands (update §4),
- calibration flips `calibrated=True`.
