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
REST / local CLI / cloud CLI / local MCP stdio / hosted MCP HTTP
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
| `GET /v1/capabilities` | `services/api/tenancy/capabilities/routes.py` | Tenant-facing SDK/release-surface and feature discovery. It is not an executable capability catalog, grant, or invocation registry; keep this path for its existing meaning. |
| `GET /v1/capabilities/activation` and `GET /v1/capabilities/activation/{provider}/{capability}` | `services/api/tenancy/capabilities/routes.py`, `CapabilityLifecycleAuthority` | Read the authenticated tenant's persisted capability readiness and history. Lifecycle changes require `admin` and remain in the lifecycle authority. |
| `GET /v1/capability-catalog`, `/overview`, `/{capability_id}` | `services/api/actions/agent_access_intelligence/routes.py`, `CapabilityCatalogService` | Read the tenant's observed external capability inventory. The catalog is evidence of observed agent access, not a grant or an Aether tool that can be executed. |
| `GET /v1/capability-installations` and detail | Agent Access Intelligence | Read tenant-scoped observed agent-to-server installation records. |
| `GET/POST /v1/capability-authorizations` and revoke | `CapabilityAuthorizationService` over the existing delegation store | Read grants or perform grant/revoke writes. Writes require `write`; do not duplicate delegation storage or lifecycle. |
| `POST /v1/capability-policy/evaluate`, `GET /v1/capability-policy/decisions` | `PolicyEngine` and Agent Access Intelligence | Evaluation records a sensitive policy decision and audit event; it does not invoke the external capability or mutate a tenant resource. Decisions are tenant-scoped reads. |
| `GET /v1/entities`, `GET /v1/entities/{entity_id}`, and `GET /v1/entities/{entity_id}/neighborhood` | Identity entity and entity-intelligence routes | Tenant-scoped reads (`read`). Explicit offset pages use durable entity-ID ordering. Neighborhood is a one-hop bounded graph projection with graph-family metering. Entity and graph mutations remain in their owner API and mutation gateway. |
| `GET /v1/agent/agents/{agent_ref}/behavior` and `GET /v1/agent/agents/{agent_ref}/decisions/{decision_id}` | `services/api/actions/agent/deployment_routes.py` over `intelligence.agent_behavior.read_models` | Tenant-scoped reads requiring `agent:manage`. Evidence-qualified Agent360 behavior read model and one reconstructed decision; another agent's or tenant's decision is not found. |
| `GET /v1/me` | `services/api/tenancy/me/routes.py:get_my_profile` | Existing tenant-scoped caller account profile, plan, billing summary, API key count, and admin flag. Middleware requires `read`; client projection omits tenant/graph IDs, contact email, and Stripe customer ID. |
| `POST /v1/auth/login` | `services/api/tenancy/auth/routes.py:login` | Existing email/password authentication. When human sessions are enabled it creates a durable session; otherwise it follows the legacy reusable API-key response. It is not a delegated CLI grant. |
| `POST /v1/auth/sso/callback` | `services/api/tenancy/auth/routes.py:sso_callback` | Exchanges an already-issued Auth0 access token for a server session or legacy key. `session_required: true` refuses before token validation or membership effects unless human sessions are enabled, so the CLI cannot receive a reusable API key. The CLI obtains the Auth0 token using Device Authorization. Membership resolution selects one existing tenant association/invitation and exposes no chooser. |
| `GET /v1/auth/sso/providers` | `services/api/tenancy/auth/routes.py` | Lists configured SSO providers (no auth), including `session_auth_enabled` for client preflight. |
| `GET /v1/me/sessions`, `DELETE /v1/me/sessions/{session_id}` | `services/api/tenancy/me/routes.py`, `SessionService` | Existing authenticated tenant session inventory and tenant-scoped revocation; the client projects safe session metadata and leaves the decision to the route. |

Every listed customer route reads `request.state.tenant`, which middleware
resolves from an API key, the existing `X-Session-Token`/session-cookie
contract, or a supported JWT before the handler. The handlers enforce
their permission and scope repository reads with that resolved tenant. Operator
views under `/v1/kyber/*` use a separate Kyber gate and are not customer Access
Kit targets.

## Implemented vertical slices in this branch

`packages/access-kit` adds a Node CLI, local MCP stdio bridge, and deployable
stateless Streamable HTTP MCP service over existing Agent Access Intelligence
reads, named tenant entity reads, account context, and canonical intake. The
surfaces use the same REST client and preserve the current API as the tenant,
permission, and data authority. The hosted process adds a transport adapter,
not a new service route or data authority.

| Surface | Supported call | Existing API | Classification |
|---|---|---|---|
| REST | `GET /v1/capability-catalog/overview` | Capability catalog overview | Query, `read` |
| REST | `GET /v1/capability-catalog?provider=&server_name=&tool_name=&limit=&offset=` | Capability catalog list | Query, `read` |
| REST | `GET /v1/capability-catalog/{capability_id}` | Capability detail | Query, `read` |
| CLI | `aether agents capabilities overview [--json]` | Catalog overview | Query, `read` |
| CLI | `aether agents capabilities list [filters] [--json]` | Catalog list | Query, `read` |
| CLI | `aether agents capabilities show CAPABILITY_ID [--json]` | Catalog detail | Query, `read` |
| CLI | `aether entities list [--entity-type TYPE] [--limit N] [--offset N] [--json]` | Entity list, max 50; stable explicit-offset paging | Query, `read` |
| CLI | `aether entities show ENTITY_ID [--json]` | Entity detail | Query, `read` |
| CLI | `aether entities neighborhood ENTITY_ID [--limit N] [--json]` | One-hop graph projection, max 50 neighbors and 100 edges | Query, `read` |
| CLI | `aether agents behavior show AGENT_REF [--json]` | Agent behavior read model (`agents.behavior`) | Query, `agent:manage` |
| CLI | `aether agents decisions show AGENT_REF DECISION_ID [--json]` | One reconstructed decision (`agents.decision`) | Query, `agent:manage` |
| CLI | `aether access operations list/show` and `aether access invoke` | Closed adapter read declaration and delegated API call | Discovery is local; invoke is query with the operation's declared `required_server_permission` (`read` unless stated) |
| CLI | `aether account context [--json]` | `/v1/me` safe projection | Query, `read` |
| CLI | `aether auth context [--json]` | `/v1/me` safe projection | Query, `read` |
| CLI | `aether auth login [--no-browser] [--json]` | Auth0 Device Authorization then `POST /v1/auth/sso/callback` with `session_required: true` | Human-session login; native OS credential store |
| CLI | `aether auth logout [--json]` | `DELETE /v1/me/sessions/{session_id}` for stored session | Tenant-scoped revocation, then credential-store removal |
| CLI | `aether auth sessions list [--limit N] [--offset N] [--json]` | `GET /v1/me/sessions`, max 100 | Auth session inventory, tenant-scoped |
| CLI | `aether auth sessions revoke SESSION_ID [--json]` | `DELETE /v1/me/sessions/{session_id}` | Auth session revocation, tenant-scoped |
| CLI | `aether ...` with `AETHER_API_KEY` or `AETHER_SESSION_TOKEN` in a CloudShell/CI/ECS environment | Existing named Aether API routes | Headless cloud use; no OS keyring login required for explicit credentials |
| MCP | `agent_access_capabilities_overview` | Catalog overview | Read-only tool, `read` |
| MCP | `agent_access_capabilities_list` | Catalog list | Read-only tool, `read` |
| MCP | `entities_list` | Entity list, max 50 | Read-only tool, `read` |
| MCP | `entities_get` | Entity detail | Read-only tool, `read` |
| MCP | `entities_neighborhood`, `access_operations_list`, `access_invoke_read` | Named graph read and closed adapter read declaration/dispatch | Read-only tools; API retains authorization |
| MCP | `account_context` | `/v1/me` safe projection | Read-only tool, `read` |
| MCP | `agents_behavior`, `agents_decision` | Agent behavior read model and decision detail | Read-only tools, `agent:manage`; not advertised to delegated OAuth tokens |
| Node ESM/TypeScript | `createAccessClient().operations.invoke(...)` and named entity/account/usage reads | Same closed REST adapters | Query, `read`; surface `access_sdk` |
| CLI / MCP / Node | `continuations create/show`, `continuations_create/get`, `createAccessClient().continuations` | Existing `POST /v1/continuations` and `GET /v1/continuations/{id}` | Principal-scoped durable resource create (`write`) and bounded readback (`read`); API feature is opt-in |
| CLI | `aether ingest EVENT_NAME ...` | `POST /v1/batch`, one `track` event | Ingestion, `ingest` + handler `write` |
| MCP | `observe` | `POST /v1/batch`, one `track` event | Ingestion, `ingest` + handler `write` |

The `agents capabilities` inventory is about observed third-party agent access.
Those records neither grant nor expose Aether capabilities for invocation. The
Access Kit now has a package-local closed declaration and read dispatcher. It
states adapter support, not server-side grants, tenant executability, or an
external capability invocation registry. Every invocation still reaches its
owning API route and its per-request checks.

The CLI and MCP clients do not accept or send a tenant ID. Read calls resolve
tenant scope from at most one explicit `AETHER_API_KEY` or
`AETHER_SESSION_TOKEN`; otherwise CLI and local MCP best-effort read a human
session from the OS credential store. Explicit environment credentials take
precedence. The stored session is sent using the existing `X-Session-Token`
contract. Intake calls
resolve tenant scope from the site-bound publishable key. For intake, the clients send `X-Aether-Site` with
`AETHER_SITE_ID`; middleware verifies the key is bound to that site. The API
retains final control of authorization, validation, privacy, consent, persistence,
deduplication, and per-event status. The intake clients return the server's
`accepted`, `duplicates`, `rejected`, event reasons, batch ID, usage evidence
ID when present, and received time with the API request ID. They do not retry
automatically. Repeating an event
with the same caller-supplied event ID is the server-supported deduplication
path.

The public Node client exports the same closed read operations and projects the
same API-derived results. It also exposes a narrow continuation create/get
pair through the existing owner. It accepts one API key or revocable session
and sends `access_sdk` for canonical access-interaction audit and metering. It
does not reuse the observation SDK's publishable key for reads or writes.

Continuation create stores one opaque entity reference and returns a durable
continuation handle, revision, and replay marker. The owner binds the record to
the authenticated principal, checks `write`, scopes the idempotency key to that
principal and original request, and rejects changed-content replay. It does
not verify the entity reference at create time; later resolution reauthorizes
it. A deterministic client-sync source event lets retries repair a missed
change-feed append without duplicating an already persisted event. The API
feature gate defaults off; Terraform exposes a reviewed opt-in for the API
task. Delegated MCP OAuth tokens never see the continuation tools.

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
Observed capability rows are emitted only for a valid `cap_` ID; projected
strings and counts have field-specific length/type bounds. Overview maps omit
invalid keys/counts, expose at most 50 entries per map, and set `sampled` when
the client truncates a map. Tenant IDs and unrecognized catalog/overview fields
are omitted.

The entity query is deliberately narrow. `entities list` and `entities_list`
default to 25 and cap at 50. Supplying offset 0 begins stable entity-ID paging;
the API returns `next_offset` until the page sequence ends. Detail calls use
the existing tenant-checked entity route. The Access Kit REST client and its CLI/MCP output
projections allow only `entity_id`, `entity_type`, `display_name`,
`parent_entity_id`, `created_at`, and
`updated_at`. They omit `tenant_id`, duplicate storage IDs, arbitrary
`metadata`, and other response fields. The named one-hop neighborhood returns
only IDs, types, labels, and relationship types, with explicit node/edge bound
flags; the adapter does not read graph storage. API status/code and request correlation are retained; CLI
`--json` failures carry these fields in an `error` object, and MCP failures set
`isError` with a JSON error object. Successful results may contain both the
middleware request ID and response envelope request ID.

Every supported CLI and MCP result also carries a protocol-neutral `interaction`
object produced by the shared REST client. It contains version, operation
(`query` or `observe`), status class (`successful`, `denied`, `blocked`,
`degraded`, or `failed`), middleware/correlation request ID, optional API
request ID, HTTP status, and recognized returned references. A 401/403 maps to
`denied`, 423/429 to `blocked`, 206/207 and observation responses with rejected
events to `degraded`, and transport/contract failures to `failed`. The original
API data remains available: observation decisions and returned receipt or
reference fields are passed through unchanged. The adapter does not create a
receipt, infer a successful admission, or promote an HTTP status into a policy
decision.

`aether account context` and MCP `account_context` call the existing read-gated
`GET /v1/me`. The projection is limited to account name, plan ID/display name
and limits, billing subscription status/period end, API key count, and the
caller admin flag. It deliberately removes tenant and graph IDs, contact email,
and Stripe customer IDs before any CLI/MCP response.

There is no combined `doctor` command. `/v1/health` and `/v1/ready` report
infrastructure liveness/readiness, `/v1/tenant/readiness` reports a separate
launch-readiness evidence view, and `/v1/me/usage` reports usage with explicit
insufficient-evidence states. Combining these into a customer verdict would
create a new readiness authority and could imply conclusions none of those
endpoints own. Expose them later only as distinct named reads, or after an
owning diagnostic/readiness contract exists.

## Authentication and transport

### CLI and local MCP bridge

- Configure `AETHER_API_KEY` with a tenant-scoped API key that has `read`
  permission for `agents capabilities`, `entities`, and `account context`
  commands. It is passed only in the HTTPS `Authorization: Bearer` header; it
  is never included in a URL, output, or persisted by this package.
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
  account services. `aether auth login` uses the Terraform-provisioned public
  Auth0 Native client and Device Authorization, then sends the Auth0 access
  token to the existing SSO callback with `session_required: true`. The API
  mints the revocable human session. The CLI stores only that Aether session
  token and session ID in native OS credential storage; it does not persist
  Auth0 access/refresh tokens, passwords, or profiles. Existing tenant
  membership resolution remains server-owned; there is no tenant chooser.
- CLI login requires `AETHER_AUTH0_DOMAIN`, `AETHER_AUTH0_CLIENT_ID`, and
  `AETHER_AUTH0_AUDIENCE`. It checks keyring availability and the public
  `session_auth_enabled` preflight before starting Auth0. macOS uses Keychain,
  Windows uses Credential Manager, and Linux explicitly requires Secret
  Service. Login fails closed if secure storage is unavailable. If the new
  session cannot be saved, the CLI attempts tenant-scoped server revocation
  using the in-memory session token.
- The package currently declares Node `>=20` because the pinned MCP SDK release
  requires it. CLI and MCP calls use Node's built-in `fetch`.
- Non-interactive CLI commands with explicit `AETHER_API_KEY` or
  `AETHER_SESSION_TOKEN` do not need the OS credential store. CloudShell, CI,
  or an ECS task can run the CLI with a secret manager injecting one supported
  credential into the process environment. Interactive `aether auth login`
  still requires the native OS credential store.
- Local MCP uses explicit `AETHER_API_KEY` or `AETHER_SESSION_TOKEN` when set;
  otherwise it best-effort loads the CLI human session from the same OS
  credential store. Missing or unavailable keyring access does not stop stdio
  startup, so publishable-key-only `observe` still works. Observe sends only
  its bound publishable key and never the saved human session.

### MCP

#### Local stdio

The local `aether-mcp` bridge uses the official
`@modelcontextprotocol/server` TypeScript SDK pinned at `2.3.1` and its
`serveStdio` entry point. It supports the current `2026-07-28` revision and
supported 2025-era stdio clients. The bridge keeps no business state in an MCP
session; each tool call makes a fresh authenticated REST request.

#### Hosted Streamable HTTP

The package also ships `aether-mcp-http`, a stateless Node service using the
same pinned SDK and tool registrations. The container listens on port `8080`
by default and serves `POST /v1/access/mcp`; `AETHER_MCP_PATH` can set another
exact path. It accepts modern protocol revision `2026-07-28` and the SDK's
required `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` routing headers.
It supports one-request/one-response tool calls, without protocol session
state or long-lived SSE streams. Every protocol request, including initialize
and tools/list, requires a caller Aether API key, revocable human-session
bearer, or an opt-in Auth0 token for the exact MCP resource. The service validates it through
`GET /v1/me`, then forwards that request-scoped credential to the existing
tenant API route; the API rechecks authorization and resolves tenant and actor.
Delegated OAuth reads additionally require the dedicated audience, Auth0
signature/issuer/expiry, `access_kit:read`, and an active durable Aether
membership. These tokens are limited to named read routes and cannot expose
the `observe` tool even when an intake key is supplied. The hosted service
signs each downstream OAuth call with a short-lived assertion bound to the
token hash and exact API request. The backend requires that assertion before
it accepts the MCP audience, so a public REST caller cannot spoof the MCP
surface header to widen a read token's API access.
The service has no shared service-level customer key and accepts no caller
tenant override.

The service requires `AETHER_API_URL` and exact `AETHER_MCP_ALLOWED_HOSTS`
configuration. Optional `AETHER_MCP_ALLOWED_ORIGINS` allows exact HTTPS browser
origins; server-to-server clients can omit `Origin`. It rejects wildcards and
invalid host/origin headers. `GET /healthz` is process liveness; `GET /readyz`
checks configuration but does not claim live Aether API reachability or tenant
readiness. The dedicated AWS Terraform service is opt-in, deploys only to the
`production` profile that canonically owns the globally named ECR
repository, uses an immutable image digest, and is routed separately from the
privileged operator `tfmcp` service. The customer MCP task role has no workload
AWS permissions. A local emulated `linux/amd64` image build and container
health/readiness plus CLI smoke passed. The hosted container workflow also
passed on PR #772 run
[38206643725](https://github.com/DammnThatsCrazy/AETHER/actions/runs/38206643725)
at head `ae66101c`, before the current local failure fixes were pushed. It
verified package contents, built the `linux/amd64` image, and passed the
container health, readiness, and headless CLI checks without AWS credentials.
Neither the local nor hosted smoke published an image, applied Terraform, or
started an ECS task. The OIDC image publisher verifies that the
production GitHub environment has at least one required reviewer before
waiting on its approval, and the reviewed plan/apply paths reject images
without a completed clean ECR scan. The repository currently has no
production environment. Its
repository-first image-publish and reviewed plan/apply sequence is documented in the
[`Access Kit MCP AWS deployment runbook`](../../../infra/aws/terraform/ACCESS_KIT_MCP_DEPLOYMENT.md).

Remote `observe` is listed only when that MCP request supplies both
`X-Aether-Observe-Key` and `X-Aether-Site-ID`. The pair is passed only to
canonical `POST /v1/batch`, whose existing admission path verifies site binding
and tenant scope. Without both headers the tool is omitted; partial or
malformed values are rejected. Tenant reads still require the caller bearer.
That bearer authenticates the MCP request but does not authorize the observation
write or choose its tenant; the publishable key and site pair independently
carry the existing site-bound intake authority.

The hosted endpoint remains bearer-authenticated. Opt-in OAuth resource-server
support publishes protected-resource metadata and challenges and configures a
distinct Auth0 audience/read scope. Auth0 owns authorization-code/PKCE and
client identity. Open dynamic client registration remains disabled; reviewed
pre-registration or compatible Client ID Metadata Document onboarding, user
consent, live tenant isolation, and remote host conformance remain separate
identity-owner and deployment gates. API key and session callers may use
`observe` with a separately valid site-bound intake pair; delegated OAuth
tokens are read-only. The server-side REST permission check remains authoritative.

## Ownership for work beyond this slice

| Concern | Authority / owner | Access Kit rule |
|---|---|---|
| API key, session, actor, tenant resolution | `services/api/middleware/middleware.py`, account/auth services | Accept existing API keys or human session tokens; never trust caller tenant context. |
| Human login, membership, and session lifecycle | `services/api/tenancy/auth/routes.py`, `services/api/tenancy/auth/sessions/service.py`, `services/api/tenancy/me/routes.py` | CLI uses Auth0 Device Authorization, the `session_required` SSO guard, and existing tenant session list/revoke routes. API remains the session and membership authority. |
| Auth0 CLI application | `infra/aws/terraform/modules/auth0/` | Terraform owns the Native public CLI client, Device Authorization grant, API audience/client grant, database connection association, and public client ID output. |
| Observed agent access inventory | `CapabilityCatalogService` | Read through its customer API; observations do not imply permission to invoke. These are not Aether's callable-capability registry. |
| CLI/MCP observation intake | `POST /v1/batch`, canonical ingestion route and authorities | Forward one site-bound `track` event and preserve every server decision. Do not ingest directly into storage or claim acceptance locally. |
| Capability grant and revoke | `CapabilityAuthorizationService` and Delegation Authority | Keep mutation commands out of the initial CLI/MCP slice; later calls use these routes and permission gates. |
| Policy decisions | `PolicyEngine` | Route checks through this engine; do not derive allow/deny from risk fields in the adapter. |
| Readiness lifecycle | `CapabilityLifecycleAuthority` | Reads may be surfaced; promotion, suspension, and resume remain `admin`/operator-owned. |
| Query/domain data | Owning domain APIs and repositories | Add only named, existing reads; no direct graph/database access from the CLI or bridge. |
| Continuation state | Existing continuation service and repository | Expose only bounded create/readback; the server owns principal scope, idempotency, sync effects, and feature gate. |
| Ingestion | Canonical ingestion authorities | Forward only through the canonical intake route. Do not build an adapter-local persistence or consent authority. |
| Graph writes and external actions | Domain authority and `MutationIntent → GraphMutationGateway.apply` / action authority | No direct graph writes, provider calls, or action dispatch from a transport adapter. |
| Billing, usage, audit, receipts | Existing middleware and billing/audit owners | Do not add local counters or invent plan behavior. Verify whether each newly exposed operation has authoritative accounting before adding it. |

## Remaining target-only work

- A package-local closed read dispatcher now covers named CLI/MCP reads through
  existing APIs. A general server executable-capability registry, tenant grant
  discovery, arbitrary invocation, and action router remain target-only.
- CLI login/logout is implemented through Auth0 Device Authorization,
  `session_required` SSO exchange, native OS credential storage, and the
  existing tenant-scoped session DELETE route. Live Auth0 configuration,
  human-session enablement, and device sign-in remain deployment proof gates.
  `POST /v1/auth/login` is a separate password flow and may return a reusable
  API key when human sessions are disabled; the CLI does not call it.
- There is no customer endpoint to list the current user's tenant memberships
  or exchange a session for a selected authorized tenant. Password login
  resolves one tenant from the user record; SSO membership resolution links or
  accepts an invitation but does not expose a tenant chooser. Tenant selection
  remains target-only until the auth/session owner provides that contract.
- A bounded one-hop entity neighborhood is registered. General graph search,
  traversal language, or broad `campaigns` and `agents` commands remain outside
  the Access Kit. Additional identity, graph, and domain queries need
  per-endpoint capability classification, scopes, pagination, output limits,
  and owner review before exposure.
- Auth0 remains the OAuth authorization server. The opt-in MCP resource server
  and protected-resource metadata are implemented; public DCR, client
  onboarding, MCP Apps, external capability execution, and graph-write/action
  tools are not. The continuation create/get pair is a resource write, not an
  external action dispatcher. CLI/MCP intake remains limited to generic site-bound `track`
  path described above; batch collections, identity writes, and arbitrary
  direct route payloads are not exposed.
- Host-specific registration and live delegated OAuth remain proof gates. Live AWS
  apply, public-host setup, two-tenant denial evidence, customer remote-client
  conformance, and Auth0 client/resource configuration are not established
  by repository code or a deployable image.
- The CLI package is configured for public npm distribution and has a manual
  release workflow that fails closed unless npm-production has a required
  reviewer, but no package version is published yet. That environment is not
  currently configured. Customer
  CloudShell/ECS/other-cloud installation by `npm install --global
  @aether/access-kit` becomes available after that release. The ECR image
  remains private to Aether AWS principals and is intended for the hosted MCP
  service and authorized Aether runners.
- This package has no usage-consumption or pricing interpretation, combined
  customer-facing doctor report, hosted protocol probe, or provider-backed
  graph hydration proof.

## Proof gates and release claims

The following evidence is required before the associated claim:

| Claim | Required evidence |
|---|---|
| CLI package usable | Clean package install, Node version check, valid-key inventory/entity reads, publishable-key site-bound observation, JSON output, bad-key/permission/site-mismatch errors, network timeout, and absence of secret output. |
| Tenant-safe read | Two tenant keys and records; a key cannot list or resolve another tenant's catalog row. A missing/insufficient read scope is denied by API middleware/route authority. |
| Tenant-safe entity query | Exercise entity list/detail with two tenants and confirm cross-tenant detail is denied; verify CLI/MCP omit tenant IDs and metadata and list results never exceed 50. Local mocked contract tests do not replace this live API proof. |
| Site-bound intake | A matching key/site accepts or returns canonical validation outcomes; missing and mismatched site headers are denied; retrying the same event ID returns the server's idempotent result. |
| CLI human-session login | Apply the Auth0 module in a non-production tenant; verify the public Native client, Device Authorization grant, API audience/client grant, and enabled login connection; set the three `AETHER_AUTH0_*` values; complete device sign-in with API human sessions enabled; verify session list/revoke, then repeat with sessions disabled and confirm refusal without storing a reusable API key. Exercise keyring-unavailable and post-issuance storage-failure cleanup. |
| MCP protocol compatible | Run the official SDK/host conformance path for the pinned release on modern `2026-07-28` and supported 2025-era stdio clients; verify deterministic tool names/schemas and that a failed API authorization is returned as an error. |
| Hosted MCP service deployable | Build and publish an immutable Access Kit image to its dedicated ECR repository; plan the opt-in Fargate service and ALB route; verify the separate task role, host/path configuration, `/healthz`, `/readyz`, and caller bearer requirement. A Terraform plan and local HTTP exchange do not prove an applied AWS endpoint. |
| MCP customer beta | Above plus actual host connection evidence, secure host secret injection, request correlation, error visibility, privacy/security review, and rollout support. A local bridge build alone is not beta evidence. |
| Graph data available | A real tenant's observation-to-normalization-to-identity-to-projection proof and a separately authenticated read of that tenant's governed graph result. Catalog rows or a successful API response do not prove graph hydration. |
| Continuation create/readback usable | Apply the reviewed API feature opt-in, then use a real tenant principal with read/write permission to create, replay with the same key and content, reject changed content, deny another principal's handle, and read the owner-produced revision. A stored entity reference alone does not prove entity authorization at resolution. |
| Delegated MCP OAuth usable | Apply the exact Auth0 resource and client configuration, verify protected-resource metadata and scope recovery in a real host, and prove direct REST reuse of an MCP-audience token is denied without the private service assertion. |
| PR readiness / production readiness | The single normal PR authority and applicable release scorecard; focused package evidence is not a substitute. |

Focused local Node tests cover REST wrapper behavior, projection and response
normalization, CLI output/error contracts, Auth0 device polling/expiry,
human-session storage/revocation, human-session header use and session
list/revoke mapping, MCP tool schemas/handlers, the pinned-SDK stdio
`initialize`/`tools/list` exchange, and a real local Node HTTP Streamable MCP
`tools/list` exchange with mocked API authority. These tests do not prove remote
host conformance, live tenant isolation, deployed AWS topology, registry/image
publication, publishable-key site binding against a live API, provider
execution, graph hydration, live OAuth, or customer beta readiness. The current
repository deliverable also includes closed read declarations/dispatch,
stable entity pagination, a bounded graph projection, and opt-in MCP OAuth
resource-server code. It remains experimental until the specific live gates
above are satisfied. Local checks do not prove live Auth0 setup, AWS apply,
supported OS keyring availability, or customer onboarding readiness.

## Protocol reference

- [Model Context Protocol 2026-07-28 specification release notes](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP TypeScript SDK support and migration guide for 2026-07-28](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28)
- [MCP TypeScript SDK server tools guide](https://ts.sdk.modelcontextprotocol.io/v2/servers/tools.html)
