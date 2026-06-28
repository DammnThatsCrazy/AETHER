---
title: "Runbook: Clearing the Mapping Review Queue"
slug: campaign/runbooks/mapping-review-resolution
section: operations
visibility: I
audience: [ops]
---

# Runbook: Clearing the Mapping Review Queue

**Trigger:** `CampaignMappingReviewQueueHigh` alert fires (queue >500 open reviews), or a tenant contacts support about unresolved campaign evidence.

## What is a Mapping Review?

A Mapping Review item is created when the `CampaignResolver` cannot deterministically assign acquisition evidence to a canonical campaign UUID — either because no campaign matches (`unresolved`) or because multiple campaigns match with equal confidence (`ambiguous`). Each unique evidence fingerprint (SHA-256 of tenant + platform + UTM fields) creates at most one open review item.

## Diagnosis

1. **Inspect the queue**

   ```
   GET /v1/mapping-review?status=open&limit=50
   ```

   Look for patterns in `evidence.platform`, `evidence.utm_campaign`, `evidence.external_campaign_id`.

2. **Common patterns and causes**

   | Pattern | Cause | Fix |
   |---|---|---|
   | All same `platform` + `external_campaign_id` | Connector hasn't synced — campaign not yet in registry | Trigger source sync |
   | Many different `utm_campaign` values | No aliases registered for UTM values | Add `utm_campaign_alias` entries or resolve individually |
   | Candidates list length > 1 | Multiple campaigns share the same UTM alias | Expire stale aliases (see utm-ambiguity runbook) |
   | No evidence fields at all | SDK not forwarding acquisition evidence | Check SDK integration |

3. **Check if source sync would fix most reviews**

   If most open reviews have `evidence.platform` matching a connected source:
   ```
   POST /v1/campaign-sources/<source_id>/sync
   ```
   After sync, the `CampaignResolver` will auto-resolve matching reviews when the next touchpoint is processed.

## Resolution Options

**Option A — Bulk resolve via source sync** (most common)

Trigger connector sync. The resolver automatically closes matching reviews when new touchpoints come in.

**Option B — Resolve individually** (for small queues or one-off cases)

```
POST /v1/mapping-review/<review_id>/resolve
{ "campaign_id": "<canonical_uuid>", "note": "Manual resolution — matched to campaign by UTM pattern" }
```

Resolving a review creates a durable alias and triggers reprocessing of affected touchpoints.

**Option C — Ignore** (for spam/test traffic with no matching campaign)

```
POST /v1/mapping-review/<review_id>/ignore
```

Ignored reviews are hidden from the queue and do not count toward the `CampaignMappingReviewQueueHigh` threshold. They can be reopened if needed.

## Verification

- `campaign_mapping_review_open` gauge drops to near zero.
- `CampaignMappingReviewQueueHigh` alert auto-resolves.
- Campaign 360 shows previously-missing touchpoints attributed to their campaigns.

## Escalation

If the queue remains high after source sync and manual resolutions, check whether the tenant has campaigns that existed before the registry was deployed (pre-migration data). Run the backfill script for the tenant.
