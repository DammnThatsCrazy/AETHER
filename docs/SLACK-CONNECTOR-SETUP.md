---
title: Slack Connector Setup (Outbound Delivery)
slug: operations/slack-connector-setup
section: operations
visibility: I
audience: [dev-senior, ops]
status: production
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Slack Connector Setup — Outbound Delivery

This guide covers configuring Slack as a **delivery target** for Aether suggestions. For inbound Slack event ingestion (graph enrichment), see `docs/SLACK-CONNECTOR.md`.

## Required OAuth Scopes

| Scope | Purpose |
|-------|---------|
| `chat:write` | Post messages to channels the bot is in |
| `chat:write.public` | Post to public channels without joining |
| `channels:read` | List available channels |
| `incoming-webhook` | Required for OAuth flow (grants channel-specific webhook) |

## Setup Steps

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name: `Aether` · Workspace: your workspace

### 2. Configure OAuth & Permissions

Under **OAuth & Permissions**:
- Add all scopes listed above under **Bot Token Scopes**
- Set **Redirect URL**: `https://{your-aether-domain}/v1/connectors/slack/oauth/callback`

### 3. Enable Interactive Components

Under **Interactivity & Shortcuts**:
- Turn on **Interactivity**
- Request URL: `https://{your-aether-domain}/v1/webhooks/slack/interactive`

This URL receives Approve / Suppress / Escalate button clicks from delivered suggestions.

### 4. Get Credentials

Under **Basic Information**:
- Copy **Signing Secret** → store as `SLACK_SIGNING_SECRET` in your vault

After installing the app to your workspace under **OAuth & Permissions**:
- Copy **Bot User OAuth Token** (`xoxb-…`) → store as your Slack credential in Aether's provider vault

### 5. Configure in Aether

```bash
# Set env vars (never commit these)
SLACK_CLIENT_ID=<your-client-id>
SLACK_CLIENT_SECRET=<your-client-secret>
SLACK_SIGNING_SECRET=<your-signing-secret>
SLACK_REDIRECT_URI=https://{your-aether-domain}/v1/connectors/slack/oauth/callback
```

### 6. Test the Connection

```bash
POST /v1/integrations/connectors/slack/test
Authorization: Bearer <operator-token>
Content-Type: application/json
{"tenant_id": "<tenant>", "config_id": "<config-id>"}
```

Response: `{"ok": true, "team_id": "T...", "bot_user_id": "U..."}` on success.

## Health States

| State | Meaning |
|-------|---------|
| Connected | `auth.test` succeeded; bot token valid |
| Credentials Missing | No Slack credential configured for this tenant |
| Credentials Invalid | `auth.test` returned `invalid_auth` or `token_revoked` |
| Permission Missing | Missing a required scope (e.g. `chat:write`) |
| Rate Limited | `ratelimited` response; delivery paused, respects `Retry-After` |
| Revoked | Token revoked; reinstall required |

## Troubleshooting

**Bot not posting to channel**: Invite the bot to the channel with `/invite @Aether`. Or use `chat:write.public` scope for public channels.

**Missing scope error**: Re-install the Slack app after adding new scopes — tokens don't update automatically.

**Token revoked**: The workspace admin revoked the bot token. Reinstall via the OAuth flow.

**Interactive actions not received**: Verify the Request URL under Interactivity is accessible from Slack's IPs and returns 200.

## Token Rotation

1. Revoke the old bot token in Slack's app settings
2. Re-install the app to the workspace (re-run the OAuth flow)
3. Update the `api_key` field in your `providers` vault record
4. The `DeliveryWorker` will pick up the new credential on the next job lease

## Signature Verification

Aether verifies all inbound Slack payloads using `HMAC-SHA256(signing_secret, f"v0:{timestamp}:{body}")`. Signatures older than 5 minutes are rejected. The verified flag is stored in `WebhookInbox.signature_verified`.
