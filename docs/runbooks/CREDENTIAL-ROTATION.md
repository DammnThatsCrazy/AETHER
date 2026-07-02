---
title: Credential Rotation Runbook
slug: runbooks/credential-rotation
section: runbooks
visibility: I
audience: [ops, security]
status: production
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Credential Rotation Runbook

All provider credentials are stored in the Aether vault (`providers` table `api_key` field). They are never in config, API responses, logs, or Kafka events. Rotation requires updating the vault record; no code restart is needed since `DeliveryWorker` resolves credentials on each job lease.

## Slack Bot Token Rotation

**When**: Token revoked, workspace re-authorized, or routine rotation.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → your Aether app → **OAuth & Permissions**
2. Re-install the app to your workspace (generates a new `xoxb-…` token)
3. Update the provider vault:
   ```bash
   PATCH /v1/admin/kyber/providers/<provider-record-id>
   Authorization: Bearer <kyber-operator-token>
   Content-Type: application/json
   {"api_key": "xoxb-new-token-here"}
   ```
4. Verify:
   ```bash
   POST /v1/integrations/connectors/slack/test
   ```
5. Old token is now invalid — no further steps needed.

**Do not**: Put the token in `SLACK_BOT_TOKEN` env var or config — env vars are for OAuth flow credentials only.

## Slack Signing Secret Rotation

**When**: Signing secret compromised or routine rotation.

1. In your Slack app → **Basic Information** → **App Credentials** → **Regenerate** signing secret
2. Update `SLACK_SIGNING_SECRET` env var and redeploy
3. Verify inbound webhooks are still processing (check `WebhookInbox.signature_verified`)

## Linear API Key Rotation

1. Go to **Linear** → **Settings** → **API** → revoke old key, create new one
2. Update provider vault:
   ```bash
   PATCH /v1/admin/kyber/providers/<provider-record-id>
   {"api_key": "lin_api_..."}
   ```
3. Verify: `POST /v1/integrations/connectors/linear/test`

## Linear Webhook Secret Rotation

1. Delete the old webhook in Linear settings, create a new one with same URL
2. Copy new signing key → update `LINEAR_WEBHOOK_SECRET` env var → redeploy
3. Verify inbound Linear webhooks arrive with `signature_verified=True`

## Jira API Token Rotation

1. Go to [id.atlassian.com](https://id.atlassian.com) → **Security** → **API tokens** → revoke old, create new
2. Update provider vault with `base64(email:new-token)` format:
   ```bash
   PATCH /v1/admin/kyber/providers/<provider-record-id>
   {"api_key": "email@example.com:new-api-token"}
   ```
   (Aether's Jira adapter handles the base64 encoding internally; store as plaintext `email:token`)
3. Verify: `POST /v1/integrations/connectors/jira/test`

## Jira Webhook Secret Rotation

1. Delete the old Jira webhook, create new one with same URL
2. Generate new secret → update `JIRA_WEBHOOK_SECRET` env var → redeploy

## Webhook Delivery Secret Rotation

For outbound webhook delivery to your endpoints:

1. Generate a new secret (minimum 32 bytes): `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update your webhook receiver to accept the new secret
3. Update provider vault:
   ```bash
   PATCH /v1/admin/kyber/providers/<provider-record-id>
   {"api_key": "new-secret-here"}
   ```
4. Test: `POST /v1/integrations/connectors/webhook/test`

**Note**: There is a brief window during rotation where some deliveries may fail verification on your receiver side. Queue any failed jobs for replay after the rotation is complete.

## Verifying Rotation Succeeded

For any provider after rotation:
1. Connector test endpoint returns `{"ok": true}`
2. A new job succeeds (create a test suggestion, approve it, verify `ProviderReceipt` is created)
3. Health status changes from `credentials_invalid` to `healthy`
