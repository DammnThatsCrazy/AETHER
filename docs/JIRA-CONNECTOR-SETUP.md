---
title: Jira Connector Setup (Outbound Delivery)
slug: operations/jira-connector-setup
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Jira Connector Setup — Outbound Delivery

## Authentication

Aether supports two auth modes for Jira:

| Mode | Header | When to use |
|------|--------|-------------|
| Basic (API token) | `Authorization: Basic base64(email:token)` | Jira Cloud |
| Bearer | `Authorization: Bearer <token>` | Jira Data Center / Server |

### Creating a Jira API Token (Cloud)

1. Go to [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **Create API token**
3. Store the token in Aether's provider vault with format `email:token` — never in config

## Required Permissions

The account creating the API token must have:
- **Browse projects** on the target project
- **Create issues**
- **Add comments**
- **Transition issues** (for outcome routing to update issue status)

## Setup Steps

### 1. Get Your Jira Domain

Format: `https://yourcompany.atlassian.net`

### 2. Find Project Key

The project key appears in issue identifiers (e.g. `PROJ` in `PROJ-42`).

### 3. Configure Channel

In the delivery channel `provider_config`:
```json
{
  "domain": "https://yourcompany.atlassian.net",
  "project_key": "PROJ",
  "issue_type": "Task",
  "priority": "Medium",
  "assignee_id": "accountId",
  "labels": ["aether"],
  "custom_fields": {}
}
```

### 4. Configure Webhooks (for outcome loop)

1. Go to **Jira** → **Settings** → **System** → **WebHooks**
2. URL: `https://{your-aether-domain}/v1/webhooks/jira/events`
3. JQL scope: `project = PROJ` (or all projects)
4. Events: Issue Created, Issue Updated, Issue Deleted
5. Generate a signing secret and store as `JIRA_WEBHOOK_SECRET`

### 5. Set Env Vars

```bash
JIRA_WEBHOOK_SECRET=<your-webhook-signing-secret>
```

### 6. Test Connection

```bash
POST /v1/integrations/connectors/jira/test
```

Response: `{"ok": true, "account_id": "...", "display_name": "..."}` on success.

## Issue Type Mapping

Default issue type is `Task`. Configure in `provider_config.issue_type`. Common values:
- `Bug`, `Story`, `Task`, `Sub-task`, `Epic`

## Priority Mapping

| Aether | Jira |
|--------|------|
| P0 | Highest |
| P1 | High |
| P2 | Medium |
| P3 | Low |
| INFO | Lowest |

## Webhook Signature Verification

Aether verifies `X-Hub-Signature-256: sha256=<hex>` using `HMAC-SHA256(JIRA_WEBHOOK_SECRET, raw_body)`. Requests without a valid `sha256=` prefix are stored with `signature_verified=False`.

## Troubleshooting

**400 on issue creation**: Check `project_key` and `issue_type` — both must match existing Jira values exactly. The response body in the `DeliveryAttempt` record contains Jira's field validation errors.

**401/403**: API token expired or the account lacks project permissions. Re-create the token in Atlassian account settings.

**Webhooks not triggering**: Jira Cloud requires the webhook URL to use HTTPS. Verify the JQL scope covers the project where issues are created.
