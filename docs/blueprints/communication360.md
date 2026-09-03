---
title: "Communication360 Vertical Slice Blueprint"
slug: blueprints/communication360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Communication360 — Intelligence-Projection Blueprint

**Registry id:** `communication360`
**Projection kind:** `sequence_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`communication360` to `implementationState: "implemented"`. Executed as program
phases 2–6 of
[docs/plans/COMMUNICATION_360_PHASES.md](../plans/COMMUNICATION_360_PHASES.md),
then flipped in the phase-6 gate. The governing specification is the full Day-1
blueprint captured in
[docs/source-of-truth/COMMUNICATION_360.md](../source-of-truth/COMMUNICATION_360.md).

---

## What it is

Communication360 is Aether's **communication and information-flow projection** —
a `sequence_360` over canonical communication truth for subjects of kind
`campaign`, `episode`, or `source`. It answers "what information existed, who or
what communicated it, through which mechanism, to whom, while acting for whom,
under what authority, how it changed in transit, what the recipient knew, what
action followed, and what outcome was affected" by **reading** the canonical
communication authorities — the `services/comms` silver path (`silver_comms_facts`
/ `campaign_touchpoints`), agent communication observability, identity and
delegation (`services/identity`, `services/delegation`), evidence, and the
information layer this program adds — and projecting a typed,
evidence-grounded, tenant-scoped `sequence` result through the Intelligence
Projection Plane's shared contracts (`ProjectionRequest` → `ProjectionResult`).

It is NOT an email dashboard, a Mailchimp/Klaviyo wrapper, a transcript store, a
second attribution engine, or a second system of record (ADR-010,
`ownsCanonicalTruth: false`). It never writes: `graphMutationPolicy: read_only`;
there is no write path at all. It is the communication and information-flow
projection of the Unified Intelligence Graph.

## Why

The backend already ships a complete, end-to-end comms substrate (`services/comms`
connector → silver dispatcher → `silver_comms_facts` → campaign resolver →
measurement → attribution → graph projection → state) with agent-side
observation layers (`services/agent_comm_observability`,
`services/agentic_observability`) and adapter surfaces on profile360 and campaign
routes — but `communication360` is only a registered `in_flight` row whose
blueprint file does not exist. Nothing states what the *Communication360 surface*
is relative to canonical truth, and the blueprint's central distinctions —
**message is not information**, **sender is not author/principal**, **delivery is
not knowledge** — are unexpressed in canonical objects. Without a declared
authority boundary and an explicit epistemic contract, comms analytics drift
toward transcript dashboards that re-answer questions the canonical planes
already answer, and inferred "who knew what" escapes the "inference is not fact"
discipline. This slice lands `communication360` as a first-class projection: a
real provider implementing the `IntelligenceProjectionProvider` protocol that
reads the same canonical sources the routes already read, plus the new
information/knowledge contracts, fail-isolated, tenant-scoped, and
epistemically honest.

## How it works

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | communication state for the subject: direction mix (H2H/H2A/A2H/A2A), active conversations, agent mediation, open requests/commitments, quality — assembled through the comms silver path + the new canonical conversation/request/commitment contracts |
| `state` | typed `SectionState` per communication dimension — `available`/`missing`/`degraded`/`unknown`/`not_applicable`; provider capability states carried downstream (a provider limitation is `unavailable`, never a fabricated zero message count) |
| `timeline` | the ordered communication sequence for the subject — messages/transfers/acts with real event times; causal relations (`responds_to`, `supersedes`) come from declared lineage, never inferred from timestamps alone |
| `evidence` | the reused `EvidenceRef`s grounding every claim in the sequence |
| `interactions` | participant/actor/principal roles, delegations, requests/commitments/response expectations, and knowledge/interpretation state bound to each interaction |
| `outcomes` | communication-linked outcomes via the canonical outcome relationships — never a redefinition of Outcome |

Every read is defensive: an unavailable backing source degrades its section
(typed `degraded`/`missing`/`empty`), never crashes, never fabricates, and never
leaks exception detail. `requiresDimensionState`, `requiresFreshness`, and
`requiresLimitations` are honored — a Communication360 result without dimension
state, freshness, and limitations is incomplete.

### Epistemic honesty (message ≠ information; inference ≠ fact)

- Every claim in the result carries a claim state from the consolidated
  `EpistemicStatus` vocabulary, a confidence, and reused `EvidenceRef`s. An
  ungrounded claim is a typed `missing`/`degraded` state, never a silent
  assertion (vertical-slice checklist §7).
- **Message ≠ information:** the projection reads messages and the separately
  addressable information/claim layer; it never collapses "the email was
  delivered" into "the recipient knew the content", nor "an agent sent X" into
  "the human wrote X".
- **Sender ≠ author ≠ principal:** roles (actor/author/generator/editor/
  approver/sender/presented_sender/principal/delegator/beneficiary/
  accountable_party) render distinctly and temporally; Profile360 never reports
  "Alice wrote this" without evidence.
- **Delivery ≠ knowledge:** `sent/delivered/opened/read` and agent-side
  `ingested/parsed/included_in_context/used` are distinct typed states;
  knowledge/interpretation state is only ever as strong as the observation that
  supports it.
- There is **no unexplained traffic-light badge**: summary state is derived from
  typed section states and never implies factual certainty about what someone
  knew or intended.

### Dependency story (profile360 / relationship360 / episode360 / outcome360)

`communication360` declares `projectionDependencies: [profile360, relationship360,
episode360, outcome360]`, all `in_flight` siblings on this lineage. While they are
unconverged the provider **degrades honestly** instead of failing — e.g. episode
binding and outcome links degrade with a typed reason until those slices land,
while the shipped comms silver path lifts immediately. The projection still
returns a valid `ProjectionResult` with `dependencyState` echoed verbatim from
the registry. When siblings land, the provider's sections lift to `available`
with zero code change.

### No redefinition

The slice reuses the canonical `EntityRef`, `RelationshipRef`, `EvidenceRef`,
`PageRequest`, `TimeRangeFilter`, and `FilterExpression` primitives, the identity
and delegation services, and the comms silver path — the communication package
declares NO second copy (parity-tested). The genuinely new canonical contracts
(information layer, conversation/thread/matter, acts/requests/commitments/
response expectations, knowledge state/context inclusion) reference canonical
primitives only.

### Metric absorption

`metricRefs` already names `email_open_rate`, `email_click_rate`,
`email_reply_rate`. Before the flip the communication metric set is absorbed
into `metric-registry.json` (and the hand-authored
`shared/measurement/registry.py` mirror) field-for-field — including the
information-fidelity metrics the new information layer supports — clearing any
`pendingReference` rows whose `resolvesInProjection` is `communication360`, and
the provider surfaces them in `summary` metrics. Honestly-missing metrics stay
`missing`, never `0`.

### Zero-pending declaration

With pending references cleared and no `pendingAuthority`, `communication360`
becomes a **zero-pending** row eligible for `implementationState: "implemented"`
and `legacyBindings.migrationMode: "converged"` once the orchestrator flips it.
`ownsCanonicalTruth` stays structurally `false`.

## What it means for the graph

Communication360 projects *over* the graph's communication truth — the comms
silver facts, campaign touchpoints, agent communication observations, identity
and delegation edges, evidence — and never writes to it. The graph remains the
single system of record; the projection is a read-only `sequence` lens that can
be run, degraded, or rebuilt without touching canonical state. Because the
provider is fail-isolated and order-resilient, it can land before or after the
profile360/relationship360/episode360/outcome360 siblings without corrupting
them, and it lifts to full `available` automatically when those sibling
projections land.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). Because the convergence spans
program phases, the `implemented` flip additionally requires the canonical
communication modeling and vocabulary (phase 2), the domain contracts and metric
absorption (phase 3), a real provider + exploration adapter (phase 4), the
information-fidelity/knowledge/authority path (phase 5), and resolution +
downstream surfaces (phase 6).

## Test surface

* Contract tests — canonical comms/information/transfer contracts carry claim
  state + confidence + evidence; no-redefinition of canonical primitives;
  `extra="forbid"`; a missing dimension/transfer is never zeroed or invented.
* Registry tests — zero-pending, DAG acyclic, bindings resolve, order-resilient.
* Provider tests — valid `ProjectionResult` with the six typed sections and
  evidence-grounded claims; missing-dep honest degradation (never raises);
  content-free degradation; tenant isolation; registration (success / duplicate
  / version-mismatch / unknown id).
* Epistemic tests — a delivered message can never render as recipient knowledge;
  a sender can never render as the author without evidence; no unexplained
  traffic-light rendering.
* Fidelity/authority tests — constraint/claim retention and semantic drift over
  agent communications; delegation `authorization_state` per agent-mediated
  communication; determinism + run reproducibility on `computation_runs`.
