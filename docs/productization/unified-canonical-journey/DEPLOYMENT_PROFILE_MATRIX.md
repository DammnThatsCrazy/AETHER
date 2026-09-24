---
title: Deployment Profile Matrix — Unified Canonical Journey
slug: productization/unified-canonical-journey/deployment-profile-matrix
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/backend/alembic/versions/20260627_canonical_activity.py, services/backend/alembic/versions/20260725_ai_referral_attribution.py, services/backend/services/measurement/engine/journey_compiler.py, services/backend/services/measurement/repositories/activity_repo.py, services/backend/services/measurement/repositories/journey_step_repo.py]
source_hashes:
  "services/backend/alembic/versions/20260627_canonical_activity.py": "sha256:aa34efcf5f337e4430e6727001ee26ca8d657b5d6be9ca7de85b7f151ee668d8"
  "services/backend/alembic/versions/20260725_ai_referral_attribution.py": "sha256:09bcc2502136159d1b50a74181c1d06a7eed30c57ffc9c15da6e900776196189"
  "services/backend/services/measurement/engine/journey_compiler.py": "sha256:53c760d1ef1a8c9efdd63665039287f033904f4c29e665341ffc6e5efdd40b4e"
  "services/backend/services/measurement/repositories/activity_repo.py": "sha256:75a46456fbefd67ec09373624857402b240879dc5400eeb1d64b4bf7555bf738"
  "services/backend/services/measurement/repositories/journey_step_repo.py": "sha256:b5ded116782e70397b8e3009c15ec8cd30490ecdf52bd7c580f0a81806804ec6"
---

# Deployment Profile Matrix — Unified Canonical Journey

## Migration

The canonical journey feature requires the `20260627_canonical_activity`
migration. AI/referral source evidence and replay-safe attribution additionally
require `20260725_ai_referral_attribution`. Canonical-envelope surface
attribution (the `canonical_activity.surface` column + partial index) requires
`20260733_canonical_activity_surface`.

```bash
cd "services/backend"
alembic upgrade head
```

This migration creates:
- `canonical_activity` — unified cross-rail activity ledger
- `journey_steps` — first-class ordered step rows for each compiled journey version

And alters `journey_versions` to add `web3_activity_ids`, `agent_activity_ids`, `x402_activity_ids`, `step_count`.

The AI/referral migration adds source evidence and eligibility columns to
touchpoints, canonical activity, journey steps, credits, and runs; durable
classification revisions and repair jobs; typed journey lineage support; and
the unique-active-run constraint used by atomic attribution completion.

## Environment Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| PostgreSQL | 14+ | For `gen_random_uuid()`, partial indexes, JSONB |
| Python | 3.11+ | `asyncio`, walrus operator, structural pattern matching |
| Node.js | 20+ | Aether/Kyber frontend build |
| `@tanstack/react-virtual` | 3.10+ | Virtualized timeline in Aether UI |

## In-Memory Fallback Behavior

Both `ActivityRepository` and `JourneyStepRepository` fall back to an in-memory dict store when no database pool is provided. This is intended for unit testing and local development only.

**In staging and production:** the database pool must be configured. Missing configuration produces `not_provisioned` quality status on journeys — it does not silently report success.

## Feature Flag Dependencies

None. The journey compiler v2.0 is always active once the migration is applied. The previous touchpoint-only path is superseded; rollback requires reverting to a prior release tag.

## Ingestion Wiring

The `SilverDispatcher` runs an ordered projector list per event type (multi-projector fan-out, ADR-C3) and calls `project_and_emit()` on each. It is attached to `SDK_EVENTS_VALIDATED` via the `silver_fact_projector` ingestion worker; rows are persisted by `services/backend/services/silver/writer.py`, and canonical activity emission is owned by exactly one projector per event (ADR-C4). No additional configuration is required.

## Scaling Considerations

| Dimension | Limit | Notes |
|---|---|---|
| Steps per journey compile | 2 000 | Configurable via `_MAX_STEPS` in `journey_compiler.py` |
| Steps per API page | 200 | Hard cap via `_MAX_STEPS_PAGE` |
| `canonical_activity` rows | Unbounded | Partition by `occurred_at` recommended at >100M rows/tenant |
| Rebuild concurrency | Unbounded | Add a semaphore in `rebuild_affected_by_web3_status_change` at scale |
| Source repair batch | Operator-selected | Monitor repair progress and attribution recompute load per tenant |

## Rollout Sequence

1. Deploy backend with both migrations (the schema changes are additive)
2. Canonical activity backfill: run a one-time adapter pass over existing silver fact tables if historical journey coverage is required
3. Use Kyber source-classification health to assess unclassified or old-version touchpoints; run tenant-scoped repair before treating the new dimensions as complete
4. Deploy Aether frontend (journey explorer page activated for all profiles)
5. Deploy Kyber frontend (compiler and source-classification health panels visible to operators)
6. Chain indexer: configure `/v1/web3/status-change` webhook for reorg/finality events
