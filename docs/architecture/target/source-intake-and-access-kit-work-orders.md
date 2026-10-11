---
title: Source Intake and Access Kit Convergence Work Orders
slug: source-intake-access-kit-convergence
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "0.1.0"
---

# Source Intake and Access Kit Convergence Work Orders

**Program:** Source Intake and Access Kit Convergence<br>
**Target branch:** `Development`<br>
**Delivery shape:** one stacked branch and one draft PR; work orders become ordered commits in that PR<br>
**Baseline:** `Development` at `b3cc28093` (2026-10-11)<br>
**Architecture anchors:** merged PR #734 (architecture reset and tenant-safe runtime) and merged PR #733 (universal connector runtime)

## 1. Objective

Make Aether's observation and callable-capability surfaces work as one product without creating another ingestion runtime, graph authority, identity system, or control plane.

The program covers two related but separate paths:

```text
OBSERVATIONS
Web / Server / React Native / iOS / Android SDKs
Imports / uploads / providers / webhooks / MCP observe / CLI ingest
                         │
                         ▼
Source adapter and authentication
                         │
                         ▼
Canonical intake and admission
                         │
                         ▼
Durable evidence → normalization → identity authority
                         │
                         ▼
Governed graph mutation and projections
```

```text
CAPABILITY CALLS
REST / MCP / CLI / access SDK
                         │
                         ▼
Shared actor, tenant, client, and capability context
                         │
                         ▼
Existing authorization, policy, readiness, entitlement, and usage authorities
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
          OBSERVE       QUERY         ACT
         intake path   read APIs   governed action
```

An MCP or CLI request that submits observations is an intake operation. A read is a capability query. A mutation or external action goes through its owning domain authority. Transport selection never changes tenant, rights, identity, graph, or action authority.

## 2. Baseline and current completion

PR #734 and PR #733 are merged into `Development`. They provide substantial architecture and runtime foundations. Their existence does not prove that every source class or access surface follows the same complete path.

| Area | Current baseline | Work in this program |
|---|---|---|
| Architecture and migration inventory | Root architecture, authority boundaries, cutover inventory, and proof expectations exist in #734 | Use them as constraints; do not reproduce a second architecture reset |
| Provider runtime | Modular manifests, account and tenant routing, sync, webhooks, raw records, replay, normalization, and mutation intents exist in #733 | Prove provider events meet the common source/evidence contract; do not create another provider runtime |
| Shared ingestion | Observation envelopes, ingestion gateway, Bronze/outbox, replay, SDK routes, imports, and provider paths exist | Identify bypasses and converge the required entry paths on the canonical admission and persistence authority |
| Rights and identity | Rights decisions, source namespaces, identity resolution, and governed mutation primitives exist | Preserve authority decisions and references across source-to-graph handoffs; do not decide rights or canonical identity in clients |
| SDKs | Web, Server, React Native, iOS, and Android packages exist | Close contract and productization gaps with a shared cross-platform acceptance surface; package presence is not device or tenant graph proof |
| Aether Mobile | The first-party app has a client, navigation, projection, and continuation shell | Keep this as a graph consumer; beta readiness remains a separate product release gate from customer SDK ingestion |
| REST, MCP, CLI, Access Kit | Auth, policy, capability, billing, graph, and domain APIs exist in parts; this feature stack includes observed-capability reads, site-bound intake, bounded entity reads, and a safe account-context projection on the experimental CLI/local MCP bridge | Compose existing authorities behind usable, consistent calls. Do not expose new authority by adding a protocol adapter |
| Live end-to-end evidence | Repository-level contracts exist; provider-backed, customer SDK, and beta/device proof must be evaluated independently | Record exact evidence and limitations; never equate accepted ingestion or a passing unit check with graph or beta readiness |

### Delivery disposition for this PR

The initial implementation slice is complete for the supported routes and
contracts that have an existing owner. The following matrix distinguishes work
delivered here from continuation gates that require an authority, policy, or
live environment outside this branch.

| Work order | Disposition | Evidence or specific continuation gate |
|---|---|---|
| WO-0 | Complete | Current #734/#733 ownership and surface map reviewed against this tree; stale standalone source-governance runtime removed from scope. |
| WO-1 | Partial; provider and SDK handoffs aligned | V1/V2 SDK envelope parity and shared five-platform wire vector are implemented. CSV import rights admission remains gated on the product decision described under WO-1; no import rights behavior is changed in this PR. |
| WO-2 | Contract slice complete; device proof deferred | Five SDKs consume the shared minimum wire vector or native serialization helper. Device installation, store beta, and tenant graph hydration need device-lab/store credentials and a live tenant. |
| WO-3 | Supported interaction normalization complete; invocation deferred | Query and observe outcomes share one response envelope. A generic invoker waits for an owning capability execution API, grant model, and server authorization contract. |
| WO-4 | Supported API surface complete | Existing entity list/detail, account context, capability inventory, and canonical batch intake are composed with fixed projections and bounds. Broad graph search, export, and unsupported queries are not claimed. |
| WO-5 | Local MCP slice complete; remote MCP deferred | Local stdio initialize/tool listing and handler contracts are tested. Remote transport needs an owning delegated-auth/client identity flow and host conformance evidence. |
| WO-6 | Env-configured CLI slice complete; customer onboarding deferred | Safe reads and site-bound intake are implemented. Login, tenant switching, secure credential storage, and revocation need a supported delegated-auth owner and live user credentials. |
| WO-7 | Response correlation complete; cross-authority receipts deferred | Server-returned references are preserved. Billing, usage, audit, and receipt joins require their owners' stable correlation contracts. |
| WO-8 | Local contract proof complete; live/release proof deferred | Focused test results are listed under WO-8. Customer tenant, device, provider, hosted PR, and release evidence remain independent gates. |

This work starts from `Development` after #734/#733. PR #771 is an unrelated open draft and is not the base of this program.

## 3. Authority rules

1. **Intake owns admission and evidence creation.** Source-specific adapters may authenticate and validate their own protocol, then hand observations to the existing canonical ingestion path.
2. **Source identity is a contract, not a new service.** Reuse tenant scope, `source_namespace`, provider/connection/account identifiers, source-native record and revision identities, provenance, and existing durable event identities. Do not create a parallel `SourceInstance` database or source registry.
3. **Clients provide evidence and hints.** SDK, MCP, and CLI clients cannot decide canonical entities, rights, graph state, attribution, or action outcomes.
4. **Rights Authority decides rights.** Intake and access preserve the durable rights decision reference where required. A source adapter must not invent a contribution or retention authority.
5. **Graph writes remain governed.** Any source-backed graph mutation uses the existing mutation intent/gateway and domain authority. An access transport never writes the graph directly.
6. **Access composes authorities.** Authentication, tenant resolution, capability lifecycle, policy, readiness, entitlements, billing, approvals, receipts, and Kyber have existing owners. A new Access layer may route and normalize calls but must not fork these decisions.
7. **Observe, query, and act are distinct operations.** They have different scopes, data paths, receipts, and approval rules even when offered through the same client.
8. **One deliverable, ordered commits.** Work orders below are not separate PRs. The integrator keeps one PR against `Development`, initially draft, and stacks all accepted work as commits.

Capability names in existing APIs are not a callable registry. `/v1/capabilities`
is tenant-facing SDK/release feature discovery; `/v1/capability-catalog` is
observed third-party agent-access evidence. Neither grants or invokes an Aether
capability. The Access Kit invocation registry remains target-only until an
owning execution runtime and grant contract exist.

## 4. Shared interface contracts

These are semantic requirements. Before adding a schema, reconcile it with current contract sources and generated artifacts.

### 4.1 Source identity

Every admitted observation must be attributable to:

```text
tenant scope
source namespace and source class
provider identity/capability where applicable
connection and provider account where applicable
source-native record identity where available
revision/event identity and replay/idempotency identity
actor/client/surface provenance
rights decision reference where governed by Rights Authority
```

Fields may be optional only when the source class cannot provide them. Adapters must not fabricate stable identity from a raw record ID outside its declared namespace. The same raw ID under two tenants or namespaces remains distinct.

### 4.2 Capability interaction

Normalize REST, MCP, CLI, and access-SDK calls to one protocol-neutral interaction context before invoking an existing authority:

```text
request_id
tenant_id (resolved and validated server-side)
actor/principal and client identity
surface/protocol and protocol-specific request identity
capability ID and operation class (observe | query | act)
idempotency key when the operation supports replay-safe execution
trace/correlation context
```

That list describes the target request context. The current Access Kit
`interaction` response envelope includes only operation/status, request IDs,
HTTP status, and returned references; tenant and actor stay inside the server's
authenticated request context and are not echoed by the client adapter.

Do not trust a client-supplied tenant ID, scope, rights decision, or capability grant as authorization. Preserve the resolved policy/readiness/entitlement decision and usage/receipt identifiers returned by the authority. Durable work uses explicit task, approval, result, export, or receipt handles rather than hidden protocol session state.

## 5. Ordered work orders

Each work order produces a commit on the same PR branch. An acceptance condition may be marked **deferred** only with the specific missing dependency and evidence needed to resume it recorded in the PR.

### WO-0 — Baseline reconciliation and ownership map

**Owner:** integrator<br>
**Purpose:** replace assumptions from older blueprints with evidence from current `Development`.

- Map SDK, import, provider/webhook, MCP, CLI, REST, and first-party mobile paths to the authorities above.
- Inspect the #734 proof ledger and #733 runtime contracts at the current tree; record path and behavior rather than infer from the PR descriptions.
- Identify existing surface routes, schemas, auth modes, and durable stores; distinguish customer-facing packages from operator tooling and `tfmcp` infrastructure.
- Update this work-order page and the Access Kit target page with current/target ownership, sequencing, and proof boundaries.

**Acceptance:** each surface is labeled implemented, partial, target-only, or deferred with concrete evidence. No stale claim from a prior branch is stated as current fact.

### WO-1 — Canonical intake handoff and source identity

**Owner:** intake/SDK track<br>
**Dependencies:** WO-0<br>

- Reuse the canonical envelope and ingestion gateway. Route only adapters that currently bypass required admission, evidence, tenant, rights, provenance, sequencing, or idempotency controls.
- Align the stable public SDK batch contract behind its adapter; preserve supported client compatibility while converging server-side persistence and outbox behavior.
- Preserve source namespace and revision identity through Bronze/replay, normalization, identity evidence, and governed mutation handoff.
- Keep uploads/imports and provider/webhook adapters source-specific at the edge while making their downstream evidence and policy semantics consistent.
- Make replay, duplicate, rejected, partially admitted, and rights-blocked outcomes machine-readable and attributable to a request/source identity.

**Acceptance:** every changed adapter has an explicit end-to-end handoff to the canonical authority, and no client or adapter makes identity, rights, or graph decisions. Legacy route removal or storage consolidation requires the #734 migration proof, not a parallel destructive cutover.

**Current stack status:** partial. The SDK observation handoff and V1/V2 envelope parity are implemented, and provider admission remains behind the existing Rights Authority checks. The separate CSV import path was audited and found to admit tenant-owned imports without a durable Rights Authority decision reference. This branch does not change that path because the governing product rule is unresolved: require an explicit Rights Authority grant before import, or accept tenant-admin-approved data for tenant use while Rights Authority gates later reuse. Resume this sub-slice only after that policy decision, then prove that denied imports produce no Bronze, identity, or graph writes and that accepted records carry the durable decision reference through replay and governed mutation.

### WO-2 — SDK productization and mobile evidence

**Owner:** intake/SDK track<br>
**Dependencies:** WO-1<br>

- Compare Web, Server, React Native, iOS, and Android public APIs against the same observation and consent contract.
- Check the publishable-key remote configuration/manifest path, version policy, safe public fields, failure visibility, heartbeat, queue diagnostics, and disabled/kill-switch behavior. Fix only gaps verified in the current tree.
- Provide equivalent documented examples and a shared conformance fixture or generated contract vectors without creating independent client-side identity semantics.
- Distinguish build/package evidence from simulator/device installation and tenant graph hydration evidence.
- Keep the Aether first-party mobile app a consumer of governed reads and continuations; do not turn it into a customer SDK or graph writer.

**Acceptance:** the shared client contract and remaining per-platform gaps are explicit. Device/store beta claims require device-lab/TestFlight/Play evidence and privacy review; a source change alone cannot satisfy them.

### WO-3 — Protocol-neutral access invocation

**Owner:** access track<br>
**Dependencies:** WO-0<br>

- Inventory and reuse existing authentication, tenant resolution, capability catalog/lifecycle, policy, readiness, entitlement, usage, approval, audit, and receipt owners.
- Add only the missing normalization/router seam needed for protocol adapters to invoke an existing capability authority.
- Return a stable request/interaction envelope with machine-readable blocked, denied, degraded, and successful outcomes. Preserve the reason and authoritative receipt/reference.
- Start with read-only capability calls. Keep observe on WO-1 and reserve act for its owning action authority and approval policy.

**Acceptance:** an authorization decision cannot be bypassed by changing transport; tenant and actor are server-resolved; denied/degraded/success results carry consistent correlation and evidence references; no second policy, billing, or capability registry is introduced.

**Current stack status:** partial. A shared REST-client result now carries the
same protocol-neutral `interaction` envelope through CLI and MCP for supported
query and observe calls: operation, `successful | denied | blocked | degraded |
failed` status class, correlation/request IDs, HTTP status, and recognized
references returned by the API. Existing observation decisions and response
references remain intact in the original result data. Tenant and actor remain
server-resolved and are deliberately not projected into this client envelope.
This closes output normalization for the currently supported calls; it does
not add a generic capability invocation/router runtime. Dispatch, decision
receipt creation, and call-level authority aggregation remain deferred until
WO-0 identifies an owning runtime contract.

### WO-4 — REST/API access contract

**Owner:** access track<br>
**Dependencies:** WO-3<br>

- Define the actual supported read/query operations from existing domain APIs. Do not create a catch-all endpoint that silently changes query semantics.
- Normalize authentication context, problem/error responses, pagination, idempotency rules, and durable result handles where the underlying operation supports them.
- Treat OpenAPI and generated SDK artifacts according to repository contract-generation ownership; do not manually maintain duplicate schemas.
- Explicitly classify each endpoint as observe, query, or act and state its required capability and authority owner.

**Acceptance:** every newly exposed API path maps to an owning service and contract artifact, with scopes, error behavior, pagination, and tenant isolation defined. Unsupported capabilities are absent or explicitly unavailable, not mocked.

**Current stack status:** partial. The package exposes only the existing
`GET /v1/entities` first page and `GET /v1/entities/{entity_id}` detail reads
through the identity API; both remain protected by tenant middleware and the
route's `read` permission. The client caps list results at 50, accepts no tenant
override, and projects a fixed entity field allowlist. The API has no cursor or
offset for this route, so later pages and broad graph/search queries remain
unavailable. It also exposes a minimal projection of tenant-scoped `GET /v1/me`
for account context. API error code/status, correlation, and normalized
interaction outcomes are preserved by the CLI/MCP wrappers.
The observed-capability adapter drops malformed IDs, bounds projected string
lengths and integer counts, strips unrecognized fields including tenant ID,
and limits overview maps to 50 entries with `sampled` set on truncation.

### WO-5 — Aether MCP adapter

**Owner:** access track<br>
**Dependencies:** WO-3, WO-4<br>

- Verify current official MCP transport/version requirements at implementation time and pin the protocol behavior in the adapter documentation.
- Separate remote authenticated MCP from an optional local stdio bridge. The bridge delegates to the same remote Access/API authority and never stores a plaintext credential or exposes a new local data authority.
- Publish deterministic, scope-aware tool catalogs from supported capabilities; validate input/output schemas; route through WO-3; return handles for durable operations.
- Classify tools as observe, query, or act. Ship read-only/query tools first; ingestion tools must enter canonical intake and write/action tools must use their owning authority.
- Keep long-running jobs and approvals in explicit durable handles. Do not depend on protocol session memory for business state.

**Acceptance:** protocol conformance, authentication, tenant isolation, scope denial, deterministic listing, error mapping, and request correlation are documented and reviewable. MCP-specific tests and remote-client evidence are required before claiming MCP beta; they are not implied by API evidence.

**Current stack status:** partial. The pinned official TypeScript SDK local
stdio bridge exposes read-only `entities_list` and `entities_get` tools using
the same entity REST wrapper, alongside the previously implemented capability
inventory reads, `account_context`, and `observe` ingestion tool. Query and
observe calls share a normalized interaction envelope. Focused local
registration and handler contract tests cover schemas, output projection,
bounds, and mapped errors; a pinned-SDK stdio subprocess smoke test covers a
legacy `initialize` plus `tools/list` exchange without an API call. Remote MCP
HTTP, delegated OAuth, full host conformance, live tenant isolation, and
customer beta evidence remain deferred.

### WO-6 — Customer CLI adapter

**Owner:** access track<br>
**Dependencies:** WO-3, WO-4<br>

- Establish one supported customer CLI package and installation command using repository conventions.
- Implement browser/device login or the existing approved delegated-auth flow, tenant selection backed by server authorization, profile/context management, and token revocation behavior.
- Route commands through the same API/Access contract. Start with `auth`, `tenant`, `capabilities`, `readiness`, safe read/query commands, and `doctor`; ingestion and act commands follow the authorities and gates above.
- Provide JSON output for automation and readable terminal output for humans. Errors must retain machine-readable codes and correlation IDs.

**Acceptance:** CLI commands do not call graph stores directly or embed privileged service credentials; install/auth/tenant/read/denied paths are documented; revocation and credential storage have an explicit supported behavior.

**Current stack status:** partial. The customer CLI now supports
`aether entities list` and `aether entities show`, `aether account context`,
the observed capability inventory commands, and site-bound one-event
`aether ingest`. All reads use externally supplied `AETHER_API_KEY` and the
existing API; no graph store access or tenant override exists. Login, tenant
selection, secure credential storage, revocation flow, and live
denied/cross-tenant evidence remain target-only. A combined `doctor` command is
excluded: `/v1/health` and `/v1/ready` describe infrastructure,
`/v1/tenant/readiness` is a distinct launch-readiness evidence view, and
`/v1/me/usage` has its own availability semantics. Aggregating these locally
would invent a diagnostic or readiness authority; expose separate named reads
or wait for an owner API.

### WO-7 — Receipts, telemetry, and developer handoff

**Owner:** integrator with access track<br>
**Dependencies:** WO-3 through WO-6<br>

- Reuse existing audit, billing, usage, approval, and receipt systems. Add protocol/surface attribution only where the canonical event contract is missing it.
- Define which decisions are billable, included, rate limited, approval gated, or explicitly not yet priced; do not invent plan numbers in an adapter.
- Publish setup, capability discovery, errors, security boundaries, and examples for each surface. A developer portal is a later product surface unless a current portal authority exists.
- Keep MCP Apps, full webhook delivery, workflow automation, broad write/action tools, and marketplace features out of the first vertical slice unless a current owner and end-to-end proof already exist.

**Acceptance:** a call can be correlated across request, authorization, usage/audit, receipt, and result where those authorities support it; missing billing or observability integration is called out, not claimed complete.

**Current stack status:** partial. CLI and MCP now carry the shared normalized
interaction envelope and preserve any server decision, batch, receipt, rights,
or other recognized reference returned in the original response. This does not
create audit, usage, billing, or durable-receipt integration: none is inferred
or synthesized when the API response omits it. A full cross-authority trace
remains target-only pending correlation/receipt contracts from the owning
authorities.

### WO-8 — Cross-surface proof and readiness record

**Owner:** integrator<br>
**Dependencies:** WO-1 through WO-7<br>

- Build focused evidence that covers one supported observation source through the governed graph/read path and one read-only capability through REST, MCP, and CLI adapters.
- Cover tenant isolation, denied authorization, idempotency/replay, partial/degraded states, error mapping, and durable handle retrieval in the affected surfaces.
- Keep package, hosted CI, provider credentials, live tenant, device lab, staging, and store evidence separate. State exactly which proof exists and which is still required.
- Update owned/generated/source-linked documentation according to repository instructions before final PR readiness.

**Acceptance:** all claims map to retained evidence; no production, certification, customer-beta, or broad merge-readiness claim is made without its canonical release/PR evidence.

**Current stack status:** local contract proof is complete for this slice. The
Access Kit suite passes 23 tests, including mocked REST/CLI/tool-handler
contracts, terminal-control escaping, and a pinned-SDK stdio subprocess smoke
test for `initialize` plus `tools/list`. Focused Web (1), Server (3), React
Native (11), backend V1/V2 observation (37), import/provider admission (25 and
17 in their respective focused runs), and Swift package-build checks have
passed. The security diff review found and this stack remediates terminal
control injection from observed capability labels in human CLI output. Android
Gradle and Apple XCTest/device tooling are not available in this environment.
No live tenant, provider credentials, modern remote MCP host, or device/store
environment was available, so cross-tenant live calls, timeout behavior
against a service, ingestion-to-graph hydration, customer beta, and release
readiness remain unproven.

## 6. Single-PR commit sequence

The integrated feature branch is one commit stack against `Development`. The
work orders are tracked by the acceptance matrix above; commits are bounded
implementation slices and may satisfy more than one work order:

1. `docs: define source intake and access convergence work orders` — ownership, acceptance, and gates.
2. `feat(ingestion): align v2 sdk observation envelopes` — V1/V2 envelope parity.
3. `feat(access-kit): add site-bound CLI and MCP surfaces` — local adapter and canonical intake.
4. `build: lock Access Kit workspace dependencies` — workspace and lockfile integration.
5. `test(ingestion): verify v1 and v2 envelope parity` — server contract evidence.
6. `feat(access-kit): add bounded tenant entity reads` — supported read APIs and projections.
7. `test(sdk): add shared batch wire conformance vector` — Web, Server, React Native, iOS, and Android fixture.
8. `feat(access-kit): normalize interaction outcomes` — consistent outcomes and server-returned references.
9. `fix(access-kit): escape terminal controls in human output` — terminal-safe external labels and values.
10. Final documentation/evidence commit — actual verification disposition, generated/source-linked pages, and deferred gates.

All changes remain commits on this feature branch and one PR targeting `Development`.

## 7. Readiness boundaries

- A successful `/v1/batch` response proves intake acceptance only; it does not prove normalization, identity resolution, graph projection, queryability, or time-to-value.
- An SDK package build proves package viability only; it does not prove device lifecycle behavior or a customer tenant graph.
- A route or MCP tool that returns data does not prove equivalent authorization, rights, scope, readiness, billing, or receipt behavior across transports.
- A CLI or local bridge is not a privileged operator channel. It must use delegated/customer authorization and the same tenant policy as REST.
- Repository-local checks, hosted PR checks, live provider evidence, staging, mobile device evidence, and production readiness remain separate claims.
