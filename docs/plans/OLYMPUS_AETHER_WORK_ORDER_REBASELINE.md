---
title: Olympus Labs / Aether Work-Order Rebaseline
slug: plans/olympus-aether-work-order-rebaseline
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0
canonical_owner: architecture@aether
---

# Olympus Labs / Aether Work-Order Rebaseline

## Purpose

Keep the capability inventory, architecture decisions, and implementation
program connected without turning each capability into a separate pull request.
The target is one Olympus Labs intelligence infrastructure, with Aether as its
unified intelligence runtime across human, agent, and economic domains.

This is a desk rebaseline against the referenced conversation and the current
`Development` checkout. It records implementation evidence and release gaps;
it is not a line-by-line certification of every capability.

## Source and inventory count

The referenced chat is **“Analyze Samsung Crypto SDK”**, conversation
`6ac7015e-dc4c-83e9-bf46-1728feb07c16`. Its latest work-order answer calls the
inventory “72” and says it contains six programs. The tables actually enumerate
67 stable IDs:

| Program | IDs shown | Count |
|---|---|---:|
| Canonical Foundations | CF-01–CF-07 | 7 |
| Universal Observability | UO-01–UO-12 | 12 |
| Intelligence Graph | IG-01–IG-12 | 12 |
| Intelligence & Product | IP-01–IP-12 | 12 |
| Trust, Security & Operations | TS-01–TS-12 | 12 |
| Commercial Readiness | CR-01–CR-12 | 12 |
| **Enumerated in the retrieved answer** |  | **67** |

The five-item difference is not assigned IDs or guessed at here. Recover the
missing source entries before calling this a reconciled 72-item inventory.
Until then, all 67 enumerated requirements remain in scope, and the five
unresolved source entries remain a traceability gap.

## Architecture alignment

The target architecture is the organizing constraint for the work:

| Olympus Labs / Aether target | Capability families represented in the inventory |
|---|---|
| Human domain | Human, device, application, account and wallet identity; behavior; relationships; communications; journeys |
| Agent domain | Agent identity and lifecycle; delegation; authority; execution; outcomes |
| Economic domain | Accounts, wallets, transactions, authorizations, settlements and value |
| Canonical graph | Shared entities, evidence, provenance, authority, temporal history and governed mutations |
| Lenses and 360 projections | Graph workspace, Profile 360, Agent 360, Value, Journeys, Signals, Snapshot and Kyber |
| Explainable intelligence | Source-backed reasoning, confidence, unknown states, anomaly and exposure explanations |
| Actions and outcomes | Authorized, observable actions with outcomes tied back to the evidence and economic operation |

The domain systems remain specialized owners. Aether composes their evidence
and projections; it does not introduce parallel identity, payment, agent, or
graph authorities.

## Rebaseline vocabulary

- **Connected** — a production runtime path exists in this checkout.
- **Partial** — some contracts or runtime paths exist, but the full capability
  in the work order is not demonstrated.
- **Design gap** — a canonical contract or decision is still needed before a
  safe implementation can be selected.
- **Proof gap** — implementation exists, but controlled provider, customer, or
  production evidence is missing.
- **Not evidenced** — this checkout and the current program do not establish
  completion; audit the named owner before implementation.

These labels distinguish code presence from completed customer capability.

## The 67 work orders, reconciled

### Program I — Canonical Foundations

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| CF-01 | Inventory canonical entities, relationships, contracts, registries and services | Partial. The repository has canonical registries, architecture source-of-truth docs and service ownership metadata; this rebaseline is the first cross-domain inventory. | Complete the ownership map from existing registries and runtime entry points. Record one authoritative owner and evidence path per concept. |
| CF-02 | Formalize human, organization, agent, device, application, account, wallet and address entities | Partial. Identity, agent, wallet and financial models exist, but wallet association, custody, control and ownership must remain distinct. | Reconcile these entity types against existing contract registries; identify only missing distinctions. Do not add duplicate canonical entities. |
| CF-03 | Establish evidence provenance, ownership, source authority and observation rights | Partial / proof gap. Source authority, consent and provenance paths exist; provider certification and cross-domain source lineage are not demonstrated end to end. | Define the evidence envelope used across SDK, provider and agent events; prove source, tenant, consent, authority and verification states survive to projections. |
| CF-04 | Standardize cross-domain canonical events and relationships | Partial. Generated event registries and domain-specific event contracts exist; common economic, agent and wallet semantics still need reconciliation. | Map each domain event to existing canonical event/relationship types and identify contract mismatches before adding new types. |
| CF-05 | Define lifecycle, transition and capability ownership rules | Partial. Service classification, lifecycle owners and bounded consumers exist; remaining provider and executor lifecycles need authority tables. | Produce a lifecycle/producer/topic ownership matrix for human, agent, payment and commerce states, including terminal-state authority. |
| CF-06 | Establish schema versioning, compatibility and migration governance | Partial / validate. Schema and contract generation exist; multi-SDK/provider compatibility has not been proven across the target flows. | Validate version evolution, replay and old-client behavior across iOS, Android, React Native and provider adapters. |
| CF-07 | Formalize economic operations, authorization and attestation-ready evidence contracts | Partial. Domain-specific authorities exist, but no one record owns the lifecycle across intent, authorization, execution, payment, settlement, fee and outcome. | Use source-owned records plus the shared evidence-only operation linkage specified below; do not establish a competing universal operation system of record. |

### Program II — Universal Observability

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| UO-01 | Extend iOS financial, wallet, agent and authorization observations | Partial / proof gap. iOS wallet and transaction observations are connected to Web3 ingestion; provider-wallet activity is not directly observable through the host SDK. | Preserve chain and VM context; complete SDK parity review and a controlled host-app journey. Treat Apple Wallet account feeds as partner-dependent. |
| UO-02 | Extend Android financial, wallet, agent and authorization observations | Partial / proof gap. Android wallet observations, Silver persistence and tenant-scoped transaction verification are connected. | Prove on a physical device and configured RPC; keep Samsung Wallet account activity behind an authorized provider integration. |
| UO-03 | Establish React Native parity and native bridge correctness | Not evidenced at end-to-end proof level. Native SDK work exists; current program does not certify the bridge contract. | Compare public event vocabulary, consent, offline queueing, chain namespace and identity behavior across all three SDKs. |
| UO-04 | Test mobile SDKs on physical devices, including heartbeat, offline and retry | Proof gap. No physical-device evidence is attached to this implementation run. | Run a controlled device matrix and capture heartbeat, offline buffering, retry, duplicate and consent withdrawal evidence. |
| UO-05 | Complete Solana, Sui and canonical network/asset observation | Partial. EVM and Solana transaction verification are described; Sui and broad asset canonicalization are not proven in the active journey. | Add or certify Sui observation/verification only through the existing Web3 owner; preserve VM family and namespaced chain IDs. |
| UO-06 | Integrate stablecoins, custodial accounts, processors and bank rails | Partial. Payment-rail adapters and provider contracts exist; Samsung/Bastion/Coinbase Prime account feeds are not integrated. | Qualify authorized sources and map custodial accounts, provider transactions and on-chain legs without asserting key control or double-counting value. |
| UO-07 | Complete x402 payment lifecycle observation | Connected for bounded server-authoritative lifecycle events; live end-to-end proof remains open. | Exercise request through authorization, submission, verified settlement, resource delivery and outcome with a controlled provider/runtime. |
| UO-08 | Integrate AP2, Verifiable Intent and agent payment authorization evidence | Design gap / not evidenced. The work-order answer identifies these standards; this checkout does not establish a certified integration. | Map standards to existing intent, mandate and authorization authorities; select a provider/fixture after the canonical authority decision. |
| UO-09 | Support enterprise-authorized financial and agent-platform integrations | Partial. Provider/runtime infrastructure and enterprise controls exist; the requested provider set and evidence are not enumerated. | Inventory authorized enterprise sources, data rights, supported capabilities and identity semantics; add only integrations backed by access. |
| UO-10 | Establish provider certification, webhook integrity and adapter conformance | Partial. Stripe signature verification and merchant-payment normalization are connected; multi-provider certification is open. | Create a shared adapter conformance package covering signature, replay, idempotency, corrections, currency precision and tenant routing. |
| UO-11 | Support historical imports, live synchronization, backfill and reconciliation | Partial. Shopify order ingestion and provider event paths exist; complete import/backfill behavior across the approved journeys is not proven. | Demonstrate cursoring, replay, stale revisions, backfill/live convergence and correction handling for each selected source. |
| UO-12 | Establish source capability discovery and truthful unsupported-feature states | Partial / audit required. Provider catalog and capability surfaces exist, but the inventory does not certify coverage for each requested source. | Reconcile declared adapter capabilities to executable paths and expose unsupported, unavailable and unverified states accurately. |

### Program III — Intelligence Graph

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| IG-01 | Resolve wallet, account, address, device and human identity | Partial / proof gap. Wallet-only observations can persist as unresolved tenant/chain/VM-scoped source identities; this does not prove human ownership. | Pair an authorized provider claim with SDK evidence and use canonical identity review/merge controls; prohibit wallet possession inference. |
| IG-02 | Represent custodial and noncustodial ownership/control relationships | Design gap. Current wallet evidence distinguishes observation from ownership but no complete custody/control contract is proven here. | Define separate relationships for account association, custody, control, delegation and ownership, each with source authority and verification requirements. |
| IG-03 | Resolve agent identity, lifecycle and principal relationships | Partial. Agent lifecycle consumers and Agent 360 are connected; a production executor and real principal/child-agent journey are unproven. | Prove server-authored lifecycle events from an actual executor and preserve tenant, agent, parent, principal and execution lineage. |
| IG-04 | Represent delegation chains, mandates, effective permissions and revocation | Partial / proof gap. Existing authority and delegation stores are surfaced in Agent 360; runtime revoke-to-execution enforcement needs proof. | Demonstrate principal → agent → subagent authority, effective permission evaluation, revocation and rejection of unauthorized spend. |
| IG-05 | Reconcile canonical economic operations and transaction lifecycles | Partial. Exact-reference Shopify order/Stripe payment evidence works as a narrow ledger; it does not join intent, authority, execution and settlement across domains. | Implement the evidence-only operation linkage around existing domain authorities; preserve lifecycle-specific semantics and avoid duplicate value. |
| IG-06 | Support cross-chain and cross-provider economic continuity | Partial / proof gap. EVM/Solana verification and Shopify/Stripe evidence exist; Sui and a verified cross-provider graph journey remain open. | Certify source-specific identifiers and settlement continuity for the five journeys; do not join on amount/time/customer identity. |
| IG-07 | Implement bitemporal financial, agent and authorization reconstruction | Partial. Temporal graph primitives exist; this program has not proven bitemporal reconstruction across these economic/authority domains. | Map valid time and system/knowledge time on canonical evidence and prove as-of reconstruction after correction and replay. |
| IG-08 | Govern graph mutations, replay, correction and restatement | Partial. Graph mutation gateway and replay-safe domain paths exist; end-to-end restatement after financial correction/revocation is open. | Prove idempotent mutation, supersession, reverse/restate, consent invalidation and audit lineage in controlled journeys. |
| IG-09 | Establish evidence-backed relationship verification and confidence | Partial / proof gap. Social360 relationship spine is registered and consent-gated; provider source credentials, evidence health and SLO proof are open. | Use one licensed source; show evidence references, confidence and unknown states; revoke consent and prove dependent projections disappear. |
| IG-10 | Support economic value attribution and multi-grain reconciliation | Partial. Existing value and financial domains exist; the new ledger intentionally does not project graph value or assert settlement. | Establish operation grain and rules for instruction, transfer, conversion, fee, settlement, refund and business outcome without double counting. |
| IG-11 | Optimize high-volume graph materialization and querying | Proof gap. Runtime and graph infrastructure exist; this build has no workload-specific latency, scale or cost evidence. | Benchmark representative mobile, provider, agent and relationship flows; set measurable SLOs and truncation/degradation limits. |
| IG-12 | Establish attestation-ready evidence and verification foundations | Design gap / partial. RPC verification and evidence provenance are foundations; no end-to-end attestation contract is established. | Define what can be attested, by whom, based on which evidence and revocation state; keep issuance disabled until authority is explicit. |

### Program IV — Intelligence & Product

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| IP-01 | Integrate financial and agent intelligence into graph workspace | Partial. Graph workspace and Agent 360 exist; full verified economic operation navigation is not proven. | Link source event → entities/authority → operation → settlement/value from the shared evidence contract. |
| IP-02 | Extend Profile 360 with authorized economic relationships | Partial. Profile financial/identity surfaces exist; commerce reconciliation remains tenant-scoped because no consented order-to-profile link exists. | Add only provider-backed identity claims resolved by canonical identity services; otherwise retain tenant-level evidence. |
| IP-03 | Complete Agent 360 authority, delegation, activity and outcome projections | Partial / proof gap. Agent 360 displays authority, delegation and execution/payment evidence; real executor + payment proof is outstanding. | Validate parent/child lineage, source authority, revoked permissions and settlement outcome in the controlled delegated journey. |
| IP-04 | Extend Value with cross-platform economic operations | Partial. Value and domain financial records exist; merchant order/payment side-ledger does not contribute to Value. | Integrate only after shared operation identity, settlement semantics and deduplication rules are accepted. |
| IP-05 | Support agent-assisted and autonomous commerce journeys | Partial. x402 and agent lifecycle paths exist; autonomous payment execution is not enabled or proven, consistent with observation-only execution decision. | Demonstrate an authorized agent request and observed payment through an approved provider; no Aether-initiated financial execution. |
| IP-06 | Build financial exposure and economic relationship lenses | Partial / proof gap. Exposure and relationship APIs/lenses exist; licensed source, health and production evidence remain open. | Connect authorized financial evidence to existing relationship projections with lineage, confidence and consent gates. |
| IP-07 | Integrate social, financial and agentic contagion intelligence | Partial / proof gap. Social360 runtime is connected; cross-domain evidence and provider authorization have not been certified. | Build a controlled cross-domain projection only after source-specific consent and relationship semantics are established. |
| IP-08 | Introduce economic anomalies and data-poisoning indicators | Partial / audit required. Risk/fraud and identity controls exist; cross-domain financial poisoning signals are not established by this work. | Threat-model forged wallet, provider, agent and webhook claims; connect validated indicators to existing risk owners. |
| IP-09 | Produce evidence-backed explanations and recommendations | Partial. Existing intelligence/explanation surfaces exist; the planned journeys need operation-level evidence and limitations shown. | Ensure each explanation resolves to sources, verification state, authority and uncertainty; never phrase observation as settlement. |
| IP-10 | Build mobile-to-financial-to-agent temporal timelines | Partial. Journey Explorer links mobile verification and agent activity; real provider and delegated-payment linkage is unproven. | Complete the three foundational customer journeys through one timeline with source and lifecycle evidence at each step. |
| IP-11 | Integrate financial and agent signals into Snapshot and Signals | Partial / audit required. Signals and Snapshot surfaces exist; cross-domain economic integration is not certified. | Map accepted operation and authority outputs to existing signal owners; retain `unknown` until evidence is sufficient. |
| IP-12 | Evaluate model accuracy, inference quality and financial correctness | Proof gap. Tenant model runtime and evaluation gates exist; finance/agent accuracy evidence is not attached. | Create evaluation criteria from reconciled operations and known ambiguity; require evidence quality and calibrated unknowns before activation. |

### Program V — Trust, Security & Operations

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| TS-01 | Enforce financial-data rights and consent throughout pipeline | Partial / proof gap. Consent and integration governance are established; each new provider and customer journey needs source-specific rights proof. | Verify purpose, subject, processing basis, revocation and downstream invalidation per source and projection. |
| TS-02 | Enforce tenant and organization isolation | Partial / validate. Tenant-scoped APIs, stores and provider routing exist; no complete cross-domain isolation proof is attached. | Prove two-tenant isolation for identity, provider references, ledger, graph, projections and erasure. |
| TS-03 | Defend wallet and financial identity resolution against poisoning | Partial. Source authority, evidence review and unresolved wallet identities limit false merges; adversarial financial proof remains open. | Test spoofed address/ownership claims, provider mismatch, replay and cross-tenant reference collisions. |
| TS-04 | Threat-model agent impersonation, delegation abuse and authority escalation | Design / validation gap. Agent authority controls exist; the end-to-end threat model and adversarial executor proof are not recorded. | Threat-model principal spoofing, child-agent substitution, stale grants, revocation races and payment escalation; remediate against existing authority owner. |
| TS-05 | Establish financial deduplication, integrity and finality controls | Partial. Stripe signature verification, idempotency, exact references, RPC checks and explicit settlement distinction exist; broad finality/reorg rules are incomplete. | Prove webhook replay, chain reorg, conflicting source revisions, payment-ID reuse, duplicate value and finality semantics. |
| TS-06 | Support corrections, erasure, revocation and derived-state invalidation | Partial. Web3/x402 erasure and consent invalidation are present; commerce correction/refund behavior and new side-ledger lifecycle are open. | Define correction/refund facts and retention/erasure treatment before projecting commerce evidence into graph or Profile 360. |
| TS-07 | Govern secrets, provider credentials, signing boundaries and keys | Partial / proof gap. Vault and provider credential authorities exist; no credentials for partner certification are attached. | Validate rotation, least privilege, tenant binding, webhook signature, revocation and incident response using authorized nonproduction credentials. |
| TS-08 | Optimize SDK/connector throughput, latency, reliability and cost | Proof gap. Durable ingestion, bounded reads and retry handling exist; workload SLO and cost evidence are absent. | Measure device buffering, provider sync, graph fan-out, projection reads and model costs; publish release thresholds. |
| TS-09 | Extend Kyber diagnostics across sources, agents, policy, graph and finance | Partial. Kyber and diagnostic frameworks exist; the program has not demonstrated one cross-domain operational view. | Surface source health, authority/consent, lineage, reconciliation drift, degradation and readiness for each selected journey. |
| TS-10 | Establish operating diagnostics, incident recovery and release controls | Partial / proof gap. Repository and deployment controls exist; financial/agent failure and recovery drills are not recorded. | Define and exercise replay, provider outage, queue backlog, credential revoke and projection recovery playbooks. |
| TS-11 | Assess privacy, financial-data and regulatory obligations | Design / external review. Repository controls do not establish legal classification or jurisdictional approval. | Obtain qualified privacy/legal review for each provider/source and document permissible observation, retention and customer claims. |
| TS-12 | Complete production conformance, regression, load and recovery tests | Proof gap. Contract fixtures and repository checks exist; production conformance/load/recovery evidence is not present. | Run focused suites and controlled staging/release gates after the implementation slices converge; keep results distinct from code presence. |

### Program VI — Commercial Readiness

| ID | Capability | Current evidence / status | Next action |
|---|---|---|---|
| CR-01 | Demonstrate human mobile financial journey | Partial / proof gap. SDK observations, Silver storage, RPC verification and Journey UI exist. | Use a configured source and physical device; show observation, verification and settlement as separate states. |
| CR-02 | Demonstrate cross-platform economic identity | Partial / proof gap. Canonical source identity and profile review exist; authorized provider-to-SDK convergence is not proven. | Pair one provider and one SDK source in a controlled tenant; show provenance, review, no false merge and withdrawal behavior. |
| CR-03 | Demonstrate human → agent → subagent delegated payment | Partial / proof gap. Server lifecycle callback and Agent 360 exist; real executor and authoritative payment path are missing. | Complete controlled delegation, child lineage, permission check, revocation, payment evidence and settlement proof. |
| CR-04 | Demonstrate multi-provider financial/commerce journey | Partial. Shopify order and signed Stripe merchant-payment evidence are linked by exact reference; no live two-provider certification or graph/Value continuity. | Certify Shopify → Stripe order/payment and then reconcile settlement/correction across Journey and Value without identity inference. |
| CR-05 | Demonstrate financial relationship and contagion intelligence | Partial / proof gap. Social360 and exposure runtime exist; authorized provider evidence and explainable cross-domain result are absent. | Use a licensed source, produce explainable edges, exercise consent withdrawal and measure source health/SLO. |
| CR-06 | Deliver design-partner integration and onboarding package | Partial / not evidenced. Existing API and integration docs exist; no active design-partner evidence is attached. | Package source prerequisites, rights/consent, deployment, evidence exchange, support and acceptance for a named design partner. |
| CR-07 | Define capability entitlements and ACU consumption rules | Partial. Billing, entitlements and metering owners exist; commercial mapping to these five journeys is not reconciled. | Map each capability to canonical entitlement and usage meters; do not add a parallel billing registry. |
| CR-08 | Deliver enterprise APIs and developer documentation | Partial. Backend APIs and docs are broad; partner-ready economic/agent evidence contracts require review and examples. | Publish stable schemas, permissions, source capability limits, idempotency, errors and partner onboarding examples. |
| CR-09 | Qualify provider partnerships and evidence package | Not evidenced. Samsung, Bastion, Coinbase Prime, Solana, Sui and payment partners are opportunities from the source chat, not confirmed integrations. | Identify authorized contacts/access, provider capabilities, commercial terms and permitted data before treating a provider as an execution dependency. |
| CR-10 | Establish alpha, beta and production readiness scorecards | Partial / proof gap. Release and projection readiness systems exist; a unified scorecard for the five journeys is not established here. | Define evidence gates, owner, severity and threshold per journey; separate simulator, design-partner, staging and production status. |
| CR-11 | Validate performance, cost and unit economics | Proof gap. No workload-based latency, scale or cost results are attached. | Measure SDK ingest, sync, graph/projection costs and model use against the agreed commercial volumes. |
| CR-12 | Keep positioning and commercial claims evidence-backed | Partial. Product positioning exists; partner and production claims must be bounded by current proof. | Tie each claim to accepted journey evidence, provider authorization and readiness tier; remove unsupported reach/user claims. |

## Architecture decisions carried into the plan

The referenced chat records these as approved: universal graph scope; trifecta
ingestion through SDKs, authorized connectors and permissible public
observations; reuse of existing canonical objects; full agent lifecycle and
delegation; canonical economic reconciliation; temporal reconstruction;
provider-neutral interoperability; evidence-backed identity; end-to-end
consent and tenant governance; observation-only financial execution initially;
shared graph/lenses/360s; and five progressive demonstrations.

It also recommends one economic-operation reconciliation primitive with
domain-specific lifecycle rules. The audit and decision below resolve CF-07
and IG-05 against current payment, x402, derivatives, commerce and graph
owners. The Shopify/Stripe ledger remains deliberately narrower: it does not
write graph facts or claim settlement.

## Economic-operation authority decision

The current checkout does not contain a single authoritative economic
operation record spanning all domains. The owning records are intentionally
different because they capture different evidence and lifecycle semantics:

| Evidence/lifecycle | Existing authority | What it proves | Boundary |
|---|---|---|---|
| Agent payment intent, quote, authorization and execution reference | `PaymentIntentRepository` / agent x402 lifecycle | What an agent requested and the intent's linked lifecycle references | It is an agent-payment record, not the canonical owner of provider commerce orders or all financial activity. |
| Settlement attempts/outcomes for agent intents | `SettlementEventRepository`; source-specific chain verification in stablecoin reconciliation | A settlement attempt/outcome linked to an agent intent, including chain finality state where verified | Settlement remains a distinct fact; intent or processor completion alone does not prove payout settlement. |
| Commerce order and processor payment observations | Provider order/payment sources, joined by `CommerceOrderPaymentLedger` on the explicit `commerce_order_ref` | A tenant-scoped exact-reference match or conflict between order and completed payment observations | This ledger does not prove settlement, infer a person, write canonical graph facts, or aggregate multiple payments into value. |
| Derivatives order, execution and funding/payment | Derivatives repositories and lifecycle state machines | Domain-specific market order, execution and funding facts | These records keep exchange/market semantics and are not interchangeable with commerce orders or consumer payments. |
| Economic events, flows, positions, obligations, adjustments and settlements | `Economic360` contracts/provider | Typed projection/read vocabulary over canonical evidence | Economic360 is explicitly a projection, not a competing system of record. |

**Decision:** do not add a universal `EconomicOperation` graph vertex or
repository as a new authority. Preserve source-owned lifecycle records and
introduce a versioned, provider-neutral **operation linkage contract** only at
the integration seam. It is a correlation/projection record, not an economic
fact authority. It must carry tenant scope, a stable operation key, typed
source-authority references, relation semantics (for example `fulfills`,
`authorized_by`, `executed_as`, `settled_by`, `reverses`, or `produced`),
source/evidence references, observed/valid time, and reconciliation state.
It must not copy an amount as a new source of truth, flatten lifecycle states,
or imply that linked records are equal-value events.

**Identity rule:** only join records through a source-provided shared
identifier or an explicitly verified mapping. Never infer operation identity
from matching amount, time, currency, email, wallet, or customer. Preserve
provider namespaces and tenant isolation. Conflicting or insufficient evidence
must remain `conflict` or `unresolved`, not be auto-resolved.

**Value rule:** instruction, authorization, execution, transfer, conversion,
fee, settlement, refund/reversal, and merchant outcome are separate semantic
facts. Value projections select the appropriate recognized fact for each
measure and expose possible double counting; they do not sum every stage in an
operation chain. Settlement/finality claims require the relevant authoritative
provider or chain evidence.

**Why this is the recommended shape:** it reuses current domain owners, fits
the existing evidence-reference and graph conventions, allows later standards
such as AP2 or Verifiable Intent to map in without owning unrelated providers,
and supports the human, agent, and economic domains in the target graph. It
also gives the five demonstrations a consistent way to connect evidence
without forcing their distinct lifecycles into one state machine.

**Implementation order:** (1) define relation vocabulary and source-reference
contract; (2) map the Shopify/Stripe proof seam and agent x402 intent →
authorization → execution → settlement seam into it; (3) add chain finality,
correction/reversal, and merchant outcome evidence; (4) project the linked
evidence through graph, Journey, Agent 360 and Value; (5) validate replay,
tenant isolation, temporal reconstruction and no-double-counting. Do not
expand provider coverage before these seams preserve their source authority.

The first implementation artifact is now the strict `EconomicOperationLink`
contract in `services/backend/services/economic/economic360_contracts.py`. It carries
provider-namespaced source-record references, lifecycle roles, evidence-backed
relations, identity basis and reconciliation state. It forbids extra fields,
is explicitly versioned, requires identity evidence, rejects a `linked` state
with fewer than two source records, and does not carry amounts. It is currently
a contract only: runtime mapping, graph navigation and projections remain the
next implementation work.

## Recommended implementation program

This is a sequence of integrated vertical slices. A slice may touch several
work orders and repository owners; it does not imply one PR per work order.

| Order | Integrated slice | Main work-order coverage | Exit evidence / dependency |
|---|---|---|---|
| 0 | Correct the capability inventory and architecture register | All IDs; CF-01, CF-07 | Recover five missing source entries; map canonical owners, runtime surfaces, current evidence and decisions. Resolve economic-operation authority before shared model changes. |
| 1 | Canonical evidence and economic-operation contract | CF-02–07; IG-02, IG-05–08, IG-10, IG-12; TS-01, TS-05–07 | Versioned, source-authoritative operation/evidence mapping across intent, authorization, execution, payment, settlement, correction and outcome. Existing owners remain authoritative. |
| 2 | Mobile observation → provider/chain verification → identity | UO-01–06, UO-10–12; IG-01, IG-02, IG-06; TS-01–03, TS-05 | Physical Android/iOS/RN evidence, authorized provider evidence, correct chain namespace, unresolved/verified distinction, no false identity merge, tenant isolation. Samsung/Apple wallet feeds require separate authorization. |
| 3 | Agent authority → delegated execution → economic outcome | UO-07–09; IG-03–05, IG-07–08; IP-03, IP-05; TS-03–07 | Real executor callback, parent/subagent authority, revoke enforcement, x402/provider lifecycle and payment/settlement evidence; Agent 360/Journey explain observed vs settled states. |
| 4 | Cross-provider economic continuity → graph, Value and Journey | UO-06, UO-10–11; IG-05–08, IG-10; IP-01–04, IP-09–10; TS-05–06; CR-04 | Certified two-provider order→payment→settlement/correction path; stable operation identity; no double-counting; shared source lineage through graph, Value and Journey. Current Shopify/Stripe side ledger is a starting seam, not completion. |
| 5 | Relationship/exposure intelligence and intelligence surfaces | IG-09, IG-11; IP-01–02, IP-06–12; TS-08–09; CR-05 | One authorized/licensed source, consent-aware Social/financial/agent evidence, explainable unknown/confidence, evidence health, production SLO and surviving Aether/Kyber surfaces. |
| 6 | Trust, conformance and commercial readiness | TS-01–12; CR-01–12 | Five controlled end-to-end journeys, source-specific rights, tenant isolation, correction/replay/revocation, incident recovery, load/cost, readiness scorecard, onboarding and proof-backed claims. |

Work orders remain stable capability references. Implementation tasks are
derived from the evidence gaps and grouped by shared canonical owner and
vertical-slice acceptance criteria.

## Priority and dependency order

1. **Inventory and authority first:** recover the five missing work-order
   entries and settle the canonical economic-operation owner. This avoids
   cross-domain duplicate objects and duplicated value accounting.
2. **Prove the observation foundation:** complete the human mobile journey and
   cross-platform identity pairing with consent and provider authority.
3. **Prove human-to-agent authority and outcome:** use a controlled executor
   and authoritative payment/settlement evidence.
4. **Converge commerce and value:** take the existing Shopify/Stripe exact
   reference seam through settlement, correction and customer projections.
5. **Complete relationship/exposure intelligence:** use a licensed source and
   prove evidence health, consent withdrawal and explainability.
6. **Close cross-cutting readiness:** apply privacy, security, performance,
   cost, runbook and evidence gates to each journey before production claims.

## Immediate next steps

1. Reconcile the enumerated 67 rows in this document with the exact source
   list; add the five missing source items only when recovered.
2. Map the exact-reference Shopify/Stripe seam and agent x402 lifecycle into
   `EconomicOperationLink`, retaining their separate status and settlement
   authorities.
3. Turn the first three approved customer journeys into evidence checklists
   with owner, source, permissions/credentials, fixture, product surface and
   pass criteria.
4. Use those checklists to select the next integrated implementation slice;
   keep the five journeys as the acceptance spine for the larger inventory.
5. Update each work-order status only when code path, runtime execution and
   evidence are linked. Do not mark partner- or production-gated work complete
   from local fixtures or API presence.

## Current baseline note

The workspace is on `Development` at `78701bc2`, 20 commits ahead of its
tracked `origin/Development` base `a8bb030f`, with a clean worktree at the time
of this review. The post-#758 runtime plan records the eight runtime gaps and
three product priorities; the items above reconcile that implementation
program with the source chat's broader capability inventory.
