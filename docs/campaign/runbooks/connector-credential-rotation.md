---
title: "Runbook: Campaign Source Connector Credential Rotation"
slug: campaign/runbooks/connector-credential-rotation
section: operations
visibility: I
audience: [ops]
---

# Runbook: Campaign Source Connector Credential Rotation

**Trigger:** Connector sync fails with an auth error, or a tenant requests credential rotation for a connected campaign source.

## Symptoms

- `campaign_source_sync_total{status="auth_error"}` incrementing for a platform.
- `CampaignSourceSyncFailed` alert fires.
- Connector health endpoint returns `"status": "auth_error"`.

## Security Invariants

- Credentials are stored in the encrypted secret store — never in the database, never in frontend state.
- **Never log or surface credential values** in error messages, telemetry, or Kyber UI.
- Token refresh happens server-side only; the frontend never receives raw credentials.

## Rotation Steps

1. **Retrieve the new credentials** from the ad platform's developer portal (OAuth refresh token, API key, service account key, etc.).

2. **Update the secret** via the credential store API:

   ```
   PUT /v1/internal/secrets/campaign-source/<source_id>
   Content-Type: application/json
   Authorization: Bearer <operator-token>
   { "credential_type": "oauth_refresh_token", "value": "<new_token>" }
   ```

   This endpoint is operator-only and never returns the credential value in the response.

3. **Trigger a test sync** to confirm the new credential works:

   ```
   POST /v1/campaign-sources/<source_id>/sync
   ```

4. **Confirm sync success**:

   - `campaign_source_sync_total{status="success", platform="<platform>"}` increments.
   - `CampaignSourceSyncFailed` auto-resolves.
   - `last_sync_at` on the source record updates.

5. **If sync still fails after rotation:**

   - Check whether the ad platform requires IP allowlisting (compare `campaign_source_freshness` gauge with the platform's API status page).
   - Verify the credential type matches what the connector expects (OAuth vs. API key vs. service account).

## Post-Rotation Verification

```
GET /v1/campaign-sources/<source_id>/health
```

Expected: `"status": "healthy"`, `"last_sync_at"` within the last 5 minutes.

## Notes

- OAuth refresh tokens for Meta, Google, TikTok expire if unused for 90 days. Set a recurring reminder to verify connector health.
- LinkedIn access tokens expire after 60 days and require re-authorization by the tenant account admin.
