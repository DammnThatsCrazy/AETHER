# Aether Access Kit

The Access Kit package provides a Node CLI and local MCP stdio bridge for two
bounded customer operations:

- Read the observed third-party agent access inventory owned by Agent Access
  Intelligence.
- Send one custom application observation through canonical `POST /v1/batch`.

The observed inventory is not an Aether callable-capability registry. Listing a
record neither grants nor invokes a capability. The Access Kit does not own
authentication, tenant selection, consent, policy, billing, graph access, or
action execution.

## Requirements and setup

Node.js 20 or later is required by the pinned MCP TypeScript SDK. In a workspace
checkout, install the repository dependencies and invoke the package scripts or
workspace binaries. The package does not save credentials.

Set `AETHER_API_URL` to an API origin if using a non-default environment. It
defaults to `https://api.aether.io`; the client requires HTTPS except for
loopback development origins.

Supply only the credential required by the command being used:

| Command | Environment |
|---|---|
| `aether agents capabilities ...` | `AETHER_API_KEY` with `read` permission |
| `aether ingest ...` | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |
| MCP inventory tools | `AETHER_API_KEY` with `read` permission |
| MCP `observe` tool | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |

The publishable key must be a `pk_` credential. The caller supplies the
site-bound ID separately. Aether resolves tenant scope from the key and checks
the required `X-Aether-Site` header against the key's binding. Do not set or
send a tenant ID override. The Access Kit uses a publishable key only for
`POST /v1/batch`, never for reads.

## Agent access inventory

```sh
aether agents capabilities overview
aether agents capabilities list --provider example --limit 25 --json
aether agents capabilities show cap_0123456789abcdef01234567 --json
```

The list API is capped at 100 rows per call. Filters and pagination are passed
to the existing tenant-scoped REST routes. Results describe observed external
agent access; they are not grants, Aether tools, or execution permissions.

## CLI ingestion

```sh
aether ingest onboarding_step_completed \
  --event-id evt_01JEXAMPLE \
  --session-id sess_customer_setup \
  --anonymous-id anon_customer_setup \
  --sequence 0 \
  --properties-json '{"step":"profile"}'
```

The CLI sends one canonical `track` event to `POST /v1/batch`. The positional
name becomes `properties.event`. The event ID is caller supplied so a caller
can repeat a request after a network failure with the same idempotency key;
session ID, anonymous ID, and sequence are also caller supplied to preserve
identity and ordering semantics across events. The client stamps the library
version, `surface: "cli"`, and canonical envelope version. It does not add a
user ID or consent grant.

The client body limit is 64 KiB. Never send passwords, tokens, payment data,
or other sensitive content in event properties. The server remains authoritative
for event validity, consent/privacy decisions, durable writes, deduplication,
and the per-event `accepted`, `duplicate`, or `rejected` outcome. The CLI
returns those outcomes and reason codes without converting rejections to
success. It does not automatically retry.

## MCP stdio bridge

Start `aether-mcp` using the MCP host's environment or secure secret-injection
mechanism. The bridge supports `agent_access_capabilities_list`,
`agent_access_capabilities_overview`, and `observe`. Read tools require the
read credential; `observe` requires the publishable key and its bound site ID.
Each call makes a fresh REST request. There is no remote HTTP MCP server,
OAuth flow, stored session, or MCP host configuration file in this package.

`observe` accepts `event_name`, `event_id`, `session_id`, `anonymous_id`,
non-negative `sequence`, and optional `properties`. It sends the same one-event
`track` batch as the CLI with `surface: "mcp"`. Its structured result preserves
the API batch counts, per-event statuses/reasons, batch ID, receive time, and
request ID. A rejected observation remains a server rejection.

The package uses the official `@modelcontextprotocol/server` SDK pinned to
`2.3.1`. The SDK `serveStdio` transport owns protocol framing and compatibility.
This package does not implement Streamable HTTP or an OAuth server.

## Implementation status

This is an experimental adapter slice. It has no saved profiles, login/device
authorization, tenant switching, general query language, callable-capability
registry, arbitrary external tool execution, graph mutation, or action
dispatch. The owning REST authorities remain the source of permission and
policy decisions.
