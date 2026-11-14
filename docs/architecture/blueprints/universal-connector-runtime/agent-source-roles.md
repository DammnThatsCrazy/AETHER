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
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
source_hashes:
  "services/api/shared/integration_contracts/correlation.py": "sha256:466dea8b14bb0795db7b5177a0dbc9e488f66840d3fe512d8a9cff95b91cb684"
  "services/api/shared/integration_contracts/correlation_token.py": "sha256:bdc1861aad5f6d2afcb6f07ad0f9ab67e3f28bca7cfea49b11dda2aa0d0c9ae7"
  "services/api/shared/integration_contracts/source_roles.py": "sha256:002bcc66f8960fec8b92f7d63f8e665cd1a20b6679957bd9459be8d8d81d94ae"
  "services/api/shared/integration_contracts/streams.py": "sha256:cea0cdc53f61bbb90b57a627cd69f032d7cc8d1e2899b4099f04d2cf52ab36ac"
---

# Agent source roles and cross-role correlation

**State:** contract foundation implemented: source roles on stream descriptors,
role-pair join rules, and the Aether correlation token, with unit tests. No
provider beyond Shopify declares roles yet. No runtime path calls the join
rules, and no verdict reaches the graph. The rollout steps below are targets,
not claims that any agent platform is connected.

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

A vendor plays the roles its streams declare. Mapping the vendors in scope is
a design target; each needs the provider's actual API, scopes, and rights
confirmed before its module is built:

| Vendor | Streams by role (target) |
|---|---|
| Shopify | `system_of_record` (orders, inventory, products: the order streams are tagged today); `authority_issuer` (app and connector access grants) |
| Stripe | `system_of_record` (payments, refunds, disputes); `authority_issuer` (restricted key scopes) |
| Ramp | `system_of_record` (card transactions, bills); `authority_issuer` (card limits, spend policies, approvals) |
| Cloudflare | `network_observer` (AI gateway logs and agent traffic on tenant-owned zones) |
| OpenAI, Grok | `agent_runtime` (run, task, and tool-call records the tenant can export or emit); `tool_bridge` where the tenant hosts the MCP server |
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

## Delivery sequence

| Step | Outcome | Exit evidence |
|---|---|---|
| 1. Contracts (this change) | Roles on streams, role/pack rules, join rules, token | Unit tests for role validation, every verdict path, token tamper/expiry/tenant cases, and the no-vendor-names guard |
| 2. Persistence | Store verdicts as append-only decision records keyed by tenant and both observation IDs, with the policy version | Replay produces identical verdicts; no graph write yet |
| 3. Aether MCP bridge | Agents register tasks and receive tokens; key custody through the credential broker | Token issued, stamped into a sandbox payment's metadata, and joined |
| 4. Projection | A projector turns `linked` verdicts into lineage relationships (`INVOKED`, `PRODUCED_EFFECT`, `AUTHORIZED`) through the graph mutation gateway | Graph shows each edge's evidence class and verification state; candidates stay out of proof views |
| 5. Second vendor per role | Add one more agent runtime, network observer, and authority issuer | No change to `correlation.py`, lineage, graph mutation, Profile 360, or Value 360 |

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
