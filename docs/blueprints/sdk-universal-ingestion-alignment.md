---
title: "Aether SDK + Universal Ingestion Alignment Blueprint"
slug: blueprints/sdk-universal-ingestion-alignment
section: blueprints
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 45
toc_depth: 3
---

# Aether SDK + Universal Ingestion Alignment Blueprint

**Status:** Canonical implementation blueprint  
**Scope:** Aether SDKs, API ingestion, webhooks, connectors, bulk/import feeds, replay, server instrumentation, agent/execution harnesses, Contract Spine integration, graph projection, intelligence consumption, Kyber observability, security, compliance, testing, migration, and release governance.

---

# 0. Executive directive

Aether's increasing backend intelligence must **not cause proportional growth in its SDKs or source adapters**.

The governing architecture is:

> **Sources observe. Ingestion preserves. Aether interprets. The graph establishes governed state. Intelligence systems derive meaning.**

The SDK therefore remains a **thin, observation-only capture and transport layer**.

API clients, webhooks, connectors, imports, server instrumentation, replay systems, and execution harnesses follow the same principle.

They may know **what happened at the source**.

They may not decide:

- canonical identity;
- canonical relationship state;
- attribution;
- causality;
- journey truth;
- Episode truth;
- entity classification;
- population membership;
- risk;
- metric results;
- graph state;
- findings;
- recommendations;
- predictions;
- Communication360 state;
- Execution360 state;
- Relationship360 state;
- Profile360 state;
- Population360 state.

The current repository already establishes the SDK as a thin observation client responsible for anonymous/session identity, identity hydration signals, event capture, consent gating, batching/retry/persistence, and capability discovery, while explicitly assigning graph construction, identity truth, scoring, ML, and orchestration to the backend. 

This blueprint completes that direction.

---

# 1. Target end-to-end architecture

The new system should converge every ingestion mechanism before graph interpretation.

```text
 CUSTOMER / EXTERNAL / INTERNAL ENVIRONMENTS
────────────────────────────────────────────────────────────────────

 Web SDK       iOS SDK       Android SDK       React Native SDK
    │              │              │                    │
    └──────────────┴──────────────┴────────────────────┘
                            │
                     SDK BaseEvent
                            │
                            ▼

 Server SDK      API Feed      Webhook      Connector
     │              │             │             │
     │              │             │             │
     └──────────────┴─────────────┴─────────────┘
                            │
                            ▼

 Bulk Import     External Feed     Agent Harness     Replay
     │                  │               │              │
     └──────────────────┴───────────────┴──────────────┘
                            │
                            ▼

                  ┌─────────────────────┐
                  │ INGRESS ADAPTERS    │
                  │                     │
                  │ SDKAdapter          │
                  │ APIAdapter          │
                  │ WebhookAdapter      │
                  │ ConnectorAdapter    │
                  │ ImportAdapter       │
                  │ HarnessAdapter      │
                  │ ReplayAdapter       │
                  └─────────┬───────────┘
                            │
                            ▼

                Universal Observation Envelope
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    UNIVERSAL INGESTION GATEWAY                    │
│                                                                  │
│ tenant resolution                                                │
│ credential / signature validation                                │
│ deployment validation                                            │
│ schema validation                                                │
│ source trust classification                                      │
│ consent + privacy policy                                         │
│ sensitive-field filtering                                        │
│ idempotency                                                      │
│ sequencing / gap detection                                       │
│ provenance stamping                                               │
│ receipt timestamps                                                │
│ typed rejection/degradation                                       │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
                       IMMUTABLE BRONZE
                                │
                  Raw source + normalized receipt
                                │
                                ▼
                    NORMALIZATION / SILVER
                                │
               canonical vocabulary + units
                                │
              temporal / geography / currency
                                │
                                ▼
                     RESOLUTION PIPELINES
                  ┌─────────────┼─────────────┐
                  │             │             │
               Identity      Entity       Source
               Resolution   Resolution   Resolution
                  │             │             │
                  └─────────────┼─────────────┘
                                ▼
                    RELATIONSHIP CONSTRUCTION
                                │
                                ▼
                       TEMPORAL GRAPH
                                │
          ┌─────────────────────┼──────────────────────┐
          │                     │                      │
       Journeys              Episodes             Outcomes
          │                     │                      │
          └─────────────────────┼──────────────────────┘
                                ▼
                  INTELLIGENCE / MEASUREMENT
                                │
        ┌────────────┬──────────┼──────────┬────────────┐
        │            │          │          │            │
    Profile360 Relationship360 Episode360 Population360 ...
        │
 Communication360
 Execution360
 Campaign360
 Attribution
 Metrics
 Findings
 Investigations
 Risk
 Predictions
 Recommendations
                                │
                                ▼
                       EXPLORATION FABRIC
                                │
                   Aether / SHIKI / APIs
                                │
                               Kyber
```

Aether already operates multiple independent ingress paths—SDK, connector pull, public/authenticated webhook, external API feed, and internal replay—and currently normalizes these into a common event representation. 

The new architecture turns that existing convergence into an explicit, governed subsystem.

---

# 2. Point 1 — Establish the Observation Boundary

## Objective

Define exactly where **observation ends and interpretation begins**.

This becomes a hard repository invariant.

## Source-side responsibilities

SDKs and ingress adapters may:

- observe;
- timestamp;
- identify the local source;
- provide identifiers visible to that source;
- preserve source-native references;
- preserve correlation IDs;
- capture consent;
- capture permitted device/application context;
- maintain local session state;
- queue;
- retry;
- authenticate/sign;
- deliver.

They may not resolve graph truth.

## Backend responsibilities

Only backend systems may establish:

- `canonical_entity_id`;
- canonical organization/profile/agent/device/wallet identity;
- entity merge/split;
- relationship validity;
- relationship confidence;
- attribution;
- derived campaign membership;
- inferred geography;
- canonical currency valuation;
- journey stitching;
- Episode boundaries;
- evidence quality;
- claim state;
- finding status;
- causal support;
- Population360 membership;
- graph projections.

The repository already enforces an important portion of this: the SDK must never emit `canonical_entity_id`, and the validator strips client assertions of canonical entity IDs before persistence.  

## Required implementation

Create an explicit contract classification for every field:

```text
OBSERVED
SOURCE_ASSERTED
SOURCE_REFERENCE
CLIENT_HINT
SERVER_STAMPED
RESOLVED
DERIVED
INFERRED
PREDICTED
OPERATOR_ASSERTED
```

Every Contract Spine field receives one of these classifications.

Then validators enforce which trust classes may originate from which ingress path.

### Example

```text
browser SDK
userId = "34922"
```

Allowed:

```text
SOURCE_ASSERTED identifier hint
```

Not allowed:

```text
canonicalEntityId = "entity-123"
identityConfidence = .99
```

Likewise:

```text
Stripe webhook
customer = cus_123
```

means:

> Stripe observed/refers to `cus_123`.

It does **not** mean:

> `cus_123` is definitely canonical Entity E5.

---

# 3. Point 2 — Introduce the Two-Envelope Architecture

Aether should not force every source to construct an enormous internal graph contract.

Use two envelopes.

## Envelope A — Source/Wire Envelope

For SDKs this remains `BaseEvent`.

The repository already has a substantially richer `EventContext` than the original simple envelope, including timezone, UTC offset, application, surface, network, semantic hints, sampling, correlation, data quality, and sequence metadata.  

Conceptually:

```ts
interface SourceObservation {
  id: string;
  type: EventType;
  timestamp: string;

  sessionId?: string;
  anonymousId?: string;
  userId?: string;

  properties?: Record<string, unknown>;
  context: SourceContext;
}
```

It stays optimized for the producer.

## Envelope B — Universal Observation Envelope

Created **inside Aether**.

```text
UniversalObservationEnvelope
│
├── observation
│   ├── observation_id
│   ├── observation_type
│   ├── family
│   ├── occurred_at
│   ├── received_at
│   ├── ingested_at
│   └── schema_version
│
├── tenancy
│   ├── tenant_id
│   ├── deployment_id
│   └── environment
│
├── source
│   ├── source_type
│   ├── source_provider
│   ├── source_instance
│   ├── source_native_id
│   └── ingress_path
│
├── subjects[]
│   ├── identifier_type
│   ├── identifier_value
│   ├── actor_role
│   └── trust_class
│
├── temporal
│   ├── source_time
│   ├── timezone
│   ├── utc_offset
│   ├── clock_source
│   ├── sequence
│   └── temporal_quality
│
├── correlation
│   ├── correlation_id
│   ├── causation_id
│   ├── trace_id
│   ├── span_id
│   └── parent_observation_id
│
├── acquisition
├── application
├── surface
├── device
├── network
│
├── privacy
│   ├── consent_snapshot
│   ├── purposes
│   ├── GPC
│   ├── DNT
│   └── policy_decisions
│
├── provenance
│   ├── credential_class
│   ├── signature_status
│   ├── adapter
│   ├── adapter_version
│   └── source_trust
│
├── quality
│   ├── completeness
│   ├── freshness
│   ├── sequencing_state
│   └── validation_state
│
├── payload
│
└── lineage
    ├── raw_record_ref
    ├── normalization_version
    └── validation_version
```

### Critical rule

`UniversalObservationEnvelope` is **not a public SDK burden**.

Adapters build it.

That is how Aether acquires a powerful backend vocabulary while keeping the SDK thin.

---

# 4. Point 3 — Make the Contract Spine the Generator of Ingestion Truth

Aether already generates its TypeScript event types and Python ingestion registry from a canonical JSON registry. 

This needs to become comprehensive.

## Contract Spine ownership

The Contract Spine should govern:

```text
Observation Schema Registry
Event Registry
Event Family Registry
Consent Registry
Privacy Classification Registry
Retention Registry
Source Registry
Identifier Registry
Correlation Registry
Temporal Vocabulary
Unit Registry
Currency Vocabulary
Location Vocabulary
Provenance Vocabulary
Quality Vocabulary
Projection Registry
Capability Registry
Deprecation Registry
```

## Generation pipeline

```text
Canonical Contract Definitions
             │
             ▼
       Contract Compiler
             │
      ┌──────┼───────┬────────┬─────────┐
      ▼      ▼       ▼        ▼         ▼
 TypeScript Python  Swift    Kotlin   OpenAPI
      │      │       │        │
      ▼      ▼       ▼        ▼
 Web SDK Backend   iOS     Android
                            │
                            ▼
                      React Native
```

Generated artifacts should include:

- event enums;
- typed payload contracts;
- field classifications;
- consent purposes;
- privacy classes;
- retention classes;
- deprecated aliases;
- source trust requirements;
- validation schemas;
- documentation tables;
- fixtures;
- conformance vectors.

## Requirement

No SDK should independently hard-code:

- event names;
- consent mappings;
- privacy mappings;
- required fields;
- source trust classes.

The current Event Registry documentation still describes consent information being mirrored into SDK structures. 

That should become entirely generated.

---

# 5. Point 4 — Universalize All Ingress Adapters

Every ingestion mechanism receives an adapter.

## Adapter interface

Conceptually:

```text
IngressAdapter
├── identify_source()
├── authenticate()
├── verify_signature()
├── extract_source_id()
├── parse()
├── map_to_observation()
├── preserve_raw()
├── derive_idempotency_key()
└── emit_validation_metadata()
```

## SDK adapter

Input:

```text
BaseEvent
```

Produces:

```text
UniversalObservationEnvelope
source.type = sdk
```

## Webhook adapter

Input:

```text
provider-native webhook
```

Produces:

```text
UniversalObservationEnvelope
source.type = webhook
source.provider = shopify | stripe | sendgrid | ...
```

## Connector adapter

Takes provider pull results and maps each record separately.

## API feed adapter

Accepts server-to-server observations with stronger authentication and potentially richer source assertions.

## Import adapter

Processes:

- CSV;
- JSON;
- JSONL;
- Parquet;
- supported archives;

into the same envelope.

## Harness adapter

Handles:

- agent execution;
- AI invocation;
- tool invocation;
- MCP;
- service execution;
- trace/span telemetry.

## Replay adapter

Recreates the canonical observation **without pretending that replay time is occurrence time**.

It must preserve:

```text
original_occurred_at
original_received_at?
replayed_at
replay_run_id
replay_reason
```

The current architecture already distinguishes SDK, connector, webhook, feed, and replay paths. 

The implementation goal is to remove all downstream knowledge of which endpoint happened to receive the observation.

---

# 6. Point 5 — Rebuild Identity Capture Around Subject Hints

The SDK should stop expanding identity logic.

Instead, create a universal **Subject Hint Contract**.

```text
SubjectHint
├── identifier_type
├── value
├── namespace
├── role
├── verification_hint?
└── source
```

Potential identifier types:

```text
anonymous_id
user_id
account_id
email_hash
phone_hash
wallet_address
device_id
session_id
organization_user_id
agent_id
service_account_id
external_customer_id
provider_account_id
```

## SDK behavior

SDK knows:

```text
anonymousId = A7
sessionId = S9
userId = U22
```

It sends exactly that.

## Backend behavior

Identity Spine determines:

```text
A7 ─┐
S9 ─┼──> canonical Entity E17
U22 ┘
```

with:

- evidence;
- temporal validity;
- confidence;
- tenant scope;
- consent;
- resolver version;
- merge/split history.

## Cleanup required

Several current `EventContext` fields blur the observation boundary, including client-visible `identityConfidence`, `identitySignals`, canonical campaign references, attribution result references, and fraud decision references. 

These should be classified explicitly.

Recommended treatment:

```text
identityConfidence
→ rename clientIdentityConfidenceHint
OR server-only

identitySignals
→ identityHints

canonicalCampaignId
→ rejected from untrusted/public SDK unless cryptographically validated
→ prefer externalCampaignId/source campaign evidence

attributionResultId
→ server-generated reference
→ not freely asserted by public clients

fraudDecisionId
→ server-generated reference
→ not freely asserted by public clients
```

The principle is not necessarily to delete all correlation references.

It is to stop a client field from masquerading as canonical truth.

---

# 7. Point 6 — Complete the Temporal Observation Contract

The Temporal Graph blueprint depends on accurate source time.

Every observation should preserve:

```text
occurred_at
received_at
ingested_at
timezone
utc_offset_at_occurrence
clock_source
sequence
source_clock_quality
```

The existing shared envelope already supports timezone, UTC offset at occurrence, timezone source, clock source, and sequence metadata. 

## Backend enrichment

The Temporal Spine adds:

```text
canonical_occurred_at
valid_from
valid_to
system_from
system_to
ordering_confidence
clock_skew
temporal_conflicts
late_arrival
watermark
```

## Why this matters

Suppose:

```text
10:31:00 local → mobile click
10:31:01 local → app background
10:31:06 server → API call
10:31:07 provider → payment
```

Aether can reconstruct:

```text
click
 ↓ 1s
background
 ↓ 5s
server request
 ↓ 1s
payment
```

even if:

- ingestion happened out of order;
- provider delivery was delayed;
- the customer changed time zones;
- data was replayed later.

## SDK does not

- construct temporal relationships;
- decide causality;
- create episodes;
- reconcile clocks.

It captures the clocks and sequence information needed for Aether to do so.

---

# 8. Point 7 — Make Correlation and Causation First-Class

Correlation is the major mechanism through which a thin SDK powers a rich graph.

The current SDK contract already has:

```text
correlationId
causationId
traceId
spanId
```

in its correlation context. 

Expand the backend representation to support:

```text
correlation_id
causation_id
trace_id
span_id
parent_span_id
parent_observation_id
request_id
operation_id
message_id
conversation_id
execution_id
transaction_id
external_workflow_id
handoff_id
```

Not every event needs every field.

## Example

```text
Email webhook
message_id = M1
link_id = L8
        │
        ▼
Browser SDK
link_id = L8
session = S10
        │
        ▼
Server API
request_id = R3
trace = T7
        │
        ▼
Payment webhook
checkout_id = C5
order_id = O9
```

Backend can derive:

```text
Communication
  ↓
Session
  ↓
Execution
  ↓
Checkout Episode
  ↓
Outcome
```

without the SDK knowing any of those objects exist.

## Requirement

Source-native correlation values must **never be overwritten** during normalization.

Canonical correlation is additive.

---

# 9. Point 8 — Make Provenance and Evidence Native to Ingestion

Every graph fact ultimately needs to answer:

> Where did this come from?

Therefore provenance begins at ingress.

## Source provenance record

Every observation receives:

```text
source_type
source_provider
source_instance
source_native_record_id
adapter_id
adapter_version
credential_class
signature_state
tenant_scope
received_at
raw_record_ref
```

## Evidence transformation

```text
Raw Provider Record
      │
      ▼
Observation O1
      │
      ▼
Normalized Fact F1
      │
      ▼
Relationship R1
```

Graph outputs then retain:

```text
R1.evidence_refs = [F1]
F1.observation_ref = O1
O1.raw_ref = RAW-123
```

This enables Evidence Inspector to move all the way back from:

```text
"Person purchased Product X"
```

to:

```text
Shopify webhook
event ID 123
received Aug 17
provider signature verified
normalized under contract v9
```

## Claim integrity

The ingestion layer may mark:

```text
observed
source_asserted
```

but cannot mark:

```text
resolved
inferred
predicted
attributed
causally_supported
```

Those belong downstream.

---

# 10. Point 9 — Unify Consent, Privacy, Minimization, and Retention

This is where the SDK Blueprint touches the Security and Compliance Blueprints without replacing them.

## SDK responsibility

Enforce local collection gates wherever data should never leave the device without consent.

Examples:

```text
analytics
marketing
personalization
commerce
web3
agent
location
credit
financial_activity
```

## Server responsibility

Never trust client consent as the sole authority.

The current ingestion validator already treats server-side consent/policy as authoritative, normalizes GPC/DNT request signals, scrubs sensitive fields, identifies fingerprint-bearing fields, and can reject policy-disallowed observations.  

That becomes universal across **all adapters**.

## Processing order

```text
receive
  ↓
determine tenant/deployment
  ↓
determine source trust
  ↓
read privacy signals
  ↓
resolve current tenant policy
  ↓
validate purpose
  ↓
minimize/scrub
  ↓
classify retention
  ↓
accept / partially accept / reject
```

## Requirement

No connector or webhook may bypass privacy logic merely because it is server-side.

## Data minimization

Prefer:

```text
content_ref
hash
opaque source ID
classified metadata
```

over unnecessary raw:

```text
message body
form values
passwords
tokens
private keys
payment card data
```

The current validator already recursively scrubs a substantial class of credential, financial, authentication, form, and message-body fields. 

---

# 11. Point 10 — Introduce Explicit Ingress Trust and Credential Classes

Not all producers have equal authority.

Define:

```text
PUBLIC_CLIENT
TRUSTED_CLIENT
TENANT_SERVER
VERIFIED_WEBHOOK
MANAGED_CONNECTOR
AETHER_INTERNAL
OPERATOR_REPLAY
```

## Public SDK credential

A browser/mobile SDK credential should be publishable and limited to:

```text
observation:write
config:read
```

It must not grant:

```text
graph:read
profile:read
identity:merge
export
admin
billing
connector:manage
investigation:write
```

## Trusted server API

May assert stronger source information, but still cannot fabricate canonical graph state unless a dedicated governed API explicitly supports that operation.

## Verified webhook

Authority is constrained to:

```text
provider
tenant
event families
source namespace
```

## Managed connector

Uses connector credentials but emits source observations under an adapter identity.

## Internal replay

Carries explicit:

```text
replay = true
operator / job identity
reason
source run
```

## Requirement

Every field can specify a minimum trust class.

Example:

```text
externalCampaignId
PUBLIC_CLIENT allowed

canonicalCampaignRef
TENANT_SERVER minimum

canonicalEntityId
AETHER_INTERNAL only
```

---

# 12. Point 11 — Make Durability, Ordering, Idempotency, and Replay Universal

Aether's ingestion promise must be:

> An accepted observation is durable, traceable, replayable, and not double-counted.

The current SDK path writes accepted observations to Bronze before acknowledgment and uses tenant-scoped idempotency. 

Other ingress paths already use source-specific idempotency keys. 

Now formalize a universal contract.

## Canonical idempotency identity

```text
tenant_id
+
source_namespace
+
source_native_event_id
+
schema_major
```

SDK:

```text
event_id
```

Webhook:

```text
provider_event_id
```

Connector:

```text
provider_record/version
```

Feed:

```text
external_id
```

Replay:

reuse original observation identity
+
replay context
```

## Queue behavior

### Web

Persistent bounded queue.

### Native

Replace purely in-memory durability with:

```text
encrypted local persistent queue
TTL
bounded disk quota
retry metadata
batch metadata
successful-ack deletion
```

The documented native SDK path still describes an in-memory queue, whereas the web path has persistence. 

That should be corrected.

## Backpressure

SDK:

```text
batch
compress
retry
drop only according to explicit policy
```

Backend:

```text
rate-limit
queue
shed noncritical traffic only under governed policy
preserve typed disposition
```

## Delivery states

Every observation can become:

```text
queued
sent
accepted
duplicate
rejected
deferred
quarantined
dead_lettered
replayed
normalized
resolved
projected
```

---

# 13. Point 12 — Introduce Typed Validation and Degradation

Aether must never collapse:

```text
missing
empty
zero
unknown
not_applicable
unavailable
degraded
rejected
```

into one state.

This applies from ingestion to UI.

## Observation validation result

```text
ValidationResult
├── disposition
│   ├── accepted
│   ├── accepted_with_degradation
│   ├── rejected
│   └── quarantined
│
├── decision_codes[]
├── missing_fields[]
├── scrubbed_fields[]
├── unsupported_fields[]
├── policy_decisions[]
├── schema_version
├── validator_version
└── quality
```

The existing validator already returns structured `EventValidationResult` data including reason codes, privacy decisions, deployment context, normalized events, and audit metadata. 

Extend this universal model to webhook/API/connector/import/harness ingestion.

## Example

A record may have:

```text
email_clicked

timestamp        available
message_id       available
user_id          missing
timezone         unknown
campaign         available
body             scrubbed
```

It should still be usable.

Do not discard a valuable observation merely because one projection cannot be resolved.

---

# 14. Point 13 — Separate Event Semantics from Derived Intelligence

The Event Registry can be broad.

The SDK still stays thin.

The current registry already spans hundreds of types across analytics, journeys, identity, commerce, agents, e-commerce, communications, server activity, Web3, stablecoin, derivatives, and interoperability. 

The key is that **event count does not have to equal SDK complexity**.

## Three semantic levels

### Level A — Primitive observation

```text
track
page
screen
interaction_observed
api_request_observed
```

### Level B — Typed source observation

```text
product_viewed
email_clicked
order_completed
agent_tool_invocation_observed
transaction_confirmed_observed
```

### Level C — Derived Aether state

```text
high_value_customer
journey_completed
relationship_strengthened
campaign_incrementality
fraud_risk_high
episode_type_purchase
```

Level C should generally **not be public SDK-emitted truth**.

If derived state is represented as an event for internal processing, it must have:

```text
source = aether_internal
claim_type = derived/inferred/etc.
model/version
evidence
```

## Semantic hints

The current envelope includes semantic input and semantic hints. 

These must remain explicitly advisory.

A client may say:

```text
predictedGoalHint = "checkout"
```

Aether may conclude:

```text
intent = comparison-shopping
confidence = .81
```

The client does not win by assertion.

---

# 15. Point 14 — Rebuild the SDK as Core + Platform Adapter + Optional Generated Facades

The physical SDK architecture should be:

```text
@aether/core
│
├── config
├── consent
├── anonymous identity
├── session
├── context
├── sequence
├── correlation
├── queue
├── storage
├── transport
└── emit
```

Then:

```text
@aether/web
@aether/ios
@aether/android
@aether/react-native
```

provide platform-specific collection.

## Optional typed facades

```text
commerce
journey
wallet
agent
communication
ecommerce
```

should be either:

1. generated thin wrappers, or
2. tree-shakeable optional modules.

Example:

```ts
aether.ecommerce.orderCompleted({
  orderId,
  amount,
  currency
});
```

internally means approximately:

```ts
core.emit("order_completed", payload);
```

It must not contain:

```text
attribution algorithm
identity resolution
order reconciliation
currency normalization
customer segmentation
graph mutation
```

## Capability manifest

The repository already returns backend capabilities through `/v1/config`, including active event families, purposes, rails, supported VMs, graph layer activations, and feature flags. 

Refine that so the SDK asks:

```text
What may I collect/send?
```

not:

```text
How should I calculate Aether intelligence?
```

## Thinness gates

Add CI rules preventing SDK packages from importing:

```text
graph algorithms
ML packages
attribution logic
risk logic
metric engine
identity resolver
projection logic
database clients
workflow orchestrators
```

The SDK should be structurally incapable of becoming a second backend.

---

# 16. Point 15 — Build the Universal Backend Projection Pipeline

Once an observation has crossed the ingestion boundary, all intelligence systems consume canonical downstream artifacts.

## Stage 1 — Bronze

Stores:

```text
raw observation
normalized receipt metadata
tenant
source
timestamps
schema
validation
provenance
```

No identity truth required.

## Stage 2 — Silver

Performs:

```text
schema normalization
unit normalization
temporal normalization
source classification
geographic normalization
economic/currency normalization
identifier extraction
semantic normalization
```

## Stage 3 — Resolution

Produces:

```text
EntityRef
SourceRef
CampaignRef
CommunicationRef
ExecutionRef
ResourceRef
OutcomeRef
etc.
```

with evidence.

## Stage 4 — Relationship facts

Produces:

```text
RelationshipFact
├── source
├── target
├── relationship_type
├── valid_from/to
├── confidence
├── evidence
├── resolution_method
└── state
```

## Stage 5 — Episodes and journeys

Combines observations into bounded temporal structures.

## Stage 6 — Graph mutation

Creates/upserts:

- entities;
- relationships;
- evidence;
- state;
- outcomes;
- temporal versions.

## Stage 7 — Projections

Feeds all 360s.

### Profile360

Consumes resolved entity observations.

### Relationship360

Consumes canonical relationship facts.

### Episode360

Consumes bounded multi-entity temporal sequences.

### Population360

Consumes versioned membership definitions and resolved entities.

### Communication360

Consumes:

- delivery observations;
- message/thread IDs;
- opens;
- clicks;
- replies;
- sessions;
- outcomes.

### Execution360

Consumes:

- execution IDs;
- traces;
- operations;
- tools;
- models;
- services;
- timings;
- failures;
- outputs;
- outcomes.

### Campaign360

Consumes:

- acquisition evidence;
- campaign/source references;
- eligible touchpoints;
- journeys;
- outcomes;
- immutable attribution credits.

---

# 17. Point 16 — Surface Ingestion as an Observable Runtime in Kyber

Kyber needs a complete operator control plane for this subsystem.

Not just logs.

## Kyber → Ingestion

```text
Overview
Sources
Deployments
SDK Versions
Adapters
Schemas
Event Families
Consent
Validation
Quality
Queues
Dead Letters
Replay
Identity Resolution
Graph Projection
Usage
Security
Compliance
```

## Global ingestion dashboard

Show:

```text
observations received
accepted
duplicates
rejected
degraded
quarantined
late arrivals
sequence gaps
schema mismatch
privacy rejection
signature failures
resolution lag
projection lag
dead-letter count
replay volume
```

## Source drill-down

For a Shopify connector:

```text
Shopify
├── connection health
├── webhook health
├── last sync
├── source version
├── observations
├── duplicate rate
├── normalization errors
├── unresolved IDs
├── graph projection lag
└── sample lineage
```

## SDK fleet view

```text
tenant
application
platform
SDK version
schema version
event volume
queue health
failure rate
consent state
deprecated version?
```

## Observation Inspector

An operator should be able to inspect:

```text
RAW
 ↓
RECEIVED
 ↓
VALIDATED
 ↓
BRONZE
 ↓
NORMALIZED
 ↓
RESOLVED
 ↓
RELATIONSHIPS
 ↓
GRAPH MUTATIONS
 ↓
PROJECTIONS
 ↓
METRICS / FINDINGS
```

This becomes a critical debugging surface.

---

# 18. Point 17 — Establish Full Conformance, Compatibility, and Migration Testing

The Universal Ingestion system requires a conformance suite.

## Golden observation fixture

Take one logical action:

```text
order completed
```

Represent it through:

```text
Web SDK
Server API
Shopify webhook
Connector pull
CSV import
Replay
```

After source normalization, all should produce semantically equivalent canonical facts where equivalent source information exists.

Not byte-identical.

Semantically equivalent.

## Contract tests

Test:

```text
schema generation
field trust classes
consent
privacy
source authentication
idempotency
sequence
correlation
time
normalization
tenant isolation
projection
lineage
```

## Cross-language parity

Generate identical fixtures for:

```text
TypeScript
Swift
Kotlin
React Native
Python/backend
```

## Backward compatibility

Every schema change classified:

```text
additive
behavioral
deprecated
breaking
```

### Additive

No SDK upgrade required.

### Backend-only

No SDK upgrade.

### New optional observation field

Older SDK continues functioning.

### Breaking wire change

Requires:

- new schema major;
- compatibility window;
- migration documentation;
- telemetry;
- staged enforcement.

## Version compatibility matrix

Kyber should know:

```text
SDK 8.x → supported
SDK 7.x → supported/deprecated
SDK 6.x → read-compatible
SDK 5.x → blocked after date
```

## Shadow validation

Before enforcing a contract:

```text
observe
→ evaluate new validator
→ record would-reject
→ do not reject
→ measure tenants affected
→ fix
→ warn
→ enforce
```

The current validator already supports staged release-profile enforcement for required envelope fields. 

Generalize this mechanism.

---

# 19. Point 18 — Execute the Migration Through a Controlled Release Program

This should not be one giant PR.

## Workstream A — Contract foundation

### PR 1 — Observation ownership taxonomy

Add:

```text
field authority
trust classes
claim classes
source classes
```

### PR 2 — Universal Observation Envelope

Create backend canonical representation.

Do **not** break `BaseEvent`.

### PR 3 — Contract generator expansion

Generate:

- TS;
- Python;
- Swift;
- Kotlin;
- OpenAPI;
- tests;
- documentation.

---

## Workstream B — Adapter convergence

### PR 4 — SDK adapter

```text
BaseEvent → UniversalObservationEnvelope
```

### PR 5 — Webhook adapter

Common adapter framework.

### PR 6 — Connector adapter

Same contract.

### PR 7 — API/feed/import adapter

Unify server sources.

### PR 8 — Harness/replay adapter

Execution + historical paths.

---

## Workstream C — SDK hardening

### PR 9 — SDK context cleanup

Separate:

```text
observed
hint
server-only
```

fields.

### PR 10 — Native persistent queue

Add durable encrypted queue.

### PR 11 — Credential model

Separate publishable ingress credentials from privileged server credentials.

### PR 12 — SDK generated facades

Remove duplicated registry logic.

---

## Workstream D — Backend integration

### PR 13 — Universal validation

Move all paths through common validation decisions.

### PR 14 — Universal provenance/evidence

Add source lineage.

### PR 15 — Resolution/projector adapters

Wire normalized observations to identity, relationship, episode, graph, and 360 consumers.

---

## Workstream E — Operations

### PR 16 — Ingestion telemetry

Canonical metrics and tracing.

### PR 17 — Kyber ingestion control plane

Health, quality, lineage, replay, versions.

### PR 18 — Conformance + release gates

Golden fixtures, compatibility, shadow enforcement, rollout.

---

# 20. Full runtime behavior — Web SDK example

A shopper enters:

```text
https://shop.example/product
?utm_campaign=summer
&gclid=ABC
```

## Client

SDK initializes:

```text
anonymous_id = ANON7
session_id = SES1
sequence = 1
timezone = America/New_York
UTC offset = -240
campaign evidence
surface = web
SDK = @aether/web 9.x
```

SDK emits:

```text
page
```

No Profile360.

No attribution.

No campaign intelligence.

### User clicks product

```text
sequence = 2
product_viewed
product_id = SKU5
```

### User logs in

```text
identify
anonymous_id = ANON7
user_id = customer_55
```

### User buys

```text
checkout_started
order_completed
```

SDK queues/batches and sends.

---

# 21. Ingestion runtime

`POST /v1/batch`

Current SDK ingestion already supports partial per-event acceptance, Bronze durability before acknowledgment, idempotency, and asynchronous downstream resolution. 

The new runtime becomes:

```text
authenticate publishable key
        ↓
tenant + deployment resolution
        ↓
privacy header capture
        ↓
BaseEvent validation
        ↓
SDKAdapter
        ↓
UniversalObservationEnvelope
        ↓
source trust evaluation
        ↓
consent/policy
        ↓
scrubbing/minimization
        ↓
idempotency
        ↓
Bronze
        ↓
acknowledge
```

Response:

```json
{
  "accepted": 4,
  "duplicates": 0,
  "rejected": 0,
  "batchId": "..."
}
```

The client is done.

Everything else is asynchronous.

---

# 22. Backend processing example

```text
ANON7 page
ANON7 product_viewed
ANON7 + customer_55 identify
customer_55 checkout
customer_55 order
```

Identity resolver establishes:

```text
ANON7 ─────────────┐
SES1 ──────────────┼── Entity E22
customer_55 ───────┘
```

Temporal engine establishes order.

Campaign resolver establishes:

```text
UTM + gclid
   ↓
Campaign C9
```

Journey engine builds:

```text
Journey J4

Campaign entry
 ↓
Product View
 ↓
Login
 ↓
Checkout
 ↓
Purchase
```

Episode engine builds:

```text
Episode E3
type = purchase
```

Outcome engine establishes:

```text
Outcome O2
order completed
$179
```

Attribution engine computes:

```text
Campaign C9
    │
touchpoint
    │
Journey J4
    │
Outcome O2
```

Graph receives:

```text
E22 ──VIEWED──> Product P5
E22 ──PARTICIPATED_IN──> Journey J4
J4  ──CONTAINS──> Episode E3
E3  ──PRODUCED──> Outcome O2
Campaign C9 ──CONTRIBUTED_TO──> O2
```

Then:

```text
Profile360
Campaign360
Relationship360
Episode360
Population360
metrics
findings
```

update.

The SDK did none of it.

---

# 23. Full runtime behavior — Webhook example

SendGrid sends:

```text
email_clicked
message_id = MSG4
url = ...
timestamp
recipient
```

Webhook adapter:

```text
verify SendGrid signature
resolve tenant
preserve provider event ID
sanitize payload
map provider vocabulary
```

Universal observation:

```text
type = email_clicked
source.provider = sendgrid
source_native_id = evt_123
message_id = MSG4
```

Communication resolver links:

```text
Campaign
 ↓
Communication
 ↓
Message MSG4
 ↓
Recipient Entity
 ↓
Click
 ↓
Session
 ↓
Journey
 ↓
Outcome
```

Communication360 emerges entirely server-side.

---

# 24. Full runtime behavior — Agent/Execution example

Agent performs:

```text
user request
 ↓
agent plan
 ↓
model call
 ↓
tool call
 ↓
database query
 ↓
tool output
 ↓
model response
```

Harness captures:

```text
execution_id
trace
span
parent span
agent ID
model
tool
operation
start
finish
latency
status
token/cost telemetry where available
resource references
```

HarnessAdapter converts these to canonical observations.

Backend builds:

```text
Execution X1
├── Agent A1
├── Invocation I1
├── ToolCall T1
├── Resource R1
├── Output O1
└── Outcome
```

Execution360 can then surface:

```text
what ran
who/what initiated it
dependencies
latency
cost
failure
tool usage
evidence
downstream effects
associated entity
associated episode
associated outcome
```

The harness remains an observer.

---

# 25. Full runtime behavior — Connector example

Shopify connector performs a pull.

```text
Orders API
Products API
Customers API
Refunds API
```

Connector records:

```text
provider IDs
provider timestamps
cursor
API version
sync ID
```

Each provider record becomes an observation.

Backend resolves:

```text
Shopify Customer 44
       ↓
Canonical Entity E6

Shopify Order 33
       ↓
Canonical Outcome O7
```

If the same order was also captured by:

```text
browser SDK
+
Shopify webhook
+
connector reconciliation
```

Aether does **not** create three purchases.

It retains three pieces of evidence supporting one canonical outcome.

That is the important shift from an analytics-event model to a graph/evidence model.

---

# 26. How this feeds the canonical graph primitives

The ingestion system provides raw material for:

| Graph primitive | Ingestion contribution |
|---|---|
| Entity | identifiers and source references |
| Observation | primary product of ingress |
| Relationship | evidence required to establish relationship |
| State | source observations supporting temporal state |
| Outcome | observations describing real-world/system results |
| Evidence | provenance and raw lineage |
| Finding | downstream only |
| Decision | downstream/system/operator only |

Therefore:

> **Observation is the ingestion system's canonical output.**

Everything else is progressively governed.

---

# 27. How this interacts with Aether's other blueprints

This blueprint must not duplicate those systems.

## Contract Governance Blueprint

Owns:

```text
what the contracts mean
versions
ownership
generation
compatibility
```

This blueprint **consumes** that governance.

---

## Metrics Blueprint

Owns:

```text
metric algebra
measurement envelope
metric definitions
dimensions
population/grain
reconciliation
```

This blueprint supplies canonical observations.

It does not compute metrics.

---

## Temporal Blueprint

Owns:

```text
valid time
system time
historical reconstruction
timeline
snapshot/replay
```

This blueprint preserves source temporal evidence.

---

## Identity Blueprint

Owns:

```text
identifier → profile → cluster
merge/split
confidence
auditability
```

The SDK supplies identifiers only.

---

## Security Blueprint

Owns:

```text
threat model
red/blue teams
secrets
tenant isolation
security posture
Kyber security controls
```

This blueprint implements ingress security hooks and evidence.

---

## Compliance Blueprint

Owns:

```text
deployment profile obligations
control mapping
evidence
retention
residency
pre-positioning
```

This blueprint enforces applicable ingest collection/retention decisions.

---

## UX/UI Blueprint

Owns customer-facing workflows.

This blueprint supplies:

```text
source health
data quality
connection status
observation lineage
```

for presentation.

---

# 28. Thinness invariant

The final canonical rule should be placed directly into repository governance:

> **An SDK feature is permitted only when the information is uniquely observable at the source, required to preserve correlation/provenance/privacy, or required for reliable delivery. Any capability involving interpretation, resolution, aggregation, classification, graph state, metrics, attribution, intelligence, or decisioning belongs to the backend.**

### Decision matrix

| Proposed feature | Location |
|---|---|
| Capture local timestamp | SDK |
| Capture local timezone | SDK |
| Generate event ID | SDK |
| Preserve click ID | SDK |
| Preserve trace ID | SDK |
| Consent gate | SDK + server |
| Offline queue | SDK |
| Retry | SDK |
| Identity resolution | Backend |
| Campaign resolution | Backend |
| Attribution | Backend |
| Currency normalization | Backend |
| Journey reconstruction | Backend |
| Episode reconstruction | Backend |
| Relationship strength | Backend |
| Risk score | Backend |
| Population membership | Backend |
| Metric computation | Backend |
| Finding | Backend |
| Recommendation | Backend |
| Profile360 | Backend |
| Relationship360 | Backend |
| Communication360 | Backend |
| Execution360 | Backend |

---

# 29. Mandatory architecture invariants

The implementation is not considered complete unless all of the following are true.

1. **One observation model after adapters.**
2. **One Contract Spine governs ingestion vocabulary.**
3. **No SDK owns backend intelligence.**
4. **No public source may assert canonical identity truth.**
5. **Every accepted observation is durable before acknowledgment.**
6. **Every observation has tenant provenance.**
7. **Every provider record preserves source provenance.**
8. **Every ingestion path implements idempotency.**
9. **Consent and privacy policy apply to every path.**
10. **Raw/source data and normalized graph truth remain distinguishable.**
11. **Temporal source information is never discarded.**
12. **Correlation IDs survive normalization.**
13. **Missing/empty/zero/degraded states remain distinct.**
14. **Derived claims retain evidence and model/policy lineage.**
15. **Replays never masquerade as new occurrence time.**
16. **SDK schemas are generated rather than manually drifting.**
17. **Kyber can trace observations end-to-end.**
18. **Backend intelligence changes do not require SDK releases unless source-observable information must change.**

---

# 30. Required release coverage matrix

| Surface | Capture | Universal Envelope | Privacy | Idempotency | Temporal | Correlation | Provenance | Replay | Kyber |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Web SDK | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| iOS SDK | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Android SDK | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| React Native | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Server API | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Public webhook | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Auth webhook | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Connector pull | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Bulk import | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| External feed | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Agent harness | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Internal replay | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

No ingress method receives a special exemption.

---

# 31. Downstream coverage matrix

| System | Reads observation | Resolves/derives | Writes canonical state |
|---|---:|---:|---:|
| SDK | ✓ | No | No |
| Adapter | ✓ | structural only | No |
| Ingestion gateway | ✓ | policy only | receipt |
| Bronze | ✓ | No | raw observation |
| Normalizer | ✓ | ✓ | normalized facts |
| Identity resolver | ✓ | ✓ | entity mappings |
| Temporal engine | ✓ | ✓ | temporal state |
| Relationship engine | ✓ | ✓ | relationships |
| Journey engine | ✓ | ✓ | journeys |
| Episode engine | ✓ | ✓ | episodes |
| Outcome engine | ✓ | ✓ | outcomes |
| Metrics | downstream | ✓ | measurements |
| Attribution | downstream | ✓ | immutable credits |
| Findings | downstream | ✓ | findings |
| 360 projections | downstream | ✓ | projections |
| Kyber | all | operator actions | governed changes |

---

# 32. Release gates

The system is not production-complete merely because code compiles.

## Gate A — Contract

- canonical source/observation authority defined;
- generated artifacts deterministic;
- schema compatibility tests pass;
- no duplicate registries.

## Gate B — SDK

- all four SDKs pass parity;
- persistent native queues;
- public-key scope verified;
- no backend intelligence imports;
- offline/reconnect tests pass.

## Gate C — Ingestion

- all paths normalize through universal adapters;
- Bronze-before-ACK;
- idempotency verified;
- partial failure tested;
- tenant isolation tested.

## Gate D — Privacy/Security

- consent parity;
- GPC/DNT;
- signature verification;
- sensitive-field scrub;
- source trust;
- malicious payload tests;
- credential boundaries.

## Gate E — Graph

Golden observations correctly produce:

```text
entities
relationships
journeys
episodes
outcomes
```

without source-specific frontend hacks.

## Gate F — 360s

Profile360, Relationship360, Episode360, Population360, Communication360, Execution360, and Campaign360 consume canonical backend state, not SDK-specific payload assumptions.

## Gate G — Operations

Kyber exposes:

- source health;
- schema health;
- ingestion lag;
- quality;
- rejection;
- replay;
- lineage.

## Gate H — Compatibility

Previous supported SDK versions continue functioning.

## Gate I — Failure testing

Test:

```text
Kafka unavailable
Bronze unavailable
Redis unavailable
provider duplicated webhook
out-of-order records
clock skew
invalid timezone
bad signature
revoked consent
schema mismatch
SDK process killed offline
source replay
connector reconnect
cross-tenant collision
```

## Gate J — Documentation

Update:

```text
SDK_SCOPE
INGESTION_CONTRACT
EVENT_REGISTRY
DATA_INGESTION_PATHS
WEBHOOK_INGESTION
CONNECTORS
API docs
Kyber operator docs
security controls
compliance evidence map
```

---

# 33. What success looks like

After implementation, Aether can add:

```text
new metrics
new graph algorithms
new lenses
new Relationship360 capabilities
new Episode360 capabilities
new Population360 capabilities
new Communication360 intelligence
new Execution360 intelligence
new findings
new attribution models
new prediction models
new investigations
new graph projections
new Kyber tools
```

without requiring customers to upgrade the SDK.

A customer who installed:

```text
Aether SDK v9
```

can continue sending the same observational evidence while:

```text
Aether backend v10
Aether backend v11
Aether backend v12
```

becomes progressively more capable.

That is the test of whether the SDK is truly thin.

---

# 34. Final target architecture

```text
                       SOURCE WORLD
                           │
       ┌───────────────────┼────────────────────┐
       │                   │                    │
   Client SDKs          Providers           Runtime
       │             APIs/Webhooks          Harness
       │                   │                    │
       └───────────────────┼────────────────────┘
                           │
                     OBSERVATIONS
                           │
                           ▼
                 ┌──────────────────┐
                 │ Ingress Adapters │
                 └────────┬─────────┘
                          │
                          ▼
             UNIVERSAL OBSERVATION ENVELOPE
                          │
                          ▼
                  CONTRACT + POLICY GATE
                          │
                          ▼
                  IMMUTABLE EVIDENCE
                          │
                          ▼
                     NORMALIZATION
                          │
                          ▼
                       RESOLUTION
                          │
                          ▼
              TEMPORALLY VALID RELATIONSHIPS
                          │
                          ▼
                  UNIFIED IN



---
---

## Document provenance (recovery note — not part of the source blueprint)

This blueprint is the **controlling artifact** for the SDK + Universal Ingestion
Alignment program. The governing architecture dictum it fixes in place is:

> **Sources observe. Ingestion preserves. Aether interprets. The graph establishes
> governed state. Intelligence systems derive meaning.**

The text above is a **verbatim recovery** (2026-09-04) of the pasted source
blueprint from the program session transcript (source line 3, single user
message). Nothing was summarized, edited, or reordered; ASCII diagrams and
box-drawing characters are preserved as stored.

**Known truncation — section 34 tail:** the source paste was recorded under a
50,000-character message cap, so the stored text ends mid-way through the
section-34 *Final target architecture* diagram, at the line `UNIFIED IN`. The
remainder of that diagram (the node(s) below `UNIFIED IN`), the closing code
fence, and any closing prose of section 34 are **not recoverable verbatim**
and were **not reconstructed by guessing**. No untruncated copy exists in any
project transcript (a sibling transcript holds a byte-identical, identically
truncated copy). Curated rendering of the target architecture, including the
section-34 final-architecture diagram, lives in
`docs/productization/sdk-universal-ingestion-alignment/TARGET_ARCHITECTURE.md`.

**Caveats:** the document is commonly described as "34 sections"; headings are
numbered 0–34 inclusive (35 `#` headings), where section 0 is the executive
directive and section 1 opens the target end-to-end architecture.
