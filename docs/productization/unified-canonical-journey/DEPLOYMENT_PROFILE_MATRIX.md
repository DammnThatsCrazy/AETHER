---
title: Deployment Profile Matrix — Unified Canonical Journey
slug: productization/unified-canonical-journey/deployment-profile-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
since_version: "8.12.0"
status: stable
source_files:
  - Backend Architecture/aether-backend/alembic/versions/20260627_canonical_activity.py
  - Backend Architecture/aether-backend/services/measurement/engine/journey_compiler.py
  - Backend Architecture/aether-backend/services/measurement/repositories/activity_repo.py
  - Backend Architecture/aether-backend/services/measurement/repositories/journey_step_repo.py
last_synced_commit: "9461239"
---

# Deployment Profile Matrix — Unified Canonical Journey

## Migration

The canonical journey feature requires the `20260627_canonical_activity` Alembic migration.

```bash
cd "Backend Architecture/aether-backend"
alembic upgrade head
```

This migration creates:
- `canonical_activity` — unified cross-rail activity ledger
- `journey_steps` — first-class ordered step rows for each compiled journey version

And alters `journey_versions` to add `web3_activity_ids`, `agent_activity_ids`, `x402_activity_ids`, `step_count`.

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

The `SilverDispatcher` calls `project_and_emit()` on each projector after the migration is applied. This is the hook that writes silver fact rows into `canonical_activity`. No additional configuration is required; the dispatch happens inline on every Bronze event.

## Scaling Considerations

| Dimension | Limit | Notes |
|---|---|---|
| Steps per journey compile | 2 000 | Configurable via `_MAX_STEPS` in `journey_compiler.py` |
| Steps per API page | 200 | Hard cap via `_MAX_STEPS_PAGE` |
| `canonical_activity` rows | Unbounded | Partition by `occurred_at` recommended at >100M rows/tenant |
| Rebuild concurrency | Unbounded | Add a semaphore in `rebuild_affected_by_web3_status_change` at scale |

## Rollout Sequence

1. Deploy backend with migration (migration is additive — no existing data is modified)
2. Canonical activity backfill: run a one-time adapter pass over existing silver fact tables if historical journey coverage is required
3. Deploy Aether frontend (journey explorer page activated for all profiles)
4. Deploy Kyber frontend (compiler health panel visible to operators)
5. Chain indexer: configure `/v1/web3/status-change` webhook for reorg/finality events
