---
title: "Infrastructure360 Vertical Slice Blueprint"
slug: blueprints/infrastructure360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Infrastructure360 — implementation blueprint

**Projection**: `infrastructure360` · **Display name**: Infrastructure 360 ·
**Kind**: `infrastructure_360` · **Registry row**: the 19th row of
`packages/shared/contracts/intelligence-projection-registry.json`.

This is the `implementationBlueprint` for the infrastructure360 registry row. It
is the Definition-of-DoD pointer for the S4 vertical slice and the honest
declaration of what the projection is, what it reads, and what it deliberately
is **not**.

---

## 1. What it is

Infrastructure360 is a **read-only intelligence projection** over canonical
Aether infrastructure truth. It answers the operational question *"what is this
tenant's infrastructure actually doing right now?"* — what entities exist, what
state they are in, what deployments are running, what the evidence says, and
what findings follow — by **composing canonical authorities**, never by keeping
its own store.

| Attribute | Value |
|---|---|
| `projectionKind` | `infrastructure_360` |
| `implementationState` | `implemented` (S4 lands the vertical slice) |
| `ownsCanonicalTruth` | `false` (structural — never flipped) |
| `subjectKinds` | `entity`, `deployment`, `infrastructure` |
| `canonicalAuthorities` | `infrastructure_facts`, `infrastructure_state`, `deployments`, `graph`, `evidence`, `temporal` |
| `hardDependencies` | `contract_spine`, `temporal_kernel`, `infrastructure_model` |
| `projectionDependencies` | `[]` — a **leaf projection**; it depends on no sibling 360 |
| `outputSections` | `summary`, `state`, `deployments`, `evidence`, `findings` |
| `graphMutationPolicy` | `read_only` — **no write path at all** |
| `tenantScoped` | `true` — tenant scope is server-authoritative end to end |
| `requiresEvidence` | `true` — every claim carries a reused `EvidenceRef` |
| `legacyBindings.migrationMode` | `converged` |
| `pendingAuthority` / `pendingReference` | `[]` — **zero pending** |

## 2. Why it exists

Aether's eighteen projections compose identity, relationship, measurement, and
risk truth — but nothing surfaces the **runtime substrate** those systems run
on. Infrastructure360 is the nineteenth projection: a 360 over the operational
*infrastructure* plane (service/database/cache/queue/host/… entities, their
lifecycle states, and the deployments riding on them). It exists so an operator
or agent can ask, in the same intelligence-projection vocabulary as every other
360, *"what infrastructure backs this tenant, and is it healthy?"* — without a
parallel store and without a parallel write path.

## 3. The read-only doctrine (binding)

Per ADR-010 and the vertical-slice checklist §9:

- `graphMutationPolicy` is `read_only`. The provider (`Infrastructure360Provider`)
  **has no write path** — no graph write, no mutation call, no state change.
  There is nothing to mutate: the projection reads canonical truth and projects.
- **Providers raise only `ProjectionError` subclasses.** In practice
  infrastructure360 degrades rather than raises; any unexpected exception is
  fail-isolated by the plane's `ProviderRegistry`.
- **Degraded results are content-free.** A section the provider cannot ground is
  a typed `degraded` / `missing` / `empty` state with a static source-key reason
  (e.g. `"deployments"`) — never an exception message, never fabricated content.

## 4. How it works

### 4.1 Contracts (`services/infrastructure/contracts.py`)

Canonical infrastructure domain models (Pydantic v2, tolerant `ContractModel`):

- `InfrastructureEntityType` — `service | database | cache | queue | worker |
  function | container | host | network | storage | gateway | orchestrator`.
- `InfrastructureState` — `provisioned | deploying | active | degraded |
  maintenance | deprovisioning | failed | unknown`.
- `InfrastructureRelationshipType` — `depends_on | deployed_on | connects_to |
  composed_of | scales_with`.
- `InfrastructureRelationship`, `Deployment`, `InfrastructureEntity`.

**Reuse, never redefine**: `EntityRef`, `EvidenceRef`, `PageRequest`,
`TimeRangeFilter` (and `ContractModel`) are imported from
`services/operational_intelligence/models.py`. This package declares **no**
second copy of any canonical primitive (checklist §2; enforced by the
no-redefinition test).

### 4.2 Taxonomy (`services/infrastructure/taxonomy.py`)

Pure, deterministic, I/O-free:

- `INFRASTRUCTURE_FACT_CATEGORIES` = `infrastructure_facts`,
  `infrastructure_state`, `deployments` — exactly the registry
  `canonicalAuthorities` the provider reads over.
- `LEGAL_STATE_TRANSITIONS` — a small legal-transition table. Headline
  invariant: **`FAILED → ACTIVE` is illegal** without an intervening redeploy
  (`FAILED → PROVISIONED → DEPLOYING → ACTIVE`). `requires_redeploy(FAILED, …)`
  exposes that rule.
- `RELATIONSHIP_SEMANTICS` — the single canonical meaning of each edge type.
- `DEPLOYMENT_TARGET_KINDS` — the entity kinds a deployment may land on.

### 4.3 Provider (`services/infrastructure/provider.py`)

`Infrastructure360Provider` implements the plane's
`IntelligenceProjectionProvider` **Protocol** (`projection_id`, `contract_version`
= `INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION`, `async project`). There is **no
`Base360` superclass**.

`project()`:

1. Reads canonical sources through a tenant-scoped reader
   (`canonical_reader(request.tenantId)`). The default reader imports
   `services/provider_runtime/registry.py` (provider/service health),
   `services/model_runtime/` (model-service presence) and `services/noesis/`
   (deployments) **lazily and defensively**; an authority that cannot be read is
   named in `degraded_sources`.
2. Re-filters every reader record by `request.tenantId` as a
   server-authoritative backstop — **tenant A's projection can never surface
   tenant B's deployments or evidence** (checklist §8).
3. Builds the five sections `summary`, `state`, `deployments`, `evidence`,
   `findings` — each in a valid `SectionState` (`available | empty | missing |
   degraded | not_applicable | unknown`). A source-backed section is
   `available`; a section whose authority is unreadable is `degraded`; a section
   with a healthy authority but no records is `empty`. **The provider never
   fabricates.**
4. Emits `ClaimEnvelope`s, every one carrying a reused `EvidenceRef`
   (`type="entity"` from `infrastructure_facts`, `type="event"` from
   `deployments`). An ungrounded claim is a typed section state — never a silent
   assertion (checklist §7).

`register_provider(registry)` registers the provider under
`source="services/infrastructure"`. It does **not** auto-register on the global
`projection_registry` at import time — wiring is the caller's job.

### 4.4 Routes (`services/infrastructure/routes.py`)

A FastAPI `APIRouter` at prefix `/v1/infrastructure` (declared in
`config/route_registry.yaml` `known_prefixes`, between `/v1/imports` and
`/v1/ingest`):

- `GET /v1/infrastructure/{subject_kind}/{subject_id}` — tenant-scoped
  (the tenant comes from the authenticated request, never the path),
  gated on the canonical `read` permission and the `infrastructure360.read`
  capability key. Composes a `ProjectionRequest` and executes it through the
  fail-isolated `ProviderRegistry`.
- `GET /v1/infrastructure/health` — read-only plane probe (registration +
  contract compatibility via `registry.availability()`).

Every route is a GET. **No route writes.**

## 5. Meaning for the graph

Infrastructure360 changes nothing on the graph. It is `read_only` and
`ownsCanonicalTruth: false`: it composes a view over canonical infrastructure
facts, lifecycle state, deployments, graph, evidence, and temporal truth. The
"19th projection" means one more consumer of the plane's shared contracts,
evidence discipline, and tenant isolation — not one more system of record.

## 6. Dependency story (leaf projection)

`hardDependencies` = `contract_spine`, `temporal_kernel`, `infrastructure_model`;
`projectionDependencies` = `[]` and `optionalProjectionDependencies` = `[]`.
Infrastructure360 depends on **no sibling 360** — it is a leaf. That makes it
out-of-order-safe: it can land before or after any other projection without
touching their rows (ADR-010 D5 order-resilience). The `infrastructure_model`
spine names the canonical model the projection reads; while the spine is
formalized, the provider degrades the affected sections honestly.

## 7. Zero-pending declaration

`pendingAuthority: []` and `pendingReference: []`. Every authority, spine,
surface (`infrastructure360` in `surface-capability-registry.json`), capability
key, and output section resolves against its real registry. Nothing is silently
unresolved.

## 8. Definition of Done

This slice satisfies `docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`
end to end: registry row (`implemented`, zero pending, converged bindings),
shared-contract conformance (no redefinitions), runtime provider, route
classification, surface join, evidence grounding, tenant isolation, `read_only`
graph policy, the targeted test suite, and no `production_ready` claim
(`implementationState` is repo metadata, not readiness).
