---
title: "ADR-010: Intelligence Projection Plane"
slug: decisions/adr-010-intelligence-projection-plane
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# ADR-010: Intelligence Projection Plane

**Status**: Accepted (8.12.0)

## Context

Aether ships eighteen "360" surfaces — profile360, relationship360,
campaign360, outcome360, and the rest — as mounted routes and services across
the backend. Each is, in practice, a composite read over canonical Aether
truth (identity, relationship facts, graph, evidence, temporal, measurement,
UPR, and the other authorities), but **nothing in the codebase states what a
360 *is***. There is no canonical registry of projections, no shared
projection request/result contract, no runtime protocol for executing a
projection, no honest inventory of which projections exist and what each is
bound to, and no definition separating "a projection is implemented" from "a
projection is production-ready".

Three forces make this a problem:

- **Ad-hoc composites drift toward competing systems of record.** Without a
  declared authority boundary, a 360 becomes a parallel store or a parallel
  write path that re-answers questions the canonical planes already answer.
- **Follow-up blueprints must be implementable out of order.** The P0
  roadmap is a set of ordered 360 blueprints, but a hard requirement is that
  a follow-up blueprint may be implemented **before or after any other**
  without corrupting or destroying previously-landed work — including
  projections that landed before it.
- **Existing work must be organized into the architecture like tetris.**
  Shipped work is not greenfield: the backend is already fully built, and
  every one of the eighteen projections already maps to real routes,
  surfaces, and services. The architecture must inventory that truth
  honestly, place the existing pieces with their real coordinates, and let
  new work (missing surfaces, missing metrics, unformalized spines, native
  providers, any future projection) slot in additively — never disturbing
  already-placed pieces.

## Decision

Adopt an **Intelligence Projection Plane**: one canonical machine-readable
registry of projections, shared request/context/result contracts (reusing
existing primitives), a runtime provider registration Protocol, a
cross-registry architecture validator, deterministic generation, and a
source-of-truth doc — all enforcing a single binding doctrine:

> **A 360 is an intelligence projection over canonical Aether truth. It is
> not a competing system of record.**

The plane is **additive, order-resilient, and reversible** (data-migration
free). No new public projection route is added by the plane itself; the
runtime ships as a library until the first real provider lands.

### D1 — A 360 is a projection, never a system of record

Every projection **reads** canonical authorities — identity, relationship
facts, graph, evidence, temporal, measurement, UPR, and the rest of the
curated authority index — when it composes. When a projection **writes**, it
writes only through the Graph Mutation Gateway (`MutationIntent` →
`GraphMutationGateway.apply`). `ownsCanonicalTruth` is structurally `false`
for every projection; the architecture validator hard-fails on anything
else.

### D2 — The Intelligence Projection Registry is the single canonical registry

`packages/shared/contracts/intelligence-projection-registry.json` is the
**single new canonical registry** for the eighteen projections. It records
id, kind, state, subject kinds, canonical authorities, hard spines,
projection dependencies, input refs, output sections, temporal modes,
surfaces, capability keys, metric refs, graph mutation policy, evidence /
freshness / limitations requirements, security, cost, commercial
classification, and the honest `legacyBindings` for existing work. The
registry **extends** adjacent registries; it never re-defines them.
Surfaces remain owned by `surface-capability-registry.json`, metrics by
`metric-registry.json`, mutation types by `graph-mutation-registry.json`.

### D3 — `implementationState` is repo metadata, NOT readiness

`implementationState` records where a projection is in its
registry → `in_flight` → `implemented` lifecycle. It is repo metadata about
the *codebase*, never a statement about *production readiness*:

- `registered` — planned; a projection row with a blueprint, nothing shipped.
- `in_flight` — an existing implementation, not yet converged onto the
  projection plane.
- `implemented` — a full vertical slice: zero pending refs, zero unresolved
  refs, `legacyBindings.migrationMode == "converged"`.
- `deprecated` — retired, with a `deprecatedReason` (and optional
  `successorId`).

Readiness has its **own vocabulary** (hand-bound, validator-enforced) and is
never derived from `implementationState`. A projection flipping to
`implemented` makes **no** `production_ready` claim.

### D4 — The inventory principle (tetris)

Existing shipped work is organized into the architecture as `in_flight`
with `legacyBindings` that resolve to the **real** routes, surfaces, and
services it already mounts. New work — missing surfaces, missing metrics,
unformalized spines, native projection providers, any future projection — is
declared `pendingAuthority` / `pendingReference` and slots in additively
when its slot opens, without re-ordering, rewriting, or deleting placed
pieces. The registry is a **truthful inventory of what exists**, not a
placeholder list.

### D5 — Order-resilience contract

- **Registration is order-independent.** The validator gates *claims*, not
  additions; it never gates on "how many projections are implemented".
- **`pendingAuthority` / `pendingReference` are the only legal escape
  hatches.** Any cross-registry ref (surface id, metric ref, spine,
  authority, dependency) that does not yet resolve MUST be declared with
  `{id, kind, reason, resolvesInProjection}` — never a silent string. An
  undeclared unresolved ref is a validator error in *any* state
  (fail-closed). A pending declaration whose target later resolves becomes a
  **dangling declaration** → error ("remove it"), so escape hatches cannot
  rot.
- **The runtime is fail-isolated per projection.** A missing/incompatible
  dependency yields typed `missing` / `degraded` / `not_applicable` section
  states, never an exception at context build; one failing provider degrades
  only its own result.
- **Generation is order-stable.** Every emitter sorts by projection id;
  reordering registry rows or shuffling dependency arrays across a rebase
  produces zero diff.
- **Rollback is additive.** Removing a projection = delete the entry +
  regenerate; every other row is byte-stable.

### D6 — Relationship to existing planes

- **Silver projector-ownership registry** — a **separate authority**.
  Projectors WRITE Silver; projections READ Gold. The projector-ownership
  registry is *never* an authority of a projection (the validator forbids it
  as a canonical authority; it may appear only as an input ref).
- **Graph Mutation Gateway** — projections default to `read_only`; a
  `canonical_gateway_only` projection writes only via
  `GraphMutationGateway.apply(MutationIntent)`. There is no other write path.
- **Exploration Fabric** — projections JOIN the surface registry;
  `surfaceIds` must be a subset of that registry. The projection registry
  **never defines surfaces**.
- **Readiness vocabulary** — no parallel ladder. `implementationState` never
  maps to readiness; readiness is a presentation-only join
  (`readiness.py`) that is asserted to never emit a certification token or
  `production_ready`.
- **Measurement, UPR, temporal kernel + bitemporal ledger, fraud engines,
  governance/CIS, model governance** — all remain the authorities they are;
  projections read them and never re-implement them.

## Security invariants (binding)

- Projections never receive direct database authority; they read through
  repositories and write only through the Graph Mutation Gateway.
- Tenant scope is server-authoritative; a projection result is scoped to the
  requesting tenant end to end, and cross-tenant evidence leakage is
  forbidden.
- `read_only` projections have no write path at all; `canonical_gateway_only`
  projections require a gateway contract and enforced policy.
- Staging/production fail closed on missing configuration; a misconfigured
  projection degrades its section state — it never silently bypasses policy.
- Providers must not mutate canonical state outside the gateway, and must
  raise only `ProjectionError` subclasses.

## Consequences

### Positive

- **A single coherent plane.** One registry, one shared contract, one
  runtime protocol, one validator — a 360 is defined once and enforced
  everywhere.
- **Out-of-order-safe follow-ups.** Order-resilience is designed in:
  skip-ahead never corrupts, and pending refs make cross-registry gaps
  explicit instead of silent.
- **Honest inventory.** The tetris inventory records what actually exists
  (all eighteen `in_flight`, with real `legacyBindings`) and what is pending;
  `implemented` stays empty until a projection truly conforms.
- **Additive, reversible, migration-free.** Existing routes, surfaces, and
  services are untouched; rollback is delete-and-regenerate; no data
  migration.
- **Fail-isolated runtime.** One broken projection cannot take down the
  plane.

### Negative / constraints

- **No `Base360`.** There is deliberately no projection superclass; providers
  are `typing.Protocol` plugins. Teams cannot rely on inherited behavior.
- **No second EntityRef/EvidenceRef/PageRequest/time-range.** Projection
  contracts must reuse the canonical primitives; re-defining any of them is
  a validator/parity failure.
- **Every unresolved ref must be declared pending.** There is no silent
  unresolved-ref path — a real cost for plumbing, but the only way to keep
  the plane honest and order-resilient.
- **`implemented` cannot lie.** A row is `implemented` only with zero
  pending, zero unresolved, and converged bindings; anything less is a hard
  failure. All eighteen projections start `in_flight`; nothing claims
  `implemented` until a real vertical slice lands.
- **No generic public 360 route.** P0 adds no public projection route prefix;
  the runtime is a library until the first real provider wires it.

## Follow-on (explicitly OUT of this ADR)

The plane itself does not implement any individual 360. Each 360 lands as a
separate vertical-slice PR that (1) converges its registry row to
`implemented` via `docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`,
(2) resolves its pending refs, and (3) swaps `legacyBindings.migrationMode`
to `converged`. The operator endpoint
`GET /v1/admin/kyber/intelligence/projections` is deferred (optional per the
P0 blueprint).

## References

- `packages/shared/contracts/intelligence-projection-registry.json` — the
  single canonical registry (18 projections, all `in_flight`).
- `scripts/validate_intelligence_projections.py` +
  `scripts/lib/intelligence_projection_validation.py` — the architecture
  validator (schema, DAG, cross-registry, inventory honesty, ownership,
  surface/metric honesty).
- `packages/shared/intelligence-projections_generated.ts`,
  `Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py`,
  `docs/_generated/intelligence-projection-registry-table.md`,
  `docs/_generated/intelligence-projection-dependency-graph.md` — generated
  twins (never hand-edited).
- `Backend Architecture/aether-backend/shared/intelligence_projections/`
  — `contracts.py`, `provider.py` (Protocol), `registry.py`
  (`ProviderRegistry`), `errors.py`, `readiness.py`, `__init__.py`.
- `docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md` — the
  enforceable source-of-truth doc (tetris inventory, migration rules,
  anti-patterns).
- `docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
  — the Definition-of-Done every follow-up 360 PR must satisfy.
- `docs/decisions/ADR-008-multi-model-intelligence-harness.md`,
  `docs/decisions/ADR-009-universal-provider-runtime.md` — the additive,
  registry-driven, Protocol-based precedents this ADR extends.
- `docs/source-of-truth/BACKEND_INTELLIGENCE_ARCHITECTURE.md` — the additive
  target architecture the projection plane is a part of.
