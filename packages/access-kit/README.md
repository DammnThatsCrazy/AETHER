# Aether Access Kit

The Access Kit package provides a Node CLI and local MCP stdio bridge for bounded
customer operations:

- Read the observed third-party agent access inventory owned by Agent Access
  Intelligence.
- Read a bounded tenant entity page or one tenant entity through the existing
  identity API.
- Read a minimal tenant account context through the existing `/v1/me` route.
- List and revoke durable human sessions through existing tenant account routes.
- Sign in through Auth0 Device Authorization and keep the resulting revocable
  Aether session in the native OS credential store.
- Send one custom application observation through canonical `POST /v1/batch`.

The observed inventory is not an Aether callable-capability registry. Listing a
record neither grants nor invokes a capability. The Access Kit does not own
authentication, tenant selection, consent, policy, billing, graph access, or
action execution.

## Requirements and setup

Node.js 20 or later is required. In a workspace checkout, install the
repository dependencies and invoke the package scripts or workspace binaries.
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
| `aether entities ...` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `read` permission |
| `aether account context`, `aether auth context` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or a saved OS credential-store session, with `read` permission |
| `aether auth login` | `AETHER_AUTH0_DOMAIN`, `AETHER_AUTH0_CLIENT_ID`, `AETHER_AUTH0_AUDIENCE` |
| `aether auth logout` | Session stored by `aether auth login` |
| `aether auth sessions list` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or saved OS credential-store session, through the existing tenant session route |
| `aether auth sessions revoke SESSION_ID` | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`, or saved OS credential-store session, through the existing tenant session route |
| `aether ingest ...` | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |
| MCP inventory, entity, and account read tools | `AETHER_API_KEY` or `AETHER_SESSION_TOKEN` with `read` permission; otherwise a saved session from the OS credential store |
| MCP `observe` tool | `AETHER_PUBLISHABLE_KEY` and its bound `AETHER_SITE_ID` |

Set at most one explicit tenant read credential: `AETHER_API_KEY` or
`AETHER_SESSION_TOKEN`; an explicit credential takes precedence over a saved
session. Session tokens are sent using the API's existing `X-Session-Token`
header. When neither environment credential is set, the CLI and local MCP
process best-effort read the human session from the OS credential store.
Explicit environment credentials are never written there. MCP still starts if
the keyring is absent so a host configured only for publishable-key `observe`
can use it; tenant read tools then require an explicit credential or successful
keyring session load. `observe` uses only its site-bound publishable key and
never uses the stored human session.
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
aether entities list --entity-type organization --limit 25 --json
aether entities show entity_123 --json
aether account context --json
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

## Tenant entity reads

`entities list` and `entities show` call the existing read-protected
`GET /v1/entities` and `GET /v1/entities/{entity_id}` endpoints. Tenant scope
comes from `AETHER_API_KEY` or `AETHER_SESSION_TOKEN`; there is no tenant override. List calls request a
single first page with a default limit of 25 and a hard client maximum of 50.
The existing route has no cursor or offset, so the CLI does not imply complete
tenant enumeration when more rows exist.

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
`account_context`, and `observe`. Inventory, entity, and account-context read
tools use exactly one read credential (`AETHER_API_KEY` or
`AETHER_SESSION_TOKEN`), either explicitly supplied or loaded from the saved
OS credential-store session;
`observe` requires the publishable key and its bound site ID.
Each call makes a fresh REST request. The local stdio bridge can reuse the
saved CLI human session; there is no remote HTTP MCP server, remote MCP OAuth
flow, or MCP host configuration file in this package.

`observe` accepts `event_name`, `event_id`, `session_id`, `anonymous_id`,
non-negative `sequence`, and optional `properties`. It sends the same one-event
`track` batch as the CLI with `surface: "mcp"`. Its structured result preserves
the API batch counts, per-event statuses/reasons, batch ID, receive time, and
request ID. A rejected observation remains a server rejection.

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
`2.3.1`. The SDK `serveStdio` transport owns protocol framing and compatibility.
This package does not implement Streamable HTTP or an OAuth server.

## Implementation status

This is an experimental adapter slice. CLI Auth0 Device Authorization and
revocable human-session storage are implemented, but saved profiles, tenant
switching, token refresh, general query language, callable-capability registry,
arbitrary external tool execution, graph traversal, graph mutation, and action
dispatch remain outside scope. Entity reads are limited to the two existing
tenant-scoped REST operations described above. The owning REST authorities
remain the source of permission and policy decisions.
