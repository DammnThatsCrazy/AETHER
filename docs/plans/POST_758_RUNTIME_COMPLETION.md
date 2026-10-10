---
title: Post-#758 Runtime Completion and Expansion
slug: plans/post-758-runtime-completion
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0
canonical_owner: architecture@aether
---
# Post-#758 Runtime Completion and Expansion

## Baseline and scope

This is the implementation delta for the October 9, 2026 post-#758 assessment.
The assessed baseline is `Development` at `a8bb030f`; the current implementation
is stacked on that branch at `ed1cfb53`. The earlier mobile identity work is in
the same checkout and is retained. The objective is to connect surviving
contracts to their real runtime owners, then prove the customer-facing path;
it is not to recreate the original 72 work orders as 72 presumed missing
features.

## Eight remaining runtime gaps

| # | Gap | Current repository evidence | Delivered implementation | Completion evidence |
|---|---|---|---|---|
| 1 | Agent lifecycle has no canonical consumer | `AgentLifecycleMapper` existed without a callsite; SDK lifecycle payloads are not authority evidence. | Added the internal event consumer for execution started/completed/failed and wired it into graph projection topics. It requires `source_service=agents`, tenant, agent, execution, and source event identity. | Server-owned execution events reach the mapper with event lineage; replay is idempotent; SDK assertions cannot mint identity, delegation, or authorization. |
| 2 | x402 lifecycle has no safe consumer | Public SDK x402 events included terminal names that could look authoritative when mapped directly. | Added a bounded SDK lifecycle worker for request/intent stages and a separate consumer for server-owned challenge, payment-submitted, reconciled settlement, failure, and access-granted topics. Each event must match its closed producer/topic authority and joins tenant-scoped commerce records. | SDK terminal claims remain deferred; server lifecycle stages are mapped only from their authoritative source and store records. |
| 3 | Social 360 relationship spine is unfinished | Social Silver held six classes of evidence, but the projection provider and exploration adapter were not registered. | Added bounded tenant-only reads across all six Social Silver fact repositories, a typed Social360 projection provider, boot registration, and a registered exploration adapter. Current server analytics consent is checked before reads; raw payload/content is excluded; capped reads are surfaced as degraded. | Output matches all six generated sections; denied consent suppresses every section. Runtime serves only stored tenant facts and keeps missing evidence unknown. Registry remains `in_flight` pending provider credentials, evidence-health wiring, and production SLOs. |
| 4 | Derivatives entitlement guard is not active on production pull paths | Entitlement enforcement was optional and not resolved through the billing owner. | Venue credential resolution now defaults to the billing entitlement repository and fails closed. Account linking and observation intake check `derivatives.enabled`. | No entitlement means no venue client or intake; resolver errors deny; the check is tenant-scoped. |
| 5 | Derivatives usage lacks durable metering | Derivatives usage had only process-local meters. | Accepted account and observation events now write through billing `MeteringService`, using deterministic source identity for deduplication. | Meter records survive restarts and replay; existing billing persistence is the sink. |
| 6 | Derivatives graph mutations are incomplete | Account/position mutation builders were not called by durable intake. | Account and position observations now project through `GraphMutationGateway` after source persistence. Duplicate intake retries fan-out to repair partial failures; gateway intents carry tenant and source lineage. | Supported account/position projections are traceable to durable source facts; unsupported observation types remain evidence-only. |
| 7 | Model-runtime tenant completion is incomplete | No tenant completion route existed; preferences and usage summaries were seed/in-memory only. | Added tenant completion guarded by billing model entitlements and transaction-serialized monthly token reservations; added durable tenant defaults and canonical usage metering/rollups. Runtime dispatch now resolves tenant-scoped BYOK/AWS credentials and retains provider configuration/circuit checks. Provider errors return content-free status codes. | Invocation requires tenant credential, model entitlement, and token reservation; usage is metered after success; provider and quota failures block dispatch. Evaluation remains a release gate before broad activation. |
| 8 | Web3/x402 storage is not fully covered by erasure and retention | Generic DSAR coverage omitted raw Web3 observations and direct x402 subject references. | Added explicit erasure components and isolated planes with tenant scoping, exact subject-reference matching, legal-hold checks, and per-store receipts. Added the Web3 storage policy; x402 resource policies already exist. | DSR records now resolve and execute both components. Matching commerce rows are deleted under current hard-delete policies; unmatched tenant records remain. |

## Three remaining product priorities

These priorities remain active architectural acceptance tracks. The changes
above connect their runtime dependencies; the sections below retain the
customer-facing work and proof still needed.

### Mobile-to-economic identity

Continue the Android, iOS, and React Native wallet contract work already in the
checkout: preserve VM family and concrete chain namespace end-to-end, connect
wallet observations to the canonical source-identity path, and keep a wallet
connection distinct from verified ownership, custody, or key control. Aether's
SDK observes activity in the integrating application; Samsung Wallet or Apple
Wallet account-level activity requires an authorized provider integration.

**Acceptance:** authorized mobile and financial-provider evidence can converge
on the correct tenant entity without false identity merges or duplicate value.

### Intelligence surfaces

Extend the surviving Graph/temporal graph, Profile 360, Agent 360, Value,
Journeys, Signals/Lenses, Snapshot, and Kyber diagnostics with evidence-backed
economic and agentic projections. Preserve each domain's lifecycle semantics
and show source, verification state, and limits in user-visible explanations.

**Acceptance:** users can navigate from an observed action to its entities,
relationships, authority chain, and reconciled economic outcome.

### Production proof and commercial readiness

Prove the approved journeys: human mobile financial activity, cross-platform
economic identity, human-to-agent-to-sub-agent delegation, multi-provider
commerce, and relationship/exposure intelligence. Include retries, replay,
correction, source revocation, consent withdrawal, tenant isolation, latency,
scale, and cost in the release evidence.

**Acceptance:** at least the human mobile journey, cross-platform identity,
and a controlled delegated-payment journey have end-to-end product evidence;
design-partner evidence is distinguished from production readiness.

## Implementation program sequence

### Slice 0 — Capability and work-order traceability

The original 72-work-order inventory is not present in this repository or the
available conversation context. Its exact item names and IDs therefore cannot
be reconciled yet. Do not fabricate replacement rows or claim a complete
traceability audit. Once the original list is restored, create one row per
source item and map it to the current owner, runtime reachability, the eight
runtime gaps above, and the three priorities below. Dispositions are
`implemented_and_reachable`, `implemented_but_unproven`, `disconnected`,
`missing`, or `superseded`. Each row must carry an evidence path, next action,
dependency, and acceptance criterion. Existing implementations remain
authoritative where they already own the capability. Until then, this program
tracks the eight gaps and three priorities as the available source of truth.

### Slice 1 — Mobile source observation to economic graph

Preserve chain namespace and VM family from SDK calls, attach the connected
wallet address only as contextual source evidence, project canonical `wallet`
and `transaction` events into tenant-scoped Web3 Silver facts, and resolve
identity only when the existing source-identity evidence is present. Public
SDK ingestion must enforce the registry's `sdkEmitable` set so client keys
cannot claim server-owned lifecycle or finality event types. Client-reported
transaction references remain unverified until a chain/provider verifier
confirms execution and finality. Only verified observations may contribute
payment or settlement graph semantics.

**Acceptance:** a controlled host-app observation is retained with tenant,
source event, wallet context, chain namespace/VM, consent, and source-observed
status; non-SDK-emittable events are rejected at the public SDK boundary. A
client event alone never creates a `PAID` or settled relationship.

**Implementation status (October 10, 2026):** Android/iOS transaction calls
include the connected address as context; the event contract marks wallet,
chain, and VM fields as source references; Web3 Silver now accepts canonical
`wallet`/`transaction` events and retains their observed status; identity
ingestion recognizes `walletAddress`; and validation enforces the generated
SDK-emittable event set. Contract generation, Python syntax compilation, and
strict documentation drift checks pass. Provider-backed transaction
verification, journey reconciliation, and product evidence remain open.

### Slice 2 — Authoritative agent execution and economic reconciliation

Connect real executor outcomes to server-authored lifecycle events. Preserve
principal, agent, sub-agent, delegation, authorization, execution, and settlement
refs. Reconcile those refs with the existing domain-specific payment, x402,
stablecoin, commerce, and derivatives contracts before introducing a shared
cross-domain operation identity.

### Slice 3 — Evidence-backed customer surfaces

Expose the verified operation chain through existing graph and temporal reads,
then Profile 360, Agent 360, and Value. Extend Journeys, Signals/Lenses,
Snapshot, and Kyber diagnostics only where they can display source evidence,
authority, lifecycle state, and limitations.

### Slice 4 — Journey and release evidence

Run the five approved journeys against controlled fixtures first and authorized
providers where available. Record replay, correction, revocation, consent,
tenant isolation, latency, scale, and cost results. Keep design-partner or
simulator evidence distinct from production readiness.

## Shared architecture decisions carried forward

- Keep one canonical agent/x402 consumer path for each source-authority class.
- Use one economic-operation identity and reconciliation contract while
  retaining specialized payment, derivatives, and commerce lifecycle rules.
- Resolve identity, delegation, and effective authority through canonical
  ownership; event payloads alone do not prove permission or execution.
- Materialize graph projections only from durable, consented evidence and keep
  source lineage through corrections and erasure.
- Reuse existing entitlement and metering authorities instead of introducing
  parallel registries.
- Activate model runtime only after tenant credential, entitlement, budget,
  readiness, and evaluation checks.
- Cover every new store and graph projection in retention, correction, and
  erasure policy.
- Declare a feature complete only with contract, runtime reachability, durable
  evidence, governed projection, and user-visible explanation.

