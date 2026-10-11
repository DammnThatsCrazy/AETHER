---
title: Source Intake and Access Kit Convergence Work Orders
slug: source-intake-access-kit-convergence
section: architecture
visibility: I
audience: [architect, dev-senior, product]
status: experimental
since_version: "0.1.0"
---

# Source Intake and Access Kit Convergence Work Orders

**Program:** Source Intake and Access Kit Convergence  
**Target branch:** `Development`  
**Delivery shape:** one stacked branch and one draft PR; work orders become ordered commits in that PR  
**Baseline:** `Development` at `b3cc28093` (2026-10-11)  
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
| REST, MCP, CLI, Access Kit | Auth, policy, capability, billing, graph, and domain APIs exist in parts; the current Access Kit target page is only a sketch | Compose existing authorities behind usable, consistent calls. Do not expose new authority by adding a protocol adapter |
| Live end-to-end evidence | Repository-level contracts exist; provider-backed, customer SDK, and beta/device proof must be evaluated independently | Record exact evidence and limitations; never equate accepted ingestion or a passing unit check with graph or beta readiness |

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

Do not trust a client-supplied tenant ID, scope, rights decision, or capability grant as authorization. Preserve the resolved policy/readiness/entitlement decision and usage/receipt identifiers returned by the authority. Durable work uses explicit task, approval, result, export, or receipt handles rather than hidden protocol session state.

## 5. Ordered work orders

Each work order produces a commit on the same PR branch. An acceptance condition may be marked **deferred** only with the specific missing dependency and evidence needed to resume it recorded in the PR.

### WO-0 — Baseline reconciliation and ownership map

**Owner:** integrator  
**Purpose:** replace assumptions from older blueprints with evidence from current `Development`.

- Map SDK, import, provider/webhook, MCP, CLI, REST, and first-party mobile paths to the authorities above.
- Inspect the #734 proof ledger and #733 runtime contracts at the current tree; record path and behavior rather than infer from the PR descriptions.
- Identify existing surface routes, schemas, auth modes, and durable stores; distinguish customer-facing packages from operator tooling and `tfmcp` infrastructure.
- Update this work-order page and the Access Kit target page with current/target ownership, sequencing, and proof boundaries.

**Acceptance:** each surface is labeled implemented, partial, target-only, or deferred with concrete evidence. No stale claim from a prior branch is stated as current fact.

### WO-1 — Canonical intake handoff and source identity

**Owner:** intake/SDK track  
**Dependencies:** WO-0

- Reuse the canonical envelope and ingestion gateway. Route only adapters that currently bypass required admission, evidence, tenant, rights, provenance, sequencing, or idempotency controls.
- Align the stable public SDK batch contract behind its adapter; preserve supported client compatibility while converging server-side persistence and outbox behavior.
- Preserve source namespace and revision identity through Bronze/replay, normalization, identity evidence, and governed mutation handoff.
- Keep uploads/imports and provider/webhook adapters source-specific at the edge while making their downstream evidence and policy semantics consistent.
- Make replay, duplicate, rejected, partially admitted, and rights-blocked outcomes machine-readable and attributable to a request/source identity.

**Acceptance:** every changed adapter has an explicit end-to-end handoff to the canonical authority, and no client or adapter makes identity, rights, or graph decisions. Legacy route removal or storage consolidation requires the #734 migration proof, not a parallel destructive cutover.

### WO-2 — SDK productization and mobile evidence

**Owner:** intake/SDK track  
**Dependencies:** WO-1

- Compare Web, Server, React Native, iOS, and Android public APIs against the same observation and consent contract.
- Check the publishable-key remote configuration/manifest path, version policy, safe public fields, failure visibility, heartbeat, queue diagnostics, and disabled/kill-switch behavior. Fix only gaps verified in the current tree.
- Provide equivalent documented examples and a shared conformance fixture or generated contract vectors without creating independent client-side identity semantics.
- Distinguish build/package evidence from simulator/device installation and tenant graph hydration evidence.
- Keep the Aether first-party mobile app a consumer of governed reads and continuations; do not turn it into a customer SDK or graph writer.

**Acceptance:** the shared client contract and remaining per-platform gaps are explicit. Device/store beta claims require device-lab/TestFlight/Play evidence and privacy review; a source change alone cannot satisfy them.

### WO-3 — Protocol-neutral access invocation

**Owner:** access track  
**Dependencies:** WO-0

- Inventory and reuse existing authentication, tenant resolution, capability catalog/lifecycle, policy, readiness, entitlement, usage, approval, audit, and receipt owners.
- Add only the missing normalization/router seam needed for protocol adapters to invoke an existing capability authority.
- Return a stable request/interaction envelope with machine-readable blocked, denied, degraded, and successful outcomes. Preserve the reason and authoritative receipt/reference.
- Start with read-only capability calls. Keep observe on WO-1 and reserve act for its owning action authority and approval policy.

**Acceptance:** an authorization decision cannot be bypassed by changing transport; tenant and actor are server-resolved; denied/degraded/success results carry consistent correlation and evidence references; no second policy, billing, or capability registry is introduced.

### WO-4 — REST/API access contract

**Owner:** access track  
**Dependencies:** WO-3

- Define the actual supported read/query operations from existing domain APIs. Do not create a catch-all endpoint that silently changes query semantics.
- Normalize authentication context, problem/error responses, pagination, idempotency rules, and durable result handles where the underlying operation supports them.
- Treat OpenAPI and generated SDK artifacts according to repository contract-generation ownership; do not manually maintain duplicate schemas.
- Explicitly classify each endpoint as observe, query, or act and state its required capability and authority owner.

**Acceptance:** every newly exposed API path maps to an owning service and contract artifact, with scopes, error behavior, pagination, and tenant isolation defined. Unsupported capabilities are absent or explicitly unavailable, not mocked.

### WO-5 — Aether MCP adapter

**Owner:** access track  
**Dependencies:** WO-3, WO-4

- Verify current official MCP transport/version requirements at implementation time and pin the protocol behavior in the adapter documentation.
- Separate remote authenticated MCP from an optional local stdio bridge. The bridge delegates to the same remote Access/API authority and never stores a plaintext credential or exposes a new local data authority.
- Publish deterministic, scope-aware tool catalogs from supported capabilities; validate input/output schemas; route through WO-3; return handles for durable operations.
- Classify tools as observe, query, or act. Ship read-only/query tools first; ingestion tools must enter canonical intake and write/action tools must use their owning authority.
- Keep long-running jobs and approvals in explicit durable handles. Do not depend on protocol session memory for business state.

**Acceptance:** protocol conformance, authentication, tenant isolation, scope denial, deterministic listing, error mapping, and request correlation are documented and reviewable. MCP-specific tests and remote-client evidence are required before claiming MCP beta; they are not implied by API evidence.

### WO-6 — Customer CLI adapter

**Owner:** access track  
**Dependencies:** WO-3, WO-4

- Establish one supported customer CLI package and installation command using repository conventions.
- Implement browser/device login or the existing approved delegated-auth flow, tenant selection backed by server authorization, profile/context management, and token revocation behavior.
- Route commands through the same API/Access contract. Start with `auth`, `tenant`, `capabilities`, `readiness`, safe read/query commands, and `doctor`; ingestion and act commands follow the authorities and gates above.
- Provide JSON output for automation and readable terminal output for humans. Errors must retain machine-readable codes and correlation IDs.

**Acceptance:** CLI commands do not call graph stores directly or embed privileged service credentials; install/auth/tenant/read/denied paths are documented; revocation and credential storage have an explicit supported behavior.

### WO-7 — Receipts, telemetry, and developer handoff

**Owner:** integrator with access track  
**Dependencies:** WO-3 through WO-6

- Reuse existing audit, billing, usage, approval, and receipt systems. Add protocol/surface attribution only where the canonical event contract is missing it.
- Define which decisions are billable, included, rate limited, approval gated, or explicitly not yet priced; do not invent plan numbers in an adapter.
- Publish setup, capability discovery, errors, security boundaries, and examples for each surface. A developer portal is a later product surface unless a current portal authority exists.
- Keep MCP Apps, full webhook delivery, workflow automation, broad write/action tools, and marketplace features out of the first vertical slice unless a current owner and end-to-end proof already exist.

**Acceptance:** a call can be correlated across request, authorization, usage/audit, receipt, and result where those authorities support it; missing billing or observability integration is called out, not claimed complete.

### WO-8 — Cross-surface proof and readiness record

**Owner:** integrator  
**Dependencies:** WO-1 through WO-7

- Build focused evidence that covers one supported observation source through the governed graph/read path and one read-only capability through REST, MCP, and CLI adapters.
- Cover tenant isolation, denied authorization, idempotency/replay, partial/degraded states, error mapping, and durable handle retrieval in the affected surfaces.
- Keep package, hosted CI, provider credentials, live tenant, device lab, staging, and store evidence separate. State exactly which proof exists and which is still required.
- Update owned/generated/source-linked documentation according to repository instructions before final PR readiness.

**Acceptance:** all claims map to retained evidence; no production, certification, customer-beta, or broad merge-readiness claim is made without its canonical release/PR evidence.

## 6. Single-PR commit sequence

The intended stack is:

1. `docs: define source intake and access convergence work orders` — this page and reconciled architecture ownership.
2. `feat(ingestion): converge verified source handoffs` — only adapters and contract gaps established by WO-0.
3. `feat(sdk): align supported client intake contracts` — verified SDK/runtime improvements and examples.
4. `feat(access): normalize capability invocations` — shared protocol-neutral invocation seam.
5. `feat(access): expose supported API and MCP capabilities` — only capabilities whose authorities exist.
6. `feat(cli): route customer commands through access contracts` — safe initial commands and install/auth docs.
7. `docs: record cross-surface proof and remaining gates` — reviewed evidence, generated/source-linked surfaces, and explicit limitations.

The sequence may be adjusted after WO-0, but all changes remain commits on the same feature branch and one PR targeting `Development`.

## 7. Readiness boundaries

- A successful `/v1/batch` response proves intake acceptance only; it does not prove normalization, identity resolution, graph projection, queryability, or time-to-value.
- An SDK package build proves package viability only; it does not prove device lifecycle behavior or a customer tenant graph.
- A route or MCP tool that returns data does not prove equivalent authorization, rights, scope, readiness, billing, or receipt behavior across transports.
- A CLI or local bridge is not a privileged operator channel. It must use delegated/customer authorization and the same tenant policy as REST.
- Repository-local checks, hosted PR checks, live provider evidence, staging, mobile device evidence, and production readiness remain separate claims.

