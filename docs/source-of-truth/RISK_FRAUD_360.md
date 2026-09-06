---
title: Risk360 and Fraud360 Architecture
slug: source-of-truth/risk-fraud-360
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
canonical_owner: backend@aether
estimated_read_minutes: 10
toc_depth: 3
---

# Risk360 and Fraud360 — Intelligence-Projection Architecture

This is the architecture source of truth for **Risk360** and **Fraud360**,
Aether's universal risk-evaluation and fraud-synthesis projections over the
Unified Intelligence Graph. The governing product blueprint is the **"Aether
Fraud360 + Risk360 — Canonical Development and Day-1 Implementation Blueprint"**
(the master specification this architecture reconciles to the repository); the
implementation program and its ledger are
[docs/plans/RISK_FRAUD_360_PHASES.md](../plans/RISK_FRAUD_360_PHASES.md). The
per-projection vertical-slice designs are
[docs/blueprints/risk360.md](../blueprints/risk360.md) and
[docs/blueprints/fraud360.md](../blueprints/fraud360.md).

Risk360 and Fraud360 are **intelligence projections** under the Intelligence
Projection Plane (ADR-010). They interpret canonical Aether truth; they do not
create an independent fraud graph, identity model, evidence model, timeline,
population model, outcome ledger, or decision system. Both are registered rows
in
[packages/shared/contracts/intelligence-projection-registry.json](../../packages/shared/contracts/intelligence-projection-registry.json)
with `graphMutationPolicy: read_only`, `ownsCanonicalTruth: false`, and
`requiresEvidence: true`.

## 1. Positioning

| | Risk360 | Fraud360 |
|---|---|---|
| Kind | **Evaluative 360** — a universal contextual risk assessment of a subject | **Domain-synthesis 360** — reconstruction of suspected deceptive/abusive mechanisms |
| Answers | "What could be materially harmful, abnormal, unstable, compromised, deceptive, or uncertain here, and why?" | "Do these facts collectively represent intentional deceptive activity; what mechanism, who participates, how does value move, and what supports or contradicts it?" |
| Subjects | `entity`, `relationship`, `cluster`, `population` | `entity`, `relationship`, `agent` |
| Output sections | `summary`, `state`, `evidence`, `findings`, `health` | `summary`, `state`, `evidence`, `findings`, `health` |
| Sinks | Findings → Investigation / OODA decision loop | Findings → Investigation / OODA decision loop |
| Legacy bindings | `/v1/risk-overlays`, `/v1/capability-risk` | `/v1/fraud` |

Risk360 is the primary subject workbench for risk; Fraud360 consumes Risk360
assessments and underlying graph truth to ask whether multiple facts form a
coherent fraud hypothesis. `fraud360` declares `projectionDependencies:
[profile360, risk360]`; `risk360` declares `projectionDependencies: [profile360,
economic360, cluster360]`. Flip order matters: **risk360 converges before
fraud360.**

## 2. Governing invariants

1. **One graph** — no `fraud_graph`. Both projections are `read_only`; any graph
   write anywhere in the plane flows through `GraphMutationGateway`.
2. **One identity model** — risk/fraud consume canonical identity resolution
   (Plane-4 `services/identity`); they may flag identity-risk conditions but
   never merge or split identities.
3. **One evidence system** — every claim references the canonical `EvidenceRef`
   from `services/operational_intelligence/models.py`. The divergent
   `EvidenceRef` in `services/fraud/models.py` is deleted before convergence
   (Phase 2 of the program).
4. **One temporal authority** — observed/recorded/valid/source/ingestion time,
   corrections, and known-then/known-now come from the temporal kernel
   (`TemporalEnvelope`, `TemporalMode.KNOWN_THEN`/`KNOWN_NOW`).
5. **One population system** — fraud rings, suspicious cohorts, and risk
   populations reuse cluster/population membership semantics (`cluster360`),
   never a fraud-specific cohort store.
6. **One outcome + economic model** — losses, exposure, prevented value, and
   recoveries reference economic360 / `MonetaryAmount` and the outcome/measurement
   plane; realized refund/chargeback dollars live in `revenue_adjustments`.
7. **One exploration context** — risk/fraud render inside `ExplorationContext`;
   filters never silently disappear (applicability report).
8. **Explicit epistemics** — see §5. A suspicious pattern may never silently
   become a factual declaration of fraud.

## 3. Canonical object model

Risk360 requires six new canonical intelligence contracts; Fraud360 requires
three. All are defined (Phase 3) against the reuse list below — never against
re-declared primitives.

| Contract | Homes | Notes |
|---|---|---|
| `RiskSignal` | risk contract module + storage | Atomic risk-relevant observation/derived condition; not itself a finding or fraud assertion |
| `RiskAssessment` | risk contract module + storage | Aggregates signals in a context (policy, dimensions, RiskVector, exposure, claim state, snapshot) |
| `RiskVector` (+ `RiskComponent`) | risk contract module | Multidimensional result; missing dimensions stay `missing`/`unknown`/`not_applicable`, never `0` |
| `ExposureAssessment` | risk contract module | "Risk of what" — exposed assets/outcomes/populations + economic value |
| `RiskAssessmentRun` | onto `computation_runs` | Reproducibility via `new_run_id()` + `context_hash` |
| `ControlEffectivenessAssessment` | risk contract module | Flag-gated; may defer to post-convergence until outcome/control data is sufficient |
| `FraudPattern` | fraud-pattern registry | Registered pattern conditions; aligned to existing `NetworkType`s, never a duplicate taxonomy |
| `FraudHypothesis` (+ state machine) | fraud contract module + storage | Fraud as hypothesis until evidence state supports it |
| `FraudHypothesisRun` | onto `computation_runs` | Reproducible synthesis runs |

**Reused (never re-declared):** `EntityRef`, `RelationshipRef`, `EvidenceRef`
(OI), `PageRequest`, `TimeRangeFilter`, `FilterExpression`, `GraphSnapshotRef`
(typed — added Phase 2), `CanonicalResult`/`MeasurementResult`, metric registry,
`ComputationDefinition`/`DecisionPolicy`, model registry, `MonetaryAmount`/
economic360, cluster/population memberships, comparison baselines.

## 4. Risk architecture

Risk intelligence is a pipeline over canonical observations:

```
contextualized facts → signal detectors → RiskSignal → baseline/peer comparison
→ aggregation → RiskVector → policy projection → RiskAssessment
   → Exposure · Finding candidate · (Fraud synthesis input)
```

- **Detectors** are the shipped, registered signal producers — fraud signals,
  fraud-network detectors, device risk, IP/geo enrichment, behavioral, trust —
  promoted to emit typed `RiskSignal`s with risk dimension, claim state,
  confidence, reused `EvidenceRef`s, and detector version (Phase 5).
- **Dimensions** (identity, authentication, behavioral, relationship, economic,
  transaction, payment, geographic, temporal, communication, campaign, agentic,
  execution, infrastructure, counterparty, population, operational, security,
  compliance, reputation, fraud, exposure, data_quality, model_uncertainty) are
  seeded as a versioned registry (Phase 3). Dimension state semantics follow
  `ValueState`: `missing`/`unknown`/`unavailable`/`not_applicable`/`suppressed`
  are legal; a dimension is never coerced to a fabricated zero.
- **Policy projection** — there is no universal meaning for an overall risk
  score. `DecisionPolicy` is extended (Phase 5) so the same RiskVector projects
  differently under `payment_authorization` vs `promotion_eligibility` vs
  `agent_execution`; thresholds live in policies, never as service constants.
- **Exposure** reads economic360 and `revenue_adjustments` for quantity and
  economic value; ControlEffectiveness is deferred.
- **Runs** reuse the computation substrate for reproducibility and late-data
  restatement (`supersedes` chains preserve both V1 and V2 — "what did Aether
  know at decision time").

## 5. Epistemic vocabulary (the no-silent-escalation rule)

Today the repository's epistemic/claim-state vocabulary is fragmented across
`CAUSALITY_CLASSES`, `OBSERVATION_CLASS_VALUES`, `LIFECYCLE_STATE_VALUES`,
`ResultStatus`, and projection section states. Phase 2 of the program promotes
one consolidated `EpistemicStatus` in `shared/contracts_models` so a claim can
carry any of:

```
observed  verified  resolved  derived  inferred  predicted  correlated
attributed  causally_supported  disputed  superseded  stale  unknown
unavailable  not_applicable
```

The rule: **a `derived`/`inferred`/`correlated` suspicion never renders as a
factual declaration** (`confirmed`/`causally_supported`) without an explicit,
evidence-grounded upgrade through the FraudHypothesis state machine. Fraud
hypothesis states (`candidate → under_evaluation → supported → material →
investigating → confirmed | rejected | inconclusive → closed`, plus
`superseded`/`disputed`/`stale`/`corrected`) are never rendered stronger than
the underlying contract permits. No unexplained traffic-light badges: `state`
output is derived from typed section/dimension states.

## 6. Fraud architecture

Fraud synthesis consumes risk assessments, fraud-network clusters and members,
flow-of-funds traces, fraud decisions, ordered behavior sequences
(journeys/`canonical_activity`), comms/execution facts, economic flows, and
outcome/`revenue_adjustments` facts, and produces `FraudHypothesis` records. The
`FraudPattern` registry (Phase 3) seeds blueprint §14 families aligned to the
shipped `NetworkType`s (`synthetic_identity_ring`, `account_takeover_cluster`,
`mule_network`, `reward_farming_ring`, `commerce_abuse_ring`, and the rest) plus
tenant-defined extensions through the same registry.

## 7. Downstream

- **Findings** — Risk360/Fraud360 are a *new* finding producer reusing the
  comparison-findings disposition ladder (`investigate` → `InvestigationCase`;
  `decide`/`act` → OODA recommendation). Materiality precedes Finding creation;
  risk does not auto-create findings.
- **Investigation** — an `InvestigationCase` is the formal sink; a FraudHypothesis
  can exist without one.
- **Noesis** — read-only explain/summarize intents over risk/fraud data
  (ADR-007); Noesis never mutates risk truth.
- **Kyber** — operator surfaces: Risk360 workbench + Fraud360 consolidation plus
  detector/pattern/policy/run health, served under the `/v1/admin/kyber/*`
  convention.
- **Events** — `aether.risk.signal.*`, `aether.risk.assessment.*`,
  `aether.fraud.hypothesis.*` are added to the bus `Topic` enum and the SDK
  `event-registry.json`. Events reference IDs; they never carry unaudited truth.

## 8. Storage

`risk_signal`, `risk_assessment`, `fraud_hypothesis` records are declared as
tenant-scoped JSONB repositories or an Alembic migration (the `fraud_decisions`
migration is the closest DDL template); runs live in `computation_runs`. No
materialized structure becomes canonical; everything rebuildable.

## 9. Scope boundaries

- **In this program:** contracts, governance vocabulary, providers/adapters,
  signal/assessment convergence, fraud synthesis, findings/investigation/OODA
  handoffs, Kyber + Noesis surfaces, convergence flip.
- **Deferred / not owned:** AML/KYC/sanctions screening engine (repo explicitly
  disclaims OFAC screening); external fraud-vendor connectors + typed
  `ExternalAssessmentObservation` (untyped Bronze/APIFeed capture exists today);
  full Geographic360/Population360/episode360 materialization (risk/fraud consume
  the real seams and record needs); graph-risk-of-the-graph and risk-propagation
  policies (Day-2/3).

## 10. Conformance

Risk360/Fraud360 converge under
[docs/blueprints/risk360.md](../blueprints/risk360.md),
[docs/blueprints/fraud360.md](../blueprints/fraud360.md), and the
[vertical-slice checklist](INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md).
The canonical completion gate is `make ci-check`; no `production_ready` claim is
derived from `implementationState`.
