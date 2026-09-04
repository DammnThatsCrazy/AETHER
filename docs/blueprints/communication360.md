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

> **Status (2026-09-03):** Phases 2–6 shipped on `feat/communication-360`;
> `communication360` is flipped in-lane to `implementationState: "implemented"` /
> `legacyBindings.migrationMode: "converged"` — `ownsCanonicalTruth` stays
> `false`, `graphMutationPolicy` stays `read_only`, the projection validator is
> zero-pending clean, the seven §71 fidelity metrics are absorbed into the
> metric registry, and the read-only `/v1/communication360` route surface is
> classified (`config/route_registry.yaml`) but not mounted in `main.py`
> (`AETHER_COMMUNICATION360_ENABLED`, default OFF). The canonical
> `make release-gate` runs post-merge (program decision #8); the authoritative
> per-phase record is the
> [program ledger](../plans/COMMUNICATION_360_PHASES.md).

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
routes — but when this program began, `communication360` was only a registered
`in_flight` row whose blueprint file did not exist, nothing stated what the
*Communication360 surface* was relative to canonical truth, and the blueprint's
central distinctions — **message is not information**,
**sender is not author/principal**, **delivery is not knowledge** — were
unexpressed in canonical objects. Without a declared authority boundary and an
explicit epistemic contract, comms analytics drift toward transcript dashboards
that re-answer questions the canonical planes already answer, and inferred "who
knew what" escapes the "inference is not fact" discipline. This slice lands
`communication360` as a first-class projection: a real provider implementing the
`IntelligenceProjectionProvider` protocol that reads the same canonical sources
the routes already read, plus the new information/knowledge contracts,
fail-isolated, tenant-scoped, and epistemically honest — shipped across program
phases 2–6 and flipped in-lane (status note above).

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

`metricRefs` names `email_open_rate`, `email_click_rate`, `email_reply_rate`
plus the seven §71 information-fidelity metrics the new information layer
supports (`claim_retention_rate`, `citation_retention_rate`,
`evidence_retention_rate`, `semantic_drift`, `omission_rate`,
`unsupported_addition_rate`, `contradiction_rate`) — each registered
field-for-field in `metric-registry.json` and the hand-authored
`shared/measurement/registry.py` mirror with a parity test (registry 20→27,
Phase 5). §71's `constraint_retention_rate` has no producer in the slice and is
deliberately not registered (program decision #7); the parity-test docstring
records the gap rather than stamping it. All `pendingReference` rows whose
`resolvesInProjection` is `communication360` cleared — the row is zero-pending.
Honestly-missing metrics stay `missing`, never `0`.

### Zero-pending declaration

With pending references cleared and no `pendingAuthority`, `communication360`
becomes a **zero-pending** row eligible for `implementationState: "implemented"`
and `legacyBindings.migrationMode: "converged"` once the orchestrator flips it.
`ownsCanonicalTruth` stays structurally `false`.

## Ratified canonical model (Phase 2)

Phase 2 establishes the single claim vocabulary and ratifies the canonical model
the Phase-3 contracts compile against. These decisions are recorded here and in
the program decision log.

- **R1 — one claim-state authority.** The consolidated `EpistemicStatus` (15
  values in `shared/contracts_models/epistemic.py`; TS twin
  `packages/shared/epistemic-status.ts`, parity-tested) is the single authority
  a claim may carry. `ClaimEnvelope` now has an optional typed
  `claimState: EpistemicStatus` — absent means *unclassified*, never factual.
  `shared/contracts_models/epistemic_communication.py` reconciles the comms
  vocabularies (`CommunicationState`, agent-observability `ActionStatus`) onto it
  with keys as literals and a parity test: a delivery/engagement/agent-action
  fact is at most `observed` and never escalates into
  `verified`/`resolved`/`causally_supported`.
- **R2 — message ≠ information.** The information layer is separate canonical
  objects — `Information`/`InformationRef` (an addressable unit of content),
  message-level `Claim` binding, `InformationTransfer`, `InformationTransformation`
  — not fields bolted onto `silver_comms_facts`. A delivered message is not
  collapsed into "the content was known".
- **R3 — sender ≠ author ≠ principal.** Roles render via a temporal-validity role
  matrix (role, participant, `valid_from`/`valid_to`) over
  actor/author/generator/editor/approver/sender/presented_sender/principal/
  delegator/beneficiary/accountable_party, reusing `services/identity`
  `EntityType` and `services/delegation` grant semantics — never a single
  `from` attribute.
- **R4 — delivery ≠ knowledge.** Two typed state families with no cross-ladder
  inference: message lifecycle/delivery (`CommunicationState` ladder) versus
  knowledge/interpretation state (`ingested`/`parsed`/`included_in_context`/
  `used`, from agent observability). A recipient-knowledge or author-intent claim
  is a structurally different object backed by its own observation — never
  granted by a delivery/action state.
- **R5 — authority verdict (decision-log #2 resolved/ratified).** The
  information-layer facts land under the **existing `communication_facts` read
  authority** — no new `AUTHORITY_INDEX` authority was added. The Phase-3
  migration registers the `communication360_facts` store as an instance of that
  authority, and the row's five `canonicalAuthorities`
  (`communication_facts`/`campaign_touchpoints`/`entities`/`outcomes`/`evidence`)
  all resolve in the platform `AUTHORITY_INDEX` (validator-clean); `SPINE_INDEX`
  is unchanged (spine-plane rows only). `ownsCanonicalTruth` stays `false`.

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
program phases, the `implemented` flip required the canonical
communication modeling and vocabulary (phase 2), the domain contracts and metric
absorption (phase 3), a real provider + read surface (phase 4; an exploration
adapter was deliberately not added — the row's `surfaceIds`
`timeline`/`profile360` already exist and a bespoke surface would contradict the
registry), the information-fidelity/knowledge/authority path (phase 5), and
resolution + downstream read surface (phase 6). All six landed in-lane on
2026-09-03 (see the status note and program ledger); the canonical
`make release-gate` runs post-merge (program decision #8).

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
* Fidelity/authority tests — claim/citation/evidence retention, semantic drift,
  omission/contradiction and unsupported-addition rates over an
  `InformationTransformation` lineage; delegation-outcome → authority-state
  evaluation per agent-mediated communication (never a silent grant);
  determinism + run reproducibility on `computation_runs`.
