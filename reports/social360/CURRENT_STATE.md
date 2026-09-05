# Social360 + Relationship Fidelity — CURRENT STATE

Recorded 2026-09-03 during Milestone M0. Describes Aether as it exists today on the program
base (`feat/social360-relationship-fidelity`, cut from `feat/aether-360-program`
@ `fced2960` — the S1–S6 360 foundation: three-360 vertical slices, exploration fabric,
projection engine). Purpose: the honest "before" picture the gap ledger (GAP_LEDGER.csv)
measures against.

Repo roots:
- Python monolith: `Backend Architecture/aether-backend/` — `services/` (one dir per domain),
  `shared/` (cross-domain library), `repositories/`, `alembic/versions/`, `config/`, `main.py`.
- TypeScript contracts: `packages/shared/` (hand-authored + generated twins of JSON registries).
- Frontends: `frontend/kyber/` (operator console), `frontend/aether/` (marketing/demo console).
- Legacy data-lake schemas: `Data Lake Architecture/schemas/gold_*.py`.
- Tooling/validators/generators: `scripts/`; canonical gates in `Makefile`.
- Program reports: `reports/` (many prior audit/readiness ledgers live here; this program
  owns `reports/social360/`).

## What already exists (blueprint's §1 inventory vs. today)

| Blueprint cites | Status today | Where |
|---|---|---|
| Canonical graph, H2H/H2A/A2H/A2A layers, mutation gateway | PRESENT on base | `Backend Architecture/aether-backend/shared/graph/` — `graph_contract.py`, `relationship_layers.py`, `edge_properties.py`, `write_validator.py`, `mutation_gateway.py`, `mutation_intents.py`, `generated_mutation_taxonomy.py`; ledger `repositories/graph_mutation_ledger.py` |
| 1–N hop / path intelligence (#357) | PRESENT | `shared/graph/path_scoring.py`, `traversal.py`; `RelationshipPath`/`PathExplanation` models in `services/operational_intelligence/models.py` |
| Canonical Computation Substrate (#508/#510) | PRESENT | `shared/computation/` (definition/registry/types/result/quality/uncertainty/temporal); service `services/computation/`; `metric-registry.json` in `packages/shared/contracts/` |
| Universal Provider Runtime (#520) | PRESENT | `services/provider_runtime/` (manifest, connection, raw_store, sync, credential_broker, normalizer, plugin, legacy bridge, certification, webhooks); contracts `shared/integration_contracts/`; concrete provider plugins are COMMERCE-only (`services/providers/{shopify,amazon,woocommerce,etsy,ebay,walmart,tiktok}/`) |
| Semantic/narrative/relationship/episode reducers (#470–#480) | PRESENT | `services/semantic_intelligence/` — `reducers.py` (weighted Silver→Gold), `graph_projector.py` (writes governed `SEMANTIC_RELATES_TO` via mutation gateway) |
| Identity spine + resolution | PRESENT | `services/identity/` (resolver, merge/split policy, source precedence, confidence, graph_writer/reconciliation), `services/resolution/` |
| Communications Intelligence (#387/#389/#512) | PRESENT | `services/comms/` (graph_projection with selective-message promotion, identity_bridge, classification, attribution policy) |
| Campaign / Economic / x402 / Geo / Temporal | PRESENT | `services/campaign/`, `services/economic/` (has the one fully-realized 360 provider: `economic360_provider.py`), `services/x402/`, `services/geo/`, `shared/temporal/` |
| Exploration Fabric (#458/#460/#496) | PRESENT (partially branch-only) | `services/exploration/`, `shared/exploration/`; LENS RUNTIME `shared/projection_engine/` is **not on origin/main** (branch-only on `feat/aether-360-program`) |
| Legacy social service | PRESENT (thin, pre-UPR) | `services/social/` (`routes.py`, `social_aggregator.py`) |
| `gold_social_intelligence` | PRESENT | `Data Lake Architecture/schemas/gold_social_intelligence.py` |
| Social Profile360 surfaces | PRESENT | `services/profile/composer.py`, `intelligence.py`, `routes.py`; TS `packages/shared/social-intelligence.ts`, `targeting-intelligence.ts` |
| Kyber operator plane / Noesis / Investigations | PRESENT | `services/kyber/` (+ `graph/`), `services/noesis/`, `services/investigation/` |
| Contract spine (JSON registry → py/ts twins) | PRESENT | `packages/shared/contracts/*.json` (~22 registries) + `scripts/generate_contracts.py`, `generate_platform_contracts.py`, `generate_computation_registry.py` |
| Repo-doctor / CI gates | PRESENT | `scripts/repo_doctor.py`, `Makefile` (`make ci-check` canonical) |

## What does NOT exist yet (the actual program gap)

1. **No `relationship360`, `social360`, `communication360` implementations.** All three are
   `projectionKinds` in `packages/shared/contracts/intelligence-projection-registry.json`,
   marked in-flight / not implemented, with no provider and no `docs/blueprints/*.md`.
2. **`relationship_fidelity`** exists only as a reserved spine key / hard dependency in the
   projection registry and `scripts/lib/intelligence_projection_validation.py` (SPINE_INDEX).
   No code module, no Computation-Definitions.
3. **No relationship predicate registry**, no Social silver-fact contracts
   (SocialIdentity/Connection/Interaction/Content/Community/Metric), no `IncentiveContext`,
   no motif registry/engine, no promotion state machine, no evidence-independence grouper.
4. **No social provider plugins on UPR** and no social capability vocabulary
   (`account_read`, `relationship_read`, …) registered. Legacy `services/social/` is the only
   social path and predates UPR.
5. **No Olympus-corpus→tenant-overlay projection rule** resolved for corpus-derived
   relationship writes (blueprint §14 P0 prerequisite). Tenant isolation exists in
   `shared/graph/graph.py` and `services/kyber/mirror/`, but corpus writes are deferred.
6. **No fidelity-aware path semantics** (hop contract enrichment, epistemic ceiling,
   path snapshot restatement).
7. **No SocialFi / EngagementFi / Narrative lenses** and no social/relationship/incentive
   filter fields in the exploration registry.

## Ownership notes / collisions already visible

- `graph_motifs` is a reserved canonical-authority token in the projection registry
  (relationship360/fraud360 scope) — a motif engine must integrate under that authority,
  not shadow it.
- `promotion` is an existing term in `services/comms/graph_projection.py`
  ("selective message promotion") — distinct meaning from relationship promotion; must be
  disambiguated in the predicate registry (§21) rather than overloaded.
- "unknown never 0" is an ACTIVE enforcement precedent on this base (enforced in
  `shared/dimension_state.py` + the profile/economic dimension-state path) — the social plane
  should inherit the same dimension-state discipline, not re-invent it.

Full file-by-file mapping: `FILE_OWNERSHIP.md`. Requirement-level gaps: `GAP_LEDGER.csv`.
