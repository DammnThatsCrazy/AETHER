---
source_files:
  - packages/shared/agent-deployment.ts
  - packages/server/src/agent-telemetry.ts
  - packages/python/aether_agentic/agentic.py
  - Backend Architecture/aether-backend/services/agent/deployments.py
  - Backend Architecture/aether-backend/services/agent/deployment_routes.py
  - Backend Architecture/aether-backend/services/ingestion/batch.py
last_synced_commit: HEAD
---

# External Agent Telemetry Plane V1 — Source of Truth

## Overview

Tenant-owned external agent deployments (Discord bots, Telegram bots, Slack
apps, web widgets, MCP servers, backend workers, wallet agents, agents on a
tenant's own or third-party marketplace) emit Aether-compatible telemetry.
Aether ingests it through canonical `/v1/batch`, validates deployment
context, enforces consent and tenant scope, resolves identity conservatively,
expands graph relationships, and surfaces deployment intelligence in the
Aether tenant app and diagnostics in Kyber.

**This is a telemetry plane, not a marketplace.** Aether does not publish,
host, list, review, or monetize agents. `custom_marketplace` is an
external-platform enum value describing a tenant-owned or third-party
surface only.

## Boundaries

- The SDK observes. It never resolves identity, emits `canonical_entity_id`,
  executes actions, signs transactions, custodies funds, or posts anywhere
  but `/v1/batch`. `canonical_entity_id` is stripped client-side and again
  at ingestion.
- `deployment_id` identifies the deployment; `agent_id` identifies the
  agent. Neither identifies a human, and neither is ever a merge-eligible
  identity signal (`services/identity/merge_policy.py` denylist).
- All registry reads/writes are tenant-scoped; cross-tenant access returns
  not-found without leaking existence.

## Data model

`AgentDeployment` (shared contract `packages/shared/agent-deployment.ts`,
backend mirror `services/agent/deployments.py`, durable store
`agent_deployments` + `agent_deployment_audit`, migration
`20260708_agent_deployments.py`):

- Identity: `id`, `tenant_id`, `agent_id`, `display_name`, `description`
- Placement: `external_platform` (14-value enum), `external_platform_account_id`,
  `external_agent_id`, `external_app_id`, `external_channel_id`,
  `external_workspace_id`, `environment` (production|staging|sandbox|development)
- Governance: `status` (`active|paused|revoked|error|archived`),
  `consent_mode` (`tenant_managed|platform_managed|aether_managed`),
  `allowed_event_families`, `required_consent_purposes`, `capability_scopes`
- Health: `health_score`, `event_count_24h`, `accepted_count_24h`,
  `rejected_count_24h`, `error_count_24h`, `consent_blocked_count_24h`,
  `graph_projection_lag_ms`, `first_seen_at`, `last_seen_at`, `last_event_at`
- Audit: every lifecycle change writes an `agent_deployment_audit` record.

Lifecycle state machine: `active → paused|revoked|error|archived`;
`paused → active|revoked|archived`; `error → active|revoked|archived`;
`revoked → archived`; `archived` terminal. Invalid transitions are 409s.

## Routes

Tenant (`/v1/agent/deployments`, permission `agent:manage`, flag
`AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED`):

```txt
POST   /v1/agent/deployments
GET    /v1/agent/deployments
GET    /v1/agent/deployments/{deployment_id}
PATCH  /v1/agent/deployments/{deployment_id}
POST   /v1/agent/deployments/{deployment_id}/pause
POST   /v1/agent/deployments/{deployment_id}/reactivate
POST   /v1/agent/deployments/{deployment_id}/revoke
POST   /v1/agent/deployments/{deployment_id}/archive
GET    /v1/agent/deployments/{deployment_id}/health
GET    /v1/agent/deployments/{deployment_id}/activity
```

Kyber operator (`/v1/admin/kyber/agent-telemetry`, operator permission, flag
`KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED`): fleet overview + per-deployment
diagnostics. Aggregates never expose raw tenant-private metadata.

## Ingestion validation

When `AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED=true` and an event carries
`context.agentDeployment`, `/v1/batch` validates: deployment exists for the
authenticated tenant, status is `active`, and the event's family is in
`allowed_event_families`. Rejections are deterministic, audited, and update
per-deployment 24h counters (`accepted`/`rejected`/`consent_blocked`).
SDK-supplied `canonical_entity_id` is always stripped regardless of flags.

## Server-side Agent Telemetry SDK

TypeScript (`packages/server`): `AgentTelemetryClient extends AetherServerSDK`
— inherits `/v1/batch` batching, retry/backoff, scrubbing, consent handling.
Construction requires a validated `AgentDeploymentContext`; every event gets
`context.agentDeployment` attached. Helpers → canonical events:

| Helper | Canonical event(s) |
|---|---|
| `interaction(...)` | `track` |
| `task({status})` | `agent_task_started` / `agent_task_completed` / `agent_task_failed` |
| `toolInvocation(...)` | `agent_tool_invocation_observed` |
| `walletObservation({kind})` | `wallet` / `transaction` |
| `paymentObservation({status})` | `payment_initiated` / `payment_completed` / `payment_failed` |
| `outcomeRecorded(...)` | `agent_outcome_recorded` |
| `riskSignal(...)` | `agent_risk_signal_observed` |

Python (`packages/python/aether_agentic`): `build_deployment_context(...)`
plus an optional `deployment=` parameter on all envelope builders; emits the
same camelCase `agentDeployment` wire shape. `execution_by_aether` remains
hard-`False`.

### Example — Discord bot

```ts
import { AgentTelemetryClient } from '@aether/server';

const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_discord_support',
    agentId: 'agent_support',
    externalPlatform: 'discord_bot',
    externalWorkspaceId: guild.id,
    externalChannelId: channel.id,
    environment: 'production',
    consentMode: 'tenant_managed',
  },
});

client.on('messageCreate', (msg) => {
  telemetry.interaction({ name: 'discord_message_handled', properties: { channelKind: 'support' } });
});
```

### Example — Telegram bot

```ts
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_tg_alerts', agentId: 'agent_alerts',
    externalPlatform: 'telegram_bot', externalChannelId: String(chatId),
    environment: 'production', consentMode: 'platform_managed',
  },
});
bot.on('message', () => telemetry.interaction({ name: 'tg_command', properties: { command: '/status' } }));
```

### Example — Slack app

```ts
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_slack_triage', agentId: 'agent_triage',
    externalPlatform: 'slack_app', externalWorkspaceId: teamId, externalAppId: appId,
    environment: 'production', consentMode: 'tenant_managed',
  },
});
app.event('app_mention', async () => {
  telemetry.task({ taskId: 'triage-123', status: 'started', taskType: 'ticket_triage' });
});
```

### Example — web widget backend

```ts
// The widget's own backend relays observations server-side.
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_web_concierge', agentId: 'agent_concierge',
    externalPlatform: 'web_widget', externalAppId: 'concierge-v2',
    environment: 'production', consentMode: 'tenant_managed',
  },
});
```

### Example — MCP server

```ts
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_mcp_tools', agentId: 'agent_mcp',
    externalPlatform: 'mcp_server', environment: 'production',
    consentMode: 'tenant_managed',
  },
});
server.onToolCall((tool) =>
  telemetry.toolInvocation({ toolName: tool.name, status: 'succeeded' }));
```

### Example — backend worker (Python)

```python
from aether_agentic import build_agent_event, build_deployment_context

deployment = build_deployment_context(
    deployment_id="dep_worker_enrich", agent_id="agent_enrich",
    external_platform="backend_worker", environment="production",
    consent_mode="tenant_managed",
)
envelope = build_agent_event(
    event_type="agent_task_completed", agent_id="agent_enrich",
    deployment=deployment, properties={"task_type": "enrichment"},
)
# POST the envelope to /v1/batch with your tenant write key.
```

### Example — wallet app

```ts
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_wallet_agent', agentId: 'agent_wallet',
    externalPlatform: 'wallet_app', environment: 'production',
    consentMode: 'platform_managed',
  },
});
telemetry.walletObservation({ kind: 'transaction', properties: { chain: 'base', asset: 'USDC' } });
// Observation only — the SDK never signs or submits transactions.
```

### Example — tenant-owned custom marketplace

```ts
// The tenant's OWN marketplace surface (not an Aether marketplace).
const telemetry = new AgentTelemetryClient({
  writeKey: process.env.AETHER_WRITE_KEY!,
  deployment: {
    deploymentId: 'dep_acme_market', agentId: 'agent_listing_helper',
    externalPlatform: 'custom_marketplace', externalPlatformAccountId: 'acme-market',
    environment: 'production', consentMode: 'tenant_managed',
  },
});
```

## Graph / Profile360 / identity

- Graph (flag `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED`): aggregate
  deployment→agent projection through the agentic-observability mutation
  path; never node-per-event.
- Profile360 (flag `AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED`):
  `GET /v1/profile/{entity_id}/external-deployments` activity subresource.
- Identity: deployment/agent/platform signals never merge identities.

## Feature flags (all default OFF)

`AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED`,
`KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED`,
`AETHER_AGENT_TELEMETRY_SDK_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED`.

## Security, privacy, abuse controls

- Deployment metadata is sanitized (secret-shaped keys rejected); secrets
  never live on deployments.
- Revoked deployments are rejected at ingestion immediately.
- Per-deployment 24h acceptance/rejection/consent-block counters expose
  abuse and misconfiguration in both Aether and Kyber.
- Kyber aggregates avoid raw tenant-private payloads.

## Testing

Backend: `BE/tests/agent/test_deployments.py` (state machine, tenant
isolation, audit, sanitization), `test_deployment_routes.py` (routes,
Kyber permission), `BE/tests/unit/test_ingestion_deployment_context.py`
(accept/reject/strip, flag-off unchanged), identity merge-policy guards.
SDK: `packages/server/src/agent-telemetry.test.ts` (15 tests),
`packages/python/aether_agentic/test_agentic.py` (20 tests).
Frontend: aether deployments feature tests; Kyber agent-telemetry page tests.

## Known limitations / non-goals

- No marketplace listing/search/discovery/submission/revenue features.
- SDK examples ship in docs; live external-platform credentials are
  tenant-supplied.
- Health counters are rolling 24h approximations (documented reset
  semantics in `deployments.py`), not billing-grade metering.
