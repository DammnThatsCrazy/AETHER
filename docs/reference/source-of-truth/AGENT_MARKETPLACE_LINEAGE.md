---
title: Agent Marketplace Lineage
slug: source-of-truth/agent_marketplace_lineage
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
source_files: [packages/sdk/server/src/agent-telemetry.ts, packages/shared/agent-deployment.ts, packages/shared/contracts/event-registry.json, packages/shared/graph-contract.ts, services/api/alembic/versions/20261010_agent_execution_lineage.py, services/api/actions/agent/deployment_routes.py, services/api/actions/agent/deployments.py, services/api/actions/agent_marketplace/models.py, services/api/actions/agent_marketplace/lineage.py, services/api/actions/agent_marketplace/projection.py, services/api/ingestion/ingestion/generated_registry.py, services/api/ingestion/ingestion/validation.py, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/shared/graph/graph.py, services/api/shared/graph/relationship_layers.py, services/api/workers/runtime/roles.py, services/api/workers/runtime/specs.py]
---

# Agent Marketplace Lineage V1

## Purpose

AETHER can already receive activity telemetry from tenant-owned external agent
deployments. This contract preserves the source lineage a tenant declares when
registering a deployment: marketplace namespace, listing reference, template
reference, and template version. The graph can then distinguish what was
listed, what the tenant says it deployed, and what later telemetry says that
deployment did.

The contract is provider-neutral. It does not fetch marketplace pages or
require a public catalog API. A marketplace adapter can be added when a source
offers an authorized acquisition surface; the current registration path records
tenant-supplied references only.

Deployment creation accepts the optional `marketplace_origin` object:

```json
{
  "agent_id": "agent_support",
  "display_name": "Support assistant",
  "external_platform": "custom_marketplace",
  "marketplace_origin": {
    "source_namespace": "xai_bot",
    "listing_ref": "listing-123",
    "template_ref": "bot-456",
    "template_version": "2026-10-01",
    "listing_url": "https://x.ai/bot/marketplace",
    "category": "support",
    "catalog_capabilities": ["ticket_triage"]
  }
}
```

The authenticated deployment tenant supplies the outer scope. Source
references are bounded and tenant-scoped in the graph; tracking query strings,
URL credentials, and fragments are rejected.

## Evidence and authority boundaries

- `marketplace_origin.assertion` is always `tenant_declared`. The registry
  rejects caller-supplied verification labels.
- `source_namespace` scopes listing and template references. These values are
  never canonical Agent identities and never trigger identity merges.
- `catalog_capabilities` are listing labels. They do not grant runtime
  authority, prove that a capability is installed, or substitute for an
  authorization grant.
- Deployment `capability_scopes`, authority grants, observed runs, and economic
  outcomes remain separate records. Marketplace purchase or listing metadata
  alone does not prove execution, payment, or settlement.
- AETHER records and observes. It does not list, host, distribute, or execute
  marketplace agents.

## Graph projection

When `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED=true`, deployment creation queues
tenant-scoped `AgentMarketplaceListing`, `AgentTemplate`, and `Marketplace`
vertices for the supervised graph-writer. The graph records listing-to-market,
listing-to-template-version, and deployment-to-template-version edges, with
source namespace, version, tenant declaration, and deployment ID as
provenance. The response reports whether origin projection is queued, disabled,
or failed. A deployment stores the tenant's agent reference, but this slice
does not create an edge to a canonical Agent vertex; that join must be resolved
by identity authority first.

For later validated telemetry, `AgentExecutionProjector` promotes deployment,
run, trace/span, correlation/causation, task, outcome, delegation, and principal
references into queryable Silver columns. The deployment's backend-validated
`agentId` takes precedence over any event property. A stable caller-provided
`runId` (or the existing distributed `traceId`) groups related events; the run
reference remains source-reported correlation, not authority or proof of
causation. With `AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED=true` and a valid run
correlation reference, graph projection adds one tenant-scoped run node, a
run-to-deployment link, plus bounded task and outcome references where the
source supplies them. Source-reported task actions, tool calls, triggers, policy
evaluations, and delegation references become action/decision records linked
from the run. Each record carries the source event ID and observed timestamp;
the full event payload remains in Silver. A delegated-to agent remains a
tenant/deployment-scoped source reference and is not joined to an Agent vertex.
When a task-completed, task-failed, or outcome-recorded event omits an explicit
outcome ID, its stable source event ID becomes the graph outcome reference.
Task/outcome graph IDs are tenant- and deployment-scoped hashes; their raw source
references remain in Silver. The tenant's `agent_id` remains a registry
reference in the deployment record and Silver; the graph records only that the
reference came from the deployment registry and does not join it to a canonical
Agent vertex until identity authority resolves it. Full event payloads remain
in Silver. The graph creates action/decision records only for curated task,
action, tool, policy, and delegation evidence; other agent telemetry remains
Silver-only.

The server telemetry client reports task start/completion/failure, tool
invocation, policy evaluation, delegation, and outcome events through
`/v1/batch`. These event types are source-asserted and are SDK-emittable only
while external agent telemetry is enabled and `context.agentDeployment` resolves
to an active deployment owned by the authenticated tenant. The validated
registry identity, not SDK `agentId`, is used in Silver attribution. Canonical
graph identity linkage remains deferred to the identity authority.

The run explanation route assembles a chronological, tenant-scoped timeline from
Silver evidence: task/action references, declared triggers, policy decisions,
delegation references, tool invocations, and reported outcomes. It reports
coverage gaps and labels these claims `tenant_source_asserted`; it does not infer
causality, verify source policy or grant authority, or collect hidden model
reasoning. A delegation reference stays unresolved until AETHER's delegation
authority resolves it.

Agent marketplace and execution graph mutations enter a store-backed outbox
and are written through `GraphMutationGateway` by the supervised graph-writer
worker. Configured Redis/Dynamo stores provide cross-process durability; the
local in-memory store does not. Retries use bounded backoff and dead-lettering.
The worker applies mutations in gateway enforce mode so ledger idempotency makes
retries safe; blocked or unapplied graph writes remain retryable. Vertices use
versioned upserts, while relationships retain deterministic idempotency keys.
Kyber can inspect queue coverage, re-enqueue source mutations missing from the
queue, replay dead letters, or explicitly replay persisted rows. Reconciliation
checks source-to-outbox coverage and queue status; it does not claim to inspect
graph state. Stale in-progress rows are recoverable through the repair route.
The local migration adds indexed execution, trigger, policy, and delegation
references to `silver_agent_execution_facts`. Projection recovery uses the
configured durable store; local in-memory mode is not cross-process durable.

## Follow-on architecture

The next evidence slice can ingest authorized provider listing revisions and
associated news/posts as separate source records, preserving source URL or ID,
publication and observation times, attribution, and the exact claim. It can then
join run references to artifacts and authoritative grant records. News claims
must remain source-attributed evidence and must not silently become verified
marketplace facts. Agent 360 can present these references once the adjacent
Journey/economic evidence work is integrated. A source listing cannot by itself
establish why an agent acted; that explanation must come from observed trigger,
delegation, policy, and outcome evidence. A reported delegation ID is only a
source reference until resolved against AETHER's delegation authority. Hidden
model reasoning is not collected.
