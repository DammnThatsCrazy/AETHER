---
title: MCP/API/CLI Access Kit
slug: mcp-api-cli-access-kit
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# MCP/API/CLI Access Kit

## Purpose and boundary

The Access Kit makes existing Aether customer authorities usable through REST,
the CLI, and MCP. It is a transport adapter and developer interface. It does not
own authentication, tenant selection, capability grants, policy, billing,
readiness, rights, graph access, or action execution.

```text
REST / CLI / local MCP stdio bridge
                  │
                  ▼
       Aether authenticated API
       ├── auth middleware resolves tenant + actor
       ├── tenant permission and domain policy checks
       └── owning capability / query / action authority
```

Each transport must preserve the same tenant, actor, operation, authorization,
and result semantics. A client-supplied tenant ID, role, grant, rights decision,
or policy verdict is never authorization evidence.

## Baseline discovered in this tree

The following REST surfaces are already mounted by `services/api/main.py`.
They have distinct owners and meanings:

| Surface | Existing owner | Behavior and boundary |
|---|---|---|
| `GET /v1/capabilities` | `services/api/tenancy/capabilities/routes.py` | Tenant-facing release and feature discovery. Keep this path for its existing meaning; it is not the observed agent capability catalog. |
| `GET /v1/capabilities/activation` and `GET /v1/capabilities/activation/{provider}/{capability}` | `services/api/tenancy/capabilities/routes.py`, `CapabilityLifecycleAuthority` | Read the authenticated tenant's persisted capability readiness and history. Lifecycle changes require `admin` and remain in the lifecycle authority. |
| `GET /v1/capability-catalog`, `/overview`, `/{capability_id}` | `services/api/actions/agent_access_intelligence/routes.py`, `CapabilityCatalogService` | Read the tenant's observed external capability inventory. The catalog is evidence of observed agent access, not a grant or an Aether tool that can be executed. |
| `GET /v1/capability-installations` and detail | Agent Access Intelligence | Read tenant-scoped observed agent-to-server installation records. |
| `GET/POST /v1/capability-authorizations` and revoke | `CapabilityAuthorizationService` over the existing delegation store | Read grants or perform grant/revoke writes. Writes require `write`; do not duplicate delegation storage or lifecycle. |
| `POST /v1/capability-policy/evaluate`, `GET /v1/capability-policy/decisions` | `PolicyEngine` and Agent Access Intelligence | Evaluation records a sensitive policy decision and audit event; it does not invoke the external capability or mutate a tenant resource. Decisions are tenant-scoped reads. |
| `GET /v1/entities` and `GET /v1/entities/{entity_id}` | `services/api/identity/entities/routes.py` | Existing tenant-scoped entity reads (`read`). Entity and graph mutations remain in their owner API and mutation gateway. There is no catch-all `/v1/graph` query route added by this work. |

Every listed customer route reads `request.state.tenant`, which middleware
resolves from the API key or session JWT before the handler. The handlers enforce
their permission and scope repository reads with that resolved tenant. Operator
views under `/v1/kyber/*` use a separate Kyber gate and are not customer Access
Kit targets.

## Implemented vertical slices in this branch

`packages/access-kit` adds a Node CLI and local MCP stdio bridge over existing
Agent Access Intelligence reads, named tenant entity reads, and canonical
intake. The surfaces use the same small REST client. No new service route or
data authority is added.

| Surface | Supported call | Existing API | Classification |
|---|---|---|---|
| REST | `GET /v1/capability-catalog/overview` | Capability catalog overview | Query, `read` |
| REST | `GET /v1/capability-catalog?provider=&server_name=&tool_name=&limit=&offset=` | Capability catalog list | Query, `read` |
| REST | `GET /v1/capability-catalog/{capability_id}` | Capability detail | Query, `read` |
| CLI | `aether agents capabilities overview [--json]` | Catalog overview | Query, `read` |
| CLI | `aether agents capabilities list [filters] [--json]` | Catalog list | Query, `read` |
| CLI | `aether agents capabilities show CAPABILITY_ID [--json]` | Catalog detail | Query, `read` |
| CLI | `aether entities list [--entity-type TYPE] [--limit N] [--json]` | Entity list, max 50 | Query, `read` |
| CLI | `aether entities show ENTITY_ID [--json]` | Entity detail | Query, `read` |
| MCP | `agent_access_capabilities_overview` | Catalog overview | Read-only tool, `read` |
| MCP | `agent_access_capabilities_list` | Catalog list | Read-only tool, `read` |
| MCP | `entities_list` | Entity list, max 50 | Read-only tool, `read` |
| MCP | `entities_get` | Entity detail | Read-only tool, `read` |
| CLI | `aether ingest EVENT_NAME ...` | `POST /v1/batch`, one `track` event | Ingestion, `ingest` + handler `write` |
| MCP | `observe` | `POST /v1/batch`, one `track` event | Ingestion, `ingest` + handler `write` |

The `agents capabilities` inventory is about observed third-party agent access.
Those records neither grant nor expose Aether capabilities for invocation. The
separate Access Kit invocation registry remains target-only until an owning
runtime exists.

The CLI and MCP clients do not accept or send a tenant ID. Read calls resolve
tenant scope from `AETHER_API_KEY`; intake calls resolve tenant scope from the
site-bound publishable key. For intake, the clients send `X-Aether-Site` with
`AETHER_SITE_ID`; middleware verifies the key is bound to that site. The API
retains final control of authorization, validation, privacy, consent, persistence,
deduplication, and per-event status. The intake clients return the server's
`accepted`, `duplicates`, `rejected`, event reasons, batch ID, and received time
with the API request ID. They do not retry automatically. Repeating an event
with the same caller-supplied event ID is the server-supported deduplication
path.

`aether ingest` and `observe` emit one generic `track` event with a custom event
name, caller-supplied opaque event/session/anonymous IDs, caller-supplied
non-negative sequence, and optional properties. The adapter stamps its actual
surface (`cli` or `mcp`) plus library and envelope version fields. It sends no
user ID, consent grant, site/tenant identity in the body, or X-Tenant-ID header.
The server may accept, deduplicate, or reject the event; a rejected response is
not rewritten as an accepted observation. Client JSON input is capped at 64 KiB.

The CLI renders concise inventory/ingestion summaries or JSON. MCP returns
structured inventory records and the full one-event ingestion decision; the
read tools omit tenant IDs, source event IDs, artifact digests, and server URLs.

The list request is capped at 100 rows per call (`offset` is bounded to 100,000).
The current REST response's `count` is the number of rows in the returned page,
not a total count. Clients must not infer a total catalog size from it.

The entity query is deliberately narrow. `entities list` and `entities_list`
request the first page only, with default limit 25 and hard client maximum 50;
the existing endpoint has no cursor or offset. Detail calls use the existing
tenant-checked entity route. The Access Kit REST client and its CLI/MCP output
projections allow only `entity_id`, `entity_type`, `display_name`,
`parent_entity_id`, `created_at`, and
`updated_at`. They omit `tenant_id`, duplicate storage IDs, arbitrary
`metadata`, and other response fields. No graph traversal or direct repository
access is added. API status/code and request correlation are retained; CLI
`--json` failures carry these fields in an `error` object, and MCP failures set
`isError` with a JSON error object. Successful results may contain both the
middleware request ID and response envelope request ID.

## Authentication and transport

### CLI and local MCP bridge

- Configure `AETHER_API_KEY` with a tenant-scoped API key that has `read`
  permission for `agents capabilities` and `entities` commands. It is passed
  only in the HTTPS `Authorization: Bearer` header; it is never included in a
  URL, output, or persisted by this package.
- Configure `AETHER_PUBLISHABLE_KEY` with a `pk_` key and `AETHER_SITE_ID` with
  its bound site ID for `ingest` / `observe`. A publishable key is designed to
  be public and middleware confines it to ingestion routes plus the public-safe
  SDK manifest; this client uses it only with `POST /v1/batch` and always sends
  `X-Aether-Site`. Middleware rejects an unbound, undeclared, or mismatched site.
  The request never includes a tenant override. Key and site association,
  status, tenant, permissions, and the handler's additional `write` permission
  check remain server-owned.
- Do not use the read key for ingestion or the publishable key for reads. Supply
  whichever credential the selected command needs through the host's environment
  or secret injection mechanism. The bridge does not save either credential.
- `AETHER_API_URL` selects the API origin and defaults to
  `https://api.aether.io`. The client requires HTTPS, allowing HTTP only for
  `localhost`, `127.0.0.1`, or `::1`. The value cannot include credentials,
  paths, query strings, or fragments.
- Key issuance, tenant membership, role/scopes, revocation, request correlation,
  rate limits, and API error authority stay in Aether's existing middleware and
  account services. This package does not cache credentials or maintain a
  profile/tenant registry.
- The package currently declares Node `>=20` because the pinned MCP SDK release
  requires it. CLI and MCP calls use Node's built-in `fetch`.

### MCP

This branch provides a **local stdio bridge**, not a remotely hosted MCP server.
It uses the official `@modelcontextprotocol/server` TypeScript SDK pinned at
`2.3.1` and its `serveStdio` entry point. That SDK release supports both the
current `2026-07-28` revision and the 2025-era protocol on stdio; the bridge
keeps the SDK's compatibility behavior. It has no protocol session business
state. Every tool call makes a fresh authenticated REST request.

The official `2026-07-28` Streamable HTTP binding requires the
`MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` routing headers and validates
them against the JSON-RPC body. This package does not ship that remote transport,
so these HTTP requirements are not implemented here. A remote service requires
a separate design for delegated customer authorization, issuer/client
registration, tenant isolation, rate limiting, and edge header validation; a
stdio bridge or API key must not be placed behind an unauthenticated shared MCP
endpoint.

Example local host configuration should execute `aether-mcp` with the relevant
environment variables supplied by the host's secret mechanism. Do not paste a
live key into a tracked config file. The capability inventory tools are
read-only; `observe` is an ingestion write and must be shown accordingly. The
server-side REST permission check remains authoritative.

## Ownership for work beyond this slice

| Concern | Authority / owner | Access Kit rule |
|---|---|---|
| API key, session, actor, tenant resolution | `services/api/middleware/middleware.py`, account/auth services | Accept existing credentials; never trust caller tenant context. |
| Observed agent access inventory | `CapabilityCatalogService` | Read through its customer API; observations do not imply permission to invoke. These are not Aether's callable-capability registry. |
| CLI/MCP observation intake | `POST /v1/batch`, canonical ingestion route and authorities | Forward one site-bound `track` event and preserve every server decision. Do not ingest directly into storage or claim acceptance locally. |
| Capability grant and revoke | `CapabilityAuthorizationService` and Delegation Authority | Keep mutation commands out of the initial CLI/MCP slice; later calls use these routes and permission gates. |
| Policy decisions | `PolicyEngine` | Route checks through this engine; do not derive allow/deny from risk fields in the adapter. |
| Readiness lifecycle | `CapabilityLifecycleAuthority` | Reads may be surfaced; promotion, suspension, and resume remain `admin`/operator-owned. |
| Query/domain data | Owning domain APIs and repositories | Add only named, existing reads; no direct graph/database access from the CLI or bridge. |
| Ingestion | Canonical ingestion authorities | Forward only through the canonical intake route. Do not build an adapter-local persistence or consent authority. |
| Graph writes and external actions | Domain authority and `MutationIntent → GraphMutationGateway.apply` / action authority | No direct graph writes, provider calls, or action dispatch from a transport adapter. |
| Billing, usage, audit, receipts | Existing middleware and billing/audit owners | Do not add local counters or invent plan behavior. Verify whether each newly exposed operation has authoritative accounting before adding it. |

## Remaining target-only work

- A generic protocol-neutral invocation router does not exist. Add one only
  when multiple surfaces need it and when it can dispatch through explicitly
  registered owning authorities without bypassing their checks.
- The CLI/MCP slice has no login/device authorization flow, saved profile,
  tenant switching, token refresh, or revocation command. Initial auth is an
  externally supplied server-side API key. A future delegated login must reuse
  the approved identity/session owner and define secure OS credential storage.
- No graph search/traversal or broad `campaigns` or `agents` command/tool is
  registered in the Access Kit. Entity reads are limited to the named list and
  detail routes above; additional identity, graph, and domain queries need
  per-endpoint capability classification, scopes, pagination, output limits,
  and owner review before exposure.
- There is no MCP API server, OAuth authorization server for remote MCP, HTTP
  adapter, MCP Apps surface, Aether invocation registry, arbitrary external
  capability execution, or graph-write/action tool in this branch. CLI/MCP
  intake is limited to the generic, site-bound `track` path described above;
  batch collections, identity writes, and arbitrary direct route payloads are
  not exposed.
- This package has no usage-plan projection, customer-facing doctor report,
  hosted protocol probe, or provider-backed graph hydration proof.

## Proof gates and release claims

The following evidence is required before the associated claim:

| Claim | Required evidence |
|---|---|
| CLI package usable | Clean package install, Node version check, valid-key inventory/entity reads, publishable-key site-bound observation, JSON output, bad-key/permission/site-mismatch errors, network timeout, and absence of secret output. |
| Tenant-safe read | Two tenant keys and records; a key cannot list or resolve another tenant's catalog row. A missing/insufficient read scope is denied by API middleware/route authority. |
| Tenant-safe entity query | Exercise entity list/detail with two tenants and confirm cross-tenant detail is denied; verify CLI/MCP omit tenant IDs and metadata and list results never exceed 50. Local mocked contract tests do not replace this live API proof. |
| Site-bound intake | A matching key/site accepts or returns canonical validation outcomes; missing and mismatched site headers are denied; retrying the same event ID returns the server's idempotent result. |
| MCP protocol compatible | Run the official SDK/host conformance path for the pinned release on modern `2026-07-28` and supported 2025-era stdio clients; verify deterministic tool names/schemas and that a failed API authorization is returned as an error. |
| MCP customer beta | Above plus actual host connection evidence, secure host secret injection, request correlation, error visibility, privacy/security review, and rollout support. A local bridge build alone is not beta evidence. |
| Graph data available | A real tenant's observation-to-normalization-to-identity-to-projection proof and a separately authenticated read of that tenant's governed graph result. Catalog rows or a successful API response do not prove graph hydration. |
| PR readiness / production readiness | The single normal PR authority and applicable release scorecard; focused package evidence is not a substitute. |

No tests, conformance checks, host connection, live tenant, provider, or graph
hydration checks are claimed by this source change. The current deliverable is
an experimental inventory and one-event intake adapter slice.

## Protocol reference

- [Model Context Protocol 2026-07-28 specification release notes](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP TypeScript SDK support and migration guide for 2026-07-28](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28)
- [MCP TypeScript SDK server tools guide](https://ts.sdk.modelcontextprotocol.io/v2/servers/tools.html)
