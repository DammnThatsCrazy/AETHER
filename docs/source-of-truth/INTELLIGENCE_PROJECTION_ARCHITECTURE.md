---
title: Intelligence Projection Architecture
slug: source-of-truth/intelligence-projection-architecture
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/intelligence-projection-registry.json
  - scripts/lib/intelligence_projection_validation.py
  - scripts/validate_intelligence_projections.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/__init__.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/contracts.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/errors.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/provider.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/readiness.py
  - Backend Architecture/aether-backend/shared/intelligence_projections/registry.py
last_synced_commit: "99736fed"
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
---

# Intelligence Projection Architecture

A **360** is an **intelligence projection over canonical Aether truth**. It is
**not a competing system of record**. The authoritative decision record is
`docs/decisions/ADR-010-intelligence-projection-plane.md`; this document is
the enforceable source of truth for the plane's contracts, inventory,
migration rules, and anti-patterns. When this document and the registry
disagree, the registry and its validator win.

## 1. Definition

A 360 composes a view by **reading canonical authorities** — identity,
relationship facts, graph, evidence, temporal, measurement, UPR, and the rest
of the curated `AUTHORITY_INDEX` — and, when it writes, **writes only through
the Graph Mutation Gateway** (`MutationIntent` → `GraphMutationGateway.apply`).
`ownsCanonicalTruth` is structurally `false` for every projection; the
architecture validator hard-fails on anything else.

- **Projections read Gold.** Silver projectors write Silver; projections read
  Gold and the canonical planes. The projector-ownership registry is never an
  authority of a projection.
- **Reads are scoped.** Every projection request is tenant-scoped,
  server-authoritative, and bounded (`PageRequest`, `TimeRangeFilter`,
  `as_of` from the temporal kernel).
- **Writes are gated.** Default `graphMutationPolicy` is `read_only` (no write
  path at all). `canonical_gateway_only` projections write only through the
  gateway.
- **Claims are evidenced.** Every claim in a projection result carries a
  reused `EvidenceRef`; a claim that cannot be grounded is a typed section
  state, never a silent assertion.

## 2. The tetris inventory — what exists today

The Aether backend is a **fully built platform**: every one of the nineteen
projections already maps to shipped, mounted work. None is greenfield. The
registry therefore records **honest state** per projection — `in_flight`
(existing implementation, not yet converged onto the projection plane) — with
`legacyBindings` resolving to the real routes, surfaces, and services. Three
360 vertical slices (`outcome360`, `economic360`, `infrastructure360`) are now
**`implemented`**: a real `IntelligenceProjectionProvider` registered in the
`ProviderRegistry`, zero pending refs, zero unresolved refs, and
`legacyBindings.migrationMode == "converged"`. New work (missing surfaces,
missing metrics, unformalized spines, native providers, any future projection)
is declared **pending** and slots in additively. This table is the truthful
inventory; the authoritative machine-readable copy is
`packages/shared/contracts/intelligence-projection-registry.json`.

### Existing surfaces (14) — `packages/shared/contracts/surface-capability-registry.json`

`graph`, `profile360`, `campaign360`, `cluster360`, `geo`, `journeys`,
`timeline`, `product_intelligence`, `temporal_observatory`,
`comparison_workbench`, `outcome360`, `economic360`, `connection360`,
`infrastructure360`. Temporal modes: `window|as_of|compare|relative`.
The four UI-less surfaces (`outcome360`, `economic360`, `connection360`,
`infrastructure360`) exist so every projection's `surfaceIds` resolves
(following the `temporal_observatory` precedent — surfaces without
adapters/pages are legal; `infrastructure360` additionally owns the read-only
`/v1/infrastructure` route classified in `config/route_registry.yaml`).

### Per-projection inventory

| id | kind | existing work today (mounted routes / services) | `surfaceIds` (resolved) | declared gaps (`pending`) |
|---|---|---|---|---|
| profile360 | entity_360 | `/v1/profile360`, `/v1/profile`; `services/profile/` aggregator/composer; `profile360` surface + tenant & Kyber pages | profile360 | — |
| agent360 | agentic_360 | `/v1/agent`, `/v1/agents`, `/v1/profile360/{type}/{id}` (AgentProfile360Composer); `services/agent/`, `agentic_observability` | profile360 | — |
| relationship360 | relationship_360 | `/v1/graph` (relationship paths, H2H/A2A layers), `/v1/semantic` (`gold_relationship_semantic_state`), `/v1/entities` | graph, profile360 | — |
| social360 | relationship_360 | `/v1/profile/{id}/social-intelligence` (single endpoint); `services/social/` | profile360 | thin — folded into profile |
| episode360 | sequence_360 | `/v1/journeys`, `/v1/events`; journey/timeline surfaces | journeys, timeline | spine `journey_continuity` |
| communication360 | sequence_360 | `/v1/comms`, `/v1/contact`, `/v1/delivery`, `/v1/notifications`; `services/comms/repository` feeds profile summary | timeline, profile360 | metricRefs: `email_open_rate`/`click`/`reply` resolve |
| execution360 | sequence_360 | `/v1/agents/{id}/execute`, `/v1/agent/runs`, `/v1/jobs`, `/v1/flows`, `/v1/computations` | timeline | — |
| temporal360 | context_360 | `/v1/graph` bitemporal `as_of`/`compare`; `/v1/preferences/temporal`, `/v1/tenants/temporal-defaults`; `shared/temporal/`; `temporal_observatory` surface | temporal_observatory, timeline | spine `graph_history_replay` (ledger exists; no replay API) |
| geographic360 | context_360 | `/v1/geo`; `geo` surface | geo | spine `context_capsule_semantics` |
| population360 | context_360 | `/v1/population`; `services/population/` | comparison_workbench, cluster360 | spine `grouping_membership` |
| cluster360 | operational_workbench | `/v1/clusters`; `cluster360` surface + tenant page | cluster360, graph | — |
| outcome360 | measurement_360 | **`implemented`** (S2) — `Outcome360Provider` in `services/measurement/outcome/`; reads outcome ledger + measurement engine (`gold_materializer`, `journey_compiler`); reads canonical `outcome_facts`/`measurement_contract`/`graph`/`evidence` | campaign360, outcome360 | — (zero pending; `migrationMode: converged`, `docs/blueprints/outcome360.md`) |
| economic360 | measurement_360 | **`implemented`** (S3) — `Economic360Provider` in `services/economic/`; reads `ai_costs`/`ai_models`/`computed_results`/`value_diagnostics` + `economic-metrics.ts` taxonomy; USD-safe value semantics (`services.value`), no cross-currency sums | campaign360, product_intelligence, economic360 | — (metricRefs `revenue`/`campaign_spend`/`campaign_roas`/`campaign_cac`/`campaign_ltv` all resolve; zero pending; `converged`, `docs/blueprints/economic360.md`; `projectionDependencies profile360/relationship360` remain `in_flight` → those sections degrade, never lie) |
| campaign360 | measurement_360 | `/v1/campaigns`, `/v1/campaign-sources`, `/v1/mapping-review`, `/v1/campaign-quality`; campaign materializer; measurement campaign engine | campaign360, comparison_workbench | metricRefs `conversion_rate`/`attributed_conversions`/`revenue`/`touchpoints` resolve |
| risk360 | risk_360 | `/v1/risk-overlays` (flag-gated OFF), `/v1/capability-risk`; CIS gateway | graph, comparison_workbench | flag-gated today |
| fraud360 | risk_360 | `/v1/fraud`, `/v1/fraud/networks`; `services/fraud/`, `fraud_networks/` | graph | — |
| source360 | operational_workbench | `/v1/imports`, `/v1/kyber/imports`, `/v1/providers`; UPR; `services/traffic/classifier.py` | campaign360 | — |
| connection360 | operational_workbench | `/v1/integrations/connectors`, `/v1/provider-connections`, `/v1/client-sync`; `provider_runtime` connections/credentials/health | (**new surface `connection360` added in P0**) | spine `reconciled_control_plane` (harness rollup PR #529 merged; spine not yet formalized) |
| infrastructure360 | infrastructure_360 | **`implemented`** (S4) — 19th projection; `Infrastructure360Provider` in `services/infrastructure/` (read-only, `graphMutationPolicy: read_only`, no write path); `GET /v1/infrastructure/{subject_kind}/{subject_id}` + `/health` (classified in `config/route_registry.yaml`); reads `infrastructure_facts`/`infrastructure_state`/`deployments` authorities over the `infrastructure_model` spine | infrastructure360 | — (zero pending; `converged`, `docs/blueprints/infrastructure360.md`) |

**Tetris mechanics.** Existing pieces (all 19) sit on the board with their
real coordinates (routes → `legacyBindings`, surfaces → `surfaceIds`, metrics
→ `metricRefs`). The three 360 vertical slices dropped into place without
disturbing placed pieces: `outcome360`/`economic360` flipped to `implemented`
(their metric pending refs were absorbed once `metric-registry.json` gained the
economic metric set) and `infrastructure360` landed as a new piece. Still-queued
pieces — the unformalized spines (`journey_continuity`,
`context_capsule_semantics`, `grouping_membership`, `graph_history_replay`,
`reconciled_control_plane` — declared `pendingAuthority`), native providers for
the remaining `in_flight` projections, and any future projection — drop into
place when their slot opens, without moving or deleting placed pieces.

## 3. Registry ownership + generated artifacts

The **Intelligence Projection Registry**
(`packages/shared/contracts/intelligence-projection-registry.json`) is the
single canonical registry for the 19 projections. `schemaVersion` /
`contractVersion` are present; vocab arrays (`projectionKinds`,
`implementationStates`, `graphMutationPolicies`, `sectionStates`,
`temporalModes`, `migrationModes`, `subjectKinds`) are non-empty unique
`lower_snake` idents; every per-entry field is present and typed;
`ownsCanonicalTruth` is `false` for all 19. `implementationState` is repo
metadata, **not** readiness (see `docs/decisions/ADR-010-intelligence-projection-plane.md` §D3).

Generated artifacts (via `scripts/generate_platform_contracts.py`, the
`REGISTRIES` table) — **never hand-edited**; regenerate with
`make repo-doctor-fix`:

| Artifact | Contents |
|---|---|
| `packages/shared/intelligence-projections_generated.ts` | `intelligenceProjectionsContractVersion`, `intelligenceProjectionIds`/`IntelligenceProjectionId`, kinds/states/section-states, `intelligenceProjectionDefinitions` (sorted by id), `projectionDependencyGraph`, `pendingAuthorities`, `pendingReferences` |
| `Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py` | `INTELLIGENCE_PROJECTION_DEFINITIONS`, `PROJECTION_DEPENDENCY_GRAPH`, `PROJECTION_SURFACE_MAP`, `PROJECTION_CAPABILITY_MAP`, vocab constants, `__all__` (sorted) |
| `docs/_generated/intelligence-projection-registry-table.md` | per-projection table: id/kind/state/spines/proj-deps/surfaces/capability keys/graph policy/authorities/legacy routes/blueprint link |
| `docs/_generated/intelligence-projection-dependency-graph.md` | Mermaid `flowchart LR`; hard-dep solid, proj-dep dashed, optional dotted; `## Pending resolutions` table |

Every emitter sorts by projection id; generation is order-stable
(byte-identical across row reorder), and `scripts/generate_platform_contracts.py
--check` enforces it. Rollback is additive: delete a row + regenerate; other
rows stay byte-stable.

## 4. Relationship to adjacent planes

| Adjacent plane | Relationship to the projection plane |
|---|---|
| **Silver projector-ownership registry** | Separate authority. Projectors WRITE Silver; projections READ Gold. The projector registry is never a canonical authority of a projection (validator forbids it; it may appear only as an input ref). |
| **Graph Mutation Gateway** | The write path. Projections default `read_only`; `canonical_gateway_only` projections write only via `GraphMutationGateway.apply(MutationIntent)` (`off\|shadow\|enforce`, `replay_ledger()` digest). |
| **Exploration Fabric** | Surface join. Projections JOIN `surface-capability-registry.json`; `surfaceIds ⊆` the surface registry. The projection registry never defines surfaces. S6 migration seam — the three implemented 360 surfaces (`outcome360`/`economic360`/`infrastructure360`) surface in exploration through `services/exploration/adapters/projection.py::ProjectionSurfaceAdapter`, which maps the surface to its projection id and runs the projection through the S1 engine for the tenant-scoped subject, reshaping the engine result into the exploration `AdapterResult` envelope (digest, per-section state, degradation; fail-isolated + content-free, `populated=False` on a missing provider). Registered only for 360s that previously had no adapter — an already-owned surface is never shadowed. |
| **Readiness vocabulary** | No parallel ladder. `implementationState` never maps to readiness; `readiness.py` maps it to presentation-only tokens and is asserted to never emit a certification token or `production_ready`. |
| **Measurement plane** | An authority (`shared/measurement`, computation substrate). `metricRefs` resolve against `metric-registry.json`; economic/outcome metrics not yet in the registry stay in `pendingReference`. |
| **UPR** | An authority (`services/provider_runtime/`). `connection360`/`source360` read connections/credentials/health from it; the `ProviderRegistry` mirrors the UPR `ProviderRegistry` shape. |
| **Temporal kernel + bitemporal ledger** | An authority (`shared/temporal/`, graph mutation gateway ledger). `temporal360` reads bitemporal `as_of`/`compare`; the `graph_history_replay` spine is pending (ledger exists, no replay API). |
| **Fraud engines / governance / CIS / model governance** | Authorities the risk projections (`risk360`, `fraud360`) read. The projection plane re-implements none of them. |

**Presentation-only readiness, on paper.** The projection plane's presentation
tokens — `queued`, `converging`, `converged`, `retired` (from `readiness.py`) —
are projection-CONVERGENCE tokens in the projection plane's OWN namespace, NOT
readiness tokens. They are therefore deliberately excluded from
`packages/shared/contracts/readiness-vocabulary.json`: that file's `singleSource`
rule governs the readiness/certification token consumers (the Python
`CredentialReadiness` enum and the TypeScript `CapabilityState` union) only, and
the projection plane is none of those consumers. The plane never emits a
certification token and never emits `production_ready` (a claim dimension, not a
state); `readiness.py` asserts both at import time, and the test suite proves
disjointness from `CredentialReadiness` without importing the certification
plane at runtime.

## 5. Runtime provider protocol

The runtime lives in `Backend Architecture/aether-backend/shared/intelligence_projections/`
and ships as a library whose provider modules never auto-wire at import — in P0
there was no `main.py` wiring and no public projection route. The plane is
brought live explicitly, at boot, through a single seam — §6 *Plane-live
enforcement*:

- **`provider.py`** — `IntelligenceProjectionProvider` is a `typing.Protocol`
  (`projection_id`, `contract_version`, `async project(request, context) ->
  ProjectionResult`). There is **no `Base360` superclass**. A provider must not
  mutate canonical state outside the gateway and must raise only
  `ProjectionError` subclasses.
- **`registry.py`** — `ProviderRegistry(registry_data=generated_registry.INTELLIGENCE_PROJECTION_DEFINITIONS)`:
  `register` (asserts projection_id in registry, contract-version compatible,
  rejects duplicate different-object), `unregister`, `get`,
  `availability()` (never infers readiness from import success),
  `build_context()` (computes `dependency_state`), `project()` (guard-wraps
  each provider → `degraded` on failure, `ProjectionNotFound` when
  unregistered), `supported_contracts()`.
- **Fail isolation.** A missing dependency → `dependencyState[dep] =
  "missing"` and the dependent sections `missing`; incompatible → `degraded`;
  optional dep absent → `not_applicable`; one provider raising → only its
  result `degraded` while others stay `available`. One broken projection cannot
  take down the plane.
- **Shared contracts** — `contracts.py` (`ProjectionRequest`,
  `ProjectionContext`, `ProjectionResult`, `ProjectionSection`,
  `ClaimEnvelope`, typed `SectionState`) reuse `ContractModel`, `EntityRef`,
  `EvidenceRef`, `PageRequest`, `PageInfo`, `TimeRangeFilter` from
  `services/operational_intelligence/models.py`. **No redefinitions.**

**Consumption seams (S6)** — projections surface OUT of the plane through two
thin, read-only seams, neither of which registers here or re-declares a
contract:
- The **exploration surface seam**
  (`services/exploration/adapters/projection.py::ProjectionSurfaceAdapter`)
  backs the implemented 360 exploration surfaces by running each surface's
  projection through the S1 engine (`ProjectionRuntime` → `ProjectionExecutor`)
  — see the **Exploration Fabric** row in §4 and
  `EXPLORATION_FABRIC.md`.
- The **Noesis read seam**
  (`services/noesis/adapters/projection_intelligence_adapter.py`) answers a
  `projection_read` for one registered projection id behind the existing Noesis
  tenant/permission gate, returning the projection digest + per-section state;
  an unknown id / invalid subject kind / missing provider / engine error
  degrades to a static content-free reason (`unknown_projection` /
  `invalid_subject_kind` / `provider_unavailable` / `projection_failed`) and
  answers `sufficient=False` — never a synthesized result.

## 6. Vertical-slice DoD + migration rules

The Definition-of-Done every follow-up 360 PR must satisfy before flipping its
registry row to `implemented` is
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`.

**Add** a projection: register → `in_flight` → `implemented`.
- `registered`: non-empty `implementationBlueprint`; may have empty bindings;
  unresolved refs MUST be declared pending.
- `in_flight`: non-empty `legacyBindings` resolving to real
  routes/surfaces/services (`inventory_integrity`); pending refs legal.
- `implemented`: `legacyBindings.migrationMode == "converged"`, zero pending,
  zero unresolved refs — hard validator failure otherwise.

**Remove** a projection: delete the entry + regenerate. Other rows are
byte-stable (order-stable, additive rollback).

**Converge** existing work: swap `legacyBindings.adapter` for a real provider
(Protocol + `ProviderRegistry.register`), converge the surfaces/metrics it
resolves, land the vertical slice, then flip to `implemented`.

**Plane-live enforcement (registration at mount)**: a provider is **not live**
until it is registered at the boot seam. `main.py`'s `lifespan` startup calls
`dependencies.projection_plane.register_implemented_projection_providers`
(`Backend Architecture/aether-backend/dependencies/projection_plane.py`), which
registers exactly the providers listed in `IMPLEMENTED_PROJECTION_IDS` on the
global runtime `projection_registry`. Landing a vertical slice therefore means
adding its provider module to that seam **in the same change that flips the row
to `implemented`** — otherwise the projection stays unregistered and its surface
degrades to `provider_unavailable` instead of composing live. Provider modules
keep their caller-driven `register_provider(registry)` contract and never mutate
the global at import time; the seam is the sole production caller and is
idempotent across repeated boot entries (an id already registered is left
untouched).

**Pending-ref rules**: unresolved refs are legal only when declared
`pendingAuthority`/`pendingReference` with `{id, kind, reason,
resolvesInProjection}`; undeclared unresolved → error in any state; a pending
declaration whose target now resolves is a dangling declaration → error; an
`implemented` projection must have zero pending and zero unresolved.

**Order-resilience rules**: registration is order-independent (the validator
gates claims, not additions); generation is sorted-by-id and byte-stable; the
runtime is fail-isolated per projection; rollback is delete-entry +
regenerate; new surfaces/metrics are appended, never rewritten.

## 7. Anti-patterns (forbidden)

- **A second canonical owner.** Any projection with `ownsCanonicalTruth:
  true`, or that writes canonical state outside the Graph Mutation Gateway,
  fails validation and review.
- **Readiness from `implementationState`.** Deriving a certification token,
  `production_ready`, or any readiness ladder position from `implemented` is
  forbidden; `readiness.py` is presentation-only and asserted against it.
- **Silent unresolved refs.** A cross-registry ref that does not resolve and
  is not declared pending fails in any state.
- **`implemented` with pending refs.** Zero pending, zero unresolved, and
  `converged` bindings are hard requirements; anything less is a lie the
  validator rejects.
- **A parallel surface / metric / readiness authority.** Surfaces stay owned
  by the surface registry, metrics by the metric registry, readiness by its
  own vocabulary; the projection plane never re-defines any of them.
- **A generic public 360 route.** Projection routes exist only as `legacyBindings`
  references to prefixes already classified in `config/route_registry.yaml`
  (default-deny ratchet). A projection may add a new classified prefix only as
  part of its vertical slice — `infrastructure360` did so with the read-only
  `/v1/infrastructure` (every route a GET; no generic catch-all).
- **Second EntityRef / EvidenceRef / PageRequest / time-range.** Projection
  contracts reuse the canonical primitives; re-declaring any of them is a
  parity/imports failure.

## Related

- `docs/decisions/ADR-010-intelligence-projection-plane.md` — the decision
  record (Context / Decision / Consequences).
- `docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
  — the Definition-of-Done checklist.
- `docs/source-of-truth/PROJECTION_ENGINE_ARCHITECTURE.md` — the higher
  orchestration layer (lens composition algebra, projection IR / compiler /
  planner / executor / digest, typed degradation, `G @ C` context operator,
  cross-360 `composition`)
  that runs projections through this plane's `ProviderRegistry`.
- `docs/source-of-truth/BACKEND_INTELLIGENCE_ARCHITECTURE.md` — the additive
  target architecture this plane is a part of.
- `docs/_generated/intelligence-projection-registry-table.md`,
  `docs/_generated/intelligence-projection-dependency-graph.md` — generated
  twins (regenerated, never hand-edited).
