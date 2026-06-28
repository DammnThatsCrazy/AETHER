---
title: "Runbook: Remap Campaign and Recompute Attribution"
slug: campaign/runbooks/remap-and-recompute
section: operations
visibility: I
audience: [ops]
---

# Runbook: Remap Campaign and Recompute Attribution

**Trigger:** A tenant requests that historical touchpoints be remapped to a different canonical campaign (e.g. evidence was incorrectly attributed; a Mapping Review was resolved to the wrong campaign).

## When This Is Appropriate

- A Mapping Review was resolved to campaign A but should have been resolved to campaign B.
- A UTM alias was assigned to the wrong campaign and subsequently corrected.
- A connector imported spend under an incorrect external ref that was later fixed.

## Pre-Checks

1. Confirm the correct target `campaign_id` with the tenant.
2. Verify the target campaign exists and is owned by the tenant.
3. Estimate the scope (number of touchpoints, spend records) — use `--dry_run` first.

## Resolution Steps

1. **Fix the alias or external ref**

   If the error came from a wrong alias:
   ```sql
   -- Expire the incorrect alias
   UPDATE campaign_aliases
   SET valid_until = NOW()
   WHERE alias_id = '<wrong_alias_id>' AND tenant_id = '<tenant_id>';

   -- Add the correct alias
   INSERT INTO campaign_aliases (tenant_id, campaign_id, alias_type, alias_value, alias_value_normalized, created_by)
   VALUES ('<tenant_id>', '<correct_campaign_id>', '<type>', '<value>', '<normalized>', 'operator-remap');
   ```

   If the error came from a wrong Mapping Review resolution:
   ```
   POST /v1/mapping-review/<review_id>/resolve
   { "campaign_id": "<correct_campaign_id>", "note": "Corrected incorrect prior resolution" }
   ```

2. **Dry-run reprocessing via Kyber**

   ```
   POST /v1/kyber/measurement/campaign/tenant/<tenant_id>/reprocess
   { "limit": 10000, "dry_run": true }
   ```

   Review the response: `records_that_would_change`, `estimated_campaign_uuid_changes`.

3. **Execute reprocessing**

   ```
   POST /v1/kyber/measurement/campaign/tenant/<tenant_id>/reprocess
   { "limit": 10000, "dry_run": false }
   ```

4. **Verify**

   - Check Campaign 360 for the affected campaign — spend and touchpoints should now appear under the correct UUID.
   - Confirm the previous (incorrect) campaign UUID shows a drop in attributed spend.
   - Validate attribution credits via the Attribution Studio page.

5. **Audit trail**

   All reprocess operations are logged. Confirm the audit entry via:
   ```
   GET /v1/kyber/measurement/campaign/audit?tenant_id=<tenant_id>
   ```

## Limitations

- Reprocessing is bounded (`limit` parameter, default 5000 per call). For large tenants, run in batches with cursor pagination.
- Journey and attribution recomputation follows the touchpoint reprocessing asynchronously — allow up to 15 minutes for Campaign 360 totals to update.
