---
title: Communications Intelligence — Release Readiness
slug: comms/comms-release-readiness
section: operations
visibility: I
audience: [operator, release-owner]
source_files:
  - Backend Architecture/aether-backend/config/settings.py
  - tests/integration/test_comms_golden_scenario.py
---

# Communications Intelligence — Release Readiness

## Feature flags (`config/settings.py::CommsConfig`)

| Flag | Default | Gates |
|---|---|---|
| `AETHER_COMMS_INGESTION_ENABLED` | true | Silver projection of comm events (Bronze always accepts) |
| `AETHER_COMMS_CAMPAIGN_PROJECTION_ENABLED` | true | Touchpoint fan-out for comm events |
| `AETHER_COMMS_JOURNEYS_ENABLED` | true | Journey inclusion of comm activities |
| `AETHER_COMMS_GRAPH_ENABLED` | true | Aggregated relationship emission |
| `AETHER_COMMS_PROFILE360_ENABLED` | true | Profile360 comms surfaces |
| `AETHER_COMMS_CAMPAIGN360_ENABLED` | true | Campaign 360 Messages surfaces |
| `AETHER_COMMS_NOESIS_ENABLED` | true | `communications_insight` intent |
| `AETHER_COMMS_OPENS_VIEW_THROUGH` | false | Reported opens as low-confidence view-through |
| `AETHER_COMMS_REPLIES_ELIGIBLE` | true | Replies as attribution-eligible touchpoints |

## Rollout sequence

1. Local/dev — `make test` + golden fixture green.
2. Internal tenant — enable ingestion only; verify Kyber comms health card.
3. Test provider — Klaviyo sandbox webhook + 30d backfill
   (`docs/comms/COMMS_BACKFILL_RUNBOOK.md`); reconcile provider counts vs
   `/v1/campaigns/{id}/comms-funnel`.
4. One pilot tenant — enable campaign projection + journeys + profile360.
5. Limited beta — enable graph + campaign360 + noesis.
6. GA.

## Release gates

- `tests/integration/test_comms_golden_scenario.py` (permanent CI fixture —
  machine-open exclusion, one-fact/one-touchpoint/one-activity, replay
  safety, funnel reconciliation, bounded graph, cross-tenant token
  rejection, health reporting) must pass.
- `tests/unit/comms/` (contracts, dispatcher, projector, state, click token,
  mailbox, replies, Klaviyo, graph, attribution policy) must pass.
- `make repo-doctor` and `python scripts/generate_contracts.py --check` green.
- Migration `20260703_comms_intel` applied with verified `downgrade()`.

## Rollback plan

| Failure | Action |
|---|---|
| Bad projections | `AETHER_COMMS_INGESTION_ENABLED=false`, fix, replay Bronze range |
| Graph pressure | `AETHER_COMMS_GRAPH_ENABLED=false` (facts unaffected) |
| Provider flood | Disable connector; webhook inbox retains raw payloads |
| Schema issue | `alembic downgrade 20260702_fraud_decisions` (additive-only drop) |
| Attribution dispute | Toggle `AETHER_COMMS_REPLIES_ELIGIBLE` / `AETHER_COMMS_OPENS_VIEW_THROUGH`; rerun attribution |

## Known limitations (initial version)

- Klaviyo pull requires credentials in a non-local environment
  (`CREDENTIAL_GATED`); local mode exercises webhook parsing only.
- Cross-channel initiative rollups have schema + registry support but no
  dedicated frontend surface yet.
- Coalesced journey-rebuild batching uses the existing per-touchpoint
  trigger; a debounced batch queue is deferred (non-blocking).
- Reply intent classification (positive/negative/scheduling) is deferred;
  deterministic automated-response detection ships now.
