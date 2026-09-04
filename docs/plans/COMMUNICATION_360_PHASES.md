---
title: Communication360 — Day-1 Convergence Program
slug: plans/communication-360-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Communication360 — Day-1 Convergence Program

This is the implementation program for **Communication360**, Aether's
communication and information-flow intelligence projection over the Unified
Intelligence Graph. The governing specification is the **"Aether Communication360
— Day-1 Production Implementation Blueprint"**, captured in full as
[docs/source-of-truth/COMMUNICATION_360.md](../source-of-truth/COMMUNICATION_360.md);
this document records the gap between the repository and that blueprint, orders
the work into phases, and is the ledger for what has shipped. The per-projection
vertical-slice design is
[docs/blueprints/communication360.md](../blueprints/communication360.md).

**The program's central finding: Communication360 is not greenfield.** The
`communication360` projection is already registered in the canonical
intelligence-projection registry as `in_flight` (`migrationMode: adapter`,
`graphMutationPolicy: read_only`, `ownsCanonicalTruth: false`,
`projectionKind: sequence_360`) whose `legacyBindings` point at fully built,
end-to-end-wired subsystems — the provider-neutral `services/comms` pipeline
(connector → `CommunicationEventPayload` → silver dispatcher →
`silver_comms_facts` → campaign resolver → measurement → attribution → graph
projection → state), the `services/agent_comm_observability` agent-mail
observability layer, the observation-only `services/agentic_observability`
harness envelope, the campaign service, and a mature connector catalog. The work
is therefore **convergence**: make the declared projection real by (1) authoring
the missing blueprint/source-of-truth documents, (2) reconciling the blueprint's
communication vocabulary onto the real architecture — *message is not
information*, *sender is not author/principal*, *delivery is not knowledge* are
the genuinely new canonical modeling obligations, not just prose — (3) defining
the small set of genuinely new canonical comms contracts (an information layer,
a canonical conversation/thread/matter layer, communication acts / requests /
commitments / response expectations, and knowledge-state/interpretation/
context-inclusion records), and (4) registering a native projection provider and
exploration adapter that read the shipped silver path and the new canonical
facts — then converging the projection's surfaces on top.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document. The projection vocabulary
(`in_flight` → `implemented`, `migrationMode`, vertical-slice DoD) is defined in
[docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md](../source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md)
and
[INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md).

**Program base.** `feat/communication-360` tracks
[`feat/aether-360-program`](../../../feat/aether-360-program) — the branch
carrying the implemented 360 plane this program converges Communication360 onto:
the converged `economic360`/`outcome360`/`infrastructure360` providers, the lens
registry, the exploration→projection adapters, and the `docs/blueprints/`
directory — at base commit `fced2960` (the shared root of the sibling
`feat/risk-fraud-360`, `feat/context-intelligence-360`, `feat/agentic-360`, and
`feat/spine-p0-foundation` lanes). That lineage is intentionally **not** based on
`origin/main`, which does not yet contain the implemented 360 plane (the
360-program work is merged to `origin/main` separately). Reconcile with
`origin/main` when that lineage lands.

## 0. How this program reads the blueprint

The blueprint speaks in vocabulary the repository does not share. This program
maps blueprint intent onto the real architecture and does not force the
blueprint's nouns onto the codebase:

| Blueprint language | Repository reality |
| --- | --- |
| "The full Day-1 chain (SOURCE → OBSERVATION → … → REPLAY → RELEASE PROOF, §2)" | The **Intelligence Projection Plane** (ADR-010) converging the registered `in_flight` row over the shipped comms evidence path (`silver_comms_facts`, campaign touchpoints, evidence, entities). Each "plane" in the blueprint is a shared plane of the repo (contract spine, evidence/provenance, temporal kernel, identity, relationship/graph, exploration fabric, Kyber/Noesis) — not a new stack |
| "Contract Spine integration (§29): 24 required communication contract modules" | Declarative registries in `packages/shared/contracts/*.json` → generated Python/TS twins via `scripts/generate_platform_contracts.py`. Many of the blueprint's objects already exist in shipped form (`services/comms`, `services/delegation`, `services/identity`, agentic observability, OI `EvidenceRef`/projection `ClaimEnvelope`); a smaller set is genuinely new and must be registered without re-declaring canonical primitives |
| "Message is not information; Information ≠ Claim ≠ Evidence (§4.1, §5.1)" | **Genuinely new.** No canonical `Information`/`InformationRef`/message-bound `Claim`/`InformationTransformation` objects exist; nearest assets are the comms contract taxonomy, `silver_comms_facts`, OI `EvidenceRef`, and projection `ClaimEnvelope`. This is the blueprint's central modeling obligation and the largest single gap |
| "Sender is not author; principal/delegation (§4.2, §51–52)" | Partial. `services/comms` carries `ActorKind`/`Direction`/roles; `services/identity` (`EntityType`) and `services/delegation` (`DelegationGrant`) ship; but there is no temporally-valid full role matrix (author/generator/editor/approver/sender/presented_sender/principal/delegator/beneficiary/accountable_party) over a single canonical communication |
| "Delivery is not knowledge (§4.3, §25–27)" | **Genuinely new.** No canonical `KnowledgeState`/`Interpretation`/`ContextInclusion`; nearest assets are the `ContextCapsule`, `continuation` records, and agent session context. Agent-side "was it actually in context" is not yet a first-class observed fact |
| "InformationTransfer is the parent abstraction (§5.3, §6)" | No `InformationTransfer` object; today agent-runtime transfers are approximated by agentic `agent.*` events and `services/agent_comm_observability` records, never as a single transfer taxonomy |
| "Registry additions: `SENT`/`RECEIVED`/`CONTAINS` edges (§30, §61–63)" | The repo does not use bare `SENT`/`RECEIVED`/`CONTAINS` `EdgeType`s: delivery/consumption are lifecycle **states** (`CommunicationState`) and graph edges are domain-specific (`THREAD_CONTAINS_MESSAGE`, `MESSAGE_HAS_ATTACHMENT`, `COMMUNICATES_WITH`, `CONTACTED`, `DELEGATED_TO`, `ACTED_FOR`, `SUPPORTED_BY`, `DERIVED_FROM`). Where the blueprint implies a real missing edge, add a domain `EdgeType` **and** its mandatory `relationship_layers._EDGE_LAYER_MAP` entry; do not force the blueprint's bare nouns |
| "Harness hooks + event taxonomy (§37–38)" | The dotted event taxonomy maps onto the repo's `family` + snake_case `type` model in `packages/shared/contracts/event-registry.json` (`comms`, `agent`, `journey`, … families) and the observation-only SDK envelope (`execution_by_aether` is always `false`). Harness observability hooks largely exist across `services/agentic_observability` + `services/agent_comm_observability`; mapping, not building, is the work |
| "Communication providers (§34–35)" | Connector adapters ship for Klaviyo, Mailchimp, SendGrid, Customer.io, Postmark, Iterable, Braze (plus HubSpot/Salesforce/Intercom/Zendesk/Slack elsewhere). **Gmail/Outlook and other instrumentable agent runtimes are net-new.** Capability truth-telling is partial: adapters declare `manifest_data_outputs`; a per-communication capability object (supported/partial/permission-dependent) does not exist |
| "Communication360 owns canonical communication representation (§3)" | The registered row is a **read-only adapter projection** (`ownsCanonicalTruth: false`, `canonicalAuthorities: [communication_facts, campaign_touchpoints, entities, outcomes, evidence]`). The genuinely new canonical comms objects therefore land as canonical contracts **consumed by** the projection, and Communication360's graph posture stays `read_only` — it becomes a projection over a richer canonical spine, not a second system of record |

## 1. Gap analysis

"Repository state" below reflects the audit that produced this program
(2026-09-03). Status legend: **FULL** = contract + code wired end-to-end;
**PARTIAL** = code/spec exists but incomplete or flag-gated OFF;
**SPEC-ONLY** = registry/doc row with no implementation or dangling reference.

| Area | Repository state before this program | Gap to the blueprint |
| --- | --- | --- |
| Projection registration | `communication360` registry row exists (`in_flight`, `adapter`, `read_only`, `sequence_360`; `subjectKinds: [campaign, episode, source]`; `surfaceIds: [timeline, profile360]`; `capabilityKeys: communication360.read/.explore`; deps profile360/relationship360/episode360/outcome360) | **No native provider, no exploration adapter, no per-projection surface-capability row** — not a real exploration surface yet; `docs/blueprints/communication360.md` is a dangling reference (only `economic360.md`, `outcome360.md`, `infrastructure360.md` exist) |
| Blueprint / DoD docs | `services/comms` + ADR-C1…C11 architecture docs live under `docs/comms/`; no Communication360 program doc exists | **No architecture SoT reconciling the master blueprint to ADR-010 + registries; no vertical-slice blueprint.** This program's Phase 1 lands both |
| Message ≠ Information (§4.1, §5.1, §13–15) | Nearest assets: comms `CommunicationEventPayload` taxonomy, `silver_comms_facts`, OI `EvidenceRef`, projection `ClaimEnvelope`, `ExtractedEntityObservedRecord` types; **no canonical Information/InformationRef/InformationTransformation or message→information→claim binding** | **The full information/claim layer is new** — independently addressable semantic content, transformation lineage, and message-level claim bindings that survive transport (email → subagent → summary → outbound → decision) |
| Actor ≠ author ≠ principal (§4.2, §51–52) | `ActorKind`/`Direction`/`JourneyRole` on comms events; identity `EntityType` (human/organization/agent/account/…); `services/delegation` `DelegationGrant` (scoped/time-bound/revocable); graph edges `ACTED_FOR`, `DELEGATED_TO`, `GRANTED_BY/TO` | **No canonical communication participant role matrix with temporal validity** over a single message (actor/author/editor/approver/sender/presented_sender/principal/delegator/beneficiary/accountable_party); AI-mailbox sender≠author semantics are not expressible per communication today |
| Delivery ≠ knowledge (§4.3, §25–28) | `ContextCapsule`, `continuation`, agent session context, `CommunicationState`; **no `KnowledgeState`/`Interpretation`/`ContextInclusion` object** | Knowledge/interpretation state, and explicit agent context-inclusion records ("was the constraint actually in context"), are new |
| InformationTransfer + harness observability (§5.3, §6, §37–38) | Agentic observability envelope + event families (`agent`/`comms`), `services/agent_comm_observability` (message/thread/inbox/attachment/extraction records), `agent.*` lifecycle/delegation/tool events — observation-only, `execution_by_aether` false | **No unified `InformationTransfer` parent abstraction** (message/context/shared-state/artifact/memory/tool-result/structured/event-signal); shared-state ↔ read and memory boundary (stored-as-memory / retrieved-into-context) are unmodeled as transfers |
| Canonical object model (§6–28) | Shipped: `services/delegation` (Delegation), `services/campaign` (campaign truth), comms taxonomy; Noesis has an agent-layer `conversation`; **no canonical `Conversation`/`ProviderThread`/`Matter`, `CommunicationMessage`/Payload/Segment/Artifact/Batch/Delivery, `CommunicationAct`, `Request`, `Commitment`, `ResponseExpectation`** | The canonical comms object model is largely new and must be built against the shipped silver path (dedup/idempotency/replay already in the comms ingest: `sync_runs`, coalescer) — no metric inflation, no parallel evidence system |
| Provider adapters + capability (§34–36) | Connectors: Klaviyo, Mailchimp, SendGrid, Customer.io, Postmark, Iterable, Braze (comms), plus the generic `BaseConnector`/`NormalizedEvent` framework; `manifest_data_outputs` auto-derives provider manifests | **Gmail/Outlook adapters absent**; no per-communication **capability object** (supported/unsupported/partial/permission-dependent/…) that flows downstream with each observation; "provider limitation is not zero" is enforced in code only where states exist |
| Evidence / dedup / replay (§39–46) | **FULL** — comms connector → bronze → `services/comms` normalization → silver `silver_comms_facts` → gold graph projection; idempotent ingest, `sync_runs`, rebuild coalescer; raw content separated from canonical facts | The canonical-message → multiple-observation dedup ("Gmail webhook + sync + harness evidence → one message") must extend to the new information/transfer layer; nothing new to build for the base pipeline |
| Participant/thread/conversation/matter resolution (§47–60) | Identity `EntityType` + agent mailbox/thread/message observation vertices (`AGENT_INBOX_OBSERVED`, `AGENT_THREAD_OBSERVED`, `AGENT_MESSAGE_OBSERVED`), `THREAD_CONTAINS_MESSAGE` edges; campaign → recipient resolution exists | **Conversation/Matter resolution is new** (provider threads must not auto-equal canonical conversations; Matter binds email+Slack+agent+campaign continuity); causal ordering (`responds_to`/`supersedes`) must not be inferred from timestamps alone |
| Temporal (§53–56) | Temporal kernel (`TemporalEnvelope`, KNOWN_THEN/KNOWN_NOW), bitemporal time machine, causal/logical ordering seams exist | Historical reconstruction of agent knowledge/authority/version is a projection consumer of the kernel; needs `knowledge_state valid_from/to` wiring, not new temporal infra |
| Graph edges (§30, §61–64) | `EdgeType` + enforced `_EDGE_LAYER_MAP`: `COMMUNICATES_WITH`, `CONTACTED`, `THREAD_CONTAINS_MESSAGE`, `MESSAGE_HAS_ATTACHMENT`, `ACTED_FOR`, `DELEGATED_TO`, `SUPPORTED_BY`, `DERIVED_FROM` present | A small set of **new domain edges** for the new object families (e.g. communication→conversation→matter→episode, information→claim→evidence, delegation-scope, context-inclusion) — each with layer classification; bare `SENT`/`RECEIVED`/`CONTAINS` not added |
| Intelligence + measurement (§65–76) | Metric registry exists; the `communication360` row's `metricRefs` name `email_open_rate`/`email_click_rate`/`email_reply_rate`; comms engagement/volume analytics live in measurement/silver adapters | Communication **findings** (agent fidelity, constraint loss, authority scope, coordination latency) and information-quality metrics (claim/constraint retention, semantic drift, contradiction rate) are new producers over the new information layer |
| Surfaces + downstream (§77–99) | Profile360 comms + campaign messages routes exist as adapter surfaces; `/v1/explore` fabric + `communications_insight` Noesis intent exist; Outcome360/relationship360/episode360/agent360 on this lineage are `in_flight` siblings | A real `communication360` projection adapter + Noesis comms intents + Kyber operator surface are new; sibling-360 integration degrades honestly until those slices land |
| Security / consent / retention (§110–123) | Shared security architecture, consent registry, retention policy, content classification seams exist; comms events already carry governance/timing/evidence fields | Communication360 **feeds** these planes (authority-scope findings, secret/PII leakage evidence, historical consent evaluation); it does not build new consent/policy/evidence systems |

## 2. Phase map

Phases are ordered so vocabulary and canonical modeling land before any provider
is registered, and the information/claim layer lands before resolution,
fidelity, or surfacing. Status in the table below is current as of the latest
ledger row; the ledger in §4 is the authoritative per-phase record as each phase
lands. Each phase ships with its new behavior flag-gated **default OFF** until
operationally validated, matching the platform convention. Phases 2–6 below are a
working sketch: each is refined into an approved brief immediately before it is
executed, as the Risk/Fraud sibling did. The master blueprint orders Day-1
delivery as four coordinated PR trains (SoT §172–176: PR1 canonical contracts +
governance, PR2 capture/evidence/resolution/temporal/graph, PR3 intelligence +
metrics + exploration + surfaces, PR4 production hardening + release proof); the
phases below execute that ordering in repo cadence, and a per-brief re-cut may
align a phase more closely to a PR boundary (e.g. conversation/matter resolution
may be pulled forward into the Phase-4 brief).

| Phase | What ships | Entry criteria | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| **1** — Blueprints + source of truth | `docs/plans/COMMUNICATION_360_PHASES.md` (this plan), `docs/source-of-truth/COMMUNICATION_360.md` (the full Day-1 blueprint captured as SoT, with a reconciliation header), and `docs/blueprints/communication360.md` (vertical-slice blueprint over the real seams: registry row, silver path, migration plan) | Master blueprint reviewed; audit (§1) accepted; program scope approved | Registry blueprint ref for `communication360` resolves to a real file; docs consistent; no behavior change | PLANNED — this milestone |
| **2** — Communication vocabulary + canonical modeling | One epistemic/claim vocabulary for communication onto the shared `EpistemicStatus`/claim lineage so a derived/inferred "constraint dropped" or "agent sent" observation can never render as a factual claim; canonical modeling decisions for the **information layer** (`InformationRef`/`Information`, `InformationTransfer`, message-level `Claim` binding, `InformationTransformation`) and the role matrix (participant/principal/delegation roles with temporal validity); convergence debt (any duplicate primitive deletes) | Phase 1 landed; modeling decisions recorded | Vocabulary single-sourced with parity tests; canonical information/role model ratified against the shipped silver path; `make ci-check` green | SHIPPED — 2026-09-03 |
| **3** — Canonical comms contracts + storage + registries | Domain contract modules (e.g. `services/communication360/`): `InformationTransfer` + transfer sub-kinds; canonical `CommunicationMessage`/`CommunicationPayload`/`Segment` over the silver path; `Conversation`/`ProviderThread`/`Matter`; `CommunicationAct`/`Request`/`Commitment`/`ResponseExpectation`; `KnowledgeState`/`Interpretation`/`ContextInclusion`; participant/principal bindings referencing `services/identity` + `services/delegation` — never re-declared primitives. Storage via tenant-scoped JSONB repos (or Alembic) + run references onto `computation_runs`; dimension/registry seeds; `AETHER_COMMUNICATION360_ENABLED` flag (default OFF) | Phase 2 landed; reuse inventory accepted | Contracts import zero duplicate primitives; storage tenant-scoped; every new `EdgeType` has a layer entry; registries seeded with alignment tests; `make docs-check` green (projection still `in_flight`) | PLANNED |
| **4** — Provider + projection convergence (core wiring) | `Communication360Provider` implementing `IntelligenceProjectionProvider` (`projection_id: communication360`, `sequence_360`), reading the shipped comms silver path + the new canonical facts; per-projection `surface-capability` row; exploration adapter so `/v1/explore` with the comms lens returns real projections; `read_only` graph posture enforced; metric absorption of the row's `metricRefs`; registration seam; honest degradation while sibling projections (profile360/relationship360/episode360/outcome360) are still `in_flight` | Phase 3 landed; contracts stable | Enabled flag-on: provider + adapter tests green; projection returns valid sections with dependency degradation (never crashes, never fabricates); `make ci-check` green | PLANNED |
| **5** — Information fidelity + knowledge/interpretation + authority | Information/claim extraction + transformation tracking (retention, semantic drift, omission/contradiction rates); `KnowledgeState`/`Interpretation`/`ContextInclusion` ingestion from agentic observability events; delegation-scope evaluation (`authorization_state`) reusing `services/delegation`; findings-candidate materiality over the fidelity metrics | Phase 4 landed | Fidelity pipeline over real agent-communication events with reproducible-run tests; authority scope evaluated per agent-mediated communication; findings path materiality-tested | PLANNED |
| **6** — Resolution + downstream + surfaces + flip | Conversation/thread/matter/episode resolution combining provider threads + identity + reply lineage + campaign/episode links (causal order never inferred from timestamps alone); Noesis read-only comms intents; Kyber operator surface; profile360/agent360/relationship360/campaign360/episode360 integration on this lineage with honest degradation; vertical-slice flip to `implementationState: implemented` + `migrationMode: converged`; regenerate + final release evidence | Phases 4–5 green | `communication360` `implemented`/`converged`; vertical-slice checklist satisfied; `make ci-check` + `make release-gate` green | PLANNED |

### Implementation priority

- **Blueprints + SoT (Phase 1) first.** The DoD documents pin every later phase
  to the real seams; the SoT is also the only place the master blueprint is
  reconciled instead of silently dropped.
- **Vocabulary + canonical modeling (Phase 2) before contracts (Phase 3).**
  Message≠information and delivery≠knowledge are modeling decisions; contracts
  compile against them.
- **Contracts (Phase 3) before providers (Phase 4).** A provider cannot be
  written against a moving contract surface.
- **Provider (Phase 4) before fidelity + knowledge (Phase 5).** Fidelity output
  needs an exploration seam to be observed.
- **Resolution + downstream + flip (Phase 6) last.** Findings/Noesis/Kyber and
  the sibling-360 integrations consume a stable provider; the
  `in_flight` → `implemented` flip is the definition of done and lands only after
  every dependency is settled and CI-guarded.

### Reuse inventory (contracts may reference, never re-declare)

Canonical `EntityRef`/`EvidenceRef`/`InvestigationCase` (OI models),
`TemporalEnvelope` + bitemporal kernel + `KNOWN_THEN`/`KNOWN_NOW`,
`EpistemicStatus`/claim vocabulary (`shared/contracts_models/epistemic.py` —
**not** present on base `fced2960`; adopted byte-identical onto this lane in
Phase 2 from the Risk/Fraud sibling's consolidation so all 360 lanes share one
authority),
`MeasurementResult`/`CanonicalResult` + metric registry + `ValueState`, model
registry, `new_run_id()` + `computation_runs` + `context_hash`,
`GraphMutationGateway` (read-only for communication360), `GraphClient`/traversal,
identity resolution (`services/identity`), `services/delegation`
(`DelegationGrant`, scoped/time-bound/revocable), the comms silver path
(`services/comms` → `silver_comms_facts`, campaign resolver, measurement silver
adapters, `attribution_policy`, `graph_projection`, `state`), connector catalog +
`NormalizedEvent`, agentic observability envelope + event families,
`ContextCapsule`, `/v1/explore` fabric (`ExplorationContextV1`, applicability),
Noesis intents, Kyber operator conventions.

## 4. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-03 | kickoff | Program plan authored on `feat/communication-360`; branch rooted at `fced2960` (the implemented-360-plane lineage, shared with the Risk/Fraud + context-intelligence siblings) after confirming `origin/main` lacks the 360 foundation; audit (§1) maps the master blueprint to repository reality; `communication360` confirmed as an `in_flight` convergence target over the shipped comms substrate, not greenfield; phases not yet started |
| 2026-09-03 | 1 | SHIPPED — `docs/plans/COMMUNICATION_360_PHASES.md`, `docs/source-of-truth/COMMUNICATION_360.md` (full Day-1 blueprint as SoT), and `docs/blueprints/communication360.md` authored; registry blueprint ref for `communication360` resolves to a real file; docs manifest + REPO-INDEX synced; `make docs-check` green (46/0) and `make ci-check` green (63/0, `ANTHROPIC_*` env stripped); no behavior change — registry row stays `in_flight` |
| 2026-09-03 | 2 | SHIPPED — vocabulary + canonical modeling. Audit found **no `EpistemicStatus` on base `fced2960`** (Phase-1 reuse-inventory claim corrected); adopted the Risk/Fraud consolidated `EpistemicStatus` (15 values) **byte-identical** onto this lane (`shared/contracts_models/epistemic.py` + `packages/shared/epistemic-status.ts` + `packages/shared/index.ts` barrel + `tests/contracts/test_epistemic_status_parity.py`, 7/7 green) so all 360 lanes share one authority; added `shared/contracts_models/epistemic_communication.py` mapping `CommunicationState` (15) + `ActionStatus` (5) onto it — keys as literals, service-free module — with `tests/contracts/test_epistemic_communication_parity.py` (6/6: totality + no-escalation band invariants); `ClaimEnvelope` gained optional typed `claimState: EpistemicStatus` in PY + TS twins (round-trip test, projection-contract tests 34/0); ratified canonical model R1–R5 recorded in `docs/blueprints/communication360.md` and decision-log #1/#2 marked RESOLVED; convergence-debt audit found no in-remit duplicate primitive to delete (cross-lane entity-kind vocabularies are outside this slice); registry row stays `in_flight` |

When a phase lands, its row is updated here; the phase map in §2 carries the
current status. As of this row Phases 1–2 have shipped; Phases 3–6 are planned.

## 5. Decision log and deferred scope

### Decisions to record early

1. **Communication vocabulary: one epistemic authority, not per-surface
   translation.** Communication findings ("constraint dropped", "agent acted for
   X", "recipient did not receive") must carry the shared `EpistemicStatus`
   vocabulary so a derived/inferred condition can never render as a factual
   claim. Confirm the mapping onto the shipped silver path in Phase 2.
   **RESOLVED (Phase 2, 2026-09-03):** `EpistemicStatus` (15 values) was not on
   base `fced2960`; it is adopted byte-identical from the Risk/Fraud sibling and
   `ClaimEnvelope` now carries an optional typed `claimState: EpistemicStatus`.
   `shared/contracts_models/epistemic_communication.py` maps `CommunicationState`
   + agent-observability `ActionStatus` onto it (keys as literals, totality +
   no-escalation parity tests). A message/agent fact is capped at `observed`.
2. **Information layer home.** The new `Information`/`InformationRef`/
   `InformationTransfer`/`Claim`-binding contracts are canonical spine objects
   consumed by the read-only projection (`ownsCanonicalTruth` stays `false` on
   the row) — they are not owned by the projection itself. Whether they register
   as a new canonical authority (extending `AUTHORITY_INDEX`) or fold under an
   existing one is decided in Phase 2.
   **RESOLVED (Phase 2, 2026-09-03, R5):** the information-layer facts land under
   a **new canonical authority** — provisional, ratified at the Phase-3
   registration review. The `communication360` row's `canonicalAuthorities` stay
   read authorities.
3. **Edges.** Add domain `EdgeType`s only where a real graph gap exists, each
   with its mandatory `relationship_layers` entry; do not add bare
   `SENT`/`RECEIVED`/`CONTAINS` members (lifecycle states + domain edges carry
   those semantics today).
4. **Events.** Map blueprint events onto the repo's `family`+`type`
   `event-registry.json` model rather than inventing a dotted taxonomy.
5. **Runs/replay.** Reuse `computation_runs` + `context_hash` and the comms
   ingest idempotency/replay seams; do not add parallel run or sync tables.
6. **Capability.** Provider capability truth-telling extends the connector
   manifest seam to per-communication capability states; "unavailable" is never
   rendered as zero message counts.

### Deferred / not owned by this program

- **Full Gmail/Outlook + instrumentable agent-runtime connectors** — Day-2/3; the
  universal connector + capability contracts land first.
- **Complete sibling-360 materialization** (profile360/agent360/relationship360/
  campaign360/episode360/outcome360) — owned by those projections; Communication360
  consumes the real seams and degrades honestly until they land.
- **Economic360-style communication cost/valuation rollups** — the blueprint's
  communication economic metrics are measurements fed to Economic360's broader
  valuation; not a new economic model.
- **Privacy/consent infrastructure, retention enforcement, and the security
  response engine** — shared planes; Communication360 supplies evidence and
  records needs, it does not build them.
