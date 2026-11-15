---
title: Agent Source Roles and Cross-Role Correlation
slug: blueprints/universal-connector-runtime/agent-source-roles
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
source_files:
  - services/api/shared/integration_contracts/source_roles.py
  - services/api/shared/integration_contracts/correlation.py
  - services/api/shared/integration_contracts/correlation_token.py
  - services/api/shared/integration_contracts/streams.py
  - services/api/actions/agent_correlation/engine.py
  - services/api/actions/agent_correlation/service.py
  - services/api/actions/agent_correlation/mcp_server.py
  - services/api/actions/agent_correlation/routes.py
  - services/api/actions/agent_correlation/projection.py
  - services/api/actions/agent_correlation/mappers/__init__.py
  - services/api/actions/agent_correlation/bindings.py
  - services/api/actions/agent_correlation/certification/runner.py
  - services/api/actions/agent_correlation/certification/record.py
  - services/api/actions/agent_correlation/certification/recorders.py
  - services/api/actions/agent_correlation/certification/fixtures.py
  - scripts/certify_agent_correlation.py
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
source_hashes:
  "scripts/certify_agent_correlation.py": "sha256:9d0bd1ef8e4e9100182487db07425f4acdb041bb55376b807d9f6dc4e3dcc5af"
  "services/api/actions/agent_correlation/bindings.py": "sha256:b345e8c5d707735c35965c9b802576495f5a9b220e3587a4377a4fff164827d6"
  "services/api/actions/agent_correlation/certification/fixtures.py": "sha256:13bef311e6a1c855939f7fa3edf8ef52bf6a6d97e1564ff2bf317773fce0a19f"
  "services/api/actions/agent_correlation/certification/record.py": "sha256:24b8570f342f378362ae5fdd3c2502b13d1dbcd2253c42202eff474ce599a37b"
  "services/api/actions/agent_correlation/certification/recorders.py": "sha256:c8056f3ba70415bc62b954bcdd7782cd63b48ef3d41b8c25c3dcc5e2fb554f2d"
  "services/api/actions/agent_correlation/certification/runner.py": "sha256:f6a73c32909978d0e554ac9888d3cdccca1c049c28d615e66ca90f8840620bd8"
  "services/api/actions/agent_correlation/engine.py": "sha256:c1a15719a8245a5713bf0c758ae7780eb1490f2d14bda7f33e7770bfc82e4e51"
  "services/api/actions/agent_correlation/mappers/__init__.py": "sha256:6f74fb42e57a1657fe5c142ccfb97944b3f0f6dcdbf3bc89f63fceb6c0faa27b"
  "services/api/actions/agent_correlation/mcp_server.py": "sha256:b20c135f39ae243eb5df8073f45df2a69c5ae8e00b635b2a84dd72ba3e6f4cde"
  "services/api/actions/agent_correlation/projection.py": "sha256:533ba53fd6932921a34e84667f6c7461eec8099906893da7f1852698ddbeb4bc"
  "services/api/actions/agent_correlation/routes.py": "sha256:6cc7bbf489ed282446b32fddbf8d8ca348aa26286b8173fb0160d723de5e7067"
  "services/api/actions/agent_correlation/service.py": "sha256:6756cb8aadd411875e3b1d37a1a0cbc79f704af3cc3803ae0f2efaf9fe361c60"
  "services/api/shared/integration_contracts/correlation.py": "sha256:3e0ab93ccd0bc9a1148f26e79aa4720fbc47f9cbdadf7d55b2db0a6e774dbb30"
  "services/api/shared/integration_contracts/correlation_token.py": "sha256:bdc1861aad5f6d2afcb6f07ad0f9ab67e3f28bca7cfea49b11dda2aa0d0c9ae7"
  "services/api/shared/integration_contracts/source_roles.py": "sha256:002bcc66f8960fec8b92f7d63f8e665cd1a20b6679957bd9459be8d8d81d94ae"
  "services/api/shared/integration_contracts/streams.py": "sha256:cea0cdc53f61bbb90b57a627cd69f032d7cc8d1e2899b4099f04d2cf52ab36ac"
---

# Agent source roles and cross-role correlation

**State:** implemented end to end in the API, with unit and route tests:

- **Contracts:** source roles on stream descriptors, role-pair join rules, and
  the Aether correlation token.
- **Runtime:** vendor mappers for Shopify, Stripe, Ramp, Cloudflare, OpenAI
  Agents, and the Aether MCP channel, plus stored tasks, observations, join
  keys, and append-only verdicts.
- **Correlation:** an engine that correlates every new observation and a
  projector that writes only proven links to the graph.
- **Interfaces:** REST routes and an MCP endpoint, mounted by default
  (`AGENT_CORRELATION_ENABLED`).

Account bindings come from verified provider connections where they exist
(see [Verified bindings](#verified-bindings)). Certification against
provider sandboxes is built (see [Sandbox certification](#sandbox-certification)),
and `stripe/event` is `sandbox_certified` from two real Stripe sandbox events
read through the Stripe connector (API version `2026-03-25.dahlia`):

- an existing `payment_intent.created`;
- a `payment_intent.succeeded` from a $1.00 test-card payment on a sandbox
  payment link. The link's PaymentIntent metadata carried a certification
  token, and the payment joined the certification task by
  `aether_correlation_token` (`DETERMINISTIC_BINDING`); replay reproduces that
  link. That recording showed that newer events name the owning
account in `context`, and the mapper now reads it. The other vendor kinds
report `uncertified` in `config/agent_correlation_certification.json` until
their sandboxes are recorded. Token issuance
needs `AGENT_CORRELATION_TOKEN_KEYS`.

## Why roles, not vendors

Agent platforms now reach business systems through connectors. Two published
examples, both read on 2026-11-14:

- **Shopify's connector for Grok.** The merchant installs it from Grok's
  connector settings and approves access in the Shopify admin. It reads by
  default and writes only after the merchant approves write access. It can
  change products, collections, inventory, percentage discounts, and theme
  copies that aren't live. Orders and customers are read-only, and it can't
  touch refunds, captures, or payments. It acts through the permissions of a
  staff account.
- **OpenAI Agent Builder with a Shopify MCP server.** A merchant builds their
  own agent and connects a Shopify MCP server from the Agent Builder
  marketplace. The published example looks up order status.

The same act is visible from two sides. The agent side knows that a bot
changed inventory because a person asked. The store side records that a staff
account changed inventory. A connector that reads only the store would credit
the staff member. A connector per vendor pair would need a new integration for
every combination of agent platform and business system.

Aether instead decomposes every vendor into **source roles**, declared per
stream, and joins observations by **role pair**. Adding a vendor adds one
provider module. It never adds join code.

## The five roles

| Role | What it proves | Example streams | Evidence ceiling on its own |
|---|---|---|---|
| `agent_runtime` | Who the agent is, its task, tool calls, delegation, the reason it gives | Grok Bot, OpenAI Agents, Claude, Cursor run records | `PROVIDER_ASSERTED` |
| `tool_bridge` | The call where an agent touched a system | A provider's AI connector or MCP server, the Aether MCP server | `DETERMINISTIC_BINDING`, but only through a returned object ID |
| `system_of_record` | The effect; owns its domain facts under the domain pack | Shopify orders and inventory, Stripe payments, Ramp transactions, GitHub pull requests | `PROVIDER_ASSERTED` for the actor it reports |
| `network_observer` | Request-level corroboration on infrastructure the tenant controls | Edge proxy and model gateway logs, signed agent requests | `CRYPTOGRAPHICALLY_ATTESTED`, but only for a verified signature |
| `authority_issuer` | What the agent was allowed to do | Connector write-access approvals, OAuth grants, spend limits, restricted keys | `VERIFIED_AUTHORITY` |

The evidence classes are `PRINCIPAL_EVIDENCE_CLASSES` from
`services/api/shared/agent_lineage/vocabulary.py`; no new vocabulary is
introduced. `cap_evidence(role, cls)` clamps a stream's self-reported evidence
to its role ceiling and never strengthens it.

A vendor plays the roles its streams declare. The runtime maps these today
(see [Runtime](#runtime)); live certification against each provider's sandbox
is still open:

| Vendor | Streams by role |
|---|---|
| Shopify | `system_of_record` (orders, inventory, products); `authority_issuer` (app and connector access grants) |
| Stripe | `system_of_record` (payments, refunds, disputes) |
| Ramp | `system_of_record` (card transactions, bills); `authority_issuer` (card limits, spend policies, approvals) |
| Cloudflare | `network_observer` (AI gateway logs and agent traffic on tenant-owned zones) |
| OpenAI | `agent_runtime` (traces) and `tool_bridge` (function spans) from the tenant's tracing export |
| Grok and other platforms | `agent_runtime` and `tool_bridge` through the Aether MCP endpoint |
| Aether MCP | `tool_bridge` (first-party; issues correlation tokens) |

## Stream contract

`StreamDescriptor.source_role` is optional, so existing descriptors keep
validating. When declared, the descriptor rejects a `domain_pack` the role
cannot emit:

| Role | Allowed domain packs |
|---|---|
| `agent_runtime`, `tool_bridge`, `network_observer` | `agent_activity` |
| `authority_issuer` | `authority` |
| `system_of_record` | `commerce`, `payments`, `communications`, `advertising`, `crm`, `analytics`, `operations` |

`agent_activity` carries the task, tool, delegation, and outcome vocabulary of
`packages/shared/agent.ts` and `agent-lineage.ts`. `authority` carries grants,
scopes, limits, approvals, and revocations, mapped to `AUTHORITY_TYPES`. Both
are contract/policy packs in the sense of the
[runtime architecture](runtime-architecture.md#53-domain-packs-and-provider-expansion):
not schedulers, credential stores, or graph writers. A runtime record can
never establish a commerce fact, and authority is always declared on its own
stream so its trust is explicit. `provider_source_roles(streams)` derives a
provider's roles from its streams.

Agent-runtime vendors should map into `agent_activity` through the existing
adapter classes in `services/api/intelligence/agent_behavior/taxonomy.py`
(`mcp`, `model_gateway`, `custom_orchestrator`, …). The provider runtime and
the agent adapters meet at the canonical event; this blueprint adds no third
ingestion path.

## Join rules

`services/api/shared/integration_contracts/correlation.py` holds one table,
keyed by unordered role pair. Each pair lists the join keys that are
meaningful between those roles:

| Join key | Matches when | Evidence class |
|---|---|---|
| `aether_correlation_token` | Both sides carry a token that verifies for the tenant and names the same task | `DETERMINISTIC_BINDING` |
| `shared_object_ref` | Same provider family, realm, account, object type, and ID, within the time window | `DETERMINISTIC_BINDING` |
| `provider_signed_request` | Same request ID, with at least one side's signature verified | `CRYPTOGRAPHICALLY_ATTESTED` |
| `provider_actor_ref` | Same namespaced actor (OAuth client, staff account) within the window | `PROVIDER_ASSERTED` |
| `infrastructure_ref` | Same namespaced infrastructure reference within the window | `INFRASTRUCTURE_CORRELATED` |
| `time_window` | The two observations fall within the window (default 5 minutes, maximum 1 hour) | `TEMPORALLY_CORRELATED` |

`correlate(left, right)` returns a `CorrelationVerdict`:

- `linked` only when the strongest matching key's class is in
  `PRINCIPAL_PROOF_EVIDENCE_CLASSES`. Weaker matches are `candidate`: weak
  evidence can cluster but never proves a link.
- `rejected` for a cross-tenant pair (always, before any key is read), when no
  key matched, or when both sides carry valid tokens for **different** tasks.
  Conflicting tokens are positive evidence of two acts and override timing.
- `no_rule` for an unregistered pair, which never falls back to timing. Two
  `system_of_record` observations are also `no_rule`: an order and its payment
  belong to domain reconciliation (see
  [canonical contracts §5](canonical-contracts.md#5-source-authority-and-reconciliation)).

An object, actor, or infrastructure match also requires proximity in time.
Without that, an agent that once read an order would bind to every later
change of it. A unit test keeps vendor names out of the join code itself.

## Correlation token

The strongest join needs no platform partnership. When an agent registers a
task through the Aether MCP tool bridge, Aether issues a token
(`issue_correlation_token`). The agent writes it wherever the downstream system
accepts free text or metadata: payment metadata, an order note, a pull request
body. A system-of-record stream that later delivers the object carries the
token, and `extract_correlation_tokens` finds it in free text.

The design follows the exact-reference pattern the commerce slice already uses
for Stripe PaymentIntent metadata (`aether_order_ref`, see the
[commerce reference slice](commerce-reference-slice.md)):

- **No identity in the token.** It leaves Aether and third parties can read
  it, so the payload holds only an opaque `ctk_` task reference, a key ID, and
  issue and expiry times.
- **Tenant bound by MAC.** HMAC-SHA256 over a domain separator, the tenant ID,
  and the payload. A token verifies only for the tenant of the connection that
  observed it, so a copy in another tenant's data never links.
- **Fail closed.** Parse errors, unknown keys, bad signatures, expiry, and
  future issue times return no task reference. Comparison is constant-time.
- **Bounded.** At most 256 characters, a 30-day maximum TTL, rotation by key
  ID, and at most eight candidates extracted from one text.
- **No environment reads.** Callers pass key material from credential custody.

## Worked example

A merchant asks a Grok bot to lower inventory for a product through Shopify's
connector.

| Observations available | Verdict |
|---|---|
| Shopify inventory change (staff account) only | No join; the effect is attributed to the staff account, with agent involvement unknown |
| + Grok run record 20 seconds earlier | `candidate`, `TEMPORALLY_CORRELATED`; never shown as proof |
| + tool-bridge record whose result names the same inventory level | `linked`, `DETERMINISTIC_BINDING` |
| + the same correlation token on the bot's task and the store note | `linked` by token, even hours apart |
| + write-access grant naming the connector's client | `candidate` `PROVIDER_ASSERTED` link to the authority; `VERIFIED_AUTHORITY` needs the issuer's own record |

## Runtime

`services/api/actions/agent_correlation/` holds the runtime. Every route is
tenant-scoped through the authenticated tenant context and observation-only.

| Route (`/v1/observability/agent/correlation`) | Purpose |
|---|---|
| `POST /tasks` | Register an agent task; returns the token and where to stamp it per system |
| `POST /observations/{provider}/{kind}` | Map one vendor record and correlate it; returns each link decision |
| `PUT /account-bindings/{family}` | Declare the tenant's account for a provider family (scopes agent-side object IDs) |
| `GET /tasks/{task_ref}/chain`, `GET /observations/{id}/chain` | The evidence-graded chain: observations in time order, proven links, unproven links, and gaps |
| `GET /catalog` | Mapped providers, kinds, and roles; whether token issuance is available |
| `POST /mcp` | MCP endpoint (JSON-RPC 2.0, streamable HTTP with JSON responses) |

The MCP endpoint offers four tools to any agent platform that accepts a custom
MCP server: `aether_register_task`, `aether_report_tool_call`,
`aether_report_outcome`, and `aether_get_task_chain`. Grok bots report this
way, because Grok exposes no public telemetry API.

| Provider / kind | Role | Record read | Join keys produced |
|---|---|---|---|
| `shopify` / `order`, `inventory_level`, `product` | `system_of_record` | Admin webhook payloads | Exact object refs; `shopify_app:` and `shopify_staff:` actors; tokens in the order note, note attributes, or tags |
| `shopify` / `order_graphql`, `inventory_level_graphql`, `product_graphql` | `system_of_record` | Admin GraphQL nodes (the provider runtime's GraphQL readers and the Shopify connector) | Translated to webhook field names and mapped by the kinds above, so one object revision yields one observation whichever path delivered it |
| `shopify` / `access_grant` | `authority_issuer` | The connection's capture of an app or connector approval | App and staff actors |
| `stripe` / `event` | `system_of_record` | PaymentIntent, Charge, Refund, Dispute events | Exact object refs (realm from `livemode`); tokens in metadata or description |
| `ramp` / `transaction` | `system_of_record` | Card transaction | Exact object ref; `ramp_card:` and `ramp_user:` actors; token in memo |
| `ramp` / `limit` | `authority_issuer` | Limit or spend program | Card and holder actors; token in display name |
| `cloudflare` / `ai_gateway_log` | `network_observer` | AI Gateway log | Token in metadata; gateway log ref |
| `cloudflare` / `http_request` | `network_observer` | Tenant-exported request row (`RayID`, `EdgeStartTimestamp`, signature nonce and check) | Signed request; Ray ID |
| `openai` / `export` | `agent_runtime`, `tool_bridge` | Agents tracing export batch | Trace token inherited by its function spans; object IDs in function input and output |
| `aether_mcp` / `task_registered`, `tool_call_reported`, `outcome_reported` | `agent_runtime`, `tool_bridge` | Aether MCP tool calls | Token; object IDs in input and output; signature nonce |

When a record arrives, the engine:

1. Stores it. A repeated delivery is a no-op.
2. Indexes its join keys: verified task refs, object refs, signed request IDs,
   actors, infrastructure refs, and its time bucket.
3. Finds candidates that share a key or fall in an adjacent bucket, capped at
   500.
4. Runs the join rules.
5. Appends linked, candidate, and conflicting verdicts.
6. Projects new linked verdicts.

The chain view lists, for each role, a gap message when no observation of that
role is linked. An answer never implies coverage it does not have.

## Verified bindings

A binding scopes provider object IDs to an account.
`actions/agent_correlation/bindings.py` resolves bindings from the provider
runtime's own records, using the same rule `object_refs` applies. An account
counts as verified only when all of these hold:

- The account and its connection belong to the tenant and share the provider
  identity.
- The connection was verified and is not revoked, disabled, failed, or waiting
  for reauthorization.
- The account is one the connection selected.
- Its external ID and realm are recorded.

A verified binding carries the account record as its `verification_ref`, and
every object ref scoped by it carries `account_verification_ref`.

| Situation | Effect |
|---|---|
| Object match where either side's scope is verified | `shared_object_ref`, `DETERMINISTIC_BINDING`, `linked` |
| Object match where neither scope is verified | `declared_object_ref`, `TENANT_DECLARED`, `candidate` |
| Family has verified accounts; a request or declaration names another account | Rejected (`422`) |
| Family has verified accounts; the realm differs | Rejected |
| Family has one verified account | It becomes the default for agent-side object IDs |

`GET /account-bindings` shows each family's effective binding and whether a
verified connection backs it. Today the provider runtime holds connections for
the commerce providers, Shopify among them. Stripe, Ramp, and Cloudflare
bindings are tenant-declared, so their object matches grade `TENANT_DECLARED`.
Token matches are unaffected: the token's MAC binds it to the tenant.

## Sandbox certification

A mapper kind is certified only by payloads the provider itself returned from a
sandbox account:

1. `python scripts/certify_agent_correlation.py record --provider <name>` runs
   the provider's recorder. Each recorder creates test activity and reads back
   the provider's own records:
   - **Stripe:** the account must report `livemode: false` first. The recorder
     creates a $1.00 PaymentIntent and a refund carrying a certification token,
     then reads their events.
   - **Shopify:** a draft product with the token as a tag, its inventory level,
     and an existing order if there is one. The product is deleted afterwards.
   - **Ramp:** read-only transactions and limits.
   - **Cloudflare:** read-only AI Gateway logs.
   - **OpenAI Agents:** one traced agent turn, when `openai-agents` is
     installed.
2. Each payload is mapped, then scrubbed to the fields mappers read. Free text
   is reduced to tokens and provider object IDs, so fixtures hold no customer
   data. If the scrubbed payload would map differently, the recording fails.
   The link decisions the payload made live against the certification task are
   stored with it, along with a certification-only key so they replay.
3. `python scripts/certify_agent_correlation.py replay` re-maps every fixture
   and writes `config/agent_correlation_certification.json`.

| Status | Meaning |
|---|---|
| `sandbox_certified` | Recorded fixtures exist and all replay |
| `failed` | A recorded fixture no longer maps the same way |
| `uncertified` | No recording yet |
| `not_recordable` | No provider read API returns this record (Cloudflare request rows come from tenant exports) |
| `first_party` | Aether's own MCP surface |

A test fails when a committed fixture stops replaying or the committed report
is stale. `GET /catalog` shows each kind's status. Credentials are read from
the environment variables listed in the script, or injected by a credential
proxy. Missing credentials skip a provider; they never certify it.

## Delivery sequence

| Step | Outcome | Exit evidence |
|---|---|---|
| 1. Contracts (done) | Roles on streams, role/pack rules, join rules, token | Unit tests for role validation, every verdict path, token tamper/expiry/tenant cases, and the no-vendor-names guard |
| 2. Persistence (done) | Append-only verdicts keyed by tenant, observation pair, policy version, and outcome | Repeated deliveries and repeated decisions write nothing new |
| 3. Aether MCP bridge (done) | Agents register tasks and receive tokens; keys from `AGENT_CORRELATION_TOKEN_KEYS` | An end-to-end test registers a task over MCP, stamps the token into Stripe metadata, and links it |
| 4. Projection (done) | `linked` verdicts become `CORRELATED_ACROSS_SOURCES` edges through the graph mutation gateway | Projected edges pass the graph write validator; candidates never project |
| 5. Vendors per role (done for six) | Shopify, Stripe, Ramp, Cloudflare, OpenAI Agents, Aether MCP | No change to `correlation.py`, lineage, graph mutation, Profile 360, or Value 360 |
| 6. Sandbox certification (harness built; Stripe recorded) | Record, scrub, and replay provider sandbox payloads; report per kind | `stripe/event` certified from real sandbox events, including the token round trip on a test payment; Shopify, Ramp, Cloudflare, and OpenAI become `sandbox_certified` once their sandboxes are recorded |
| 7. Verified bindings (done) | Bindings from verified provider connections; declared scopes graded `TENANT_DECLARED` | Tests cover verified, declared, spoofed, realm-mismatched, revoked, and cross-tenant cases |

Step 5 is the modularity test. A vendor that needs a change outside its own
module means the abstraction is leaking.

## Constraints carried from the runtime

- The provider runtime must not be enabled in any shared environment until the
  open race between rights admission or revocation and Bronze persistence is
  closed (see the #733 change record).
- Correlation reads only observations that passed raw-rights admission for the
  same tenant. A verdict is evidence, not a data-use grant.
- Nothing here changes identity resolution. A joined actor reference does not
  resolve a person; the identity service still owns that decision.
