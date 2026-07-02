---
title: Delivery Failures Runbook
slug: runbooks/delivery-failures
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
---

# Delivery Failures Runbook

## Job Stuck in LEASED

**Symptom**: A `delivery_jobs` row has `state = leased` and `lease_expires_at` in the past. The suggestion never reaches DELIVERED.

**Cause**: Worker crashed or was restarted while holding the lease.

**Fix**:
```sql
-- Find expired leases
SELECT id, tenant_id, provider_adapter, lease_expires_at
FROM delivery_jobs
WHERE state = 'leased'
  AND lease_expires_at < NOW();
```

The `DeliveryWorker._reclaim_loop()` runs every 60 seconds and automatically re-queues these. If you need to force it:
```sql
UPDATE delivery_jobs
SET state = 'queued', leased_by = NULL, lease_expires_at = NULL
WHERE state = 'leased'
  AND lease_expires_at < NOW();
```

No restart needed. The next `lease_next_batch()` cycle will pick the job up.

---

## DEAD_LETTER Investigation

**Symptom**: `delivery_jobs.state = dead_letter`. `DELIVERY_JOB_DEAD_LETTERED` event was published.

**Step 1 — Read the error summary**:
```sql
SELECT id, provider_adapter, attempt_count, error_summary, dead_lettered_at
FROM delivery_jobs
WHERE state = 'dead_letter'
  AND tenant_id = '<tenant>'
ORDER BY dead_lettered_at DESC
LIMIT 10;
```

**Step 2 — Read the attempt history**:
```sql
SELECT attempt_number, outcome, http_status, error_class, error_message, latency_ms
FROM delivery_attempts
WHERE job_id = '<job-id>'
ORDER BY attempt_number;
```

**Step 3 — Classify the failure**:

| `error_class` | Meaning | Fix |
|--------------|---------|-----|
| `AuthError` | Credential invalid or expired | Rotate credential, then replay |
| `InvalidPayloadError` | Bad channel config (wrong team_id, project not found) | Fix config, then replay |
| `ProviderNetworkError` | Provider unreachable | Usually transient; replay |
| `ProviderTimeoutError` | Provider took too long | Retry; check provider status page |

**Step 4 — Replay via Kyber**:
```
Kyber → Delivery Operations → Dead-Letter tab → Replay
```

Or via API (Kyber operator token required):
```bash
POST /v1/delivery/jobs/<job-id>/replay
Authorization: Bearer <kyber-operator-token>
```

---

## Credential Expiration Diagnosis

**Symptom**: All jobs for a tenant's Slack/Linear/Jira channel are going to DEAD_LETTER with `AuthError`.

**Diagnostic**:
```bash
POST /v1/integrations/connectors/<provider>/test
Content-Type: application/json
{"tenant_id": "<tenant>", "config_id": "<config-id>"}
```

If response is not `{"ok": true, ...}` the credential is invalid.

**Fix**: See the `CREDENTIAL-ROTATION.md` runbook.

---

## Rate Limit Handling

**Symptom**: Jobs failing with `ProviderNetworkError` and `http_status = 429`. `error_message` contains `Retry-After`.

**Behavior**: `DeliveryWorker` reads the `Retry-After` header and sets `next_attempt_at` accordingly. No manual intervention needed unless the job hits `max_attempts` before the rate limit clears.

**If DEAD_LETTER due to rate limiting**: Wait for rate limit to clear (check provider status), then replay the job via Kyber.

---

## Reconciliation for Ambiguous Deliveries

**Symptom**: A suggestion shows `status = approved` but there is a `ProviderReceipt` row for it, suggesting it was delivered. Or vice versa.

**Diagnostic**:
```sql
-- Find the receipt
SELECT pr.*
FROM provider_receipts pr
JOIN delivery_jobs dj ON pr.job_id = dj.id
JOIN delivery_intents di ON dj.intent_id = di.id
WHERE di.source_type = 'suggestion'
  AND di.source_id = '<suggestion-id>';

-- Check external_id is real (not sim-)
SELECT external_id FROM provider_receipts WHERE job_id = '<job-id>';
```

If `external_id` is real and verifiable in the provider (Slack: `channel:ts` visible in permalink; Linear: issue URL; Jira: `PROJ-N`), the delivery was successful. Manually advance the suggestion:
```bash
PATCH /v1/suggestions/<id>
{"status": "delivered"}
```

If the `ProviderReceipt` does not exist despite `state = succeeded` on the job, this indicates a bug — file an incident.
