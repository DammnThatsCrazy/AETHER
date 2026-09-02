---
title: Campaign Intelligence — Kyber Operator Guide
slug: campaign/campaign-kyber-guide
section: kyber
visibility: I
audience: [ops]
source_files:
  - Backend Architecture/aether-backend/services/measurement/routes/kyber.py
  - Backend Architecture/aether-backend/services/traffic/repair.py
  - frontend/kyber/src/pages/measurement/campaign-registry-health-page.tsx
  - frontend/kyber/src/pages/measurement/kyber-measurement-ops-page.tsx
last_synced_commit: "4e6fdad"
---

# Campaign Intelligence — Kyber Operator Guide

## Operator endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/kyber/measurement/campaign/fleet-health` | Fleet-wide resolution health |
| GET | `/v1/kyber/measurement/campaign/tenant/{tenant_id}` | Per-tenant drill-down |
| POST | `/v1/kyber/measurement/campaign/tenant/{tenant_id}/reprocess` | Trigger bounded reprocessing |
| GET | `/v1/kyber/measurement/campaign/audit` | Audit log of resolved reviews |
| GET | `/v1/kyber/measurement/source-classification/health` | Source classifier version, provider, mediation, and exclusion health |
| POST | `/v1/kyber/measurement/source-classification/reclassify` | Enqueue bounded source repair and downstream recomputation |

All endpoints require kyber operator authentication and are tenant-scoped.

## Fleet health dashboard

Navigate to **Kyber → Measurement → Campaign Registry Health** for:

- Spend mapping rate gauge (target: ≥90%)
- Touchpoint mapping rate gauge (target: ≥90%)
- Open review count
- Total and external campaign counts

## Tenant drill-down

Enter a tenant ID to view:

- Per-tenant mapping quality
- Open mapping reviews (up to 20 samples)
- Operator actions: Dry-run reprocess / Trigger reprocess

## Reprocessing

Reprocessing re-runs campaign resolution for a tenant's spend records (bounded by `limit`). The API endpoint runs the backfill inline as a background task and returns immediately with `"status": "running"`. Monitor `campaign_reprocess_completed_total` to confirm completion. Use dry-run first to estimate scope.

```bash
# Via API (bounded, runs in background — suitable for ≤5000 records):
curl -X POST /v1/kyber/measurement/campaign/tenant/{tenant_id}/reprocess \
  -H "Authorization: Bearer $KYBER_TOKEN" \
  -d '{"limit": 500, "dry_run": true}'
```

For large-scale reprocessing (>5000 records), use the backfill script directly:

```bash
python scripts/campaign/backfill_campaign_ids.py --tenant-id <ID> --batch-size 1000
```

## AI and agent source repair

Source repair is separate from campaign reprocessing: it corrects what a
touchpoint represents, then deliberately invokes the existing campaign,
journey, attribution, and measurement planes. Start with `dry_run: true` and a
bounded date range. A live run appends classification revisions, rebuilds the
affected profile or cluster journeys, recomputes canonical conversions, and
restates the affected Gold windows.

```json
{
  "start_date": "2026-07-01",
  "end_date": "2026-07-31",
  "dry_run": true,
  "limit": 10000,
  "request_id": "operator-change-2026-07-14-001"
}
```

Keep `request_id` stable when retrying the same operator action. Supply a new
value for an intentional rerun; otherwise the durable jobs platform returns the
existing idempotent job. The Kyber Measurement Operations page keeps the same
request ID after a failed submission, rotates it after a successful submission
or input change, and shows the returned job ID, request ID, and replay status.
Confirm the job timeline completes, then verify the classifier version
distribution and excluded machine-traffic count.

## Audit log

All resolved mapping reviews appear in the audit log with:

- Review ID, resolved campaign UUID, operator identity, timestamp, and note.

## Alert response runbooks

See `docs/campaign/runbooks/` for:

- `source-sync-failure.md` — connector credentials expired or platform API down
- `utm-ambiguity.md` — multiple UTM aliases pointing to different campaigns
- `stuck-backfill.md` — backfill not progressing
- `mapping-review-queue-high.md` — operator review queue backlog
- `unresolved-rate-spike.md` — sudden spike in unresolved resolution rate
