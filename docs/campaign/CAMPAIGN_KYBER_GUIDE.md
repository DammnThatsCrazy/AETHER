---
title: Campaign Intelligence — Kyber Operator Guide
slug: campaign/campaign-kyber-guide
section: kyber
visibility: I
audience: [ops]
source_files:
  - Backend Architecture/aether-backend/services/measurement/routes/kyber.py
  - frontend/kyber/src/pages/measurement/campaign-registry-health-page.tsx
last_synced_commit: 64f12e3
---

# Campaign Intelligence — Kyber Operator Guide

## Operator endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/kyber/measurement/campaign/fleet-health` | Fleet-wide resolution health |
| GET | `/v1/kyber/measurement/campaign/tenant/{tenant_id}` | Per-tenant drill-down |
| POST | `/v1/kyber/measurement/campaign/tenant/{tenant_id}/reprocess` | Trigger bounded reprocessing |
| GET | `/v1/kyber/measurement/campaign/audit` | Audit log of resolved reviews |

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
