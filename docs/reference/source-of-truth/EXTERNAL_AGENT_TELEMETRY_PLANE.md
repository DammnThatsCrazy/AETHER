---
title: External Agent Telemetry Plane
slug: source-of-truth/external_agent_telemetry_plane
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
source_files: [config/environments/.env.example, packages/shared/agent-deployment.ts, packages/shared/contracts/event-registry.json, packages/sdk/server/src/agent-telemetry.ts, packages/sdk/python/aether_agentic/agentic.py, services/api/alembic/versions/20261010_agent_economic_correlation_refs.py, services/api/actions/agent/deployments.py, services/api/actions/agent/deployment_routes.py, services/api/actions/agent_marketplace/authority.py, services/api/actions/agent_marketplace/catalog.py, services/api/actions/agent_marketplace/lineage.py, services/api/actions/agent_marketplace/projection.py, services/api/config/settings.py, services/api/ingestion/ingestion/batch.py, services/api/ingestion/ingestion/lifecycle_worker.py, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/repositories/repos.py, services/api/shared/graph/graph.py, services/api/shared/graph/relationship_layers.py, services/api/value/x402/economic_mutations.py, services/api/value/x402/lifecycle_mapper.py, services/api/value/x402/provenance.py, services/api/workers/profile360_workers/workers.py, services/api/workers/runtime/roles.py, services/api/workers/runtime/specs.py]
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

**This is a telemetry plane, not an Aether-operated marketplace.** Aether does
not host agents, accept listing submissions, review or distribute bots, or
monetize listings. A separate opt-in observer reads only public listing labels,
URLs, and order from xAI's public index; it does not ingest bot configuration
or grant execution authority. `custom_marketplace` remains an external-platform
enum value describing a tenant-owned or third-party surface.

## Boundaries

- The SDK observes. It never resolves identity, emits `canonical_entity_id`,
  executes actions, signs transactions, custodies funds, or posts anywhere
  but `/v1/batch`. `canonical_entity_id` is stripped client-side and again
  at ingestion.
- `deployment_id` identifies the deployment; `agent_id` identifies the
  agent. Neither identifies a human, and neither is ever a merge-eligible
  identity signal (`services/api/identity/identity/merge_policy.py` denylist).
- All registry reads/writes are tenant-scoped; cross-tenant access returns
  not-found without leaking existence.

## Data model

`AgentDeployment` (shared contract `packages/shared/agent-deployment.ts`,
backend mirror `services/api/actions/agent/deployments.py`, durable store
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

TypeScript (`packages/sdk/server`): `AgentTelemetryClient extends AetherServerSDK`
— inherits `/v1/batch` batching, retry/backoff, scrubbing, consent handling.
Construction requires a validated `AgentDeploymentContext`; every event gets
`context.agentDeployment` attached. Helpers → canonical events:

| Helper | Canonical event(s) |
|---|---|
| `interaction(...)` | `track` |
| `task({status, paymentIntentId?, settlementEventId?})` | `agent_task_started` / `agent_task_completed` / `agent_task_failed`; optional payment IDs are caller-reported references |
| `toolInvocation(...)` | `agent_tool_invocation_observed` |
| `walletObservation({kind})` | `wallet` / `transaction` |
| `paymentObservation({status})` | `payment_initiated` / `payment_completed` / `payment_failed` |
| `delegatedTask({delegationId, delegatedToAgentId})` | `agent_delegated_task`; both IDs remain source references |
| `outcomeRecorded({paymentIntentId?, settlementEventId?, ...})` | `agent_outcome_recorded`; optional payment IDs are caller-reported references |
| `riskSignal(...)` | `agent_risk_signal_observed` |
| `objective({status})` | `agent_objective_created` / `_started` / `_modified` / `_completed` / `_failed` / `_abandoned` |
| `decision({phase})` | `agent_decision_started`, `agent_candidate_considered`, `agent_candidate_rejected`, `agent_action_selected`, `agent_decision_completed` |
| `authorization({status})` | `agent_authorization_requested` / `_granted` / `_denied` |
| `toolAdaptation({kind})` | `agent_tool_retried` / `agent_tool_switched` |
| `execution({status})` | `agent_execution_started` / `_succeeded` / `_failed` / `_aborted` |
| `economic({kind})` | `agent_quote_received`, `agent_price_evaluated`, `agent_transaction_*`; amounts are decimal strings and stay agent-reported |
| `information({kind})` / `memory({op})` | `agent_information_retrieved`, `agent_source_consulted`, `agent_context_received`, `agent_memory_*`; references only, never content |
| `spawned(...)` / `terminated()` | `agent_subagent_spawned` (parent is the deployment's agent) / `agent_terminated` |

Payment and settlement references resolve only to exact tenant-scoped records
whose provenance comes from the server-owned x402 commerce event registry.
Their amount, currency, provider, protocol, and lifecycle state come from
those records. A delegation reference resolves only when the exact canonical
record belongs to the tenant. The deployment's `agent_id` is a tenant registry
reference, while delegation endpoints are canonical entity IDs; this feature
does not identity-match the deployment to either party or evaluate grant
scope. These links express correlation; they do not establish causality,
grant-scope authorization, or payment finality.

Python (`packages/sdk/python/aether_agentic`): `build_behavior_event(...)` emits the same behavior types (deployment required, content keys and float amounts rejected); `build_deployment_context(...)`
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

- Graph (flag `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED`): tenant-scoped
  deployment lineage and bounded execution run/action evidence. Public catalog
  snapshots are separately platform-scoped and source-attributed. External
  IDs are not joined to canonical Agent vertices before identity authority
  resolves them. Tenant graph queries do not include platform-scoped catalog
  records; Agent 360 presents public listing metadata separately from tenant
  declared deployment origins. See `AGENT_MARKETPLACE_LINEAGE.md` for projection
  and recovery.
- Profile360 (flag `AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED`):
  `GET /v1/profile/{entity_id}/external-deployments` activity subresource.
- Identity: deployment/agent/platform signals never merge identities.

## Feature flags (all default OFF)

`AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED`,
`KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED`,
`AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED`,
`AETHER_AGENT_MARKETPLACE_CATALOG_ENABLED` (default OFF; public index reader).
The catalog poll interval is configured by
`AETHER_AGENT_MARKETPLACE_CATALOG_POLL_SECONDS` (default 21600; 900–86400
seconds). The public catalog route is
`GET /v1/agent/deployments/marketplace/catalog`; it is authenticated and
requires `agent:manage`. `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED` controls
catalog graph enqueue separately from source capture.

## Security, privacy, abuse controls

- Deployment metadata is sanitized (secret-shaped keys rejected); secrets
  never live on deployments.
- Revoked deployments are rejected at ingestion immediately.
- Per-deployment 24h acceptance/rejection/consent-block counters expose
  abuse and misconfiguration in both Aether and Kyber.
- Kyber aggregates avoid raw tenant-private payloads.

## Testing

Backend: deployment state, tenant isolation, audit, sanitization, ingestion
context, marketplace catalog parsing/status, platform graph reconciliation,
and run explanation coverage are checked in `services/api/tests/agent/`.
SDK: `packages/sdk/server/src/agent-telemetry.test.ts` covers task, tool,
policy, delegation, and outcome references. Frontend: Agent 360 evidence and
graph presentation tests cover source labels, coverage gaps, and evidence
authority.

## Sub-agent spawn lineage

`agent_subagent_spawned` events carry `parentAgentId`, `childAgentId`, an
optional `rootAgentId` and `parentRunId`. Silver stores them as
`parent_agent_ref`, `child_agent_ref`, `root_agent_ref` and `parent_run_id` on
`silver_agent_execution_facts` (migration `20261022_agent_spawn_lineage`), and
the lifecycle mapper writes the `SPAWNED_SUBAGENT` edge and a delegation row
from the parent to the **child** (earlier code read the child from
`parent_agent_id`, which produced self edges for SDK-shaped payloads).

`GET /v1/agent/agents/{root_agent_ref}/lineage` (`agent:manage`, registry flag)
returns the orchestrator tree with per-agent run, tool-call and outcome
rollups. It is tenant-scoped, cycle-safe, and bounded (depth 8, 100 agents);
bounds that apply are listed in `truncated`. The Silver reads behind it are
capped too (1,000 spawn facts per tenant, 200 facts per agent, newest first);
a cap that bites is reported in `source_truncation` and the response's
`source_status` is `incomplete`, never `empty`, so unrelated tenant activity
cannot silently evict the requested topology. Every node and edge is
`source_reported` and the response states `attribution: "none"`: the tree shows
which agent references spawned which, never who controls them. Silver stores
the event type as `source_event_type`; the readers accept `event_name` only for
locally held rows.

Spawn and delegation facts reported by an agent without a validated
deployment also project one bounded `SPAWNED_SUBAGENT` / `DELEGATED_TO`
graph edge per (parent, child) through the mutation gateway. The edge source
is always the reporting agent; a payload naming a different parent emits no
edge. At ingestion, `agent_subagent_spawned` and every agent behavior taxonomy
type (objectives, decisions, authority, execution, economic, memory) require a
validated deployment context. Behavior read models over these facts are
`GET /v1/agent/agents/{agent_ref}/behavior` and
`/decisions/{decision_id}`; see the
[agent behavior architecture map](../../architecture/agent-behavior/00-current-architecture-map.md).

## Known limitations / non-goals

- No Aether-operated marketplace, listing submissions/review/distribution, or
  revenue features. Public catalog observations are read-only and
  source-attributed.
- SDK examples ship in docs; live external-platform credentials are
  tenant-supplied.
- Associated X posts and newsroom news ingestion remain deferred until source
  access and provider compliance are approved. The public index observer does
  not bypass those controls.
- Health counters are rolling 24h approximations (documented reset
  semantics in `deployments.py`), not billing-grade metering.
