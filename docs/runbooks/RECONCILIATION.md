---
title: Delivery Reconciliation Runbook
slug: runbooks/reconciliation
section: runbooks
visibility: I
audience: [ops, dev-senior]
status: production
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Delivery Reconciliation Runbook

## Suggestion APPROVED but No ProviderReceipt

**Symptom**: A suggestion has been `approved` for more than an hour with no DELIVERED transition and no ProviderReceipt.

**Step 1 — Check for a DeliveryIntent**:
```sql
SELECT id, state, idempotency_key, created_at
FROM delivery_intents
WHERE source_type = 'suggestion'
  AND source_id = '<suggestion-id>';
```

If no row exists: the `deliver_suggestion_via_notification` function failed or was not called. Check application logs at the suggestion's `approved_at` timestamp for errors. Manually create a DeliveryIntent via the API:
```bash
POST /v1/delivery/intents
Authorization: Bearer <operator-token>
{"source_type": "suggestion", "source_id": "<id>", "tenant_id": "<tenant>", ...}
```

**Step 2 — Check for DeliveryJobs**:
```sql
SELECT id, state, provider_adapter, attempt_count, error_summary
FROM delivery_jobs
WHERE intent_id = '<intent-id>';
```

- No jobs: channels may not be configured for this tenant. Check `user_notification_channels` for the tenant.
- Jobs exist with `state = dead_letter`: see the DELIVERY-FAILURES runbook.
- Jobs exist with `state = queued/failed`: worker may be down. Check `DeliveryWorker` is running.

**Step 3 — Check worker status**:
```bash
GET /v1/admin/kyber/delivery/worker-status
```

Response includes `last_run_at`, `jobs_processed`, `current_batch_size`.

---

## ExternalResourceLink Missing

**Symptom**: A `ProviderReceipt` exists (delivery confirmed) but no `ExternalResourceLink` joins it to the suggestion, and the suggestion outcome is not updating from provider webhooks.

**Diagnostic**:
```sql
SELECT * FROM external_resource_links
WHERE aether_object_type = 'suggestion'
  AND aether_object_id = '<suggestion-id>';
```

If missing, create it:
```bash
POST /v1/admin/kyber/delivery/links
Authorization: Bearer <kyber-operator-token>
{
  "tenant_id": "<tenant>",
  "aether_object_type": "suggestion",
  "aether_object_id": "<suggestion-id>",
  "external_system": "slack",
  "external_resource_type": "message",
  "external_id": "<channel:ts>",
  "external_url": "https://slack.com/...",
  "receipt_id": "<receipt-id>"
}
```

---

## Duplicate External Resource Detected

**Symptom**: Two `ExternalResourceLink` rows exist for the same `(tenant_id, external_system, external_id)` — this violates the unique constraint and should not happen in normal operation.

**How this can occur**: Worker crashed after creating the resource but before persisting the unique constraint check, AND idempotency key collision from a buggy client.

**Fix**:
1. Identify which is the authoritative row (newer `created_at` with a valid `receipt_id`)
2. Re-point any `ExternalOutcomeEvent` rows referencing the duplicate `link_id` to the authoritative one:
   ```sql
   UPDATE external_outcome_events
   SET link_id = '<authoritative-link-id>'
   WHERE link_id = '<duplicate-link-id>';
   ```
3. Delete the duplicate:
   ```sql
   DELETE FROM external_resource_links WHERE id = '<duplicate-link-id>';
   ```

---

## WebhookInbox Entries Not Processing

**Symptom**: `WebhookInbox` rows accumulate with `processing_status = pending`. Outcomes are not routing.

**Check WebhookInboxProcessor status**:
```bash
GET /v1/admin/kyber/delivery/inbox-processor-status
```

**Check for persistent processing failures**:
```sql
SELECT source_system, error_message, COUNT(*)
FROM webhook_inbox
WHERE processing_status = 'failed'
  AND received_at > NOW() - INTERVAL '1 hour'
GROUP BY source_system, error_message;
```

Common causes:
- `signature_verified = False` — provider secret mismatch; see CREDENTIAL-ROTATION runbook
- `ExternalResourceLink` not found — delivery for this `external_id` was from a different system; check `external_system` alignment
- `OutcomeRouter` exception — check application logs for the `inbox_id`
