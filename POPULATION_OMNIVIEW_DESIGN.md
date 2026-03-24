# Population Omniview Design — Macro-to-Micro Intelligence

## Architecture

Population Omniview is a **composition and registry layer** that adds group-level intelligence on top of existing Aether subsystems.

```
MACRO (population-level)
├── /v1/population/summary         Total groups, trends, type distribution
├── /v1/population/groups          List all groups with filters
└── /v1/population/trends          Group creation and membership over time

MESO (group-level)
├── /v1/population/groups/{id}           Group details + definition
├── /v1/population/groups/{id}/members   Member list with confidence
├── /v1/population/groups/{id}/intelligence  Group feature summary
└── /v1/population/compare              Compare two groups (overlap, unique)

MICRO (entity-level)
├── /v1/population/entity/{id}/memberships    All groups for entity
└── /v1/population/entity/{id}/explain/{pop}  Why entity is in group

CROSS-LEVEL NAVIGATION
├── Macro → drill down to top groups → drill down to members → Profile 360
├── Profile 360 → /v1/population/entity/{id}/memberships → group context
└── Group → members → each member links to /v1/profile/{id}
```

## Data Model

| Model | Storage | Purpose |
|-------|---------|---------|
| `populations` table | BaseRepository (PostgreSQL) | Population objects with type, definition, metadata |
| `population_memberships` table | BaseRepository (PostgreSQL) | Entity-to-group links with basis, confidence, provenance |

## Group Types (PopulationType)

- `segment` — Rule-based, operator-defined
- `cohort` — Saved, scheduled, or dynamic
- `cluster` — ML-derived (similarity, behavior)
- `community` — Graph-derived (topology)
- `batch` — One-time analysis
- `archetype` — Behavior archetype label
- `anomaly` — Anomaly-detected group
- `lookalike` — Similar to a seed set
- `risk` — Risk-tier grouping
- `lifecycle` — Lifecycle stage group

## Membership Model

Every membership includes:
- `basis` — How membership was determined (rule, graph, ml_model, similarity, manual, inferred)
- `confidence` — 0.0 to 1.0
- `reason` — Human-readable explanation
- `source_tag` — Provenance tracking
- `joined_at` — When entity entered the group
- `status` — active/removed

## Privacy / Access

- All queries tenant-scoped via middleware auth
- Group visibility follows tenant permissions
- Member data respects existing consent/PII controls
- Financial data only included where policy permits
