---
title: Contextual 360 — Phased Implementation Program
slug: plans/contextual-360-phases
section: architecture
visibility: I
audience: [architect, dev-senior, ai]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Contextual 360 — Phased Implementation Program

This is the implementation program for the **Context Intelligence 360** family:
the three `context_360` intelligence projections that answer **WHEN**
(`temporal360`), **WHERE** (`geographic360`), and **WHO / WHAT SET**
(`population360`) as governed projections of canonical Aether graph state and
evidence.

The family rule — from the canonical Context Intelligence 360 blueprint and the
enforced `docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md` — is:

> **A contextual 360 is an intelligence projection over canonical Aether truth,
> never a competing system of record.** Demographics are a governed human
> Population360 lens (no `Demographic360` backend). Spatiotemporal analysis is
> composition of the three projections, not a fourth backend.

All three projections are **already registered** on the Intelligence Projection
Registry ([intelligence-projection-registry.json](../../packages/shared/contracts/intelligence-projection-registry.json))
with `projectionKind: "context_360"` and `implementationState: "in_flight"`,
each carrying a declared `pendingAuthority`. This program **converges** them
(`in_flight` → `implemented`) by resolving those authorities — it does not build
three new systems and it must not duplicate canonical authorities.

Completion of the program is gated by the repository's canonical gate
(`make ci-check`) and, per projection, by the 13-gate vertical-slice checklist
([INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md](../../docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md)).
The ownership category `intelligence_projection_architecture` in
`docs/source-of-truth/repo_consistency_ownership.json` lists the derived
surfaces and commands any registry/projection change must move.

## Governing authorities (extend, never duplicate)

| Authority | Where | What it owns |
| --- | --- | --- |
| Intelligence Projection plane | [INTELLIGENCE_PROJECTION_ARCHITECTURE.md](../../docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md) + `shared/intelligence_projections/` | The 19-row registry, `ProjectionResult`, `ProjectionSubject`, section states, provider protocol |
| Projection Engine | [PROJECTION_ENGINE_ARCHITECTURE.md](../../docs/source-of-truth/PROJECTION_ENGINE_ARCHITECTURE.md) + `shared/projection_engine/` | Lenses (`lens-registry.json`), composition algebra, `TemporalMode`, IR/planner/executor, typed degradation |
| Exploration Fabric | [EXPLORATION_FABRIC.md](../../docs/source-of-truth/EXPLORATION_FABRIC.md) + `shared/exploration/` | `ExplorationContextV1`, `FilterDisposition`, `ExplorationResultEnvelope`, surface capabilities |
| Temporal kernel | `shared/temporal/` (+ `packages/shared/temporal.ts`) | Instants, IANA zones, clocks, DST windows, bitemporal `TemporalEnvelope` — the only temporal parser/calendar authority |
| Context capsule / ingestion geo | [CONTEXT_INTELLIGENCE.md](../../docs/source-of-truth/CONTEXT_INTELLIGENCE.md) + `context-capsule-registry.json` + `services/ingestion/geo_provider.py` | Network-egress geo semantics, precision classes, retention; **source-linked** (drift-reviewed when its source files change) |
| Graph mutation authority | `shared/graph/mutation_gateway.py` + `repositories/graph_mutation_ledger.py` | Bitemporal close-and-append (`graph_fact_versions`), append-only ledger, idempotency, consent validation |
| Measurement / value | `shared/measurement/` + `services/value/` + `packages/shared/value.ts` | `MeasurementResult`/`ValueState`/`MetricDefinition`; money + FX provenance (no domain FX) |
| Identity/resolution | `services/identity/` | `IdentitySubject`, resolution/merge, canonical ids |
| Consent / DSR | `services/consent/` + `services/dsr_propagation/` | Fail-closed consent evaluation; the 26 `DSR_COMPONENTS` erasure propagation spine |
| Evidence | `EvidenceRef` (`services/operational_intelligence/models.py`) + `ProvenanceEnvelope` | Evidence references, provenance |

## 1. Vocabulary reconciliation (blueprint → repository)

The canonical Context Intelligence 360 blueprint's concepts already exist in the
repository under specific names. Implementation must use the repository names.

| Blueprint concept | Repository artifact |
| --- | --- |
| `ExplorationContext` | `ExplorationContextV1` (`shared/exploration/models.py`) |
| `ProjectionEnvelope` | `ProjectionResult` (`shared/intelligence_projections/contracts.py`) / `ExplorationResultEnvelope` |
| `SubjectRef` | `ProjectionSubject` — canonicalized in Phase 1 to a single exploration→projection join (`services/exploration/projection_subject.projection_subject_for`) shared by the surface adapter and the fabric's session composition; ad-hoc provider `{"kind","id"}` copies removed. Cross-plane seams (`ComputationContext.subject_type`/`subject_id`, `/v1/infrastructure/{subject_kind}/{subject_id}` path params, Noesis read kwargs) translate at their own edge and are deliberately not folded in |
| `LensDefinition` | `LensDescriptor`; overlay lenses `temporal` / `geographic` / `population` already registered |
| §8 result status | `SectionState` (`available/degraded/empty/missing/not_applicable/stale/suppressed/unknown`) + `ProjectionDegradation` |
| §9 filter disposition | `FilterDisposition` (`applied/translated/unsupported/suppressed/not_applicable`) — exact match |
| §17 query modes | `TemporalMode` (`LIVE/AS_OF/KNOWN_THEN/KNOWN_NOW/COMPARE/CORRECTION_DIFF/PLAYBACK/SIMULATION`) |
| §14–15 bitemporal truth | `TemporalEnvelope` + gateway bitemporal close-and-append |
| §87–93 metrics / money | `shared/measurement` + `services/value` + `packages/shared/value.ts` |

There is no "eight-plane / Plane 5" vocabulary in the repository; the planes are
the Intelligence Projection Plane, the Projection Engine, and the Exploration
Fabric.

## 2. Gap analysis

| Area | Repository state before this program | Gap to target |
| --- | --- | --- |
| Plane wiring | The three implemented providers (`economic360`/`outcome360`/`infrastructure360`) exist, but **no provider is registered on the global `projection_registry` after boot** — every `register_provider()` call site is test-only or into fresh registries; the `infrastructure360` router is never mounted in `main.py`; the Noesis adapter is never dispatched; exploration adapters default through `ProjectionExecutor` to the **empty global singleton**, so surfaces degrade to `provider_unavailable` | **Projection plane is not live** — a production registration seam must exist at app mount before any context_360 provider can serve data |
| Surface capabilities | `temporal360` / `geographic360` / `population360` have **no `SURFACE_CAPABILITIES` entry** (only `economic360`/`infrastructure360`/`outcome360` among the 360s); the exploration planner reports `surface_not_registered` for absent ids | Each context_360 provider needs a `surface-capability-registry.json` block + regeneration before it can be served on `/v1/explore/query` |
| Temporal — history/replay authority | Bitemporal close-and-append to `graph_fact_versions` + append-only ledger **exist**; valid-time as-of over the live graph **exists** (`temporal_bfs`, `/v1/graph/compare`, universal-query `as_of`); `replay_ledger`/`current_graph_digest` are **digest-only**; **system-time ("as known at knowledge time") reconstruction from `graph_fact_versions` is absent**; `KNOWN_THEN`/`KNOWN_NOW` are enum-only | `temporal360`'s declared `pendingAuthority: graph_history_replay` — a read-side authority that reconstructs knowledge-time state from the ledger (registry row already names `graph_snapshots, mutation_history, temporal_kernel, validity_state` as its authorities) |
| Population — governed membership | `populations`/`population_memberships`/`population_snapshots` are JSONB auto-created tables (no migration, unversioned); membership is **never written as a graph `MEMBER_OF` edge**, is **not consent-gated**, and is **not a DSR component**; graph edge properties support temporal provenance but not `membership_state`/`definition_version`/`evidence_refs` | `population360`'s `pendingAuthority: grouping_membership` — membership as a first-class governed graph fact (definition version, bitemporal, evidence, consent), with erasure coverage |
| Geographic — location primitive | Only coarse network-egress `GeoLookup`; `LocationObservation`/`ContextCapsule` deliberately carry **no lat/lon** (parity test `test_no_raw_ip_or_latlon_fields`); `/v1/geo` is a `not_provisioned` stub; **no** coordinate/place/region/jurisdiction primitive, no spatial index, no geo dependencies | `geographic360`'s `pendingAuthority: context_capsule_semantics` + a **single new canonical location primitive** (this is the program's only genuinely new canonical authority) — registry-driven, with coordinates living in the new contract, never back-filled into the context capsule |
| Erasure / recompute | `services/dsr_propagation/` has 26 components; none covers the population tables or a future location-fact table; no generic recompute engine (per-domain recompute: measurement `privacy.py`/`reattribution.py`/`journey_compiler.py`, `targeting_intelligence/recompute.py`) | Every new persisted artifact the trio introduces must register a DSR component; late-arrival/recompute follows the "resolve affected → supersede → idempotently recompute with truncation honesty" pattern |
| Docs | `docs/blueprints/{temporal360,geographic360,population360}.md` do not exist (only economic/outcome/infrastructure blueprints) | Per-projection blueprint authored by each phase |

## 3. Phase map

Phases are ordered so the plane is live before any context_360 provider lands,
and authorities resolve before the projections that consume them. Every phase
below is **NOT YET SHIPPED** unless its row says otherwise; the ledger in §6 is
updated as each phase lands.

| Phase | What ships | Entry criteria | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| **0** — Baseline, program scaffold, verification spike | This program ledger; branch `feat/context-intelligence-360` cut from the stacked lane; baseline `make ci-check` green; read-only verification spike (plane wiring, history/replay substrate, population→graph path, geo primitive/library decision) | Program scope approved (this doc) | Spike findings recorded (§5); baseline gate green; docs-only commit | IN PROGRESS — this doc + spike; final `make ci-check` pending |
| **1** — Plane live + shared foundation | Production registration seam wiring the implemented providers onto the global `projection_registry` at app mount (fixes the empty-singleton degrade for all implemented projections); `SubjectRef` canonicalization to `ProjectionSubject`; enforcement note in `INTELLIGENCE_PROJECTION_ARCHITECTURE.md` that a provider is not live until registered at mount | Phase 0 landed | Boot-time providers answer on `/v1/explore/query` with live data; one `SubjectRef` surface with no duplicated `subject_type`/`subject_id` shapes; contracts parity + gate green | SHIPPED 2026-09-03 — plane-live seam (registration seam + infra router mount + enforcement note; spike §5.1 resolved) landed first, then `SubjectRef` canonicalization: the exploration→projection join is now a single `projection_subject_for` helper shared by the projection-surface adapter and the fabric's session composition, with the providers' redundant subject re-derivations and ad-hoc `{"kind","id"}` summary copies removed. Pinned by `tests/unit/exploration/test_projection_subject_canonicalization.py` (one conversion surface; canonical `kind`/`id` only) + the existing surface/provider suites. Registry rows unchanged — all context_360 rows still `in_flight`. |
| **2** — `temporal360` (root of the cluster) | The `graph_history_replay` authority (system-time/knowledge-as-of reconstruction from `graph_fact_versions`, extending `services/operational_intelligence` + `shared/graph/traversal.py`; materialize `replay_ledger` beyond digest); `temporal360` provider + surface-capability entry + lenses; late-arrival recompute following the measurement pattern; `docs/blueprints/temporal360.md`; registry → `implemented` | Phase 1 landed | `temporal360` answers reality-vs-knowledge as-of via the exploration surface; 13-gate checklist passes; gate green | SHIPPED 2026-09-03 — T2.1–T2.4 landed (replay authority 1cf91b56, provider ec513f60, surface+adapter e31f9724, registry `implemented` + boot wiring e5330973); ledger rows 2026-09-03 (Phase 2 T2.1–T2.4) carry the detail |
| **3** — `population360` | Governed membership path: memberships written as graph membership edges through the mutation gateway with provenance (`definition_version`/`membership_state`/`evidence_refs` carried on the record/edge vocabulary), definition versioning (immutable), consent gating at membership compute/write, DSR components for the population tables; provider (snapshots/deltas/overlap/transitions/composition) + human **demographic lens** (no `Demographic360`); `docs/blueprints/population360.md`; registry → `implemented` | Phase 2 landed (temporal dep) | Memberships are governed graph facts with provenance + consent + erasure; population360 answers on the exploration surface; 13-gate checklist passes; gate green | SHIPPED 2026-09-03 — P3.1–P3.5 landed (governed `MEMBER_OF` membership 22778584 + tenant-scope c0877d47, definition versioning + consent 1d1f2476, DSR components 9fb7f9de, provider + demographic lens c77c69d7, surface+adapter bb8ec334, registry `implemented` + `grouping_membership` formalized 2c9bd0a2, docs close-out bef48b4c); ledger rows 2026-09-03 (Phase 3 P3.1–P3.5) carry the detail; **no `production_ready` claim** |
| **4** — `geographic360` | The **one new canonical location primitive**: `location-registry.json` + `shared/geo` + `services/geo` (LocationFact with roles/precision/coordinates; Place/Region/Jurisdiction; region-type hierarchy — not US-only), H3 client-side cells, geodesy via pure-python libs, `GeocodingProvider` behind the existing credential vault; graph edges with new `EdgeType` + `relationship_layers` entry; jurisdiction-vs-location and privacy downgrade (`exact→city→metro`) with `suppressed`/`precision_reduced`; provider lenses; DSR components; `docs/blueprints/geographic360.md`; registry → `implemented` | Phase 2 landed (temporal dep); location authority design reviewed | geographic360 answers on the exploration surface with precision never exceeding evidence; parity/gate green | NOT YET SHIPPED |
| **5** — Cross-cutting close-out | Cross-dimensional composition (temporal × geographic × population via the engine composition pattern); cross-360 monetary metrics consume canonical `value.ts`/FX only; full gates + docs regen; PR | Phases 2–4 landed | All three `implemented`; `make ci-check` green; `make release-gate` only if readiness is claimed | NOT YET SHIPPED |

> **Note on blueprints:** the per-360 vertical-slice blueprints
> (`docs/blueprints/{temporal360,geographic360,population360}.md`) are authored
> in the Phase-0 scaffold (they are this program's slice specs) and are
> *satisfied* — reviewed, not re-authored — inside each owning phase (§3.1).

### Implementation priority

- **Phase 1 before any provider** because no context_360 provider can serve live
  data until the projection plane is actually registered at app mount and its
  surface is capability-declared.
- **Temporal (Phase 2) before population/geo** because both `population360` and
  `geographic360` declare `temporal360` as a dependency and both need a governed
  way to attach valid/system time to the membership and location facts they
  introduce.
- **Population membership discipline (Phase 3) before geo breadth (Phase 4)**
  because membership-as-governed-graph-fact establishes the MEMBER_OF/provenance
  edge conventions and DSR-component pattern that geographic membership reuses.
- **Geographic (Phase 4) last** because it defines the program's only new
  canonical authority (the location primitive) and consumes the settled
  membership/edge/DSR conventions.

### Per-360 workstreams (sub-phases)

Each single phase row above expands into the ordered workstreams below, and each
workstream ships as its own reviewable commit. A phase is complete only when all
its workstreams are green **and** its vertical-slice blueprint (§3 note) is
satisfied. A workstream row is stamped **SHIPPED — <commit>** as it lands;
un-stamped rows remain **NOT YET SHIPPED**.

#### Phase 2 → `temporal360` (spec: [docs/blueprints/temporal360.md](../../docs/blueprints/temporal360.md))

| WS | What ships | Exit criteria | Status |
| --- | --- | --- | --- |
| T2.1 | `graph_history_replay` authority — read-side knowledge-time reconstruction from the ledger prefix + `graph_fact_versions` (extending `services/operational_intelligence` + `shared/graph/traversal.py`); `replay_ledger` beyond digest; digest-verifiable | Reconstruction at knowledge instant τ equals the ledger prefix closed at τ; `KNOWN_THEN` served; no write path | SHIPPED — 1cf91b56 |
| T2.2 | `temporal360` provider (leaf; `summary`/`state`/`timeline`/`evidence`/`findings`; surface modes `window`/`as_of`/`compare`/`relative`; `KNOWN_NOW` vs `KNOWN_THEN` correction diff) | Valid `ProjectionResult` on a fresh registry; modes requiring reconstruction degrade with a typed warning until T2.1 lands | SHIPPED — ec513f60 |
| T2.3 | Surface-capability block for `temporal360` (dedicated `temporal360` surface; sibling `timeline`/`temporal_observatory` stay with their owners) + regen; late-arrival recompute following the measurement pattern; DSR check on any new replay artifact | Surface routable on `/v1/explore/query`; recompute + erasure honest | SHIPPED — e31f9724 |
| T2.4 | Blueprint review; zero-pending (`graph_history_replay` resolved); source-linked docs stamped after review | 13-gate checklist passes; `make ci-check` green; row → `implemented` | SHIPPED — e5330973 |

#### Phase 3 → `population360` (spec: [docs/blueprints/population360.md](../../docs/blueprints/population360.md))

| WS | What ships | Exit criteria | Status |
| --- | --- | --- | --- |
| P3.1 | Governed membership: memberships written as graph `MEMBER_OF` edges through the mutation gateway with provenance (`definition_version`/`membership_state`/`evidence_refs` added to the record/edge vocabulary); migration replaces auto-create JSONB | Membership is a governed graph fact; no direct table-write path remains | SHIPPED — 22778584 (+ tenant-scope IDOR guard c0877d47) |
| P3.2 | Immutable definition versioning; consent/policy evaluation at membership compute/write (gateway parity) | A definition version cannot be silently redefined; writes pass consent | SHIPPED — 1d1f2476 |
| P3.3 | `DSR_COMPONENT` coverage for `populations`/memberships/snapshots in `services/dsr_propagation/` | Erasure of a member recomputes counts honestly; component count grows past 26 | SHIPPED — 9fb7f9de |
| P3.4 | `population360` provider (snapshots/deltas/overlap/transitions/composition) + human demographic lens (no `Demographic360`) | Provider answers on the exploration surface; lens reads canonical profile facts with configurable small-cell suppression | SHIPPED — c77c69d7 |
| P3.5 | Blueprint review; zero-pending (`grouping_membership` resolved); source-linked docs stamped after review | 13-gate checklist passes; `make ci-check` green; row → `implemented` | SHIPPED — 2c9bd0a2 (surface+adapter bb8ec334; docs close-out bef48b4c) |

#### Phase 4 → `geographic360` (spec: [docs/blueprints/geographic360.md](../../docs/blueprints/geographic360.md))

| WS | What ships | Exit criteria | Status |
| --- | --- | --- | --- |
| G4.1 | The one new canonical authority: `location-registry.json` + `shared/geo` models (`LocationFact` roles/precision/coordinates; `Place`/`Region`/`Jurisdiction`, region-type hierarchy not US-only) | Registry fails closed on unknown/duplicate/non-lower-snake ids; coordinates never back-filled into context capsules (parity green) | SHIPPED — b3e06071 |
| G4.2 | Graph vocabulary: new `EdgeType` + `relationship_layers` entry; `services/geo` surfacing; precision classes aligned to the `coarse_cell` taxonomy | Location edges classified + evidence-carrying; unclassified edges still error in staging/prod | SHIPPED — 0a028490 |
| G4.3 | H3 client-side cells (hierarchical, k-ring) + `geographiclib` geodesy + vault-backed `GeocodingProvider` | Spatial cells are client-computed strings; no PostGIS; keys live in the credential vault | SHIPPED — 14dc8ea7 |
| G4.4 | `geographic360` provider (`summary`/`state`/`timeline`/`evidence`/`findings`; `exact→city→metro` privacy downgrade) + surface-capability block (`geo`) + lenses | Provider + surface routable on `/v1/explore/query`; precision never exceeds evidence | NOT YET SHIPPED |
| G4.5 | `DSR_COMPONENT` for location facts; blueprint review; zero-pending (`context_capsule_semantics` resolved); source-linked docs stamped after review | 13-gate checklist passes; `make ci-check` green; row → `implemented` | NOT YET SHIPPED |

Within each phase the ordering is fixed: authority resolves before provider,
provider before surface, governance/erasure ships in the same phase as the
artifact it governs, and the blueprint is reviewed — never blindly stamped —
before the row flips.

## 4. Standing rules (blueprint constraints in repository terms)

1. **Typed states throughout.** Use `SectionState`, `ValueState`, and
   `ProjectionDegradation`. `unknown`, `suppressed`, `insufficient_data`, and
   `not_applicable` are distinct from `0`/`false`/`healthy`/`empty` — never
   convert one into another to make a UI render (PR #525 rule).
2. **Precision never exceeds evidence.** Output temporal/spatial precision must
   not exceed source/evidence precision without stating the derivation.
   `LocationObservation`/`ContextCapsule` keep their no-raw-IP / no-lat-lon
   invariant; coordinates live only in the new location contract.
3. **No silent filter failures.** Every requested dimension/filter returns a
   `FilterDisposition`; unsupported/suppressed are explicit, never silently
   dropped.
4. **One measurement system.** Every measure uses `shared/measurement`
   (`MeasurementResult`/`ValueState`/`MetricDefinition`). Never average
   averages; never sum regional distincts; percentiles recompute from
   sufficient distribution state. Monetary values consume `packages/shared/value.ts`
   / `Money` and FX provenance — no geography- or population-specific FX.
5. **Extend authorities, do not duplicate.** No second temporal parser
   (`shared/temporal/` is the sole authority), no second identity, evidence,
   metric, graph store, consent/DSR, or ingestion path, and **no second
   geography registry** once the location primitive is defined.
6. **Demographics are a lens, not a backend.** No `Demographic360`; no
   `Spatiotemporal360`. Demographic composition is a governed human Population360
   lens over canonical profile facts; small-cell suppression is configurable and
   is not marketed as differential privacy.
7. **Erasure is not a dead end.** Any persisted artifact a phase introduces
   (population memberships/snapshots, location facts) must be added as a
   `DSR_COMPONENT` in `services/dsr_propagation/` in the same phase.
8. **Consent is enforced where facts are written.** Membership and location
   writes must pass the same consent/policy evaluation the graph mutation
   gateway applies, not just a tenant `write` permission.

## 5. Phase-0 verification findings (spike)

Read-only verification performed 2026-09-03 against the projection-plane,
mutation-ledger, population, and geo surfaces. Definitive yes/no statements;
full citations live in the exploration transcripts.

### 5.1 Plane wiring — NO projection provider is live after boot

- `main.py` mounts a `ResourceRegistry` and a provider **gateway** registry, but
  never imports or populates `shared.intelligence_projections.registry.projection_registry`
  (the module singleton is created empty). The three implemented providers'
  `register_provider()` seams are invoked **only in tests** against fresh
  `ProviderRegistry()` instances.
- `services/infrastructure` is never imported/mounted in `main.py`, so the
  classified `/v1/infrastructure` route is not served either.
- Exploration adapters resolve providers via `ProjectionExecutor` → the global
  `projection_registry` singleton, so today every projection surface degrades to
  `provider_unavailable`. The Noesis adapter is never dispatched in production.
- **Load-bearing consequence:** Phase 1 must introduce the first production call
  site of `register_provider(projection_registry)`; the exploration adapters and
  capability keys need no change for the `/v1/explore/query` path (it is already
  classified and `read`-permissioned).

**Status — RESOLVED (Phase 1, 2026-09-03).** `main.py`'s `lifespan` startup now
calls `dependencies.projection_plane.register_implemented_projection_providers`
(`Backend Architecture/aether-backend/dependencies/projection_plane.py`) — the
first production call site of `register_provider(projection_registry)`. The
implemented trio (`economic360`/`outcome360`/`infrastructure360` =
`IMPLEMENTED_PROJECTION_IDS`) is live at boot, exactly once (guard-by-id —
idempotent across repeated boot entries); `services/infrastructure` is imported
and its classified router mounted in `create_app()`; and a live projection
surface composes through the exploration fabric instead of degrading to
`provider_unavailable` (pinned end-to-end by
`tests/unit/exploration/test_projection_plane_boot.py` and unit-pinned by
`Backend Architecture/aether-backend/tests/unit/test_projection_plane_boot_wiring.py`).
The enforcement rule this finding drives — a provider is not live until
registered at mount — is recorded in
`docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md` (§6).

### 5.2 Surface capability registry — trio absent

`shared/exploration/generated_surfaces.py` (from `surface-capability-registry.json`)
has rows for the fabric's registered surfaces (14, per the fabric source of
truth) — among the 360 projection family the only rows present correspond to the
implemented projection-backed adapters `economic360`, `infrastructure360`, and
`outcome360`. `temporal360`, `geographic360`, and `population360` are **absent**,
so the fabric cannot route them (absent id ⇒ planner `surface_not_registered`,
every submitted filter disposed `not_applicable`). Each provider phase must add
its surface-capability block and regenerate.

### 5.3 Temporal — history/replay substrate

- Bitemporal close-and-append into `graph_fact_versions`: **EXISTS**
  (`GraphMutationLedgerRepository.append`/`_pg_append`, transactional).
- Append-only ledger: **EXISTS** (`graph_mutation_ledger`, idempotent, ordered).
- `replay_ledger` / `current_graph_digest`: **digest-only** (sha256 parity), not
  state reconstruction.
- Valid-time as-of over the **live** graph: **EXISTS** (`temporal_bfs` in
  `shared/graph/traversal.py`, `POST /v1/graph/compare`, universal-query `as_of`).
- System-time ("as known at knowledge time") reconstruction from
  `graph_fact_versions`: **ABSENT** — `KNOWN_THEN`/`KNOWN_NOW` are enum-only in
  `shared/projection_engine/temporal_modes.py`. This is the authority Phase 2
  builds.
- Do-not-duplicate boundaries: `shared/temporal/` (kernel), `services/temporal_preferences/`
  (display prefs), `projection_engine/temporal_modes.py` (vocabulary) each own a
  distinct slice.

### 5.4 Population — membership is not a governed graph fact

- Tables: `populations`, `population_memberships`, `population_snapshots`
  (JSONB auto-create via `BaseRepository`; **no Alembic migration**; membership
  unversioned, idempotent update, hard delete).
- Membership is **never** written as a graph `MEMBER_OF` edge (no gateway
  reference in `services/population/`); only a `population_memberships` table row
  + an `ENTITY_MEMBERSHIP_ADDED` bus event. (`MEMBER_OF`/`MEMBER_OF_CLUSTER`
  edges are written by the `entities` and `cluster` services.)
- Edge provenance: temporal properties supported; **`membership_state`,
  `definition_version`, and `evidence_refs` are not** on the canonical edge
  property vocabulary.
- Consent: `services/population/` has zero consent/policy references — membership
  writes bypass the consent validation graph writes receive.
- DSR: **none of the 26 `DSR_COMPONENTS` covers the population tables** — an
  explicit erasure gap.

### 5.5 Geographic — decision inputs (adopt A/A/A/A)

- Canonical authorities already declared for `geographic360`:
  `context_capsules`, `geo_observations`, `locations`, `entity_graph`,
  `temporal`; surface `geo`; legacy binding `services/geo`; blueprint
  `docs/blueprints/geographic360.md` (not yet authored).
- No geo dependencies installed; graph backend is in-memory/Neptune (never
  PostGIS); Postgres is JSONB (`postgres:16-alpine`, no PostGIS). Spatial cells
  must therefore be computed **client-side**.
- **LocationFact home (A):** new `packages/shared/contracts/location-registry.json`
  + `Backend Architecture/aether-backend/shared/geo/models.py`, surfaced through
  `services/geo`. Coordinates must NOT be added to the context capsule (parity
  test forbids raw IP/lat-lon there).
- **Spatial index (A):** H3 (`h3-py`) client-side cell strings, hierarchical,
  aligning with the existing `coarse_cell`/`precisionClasses` taxonomy; k-ring for
  neighborhood/containment.
- **Geodesy (A):** `h3-py` cell math + `geographiclib` pure-python geodesic
  distance; heavier `pyproj`/`shapely` only if jurisdiction-boundary
  point-in-polygon is later required.
- **Geocoding (A):** a `GeocodingProvider` protocol beside `GeoProvider`, keys in
  the existing credential vault (`shared/credentials/interface.py` +
  `shared/providers/base.py`), MaxMind GeoLite2 local files remaining the
  air-gapped default.
- New location graph edges need a new `EdgeType` plus a `relationship_layers`
  entry (unclassified edges error in staging/prod).

## 6. Ledger

| Date | Phase | Result |
| --- | --- | --- |
| 2026-09-03 | Phase 0 (kickoff) | Reconciliation complete (blueprint → repository); branch `feat/context-intelligence-360` cut from the stacked lane (carries the projection plane + context_360 registry rows); this program ledger + §5 spike authored; verification spike confirmed the plane is not live, the trio lacks surface-capability entries, the knowledge-time replay authority is absent, population membership is not a governed/consented/DSR-covered graph fact, and the geographic primitive is genuinely new (decision A/A/A/A). Baseline `make ci-check` green pending; final `make ci-check` gate remains. |
| 2026-09-03 | Phase 0 (scaffold) | Per-360 workstream detail added (§3.1, T2.x/P3.x/G4.x) and the three vertical-slice blueprints `docs/blueprints/{temporal360,geographic360,population360}.md` authored on `feat/context-intelligence-360` rooted at `fced2960`; docs manifest regenerated. Program remains pre-implementation — phases 1–5 NOT YET SHIPPED. |
| 2026-09-03 | Phase 1 (plane-live seam) | First implementation step landed: `dependencies.projection_plane.register_implemented_projection_providers` wired into `main.py` `lifespan` (implemented trio live on the global `projection_registry` at boot, guard-by-id idempotent); `services/infrastructure` router mounted in `create_app()`; enforcement note added to `INTELLIGENCE_PROJECTION_ARCHITECTURE.md` (§6, §5) and spike §5.1 marked RESOLVED. Pinned by `test_projection_plane_boot_wiring.py` + `tests/unit/exploration/test_projection_plane_boot.py` (live surface composes, not `provider_unavailable`). Registry rows unchanged — all context_360 rows still `in_flight`. |
| 2026-09-03 | Phase 1 (SubjectRef canonicalization) | `SubjectRef` consolidation landed, closing the Phase-1 exit: new `services/exploration/projection_subject.projection_subject_for` is the ONE exploration→projection join; both the projection-surface adapter (`services/exploration/adapters/projection.py`) and the fabric's session composition (`services/exploration/service.py::_compose_projection`) now call it (their private `_subject_from_context` / `_VALID_SUBJECT_KINDS` / `_DEFAULT_SUBJECT_KIND` copies deleted); the economic360/outcome360 providers emit `request.subject.model_dump()` instead of hand-rolled `{"kind","id"}` summary copies, and economic360's claims reuse `request.subject` instead of re-deriving it. Cross-plane seams (computation `subject_type`/`subject_id`, REST/read `subject_kind`/`subject_id` params) intentionally untouched — they translate at their own edge. Pinned by `tests/unit/exploration/test_projection_subject_canonicalization.py` (behavior + single-conversion-surface identity + no-`subject_type`/`subject_id` on the plane). Targeted suites 336+6 pass; ruff clean. Registry rows unchanged — all context_360 rows still `in_flight`. Phase 1 exit gate (`make ci-check`) pending this commit's doc-sync. |
| 2026-09-03 | Phase 2 (T2.1 — replay authority) | `graph_history_replay` landed as the knowledge-time reconstruction authority: `shared/graph/mutation_gateway.py` gained `replay_state` (state-returning replay — `GraphReplayState` with vertices/edges/digest) so `replay_ledger` is the digest-only face of the same application path; `repositories/graph_mutation_ledger.py` gained `list_records_known_as_of` (knowledge-time-bounded prefix read, in-memory + PG); `services/temporal360/history_replay.py` ships `known_as_of`/`known_now`/`digest_known_as_of`/`subject_history`/`corrections_between` over live topology (a revoked edge stays in the canonical list flagged `revoked`, so revocation reads as removal). No write path. Pinned by `tests/unit/graph_gateway/test_graph_history_replay.py` (25 tests). Registry rows unchanged — all context_360 rows still `in_flight`. |
| 2026-09-03 | Phase 2 (T2.2 — temporal360 provider) | `services/temporal360/provider.py` ships the `temporal360` projection leaf (`summary`/`state`/`timeline`/`evidence`/`findings`): `LedgerTemporalReader` over `GraphHistoryReplay.subject_history`; `KNOWN_THEN` served at `request.timeRange.from_` for `as_of`, `KNOWN_NOW` for `window`/`relative`, `COMPARE` diffs; modes without a usable instant degrade with a typed warning and never relabel or raise; unknown subjects / empty bounded windows / not-applicable reconstruction stay distinct typed states; evidence-grounded `ClaimEnvelope`s reuse canonical `EvidenceRef`. `SubjectHistory.live_edges` (reconstruction-final liveness, never event presence) keeps `corrections_between` honest. Pinned by `tests/unit/test_temporal360_provider.py`. Registry rows unchanged — all context_360 rows still `in_flight`. |
| 2026-09-03 | Phase 2 (T2.3 — surface + recompute/erasure honesty) | temporal360 ships a dedicated `temporal360` surface-capability block (all four temporal modes; `timeline`/`table` views; entity/time/truth categories) + regen of the PY/TS/MD twins, and `Temporal360SurfaceAdapter` is registered on the exploration fabric — so `temporal360` is routable on `/v1/explore/query` without shadowing `timeline` (non-projection adapter) or `temporal_observatory` (owned by other work packages). Recompute + erasure honesty pinned at the authority: reconstruction persists nothing and rebuilds from the ledger prefix at read time (late-arrival rows with `recorded_at <= τ` are honoured idempotently; an erasure is a terminal tombstoned canonical state that never resurrects, while KNOWN_THEN before it stays the audit record). Surface pinned in `tests/unit/exploration/test_exploration_adapters.py`, `tests/contracts/test_surface_capability_parity.py`, `test_projection_surface_adapter.py`; recompute/erasure pinned in `tests/unit/graph_gateway/test_graph_history_replay.py`. Registry rows unchanged — all context_360 rows still `in_flight` (boot wiring + `implemented` flip are T2.4). |
| 2026-09-03 | Phase 2 (T2.4 — registry implemented + boot wiring) | temporal360 is the **first context_360 row to flip `in_flight` → `implemented`** (e5330973): the row's `pendingAuthority`/`pendingReference` are emptied — `graph_history_replay`, shipped in T2.1, is formalized into the validator `SPINE_INDEX` so the row's `hardDependency` resolves through the spine (the designed formalization step, not a weakening) — and `legacyBindings` are converged on the dedicated `temporal360` surface (`migrationMode: converged`, blueprint `docs/blueprints/temporal360.md`). PY/TS/MD generated twins regenerated (implemented + zero-pending). `dependencies/projection_plane.py` now registers temporal360 at app mount alongside the trio (guard-by-id idempotent); boot-wiring + registry-schema suites updated to the four-implemented set. Blueprint reviewed and updated to the resolved authority state (shipped source locations replace the design-time "extends operational_intelligence/traversal" pointer). Source-linked review done then stamped at e31f9724: `ARCHITECTURE.md` + `BACKEND-API.md` enumerate four implemented 360s; `INTELLIGENCE-GRAPH.md` bitemporal-replay section now documents the knowledge-time reconstruction nuance. Sibling context rows (`population360`, `geographic360`) stay `in_flight`. |
| 2026-09-03 | Phase 3 (P3.1 — governed membership) | `PopulationMembershipGovernor` (`services/population/governance.py`) makes population membership a governed graph fact: every join/leave is a directed `MEMBER_OF` edge (`entity -> population`) written through the canonical `GraphMutationGateway` — never a bare table write — carrying the membership-provenance keys added to `shared/graph/edge_properties.py::OPTIONAL_EDGE_PROPERTIES` (`membership_state`/`definition_version`/`membership_basis`/`population_type`/`evidence_refs`); the membership table row is the materialised current state the governed path maintains, and a leave is a state transition (soft-revoke `edge_expired`), never a hard delete. Population routes are tenant-scoped (IDOR guard c0877d47). Pinned by `tests/unit/population/test_population_governed_membership.py` + `test_population_routes_tenant_scope.py`. Registry rows unchanged — population360 still `in_flight`. |
| 2026-09-03 | Phase 3 (P3.2 — definition versioning + consent) | `services/population/registry.py` ships immutable population-definition versioning (`population_definition_versions`, append-only) and the membership write path gates through server-authoritative consent (`services.consent.authority.evaluate_consent`) under the population's declared consent purpose — fail-closed, never merely a tenant `write` permission; leaving is always honoured regardless of current grant state. Pinned by `tests/unit/population/test_population_definition_versioning.py` + `test_population_membership_consent.py`. Registry rows unchanged — population360 still `in_flight`. |
| 2026-09-03 | Phase 3 (P3.3 — DSR components) | `DSR_COMPONENTS` grows 26 → 29 with the population-plane components (`population_memberships`/`population_snapshots`/`populations`); `services/consent/erasure_jobs.py::_erase_population_plane` erases every active membership as a **governed leave** (`PopulationMembershipGovernor.remove_membership` — `MEMBER_OF` edge soft-revoked, row → `left`, never a hard delete) so the append-only ledgers stay intact, recomputes each affected population's `member_count`, and reports honest zero receipts for the aggregate components. Pinned by `tests/dsr/test_population_dsr_erasure.py`. Registry rows unchanged — population360 still `in_flight`. |
| 2026-09-03 | Phase 3 (P3.4 — provider + demographic lens) | `services/population360/provider.py` ships the population360 projection leaf (`summary`/`state`/`timeline`/`evidence`/`findings`) over the governed membership + immutable-definition registries, plus the human **demographic lens** reading canonical profile facts with configurable small-cell suppression (no `Demographic360`). Pinned by `tests/unit/test_population360_provider.py` + `tests/unit/test_population360_demographics.py`. Registry rows unchanged — population360 still `in_flight`. |
| 2026-09-03 | Phase 3 (P3.5 — registry implemented + boot wiring) | population360 is the **second context_360 row to flip `in_flight` → `implemented`** (2c9bd0a2; surface+adapter bb8ec334, docs close-out bef48b4c): a dedicated `population360` surface-capability block + `Population360SurfaceAdapter` ship first (16 surfaces; no-shadowing of `comparison_workbench`/`cluster360`); `legacyBindings` converge on the dedicated `population360` surface (`migrationMode: converged`, blueprint `docs/blueprints/population360.md`) and `pendingAuthority` is emptied — `grouping_membership`, shipped in P3.1, is formalized into the validator `SPINE_INDEX` (the designed formalization step, not a weakening). PY/TS/MD generated twins regenerated (implemented + zero-pending). `dependencies/projection_plane.py` registers population360 at app mount (five implemented, guard-by-id idempotent; `TYPE_CHECKING` forward-ref fix); boot-wiring + registry-schema suites updated to the five-implemented set; surface/adapter/parity/provider/DSR suites green (87). Blueprint reviewed to the resolved authority state (shipped source locations replace the design-time "pending authority"). Source-linked docs reviewed then stamped at 2c9bd0a2: `ARCHITECTURE.md`/`BACKEND-API.md` enumerate five implemented 360s; `INTELLIGENCE-GRAPH.md` gains the membership-governed-graph-fact mutation path + DSR governed-leave bullet; IPA/EXPLORATION_FABRIC updated to five slices / 16 surfaces. **No `production_ready` claim.** `geographic360` stays `in_flight`. |
| 2026-09-03 | Phase 4 (G4.1 — canonical location authority) | The **one new canonical authority** lands (b3e06071): `packages/shared/contracts/location-registry.json` (13 location roles, 8 region types — not US-only, precision ladder matching the context-capsule taxonomy, `wgs84`/`h3` vocabulary) + the platform-contract-generator wiring that emits the TS/PY/MD twins + the hand-authored `shared/geo` model surface (`LocationFact` with role/precision/coordinates/provenance; `Place`/`Region`/`Jurisdiction`) + the `packages/shared/index.ts` barrel export. Coordinates live only on location facts — never the context capsule (the no-raw-IP / no-lat-lon parity test stays green). Pinned by `tests/contracts/test_location_registry.py` (11) + capsule parity. Registry rows unchanged — `geographic360` still `in_flight`. |
| 2026-09-03 | Phase 4 (G4.2 — graph vocabulary + `services/geo` surface) | The location-fact graph vocabulary ships (0a028490): VertexTypes `PLACE`/`REGION`/`JURISDICTION` + EdgeTypes `LOCATED_AT` (subject → Region) / `OBSERVED_IN` (subject → Place) / `UNDER_JURISDICTION` (subject → Jurisdiction), each mapped to `RelationshipLayer.EXCLUDED` in `relationship_layers._EDGE_LAYER_MAP` (Python-only, mirroring `SEMANTIC_RELATES_TO` — unclassified edges still error in staging/prod, TS parity surface untouched). `services/geo/location_edges.py` is the ONE assembly surface (services/geo is the row's legacy binding): `validate_location_fact` fails closed on unknown role/region_type/precision_class/precision_state and on a `precise`/`coarse_cell` claim the fact's evidence cannot support (precision never exceeds evidence); `build_location_edge_intents` emits one typed, evidence-carrying edge per resolution target, each carrying the provenance keys now registered on `edge_properties.py::OPTIONAL_EDGE_PROPERTIES` (`location_role`/`precision_class`/`precision_state`/`region_type`/`coarse_cell`) + the fact's `EvidenceRef`s on edge and intent. Pure assembly — the governed write path (consent, vertex materialisation, soft-revoke leaves) and the projection read land in G4.4/G4.5. Pinned by `tests/graph/test_geographic360_graph_surface.py` (11) + the exhaustiveness/parity gates; full backend suite 7098 passed, 1 skipped. Registry rows unchanged — `geographic360` still `in_flight`. |
| 2026-09-03 | Phase 4 (G4.3 — spatial substrate) | The client-side spatial substrate the G4.2 vocabulary stores its `coarse_cell` strings against lands (14dc8ea7). `services/geo/spatial_cells.py` computes h3 (v4 API) `h3`-scheme string cells in-application — `coordinate_to_cell` at the canonical `coarse_cell` resolution (6), center/resolution, strict hierarchical `parent_cell`/`child_cells`, `k_ring` + exact `ring` neighbourhoods, and `contains_cell` hierarchical containment — every failure typed (`CellValidation`/`CoordinateDomain`/`Resolution` under `SpatialCellError`), never a raw h3 exception; cell centres re-index to their own cell (stable, rebuildable, no PostGIS / no spatial index). `services/geo/geodesy.py` gives pure-python WGS84 distance via `geographiclib` (`geodesic_distance_m`, `cell_centroid_distance_m`). `services/geo/geocoding.py` adds the vault-backed `GeocodingProvider` protocol beside the network-egress `GeoProvider`: `reverse` (coordinate → coarse region/place label + client-computed `coarse_cell`, never a coordinate echo) and `forward` (query → candidate labels); external geocoder keys resolve ONLY through `CredentialService.get` on a tenant-scoped `geo:{provider}` ref (`build_vault_geocoding_provider`) — never env/hardcode, key passed to the executor per call, repr masked; fail-closed to the honest `NullGeocodingProvider` when the credential is missing/revoked or no executor is wired, typed `provider_error`/`invalid_input` hits on executor failure / out-of-domain input, unknown region types normalized to `None` against `REGION_TYPES`. Dependencies `h3>=4.0` + `geographiclib>=2.0` declared in the `backend` optional group (services/geo imports them directly). Pinned by `tests/unit/test_geographic360_{spatial_cells,geodesy,geocoding}.py` (34); geo-surface suite stays green. Registry rows unchanged — `geographic360` still `in_flight`. |

When a phase lands, its row is updated here and the corresponding registry rows
move `in_flight` → `implemented` only after the vertical-slice checklist and
`make ci-check` pass. As of this ledger the implemented set is `economic360`,
`outcome360`, `infrastructure360`, and the two context-360 rows flipped so far —
`temporal360` (Phase 2) and `population360` (Phase 3). `geographic360` remains
`in_flight`. None of the trio was actually served live until the Phase-1
registration seam, and population360 was not routable on the exploration surface
until its P3.5 surface + adapter shipped.
