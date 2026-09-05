---
title: Risk360 + Fraud360 — Phased Convergence Program
slug: plans/risk-fraud-360-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---
# Risk360 + Fraud360 — Phased Convergence Program

This is the implementation program for **Risk360 and Fraud360**, Aether's
universal contextual risk-evaluation and fraud-synthesis projections over the
Unified Intelligence Graph (the "Risk360 + Fraud360 Day-1 blueprint"). That
blueprint is the governing specification this program implements; this document
records the gap between the repository and the blueprint, orders the work into
phases, and is the ledger for what has shipped.

**The program's central finding: Risk360 and Fraud360 are not greenfield.** Both
are already registered in the canonical intelligence-projection registry as
`in_flight` projections (`migrationMode: adapter`, `graphMutationPolicy:
read_only`, `ownsCanonicalTruth: false`) whose `legacyBindings` point at fully
built, end-to-end-wired subsystems — the fraud scoring engine, fraud network
intelligence, flow-of-funds trace, risk overlays, investigations, trust scoring,
comparison baselines, and their Kyber surfaces. The work is therefore
**convergence**: make the two declared projections real by (1) authoring the
missing blueprint/DoD documents, (2) locking the governance vocabulary the
blueprint demands, (3) defining the small set of genuinely new canonical
contracts, and (4) registering native projection providers and adapters that
delegate to the shipped subsystems — then converging the thin Risk360 surface and
the Fraud hypothesis layer the blueprint requires on top.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document. The projection vocabulary
(`in_flight` → `implemented`, `migrationMode`, vertical-slice DoD) is defined in
[docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md](../source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md)
and
[INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md).

**Program base.** `feat/risk-fraud-360` tracks
[`feat/aether-360-program`](../../../feat/aether-360-program) — the branch
carrying the implemented 360 plane this program converges Risk360/Fraud360 onto:
the converged `economic360`/`outcome360`/`infrastructure360` providers, the lens
registry, the exploration→projection adapters, and the `docs/blueprints/`
directory. That lineage is intentionally **not** based on `origin/main`, which
does not yet contain the implemented 360 plane (the 360-program work is merged
to `origin/main` separately). Reconcile with `origin/main` when that lineage
lands.

## 0. How this program reads the blueprint

The blueprint speaks in vocabulary the repository does not share. This program
maps blueprint intent onto the real architecture and does not force the
blueprint's nouns onto the codebase:

| Blueprint language | Repository reality |
| --- | --- |
| "Eight Planes" (Plane 1–8) | The **Intelligence Projection Plane** (ADR-010) + the operational stacks in `docs/ARCHITECTURE.md`; no "8 Planes" doc exists |
| "Contract spine" | Declarative registries in `packages/shared/contracts/*.json` → generated Python/TS twins via `scripts/generate_platform_contracts.py`; runtime provider registry in `shared/intelligence_projections/` |
| "Risk360 / Fraud360 must consume the canonical graph, identity, evidence, population, temporal, outcome, economic models — not own them" | Already enforced structurally: `read_only` graph mutation, `ownsCanonicalTruth: false`, `tenantScoped`, `requiresEvidence`, canonical `EntityRef`/`EvidenceRef`, `TemporalEnvelope`, `MeasurementResult`/`CanonicalResult`, economic360 (implemented), `GraphMutationGateway` |
| "New contracts: RiskSignal, RiskAssessment, RiskVector, ExposureAssessment, …Run, ControlEffectiveness, FraudPattern, FraudHypothesis, FraudHypothesisRun" | Genuinely new; the exact deliverable of Phase 3 below. Must reference canonical primitives, never re-declare them |
| "One Epistemic status vocabulary (§3.11)" | Fragmented across several enums (`CAUSALITY_CLASSES`, `OBSERVATION_CLASS_VALUES`, `LIFECYCLE_STATE_VALUES`, `ResultStatus`, section states) — no unified authority. Phase 2 resolves this; it is the blueprint's key anti-silent-fraud-assertion guardrail |

## 1. Gap analysis

"Repository state" below reflects the audit that produced this program
(2026-09-03). Status legend: **FULL** = contract + code wired end-to-end;
**PARTIAL** = code/spec exists but incomplete or flag-gated OFF;
**SPEC-ONLY** = registry/doc row with no implementation or dangling reference.

| Area | Repository state before this program | Gap to the blueprint |
| --- | --- | --- |
| Projection registration | `risk360` + `fraud360` registry rows exist (`in_flight`, `adapter`); `risk`/`fraud` lenses exist; `outputSections: [summary,state,evidence,findings,health]`; capability keys `*.read`/`*.explore`; deps risk360→(cluster360,economic360,profile360), fraud360→(profile360,risk360) | **No native providers, no exploration adapters, no surface-capability rows** — neither 360 is a real exploration surface yet |
| Blueprints / DoD docs | Only `economic360.md`, `outcome360.md`, `infrastructure360.md` exist under `docs/blueprints/` | **`docs/blueprints/risk360.md` and `docs/blueprints/fraud360.md` are dangling references** (16 of 19 360 blueprints are dangling); no architecture source-of-truth mapping the master blueprint to the repo |
| Governance vocabulary (§3.11) | Epistemic/claim state fragmented across `CAUSALITY_CLASSES`, `OBSERVATION_CLASS_VALUES`, `LIFECYCLE_STATE_VALUES`, `ResultStatus`, `PROJECTION_SECTION_STATES`, identity `ConflictStatus`; no `verified`/`resolved` global state | **No single EpistemicStatus authority**; the invariant "a suspicious pattern may never silently become a factual fraud declaration" has no enforceable vocabulary |
| Canonical risk contracts (§5–13) | Nearest assets are `FraudDecision` (versioned, supersession chain), comparison `ComparisonFinding`, `trust_vector`/`IntelligenceScore`, economic360 `MonetaryAmount` — none is a canonical RiskSignal/RiskAssessment/RiskVector/Exposure | **RiskSignal, RiskAssessment (+RiskVector/RiskComponent), ExposureAssessment, RiskAssessmentRun, ControlEffectivenessAssessment absent**; no RiskDimension registry; no Exposure outcome types |
| Canonical fraud contracts (§14–17) | `NetworkType` (14 values) + detectors + `FraudDecision.reason_codes`; `services/fraud_networks` roles/scoring | **FraudPattern registry and FraudHypothesis (+ state machine, run) absent** — no hypothesis lifecycle, no supersede/dispute/stale/corrected handling |
| Evidence reuse | Canonical `EvidenceRef` in `operational_intelligence/models.py` reused by `fraud_networks`; **`services/fraud/models.py` defines a divergent duplicate `EvidenceRef`** | Duplicate must be deleted before convergence (violates "one evidence system") |
| Graph snapshot refs | `graph_snapshot_id` string fields on `ComputationContext`/`GraphMetric`; registry names `GraphSnapshotRef` as an `inputRef` | **`GraphSnapshotRef` is spec-only** — no typed reference class |
| Runs / reproducibility (§11, §17) | `new_run_id()` + `computation_runs` table + `context_hash` substrate real; Kyber runs screen exists | No cross-domain `RunRef` object — Risk/Fraud `*Run` contracts must reuse `computation_runs`, not add parallel tables |
| Findings / Investigations (§54–55) | `ComparisonFinding` is the only finding producer (disposition ladder: investigate → `InvestigationCase`, decide/act → OODA recommendation); `InvestigationCase` FULL | Risk/Fraud findings are a new producer type reusing the same two handoffs; no fraud/risk finding pipeline |
| Events (§59) | `aether.fraud.{network,decision,evaluation}.*`, `aether.risk.overlay.generated`, `aether.risk.annotation.updated`, `aether.flow.trace.*`, `aether.investigation.*` all exist | **`aether.risk.signal.*` and `aether.fraud.hypothesis.*` are greenfield** additions to `Topic` + `event-registry.json` |
| Fraud engine + network intelligence | **FULL** — `services/fraud` (8 signals, composite scorer, `FraudDecision` CRUD), `services/fraud_networks` (8 detectors, 14 network types, 17 roles, takedown→reattribution invalidation), `services/flow_trace`, `services/risk_overlay`, Kyber fraud pages | Nothing missing here — this is the substrate the fraud360 provider delegates to |
| Risk substrate | **FULL/PARTIAL** — trust score/vector, agent capability-risk + blast radius, `services/kyber/devices/risk.py`, geo/IP enrichment, behavioral signals; comparison baselines FULL (flag OFF) | Risk360 must *classify* these into dimensions and aggregate; Risk360 Kyber surface is currently thin (`frontend/aether` `use-journey-risk.ts`) |
| Downstream decision surfaces | OODA loop FULL (`fraud_review` recommendation family), Kyber operator console FULL, Noesis FULL + read-only (ADR-007, `risk_cluster_lookup` intent), `/v1/intelligence/*` conventions | Noesis risk/fraud explain intents; risk360 operator/health screens; hypothesis → finding → investigation wiring |
| Supporting-domain reality | economic360 implemented; `revenue_adjustments` carries realized refund/chargeback; population/cluster membership queryable (`cluster360`); journeys/`canonical_activity` give ordered sequences; comms link facts, agent/x402 execution facts real | Geographic360 service is a stub (real geo lives in `ip_enrichment` + `LocationObservation`); population360 filter materialization partial; episode360 is sentiment-only; Outcome360 backing store stubbed — Risk/Fraud consume the real seams and register needs, they do not build these |
| External provider scores (§2) | Generic Bronze/APIFeed capture persists arbitrary payloads with provenance + idempotency; `/v1/fraud` accepts a `FraudDecisionCreateRequest` | **No typed `ExternalAssessmentObservation` and no external fraud-vendor connectors** — Day-2; the "provider score is an observation, never Aether truth" rule is unenforced today |
| Compliance screening | RWA/crossdomain enums + archived ontology only; `REWARD_NO_CUSTODY_MODEL.md` explicitly disclaims OFAC | **Not owned by this program** (see §5 Deferred) |

## 2. Phase map

Phases are ordered so vocabulary and contracts land before any provider is
registered, and risk lands before fraud (fraud360 depends on risk360). Status in
the table below is current as of the latest ledger row; the ledger in §4 is the
authoritative per-phase record as each phase lands. Each phase ships with its
new behavior flag-gated **default OFF** until operationally validated, matching
the platform convention.

| Phase | What ships | Entry criteria | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| **1** — Blueprints + source of truth | `docs/blueprints/risk360.md` and `docs/blueprints/fraud360.md` authored against the real seams (registry rows, surfaces, DoD, migration plan; templates: `economic360.md`); a source-of-truth doc (`docs/source-of-truth/RISK_FRAUD_360.md`) reconciling the master blueprint to ADR-010 + registries; this plan | Master blueprint reviewed; audit (§1) accepted; program scope approved | Registry blueprint refs for `risk360`/`fraud360` resolve to real files; docs consistent; no behavior change | SHIPPED (`db2adccc`) |
| **2** — Governance vocabulary + convergence debt | Single authoritative epistemic vocabulary (EpistemicStatus) under `shared/contracts_models`, mapped onto the existing fragmented enums so `ClaimEnvelope`/fraud-hypothesis state can never silently upgrade a suspicion into a factual claim; typed `GraphSnapshotRef`; delete the duplicate `EvidenceRef` in `services/fraud` and converge call sites onto the canonical OI `EvidenceRef` | Phase 1 landed; epistemic design decision recorded | Vocabulary single-sourced with parity tests; snapshot ref typed; no duplicate EvidenceRef anywhere; `make ci-check` green | SHIPPED (`fbda361b`) |
| **3** — Canonical Risk/Fraud contracts + registries + storage | Domain contract modules for `RiskSignal`, `RiskAssessment` (+`RiskVector`/`RiskComponent`), `ExposureAssessment`, `FraudPattern`, `FraudHypothesis` (+ state machine), run references onto `computation_runs`; risk-dimension + fraud-pattern registry seeds (blueprint §7/§14 Day-1 sets, fraud families aligned to existing `NetworkType`s); `risk_signal`/`risk_assessment`/`fraud_hypothesis` storage (JSONB repos or Alembic); all contracts carry `tenant_id` and reference only canonical primitives. Metric-registry rows and outcome-type-registry additions (refund, loss, payment_reversal, credential_compromise, reward issuance) **deferred**: both target rows carry empty `metricRefs` and `metric-registry.json` has no `pendingReference` rows to clear, so absorption buys zero validator progress and lands (if at all) with the Phase-5 exposure surfacing. Registries ship as **typed Python** (frozen-dataclass + frozenset keys), not JSON, per scoping decision §5.1 | Phase 2 landed; reuse inventory accepted | Contracts import zero duplicate primitives; registries seeded with alignment tests (every fraud family refs a real `NetworkType`/`MemberRole`); storage repos tenant-scoped JSONB via the reused `BaseRepository`; `make docs-check` green (projections still `in_flight`) | SHIPPED |
| **4** — Providers + projection convergence (core wiring) | `Risk360Provider` + `Fraud360Provider` implementing `IntelligenceProjectionProvider`, registered via `ProviderRegistry`; surface-capability rows for both 360s; `ProjectionSurfaceAdapter` subclasses so `/v1/explore` with `lens: risk`/`fraud` returns real projections; `read_only` graph posture enforced; new `Topic` members for `aether.risk.signal.*`, `aether.risk.assessment.*`, `aether.fraud.hypothesis.*` (the plan's `event-registry.json` rows do not exist — that file is a telemetry-type registry with zero `aether.*` domain rows; the hand-maintained `Topic` enum is the authority and is captured by the `docs/_generated/topics.json` generator, so rows there would be wrong) | Phase 3 landed; contracts stable | Enabled flag-on: `/v1/explore` returns risk/fraud projections through providers with no-silent-drop applicability; provider + adapter tests green; `make ci-check` green | SHIPPED |
| **5** — Signal convergence + RiskAssessment reality | Ship detectors promoted to typed `RiskSignal` emission (fraud signals ×8, fraud-network detectors ×8, device risk, IP/geo enrichment, behavioral, trust) with risk_dimensions / claim_state / confidence / OI evidence refs / detector version; baseline + peer comparison (comparison baselines); aggregation → RiskVector → policy projection → RiskAssessment per subject; `DecisionPolicy` extension for dimension weights/thresholds (§10); Exposure via economic360 + `revenue_adjustments`; `RiskAssessmentRun` on `computation_runs` with `context_hash` determinism; findings-candidate materiality hook | Phase 4 landed | Detector → signal → assessment pipeline with baselines + reproducible-run tests; risk lens returns assessments; materiality/finding-candidate path tested | SHIPPED |
| **6** — Fraud synthesis + downstream + surfaces + convergence flip | Operational FraudPattern evaluation; FraudHypothesis generator consuming risk assessments, network clusters, flow traces, fraud decisions, journey sequences, economic flows; hypothesis state machine + supersede/dispute/stale/corrected + `FraudHypothesisRun`; hypothesis → Finding (disposition ladder) → `InvestigationCase` + OODA `fraud_review`; Kyber operator surfaces (Risk360 workbench + Fraud360 consolidation under the existing fraud pages; detector/pattern/policy/run health per blueprint §74–76 via `/v1/admin/kyber`); Noesis read-only intents (assessment explain, hypothesis summarize, contradiction surfacing); per-360 vertical-slice flip to `implementationState: implemented` + `migrationMode: converged` (risk360 first, fraud360 after); regenerate + final release evidence | Phases 4–5 green | Both projections `implemented`/`converged`; vertical-slice checklist satisfied; `make ci-check` + `make release-gate` green; ledger complete | SHIPPED (`54f194e7`) — `implemented`/`converged` + ledger complete on this branch; `make ci-check`/`make release-gate` green deferred to the post-merge re-cut (base-lineage npm-ci lockfile defect) |

### Implementation priority

- **Blueprints (Phase 1) first.** The DoD documents pin every later phase to the
  real seams; they are also the only way to clear the dangling registry refs.
- **Vocabulary + convergence debt (Phase 2) before contracts (Phase 3).**
  Contracts compile against the epistemic vocabulary and snapshot/evidence
  types; landing the duplicate-EvidenceRef fix before new contracts prevents the
  new code from importing the wrong one.
- **Contracts (Phase 3) before providers (Phase 4).** Providers emit contract
  sections; they cannot be written against a moving contract surface.
- **Providers (Phase 4) before signal convergence (Phase 5).** RiskSignal output
  needs an exploration seam to be observed; the adapter is that seam.
- **Risk (Phase 5) before fraud synthesis (Phase 6).** `fraud360` depends on
  `risk360`, and hypotheses consume risk assessments as contributing inputs.
- **Downstream + flip (Phase 6) last.** Findings/investigations/OODA, Kyber
  surfaces, and Noesis intents consume stable providers; the
  `in_flight` → `implemented` flip is the definition of done and therefore lands
  only after every dependency is settled and CI-guarded.

### Reuse inventory (contracts may reference, never re-declare)

Canonical `EntityRef`/`EvidenceRef`/`InvestigationCase` (OI models), `TemporalEnvelope`
+ bitemporal kernel + `KNOWN_THEN`/`KNOWN_NOW`, `MeasurementResult`/`CanonicalResult`
+ metric registry + `ValueState`, `ComputationDefinition`/`DecisionPolicy`/model
registry, `new_run_id()` + `computation_runs` + `context_hash`,
`GraphMutationGateway` (read-only for risk/fraud), `GraphClient`/traversal,
`MonetaryAmount`/economic360, `cluster360`/population memberships, comparison
baselines, `services/fraud` + `services/fraud_networks` + `services/flow_trace` +
`services/risk_overlay` + `services/agent_access_intelligence`, trust
score/vector, journeys/`canonical_activity`, comms link facts, agent/x402
execution facts, `Topic` event bus + outbox, `/v1/explore` fabric
(`ExplorationContextV1`, applicability, saved views).

## 4. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-03 | kickoff | Program plan authored on `feat/risk-fraud-360`; branch re-based onto `feat/aether-360-program` `fced2960` (the implemented-360-plane lineage) after confirming `origin/main` lacks the 360 foundation; audit (§1) maps the master blueprint to repository reality; Risk360/Fraud360 confirmed as `in_flight` convergence targets over shipped subsystems, not greenfield; phases not yet started |
| 2026-09-03 | 1 | SHIPPED — `docs/blueprints/risk360.md`, `docs/blueprints/fraud360.md`, and `docs/source-of-truth/RISK_FRAUD_360.md` authored; registry blueprint refs for both rows resolve to real files; docs manifest + REPO-INDEX synced; `make docs-check` green (46/0). Pre-existing `repo-doctor-fix`/`ci-check` npm-ci lockfile failure recorded as a base-lineage defect, deferred to the post-merge re-cut |
| 2026-09-03 | 2 | SHIPPED — consolidated `EpistemicStatus` (15 values, no-silent-escalation invariant) in `shared/contracts_models/epistemic.py` + mapping tables over the fragmented vocabularies; TS twin `packages/shared/epistemic-status.ts` + parity test; typed `GraphSnapshotRef` added to `services/operational_intelligence/models.py`; duplicate fraud-local `EvidenceRef` deleted from `services/fraud` and call sites converged onto the canonical OI `EvidenceRef` with a one-way legacy JSONB compat loader (`services/fraud/evidence.py`); 23 targeted tests green; `make docs-check` green (46/0); registry rows still `in_flight` |
| 2026-09-03 | 3 | SHIPPED — built by two parallel subagents over the approved Phase-3 brief, integrated + committed by the orchestrator. **`services/risk360/`**: `contracts.py` (`RiskContract` `extra="forbid"` base; `RiskSignal`, `RiskComponent`, `RiskVector` sparse + honest-absence, `ExposureAssessment`, `RiskAssessment`, `RiskAssessmentRun` onto `computation_runs` via `new_run_id()`), `dimensions.py` (frozen-dataclass `RiskDimension` registry, full SoT §4 24-dimension set, `ValueState` reuse), `store.py` (tenant-scoped JSONB `RiskSignalRepository`/`RiskAssessmentRepository` via the reused comparison `BaseRepository`, no Alembic). **`services/fraud360/`**: `contracts.py` (`FraudPattern`, `FraudHypothesisState` 13-state, `FraudHypothesis`, `FraudHypothesisRun`, `FraudHypothesisStateMachine` enforcing no-silent-escalation — `confirmed` requires a factual claim state, `rejected` requires evidence), `patterns.py` (16 Day-1 families, every ref a real shipped `NetworkType`/`MemberRole`), `store.py` (`FraudHypothesisRepository`, state machine enforced at the storage boundary). Feature flags `AETHER_RISK360_ENABLED`/`AETHER_FRAUD360_ENABLED` (`RiskFraud360Config`, default OFF) added to `config/settings.py`. Contracts import zero duplicate primitives (identity-parity tested against canonical `EvidenceRef`/`EntityRef`/`GraphSnapshotRef`/`EpistemicStatus`); `RiskComponent` value-state invariant uses `requires_value()` so a missing dimension can never carry a fabricated `0.0`. 62 new tests green (24 risk360 + 38 fraud360; full Phase-2+3 combined suite 85 passed). `make docs-check` green (46/0) after syncing the test-file count (REPO-INDEX 516→517). Scoping: registries ship as **typed Python** not JSON; **metric-registry + outcome-type additions deferred** (rows have empty `metricRefs`, no `pendingReference`s exist); exposure `ValueState` gap resolved by importing canonical `ValueState` and mapping `missing`/`unknown`→`MISSING_INPUTS` with `not_applicable` preserved (never zeroed). Registry rows still `in_flight` |

| 2026-09-03 | 4 | SHIPPED — built by two parallel subagents (provider + routes each) over the approved Phase-4 brief, integrated + committed by the orchestrator. **`services/risk360/provider.py`** (`RiskSourceReader` Protocol + `RepositoryRiskSourceReader` over the Phase-3 `RiskAssessmentRepository`/`RiskSignalRepository`; `Risk360Provider(projection_id="risk360")` emitting the 5 typed sections `summary/state/evidence/findings/health`; missing dims typed `missing_inputs`/`not_applicable`/`unknown`, never `0`; zero-component assessment → honest `empty`; findings degraded until the Phase-5 materiality path; dependency degradation on profile360/cluster360; content-free fail isolation; tenant scoped; `register_provider` explicit, no import-time side effect) + **`routes.py`** (`/v1/risk360` GET `/{subject_kind}/{subject_id}` + `/health`, tenant read gate + `PROJECTION_CAPABILITY_MAP` fail-closed, mirror infra). **`services/fraud360/provider.py`** (`FraudSourceReader` Protocol + `RepositoryFraudSourceReader` over `FraudHypothesisRepository`; `Fraud360Provider(projection_id="fraud360")`, state + `claim_state` echoed verbatim so a `derived`/`inferred` suspicion never renders `confirmed`; supporting + contradictory `EvidenceRef`s first-class; material-phase hypotheses only as finding candidates; risk360/profile360-missing degradation; no-silent-escalation cross-cut test) + **`routes.py`** (`/v1/fraud360`). Surface rows `risk360`/`fraud360` added to `surface-capability-registry.json`; both projection rows' `surfaceIds` + `legacyBindings.surfaceIds` extended (surface_honesty satisfied; validator 0 errors, warnings unchanged 12, resolved refs 43→45); `Risk360SurfaceAdapter`/`Fraud360SurfaceAdapter` joined `_ADAPTER_TYPES`; `Topic` members `aether.risk.signal.{created,superseded}`, `aether.risk.assessment.{created,superseded}`, `aether.fraud.hypothesis.{created,updated,confirmed,superseded}` added (captured by `docs/_generated/topics.json`); `/v1/risk360` + `/v1/fraud360` classified in `route_registry.yaml`; **main.py** flag-gated block (`AETHER_RISK360_ENABLED`/`AETHER_FRAUD360_ENABLED`) registers both providers on the global `projection_registry` and mounts their routers — the FIRST production registration site for any 360 provider (the audit confirmed the implemented outcome360/economic360/infrastructure360 providers have no app-runtime registration call site yet; pre-existing gap, flag-default-OFF means no behavior change). Regenerated platform twins (surface/projection) + topics doc. Tests: risk360 52 passed (Phase-3+4 package), fraud360 22 provider passed, combined Phase-2/3/4 suite 111 passed; route-registry coverage 15 passed; projection-surface + noesis adapter 15 passed; consumer-specs parity 4 passed. `make docs-check` gate (46/0) green after this commit. Rows still `in_flight` |
| 2026-09-03 | 5 | SHIPPED — built by one implementation subagent over a seam-audit brief, integrated + extended by the orchestrator. **`services/risk360/signals.py`** — producer→RiskSignal convergence adapters over all six shipped seams (the 8 `FraudSignal`s via `FraudEngine.evaluate`, the 8 fraud-network `EvidenceTuple` detectors, `kyber` device risk, geo `GeoLookup` datacenter/ASN enrichment, behavioral scan, `trust_vector`); every emitted `risk_dimension` registry-asserted; a numeric is promoted to a typed 0–1 `score` only when the producer flags it `calibrated`, else `score=None` (no fabricated numbers); content-derived signal/evidence ids (deterministic); claim_state never silently escalated (heuristic outputs → `derived`/`inferred`). **`policies.py`** — typed `RiskPolicy` registry (dimension weights ⊆ the 24 registered keys; aggregate decision via the canonical `DecisionPolicy`; thresholds live in the policy row, never service constants) + weighted aggregation (empty vector → fail-closed `REVIEW`). **`exposure.py`** — `ExposureAssessment` from economic360 `safe_rollup` netting realized `revenue_adjustments`; unpriced → honest None, never fabricated. **`materiality.py`** — comparison-plane `score_materiality` hook (`None` when nothing evidence-backed — never a silent low-severity score). **`pipeline.py`** — deterministic aggregation (strongest score per dimension; unscored → `insufficient_data`, never zero; claim escalation blocked), policy projection, `compute_assessment`/`assess_subject` → `RiskAssessment` + `RiskAssessmentRun` over a content-only `ComputationContext` hash (identical evidence ⇒ identical `assessment_id` + `context_hash`; restatement supersedes), and the orchestrator-added **`persist_assessment`** write path: assessment → `risk_assessments`, signals → `risk_signals`, run → `computation_runs` via `ComputedResultsRepository.insert_run` (the first production writer for that row), repeat runs recording `supersedes_run_id`. Deferred with reason: live peer-baseline/`comparison_baselines` consumption (that API is event-behavioral dimension observations + comparison plane default-OFF; baseline presence participates in run identity, never fabricates subject scores); broker event emission deferred to Phase-6 producer wiring (no-op emitter seam). Tests: risk360 suite 94 passed (signals 11 + policies 7 + pipeline 15 incl. the persist path + exposure 5 + provider/contracts/store/dimensions), downstream consumers 63 passed; `ruff` clean; `make docs-check` 46/0 green. Registry rows still `in_flight` |

| 2026-09-03 | 6 | SHIPPED — Phases 6A–6D built by three parallel subagents over seam-audit briefs (fraud-synthesis backend, Noesis read-only intents, Kyber operator UI) + a docs-sync review agent, integrated + committed by the orchestrator. **6A (`8da22279`) `services/fraud360/hypotheses.py`** — `FraudHypothesisEvidence`; `FraudEvidenceReader` Protocol + `RepositoryFraudEvidenceReader` (lazy repo reads, per-authority degrade-to-empty, never raises); `evaluate_pattern` heuristic alignment (no invented numeric probabilities); deterministic `generate_hypotheses` (suspicion-only claim_state, content-derived ids/hash, empty when zero matches); `hypothesis_materiality` rubric (`None` when nothing evidence-backed); `persist_hypotheses` (skip-existing creates + one `computation_runs` row under `fraud360.hypothesis`/v1, `supersedes_run_id` on repeat); supersede/dispute/mark_stale/correct lifecycle wrappers through the state machine. **`downstream.py`** — `hypothesis_to_finding_candidate` (`None` unless material with a mappable claim; causal claim capped at the evidence ceiling); `material_hypotheses_to_findings` (disabled ⇒ honest `DISABLED_ENVELOPE`; enabled creates via the comparison `FindingsService`, per-hypothesis created/suppressed/skipped/error); `dispose_finding` delegating to the canonical disposal ladder (no re-implementation). Tests: fraud360 suite 80 passed; ruff clean. **6B (`6404796b`) Noesis read-only intents** — `risk_assessment_explain`, `fraud_hypothesis_summarize`, `risk_fraud_contradiction_lookup` into `SUPPORTED_INTENTS` + `QueryPlan.intent`; 1:1 `CAPABILITY_REGISTRY` entries (read-only + flag-gated); `_classify` rules + `_risk_fraud_dispatch` honoring `risk_fraud_360.risk360_enabled`/`.fraud360_enabled` (default OFF ⇒ `service_disabled`) under `_assert_read_only`; `adapters/risk_fraud_adapter.py::RiskFraudNoesisAdapter` reads `RiskAssessmentRepository` + `FraudHypothesisRepository` (honest `sufficient=False`, never mutates). Tests: 18 new + noesis core suites 93 passed. **6C (`147faae0`) Kyber operator surfaces** — `/fraud/risk-360` (Risk 360 workbench, kinds entity\|relationship\|cluster\|population) + `/fraud/fraud-360` (Fraud 360 consolidation, kinds entity\|relationship\|agent); nav labels `Risk 360`/`Fraud 360`; feature modules `features/{risk360,fraud360,projection-plane}`; `api` risk360/fraud360 projection + health GETs with 503/404/400 ⇒ graceful not-enabled EmptyState; tsc exit 0 (strict). **6D convergence flip (`54f194e7`)** — registry rows `risk360` then `fraud360`: `implementationState in_flight → implemented`, `legacyBindings.migrationMode adapter → converged` (graph still `read_only`, `ownsCanonicalTruth` false — projections over shipped subsystems, not new canonical truth); platform twins regenerated (generated_registry.py, intelligence-projections_generated.ts, registry table). Registry now 19 projections / 5 implemented (outcome360, economic360, infrastructure360, risk360, fraud360). Gate: `make docs-check` 46/0 green; targeted pytest green (84 risk360+fraud360 backend, 93 noesis core). Honesty: `implemented`/`converged` reflects the shipped code slice per the vertical-slice day-1 checklist on this branch; the full `make ci-check`/`make release-gate` confirmation (incl. the pre-existing npm-ci lockfile base defect) is deferred to the post-merge re-cut onto `origin/main`; no `production_ready` claim is made anywhere.

When a phase lands, its row is updated here; the phase map in §2 carries the
current status. As of this row Phases 1–6 have shipped.

**Phase-4 close-out (source-linked docs drift + gate):** the post-commit
`docs-check` flagged 10 source-linked docs stale (accumulated source changes in
Phases 2–4). Genuine content updates after review (never blind stamps):
`docs/SUBSYSTEM-EVENTS.md` — topic count corrected 181→248 (real count, already
stale before this work) + Risk360/Fraud360 read-only projection-plane domain
bullet; `docs/BACKEND-API.md` — `/v1/risk360` + `/v1/fraud360` classified
read-only projection surfaces documented beside the `/v1/infrastructure`
precedent in the Intelligence Projection Plane section. The remaining 8 docs
stamped-only after review as out of scope: `ARCHITECTURE.md` (19-row /
3-implemented claims remain accurate — risk360/fraud360 still `in_flight`),
`OPERATIONS-RUNBOOK.md` (run-control mount inventory for the projection planes
lands in Phase 6 with the flip, not now), `UNIVERSAL-PROVIDER-RUNTIME.md`
(UPR-plane scoped), `BACKEND-EXECUTION-MODEL.md`, `DECISION-OUTCOME-INTELLIGENCE.md`,
`OPERATIONAL-INTELLIGENCE-AUDIT.md` (dated audit snapshot),
`DEPLOYMENT_PROFILE_MATRIX.md` + `TARGET_ARCHITECTURE.md` (economic-interop
domain scope). `python scripts/docs_drift.py --update` stamped all 10 at
`fefdc514`. Auto commit-security review flagged the route read-gate ("missing
capability enforcement") on both Phase-4 route files; the gate is byte-parity
with the accepted `infrastructure360` precedent — base `read` enforced
in-handler + per-projection capability asserted-declared (fail-closed on
registry contradiction), capability possession enforced at the platform
route-classification boundary — so no new fail-open is introduced; acknowledged,
no change. `make docs-check` 46/0 green.

## 5. Decision log and deferred scope

### Decisions to record early

1. **Epistemic vocabulary: consolidate vs. map.** Recommended: promote one
   `EpistemicStatus` under `shared/contracts_models` (blueprint §3.11) and map it
   onto the existing enums — the "suspicion never silently becomes fraud"
   invariant needs one authority a UI cannot overstate. Alternative (rejected as
   weaker): translate across the five existing enums per surface.
2. **Contract/module home.** Recommended: new `services/risk360/` and
   `services/fraud360/` provider+contract modules that *delegate to* the shipped
   subsystems (mirrors `services/economic/economic360_provider.py`); confirm in
   Phase 1 blueprint authoring.
3. **Runs.** Reuse `computation_runs` via `new_run_id()`/`context_hash`; do not
   add parallel run tables. A typed cross-domain `RunRef` may be added to
   `shared/computation/` only if needed.
4. **Registries.** Risk dimensions + fraud patterns as declarative JSON registries
   seeded from the Day-1 sets (blueprint §7/§14); fraud families align to
   existing `NetworkType`s rather than replacing them.
5. **Exposure / ControlEffectiveness scope.** Exposure lands with Phase 5;
   ControlEffectivenessAssessment is flag-gated and may defer to post-convergence
   until outcome/control data is sufficient.

### Deferred / not owned by this program

- **AML / KYC / sanctions screening engine** — currently enums + archived
  ontology only, and `docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md` disclaims
  OFAC. A separate governed program; not a Risk360/Fraud360 dependency.
- **External fraud-vendor connectors + typed `ExternalAssessmentObservation`** —
  Day-2. Untyped Bronze/APIFeed capture with provenance exists today.
- **Geographic360 / Population360 / episode360 / Outcome360 full
  materialization** — owned by those projections; Risk/Fraud consume the real
  seams (`ip_enrichment`, `LocationObservation`, `cluster360` memberships,
  journeys/`canonical_activity`, `revenue_adjustments`) and record needs here.
- **Graph-risk of the graph itself (blueprint §48) and risk-propagation policies
  (§49)** — Day-2/3, layered once RiskVector is real.
