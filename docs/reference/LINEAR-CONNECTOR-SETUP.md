---
title: Linear Connector Setup (Outbound Delivery)
slug: operations/linear-connector-setup
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Linear Connector Setup — Outbound Delivery

## Prerequisites

- Linear workspace with admin or member access
- A Linear team and project to receive issues

## Required Permissions

Linear API keys are workspace-scoped. The key needs:

| Permission | Purpose |
|-----------|---------|
| Issues: Create | Create issues from suggestions |
| Issues: Update | Update issue status when outcome changes |
| Comments: Create | Add comments on existing issues |
| Webhooks: Admin | (optional) Configure webhooks via API |

## Setup Steps

### 1. Create an API Key

1. Go to **Linear** → **Settings** → **API** → **Personal API keys**
2. Create a key with a descriptive name (e.g. `aether-delivery`)
3. Store the key in Aether's provider vault; it is never stored in config or returned by the API

### 2. Find Your Team ID

```bash
curl -s -H "Authorization: Bearer $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ teams { nodes { id name } } }"}' \
  https://api.linear.app/graphql
```

Store the `team_id` in the delivery channel config (`provider_config.team_id`).

### 3. Configure Webhooks (for outcome loop)

1. Go to **Settings** → **API** → **Webhooks** → **New webhook**
2. URL: `https://{your-aether-domain}/v1/notifications/webhooks/linear/events`
3. Enable: **Issues** (created, updated, removed)
4. Copy the **webhook signing key** → store as `DELIVERY_LINEAR_WEBHOOK_SECRET`

### 4. Set Env Vars

```bash
DELIVERY_LINEAR_WEBHOOK_SECRET=<signing-key-from-linear-settings>
LINEAR_OAUTH_CLIENT_ID=<optional-for-oauth-flow>
LINEAR_OAUTH_CLIENT_SECRET=<optional-for-oauth-flow>
```

### 5. Test Connection

```bash
POST /v1/integrations/connectors/linear/test
```

Response: `{"ok": true, "viewer": {"id": "...", "name": "..."}}` on success.

## Team and Project Mapping

In the channel `provider_config`:
```json
{
  "team_id": "TEAM_UUID",
  "project_id": "PROJECT_UUID",
  "assignee_id": "USER_UUID",
  "label_ids": ["LABEL_UUID"]
}
```

## Priority Mapping

| Aether priority | Linear priority |
|----------------|----------------|
| P0 | 1 (Urgent) |
| P1 | 2 (High) |
| P2 | 3 (Medium) |
| P3 | 4 (Low) |
| INFO | 0 (No priority) |

## Webhook Signature Verification

Aether verifies `Linear-Signature` using `HMAC-SHA256(DELIVERY_LINEAR_WEBHOOK_SECRET, raw_body)` and `hmac.compare_digest`. Requests without a valid signature are stored in `WebhookInbox` with `signature_verified=False` and are not processed. The signed body's `webhookTimestamp` is required and must be within 60 seconds of when Aether received the request; older or missing timestamps are rejected as replays.

## Outcome Routing

The webhook never names its tenant: an `X-Aether-Tenant-ID` header is ignored.
Aether routes an event only to the tenant whose stored delivery created the issue
(`data.id` must match a stored issue link). When Aether created the issue it
stored the issue's team and organisation; the event's `organizationId` must
match that organisation, so an issue later moved to another team in the same
workspace still routes. Where no organisation was stored, the event's
`data.teamId` must match the stored team. Events matching no stored issue are
dead-lettered and never applied.

## Troubleshooting

**Issue not created — `INVALID_INPUT` GraphQL error**: Check that `team_id` and `project_id` are valid UUIDs for your workspace.

**`Forbidden` on issue creation**: The API key lacks Issues: Create permission. Regenerate with correct scopes.

**Webhook events not arriving**: Verify the webhook URL is publicly reachable and returns 200. Linear requires HTTPS.
