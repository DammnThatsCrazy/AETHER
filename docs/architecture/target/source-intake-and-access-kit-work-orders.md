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

The implementation has closed the locally actionable remainder for six
carry-forward items. Code and repository-local proof are complete where an
existing authority supports them. The remaining entries are specific live
environment or owner-contract gates, not work represented as complete by
package presence or mocked tests.

| Carry-forward item | Delivered on this stack | Remaining proof or owner gate |
|---|---|---|
| CSV import rights admission | Commit requires allowed, durable Rights Authority decisions for `tenant_lake`, `write_tenant_graph`, and `tenant_insights`; source grant is checked and held through writes; decision refs are retained on attempts, Bronze, Silver, and governed graph mutations. Missing, denied, mismatched, revoked, or unavailable authority fails before data writes. | Run the migration and accepted/denied import against a live tenant with configured grants; local tests do not prove deployed policy or production data behavior. |
| SDK/mobile evidence | Web, Server, and React Native suites pass and exercise the shared wire fixture; iOS and Android fixture tests exist but are not runnable here. A macOS Swift package build passes. | Xcode is not installed (`xcode-select` points to Command Line Tools and `simctl` is absent), so `swift test` cannot load `XCTest`; Android has no Java runtime, Gradle, Android SDK, or ADB. Device install, store beta, and tenant graph hydration need those toolchains, credentials, and a live tenant. |
| Customer CLI onboarding | Auth0 Device Authorization login, `session_required` Aether session exchange, OS keyring storage, session context/list/revoke/logout, and local MCP reuse of that session are implemented. Reusable API-key fallback is refused. | Configure the Auth0 Native client and API audience, enable human sessions, and prove a real invited user login/session revoke and OS keyring on supported platforms. Tenant switching remains owner-gated because no membership chooser contract exists. |
| Remote MCP | Local stdio protocol uses the pinned official SDK, exposes bounded supported tools, and reuses the existing API/session authorities. | Remote HTTP transport, delegated client registration/auth, and host conformance need an owning product runtime/auth contract and an actual supported remote host. IAM/Auth must define OAuth resource discovery plus caller-bound token issuance or introspection returning principal, tenant membership, audience, scopes, expiry, and revocation. Opaque `sess_...` credentials are not treated as if they had OAuth claims. `tfmcp` remains operator infrastructure and is not repurposed. |
| Request-to-usage correlation | Batch responses join the middleware request ID to the actual usage event/evidence IDs and, when the existing audit write succeeds, to an `auditEventId` whose audit row also carries the authenticated request correlation. Allowed authoritative consent is stored as the actual receipt reference in each accepted observation's gateway-stamped Envelope-B privacy block. Access Kit preserves API-returned audit, usage, and evidence references. | The ordinary `WRITE` permission check still has no durable authorization-decision ID; it is not represented as a Rights Authority decision. General billing/payment receipts remain owned by their billing/payment flows. Audit persistence is best-effort after ingestion, and no missing IDs are synthesized. |
| Live tenant/provider proof | Local SDK, import, provider-admission, batch, CLI, MCP, and auth route contracts are covered by focused tests below. | Real provider credentials, customer tenant/API credentials, and a separately authenticated graph read are required to prove provider-to-graph hydration, tenant isolation, and time-to-value. No such credentials are configured in this environment. |

The work-order matrix below records the broader disposition for the
implemented surface and its still-open external proof.

| Work order | Disposition | Evidence or specific continuation gate |
|---|---|---|
| WO-0 | Complete | Current #734/#733 ownership and surface map reviewed against this tree; stale standalone source-governance runtime removed from scope. |
| WO-1 | Local implementation complete; live policy proof deferred | V1/V2 SDK envelope parity, existing provider admission, and CSV import Rights Authority admission are implemented. Two focused import suites pass (25 tests); deployed migration and active-grant behavior still need a live tenant. |
| WO-2 | Cross-platform contract evidence complete where tools are available; device proof deferred | Web 382, Server 97, and React Native 127 tests pass and exercise the shared wire fixture; the iOS XCTest target cannot resolve `XCTest`; Android Gradle/ADB are unavailable. The Swift package builds for the available macOS target. Device/store beta and tenant graph hydration remain separate gates. |
| WO-3 | Supported interaction normalization complete; invocation deferred | Query and observe outcomes share one response envelope. A generic invoker waits for an owning capability execution API, grant model, and server authorization contract. |
| WO-4 | Supported API surface complete | Existing entity list/detail, account context, capability inventory, and canonical batch intake are composed with fixed projections and bounds. Broad graph search, export, and unsupported queries are not claimed. |
| WO-5 | Local MCP slice complete; remote MCP deferred | Local stdio initialize/tool listing, read and observe handlers, session reuse, and error contracts are tested. Remote transport needs an owning delegated-auth/client identity contract and host conformance evidence. |
| WO-6 | CLI login and local onboarding implemented; live configuration and tenant selection deferred | Auth0 Device Authorization, revocable Aether session storage, context/list/revoke/logout, and safe reads/intake are implemented. Live Auth0/API setup and OS keyring proof remain; tenant switching needs a supported membership-selection API. |
| WO-7 | Supported request, consent, usage, and audit references joined | Batch request IDs correlate to returned usage/evidence IDs and tenant audit rows; accepted observations preserve the real allowed consent receipt in gateway-stamped Envelope-B. Durable per-request authorization decisions and general billing/payment receipt joins remain owner-gated. |
| WO-8 | Local proof complete for supported paths; live/release proof deferred | Exact focused results and toolchain limitations are listed under WO-8. Customer tenant, device, provider, hosted PR, and release evidence remain independent gates. |

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

**Current stack status:** the SDK and provider handoffs use their existing canonical authorities, and this stack now closes the CSV import admission gap with an explicit-grant rule. Every import commit resolves allowed durable decisions for tenant lake storage, graph write, and tenant insights against the submitted source and retains the active source grant through writes. Denial, missing or wrong-source grant, revocation, and resolver/store failure stop before import data writes. Import attempt, Bronze, Silver, and graph-mutation evidence retain their durable decision references. Focused commit/projector suites pass (25 tests total); live tenant grants and deployed migration execution remain unproven.

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
query, observe, and auth calls: operation, `successful | denied | blocked | degraded |
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

**Current stack status:** local stdio is complete for the supported read and
observe surface. The pinned official TypeScript SDK bridge exposes
`entities_list`, `entities_get`, capability inventory reads, `account_context`,
and `observe` through the existing REST authorities. It best-effort reuses a
stored human session for reads while preserving site-bound publishable-key-only
observe. Focused handler tests and a pinned-SDK stdio subprocess smoke test
cover schemas, projections, bounds, errors, initialization, and tool listing.
Remote MCP HTTP, delegated client registration, host conformance, live tenant
isolation, and customer beta evidence remain deferred to an owning runtime/auth
contract and supported remote host.

### WO-6 — Customer CLI adapter

**Owner:** access track<br>
**Dependencies:** WO-3, WO-4<br>

- Establish one supported customer CLI package and installation command using repository conventions.
- Implement browser/device login or the existing approved delegated-auth flow, tenant selection backed by server authorization, profile/context management, and token revocation behavior.
- Route commands through the same API/Access contract. Start with `auth`, `tenant`, `capabilities`, `readiness`, safe read/query commands, and `doctor`; ingestion and act commands follow the authorities and gates above.
- Provide JSON output for automation and readable terminal output for humans. Errors must retain machine-readable codes and correlation IDs.

**Acceptance:** CLI commands do not call graph stores directly or embed privileged service credentials; install/auth/tenant/read/denied paths are documented; revocation and credential storage have an explicit supported behavior.

**Current stack status:** CLI login and local customer operations are
implemented. Commands include bounded entity/account/capability reads,
site-bound one-event intake, Auth0 Device Authorization login, revocable
human-session context/list/revoke/logout, and native OS credential storage.
The SSO exchange explicitly requires a human session and refuses the reusable
API-key fallback. Local MCP can reuse the same stored session. Live Auth0
configuration, enabled API human sessions, invited-user login, and native
keyring proof remain deployment gates. Tenant switching remains target-only
until the account/session authority exposes membership selection. A combined
`doctor` command remains excluded because health, launch readiness, and usage
have separate owners and semantics.

### WO-7 — Receipts, telemetry, and developer handoff

**Owner:** integrator with access track<br>
**Dependencies:** WO-3 through WO-6<br>

- Reuse existing audit, billing, usage, approval, and receipt systems. Add protocol/surface attribution only where the canonical event contract is missing it.
- Define which decisions are billable, included, rate limited, approval gated, or explicitly not yet priced; do not invent plan numbers in an adapter.
- Publish setup, capability discovery, errors, security boundaries, and examples for each surface. A developer portal is a later product surface unless a current portal authority exists.
- Keep MCP Apps, full webhook delivery, workflow automation, broad write/action tools, and marketplace features out of the first vertical slice unless a current owner and end-to-end proof already exist.

**Acceptance:** a call can be correlated across request, authorization, usage/audit, receipt, and result where those authorities support it; missing billing or observability integration is called out, not claimed complete.

**Current stack status:** the supported request-to-usage join is implemented.
Both batch handlers pass the middleware request ID into canonical metering
correlation metadata and return the real meter event and evidence IDs when the
metering owner supplies them. After the batch is accepted, the route writes an
`ingestion.batch` row to the existing tenant Audit Ledger with the actual batch
ID, accepted/duplicate/rejected counts, available usage references, and the
authenticated request correlation. It returns the persisted `auditEventId`
only when that write succeeds; audit failure does not cause an already-durable
batch to be retried. Access Kit preserves the returned audit, usage, and
evidence references.

The ingestion consent evaluator now exposes an additive receipt-bearing result
while preserving its existing tuple API. For an allowed authoritative consent
decision, validation places the actual tenant-scoped receipt ID and purpose in
the gateway-stamped Envelope-B privacy block. Denied or unreceipted consent
does not receive a fabricated reference. This is consent evidence, not a
durable per-request authorization decision. The general `WRITE` permission
check still lacks a durable decision ID, and billing/payment receipts remain
with their owning flows; neither is synthesized by the adapter.

### WO-8 — Cross-surface proof and readiness record

**Owner:** integrator<br>
**Dependencies:** WO-1 through WO-7<br>

- Build focused evidence that covers one supported observation source through the governed graph/read path and one read-only capability through REST, MCP, and CLI adapters.
- Cover tenant isolation, denied authorization, idempotency/replay, partial/degraded states, error mapping, and durable handle retrieval in the affected surfaces.
- Keep package, hosted CI, provider credentials, live tenant, device lab, staging, and store evidence separate. State exactly which proof exists and which is still required.
- Update owned/generated/source-linked documentation according to repository instructions before final PR readiness.

**Acceptance:** all claims map to retained evidence; no production, certification, customer-beta, or broad merge-readiness claim is made without its canonical release/PR evidence.

**Current stack status:** focused local evidence is complete for the supported
surface. Current integrated results: Access Kit 43 tests; Web SDK 382; Server
SDK 97; React Native SDK 127; 90 combined tests across CSV import commit and
Silver projection, V1/V2 batch route, consent authority, observation envelope,
and golden-fixture suites; 59 tests across provider-rights admission, batch
identity/idempotency, and security governance; and 28 auth route/session tests
from the delegated CLI slice. The batch identity/idempotency suite contains 7
tests. The Access Kit security fix for terminal-control injection is also
covered. `swift build` passes for the available macOS target. `swift test`
cannot run because Xcode/XCTest and `simctl` are unavailable; Android has no
Java runtime, Gradle, Android SDK, or ADB.

The full local `verification-disposition` run at `32bb77cb1` selected 46 suites
and recorded 58 passing checks. Its sole failed check was the Docker-backed
integration lane, which stopped before tests because Docker Desktop was not
running. After starting Docker Desktop, `make integration-durable` passed all 9
tests in 21.79 seconds. The aggregate artifact remains `FAILED`; no single
aggregate PASS was recorded. No hosted checks were reported for the ready PR at
the time of this record. No live Auth0 setup, customer tenant/provider
credentials, remote MCP host, or mobile device/store environment is available.
Therefore live cross-tenant denial, tenant/provider-to-graph hydration, device
lifecycle, remote host conformance, customer beta, and release readiness remain
unproven until their specific environments are supplied.

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
10. `feat(ingestion): correlate batch usage evidence` — join middleware request IDs to existing usage and evidence records when returned.
11. `gate CSV imports through Rights Authority` — require durable purpose decisions and an active source grant before import writes.
12. `refactor(ingestion): use canonical correlation metadata` — use the metering contract's canonical metadata key.
13. `feat(access-kit): add delegated CLI auth and MCP session reuse` — Auth0 Device Authorization, revocable Aether sessions, OS credential storage, session management, and local MCP reuse.
14. `feat(governance): retain consent receipt references` — preserve actual allowed consent receipt evidence in the governed observation envelope.
15. `feat(ingestion): audit batch request correlation` — link completed batch responses to durable tenant audit entries when persisted.
16. Final documentation/evidence commit — reviewed source-linked pages, generated artifacts, focused proof, and exact external gates.

All changes remain commits on this feature branch and one PR targeting `Development`.

## 7. Readiness boundaries

- A successful `/v1/batch` response proves intake acceptance only; it does not prove normalization, identity resolution, graph projection, queryability, or time-to-value.
- An SDK package build proves package viability only; it does not prove device lifecycle behavior or a customer tenant graph.
- A route or MCP tool that returns data does not prove equivalent authorization, rights, scope, readiness, billing, or receipt behavior across transports.
- A CLI or local bridge is not a privileged operator channel. It must use delegated/customer authorization and the same tenant policy as REST.
- Repository-local checks, hosted PR checks, live provider evidence, staging, mobile device evidence, and production readiness remain separate claims.
