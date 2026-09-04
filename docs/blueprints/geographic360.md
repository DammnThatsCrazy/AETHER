---
title: "Geographic360 Vertical Slice Blueprint"
slug: blueprints/geographic360
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Geographic360 — Intelligence-Projection Blueprint

**Registry id:** `geographic360`
**Projection kind:** `context_360`
**Blueprint for:** the registry row's `implementationBlueprint` /
`legacyBindings.migrationBlueprint` — the vertical slice that converges
`geographic360` to `implementationState: "implemented"`. Executed as **Phase 4**
of [docs/plans/CONTEXTUAL_360_PHASES.md](../plans/CONTEXTUAL_360_PHASES.md)
(per-360 workstreams G4.1–G4.5), then flipped to `implemented` at the phase-4
exit gate.

---

## What it is

Geographic360 is Aether's **contextual WHERE projection** — a governed, read-only
answer to "where is / was this subject (or where did this population / source
come from), with what precision, and under what jurisdiction?" over
`subjectKinds: [entity, population, source]`. It reconciles coarse network-egress
geo (`GeoLookup`, context capsules) with a **single new canonical location
primitive** and projects `summary`, `state`, `timeline`, `evidence`, and
`findings` through the Intelligence Projection Plane's shared contracts.

It is NOT a competing geography system of record (ADR-010,
`ownsCanonicalTruth: false`), NOT a demographics or jurisdiction-policy engine,
and NOT a reverse-geocoding API dump. It never writes: `graphMutationPolicy:
read_only`. It does not add coordinates to the context capsule — the existing
no-raw-IP / no-lat-lon invariant on `LocationObservation`/`ContextCapsule` is
preserved (parity-tested); coordinates live **only** in the new location
contract this slice introduces.

The registry already names its authorities: `context_capsules`,
`geo_observations`, `locations`, `entity_graph`, `temporal`; a dedicated
`geographic360` surface (G4.4b — `geo` stays owned by its graph-plane adapter,
never shadowed); legacy binding `services/geo`; `hardDependencies:
[temporal_kernel, context_capsule_semantics]`; `projectionDependencies:
[profile360, temporal360]`.

## Why

Today Aether's geo story is a single, deliberately-coarse surface: network-egress
`GeoLookup` feeds context capsules that by design carry no coordinates, and
`/v1/geo` is a `not_provisioned` stub. There is no coordinate/place/region/
jurisdiction primitive, no spatial index, and no declared boundary between
"where a fact was observed" and "where a subject is governed." As sibling
projections (risk360's geographic dimension, population360's regional cohorts,
fraud synthesis over mule networks) began to need real geo, the gap became an
authority vacuum — the program's **only genuinely new canonical authority**. This
slice defines that primitive once, registers its edge vocabulary, and lands
`geographic360` as a real, fail-isolated provider that answers WHERE with
precision that never exceeds evidence.

## How it works

### The one new canonical authority — the location primitive

Per the Phase-0 geo decision (spike §5.5, adoption A/A/A/A), the slice introduces
exactly one new canonical geography authority and no second geography registry:

* **Location registry + models.** A new `packages/shared/contracts/location-registry.json`
  (role, precision class, region-type vocabulary — **not US-only**) and a
  `shared/geo` model surface (`LocationFact` with roles, precision, coordinates;
  `Place` / `Region` / `Jurisdiction`), surfaced through `services/geo`. The
  registry is the canonical source; generated twins come from it via the
  platform contract generator.
* **Coordinates live in the contract, never the context capsule.** The
  `LocationObservation`/`ContextCapsule` no-raw-IP / no-lat-lon parity test stays
  green. Geographic evidence is a first-class `LocationFact` with provenance.
* **Precision classes align to the existing taxonomy.** The `coarse_cell` /
  `precisionClasses` vocabulary already used by context capsules extends into the
  location contract so region and coordinate precision share one ladder.
* **Spatial index computed client-side.** H3 (`h3-py`) hierarchical cell strings
  for containment/neighborhood (`k-ring`); the graph backend is in-memory/Neptune
  and Postgres is JSONB — **no PostGIS**. Cells are stored as strings on facts /
  edges, never as a spatial index in the DB.
* **Geodesy via pure-python.** H3 cell math + `geographiclib` for geodesic
  distance. Heavier `pyproj`/`shapely` only if jurisdiction-boundary
  point-in-polygon is later required (not in this slice).
* **Geocoding behind the vault.** A `GeocodingProvider` protocol beside the
  existing `GeoProvider`, keys in the credential vault
  (`shared/credentials/interface.py` + `shared/providers/base.py`). MaxMind
  GeoLite2 local files remain the air-gapped default; no new external dependency
  is required to converge.
* **The governed store ships with the flip (G4.5).** The one repository over
  these facts is `services/geo/location_facts.py::LocationFactRepository`
  (table `location_facts`, the shared `BaseRepository` — in-memory dicts under
  `AETHER_ENV=local`, asyncpg JSONB in production). `record` is the *internal*
  write boundary (repositories only; deliberately no public route or consent
  surface); `active_facts_for_subject` reads tenant-scoped; and
  `revoke_facts_for_subject` is the governed soft-revoke (`active` → `revoked`,
  stamped, never a hard delete) the DSR eraser drives. The provider's default
  reader is store-backed rather than honest-`missing`.

### New graph vocabulary

Geography reaches the graph through edges, not a parallel store. The slice adds
a new `EdgeType` for located-in / observed-at / governed-by relationships plus a
`relationship_layers` entry — **required**, because unclassified edges error in
staging/prod. A subject's location history therefore reads as a timeline of
typed, evidence-carrying graph edges (`timeline` section), and jurisdiction
(`Place`/`Region`/`Jurisdiction` hierarchy) is carried distinctly from the
observation that locates a subject — jurisdiction-vs-location stays a first-class
separation, never collapsed into one "address" field.

### Precision and privacy (the honesty contract)

* **Precision never exceeds evidence** (standing rule 2). A source that yields
  only city precision renders `city`, never an exact coordinate; an ungrounded
  coordinate is a typed `missing`/`degraded` state, never a silent assertion.
* **Privacy downgrade is explicit.** The provider supports `exact → city →
  metro` downgrades with `suppressed` / `precision_reduced` section states —
  never a silent coarsening, and never a claim of differential privacy.
* Every claim carries a reused `EvidenceRef` (`requiresEvidence: true`); tenant
  scope is server-authoritative end to end.

### Canonical sources (read-only)

| Section | Canonical source read |
|---|---|
| `summary` | subject's geo posture: primary location(s) + roles, precision ladder reached, jurisdiction, effective temporal mode, freshness |
| `state` | typed `SectionState` per geo dimension — `available`/`missing`/`degraded`/`unknown`/`not_applicable`; an unobserved subject is `unknown`, never `0` |
| `timeline` | the subject's location/edge history — where known at valid time, from which observation/evidence |
| `evidence` | the reused `EvidenceRef`s grounding every location claim |
| `findings` | derived findings — precision downgrades, jurisdiction conflicts, stale/contradictory geo evidence — with evidence |

Every read is defensive: unavailable backing sources degrade their section,
never crash, never fabricate, never leak exception detail. `requiresDimensionState`,
`requiresFreshness`, `requiresLimitations` are honored.

### Dependency story (profile360 + temporal360)

`geographic360` declares `projectionDependencies: [profile360, temporal360]` and
`hardDependencies: [temporal_kernel, context_capsule_semantics]`. Sibling rows
compute as `missing` at the registry level while `in_flight`, and the provider
**degrades honestly** and never fabricates a dependency it does not have:

* `temporal360` has landed (Phase 2, now `implemented`), so its
  `dependencyState` is no longer `missing`. geographic360's own
  `supportedTemporalModes` stay `[window, compare, relative]` (no `as_of`): the
  WHERE leaf renders a location-history window over canonical location facts with
  valid-time provenance and deliberately does **not** perform knowledge-time
  reconstruction (that belongs to the `temporal360` dep, which only projections
  declaring `as_of`/`known_then` modes consume).
* `profile360` remains `in_flight`, so region/jurisdiction interpretation over
  profile provenance degrades to a typed `missing` state until canonical profile
  facts exist — it lifts when `profile360` lands and is never fabricated
  meanwhile.
* `context_capsule_semantics` — the authority this row resolves — ships in G4.5
  at `services/geographic360/capsule_semantics.py`: the pure rule set mapping one
  privacy-shaped capsule `LocationObservation` to a canonical geographic reading
  (the write-side `capsule_location_fact` builder plus the read-boundary guard
  `normalise_capsule_fact_row`, applied by the provider's reader seam to every
  capsule-provenance row). At the flip the row's `pendingAuthority` is emptied
  and `context_capsule_semantics` is formalized into the validator `SPINE_INDEX`,
  so the now-zero-pending row's `hardDependency` still resolves — the designed
  spine-formalization step (mirroring `grouping_membership` at P3.5), not a
  validator weakening.

### No redefinition

The slice reuses canonical `EntityRef`, `GraphSnapshotRef`, `PageRequest`,
`TimeRangeFilter`, and `EvidenceRef`; `shared/temporal/` remains the sole
temporal authority for when a location fact was true/known. It declares **no
second** geography registry, evidence model, or temporal kernel.

## What it means for the graph

Geographic360 is a **pure read** over canonical location facts and graph edges.
Its coordinates never leak into context capsules, so the no-raw-geo invariant
holds; its location facts are first-class, evidence-carrying records the graph
already owns; and its H3 cells are stored strings, rebuildable at any time — no
materialized spatial index becomes canonical. Because precision is a first-class
state (`suppressed`/`precision_reduced` are typed, never silent), a geographic
answer can be downgraded for a surface or a tenant without rewriting truth.
`risk360`'s geographic dimension and `population360`'s regional cohorts consume
this same vocabulary — a second geo registry is forbidden once this lands.

## Definition of Done

This slice follows the canonical vertical-slice checklist —
[docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../../docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md)
(registry row zero-pending + converged, shared-contract conformance, runtime
provider, evidence, tenant isolation, `read_only` graph policy, targeted tests,
source-linked review, and `make ci-check` green). The `implemented` flip is
gated on the prerequisites having **shipped**: the location registry + `shared/geo`
models (G4.1), the graph edge vocabulary (G4.2), a vault-backed
`GeocodingProvider` (G4.3), the provider + surface-capability block (G4.4), and
— in G4.5 — the canonical `location_facts` store, the `context_capsule_semantics`
authority, and the `DSR_COMPONENT` closing the location-facts erasure gap.
Flipping to `implemented` makes **no** `production_ready` claim.

## Test surface

* Registry/contract tests — `location-registry.json` fails closed on an unknown
  region-type / duplicate / non-lower-snake id; `LocationFact` carries role +
  precision + coordinates with provenance; `extra="forbid"`; no redefinition.
* Privacy tests — the context-capsule no-raw-IP / no-lat-lon parity test stays
  green; `exact → city → metro` downgrade yields `precision_reduced`/`suppressed`,
  never a silent coarsening; no differential-privacy claim.
* Graph tests — the new `EdgeType` is classified in `relationship_layers`;
  location edges carry `EvidenceRef`s; unclassified edges error as expected.
* Provider tests — valid `ProjectionResult`; precision never exceeds evidence;
  missing geo authority degrades (`missing`/`degraded`), never raises; tenant
  isolation; registration (success / duplicate / version-mismatch / unknown id).
* Surface tests — `geographic360` present in `surface-capability-registry.json`
  and routable on `/v1/explore/query` once the surface block lands.
