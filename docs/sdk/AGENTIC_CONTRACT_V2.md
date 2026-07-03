---
title: Agentic Observation Contract v2
slug: sdk/agentic-contract-v2
section: sdk
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - packages/shared/agentic-observability.ts
  - Backend Architecture/aether-backend/services/agentic_observability/schemas.py
  - Backend Architecture/aether-backend/services/agentic_observability/models.py
---

# Agentic Observation Contract v2

Agentic Observation Contract v2 is the server-side SDK and MCP middleware
payload shape for observing delegated agent activity. It keeps the core invariant:
Aether observes, correlates, verifies, explains, and recommends; Aether does not
execute provider actions.

## Compatibility

The backend accepts `event_type` as the v2 canonical field and continues to
accept `event_name` for v1 compatibility. If both fields are present, they must
match. Unknown canonical event values are still rejected by the route-level event
registry validator.

## Context groups

The v2 envelope adds typed context groups:

| Group | Purpose |
| --- | --- |
| `runtime` | Runtime id, environment, region, SDK name, and SDK version. |
| `correlation` | Trace, task, connection, invocation, provider request, object, campaign, and journey ids. |
| `mcp` | MCP protocol, transport, server identity, catalog revisions, tool schema, invocation phase, and metadata policies. |
| `authorization` | Authorization grant, credential reference, external account, workspace, scopes, and approval lifecycle metadata. |
| `verification` | Verification status, provider source, confidence, external object, evidence reference, and contradictions. |
| `privacy` | Content capture mode, redaction policy, privacy class, retention class, consent reference, and sensitive-data marker. |

## Projection behavior

The PR-3 foundation preserves v2 fields through normalization into typed Silver
facts. Trace, runtime, connection, tool, authorization, provider request,
external object, verification status, and evidence references become queryable
lineage fields while sanitized Bronze retains the source envelope.

## Safety boundary

The contract only records externally observed activity. `execution_by_aether`
remains `false`; payloads that claim Aether executed the action are rejected.
Credential material must be sent only as references such as `credential_ref`, not
as raw tokens or secrets.
