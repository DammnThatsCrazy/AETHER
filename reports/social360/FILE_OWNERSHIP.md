# Social360 + Relationship Fidelity — FILE OWNERSHIP (authority map)

Milestone M0 deliverable (blueprint §4 ownership matrix + §139 authority map).
Columns: capability → canonical owner today → owning path → this program's relation
(NEW = create, EXTEND = modify, CONSUME = read/use, NO_TOUCH = must not own).

## Domain ownership matrix (blueprint §4, grounded)

| Capability | Canonical owner today | Owning path (repo-root-relative) | Program relation |
|---|---|---|---|
| Provider auth/sync/webhooks | UPR | `Backend Architecture/aether-backend/services/provider_runtime/` | CONSUME + EXTEND (social capabilities) |
| Provider credentials | Credential Authority | `services/provider_runtime/credential_broker.py`, `shared/providers/credential_cipher.py` | CONSUME |
| Public/licensed rights | Data Rights | Data-rights authority (per docs/source-of-truth/OLYMPUS_PROVIDER_SOURCE_CATALOG.md) | CONSUME/ENFORCE |
| Tenant consent | Consent Registry | `packages/shared/contracts/consent-registry.json` | CONSUME |
| Raw provider evidence | Bronze/UPR | `services/provider_runtime/raw_store.py` | CONSUME |
| Social account/profile facts | **NEW — Social360** | planned `services/social360/` + silver contracts | NEW |
| Social connection facts | **NEW — Social360** | planned `services/social360/` | NEW |
| Social interactions/content | **NEW — Social360** | planned `services/social360/` | NEW |
| Email/DM semantics | Communication360 | `services/comms/` | CONSUME (reference, no duplicate store) |
| Campaign/reward program | Campaign360 | `services/campaign/` | CONSUME |
| Economic transfer/reward/value | Economic360 | `services/economic/` | CONSUME |
| Entity/account identity | Identity Spine | `services/identity/`, `services/resolution/` | CONSUME |
| Cross-domain relationship | Relationship360 | **NEW** — projection registry entry `relationship360`; planned `services/relationship360/` provider + assertions | NEW |
| Relationship promotion | Relational Spine | **NEW** spine concern (planned shared/service relationship-spine modules) | NEW |
| Relationship fidelity | Spine + Computation Substrate | **NEW** — reserve `relationship_fidelity` spine key; defs in `shared/computation/registry.py` | NEW |
| Semantic topic/stance/narrative | Semantic Intelligence | `services/semantic_intelligence/` | CONSUME |
| Narrative cascade | Narrative/Cascade reducers | `services/semantic_intelligence/reducers.py` | EXTEND (feed Social evidence in; NO second reducer) |
| Fraud/coordination risk | Fraud/Risk360 | risk domain (projection `graph_motifs` authority) | EMIT indicators only |
| Temporal truth | Temporal Spine | `shared/temporal/` | CONSUME |
| Graph mutations | Graph Mutation Gateway | `shared/graph/mutation_gateway.py`, `mutation_intents.py`, `write_validator.py` | CONSUME (sole write path) |
| 1–N hop traversal | Path Intelligence | `shared/graph/path_scoring.py`, `traversal.py`, `operational_intelligence/models.py` | EXTEND |
| Lens query execution | Exploration Fabric | `services/exploration/`, `shared/exploration/`, `shared/projection_engine/` (branch-only) | CONSUME + EXTEND (register lenses/filters) |
| Findings/Investigations | Intelligence/Investigation | `services/investigation/` | CONSUME |
| NL explanation | Noesis | `services/noesis/` | CONSUME (read-only; add read-only intents) |
| Operator workflow | Kyber Intelligence OS | `services/kyber/`, `frontend/kyber/` | EXTEND |

## Contract/registry ownership (integrator-owned; no shared-file free-for-all)

| Registry/contract | Path | Owner |
|---|---|---|
| Relationship predicate registry | planned `packages/shared/contracts/relationship-predicate-registry.json` (+ twins) | Integrator |
| Social contracts (silver facts, IncentiveContext, FidelityVector, motifs) | planned `packages/shared/contracts/` additions | Integrator |
| Graph mutation registry | `packages/shared/contracts/graph-mutation-registry.json` | Integrator (no unchecked growth) |
| Intelligence projection registry | `packages/shared/contracts/intelligence-projection-registry.json` | Integrator (holds `social360`, `relationship360`, `relationship_fidelity`, `graph_motifs` authorities) |
| Lens + filter-field registry | `packages/shared/contracts/lens-registry.json` | Integrator |
| Metric/computation registry | `packages/shared/contracts/metric-registry.json` + `shared/computation/registry.py` | Integrator |
| Consent registry | `packages/shared/contracts/consent-registry.json` | Integrator (only add purpose if necessary) |
| Generated twins | `packages/shared/*.ts`, backend `shared/*/generated_*.py` | Generated — never hand-edited |
| Alembic migrations | `Backend Architecture/aether-backend/alembic/versions/` | Integrator |
| `main.py` + worker topology | `services/*`, `main.py` | Integrator |

## Legacy social truth ownership (see LEGACY_SOCIAL_TRUTH_MATRIX.md for classification)

- `services/social/` — legacy; classified per §117 in the matrix (expected MIGRATE/COMPAT/DEPRECATE).
- `Data Lake Architecture/schemas/gold_social_intelligence.py` — reuse or extend per §57 (no duplicate Gold where semantic/relationship Gold owns state).
- Profile360 social surfaces (`services/profile/`, `packages/shared/social-intelligence.ts`, Kyber/Aether frontends) — COMPATIBILITY_WRAPPER then live Social360 data.
