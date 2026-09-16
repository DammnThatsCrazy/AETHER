# Identity Continuity & Late Binding Runtime — Implementation Plan

**Mapped against Aether repo (DammnThatsCrazy/AETHER)**
**Blueprint: Identity Continuity & Late Binding Runtime Implementation Blueprint.md**

---

## 0. Existing asset inventory (don't rebuild)

### Already built — reuse as-is

| Area | Location | Status |
|---|---|---|
| Identity resolution engine | `services/backend/services/identity/resolver.py` | Core resolver with 15-step flow, idempotent |
| Identity models | `services/backend/services/identity/models.py` | EntityType, ConfidenceTier, MergeDecision, EdgeType, ConflictStatus, SubjectStatus, VerificationMethod |
| Merge policy engine | `services/backend/services/identity/merge_policy.py` | Evaluate with cross-tenant, consent, fingerprint, deterministic, strong, probable, weak rules |
| Split policy | `services/backend/services/identity/split_policy.py` | Operator/admin split validation |
| Confidence scoring | `services/backend/services/identity/confidence.py` | 5-tier match score with reason codes, calibrated=False |
| Graph writer | `services/backend/services/identity/graph_writer.py` | GraphMutationGateway-backed edge writes, idempotent |
| Conflict manager | `services/backend/services/identity/conflicts.py` | Open/conflict/resolve/conflict listing |
| Identity repository | `services/backend/services/identity/repository.py` | Subject/alias/conflict persistence |
| Audit writer | `services/backend/services/identity/audit.py` | Decision audit records |
| Decision evidence | `services/backend/services/identity/decision_evidence.py` | DecisionType mapping, evidence service |
| Resolution replay | `services/backend/services/identity/resolution_replay.py` | Idempotent replay wrapper |
| Verification | `services/backend/services/identity/verification.py` | Email/wallet ownership verification |
| Hashing | `services/backend/services/identity/hashing.py` | Email/phone/wallet/fingerprint/external_id hashing |
| Normalization | `services/backend/services/identity/normalization.py` | Value normalization |
| Source precedence | `services/backend/services/identity/source_precedence.py` | Source priority ordering |
| Metrics | `services/backend/services/identity/metrics.py` | Identity metrics |
| Identity routes | `services/backend/services/identity/routes.py` | HTTP surface |
| Identity schemas | `services/backend/services/identity/schemas.py` | Pydantic schemas |
| SDK routes | `services/backend/services/sdk/routes.py` | SDK event ingestion |
| Ingestion envelope | `services/backend/services/ingestion/observation_envelope.py` | CanonicalObservationEnvelope mapping |
| Ingestion adapters | `services/backend/services/ingestion/adapters/` | Base, SDK, replay adapters |
| Profile 360 composer | `services/backend/services/profile/composer.py` | Holistic profile aggregation |
| Profile routes | `services/backend/services/profile/routes.py` | 20+ profile endpoints |
| Graph contract (TS) | `packages/shared/graph-contract.ts` | Edge layer classification (H2H/H2A/A2H/A2A) |
| Interaction contract (TS) | `packages/shared/interaction-contract.ts` | Interaction vocabulary |
| Observation envelope registry | `packages/shared/contracts/observation-envelope-registry.json` | Envelope B field registry |
| Provider adapters | `services/backend/services/providers/` | Shopify, WooCommerce, eBay, Etsy, TikTok, Walmart |
| Proof infrastructure | `packages/proof-runner/`, `packages/proof-fixtures/`, `packages/proof-reporting/` | Existing proof harness |
| Feature flags | `config/release/feature_flags/` | Existing flag framework |
| Tests (identity) | `services/backend/tests/identity/` | verified_email_resolution, resolution_replay, decision_evidence |
| Tests (restatement) | `services/backend/tests/computation/test_identity_restatement.py` | Restatement + confidence semantics |

### Gaps — build or harden

| Gap | Blueprint ref | Agent |
|---|---|---|
| TS identity contract spine | §5, §11 PR 1 | Alpha |
| Source Identity Registry service | §5.2, §13, Phase 2 PR 2 | Beta |
| Identity Claim Normalizer | §5.3, Phase 2 | Beta |
| Contradiction/Veto Engine | §8.3, §8.4, Phase 3 PR 3 | Gamma |
| Confidence band mapping (very_high/high/medium/low/blocked) | §8.2 | Gamma |
| Identity Decision ledger | §5.6, §2.4, Phase 4 PR 4 | Delta |
| Identity Graph Versioner | §5.8, Phase 4 PR 4 | Delta |
| Split/Unmerge execution engine | §10, Phase 5 PR 5 | Epsilon |
| Projection Restatement Orchestrator | §11, Phase 6 PR 6 | Zeta |
| SDK late-binding contract + parity | §14, Phase 7 PR 7 | Eta |
| Tenant Activation Dashboard | §12.1, Phase 8 PR 8 | Theta |
| Profile 360 Identity Panel | §12.2, Phase 8 PR 8 | Theta |
| Identity Review Queue | §12.3, Phase 8 PR 8 | Theta |
| Identity Explainability API | §13.2, Phase 8 PR 8 | Theta |
| Proof harness + fixtures | §17, §18, Phase 9 PR 9 | Iota |
| Observability metrics/traces/logs | §19, §20 | Iota |
| Feature flag wiring (identity continuity flags) | §15 | Iota |
| CI gates (Gates 1-7) | §22 | Iota |
| Docs: current-state-inventory, proof-plan, fixtures, rollout-plan | §21 | Iota |

---

## 1. Agent assignments

### Agent Alpha — Contract Spine (PR 1)
**Goal:** Create/align canonical identity contracts in TS + Python. Ensure all ingestion sources import the same identity contracts. Remove duplicate identity DTOs.

**Files to create/modify:**
- `packages/shared/contracts/identity/source-system.json` — source_system contract
- `packages/shared/contracts/identity/source-identity.json` — source_identity contract
- `packages/shared/contracts/identity/identity-claim.json` — identity_claim contract
- `packages/shared/contracts/identity/canonical-entity.json` — canonical_entity contract
- `packages/shared/contracts/identity/identity-edge.json` — identity_edge contract
- `packages/shared/contracts/identity/identity-decision.json` — identity_decision contract
- `packages/shared/contracts/identity/identity-conflict.json` — identity_conflict contract
- `packages/shared/contracts/identity/identity-graph-version.json` — identity_graph_version contract
- `packages/shared/contracts/identity/projection-restatement-job.json` — projection_restatement_job contract
- `packages/shared/contracts/identity/index.json` — manifest
- `packages/shared/src/identity/types.ts` — generated/normalized TS types (if generated contract system supports it; else hand-authored)
- Align `services/backend/services/identity/models.py` — add missing fields (confidence_band, decision_type vocabulary, positive_evidence, negative_evidence, vetoes, policy_version, decided_by, graph_version_before/after, explanation, candidate arrays)

**Acceptance:**
- All identity contracts exist as JSON registries
- Python models aligned with blueprint §5.1-5.9
- No duplicate identity DTOs in feature folders

---

### Agent Beta — Source Identity Registry (PR 2)
**Goal:** Create source identity registry. Wire CSV/connector/SDK/API/agent source identity creation. Add idempotency.

**Files to create/modify:**
- `services/backend/services/identity/source_identity_registry.py` — new service
  - `register_source_identity(input)` — create/update source identity
  - `upsert_identity_claim(input)` — normalize + store claim
  - `find_existing_source_identity(input)` — lookup by external_id/user_id/anonymous_id/device_id/installation_id + tenant
  - `get_claims_for_source_identity(source_identity_id)` — list claims
  - `mark_suppressed(source_identity_id)` — suppress
- `services/backend/services/identity/claim_normalizer.py` — new service
  - Email normalization (lowercase, strip, domain normalization)
  - Phone normalization (E.164)
  - Provider ID normalization (Shopify customer ID, Stripe customer ID, etc.)
  - Anonymous ID handling
- Wire into ingestion: `services/backend/services/ingestion/adapters/sdk.py` — source identity creation on SDK events
- Wire into providers: `services/backend/services/providers/shopify/` — source identity creation on customer sync
- Wire into providers: `services/backend/services/providers/woocommerce/` — source identity creation
- Wire into SDK routes: `services/backend/services/sdk/routes.py` — source identity on heartbeat/identify
- Add idempotency: source_record_id + idempotency_key dedup

**Acceptance:**
- CSV row, Shopify customer, Stripe customer, SDK anonymous ID, SDK user ID, mobile installation ID, API subject, agent ID all become source identities
- Idempotent: repeated import doesn't duplicate source identities

---

### Agent Gamma — Resolution Engine & Policy Hardening (PR 3)
**Goal:** Harden resolver with blueprint invariants. Add veto engine. Add confidence band mapping. Add entity-type mismatch veto. Add cross-tenant hard block.

**Files to create/modify:**
- `services/backend/services/identity/veto_engine.py` — new service
  - `evaluate_vetoes(input)` — check all hard vetoes:
    - cross-tenant candidate
    - deleted/suppressed identity
    - revoked consent grant
    - entity type mismatch (person↔agent, person↔account, device↔person)
    - conflicting verified emails
    - conflicting authenticated user IDs
    - known shared device
    - known shared inbox
    - provider namespace collision
    - simultaneous contradictory sessions
    - manual do-not-merge flag
  - Returns list of `IdentityVeto` objects
- `services/backend/services/identity/confidence.py` — extend:
  - Add confidence_band: "very_high" (>=0.97), "high" (0.90-0.969), "medium" (0.70-0.899), "low" (0.30-0.699), "blocked" (any veto)
  - Map ConfidenceTier → confidence_band
- `services/backend/services/identity/merge_policy.py` — extend:
  - Add entity type mismatch check (person ≠ agent, person ≠ account, device ≠ person)
  - Add conflicting verified email check
  - Add conflicting authenticated user ID check
  - Add shared device veto
  - Add shared inbox detection (role email patterns)
- `services/backend/services/identity/resolver.py` — extend:
  - Wire veto engine before merge decision
  - High score cannot override hard veto
  - Every observation produces one resolution outcome

**Acceptance:**
- Every observation produces: resolved, provisional, review_required, conflicted, suppressed, or rejected
- No observation silently bypasses identity resolution
- Hard vetoes always block auto-merge regardless of score

---

### Agent Delta — Merge Ledger & Graph Versioning (PR 4)
**Goal:** Make merges explicit, auditable, versioned, reversible.

**Files to create/modify:**
- `services/backend/services/identity/merge_ledger.py` — new service
  - `auto_merge(input)` — create decision record + execute merge
  - `manual_merge(input)` — operator merge with confirmation token
  - `block_merge(input)` — record blocked merge
  - `get_merge_history(canonical_entity_id)` — list all merge decisions
- `services/backend/services/identity/graph_versioner.py` — new service
  - `create_graph_version(input)` — increment graph version
  - `get_current_version(canonical_entity_id)` — current graph version
  - `get_version_history(canonical_entity_id)` — version chain
- Extend `services/backend/services/identity/models.py`:
  - Add `IdentityDecision` model (decision_type, candidate arrays, selected_entity, confidence, confidence_band, positive_evidence, negative_evidence, vetoes, policy_version, graph_version_before/after, explanation, decided_by, decided_at)
  - Add `IdentityGraphVersion` model (previous_version_id, version_number, reason, decision_ids, created_at)
- Extend `services/backend/services/identity/graph_writer.py`:
  - Every merge creates identity_decision
  - Every merge increments graph version
  - Every merge queues projection restatement (via event)

**Acceptance:**
- Every merge creates an identity_decision
- Every merge creates/updates identity_edges
- Every merge increments graph version
- Every merge queues projection restatement

---

### Agent Epsilon — Split/Unmerge Engine (PR 5)
**Goal:** Support bad-merge repair and conflict-based split candidates.

**Files to create/modify:**
- `services/backend/services/identity/split_service.py` — new service
  - `create_split_candidate(input)` — detect conflict, create split candidate
  - `approve_split(input)` — admin/operator approval
  - `execute_split(input)` — move source identities, reverse edges, create new entities
  - `move_source_identity(input)` — move source identity from one canonical entity to another
  - `reverse_identity_edge(input)` — reverse an edge
  - `get_split_history(canonical_entity_id)` — list splits
- Extend `services/backend/services/identity/split_policy.py`:
  - Add auto-detect conflict → create split candidate flow
  - Add approval token validation
- Extend `services/backend/services/identity/graph_writer.py`:
  - Edge reversal on split
  - Source identity reassignment
- Extend `services/backend/services/identity/resolver.py`:
  - Wire split candidate creation on conflict detection

**Acceptance:**
- Bad auto-merge can be split without deleting raw records
- Source identities move correctly
- Affected projections restate under new graph version
- Audit trail preserved

---

### Agent Zeta — Projection Restatement Orchestrator (PR 6)
**Goal:** Restate downstream views after identity changes.

**Files to create/modify:**
- `services/backend/services/projections/projection_restatement_orchestrator.py` — new service (create `services/backend/services/projections/` if not exists)
  - `queue_restatement(decision)` — create restatement job
  - `run_restatement(job)` — execute restatement
  - `restate_profile_360(entity_ids)` — recompute Profile 360
  - `restate_journeys(entity_ids)` — re-thread timelines
  - `restate_campaigns(entity_ids)` — reassign touchpoints
  - `restate_communications(entity_ids)` — rebind messages
  - `restate_value(entity_ids)` — reassign revenue (no duplicate)
  - `restate_signals(entity_ids)` — recompute profile signals
  - `restate_syndicates(entity_ids)` — recompute membership
- `services/backend/services/projections/restatement_job_repository.py` — new repository
  - ProjectionRestatementJob CRUD
- Wire into merge_ledger: after merge, queue_restatement
- Wire into split_service: after split, queue_restatement
- Extend `services/backend/services/profile/composer.py`:
  - Accept graph_version parameter for restatement
- Add event topics: `TOPIC_IDENTITY_MERGED` (already exists), `TOPIC_IDENTITY_SPLIT` (new), `TOPIC_PROJECTION_RESTATEMENT_QUEUED` (new)

**Acceptance:**
- Profile 360, Journey, Campaign, Communications, Value, Signals, Syndicates all update after merge/split
- Restatement is observable and retryable
- Raw data never rewritten
- Value restatement doesn't duplicate revenue

---

### Agent Eta — SDK Late Binding & Contract Parity (PR 7)
**Goal:** Ensure all SDKs emit enough identity evidence for late binding.

**Files to create/modify:**
- `services/backend/services/sdk/routes.py` — extend:
  - Anonymous-to-known binding flow
  - Heartbeat → source identity creation
  - Identify → source identity creation + resolution
  - Alias → anonymous-to-known binding
  - Reset → clear local anonymous context
- `services/backend/services/ingestion/adapters/sdk.py` — extend:
  - Extract anonymous_id, user_id, session_id, device_id, installation_id, traits, consent state
  - Map to source_identity + identity_claim
- `packages/shared/contracts/identity/sdk-contract.json` — new contract
  - Required SDK fields per blueprint §14.2
- SDK fixture apps (minimal):
  - `apps/proof-web/src/identity-test/` — web SDK test app
  - `apps/proof-react/src/identity-test/` — React SDK test app
  - `apps/proof-ios/src/identity-test/` — iOS SDK test app (stub)
  - `apps/proof-android/src/identity-test/` — Android SDK test app (stub)
  - `apps/proof-react-native/src/identity-test/` — React Native test app (stub)
- `services/backend/tests/identity/test_sdk_late_binding.py` — new test
  - Import-first SDK-later scenario
  - Anonymous-to-known scenario

**Acceptance:**
- Each SDK can: heartbeat, anonymous event, identify, alias, reset, consent state, idempotent retry
- Import-first SDK-later test passes
- Anonymous-to-known test passes

---

### Agent Theta — Tenant UX & Explainability (PR 8)
**Goal:** Expose identity continuity in product surfaces.

**Files to create/modify:**
- `services/backend/services/identity/explainability.py` — new service
  - `get_profile_identity_explanation(profile_id)` — return explanation object
  - `get_decision_details(decision_id)` — return decision with evidence
- `services/backend/services/identity/routes.py` — extend:
  - `GET /v1/profiles/{profile_id}/identity/explanation` — explainability endpoint
  - `POST /v1/admin/identity/merge` — manual merge with confirmation token
  - `POST /v1/admin/identity/split` — manual split with confirmation token
  - `POST /v1/admin/identity/reconcile` — re-run resolution
  - `GET /v1/admin/identity/review-queue` — open conflicts/reviews
  - `GET /v1/admin/identity/activation-status` — tenant activation dashboard data
- Frontend: `frontend/aether/src/features/identity/`
  - `TenantActivationDashboard.tsx` — activation status surface
  - `Profile360IdentityPanel.tsx` — identity panel component
  - `IdentityReviewQueue.tsx` — review queue page
  - `ConflictDetail.tsx` — conflict detail page
  - `MergeSplitAudit.tsx` — merge/split audit page
  - `SdkHealth.tsx` — SDK health page
- Wire feature flags: `identity_explainability_enabled`, `tenant_identity_activation_dashboard_enabled`

**Acceptance:**
- Tenant/admin can see: what imported, what resolved, what merged, what didn't merge, what needs review, why a profile exists, why sources were stitched, what projections were restated

---

### Agent Iota — Proof Harness, Observability & Release Gates (PR 9)
**Goal:** Prove the feature end-to-end. Add metrics/traces/logs. Wire feature flags. Add CI gates.

**Files to create/modify:**
- `services/backend/tests/identity/` — new fixtures:
  - `test_import_first_sdk_later.py` — Scenario A
  - `test_anonymous_to_known.py` — anonymous→known binding
  - `test_multi_sdk_same_user.py` — multi-SDK stitching
  - `test_shared_device_no_merge.py` — Scenario B
  - `test_shared_email_review.py` — shared email → review
  - `test_bad_merge_split.py` — Scenario C
  - `test_agent_human_no_merge.py` — Scenario D
  - `test_cross_tenant_block.py` — cross-tenant rejection
  - `test_deleted_identity_suppression.py` — suppressed identity block
  - `test_projection_restatement.py` — restatement after merge/split
  - `test_connector_reimport_idempotency.py` — duplicate import dedup
- `services/backend/services/identity/observability.py` — new service
  - Metrics: identity.source_identity.created.count, identity.resolve.*, identity.merge.*, identity.split.*, identity.veto.*, identity.cross_tenant_block.*, identity.projection_restatement.*
  - Traces: ingestion.receive → source_identity.register → claims.normalize → identity.resolve → policy.score → veto.evaluate → decision.write → graph_version.create → projection_restatement.queue → profile_360.update
  - Logs: every identity decision log with tenant_id, source_system_id, source_identity_id, candidate_entity_ids, decision_type, confidence, vetoes, policy_version, graph_version_before/after, projection_jobs_created
- Feature flags wiring (`config/release/feature_flags/`):
  - `identity_resolution_enabled`
  - `identity_auto_merge_enabled`
  - `identity_manual_review_enabled`
  - `identity_conflict_detection_enabled`
  - `identity_split_enabled`
  - `identity_manual_split_enabled`
  - `identity_auto_split_candidates_enabled`
  - `sdk_late_binding_enabled`
  - `anonymous_to_known_binding_enabled`
  - `multi_sdk_identity_stitching_enabled`
  - `connector_backfill_identity_resolution_enabled`
  - `projection_restatement_enabled`
  - `campaign_restatement_enabled`
  - `value_restatement_enabled`
  - `identity_explainability_enabled`
  - `tenant_identity_activation_dashboard_enabled`
  - `agent_identity_resolution_enabled`
- Docs:
  - `docs/blueprints/identity-continuity/current-state-inventory.md`
  - `docs/blueprints/identity-continuity/proof-plan.md`
  - `docs/blueprints/identity-continuity/fixtures.md`
  - `docs/blueprints/identity-continuity/rollout-plan.md`
- CI gates (`.github/workflows/`):
  - Gate 1: Contract gate — all identity contracts exist
  - Gate 2: Routing gate — all ingestion sources route through resolver
  - Gate 3: Merge safety gate — deterministic merges work, weak evidence doesn't merge, cross-tenant impossible, deleted/suppressed don't merge, entity type mismatch doesn't merge, conflicts block auto-merge
  - Gate 4: Split gate — bad merge can be split, source identities move, raw events immutable, graph version increments, projections restate, audit visible
  - Gate 5: Projection gate — Profile 360, Journey, Campaign (gated), Communications, Value (no duplicate), Signals, Syndicates restate
  - Gate 6: UX explainability gate — tenant/admin can see why profile exists, which sources, which evidence matched/ignored/blocked, current graph version, what changed
  - Gate 7: Proof pack gate — staging produces full proof pack

**Acceptance:**
- All 11 proof fixtures pass
- Tenant activation dashboard displays correct state
- Profile 360 identity panel explains current identity state
- Metrics/traces/logs expose full runtime path
- CI gates pass

---

## 2. Execution sequence

```
Phase 0 (concurrent): Alpha + Beta + Gamma
  → Alpha: contracts
  → Beta: source registry + claim normalizer
  → Gamma: veto engine + confidence bands + policy hardening

Phase 1 (concurrent): Delta + Epsilon + Zeta
  → Delta: merge ledger + graph versioner
  → Epsilon: split service
  → Zeta: projection restatement orchestrator

Phase 2 (concurrent): Eta + Theta
  → Eta: SDK late binding + parity
  → Theta: tenant UX + explainability API

Phase 3 (final): Iota
  → Iota: proof fixtures + observability + feature flags + CI gates + docs
```

**CI run:** After all agents complete, run:
```
cd /Users/osazehunt/AETHER
pytest services/backend/tests/identity/ -v
pytest services/backend/tests/computation/test_identity_restatement.py -v
# + any frontend tests for identity features
```

**Doc restamp:** After CI passes, update:
- `docs/blueprints/identity-continuity/implementation-blueprint.md` — mark implemented sections
- `CHANGELOG.md` — add identity continuity release entry

---

## 3. Risk register

| Risk | Mitigation | Owner |
|---|---|---|
| Silent bad merge | Decision records + vetoes + explainability (Gamma/Delta) | Gamma |
| Duplicate profiles | Source identity registry + idempotency (Beta) | Beta |
| Duplicate revenue | Value restatement checksums (Zeta) | Zeta |
| Weak evidence over-merging | Strict evidence classes + veto engine (Gamma) | Gamma |
| Shared device contamination | Device association only (Gamma) | Gamma |
| Agent/person confusion | Entity-type veto (Gamma) | Gamma |
| Cross-tenant leakage | Tenant namespace hard boundary (Gamma) | Gamma |
| Historical timeline corruption | Separate occurred_at/ingested_at/resolved_at (existing) | — |
| Projection drift | Versioned graph + restatement jobs (Delta/Zeta) | Delta/Zeta |
| Unrecoverable merge | Split/unmerge engine (Epsilon) | Epsilon |
| Tenant distrust | Profile identity panel + review queue (Theta) | Theta |
| CI green but runtime unproven | Proof fixtures + staging proof pack (Iota) | Iota |
