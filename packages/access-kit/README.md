# Aether Access Kit

The Access Kit package provides a Node CLI, local MCP stdio bridge, and hosted
stateless MCP HTTP service for bounded customer operations:

- Read the observed third-party agent access inventory owned by Agent Access
  Intelligence.
- Read stable, bounded tenant entity pages, one entity, or a one-hop graph
  neighborhood through the identity and graph authorities.
- Discover the adapter's closed read-operation list and invoke a named read
  through the owning API. This list does not report tenant authorization.
- Read the evidence-qualified Agent360 behavior read model for one agent, or
  one reconstructed agent decision, through the agent behavior routes. These
  two operations declare `required_server_permission: agent:manage`.
- Read a minimal tenant account context through the existing `/v1/me` route.
- Read the non-billable Access Kit interaction count through the existing
  billing usage authority.
- Create and read back a bounded, durable continuation for one entity through
  the existing continuation authority, when that API feature is enabled.
- List and revoke durable human sessions through existing tenant account routes.
- Sign in through Auth0 Device Authorization and keep the resulting revocable
  Aether session in the native OS credential store.
- Send one custom application observation through canonical `POST /v1/batch`.
- Serve the supported tenant reads over stateless remote Streamable HTTP MCP.

The observed inventory is not an Aether callable-capability registry. Listing a
record neither grants nor invokes a capability. The Access Kit does not own
authentication, tenant selection, consent, policy, billing, graph access, or
action execution.

## Requirements and setup

Node.js 20 or later is required. In a workspace checkout, install the
repository dependencies and invoke the package scripts or workspace binaries.
After an approved npm release, install the customer CLI with
`npm install --global @aether/access-kit`; `aether` is the installed command.
Before that release, use the workspace checkout or the reviewed Aether AWS
container image described below. Release validation is available through the
manual `Publish Access Kit CLI and MCP` workflow; it defaults to a pack
dry-run. Before enabling a public release, configure the npm-production
environment with at least one required reviewer and an NPM_TOKEN. The
workflow fails closed if that reviewer rule is absent. The package is not yet
published.
CLI login requires a persistent native credential store: macOS Keychain,
Windows Credential Manager, or Linux Secret Service. Linux kernel keyutils is
not used as a fallback because it does not persist across restarts.
The native `@napi-rs/keyring` dependency is pinned exactly, and the workspace
lockfile includes its optional platform packages. Its availability still
depends on the host OS credential service; unit tests inject a fake store and
do not prove native Keychain, Credential Manager, or Secret Service access.

Set `AETHER_API_URL` to an API origin if using a non-default environment. It
defaults to `https://api.aether.io`; the client requires HTTPS except for
loopback development origins.

Supply only the credential required by the command being used:

| Command | Environment |
|---|---|
| `aether agents capabilities ...` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `read` permission |
| `aether entities ...`, `aether access invoke ...` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `read` permission |
| `aether agents behavior show`, `aether agents decisions show` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `agent:manage` permission |
| `aether continuations create` | A tenant API key or saved/revocable session with `write` permission and an enabled continuation API |
| `aether continuations show` | The same credential class with `read` permission and an enabled continuation API |
| `aether access operations list/show` | No credential; these describe adapter support only |
| `aether account context`, `aether auth context` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `read` permission |
| `aether usage summary` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, through `/v1/billing/usage/summary` |
| `aether auth login` | `AETHER_AUTH0_DOMAIN`, `AETHER_AUTH0_CLIENT_ID`, `AETHER_AUTH0_AUDIENCE` |
| `aether auth logout` | Session stored by `aether auth login` |
| `aether auth sessions list` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or saved OS credential-store session, through the existing tenant session route |
| `aether auth sessions revoke SESSION_ID` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or saved OS credential-store session, through the existing tenant session route |
| `aether ingest ...` | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |
| MCP inventory, entity, account, and continuation read tools | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN` with `read` permission; otherwise a saved session from the OS credential store |
| MCP `continuations_create` | API key or revocable session with `write` permission; the continuation API feature must be enabled |
| MCP `observe` tool | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |
| Hosted MCP tenant read tools | Per-request `Authorization: Bearer ak_...` or `Bearer sess_...`; a delegated Auth0 MCP OAuth token is accepted only after the opt-in identity and host configuration is applied |
| Hosted MCP `observe` tool | Per-request `X-Aether-Observe-Key: pk_...` plus `X-Aether-Site-ID`, alongside the read bearer |

Set at most one explicit tenant read credential: `AETHER_API_KEY` or
`AETHER_SESSION_TOKEN`; an explicit credential takes precedence over a saved
session. Session tokens are sent using the API's existing `X-Session-Token`
header. When neither environment credential is set, the CLI and local MCP
process best-effort read the human session from the OS credential store.
Explicit environment credentials are never written there. MCP still starts if
the keyring is absent so a host configured only for publishable-key `observe`
can use it; tenant read tools then require an explicit credential or successful
keyring session load. `observe` uses only its site-bound publishable key and
never uses the stored human session. Non-interactive CLI commands with an
explicit API key or human session skip OS credential-store lookup, which
supports headless CloudShell, CI, and ECS jobs; interactive `auth login` still
requires the native credential service.
The publishable key must be a `pk_` credential. The caller supplies the
site-bound ID separately. Aether resolves tenant scope from the key and checks
the required `X-Aether-Site` header against the key's binding. Do not set or
send a tenant ID override. The Access Kit uses a publishable key only for
`POST /v1/batch`, never for reads.

## Programmatic Access Kit client

The package also exports a small Node ESM/TypeScript client. Its named reads
use the same closed operation declaration and REST projections as the CLI and
MCP. Its continuation create/get methods call the existing continuation API.
The caller supplies one tenant credential from its secret manager; the client
does not accept tenant IDs or make graph/provider writes.

```js
import { createAccessClient } from '@aether/access-kit';

const access = createAccessClient({
  apiUrl: process.env.AETHER_API_URL,
  apiKey: process.env.AETHER_API_KEY,
});
const page = await access.entities.list({ limit: 25, offset: 0 });
const next = page.data.next_offset;
const neighborhood = await access.entities.neighborhood('entity_123', { limit: 25 });
const saved = await access.continuations.create({
  title: 'Review this entity',
  entityId: 'entity_123',
  idempotencyKey: 'review-entity-123-v1',
});
const readback = await access.continuations.get(saved.data.continuation_id);
```

`page` and `neighborhood` include `data`, `request_id`, optional
`api_request_id`, and the API-derived `interaction`. `operations.list()`
describes adapter support; `operations.invoke(id, input)` calls the owning API,
which decides permission and tenant scope per request. The public client sends
`access_sdk` as its accounting surface. Continuation create requires `write`
and an enabled server feature; the entity ID is an opaque reference at create
time and is reauthorized when later resolved. The idempotency key is scoped to
the authenticated principal and same request content. Observation intake
continues to use the Web, Server, and mobile SDKs or the explicit CLI/MCP
site-bound path.

For hosted MCP, the bearer authenticates the MCP request and permits its
tenant-scoped read surface; it does not grant observation-write authority or
select the ingestion tenant. The separate `pk_` key and bound site ID are sent
to `/v1/batch`, where the existing intake authority independently validates the
site binding and resolves the tenant. Treat both credentials as sensitive and
inject them from the remote host's secret manager.

## Agent access inventory

```sh
aether agents capabilities overview
aether agents capabilities list --provider example --limit 25 --json
aether agents capabilities show cap_0123456789abcdef01234567 --json
aether agents behavior show agent_123 --json
aether agents decisions show agent_123 decision_456 --json
aether entities list --entity-type organization --limit 25 --json
aether entities list --limit 25 --offset 25 --json
aether entities show entity_123 --json
aether entities neighborhood entity_123 --limit 25 --json
aether continuations create --title 'Review this entity' --entity-id entity_123 --idempotency-key review-entity-123-v1 --json
aether continuations show cont_0123456789abcdef0123456789abcdef --json
aether access operations list --json
aether access operations show entities.neighborhood --json
aether access invoke entities.neighborhood --input-json '{"entity_id":"entity_123","limit":25}' --json
aether account context --json
aether usage summary --json
aether auth context --json
aether auth login
aether auth logout
aether auth sessions list --limit 20 --json
aether auth sessions revoke SESSION_ID --json
```

The list API is capped at 100 rows per call. Filters and pagination are passed
to the existing tenant-scoped REST routes. Results describe observed external
agent access; they are not grants, Aether tools, or execution permissions.
The client drops rows with malformed capability IDs, bounds every projected
string, and accepts only safe non-negative observation counts. Overview counts
and grouping maps are validated; maps expose at most 50 bounded keys with
non-negative integer values, and the `sampled` flag is set when local
projection truncates a map.

## Agent behavior reads

`agents behavior show AGENT_REF` (operation `agents.behavior`, MCP
`agents_behavior`) calls `GET /v1/agent/agents/{agent_ref}/behavior`.
`agents decisions show AGENT_REF DECISION_ID` (operation `agents.decision`, MCP
`agents_decision`) calls
`GET /v1/agent/agents/{agent_ref}/decisions/{decision_id}`. Both are reads,
owned by `agent_behavior`, and the API requires `agent:manage`; operation
metadata reports that as `required_server_permission` (every other operation
declares `read`). Agent refs and decision IDs are 1 through 256 characters and
inputs are strict.

The read models are backend-owned. Every section states `available`,
`partial`, or `unavailable` with its evidence and reason, and the client
passes them through unaltered after checking the envelope (matching agent ref;
a decision must belong to the requested agent). Inferred behavior is never a
verified fact and a source-reported agent ref is not an identity resolution.
The MCP tools are not advertised to delegated read-only OAuth tokens, which
cannot carry `agent:manage`.

## Tenant entity reads

`entities list`, `entities show`, and `entities neighborhood` call the
read-protected identity and graph APIs. Tenant scope comes from the credential;
there is no tenant override. List calls default to 25 and cap at 50. Pass
`--offset 0` for the first stable page and follow `next_offset` until it is
null. The route orders explicit-offset pages by durable entity ID. `show` and
`neighborhood` require an entity in the authenticated tenant; neighborhood
traversal is one hop with at most 50 neighbors and 100 returned edges.

Entity responses contain only `entity_id`, `entity_type`, `display_name`,
`parent_entity_id`, `created_at`, and `updated_at`. The client omits
`tenant_id`, duplicate repository IDs, arbitrary `metadata`, and unrecognized
fields. String lengths are bounded before they are returned. This is a named
entity read, not graph search, traversal, identity resolution, or a governed
write. Successful JSON responses include request IDs; with `--json`, CLI
errors are emitted as an `error` object with the API status/code and request
IDs when supplied by the API.

## Account context

`aether account context` calls existing tenant-scoped, read-protected
`GET /v1/me`. Its fixed projection contains account name, plan ID/display name
and limits, billing subscription status/period end, API key count, and the
caller admin flag. It omits tenant and graph IDs, contact email, Stripe
customer IDs, and all unrecognized fields. This read reports account context;
it does not assess ingestion, graph, or product readiness.

`aether auth context` aliases the same account projection. Session list and
single-session revoke call the existing tenant-scoped `GET /v1/me/sessions`
and `DELETE /v1/me/sessions/{session_id}` routes. The list projection returns
only session ID, status, credential class, and expiry timestamps; it drops
principal IDs, token hashes, metadata, and unknown fields. Revocation passes
the supplied session ID to the API and preserves the server response and
request IDs. The adapter does not create, choose, or locally revoke a session.

### Usage accounting and receipts

`aether usage summary` calls `/v1/billing/usage/summary` and projects only the
current billing period and `access_interaction` count. Authenticated CLI and
MCP reads for account context, sessions, entities, and the observed capability
catalog are recorded by the API's existing audit ledger and usage metering
service. The API returns durable audit and usage event IDs in response headers;
CLI/MCP results preserve those IDs in `interaction.references`.
`X-Aether-Access-Surface` is a non-authoritative attribution label (`cli`,
`mcp_stdio`, or `mcp_http`); it never grants access or changes tenant scope.

The Access Kit dimension is explicitly non-billable until Aether configures
and approves a price. The Console's Usage & Plan page shows it as “Access Kit
interactions (non-billable)”; the CLI and MCP summary expose no other usage
dimensions, tenant IDs, or event IDs. Calling the usage summary itself is not
metered, so reading the counter does not increase it.

### Customer Access Kit webhooks

From **Settings → Webhooks**, add an HTTPS endpoint and select the Access Kit
interaction events it should receive: `access.interaction.completed`,
`access.interaction.blocked`, or `access.interaction.failed`.

The endpoint is inactive until its signed test delivery succeeds. Aether
generates the signing secret and displays it once at creation or rotation;
store it in your receiver's secret manager. Rotating a secret disables the
endpoint until it passes another test. Each delivery uses the durable
notification outbox with retries and dead-letter handling; delivery history is
available in the Console.

Event bodies contain the event ID/type/time, surface label, capability ID,
outcome, HTTP status, API request ID, audit event ID, and usage event ID when
available. They omit request/query bodies, entity IDs, and response content.
Destinations are checked for public HTTPS and revalidated with DNS-pinned
delivery; redirects and private/metadata destinations are blocked. Webhook
configuration and delivery history remain tenant-scoped.

### CLI Auth0 sign-in

`aether auth login` uses Auth0 Device Authorization through a dedicated public
Native application provisioned by the existing Terraform Auth0 module:

```sh
export AETHER_AUTH0_DOMAIN=your-tenant.us.auth0.com
export AETHER_AUTH0_CLIENT_ID="$(terraform -chdir=infra/aws/terraform output -raw aether_cli_auth0_client_id)"
export AETHER_AUTH0_AUDIENCE=https://api.aether.io
```

The CLI opens Auth0's verification URL and prints the short user code. It does
not start a loopback listener, collect an Auth0 password, request offline
access, save Auth0 access/refresh tokens, or accept a tenant ID. Auth0's device
grant returns an access token, which the CLI exchanges at
`POST /v1/auth/sso/callback` with `session_required: true`. Aether selects the
server-authorized tenant membership. If the API does not advertise human-session
support or returns a legacy `api_key`, the CLI stops without saving or
displaying that key. The API guard refuses session-required exchanges before
identity or tenant provisioning when human sessions are disabled.

Only the Aether session token and session ID are stored by the native OS
credential store. On Linux the CLI explicitly requires Secret Service. If the
store is unavailable, login stops before contacting Auth0. If the session is
issued but cannot be saved, the CLI attempts to revoke it through
`DELETE /v1/me/sessions/{session_id}` using the in-memory session token, then
fails without printing that token. `aether auth logout` revokes the saved
session through that same tenant-scoped route before removing the local OS
credential entry. Server revocation and expiry remain authoritative.

Terraform must be applied to create the Auth0 Native client and publish the
public output. The Auth0 tenant must have the applicable login connection
configured, and the Aether API must run with human sessions enabled. External
provider sign-in still depends on provider credentials/configuration for that
Auth0 environment. Those live Auth0 and API checks are deployment gates; local
tests use mocked endpoints. No tenant chooser exists: membership and invitation
resolution stay server-owned. Existing human sessions can still be provided as
`AETHER_SESSION_TOKEN` through a host secret-injection mechanism.

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
`agent_access_capabilities_overview`, `entities_list`, `entities_get`,
`account_context`, `usage_summary`, and `observe`. Inventory, entity, account,
and usage read tools use exactly one read credential (`AETHER_API_KEY` or
`AETHER_SESSION_TOKEN`), either explicitly supplied or loaded from the saved
OS credential-store session;
`observe` requires the publishable key and its bound site ID.
Each call makes a fresh REST request. The local stdio bridge can reuse the
saved CLI human session.

`observe` accepts `event_name`, `event_id`, `session_id`, `anonymous_id`,
non-negative `sequence`, and optional `properties`. It sends the same one-event
`track` batch as the CLI with `surface: "mcp"`. Its structured result preserves
the API batch counts, per-event statuses/reasons, batch ID, receive time,
request ID, and any server-returned `usageEventId`, `usageEvidenceId`,
`auditEventId`, and actual `consentReceiptIds`. Those correlation references
are optional because the owning authority may not return them. A rejected
observation remains a server rejection.

`usage_summary` returns the current-period non-billable Access Kit interaction
count through `/v1/billing/usage/summary`. It is available on local stdio and
hosted MCP and does not expose unrelated billing dimensions. Neighborhood
results project only IDs, types, labels, and relationship types; the
`limit_reached` and `edges_truncated` flags state when a result hit a bound.

Entity tool errors set MCP `isError` and include a JSON `error` object with the
API status/code and request IDs when available.

Each supported CLI JSON result and MCP structured result carries the same
`interaction` object from the shared REST client. It includes `version`,
`operation` (`query`, `observe`, or `auth`), `status_class`, `request_id`, optional
`api_request_id`, `http_status`, and recognized server-returned `references`.
401/403 map to `denied`; 423/429 to `blocked`; 206/207 and server responses
with rejected observations to `degraded`; transport/contract failures to
`failed`; other valid responses to `successful`. Original server response data
is preserved, including per-event decisions and any returned batch, receipt,
rights-decision, task, result, approval, usage, or audit reference. The client
does not synthesize missing references or reinterpret server decisions.

There is no combined `doctor` command. `/v1/health` and `/v1/ready` are
infrastructure probes, `/v1/tenant/readiness` is an independent launch-readiness
view, and `/v1/me/usage` is a separate usage view that can report
`insufficient_evidence`. Combining them in the CLI would create an unsupported
diagnostic/readiness authority. Account context must not be presented as a
readiness signal.

The package uses the official `@modelcontextprotocol/server` SDK pinned to
`2.3.1`. The SDK owns stdio framing and remote protocol dispatch.

## Hosted Streamable HTTP MCP

Build the standalone Access Kit image from the repository root:

```sh
docker build -f packages/access-kit/Dockerfile -t aether-access-kit .
docker run --rm -p 8080:8080 \
  -e AETHER_API_URL=https://api.aether.io \
  -e AETHER_MCP_ALLOWED_HOSTS=mcp.example.com \
  -e AETHER_MCP_ALLOWED_ORIGINS=https://console.example.com \
  aether-access-kit
```

The container listens on port `8080` and serves MCP at
`/v1/access/mcp` by default. Set `AETHER_MCP_PATH` to change the exact path;
the default avoids the `/mcp*` route reserved for the internal Terraform MCP
operator. Put the container behind TLS termination at the AWS edge. The service
does not need or accept a shared tenant API key in its environment. Configure
`AETHER_MCP_ALLOWED_HOSTS` as a comma-separated list of exact hostnames without
ports or wildcards. `AETHER_MCP_ALLOWED_ORIGINS` is an optional comma-separated
list of exact HTTPS origins (HTTP is accepted for loopback development only).
Server-to-server MCP clients may omit `Origin`; browser requests must match the
origin allowlist. No wildcard CORS is enabled.

Every POST to the MCP path, including protocol discovery and `tools/list`,
requires an `Authorization: Bearer` containing an existing Aether secret API
key (`ak_` plus 24 alphanumeric characters), revocable human session
(`sess_` plus 48 lowercase hexadecimal characters), or an opt-in Auth0 token
issued for the exact hosted MCP resource with `access_kit:read`. The handler validates the
credential against the existing tenant-scoped `GET /v1/me` API for each HTTP
request, then passes the same request-scoped credential to each tool's existing
API route. Aether revalidates authorization and tenant scope on every API call.
OAuth validation also checks the signing key, issuer, audience, expiry, scope,
and durable active Aether membership. An OAuth token is accepted only on named
read routes; it cannot invoke `observe`, revoke a session, or select a tenant.
The hosted MCP service signs each downstream OAuth read using an ECS-injected
`AETHER_MCP_SERVICE_ASSERTION_KEY`. The backend requires that short-lived
assertion before validating an MCP-audience token. Setting an Access Kit
surface header on public REST cannot make that token usable there. API keys
and Aether sessions continue through their existing paths.
The tools are bounded to the declared read operations, entity pages and
neighborhood, account context, observed third-party agent inventory, and (for
API key and session callers with `agent:manage`) agent behavior reads.
No caller-supplied tenant ID is accepted.

`observe` appears in the remote tool list only when that MCP request also
provides both `X-Aether-Observe-Key` and `X-Aether-Site-ID`. The first must be
the `pk_` publishable key for that site; the pair is request-scoped and is
forwarded only to the existing `POST /v1/batch` route. Aether checks the key's
site binding and resolves the tenant. If both headers are absent, `observe` is
omitted; a partial or malformed pair is rejected. The MCP service stores and
logs neither credential. The caller's secret API key or session remains
required for every MCP protocol request, including an `observe` call.

The transport is modern-only for MCP protocol revision `2026-07-28` and uses
the SDK's required `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name`
validation. It is stateless and does not create an MCP session. It supports the
JSON request/response tools in this package, not long-lived SSE streams.
When OAuth is enabled, the service publishes RFC 9728 protected-resource
metadata at `/.well-known/oauth-protected-resource/v1/access/mcp` (and the
root well-known path) and advertises the configured Auth0 authorization server.
Unauthorized responses include a bearer challenge with the metadata URL and
read scope. A validated OAuth token missing `access_kit:read` receives an
`insufficient_scope` challenge; unrelated permission denials do not claim a
missing scope. Auth0 remains the authorization server; the Access Kit does not
issue tokens. Public client registration, Client ID Metadata Document support
by the configured Auth0 tenant, user consent, and actual host sign-in remain
deployment and interoperability gates. Open Auth0 dynamic client registration
is deliberately disabled. Without OAuth configuration, a host supplies an
Aether API key or session on every request.

Container health probes are independent of customer credentials:

| Route | Contract |
|---|---|
| `GET /healthz` | Liveness: `200 {"status":"ok"}` while the process responds |
| `GET /readyz` | `200 {"status":"ready","path":"/v1/access/mcp"}` when API origin, MCP path, and allowed-host configuration are valid; otherwise `503` |

Readiness checks configuration, not live Aether API connectivity or a
customer tenant. The remote handler verifies Aether reachability and the
caller's current access on each MCP request.

The same image includes the standalone CLI. In an Aether-authorized CloudShell
or ECS task, inject the credential through a secret-backed environment
variable and run a CLI command directly; no interactive login or OS keyring
service is required for explicit environment credentials:

```sh
docker run --rm \
  -e AETHER_API_URL=https://api.aether.io \
  -e AETHER_API_KEY \
  aether-access-kit node ./bin/aether.js entities list --json
```

Use `AETHER_SESSION_TOKEN` instead of `AETHER_API_KEY` when using a revocable
human session. With a workspace checkout, install the locked package
dependencies and run `node packages/access-kit/bin/aether.js ...`. Let the
cloud secret manager inject the value; do not paste it into shell history,
print it, write it to a file, or pass it as a literal command argument. The
CLI does not log the credential. After public npm release, a customer-owned
CloudShell, ECS task, Lambda container, CI job, or other Node 20+ cloud runner
can install the CLI without ECR access:

```sh
npm install --global @aether/access-kit
aether entities list --json
```

Configure `AETHER_API_KEY` or `AETHER_SESSION_TOKEN` using that platform's
secret-injection mechanism. This package release is not complete until the
Publish Access Kit CLI and MCP workflow publishes the reviewed version after
its npm-production reviewer gate. For ECS, use the task definition's Secrets Manager/Parameter Store
secret mapping instead of a plaintext environment value in the task
definition.

In a cloud runner with Docker and read access to the published ECR image, pin
the same reviewed digest the MCP service uses and override its default HTTP
server command to run the CLI:

```sh
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
ACCESS_KIT_IMAGE="${ECR_REGISTRY}/aether-access-mcp@${ACCESS_MCP_IMAGE_DIGEST}"
docker run --rm \
  -e AETHER_API_URL=https://api.aether.io \
  -e AETHER_API_KEY \
  "$ACCESS_KIT_IMAGE" node ./bin/aether.js entities list --json
```

Set `AWS_REGION`, `ACCESS_MCP_IMAGE_DIGEST`, and the Aether key through the
runner's environment/secret manager. The image runs as the non-root `node`
user. The MCP ECS service itself has no caller credential; do not add one to
its task definition.

### V1 live acceptance

After a deployment is available, run the acceptance runner against an explicitly
selected API and, optionally, hosted MCP endpoint. It makes tenant-scoped
read-only usage and one-row entity-list calls, checks returned audit and usage
references, verifies the count advances, and checks that hosted MCP exposes and
runs `entities_list` and `usage_summary`:

```sh
export AETHER_API_URL=https://api.example.com
export AETHER_API_KEY # inject through the host's secret manager
export AETHER_MCP_URL=https://mcp.example.com/v1/access/mcp # optional
npm run acceptance:v1 --workspace @aether/access-kit
```

The runner requires `AETHER_API_URL` explicitly and performs no deployment,
staging lifecycle, webhook creation, graph write, or action. Omitting
`AETHER_MCP_URL` skips only the remote MCP checks; local stdio and API tests
remain covered by the package test suite. Treat production live evidence
separately from local tests and run this only against an environment where the
supplied read credential is authorized.

## V1 scope and remaining productization

V1 is a usable, bounded access adapter across the API, CLI, local stdio MCP,
and stateless hosted Streamable HTTP MCP. It supports tenant account context,
observed capability inventory, tenant-scoped entity reads, human-session
management, Auth0 Device Authorization, site-bound canonical observation
ingestion, non-billable Access Kit interaction accounting, and signed outbound
interaction webhooks. Audit and usage receipts come from the existing API
authorities; each surface is an adapter and cannot grant itself tenant access
or write directly to the graph.

The post-773 slice adds a closed read-operation declaration, explicit read
invocation, entity pagination, a bounded one-hop graph read, and opt-in
delegated OAuth resource support. It does not implement saved named profiles,
tenant switching, token refresh, a general graph query language, arbitrary
external tool execution, graph mutation, action dispatch, exports, or
long-running task/result handles. OAuth client onboarding and actual host
conformance, mobile SDK device parity, and desktop bridge integration remain
separate work and proof gates.

The package is configured for public npm distribution but has not been
published. Its release workflow validates and preserves the exact main-branch
tarball; public publication requires the npm-production environment to have at
least one required reviewer and an NPM_TOKEN, followed by an authorized
release run. The AWS image is published to Aether's private ECR and is
available only to principals granted pull access in that account. It serves
the hosted MCP runtime and Aether-owned AWS runners, not cross-account
distribution. Customer-owned AWS and other cloud jobs can install the npm
package after release and inject a tenant API key or revocable session from
their secret manager. The live acceptance runner is included in the package,
but it must be run against an explicitly selected, deployed API and (for the
remote MCP checks) a deployed hosted MCP endpoint. Local package and backend
checks do not claim production readiness or substitute for that environment
evidence.
