---
title: Python Agentic SDK
slug: sdk/python-agentic-sdk
section: sdks
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - packages/python/aether_agentic/agentic.py
  - packages/python/aether_agentic/__init__.py
---

# Python Agentic SDK

The Python agentic SDK foundation emits Agentic Observation Contract v2 payloads
for server-side agents, FastAPI services, workers, and MCP runtimes. It is
observation-only: helpers never execute provider actions, sign provider
requests, send messages, post content, trade, settle, or revoke access.

## Helpers

`AgenticObservationClient` exposes queue-backed helpers:

| Helper | Observed event |
| --- | --- |
| `observe_agentic` | Generic Contract v2 event. |
| `observe_agent` | Agent inventory observation. |
| `observe_mcp_connection` | MCP connection observation. |
| `observe_tool_invocation` | Tool invocation observation. |
| `observe_authorization` | Authorization grant/scope observation. |
| `observe_provider_action` | Provider action observation, not provider execution. |
| `observe_provider_verification` | Provider confirmation or contradiction observation. |

## Safety behavior

The helper builder sets `schema_version: "2.0"`, mirrors `event_type` into
`event_name`, and forces `execution_by_aether: false` on the ingestion payload.
Authorization data should use references such as `credential_ref`; raw tokens and
provider credentials must not be passed.

## Example

```py
from packages.python.aether_agentic import AgenticObservationClient

client = AgenticObservationClient()
client.observe_tool_invocation(
    tenant_id="tenant_123",
    invocation_id="invoke_123",
    tool_name="x.create_post",
    tool_id="tool_x_create_post",
    correlation={"trace_id": "trace_123", "connection_id": "conn_123"},
    authorization={
        "authorization_id": "auth_123",
        "external_account_id": "acct_123",
        "credential_ref": "vault://agentic/auth_123",
        "scopes": ["tweet.write"],
    },
)

queued_events = client.drain()
```
