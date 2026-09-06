---
title: "Fraud360 Vertical Slice Blueprint"
slug: blueprints/fraud360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Fraud360 — Intelligence-Projection Blueprint

**Registry id:** `fraud360`
**Projection kind:** `risk_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`fraud360` to `implementationState: "implemented"`. Executed as program phase 6
of [docs/plans/RISK_FRAUD_360_PHASES.md](../plans/RISK_FRAUD_360_PHASES.md),
**after `risk360` has converged** (`fraud360` declares `projectionDependencies:
[profile360, risk360]`).

---

## What it is

Fraud360 is Aether's **domain-synthesis 360** — a fraud-specific graph-synthesis
projection over canonical Aether truth, for subjects of kind `entity`,
`relationship`, or `agent`. It answers "is there evidence that these facts
collectively represent intentional deceptive or abusive activity, what mechanism
is occurring, who or what participates, how does value move, what is affected,
and what supports or contradicts the hypothesis?" by **reading** the canonical
fraud/risk authorities — risk assessments (`risk360`), fraud engine decisions,
fraud-network clusters and membership, flow-of-funds traces, ordered behavior
sequences, execution and communication facts, economic flows, and outcome facts
— and projecting typed, evidence-grounded fraud hypotheses through the shared
Intelligence Projection Plane contracts.

It is NOT a competing system of record (ADR-010, `ownsCanonicalTruth: false`),
NOT a case-management system, and NOT a separate graph or identity/evidence/
population model. Fraud is represented as a **hypothesis** until the required
evidence state supports it. It never writes: `graphMutationPolicy: read_only`;
there is no write path at all.

## Why

The backend already ships a fully-wired fraud subsystem — the fraud scoring
engine (`services/fraud`, `/v1/fraud`), fraud network intelligence
(`services/fraud_networks`), and flow-of-funds tracing — as mounted routes and
services with Kyber operator pages, but nothing states what the *Fraud360
surface* is relative to canonical truth, and there is no hypothesis layer
standing between "a suspicious pattern was detected" and "fraud occurred". This
slice lands `fraud360` as a first-class projection: a real provider implementing
the `IntelligenceProjectionProvider` protocol that reads those shipped
subsystems plus `risk360` assessments, and adds the synthesis contracts —
`FraudPattern`, `FraudHypothesis`, `FraudHypothesisRun` — that make suspicion
explicit, evidence-grounded, reviewable, and never silently factual.

## How it works

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | fraud-synthesis state for the subject: families involved, hypothesis count/state, materiality, exposure — assembled from the sources below |
| `state` | typed `SectionState` per hypothesis and family — `candidate` … `confirmed | rejected | inconclusive | closed`, plus `superseded`/`disputed`/`stale`/`corrected`; never rendered stronger than the contract permits |
| `evidence` | reused `EvidenceRef`s supporting the synthesis **and** `contradictory`/missing evidence — both are first-class |
| `findings` | hypothesis-derived material findings; degraded honestly until the findings path (phase 6) is live |
| `health` | detector/pattern freshness and synthesis-run health; degraded honestly when a source is flag-gated off |

Every read is defensive: an unavailable backing source degrades its section,
never crashes, never fabricates. `requiresEvidence`, `requiresDimensionState`,
`requiresFreshness`, and `requiresLimitations` are honored.

### Epistemic honesty (the no-silent-fraud-declaration rule)

- A detected pattern is **not** proof of fraud. `FraudHypothesis` states flow
  `candidate → under_evaluation → supported → material → investigating →
  confirmed | rejected | inconclusive → closed`, with additional transitions
  `superseded`, `disputed`, `stale`, `corrected`. Confirmation requires the
  evidence state the pattern declares.
- Every hypothesis carries a claim state from the consolidated `EpistemicStatus`
  vocabulary, a confidence, matched patterns, materiality, reused `EvidenceRef`s,
  and contradictory evidence. Contradictions and missing evidence are surfaced,
  never hidden.
- UI/Noesis render hypothesis state labels without converting them into stronger
  epistemic claims than the underlying contract permits.
- "Aether suspects" never renders as "Aether knows" without an evidence-grounded
  upgrade through the state machine.

### Dependency story (profile360 / risk360)

`fraud360` declares `projectionDependencies: [profile360, risk360]`. Until
`risk360` is `implemented`, the registry computes it as `missing` and the
provider degrades the risk-assessment contributions to its synthesis honestly —
`FraudHypothesis` without contributing risk assessments is a partial hypothesis,
surfaced as such — never failing the projection. When `risk360` lands, the
synthesis lifts with zero code change. This ordering is structural: fraud
synthesis consumes Risk360 assessments and underlying graph truth.

### No redefinition

The slice reuses the canonical `EntityRef`, `RelationshipRef`, `EvidenceRef`,
`PageRequest`, `TimeRangeFilter`, and `FilterExpression` primitives — the fraud
synthesis package declares NO second copy (parity-tested). The divergent
`EvidenceRef` in `services/fraud/models.py` is removed before convergence so
`FraudHypothesis` evidence is the canonical OI `EvidenceRef`. `inputRefs`
include `GraphSnapshotRef` (typed in program phase 2), which pins each
hypothesis to the graph snapshot it was synthesized against.

### Pattern registry alignment

`FraudPattern` is a registered pattern system, not a parallel taxonomy. The
Day-1 families (promotion abuse, referral abuse, synthetic identity, account
takeover, payment fraud, refund/chargeback abuse, bot activity, device farm,
conversion manipulation, credential abuse, agent abuse, counterparty fraud,
collusion, circular value flow, wallet abuse, reward extraction) seed the
pattern registry **aligned to the shipped `NetworkType`s** and detector outputs —
never duplicating them. Tenant-defined extensions register through the same
registry.

### Metric absorption

`metricRefs` is empty today. Before the flip, the fraud metric set is absorbed
into `metric-registry.json` (and the hand-authored
`shared/measurement/registry.py` mirror) field-for-field — supported-hypothesis
rate, hypothesis count by family/state, mean exposure, contradiction ratio,
finding rate — clearing any `pendingReference` rows whose
`resolvesInProjection` is `fraud360`, surfaced in `summary` metrics with
honestly-`missing` values where data does not exist.

### Zero-pending declaration

With pending references cleared and no `pendingAuthority`, `fraud360` becomes a
**zero-pending** row eligible for `implementationState: "implemented"` and
`legacyBindings.migrationMode: "converged"` once the orchestrator flips it.
`ownsCanonicalTruth` stays structurally `false`.

## What it means for the graph

Fraud360 projects *over* the canonical graph's fraud-relevant truth — identity,
relationships, agents, economic flows, execution facts, evidence — and never
writes to it. There is no `fraud_graph`: fraud networks, device clusters, and
value flows remain canonical relationship/economic facts, and the FraudHypothesis
references them by id. Because the provider is fail-isolated and order-resilient,
it can land before sibling surfaces fully converge and lift automatically when
they do; because it depends on `risk360`, flipping `risk360` first is what makes
`fraud360`'s dependency state resolve.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). Because the convergence spans
program phases, the `implemented` flip additionally requires `risk360`
implemented, the consolidated `EpistemicStatus` vocabulary and typed
`GraphSnapshotRef` (phase 2), the synthesis contracts and pattern registry
(phase 3), and a live FraudHypothesis state machine + findings handoff
(phase 6).

## Test surface

* Contract tests — hypotheses carry state + claim state + confidence + matched
  patterns + materiality + evidence + contradictions; no-silent-escalation is
  enforced (`derived`/`inferred` never render as `confirmed`); `extra="forbid"`;
  no-redefinition of canonical primitives.
* Registry tests — zero-pending, DAG acyclic (fraud360 after risk360), bindings
  resolve, order-resilient.
* Provider tests — valid `ProjectionResult` with typed sections; missing-dep
  (`risk360`) honest degradation (never raises); tenant isolation; registration
  (success / duplicate / version-mismatch / unknown id).
* State-machine tests — full hypothesis lifecycle incl. `superseded`/`disputed`/
  `stale`/`corrected`; repro runs on `computation_runs`.
* Findings-handoff tests — hypothesis → material finding → `InvestigationCase` /
  OODA recommendation, only at the documented disposition points.
