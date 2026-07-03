---
title: Node Agentic SDK
slug: sdk/node-agentic-sdk
section: sdks
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - packages/server/src/agentic.ts
  - packages/server/src/index.ts
  - packages/shared/agentic-observability.ts
---

# Node Agentic SDK

The Node agentic SDK foundation lives in `@aether/server` and emits Agentic
Observation Contract v2 payloads. It is observation-only: the helpers never
execute provider actions, sign provider requests, send messages, post content,
trade, settle, or revoke access.

## Helpers

`AetherServerSDK` exposes `sdk.agentic` with typed helpers:

| Helper | Observed event |
| --- | --- |
| `observeAgentic` | Generic Contract v2 event. |
| `observeAgent` | Agent inventory observation. |
| `observeRuntime` | Runtime observation. |
| `observeExternalAccount` | External account observation. |
| `observeAuthorization` | Authorization grant/scope observation. |
| `observeProviderAction` | Provider action observation, not provider execution. |
| `observeProviderVerification` | Provider confirmation or contradiction observation. |
| `observeMcpConnection` | MCP connection observation. |
| `observeToolInvocation` | MCP/tool invocation observation. |

## Safety behavior

The helpers set `schema_version: "2.0"`, mirror `event_type` into the v1
compatibility `event_name`, and force `execution_by_aether: false` in the queued
server event payload. Authorization data uses references such as
`credential_ref`; raw tokens and provider credentials must not be passed.

## Example

```ts
import { AetherServerSDK } from '@aether/server';

const sdk = new AetherServerSDK({ writeKey: process.env.AETHER_WRITE_KEY! });
sdk.grant(['agent']);

sdk.agentic.observeToolInvocation({
  tenant_id: 'tenant_123',
  agent_id: 'agent_123',
  invocation_id: 'invoke_123',
  tool_name: 'x.create_post',
  tool_id: 'tool_x_create_post',
  correlation: { trace_id: 'trace_123', connection_id: 'conn_123' },
  authorization: {
    authorization_id: 'auth_123',
    external_account_id: 'acct_123',
    credential_ref: 'vault://agentic/auth_123',
    scopes: ['tweet.write'],
  },
});

await sdk.flush();
```
