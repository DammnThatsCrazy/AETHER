# Social360 + Relationship Fidelity — OPEN PR COLLISIONS + REGISTRY AUTHORITY

Milestone M0 deliverable (blueprint §2 rules 2–4, §139 "open PR collisions"). Recorded 2026-09-03.
Re-verified 2026-09-03 (M1 open, session reconcile): **no change** to the 2-open-PR picture;
origin/main advanced from `6a11394f` → `e288320f` **via staging PRs #591/#592 only** (IAM staging
contracts; no surface overlap with the five §2 collision surfaces). No new collisions introduced.

## 1. Open PR inventory (complete)

Method: `gh pr list --state open`. Only **2 open PRs exist**, both targeting `main`.
Neither targets the program base lane (`feat/aether-360-program`, itself unmerged). All head SHAs recorded.

| PR | Title | Base | Head branch | Head SHA | Listed-surface overlap |
|---|---|---|---|---|---|
| **584** | Complete IRRL rights authority and verification spine | `main` | `codex/irrl-completion` | `b1a2ee527ee506c595c2c24d991d7ba255ed69bf` | **HIGH** — migrations, graph, semantic reducers, exploration |
| **586** | feat(identity): harden verification — real OIDC verify, atomic consume, rate limiting (DRAFT) | `main` | `claude/aether-identity-assurance-2b143i` | `b551e0c566d3cd154008c030a2706f2cb445f158` | NONE on listed surfaces (identity/events only) |

## 2. Collision detail

### PR 584 — IRRL rights authority + verification spine (PRIMARY collision)
Touches ~120 files across four surfaces this program consumes/extends:
- **Graph mutation spine**: `shared/graph/mutation_gateway.py` (+110), new `shared/graph/mutation_helpers.py`, `mutation_intents.py`, `mutation_models.py`, `shared/graph/graph.py`, `repositories/graph_mutation_ledger.py` — this is the **sole graph write path** M6/M8 must extend (§52).
- **Semantic reducers**: `services/semantic_intelligence/` broadly (`reducers.py`, `engine.py`, `models.py`, `consumer.py`, `service.py`, `repositories/base_fact_repo.py`) — the reducer this program must EXTEND, never fork (§83).
- **Exploration**: `services/exploration/routes.py`, `service.py`, `shared/exploration/models.py` — the M9 lens/filter surface.
- **Migrations**: 6 new `alembic/versions/*` files (integrator-owned surface).
- **Adjacent new modules**: large `shared/rights_authority/` service, `services/olympus/`, `services/ingestion/`, `services/lake/`, `services/profile/`, `services/kyber/access/` + `kyber/graph/scoped_gateway.py`. The `rights_authority`/`services/olympus` work is **directly relevant** to this program's §14 Olympus-corpus→tenant projection rule.
- **NOT touched**: `provider_runtime/`, `shared/providers/`, `services/providers/`, `shared/computation/`, `services/computation/`, `frontend/*`, `packages/shared/contracts/*`.

Disposition: **coordinate-before-merge.** PR 584 targets `main`; this program's base lane does not contain it, so conflicts materialize at merge-to-main time, not today. Recorded here per §2 rule 4. Because 584 owns large swaths of the rights/olympus/ingestion substrate, M0 does **not** rely on it, but the §14 rule resolution and any later graph/semantic/exploration edits on this branch must be reconciled against it before either merges.

### PR 586 — identity hardening (LOW, watch-only)
No file overlap. It changes identity verification/consume semantics in `services/identity/*`, which the social plane binds against (CONSUME). Watch-only; no disposition change. (Note: prior lane guidance to "ignore #584 + concurrent merges" applied to the p0-spine lane; recorded here neutrally for THIS program's ledger.)

## 3. Branch-lane context (approximate — NOT open PRs)

From `git log --all`, not `gh`:
- `feat/aether-360-program` — this program's base lane (cut @ `fced2960`; S1–S6 360 foundation,
  unmerged). `feat/financial-normalization` (W1–W5) descends from it — out of scope for this program.
- `feat/spine-p0` — actively formalizing a canonical "spine registry" + `SPINE_INDEX` conformance surface — touches the exact `relationship_fidelity`/spine-key territory this program claims.
- `feat/context-intelligence-360`, `feat/risk-fraud-360`, `feat/aether-p0-spine-architecture` — other 360-program lanes that may touch shared registries. Watch; none open (`feat/aether-360-program` is the base lane above).

## 4. Registry authority map (source: packages/shared/contracts/intelligence-projection-registry.json)

### Projection records relevant to this program

| id | projectionKind | implementationState | graphMutationPolicy | hardDependencies | canonicalAuthorities |
|---|---|---|---|---|---|
| `relationship360` | `relationship_360` | `in_flight` | `read_only` | **`relationship_fidelity`**, `identity_resolution`, `temporal_kernel` | `relationship_facts, graph, identity, evidence, temporal` |
| `social360` | `relationship_360` | `in_flight` | `read_only` | **`upr`**, **`relationship_fidelity`**, `temporal_kernel` | `social_observations, source_facts, relationship_facts, evidence, graph` |
| `communication360` | `sequence_360` | `in_flight` | `read_only` | `contract_spine`, `temporal_kernel` | `communication_facts, campaign_touchpoints, entities, outcomes, evidence` |
| `episode360` | `sequence_360` | `in_flight` | `read_only` | `contract_spine`, `temporal_kernel`, `journey_continuity` | `events, journeys, episode_facts, graph, evidence, temporal` |
| `profile360` | `entity_360` | `in_flight` | `read_only` | `contract_spine, identity_resolution, evidence_provenance, temporal_kernel` | `identity, entity_registry, graph, evidence, temporal, observations` |
| `economic360` | `measurement_360` | **`implemented`** | `read_only` | `measurement_outcome_contract, temporal_kernel` | `economic_facts, currency_value_normalization, payments, commerce, graph, outcome_facts` |

- All six: `ownsCanonicalTruth: false`; `economic360` is the ONLY `implemented` one (this program's implementation precedent).
- Section-state vocab is top-level `sectionStates`: `available, empty, missing, degraded, not_applicable, unknown, suppressed, stale`. `graphMutationPolicies`: `read_only | canonical_gateway_only`.
- Soft deps are expressed as `optionalProjectionDependencies` (no `softDependencies` key).

### Ownership of the two reserved tokens this program must respect

- **`relationship_fidelity`** = RESOLVED **spine key** (in `SPINE_INDEX` in `scripts/lib/intelligence_projection_validation.py`, not `AUTHORITY_INDEX`). Consumed as a hard dependency of `relationship360` + `social360`. No code exists. This program implements it as "Spine + Computation Substrate" (definitions planned in `shared/computation/registry.py`), matching the reservation.
- **`graph_motifs`** = canonical **authority token** (in `AUTHORITY_INDEX`), consumed as a `canonicalAuthorities` member of `fraud360`. Motif outputs from this program must be **indicators under the existing `graph_motifs` authority**, not a new claim engine (§42, §101).

### Lens + filter-field gaps (M9 inputs)

- `lens-registry.json`: 27 lenses; **`relationship` lens EXISTS** (overlay on `standard`, domain `relationship`, composes with relationship360). No `social`, `narrative`, `socialfi`, or `engagementfi` lens exists → M9 adds them.
- Filter fields live in **`packages/shared/contracts/filter-field-registry.json`** (separate file; 33 fields; categories `entity, time, geography, device, graph, risk, campaign, economic, truth`). **None** of the blueprint's §84 desired fields exist (`social.provider`, `relationship.family`, `incentive.status`, `source.scope`, `evidence.basis`, `path.type`); neither do their parent categories. Neighbors: `truth.evidence_basis`, `graph.relationship_layer`/`edge_type`/`edge_confidence`/`depth`, `campaign.source`. No `social.*`, `incentive.*`, `path.*` anywhere.

## 5. Provider shape the new projections must satisfy

`shared/intelligence_projections/provider.py` — `IntelligenceProjectionProvider` is a **`typing.Protocol`** (no base class, no write surface):

```python
class IntelligenceProjectionProvider(typing.Protocol):
    projection_id: str        # MUST be a registry id
    contract_version: str     # semver built against
    async def project(self, request: ProjectionRequest, context: ProjectionContext) -> ProjectionResult
```

Contract (per module): MUST NOT mutate canonical state; graph writes (when policy `canonical_gateway_only`) go through `GraphMutationGateway.apply(MutationIntent)`; raise only `ProjectionError` subclasses; pass explicit `[]` for `sections`/`claims`/`dependencyState`/`degradedReasons`. Registry `projection_registry = ProviderRegistry()` singleton gates on real id + major semver (`DuplicateProjection` on id collision) and fail-isolates providers to `DEGRADED`.

**Implication for M1/M10:** `social360` + `relationship360` must be implemented as `IntelligenceProjectionProvider`s (read-only projections over canonical silver/gold state), satisfying this protocol — the reserved registry entries unlock exactly this surface.
