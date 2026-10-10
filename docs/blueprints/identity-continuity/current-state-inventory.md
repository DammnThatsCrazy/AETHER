---
title: Identity Continuity Current State Inventory
slug: blueprints/identity-continuity/current-state-inventory
section: blueprints
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Identity Continuity — Current State Inventory

> Implementation status update — 2026-10-02: runtime and proof-pack paths are
> built and locally exercised, but staging connector/UI proof and confidence
> evaluation are not complete until real staging credentials and a
> representative human-adjudicated sample are available. Syndicates merge
> restatement and evidence-attributed split handling are implemented for
> explicitly opted-in groups; split memberships with missing or conflicting
> attribution remain unchanged and report an unsupported result.

**Blueprint:** Identity Continuity & Late Binding Runtime (blueprint §21, PR 9/Iota)
**Companion to:** `implementation-plan.md` in this directory
**Last updated:** 2026-10-02 (current implementation checkout)
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
| Projection orchestrator | `services/backend/services/projections/projection_restatement_orchestrator.py` | durable tenant-scoped jobs; implemented executors report outcomes, unsupported surfaces retain explicit reasons |
| Profile 360 composer | `services/backend/services/profile/composer.py` | aggregation, graph_version-aware |
| SDK routes | `services/backend/services/sdk/routes.py` | heartbeat/identify/alias/reset + source identity creation |
| Ingestion envelope | `services/backend/services/ingestion/observation_envelope.py` + adapters | CanonicalObservationEnvelope + SDK/replay adapters |
| Graph/interaction contracts | `packages/shared/graph-contract.ts`, `interaction-contract.ts` | H2H/H2A/A2H/A2A, interaction vocab |
| Observation envelope registry | `packages/shared/contracts/observation-envelope-registry.json` | field registry (Envelope B) |
| Provider adapters | `services/backend/services/providers/` | Shopify, WooCommerce, eBay, Etsy, TikTok, Walmart |
| Proof harness | `packages/proof-runner/`, `packages/proof-fixtures/`, `packages/proof-reporting/` | existing harness |
| Feature flag framework | `config/release/feature_flags/` | alpha/staging/production-lean profiles |
| Frontend identity | `apps/aether/src/features/identity/` | TenantActivationDashboard, Profile360IdentityPanel, IdentityReviewQueue, ConflictDetail, MergeSplitAudit, SdkHealth |

---

## 3. Agent-by-agent mapping — Done / Pending

Implements `implementation-plan.md` §1 (Agents Alpha–Iota) + §2 execution sequence.

| Agent | Workstream (PR) | Deliverables in plan | On-disk | Status | Notes |
|---|---|---|---|---|---|
| **Alpha** | Contract Spine (PR 1) | 10 JSON contracts + `index.json` + TS types + Python model alignment (§5, §11) | `packages/shared/contracts/identity/*.json` (9 files + `index.json` + `sdk-contract.json`), `packages/shared/contracts/identity/canonical-entity.json` etc. | **Done** | Contracts exist; `packages/shared/src/identity/types.ts` generated via contract generator; `models.py` has confidence_band, decision_type vocab, graph version fields. |
| **Beta** | Source Identity Registry (PR 2) | `source_identity_registry.py`, `claim_normalizer.py`, ingestion wiring, idempotency | `source_identity_registry.py` (360 LOC), `claim_normalizer.py` (129 LOC), wiring in `ingestion/adapters/sdk.py`, provider runtime webhook/pull, `sdk/routes.py` | **Partial** | CSV and Shopify/WooCommerce provider paths persist unresolved source identities with hashed email/phone claims and provider-record provenance. Provider claims become SDK candidate evidence only when a newly persisted raw record is anchored to a completed sync run or verified-and-processed webhook inbox; failed, pending, rolled-back, mismatched, or cross-tenant anchors are ignored. Candidate status still requires person-level identity-link consent before resolution. Stripe and other provider runtime paths are not proven here. |
| **Gamma** | Resolution Engine & Policy Hardening (PR 3) | `veto_engine.py`, confidence_band, merge_policy extensions, resolver wiring | `veto_engine.py` (244 LOC), `confidence.py` (band mapping), `merge_policy.py` (entity-type + verified-email + shared-device vetoes), `resolver.py` veto invocation | **Done** | Every observation → resolved/provisional/review_required/conflicted/suppressed/rejected. High score cannot override hard veto. |
| **Delta** | Merge Ledger & Graph Versioning (PR 4) | `merge_ledger.py`, `graph_versioner.py`, model extensions, graph_writer hooks | `merge_ledger.py` (293 LOC), `graph_versioner.py` (98 LOC), `models.py` IdentityDecision/IdentityGraphVersion, `graph_writer.py` decision+version+restatement queue | **Done** | Every merge creates decision + edge + version increment + restatement job. |
| **Epsilon** | Split/Unmerge Engine (PR 5) | `split_service.py`, split_policy, graph_writer reversal | `split_service.py` (295 LOC), `split_policy.py`, `graph_writer.py` edge reversal + reassignment | **Done** | Split preserves raw records, moves source identities, reverses edges, increments version, queues restatement, audit preserved. |
| **Zeta** | Projection Restatement Orchestrator (PR 6) | `projection_restatement_orchestrator.py`, durable jobs-platform queue, worker registration, merge/split/resolver wiring | `services/backend/services/projections/projection_restatement_orchestrator.py`, `services/backend/services/projections/syndicates_restatement.py`, `main.py`, `merge_ledger.py`, `split_service.py`, `resolver.py` | **Partial; staging proof pending** | Merge/split decisions and resolver decisions enqueue idempotent tenant-scoped jobs. Syndicates merge restatement uses explicitly tagged Population 360 groups; split moves only memberships whose full alias/observation evidence resolves to one fragment. Unattributed memberships remain unchanged with structured per-membership reasons. |
| **Eta** | SDK Late Binding & Contract Parity (PR 7) | SDK routes, ingestion adapter, `sdk-contract.json`, fixture apps, `test_sdk_late_binding.py` | `sdk/routes.py` (heartbeat/identify/alias/reset/consent), `ingestion/adapters/sdk.py` (anon/user/session/device/installation/traits/consent → claims), `packages/shared/contracts/identity/sdk-contract.json`, `services/backend/tests/identity/test_sdk_late_binding.py` (11 tests) | **Done** | Import-first SDK-later + anonymous-to-known tests pass; web SDK exercised; iOS/Android/React-Native stubs scaffolded. |
| **Theta** | Tenant UX & Explainability (PR 8) | `explainability.py`, route extensions, tenant activation and review surfaces | `explainability.py`, `routes.py`, `apps/aether/src/features/identity/` | **Implemented; local proof present** | Gated activation and review routes are wired to tenant-scoped capability and identity APIs. Fixture-backed UI tests are separate from authenticated staging UI evidence. |
| **Iota** | Proof Harness, Observability & Release Gates (PR 9) | Fixtures, observability, flags, CI gates (§17–§22), docs (§21) | `packages/proof-reporting/`, `scripts/identity_staging_capture.py`, `.github/workflows/identity-continuity-gates.yml`, staging lifecycle workflow | **Implemented; staging proof pending** | Capture, validation, redaction, and pack generation fail closed and are wired into staging. Real connector sync and authenticated live UI evidence have not been captured because required provider secrets are not configured. |

---

## 4. Iota sub-inventory (PR 9)

| Item | Location | Status |
|---|---|---|
| Identity fixtures | `packages/proof-fixtures/fixtures/identity/` | **Expanded** — includes import-first/SDK-later, shared-device no-merge, bad-merge/split, reimport idempotency, cross-tenant, deletion suppression, and multi-SDK cases |
| Backend identity tests | `services/backend/tests/identity/` | **Expanded** — focused modules cover resolver policy, tenant/consent boundaries, recovery, provider candidate evidence, SDK lifecycle, projections, staging capture, and calibration evaluation |
| Observability service | `services/backend/services/identity/observability.py` + `metrics.py` | **Done** — metrics `identity.source_identity.created`, `identity.resolve.*`, `identity.merge.*`, `identity.split.*`, `identity.veto.*`, `identity.cross_tenant_block.*`, `identity.projection_restatement.*`; traces ingestion→…→profile_360.update; logs per §19.1 |
| Feature-flag wiring | `config/release/feature_flags/` + backend settings and routes | **Wired and locally exercised** — retain runtime confidence as uncalibrated |
| CI gates 1–7 | `.github/workflows/identity-continuity-gates.yml` plus staging lifecycle capture | **Wired as supplementary finalization evidence** — the canonical repository disposition remains the normal-PR readiness authority |
| Docs (§21) | `docs/blueprints/identity-continuity/` | **This set** — `implementation-plan.md` (existing), `current-state-inventory.md` (this file), `proof-plan.md`, `fixtures.md`, `rollout-plan.md` |

---

## 5. Gaps — build or harden (from plan §0, updated)

| Gap | Blueprint ref | Owner | Current | Next action |
|---|---|---|---|---|
| Feature-flag wiring | §15 | Iota | Routes, SDK lifecycle, and tenant activation surfaces have flag checks and focused tests | Review the complete flag map during final architecture review; runtime confidence remains uncalibrated |
| CI gates 1–7 | §22 | Iota | Supplementary identity continuity workflow is wired to finalization; repository disposition remains the sole normal-PR authority | Run supplementary evidence on a fully configured staging run; do not substitute it for final disposition |
| Fixture breadth | §17–§18 | Iota | Fixtures cover import-first, shared-device, split/recovery, connector idempotency, cross-tenant, suppression, and multi-SDK scenarios | Review fixture claims against the final behavior and captured staging transcripts |
| Staging proof-pack automation | §18 | Iota | Collector, schemas, capture CLI, and staging workflow are implemented; collector requires both live UI surfaces | Configure `IDENTITY_STAGING_PROVIDER_IDENTITY`, `IDENTITY_STAGING_PROVIDER_CONFIG_JSON`, and `IDENTITY_STAGING_PROVIDER_CREDENTIAL_JSON`, then run staging workflow and inspect uploaded pack |
| Authenticated live UI evidence | §12 | Theta/Iota | Activation and Review Queue Playwright path uses deployed Aether UI and real backend; fixture suite is supplemental | Run with deployed UI URL and staging API credential; inspect successful API observations and both screenshot artifacts |
| Confidence evaluation | §8.2 | Gamma | Evaluator requires independent adjudication and pseudonymous tenant/source/reviewer/time provenance; production `calibrated=False` | Supply representative independently reviewed data meeting sample, source, tenant, score-band, and holdout gates; no qualifying label dataset is present |
| Syndicates restatement | §11 | Zeta | Governed merge union and evidence-attributed split paths are implemented for groups tagged `syndicates_group: true`; untagged groups and Cluster360 are excluded | Add accepted alias/observation evidence references when creating membership rows; keep unattributed or mixed split memberships unchanged and investigate those evidence gaps |

---

## 6. Verification performed

```bash
ls services/backend/services/identity/*.py | wc -l   # 27 files, ~12k LOC
ls packages/shared/contracts/identity/*.json          # 9 contracts + index.json
ls apps/aether/src/features/identity/*.tsx        # 6 components
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

This inventory is a point-in-time view. Update it when new implementation
slices land or real staging and reviewed-label evidence become available.
