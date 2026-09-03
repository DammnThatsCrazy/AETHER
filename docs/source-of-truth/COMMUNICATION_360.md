---
title: Communication360 — Day-1 Blueprint Source of Truth
slug: source-of-truth/communication-360
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
canonical_owner: backend@aether
estimated_read_minutes: 60
toc_depth: 4
---

# Communication360 — Day-1 Blueprint Source of Truth

This is the architecture source of truth for **Communication360**, Aether's
communication and information-flow intelligence projection over the Unified
Intelligence Graph. It captures the governing Day-1 specification in full. The
implementation program and its ledger are
[docs/plans/COMMUNICATION_360_PHASES.md](../plans/COMMUNICATION_360_PHASES.md);
the per-projection vertical-slice design is
[docs/blueprints/communication360.md](../blueprints/communication360.md).

Communication360 is an **intelligence projection** under the Intelligence
Projection Plane (ADR-010). It interprets canonical Aether communication truth;
it does not create an independent communication graph, identity model, evidence
system, temporal line, campaign truth, outcome ledger, or security engine. It is
a registered row in
[packages/shared/contracts/intelligence-projection-registry.json](../../packages/shared/contracts/intelligence-projection-registry.json):

```text
id: communication360
displayName: Communication 360
projectionKind: sequence_360
implementationState: in_flight
legacyBindings.migrationMode: adapter
graphMutationPolicy: read_only
ownsCanonicalTruth: false
requiresEvidence: true
subjectKinds: [campaign, episode, source]
```

The body of this document (sections 1-192) is the **"Aether Communication360 -
Day-1 Production Implementation Blueprint"** captured near-verbatim as the
governing specification (audit date 2026-09-03). Section numbering is preserved;
headings are demoted one level so the document keeps a single title. Where the
blueprint speaks in vocabulary the repository does not yet share ("eight
planes", bare `SENT`/`RECEIVED`/`CONTAINS` edges, a dotted event taxonomy), the
reconciliation of that language onto the real architecture (ADR-010, the
declarative registries under `packages/shared/contracts/`, the `services/comms`
silver path, the connector catalog, agentic observability, identity and
delegation services) is recorded in the program plan's section 0 mapping table
and reflected in the vertical-slice blueprint.

This source of truth is the **target-state specification** for the Day-1
program. Nothing here asserts current implementation: `communication360` remains
`in_flight` on this lineage and is not claimed production-ready by this
document.

---

## The Day-1 specification (verbatim)

> Status, purpose, and the complete Day-1 specification as authored in the
> master blueprint. Text is unchanged; section headings are demoted one level.


**Status:** Canonical implementation blueprint  
**Purpose:** Define everything required to build, integrate, validate, operate, and ship Communication360 as a production-ready Aether capability on Day 1.  
**Architecture posture:** Additive. Communication360 extends the existing Aether contract spine, evidence architecture, graph, temporal system, Exploration Fabric, metric algebra, 360 projections, security controls, and Kyber operations. It does not create parallel infrastructure.

---

## 1. Executive directive

Communication360 is Aether's canonical system for understanding **information exchange and information movement** across humans, agents, organizations, campaigns, applications, services, communication providers, tools, and autonomous runtimes.

Communication360 must answer:

> **What information existed, who or what communicated it, through which mechanism, to whom, while acting for whom, under what authority, how the information changed in transit, what the recipient knew or interpreted, what action followed, and what outcome was affected?**

Communication360 is not an email dashboard.

It is not a Mailchimp, Klaviyo, Gmail, Slack, Claude, GPT, Cursor, MCP, or agent-observability wrapper.

It is not a second attribution engine.

It is not a transcript store.

It is not a replacement for Execution360, Campaign360, Agent360, Relationship360, Episode360, Profile360, or the canonical graph.

It is:

> **The communication and information-flow intelligence projection of the Aether Unified Intelligence Graph.**

---

## 2. Day-1 definition of complete

Communication360 is considered production-ready only when the complete path works:

```text
SOURCE
  ↓
OBSERVATION
  ↓
CONTRACT VALIDATION
  ↓
AUTHORIZATION / PURPOSE / CONSENT
  ↓
BRONZE EVIDENCE
  ↓
CANONICAL NORMALIZATION
  ↓
DEDUPLICATION
  ↓
PARTICIPANT RESOLUTION
  ↓
PRINCIPAL / DELEGATION RESOLUTION
  ↓
TEMPORAL + CONTEXT RESOLUTION
  ↓
THREAD / CONVERSATION / MATTER / EPISODE RESOLUTION
  ↓
INFORMATION + CLAIM EXTRACTION
  ↓
GRAPH MUTATION
  ↓
KNOWLEDGE / INTERPRETATION STATE
  ↓
METRICS + FINDINGS
  ↓
COMMUNICATION360 PROJECTION
  ↓
PROFILE360 / AGENT360 / RELATIONSHIP360 / CAMPAIGN360
  ↓
EPISODE360 / EXECUTION360 / OUTCOME360
  ↓
EXPLORATION FABRIC
  ↓
NOESIS / INVESTIGATIONS / EXPORTS
  ↓
KYBER OPERATIONS
  ↓
RECONCILIATION
  ↓
REPLAY
  ↓
AUTOMATED RELEASE PROOF
```

A schema alone is not implementation.

A connector alone is not implementation.

A UI alone is not implementation.

A Day-1 implementation requires this entire chain.

---

## 3. Product ownership boundary

Communication360 owns:

- canonical communication representation;
- canonical information-transfer representation;
- message and payload semantics;
- conversation resolution;
- communication participants and roles;
- communication acts;
- information propagation;
- claim propagation through communications;
- knowledge/interpretation state derived from communication evidence;
- communication quality;
- communication-specific measurements;
- communication-specific findings;
- communication projections into other 360s;
- communication exploration.

Communication360 does **not** own:

- canonical identity;
- identity resolution infrastructure;
- campaign truth;
- attribution truth;
- general outcomes;
- canonical graph storage;
- temporal infrastructure;
- consent infrastructure;
- policy engine;
- evidence system;
- security engine;
- metric engine;
- Investigation objects;
- job infrastructure;
- export infrastructure;
- Noesis;
- Kyber identity/access;
- billing;
- deployment profiles.

Those are consumed through shared contracts.

---

## 4. Foundational architecture invariants

Day-1 implementation must enforce the following.

### 4.1 Message is not information

```text
Message != Information
Information != Claim
Claim != Evidence
```

### 4.2 Sender is not author

```text
Actor
Author
Generator
Editor
Approver
Presented Sender
Actual Sender
Principal
Delegator
Beneficiary
Accountable Party
```

must be independently representable.

### 4.3 Delivery is not knowledge

```text
delivered != read
read != understood
understood != believed
believed != used
```

### 4.4 Communication is broader than text

Information may move through:

```text
messages
email
chat
context bundles
shared state
memory
artifacts
structured payloads
tool results
files
agent protocols
voice
meetings
events
```

### 4.5 Agent death does not erase lineage

An agent instance may terminate.

Its:

- messages;
- delegations;
- context;
- findings;
- actions;
- information;
- evidence;
- outcomes;

remain attached to the graph according to retention policy.

### 4.6 Communication association is not causality

Communication360 must preserve:

```text
observed
associated
sequenced
correlated
attributed
causally_supported
```

as distinct claims.

### 4.7 Provider limitation is not zero

If inter-agent messaging cannot be observed:

```text
availability = unavailable
```

not:

```text
message_count = 0
```

---

## 5. The five foundational gaps become hard requirements

### 5.1 Information/Claim separation

Required canonical concepts:

```text
InformationRef
InformationFragmentRef
ClaimRef
InformationTransformationRef
```

Information must be independently addressable from the message carrying it.

#### Example

```text
Evidence
  ↓
Claim: Vendor A supports FedRAMP
  ↓
Subagent Message
  ↓
Orchestrator Summary
  ↓
Outbound Email
  ↓
Decision
```

Every transformation remains traceable.

---

### 5.2 Delegation and authority

Required:

```text
DelegationRef
AuthorityScope
PrincipalRef
DelegatorRef
DelegateRef
BeneficiaryRef
AccountablePartyRef
```

Communication360 must be able to determine:

- who acted;
- who authorized the actor;
- what the actor was allowed to do;
- whether the communication was within scope;
- who ultimately benefited;
- who is accountable.

---

### 5.3 InformationTransfer

`InformationTransfer` becomes the parent abstraction.

```text
InformationTransfer
├── CommunicationMessage
├── ContextTransfer
├── SharedStateTransfer
├── ArtifactTransfer
├── MemoryTransfer
├── ToolResultTransfer
├── StructuredTransfer
└── EventSignal
```

This prevents agent systems from becoming invisible when they communicate without conventional messages.

---

### 5.4 Knowledge and interpretation

Required:

```text
InterpretationRef
KnowledgeStateRef
ContextInclusionRef
```

These capture whether information was:

```text
available
received
ingested
parsed
included_in_context
recognized
believed
disputed
ignored
used
superseded
unknown
```

---

### 5.5 Policy and provenance

Every communication path must be:

- tenant scoped;
- purpose scoped;
- policy evaluated;
- retention classified;
- evidence referenced;
- access controlled;
- provenance marked;
- capability aware.

There is no ungoverned "raw transcript" shortcut.

---

## 6. Canonical object model

The following are the Day-1 Communication360 objects.

### 6.1 InformationTransfer

Parent object representing meaningful transfer of information.

Required fields:

```text
transfer_id
tenant_id
transfer_type

source_actor_ref
destination_actor_refs[]

principal_ref?
delegation_ref?
beneficiary_ref?

payload_refs[]
information_refs[]

provider_ref?
channel

conversation_ref?
thread_ref?
matter_ref?
episode_ref?
execution_ref?
campaign_ref?

started_at
completed_at?

delivery_state
consumption_state

policy_ref
evidence_refs[]

availability_state
quality_ref
```

---

## 7. CommunicationArtifact

Represents the reusable or conceptual authored artifact.

Examples:

- campaign template;
- newsletter;
- promotional email;
- outbound sales template;
- agent-generated message draft;
- support response template;
- notification body.

Required:

```text
artifact_id
artifact_type
title?
subject?
body_ref?
format
language

author_ref?
generated_by_ref?
edited_by_refs[]
approved_by_refs[]

template_ref?
variant_ref?
parent_artifact_ref?

attachment_refs[]
embedded_link_refs[]

content_hash
created_at
version

policy_ref
```

---

## 8. CommunicationBatch

Required for bulk communication.

A template sent to one million recipients must not become one million separately authored artifacts.

```text
CommunicationArtifact
        ↓
CommunicationBatch
        ↓
DeliveryInstance[]
```

Fields:

```text
batch_id
artifact_ref
campaign_ref?
provider_ref
sender_ref
principal_ref
recipient_population_ref?
started_at
completed_at
delivery_count
```

---

## 9. CommunicationDelivery

Represents delivery of an artifact/message instance to one or more recipients.

```text
delivery_id
artifact_ref
batch_ref?
provider_message_id?
sender_ref
recipient_refs[]

sent_at
delivered_at?
opened_at?
read_at?

delivery_state

campaign_ref?
conversation_ref?
policy_ref
evidence_refs[]
```

---

## 10. CommunicationMessage

Represents a concrete communication instance.

Required:

```text
communication_id
tenant_id

transfer_ref
artifact_ref?
delivery_ref?

channel
provider
provider_message_id?

actor_ref
author_ref?
generator_ref?
editor_refs[]
approver_refs[]
sender_ref
presented_sender_ref?
principal_ref?
delegator_ref?
beneficiary_ref?
accountable_party_ref?

recipient_refs[]
cc_refs[]
bcc_refs[]

thread_ref?
conversation_ref?
matter_ref?
episode_ref?
campaign_ref?
execution_ref?
delegation_ref?

reply_to_ref?
parent_message_ref?

payload_refs[]
attachment_refs[]
link_refs[]

created_at
sent_at?
received_at?
processed_at?

availability_state
quality_ref

policy_ref
consent_ref?
evidence_refs[]
```

---

## 11. CommunicationPayload

Payload is medium independent.

```text
payload_id
payload_type

natural_language
structured_data
instruction
context_bundle
code
file
artifact
tool_result
memory
signal
audio
video
image
```

Payload can be:

```text
inline
referenced
encrypted
redacted
expired
unavailable
```

Communication360 must not assume `body: string`.

---

## 12. CommunicationSegment

Messages may contain several independent communication acts.

Example:

```text
Order confirmation
Shipping delay
Cross-sell offer
Review request
Legal footer
```

Each may become a segment.

```text
segment_id
communication_ref
sequence
content_ref
act_refs[]
information_refs[]
link_refs[]
```

This enables segment-level analysis without making the entire message a single semantic label.

---

## 13. Information

Information represents semantic content independent from transport.

```text
information_id
tenant_id
information_type
canonical_representation
source_fragment_refs[]
claim_refs[]
origin_ref
created_at
```

Potential relationships:

```text
derived_from
summarizes
paraphrases
translates
extracts
synthesizes
corrects
contradicts
supersedes
```

---

## 14. Claim

Claim uses the canonical epistemic architecture.

```text
claim_id
subject_ref
predicate
object/value

claim_type
epistemic_state

confidence
valid_at
observed_at

evidence_refs[]
contradictory_evidence_refs[]

origin_information_ref?
origin_communication_ref?

model_ref?
policy_ref?

freshness
limitations[]
```

Communication360 never introduces an alternative epistemic system.

---

## 15. InformationTransformation

Represents change between information states.

```text
transformation_id
source_information_refs[]
output_information_ref

transformation_type

summary
paraphrase
translation
extraction
synthesis
correction
contradiction
omission
augmentation

performed_by_ref
execution_ref?
model_ref?

retained_claim_refs[]
removed_claim_refs[]
added_claim_refs[]

confidence
evidence_refs[]
```

This is the core of agent information-fidelity analysis.

---

## 16. Conversation

Provider threads do not define canonical Aether conversations.

```text
conversation_id
participant_refs[]
channel_refs[]
provider_thread_refs[]
matter_ref?
episode_refs[]

started_at
last_activity_at
state

open
awaiting_response
responded
resolved
escalated
abandoned
unknown

quality_ref
```

---

## 17. ProviderThread

Native provider grouping.

Examples:

```text
Gmail thread
Slack thread
Intercom ticket
agent orchestration session
```

Fields:

```text
provider_thread_id
provider
provider_account_ref
native_identifier
conversation_ref?
```

Aether can combine multiple provider threads into one conversation or Matter.

---

## 18. Matter

A long-running semantic subject.

Example:

```text
Customer renewal
Vendor procurement
Fraud investigation
Support issue
Agent research assignment
```

A Matter may span:

- several email threads;
- Slack;
- agents;
- meetings;
- campaigns;
- applications.

It sits between Conversation and Episode where useful.

---

## 19. CommunicationAct

Canonical acts:

```text
inform
ask
request
answer
respond
offer
recommend
accept
reject
approve
deny
instruct
delegate
handoff
escalate
commit
cancel
warn
notify
acknowledge
correct
dispute
```

One message can contain several acts.

Each act has:

```text
act_id
communication_ref
segment_ref?
act_type
actor_ref
target_refs[]
information_refs[]
confidence
evidence_refs[]
```

---

## 20. Request

Requests become durable objects.

```text
request_id
requester_ref
target_ref
requested_action
communication_ref
created_at
due_at?
status
response_ref?
fulfillment_ref?
```

States:

```text
open
fulfilled
partially_fulfilled
rejected
expired
cancelled
unknown
```

---

## 21. Commitment

```text
commitment_id
promisor_ref
beneficiary_ref
commitment_content
origin_communication_ref
due_at?
status
fulfillment_ref?
```

This supports operational questions such as:

> What promises are outstanding?

---

## 22. ResponseExpectation

Silence must be representable when a response is expected.

```text
expectation_id
trigger_ref
expected_from_ref
expected_by
status
fulfilled_by_ref?
```

States:

```text
pending
fulfilled
missed
cancelled
unknown
```

---

## 23. Delegation

Delegation must be a canonical temporal relationship.

```text
delegation_id

principal_ref
delegator_ref
delegate_ref
beneficiary_ref?
accountable_party_ref?

task_ref
purpose

authority_scope[]
permitted_actions[]
prohibited_actions[]

permitted_channels[]
permitted_recipients[]

data_access_scope[]
financial_limit?
geographic_scope?

valid_from
valid_to?
revoked_at?

episode_ref?
execution_ref?

policy_ref
evidence_refs[]
```

---

## 24. Delegation evaluation

Every agent-mediated communication derives:

```text
authorization_state
```

Possible values:

```text
authorized
authorized_within_scope
authorized_pending_approval
scope_exceeded
expired
revoked
policy_blocked
unknown
```

The raw communication remains evidence even if blocked.

---

## 25. Interpretation

Represents Aether-supported understanding of what the recipient extracted.

```text
interpretation_id
recipient_ref
communication_ref
information_refs[]

retained_information_refs[]
modified_information_refs[]
ignored_information_refs[]
contradicted_information_refs[]

confidence
model_ref?
evidence_refs[]
```

This object must never pretend private cognitive state is observed when it is merely inferred.

---

## 26. KnowledgeState

Represents what information is supported as available/known to an actor at time T.

```text
knowledge_state_id
entity_ref
information_ref

state

available
received
ingested
parsed
included_in_context
recognized
believed
disputed
ignored
retained
used
superseded
unknown

valid_from
valid_to?
confidence
evidence_refs[]
```

---

## 27. Agent context inclusion

Agent systems require an explicit Context Inclusion object/event.

```text
context_inclusion_id
execution_ref
agent_instance_ref
information_ref
context_position?
token_range?
included_at
removed_at?
source_ref
```

This enables Aether to answer:

> Was the constraint actually present in the agent's working context when it decided?

---

## 28. Agent memory boundary

Memory remains separate.

```text
Communication
      ↓
stored_as_memory
      ↓
Memory
      ↓
retrieved_into_context
      ↓
Execution
```

Required relationships:

```text
stored_as_memory
retrieved_from_memory
superseded_memory
forgotten
memory_influenced
```

Communication360 references memory but does not own the complete Agent360 memory subsystem.

---

## 29. Contract Spine integration

All objects are registered through the existing Contract Spine.

Required Communication360 contract modules:

```text
communication_artifact
communication_batch
communication_delivery
communication_message
communication_payload
communication_segment

information_transfer
information
information_transformation
claim_binding

conversation
provider_thread
matter

communication_act
request
commitment
response_expectation

delegation
communication_participant

interpretation
knowledge_state
context_inclusion

communication_quality
communication_capability
```

No frontend or provider adapter may define independent versions.

---

## 30. Registry additions

Extend existing registries.

### Entity registry

Add no duplicate human/agent entities.

Register only new domain objects where they qualify.

### Relationship registry

Add:

```text
SENT
RECEIVED
ACTED_FOR
AUTHORIZED_BY
DELEGATED_TO
GENERATED_BY
EDITED_BY
APPROVED_BY
RESPONDS_TO
PART_OF_CONVERSATION
PART_OF_MATTER
PART_OF_EPISODE
CONTAINS_INFORMATION
REFERENCES
SUPPORTED_BY
CONTRADICTS
DERIVED_FROM
INCLUDED_IN_CONTEXT
STORED_AS_MEMORY
USED_IN_DECISION
CONTRIBUTED_TO_OUTCOME
```

### Dimension registry

Register:

```text
channel
provider
participant_type
actor_type
principal_type
communication_act
topic
matter
conversation_state
delivery_state
consumption_state
authority_state
information_state
availability_state
```

---

## 31. Eight-plane architecture

Communication360 is implemented across the canonical eight planes.

```text
1. Contract & Governance
2. Capture & Acquisition
3. Evidence & Data
4. Resolution & Entity
5. Temporal & Contextual
6. Relationship & Graph
7. Intelligence & Measurement
8. Experience, Decision & Operations
```

It is not a ninth plane.

---

## 32. Plane 1 — Contract & Governance

Plane 1 defines:

- canonical fields;
- required versus optional semantics;
- schemas;
- enum registries;
- provider capability declaration;
- contract ownership;
- compatibility;
- migration;
- policy references;
- retention behavior;
- access-control requirements.

### Day-1 deliverables

- schemas for every canonical object;
- JSON/OpenAPI representation;
- persistence representation;
- event representation;
- contract tests;
- fixtures;
- golden examples;
- migration rules;
- versioning policy;
- schema registry integration.

---

## 33. Communication capability contract

Each provider declares what it can actually expose.

```text
content
subject
sender
recipient
thread
attachments
links
delivery
open
click
reply
edit_history
deletion

campaign_context

agent_messages
agent_delegations
agent_context
agent_memory
agent_shared_state
agent_tool_results
authority_context
```

Capability has state:

```text
supported
unsupported
partial
permission_dependent
provider_dependent
unknown
```

This capability object follows the observation downstream.

---

## 34. Plane 2 — Capture & Acquisition

Supported acquisition categories:

### Communication providers

```text
Klaviyo
Mailchimp
Customer.io
Braze
HubSpot
SendGrid
Gmail
Outlook
other connector-supported providers
```

### Agent runtime providers

```text
OpenAI-compatible agent runtimes
Claude-compatible runtimes
Cursor
Manus
Hermes
other instrumentable systems
```

Day-1 support does not require universal runtime support.

It requires the universal contract plus truthful adapter capabilities.

### Protocols

```text
Aether SDK
Aether harness
MCP
A2A-compatible runtime integration
webhooks
REST
stream/event
```

---

## 35. Provider adapter contract

Every provider adapter must:

1. authenticate through the shared connector system;
2. map source account to tenant;
3. preserve provider IDs;
4. emit canonical observation envelopes;
5. preserve original timestamps;
6. declare provider capability;
7. retain raw provenance;
8. never resolve identities locally;
9. never perform campaign attribution locally;
10. never generate independent graph objects.

Adapters translate.

They do not become mini-intelligence systems.

---

## 36. Provider observation envelope

Minimum provider event:

```text
observation_id
tenant_id
provider
provider_account_ref
provider_event_id
provider_event_type

source_identity_refs

event_time
received_time
ingested_at

raw_payload_ref
schema_version

capability_ref
policy_context

evidence_hash
```

---

## 37. Aether Agent Harness

The Aether harness must support Communication360 observability directly.

Required hooks:

```text
register_agent
start_agent_instance
end_agent_instance

create_delegation
update_delegation
revoke_delegation

emit_message
emit_context_transfer
emit_shared_state_write
emit_shared_state_read
emit_artifact_transfer
emit_memory_write
emit_memory_read
emit_tool_result_transfer

record_external_contact
record_external_response

record_context_inclusion
record_task_response

record_human_approval
record_human_edit
record_human_rejection
```

---

## 38. Harness event taxonomy

Required Day-1 events:

```text
agent.instance.created
agent.instance.started
agent.instance.completed
agent.instance.failed
agent.instance.terminated

agent.delegation.created
agent.delegation.accepted
agent.delegation.completed
agent.delegation.failed
agent.delegation.revoked

communication.transfer.started
communication.transfer.completed
communication.message.created
communication.message.sent
communication.message.received
communication.message.failed

communication.context.transferred
communication.context.received

communication.shared_state.written
communication.shared_state.read

communication.artifact.shared

communication.external.sent
communication.external.received

communication.response.generated
communication.response.received

communication.handoff.created
communication.handoff.completed
communication.handoff.failed
```

---

## 39. Plane 3 — Evidence & Data

Communication360 uses the existing evidence pipeline.

```text
BRONZE
→ SILVER
→ GOLD
```

### Bronze

Immutable source evidence.

Contains:

- provider raw event;
- raw payload;
- source identifiers;
- timestamps;
- hash;
- connector version;
- policy classification;
- ingestion metadata.

Bronze is not modified to match later interpretation.

---

## 40. Silver

Silver contains normalized communication facts.

Examples:

```text
normalized provider
normalized channel
normalized sender identifiers
normalized recipient identifiers
normalized thread
normalized timestamps
normalized payload references
normalized link references
normalized attachment references
normalized delivery states
```

No inferred customer identity is written as observed provider truth.

---

## 41. Gold

Gold contains derived intelligence:

```text
resolved participants
principal/delegation bindings
conversation resolution
matter resolution
information objects
claims
communication acts
topics
interpretations
knowledge states
information transformations
metrics
findings
outcome links
```

Gold must be recomputable.

---

## 42. Raw content storage

Raw communication content should not be treated as graph-native state.

Logical storage separation:

```text
Raw Content Store
Bronze Evidence
Canonical Facts
Graph
Semantic Index
Projection Store
```

This allows different:

- retention;
- encryption;
- indexing;
- residency;
- scaling;
- access controls.

---

## 43. Content lifecycle

Required states:

```text
available
redacted
expired
provider_deleted
tenant_deleted
policy_purged
unavailable
missing
corrupt
```

Historical metadata remains truthful where policy allows.

---

## 44. Deduplication

Deduplication must occur before communication metrics and graph mutation.

Potential identity signals:

```text
provider_message_id
provider_thread_id
provider_account
sender
recipient set
content fingerprint
timestamp
transport fingerprint
batch ID
```

A canonical communication can reference multiple source observations.

```text
CanonicalMessage
  ├── Gmail webhook evidence
  ├── Gmail synchronization evidence
  └── Agent harness evidence
```

No metric inflation.

---

## 45. Idempotency

Every pipeline stage must be safely replayable.

Required deterministic keys for:

- source observations;
- normalized messages;
- communication deliveries;
- information extraction;
- claims;
- graph mutations;
- metrics.

Re-running ingestion must not double count.

---

## 46. Replay

Day-1 operational tooling must support:

```text
source replay
normalization replay
participant resolution replay
conversation resolution replay
semantic extraction replay
graph replay
metric replay
projection replay
```

Original evidence remains unchanged.

---

## 47. Plane 4 — Resolution & Entity

Communication identities use the existing identity architecture.

Resolvable participant types:

```text
Human
Organization
AgentDefinition
AgentInstance
Account
Mailbox
Application
Service
Device
Wallet
Resource
Campaign
```

No Communication360 profile system.

---

## 48. Participant identity model

Every participant binding records:

```text
source_identifier
canonical_entity_ref?
resolution_state
resolution_method
confidence
valid_from
valid_to?
evidence_refs[]
```

States:

```text
resolved
partially_resolved
ambiguous
unresolved
suppressed
```

---

## 49. Human aliases

Example:

```text
john@example.com
Slack @john
CRM account 992
Profile p_81
```

Identity resolution determines whether those represent one person.

Communication360 only consumes the result.

---

## 50. Agent identity

Agent identifiers can include:

```text
provider_agent_id
runtime_agent_id
session_id
Aether agent_instance_id
agent_definition_id
friendly_name
```

Agent continuity relationships:

```text
spawned_from
forked_from
resumed_from
cloned_from
replaced_by
inherits_context_from
inherits_memory_from
```

---

## 51. Actor/principal model

Required communication participation roles:

```text
actor
author
generator
editor
approver
sender
presented_sender
principal
delegator
delegate
beneficiary
accountable_party

to
cc
bcc
observer
subscriber
mentioned
```

These roles are temporally valid.

---

## 52. Example: AI mailbox sender

```text
Presented sender:
Alice <alice@acme.com>

Executing actor:
SalesAgent-12

Principal:
Acme Corporation

Delegator:
Alice

Authorization:
outbound prospecting

Approved by:
Alice
```

Profile360 must not report:

> Alice wrote this email.

unless evidence supports that claim.

---

## 53. Plane 5 — Temporal & Contextual

Required timestamps:

```text
created_at
sent_at
provider_received_at
delivered_at
opened_at
read_at
event_time
ingestion_time
processing_time
valid_from
valid_to
```

Agent systems additionally require:

```text
logical_order
causal_order
```

---

## 54. Causal communication ordering

Relations:

```text
responds_to
triggered_by
depends_on
preceded_by
concurrent_with
supersedes
```

must not be inferred purely from timestamps.

This is critical for parallel subagents.

---

## 55. Historical reconstruction

Aether must be able to reconstruct:

> What communications had Agent A received by 10:04?

> What authority did Agent A have when it sent the email?

> What version of the message existed then?

> Which evidence had been discovered?

> Which contradictory claim arrived afterward?

This reuses the Aether Time Machine.

---

## 56. Context capsule

Communication computations should retain:

```text
tenant_id
time range
timezone

campaign_ref?
episode_ref?
execution_ref?
delegation_ref?
principal_ref?
population_ref?
investigation_ref?

data watermark
identity watermark
model version
policy version
provider capability version
```

---

## 57. Provider thread resolution

Native provider grouping is preserved.

```text
Gmail thread
Klaviyo delivery
Slack thread
agent session
support ticket
```

These do not automatically equal Aether Conversation.

---

## 58. Conversation resolution

Conversation resolution combines:

- participants;
- subject/topic;
- temporal continuity;
- reply lineage;
- provider threads;
- linked activities;
- shared Matter;
- explicit customer/agent session IDs.

Resolution records:

```text
method
confidence
supporting evidence
contradictions
```

---

## 59. Matter resolution

Matter binds longer-lived subject continuity.

Example:

```text
Email thread: renewal
Slack discussion: renewal
Agent research: renewal
Support case: renewal
```

all link to:

```text
Matter: 2026 Enterprise Renewal
```

---

## 60. Episode integration

Communication is one component of Episode360.

Example:

```text
Human request
→ Orchestrator delegation
→ Subagent research
→ Evidence acquisition
→ Agent response
→ External email
→ Vendor reply
→ Decision
```

All belong to one Episode even if multiple agents die.

---

## 61. Plane 6 — Relationship & Graph

Communication360 adds graph relationships, not a separate graph.

Core edge families:

```text
Entity ─SENT→ Communication
Communication ─SENT_TO→ Entity
Agent ─ACTED_FOR→ Principal
Delegator ─DELEGATED_TO→ Agent
Communication ─PART_OF→ Conversation
Conversation ─PART_OF→ Matter
Conversation ─PART_OF→ Episode
Communication ─CONTAINS→ Information
Information ─ASSERTS→ Claim
Claim ─SUPPORTED_BY→ Evidence
Communication ─REFERENCES→ Resource
Communication ─ASSOCIATED_WITH→ Campaign
Information ─INCLUDED_IN_CONTEXT→ AgentExecution
Information ─USED_IN→ Decision
Decision ─RESULTED_IN→ Action
Action ─CONTRIBUTED_TO→ Outcome
```

---

## 62. Relationship semantics

Every durable relationship must support, where appropriate:

```text
valid_from
valid_to
observed_at
confidence
evidence_refs
provenance
resolution_method
quality_state
```

---

## 63. Communication graph cardinality

Do not render every message as a visible graph vertex at default zoom.

### Level 1

```text
Human ───── Agent
     802 interactions
```

### Level 2

```text
Human
 ├── Vendor Research Episode
 ├── Renewal Conversation
 └── Support Matter
```

### Level 3

```text
Message
Request
Response
Claim
Finding
```

This keeps graph exploration usable at scale.

---

## 64. Claim propagation graph

Information flow should be graph traversable.

```text
Evidence
  ↓
Claim
  ↓
Research Agent
  ↓
Subagent Response
  ↓
Orchestrator
  ↓
Email
  ↓
Human
```

This should be queryable independently of the raw message thread.

---

## 65. Plane 7 — Intelligence & Measurement

Communication intelligence is derived here.

Required Day-1 intelligence families:

```text
communication semantics
conversation state
information extraction
claim extraction
information transformation
delegation analysis
knowledge state
information fidelity
response analysis
commitment tracking
communication contribution
quality
risk findings
```

---

## 66. Semantic extraction

Derived semantic structures can include:

```text
topics
referenced entities
communication acts
requests
commitments
offers
decisions
dates
amounts
products
campaigns
resources
claims
uncertainties
citations
```

These remain derived/model-supported facts.

---

## 67. Information fidelity

Agent coordination analysis must support:

```text
constraint retention
claim retention
semantic drift
omission rate
unsupported addition rate
contradiction rate
citation retention
evidence retention
instruction retention
```

Example:

```text
Human request:
FedRAMP + under $100K

Subagent context:
enterprise vendor
```

Communication360 derives:

```text
FedRAMP constraint = omitted
Price constraint = omitted
```

with supporting evidence.

---

## 68. Consumption states

Human-oriented states:

```text
sent
delivered
opened
read
clicked
responded
```

Agent-oriented states can include:

```text
delivered
ingested
parsed
included_in_context
used
responded
discarded
unknown
```

Provider capability determines which can be known.

---

## 69. Communication metric families

### Volume

```text
communication_count
message_count
transfer_count
conversation_count
participant_count
active_conversation_count
```

### Direction

```text
human_to_human
human_to_agent
agent_to_human
agent_to_agent
organization_to_human
agent_to_organization
system_to_agent
```

### Delivery

```text
sent
delivered
opened
read
processed
acknowledged
responded
failed
```

---

## 70. Coordination metrics

```text
delegation_count
delegation_depth
fanout
branch_factor
handoff_count
round_trip_count
response_latency
coordination_latency
failed_handoff_rate
orchestrator_bottleneck_rate
```

---

## 71. Information quality metrics

```text
claim_retention_rate
constraint_retention_rate
semantic_drift
contradiction_rate
unsupported_addition_rate
evidence_retention_rate
citation_retention_rate
```

---

## 72. Operational communication metrics

```text
request_completion_rate
response_completion_rate
commitment_fulfillment_rate
unanswered_request_rate
escalation_rate
conversation_resolution_rate
```

---

## 73. Communication economic metrics

Through the universal metric contract:

```text
input_tokens
output_tokens
compute_cost
provider_cost
communication_cost

cost_per_message
cost_per_conversation
cost_per_resolved_request
cost_per_finding
cost_per_outcome
```

Economic360 owns broader valuation.

Communication360 provides the communication measurements.

---

## 74. Metrics between metrics

Required derived ratios include:

```text
messages / conversation
messages / finding
messages / outcome

delegations / resolved task
handoffs / resolution

communication cost / task
communication cost / outcome

context loss / delegation depth
semantic drift / handoff count

claims retained / claims received
evidence retained / evidence received
```

---

## 75. Communication contribution

Communication contribution must use Aether's epistemic distinctions.

Potential claim strengths:

```text
associated_with
preceded
correlated_with
contributed_to
attributed_to
causally_supported
```

A delivered email followed by a purchase is not automatically causal.

---

## 76. Communication Findings

Examples:

### Agent

> Agent B consistently loses pricing constraints during delegated research.

### Campaign

> Agent-mediated recipients have a different conversion pattern than direct human recipients.

### Customer

> Renewal objections have appeared in four separate conversations without resolution.

### Security

> Agent transmitted restricted information outside its delegation authority.

### Operations

> Conversations requiring more than three agent handoffs exhibit materially higher resolution latency.

These use the canonical Finding contract.

---

## 77. Plane 8 — Experience, Decision & Operations

Communication360 becomes a first-class projection exposed across:

```text
Aether customer UI
Exploration Fabric
Profile360
Agent360
Relationship360
Campaign360
Episode360
Execution360
Outcome360
Investigations
Noesis
Kyber
Exports
```

---

## 78. Communication360 main surface

Day-1 navigation:

```text
Overview
Conversations
Messages
Information
Participants
Agents
Campaigns
Episodes
Topics / Matters
Requests & Commitments
Outcomes
Findings
Evidence
Quality
Timeline
```

---

## 79. Communication360 Overview

Required cards:

```text
Total communications
Active conversations
Human ↔ Agent
Agent ↔ Agent
Campaign communications
Agent-mediated communications
Open requests
Open commitments
Resolved conversations
Communication-linked outcomes
Degraded sources
```

Required charts:

- channel distribution;
- communication direction;
- conversation state;
- provider freshness;
- communication outcome;
- agent communication volume;
- information-quality trend.

---

## 80. Conversation detail

Must include:

```text
participants
actor/principal relationships
delegations
timeline
messages
information transfers
requests
responses
commitments
topics
attachments
links
campaign context
episode context
outcomes
findings
evidence
quality
```

---

## 81. Message detail

Must expose:

```text
raw/derived availability
provider
channel
source identity
resolved identity

author
actor
sender
principal
delegator
beneficiary

subject/body when authorized
segments
acts
claims
attachments
links

reply lineage
thread
conversation
episode
campaign
execution

evidence
quality
```

---

## 82. Information detail

This should be a distinct Day-1 object page or inspector.

Shows:

```text
canonical information
claims
origin evidence
communications containing it
transformations
recipients
knowledge states
contradictions
decisions using it
actions following it
outcomes linked to it
```

This is what elevates Communication360 beyond transcript analytics.

---

## 83. Information Flow graph lens

Required Day-1 graph support:

```text
Evidence
 ↓
Information
 ↓
Agent
 ├── Human
 ├── Agent
 └── Organization
      ↓
Decision
      ↓
Outcome
```

User can select a claim and see:

- origin;
- path;
- transformations;
- dropped information;
- recipients;
- action lineage.

---

## 84. Profile360 integration

Add Communications projection:

```text
Profile360
├── Overview
├── Identity
├── Relationships
├── Activity
├── Journeys
├── Episodes
├── Communications
├── Campaigns
├── Outcomes
├── Findings
├── Evidence
└── Temporal
```

Profile communications must distinguish:

```text
direct
agent-mediated
delegated
received_by_agent
agent_action_for_profile
```

---

## 85. Agent360 integration

Required Agent360 sections:

```text
Identity
Principal
Authority
Executions
Delegations
Communications
Context
Memory
Relationships
Episodes
Tools
Findings
Decisions
Outcomes
Evidence
```

Communication panel:

```text
sent
received
delegations
handoffs
external contacts
context retention
semantic drift
failed responses
authority violations
```

---

## 86. Relationship360 integration

Communication-derived relationship intelligence:

```text
first communication
last communication
communication frequency
channels
directionality
response latency
conversation count
topics
requests
commitments
episodes
campaign involvement
agent mediation
communication quality
```

Agent-to-agent edges additionally show:

```text
delegation count
completion rate
context loss
handoff failures
dependency
```

---

## 87. Campaign360 integration

Campaign360 owns campaign context.

Communication360 owns the communication itself.

Campaign360 receives:

```text
Communication360 WHERE campaign_ref = X
```

Campaign Communication tab must expose:

```text
artifacts
variants
batches
deliveries
recipient type
human vs agent recipient
generation source
AI involvement
message semantics
links
responses
communication outcomes
```

---

## 88. Traditional campaign flow

```text
Organization
 ↓
Campaign
 ↓
Communication Artifact
 ↓
Batch
 ↓
Delivery
 ↓
Human
 ↓
Open
 ↓
Click
 ↓
Application
 ↓
Promotion
 ↓
Journey
 ↓
Conversion
 ↓
Outcome
```

Campaign360 handles campaign analysis.

Communication360 explains what was communicated and how it moved.

---

## 89. Agent-mediated campaign flow

```text
Campaign
 ↓
Communication
 ↓
Consumer Agent
 ↓
Research Subagent
 ↓
Application
 ↓
Commerce Agent
 ↓
Purchase
 ↓
Human Beneficiary
```

Required distinctions:

```text
recipient
consumer
decision maker
actor
purchaser
principal
beneficiary
```

Aether must not assume these are one entity.

---

## 90. Episode360 integration

Communication events appear inside bounded episodes.

Example:

```text
Human request
→ Agent delegation
→ Agent research
→ External outreach
→ Vendor response
→ Recommendation
→ Human decision
```

Agent termination does not end the Episode.

---

## 91. Execution360 integration

Execution360:

> What did the runtime do?

Communication360:

> What information moved?

Execution view should expose:

```text
Execution
Communications
Information
Evidence
Graph
Timeline
Costs
Outcomes
```

A tool result can be both:

- an execution observation;
- an InformationTransfer;

without duplicate evidence.

---

## 92. Outcome360 integration

Communication360 should link to Outcome360 through canonical outcome relationships.

Examples:

```text
conversation_resolved
meeting_booked
support_issue_resolved
agreement_reached
purchase
conversion
fraud_prevented
decision_completed
task_completed
```

Communication360 should not redefine Outcome.

---

## 93. Population360 integration

Communication dimensions can participate in populations:

```text
people receiving agent-generated campaigns
customers with unresolved commitments
agents exceeding handoff threshold
organizations contacted by autonomous agents
users whose agents consumed promotions
```

Population360 owns population definition/membership.

---

## 94. Geographic and Temporal360 integration

Communication can contribute:

```text
sender geography
recipient geography
communication timezone
provider timestamp
journey geography
effective authority jurisdiction
```

Communication360 consumes canonical Geographic/Temporal facts.

It does not create separate location/time systems.

---

## 95. Fraud/Risk lens integration

Communication360 supplies evidence for:

```text
impersonation
social engineering
fraudulent instruction
anomalous communication graph
secret propagation
unauthorized recipient
suspicious agent delegation
```

Fraud/Risk lenses interpret those signals.

No duplicated fraud engine.

---

## 96. Exploration Fabric integration

Communication360 registers dimensions, metrics, objects, and traversal rules in the Unified Exploration Fabric.

Users must be able to ask:

```text
Show communications involving Profile X.

Show messages generated by agents acting for Organization Y.

Show agent communication preceding Outcome Z.

Show every recipient of Claim Q.

Show communications where budget constraints disappeared.

Show unresolved commitments for this customer population.

Show agent-generated campaign interactions.

Show Communication360 as of timestamp T.
```

---

## 97. ExplorationContext

Navigation preserves:

```text
tenant
time range
timezone
filters
population
campaign
episode
investigation
quality
model version
data watermark
```

User can traverse:

```text
Profile
→ Conversation
→ Message
→ Information
→ Claim
→ Evidence
→ Episode
→ Outcome
```

without resetting context.

---

## 98. Noesis integration

Noesis should query Communication360 through canonical graph/exploration services.

Supported questions include:

> Why did this agent send this message?

> Who authorized the agent?

> Where did this claim originate?

> What did the orchestrator know before this recommendation?

> What customer commitments remain open?

> Which campaign interactions were agent-mediated?

Noesis must not bypass Communication360 and read provider tables directly.

---

## 99. Investigation integration

Investigations may save:

```text
communications
conversations
claims
information flows
delegations
authority findings
attachments
agent executions
knowledge states
```

Evidence chain remains canonical.

---

## 100. Provider-specific flow — Klaviyo/Mailchimp

```text
Provider
 ↓
Webhook / Sync
 ↓
Adapter
 ↓
Observation
 ↓
Bronze
 ↓
Silver communication normalization
 ↓
Recipient resolution
 ↓
Campaign resolution
 ↓
Communication Artifact / Batch / Delivery
 ↓
Graph
 ↓
Communication360
 ↓
Campaign360 / Profile360 / Outcome
```

---

## 101. Gmail flow

```text
Gmail
 ↓
Connector / MCP
 ↓
Provider Adapter
 ↓
Observation
 ↓
Bronze
 ↓
Normalized Message
 ↓
Mailbox identity resolution
 ↓
Sender/recipient resolution
 ↓
Thread resolution
 ↓
Conversation resolution
 ↓
Information extraction
 ↓
Graph
 ↓
Communication360
```

---

## 102. Human → orchestrator → agents → Gmail flow

```text
Human
 ↓
Task
 ↓
Orchestrator
 ↓
Delegation
 ├── Research Agent A
 ├── Research Agent B
 └── Research Agent C
 ↓
Information / Evidence
 ↓
Orchestrator synthesis
 ↓
Delegated Gmail communication
 ↓
External business
 ↓
Reply
 ↓
Orchestrator interpretation
 ↓
Human
```

Every edge remains attributable.

---

## 103. Internal agent communication flow

```text
Orchestrator
 ↓
TaskRequest
 ↓
Subagent
 ↓
Tool execution
 ↓
Evidence
 ↓
Information
 ↓
TaskResponse
 ↓
Orchestrator
```

Communication360 records:

- request;
- context transferred;
- information acquired;
- response;
- retained information;
- omitted information.

Execution360 records runtime operations.

---

## 104. Shared-state flow

```text
Agent A
 ↓ write
Shared State
 ↓ read
Agent B
```

Canonical:

```text
InformationTransfer.type = shared_state
source_actor = Agent A
destination_actor = Agent B
```

No fake chat message is invented.

---

## 105. Human approval flow

```text
Agent generates
 ↓
Human edits
 ↓
Manager approves
 ↓
Agent sends
```

Communication lineage preserves each action.

---

## 106. Message mutation flow

```text
Message v1
 ↓ edited_by
Message v2
 ↓ corrected_by
Message v3
```

Historical replay must show v1 when querying its original valid interval.

---

## 107. Quote and forwarding resolution

Example:

```text
Alice writes X
Bob replies quoting X
Carol forwards both
```

Aether must understand:

```text
origin_of(X) = Alice message
```

rather than generating three independent information origins.

---

## 108. Attachment flow

```text
Communication
 ↓
Attachment Artifact
 ↓
Extracted Information
 ↓
Claims
 ↓
Decision / Outcome
```

A message saying:

> Review attached contract.

cannot be semantically understood without the attachment relationship.

---

## 109. Link resolution

Required:

```text
Provider Tracking URL
 ↓
Redirect chain
 ↓
Canonical URL
 ↓
Application Resource
 ↓
Promotion/Product
```

Preserve:

```text
UTM
campaign parameters
affiliate IDs
redirect IDs
signed params
canonical destination
```

This is critical for campaign-to-journey continuity.

---

## 110. Search architecture

Communication search must combine:

```text
structured search
semantic retrieval
graph traversal
temporal filtering
evidence filtering
```

Supported filters:

```text
sender
recipient
principal
agent
channel
provider
campaign
conversation
matter
episode
topic
claim
act
authority
quality
time
outcome
```

---

## 111. Search policy

Raw body search must respect:

- tenant policy;
- field authorization;
- content classification;
- retention;
- redaction;
- residency.

Derived semantic search may have different authorization.

Those permissions must be explicit.

---

## 112. API architecture

Domain-address APIs:

```text
GET /v1/communications/{id}
GET /v1/conversations/{id}
GET /v1/information/{id}
GET /v1/claims/{id}
GET /v1/delegations/{id}
```

Creation/ingestion paths use canonical ingest/SDK/harness contracts.

Cross-domain discovery remains:

```text
/v1/explore/*
```

Graph remains:

```text
/v1/graph/query
```

Long jobs:

```text
/v1/jobs
```

Exports:

```text
/v1/exports
```

No duplicate job/export/search infrastructure.

---

## 113. Query contracts

Communication queries should return:

```text
data
context
quality
availability
lineage
pagination
watermark
policy
```

Every query needs explicit semantics for:

```text
empty
partial
stale
suppressed
degraded
```

---

## 114. SDK requirements

Thin SDK methods should conceptually support:

```text
observeCommunication()
observeInformationTransfer()
observeDelegation()
observeContextTransfer()
observeArtifactTransfer()
observeSharedState()
observeHumanApproval()
observeAgentLifecycle()
```

The SDK emits evidence.

The backend owns canonical resolution and intelligence.

---

## 115. SDK non-responsibilities

SDK must not:

- resolve canonical people;
- determine Campaign360 truth;
- compute semantic findings;
- produce graph IDs independently;
- determine attribution;
- decide communication authority;
- build permanent conversation groupings.

This keeps the SDK thin.

---

## 116. Security integration

Communication360 must feed the existing security architecture.

Required communication security signals include:

```text
prompt injection
social engineering
credential request
malicious attachment
secret leakage
PII leakage
unauthorized recipient
policy override attempt
agent impersonation
scope-exceeded external contact
```

Communication360 detects/evidences.

Security systems evaluate response policy.

---

## 117. Communication authenticity

Preserve where supported:

```text
authentication method
provider attestation
content hash
transport identity
message signature
source checksum
```

Distinguish:

```text
claimed sender
presented sender
authenticated sender
executing actor
principal
```

---

## 118. Content classification

Day-1 classifications must at minimum support:

```text
public
internal
confidential
restricted
PII
financial
credential
secret
legal
customer_data
regulated
```

Classification can be:

```text
provider_observed
policy_assigned
model_inferred
user_corrected
```

---

## 119. Access-control granularity

Permissions must independently control:

```text
communication existence
metadata
participants
subject
semantic summary
claims
raw body
attachments
system prompt
agent context
agent memory
internal agent communication
security findings
```

Profile360 permission does not imply raw inbox permission.

---

## 120. Tenant isolation

All Communication360 objects are tenant scoped.

Cross-tenant identity correlation is prohibited unless another explicitly governed architecture permits it.

No communication-derived cross-tenant identity marketplace.

---

## 121. Consent and communication preference

Where applicable preserve:

```text
consent basis
subscription state
purpose
communication channel preference
jurisdiction
valid_from
valid_to
```

Historical queries answer:

> Was this communication permitted when it was sent?

not simply:

> Is this person subscribed now?

---

## 122. Retention

Retention is independent across:

```text
raw content
attachments
metadata
semantic extraction
claims
graph relationships
hashes
derived findings
```

Example policy:

```text
Raw body        90 days
Attachment      90 days
Metadata        longer
Evidence hash   longer
Graph lineage   policy governed
```

Exact policy is deployment controlled.

---

## 123. Deletion semantics

When payload disappears:

```text
payload_state = expired
```

The system must not pretend:

```text
communication never existed
```

Deletion reason is retained where policy permits.

---

## 124. Communication quality envelope

Required quality dimensions:

```text
source_quality
content_availability
participant_resolution_quality
conversation_resolution_quality
principal_resolution_quality
delegation_quality
semantic_quality
knowledge_state_quality
outcome_linkage_quality
completeness
freshness
```

No single opaque confidence score.

---

## 125. Typed degradation

Day-1 UX and API states:

```text
ready
empty
partial
stale
insufficient_data
degraded
suppressed
not_applicable
pending
error
```

Field-level states can include:

```text
available
unknown
missing
unavailable
redacted
expired
```

---

## 126. Example degradation

```text
Agent internal communication:
PARTIAL

Available:
- Delegation events
- Agent execution
- Final responses

Unavailable:
- Full subagent transcripts

Provider limitation:
Internal message payload is not exposed.
```

This is superior to displaying `0 internal messages`.

---

## 127. Kyber operations

Kyber does not become an inbox.

It becomes the operational control surface.

Required Day-1 Communication360 Kyber areas:

```text
Connector Health
Pipeline Health
Contract Health
Resolution Health
Agent Communication Health
Semantic Processing Health
Security / Policy Findings
Replay / Repair
Capacity
Release Proof
```

---

## 128. Kyber Connector Health

Display:

```text
provider
account
connection state
last success
last event
sync lag
backlog
rate limit
error rate
permission health
capability changes
```

---

## 129. Kyber contract health

Monitor:

```text
schema incompatibility
unknown event type
missing required field
enum drift
provider schema drift
contract version mismatch
```

---

## 130. Kyber resolution health

Monitor:

```text
unresolved participant rate
ambiguous participant rate
orphan replies
conversation resolution failures
unknown principal rate
unknown delegation rate
```

---

## 131. Kyber agent communication health

Monitor:

```text
agent communication volume
delegation fanout
failed handoffs
context loss
unreturned delegations
terminated agents with unresolved tasks
external contacts
authority violations
```

---

## 132. Kyber semantic pipeline health

Monitor:

```text
semantic queue depth
extraction latency
model failures
model version
claim extraction rate
information-transformation failures
reprocessing backlog
```

---

## 133. Kyber security findings

Surface:

```text
restricted information propagation
agent impersonation
unauthorized recipient
authority scope exceeded
cross-tenant policy violation
prompt injection signal
sensitive attachment exposure
```

---

## 134. Reconciliation invariants

Day-1 must implement automated reconciliation.

### Provider reconciliation

```text
observed provider sends
≈ canonical accepted sends
+ quarantined/rejected observations
```

### Campaign reconciliation

```text
Campaign360 communication count
=
eligible Communication360 campaign deliveries
```

under the same watermarks/capability scope.

### Conversation reconciliation

Every response is:

```text
linked to parent
```

or:

```text
parent_state = unresolved
```

### Agent delegation reconciliation

```text
created delegations
=
active
+ completed
+ failed
+ cancelled
+ revoked
+ unresolved
```

---

## 135. Content-state reconciliation

```text
all canonical communication payloads
=
available
+ redacted
+ expired
+ unavailable
+ missing
+ corrupt
```

No silent disappearance.

---

## 136. Communication counts

Never aggregate all provider events as messages.

Metrics distinguish:

```text
source observations
canonical transfers
canonical messages
deliveries
artifacts
conversations
```

This prevents duplicated analytics.

---

## 137. Reliability and SLOs

Required service-level metric families:

```text
ingestion availability
provider freshness
ingestion latency
normalization latency
resolution latency
semantic processing latency
graph mutation lag
query latency
projection freshness
replay success
dead-letter volume
```

Exact numerical targets should align with the platform-wide SLO blueprint rather than Communication360 inventing its own system.

---

## 138. Operational failure classes

Required error classification:

```text
provider_auth_failure
provider_rate_limit
provider_schema_change
provider_permission_loss

invalid_contract
normalization_failure
dedupe_failure

identity_resolution_failure
conversation_resolution_failure

semantic_processing_failure
graph_mutation_failure

policy_denied
content_unavailable
retention_expired

query_degraded
projection_stale
```

---

## 139. Dead-letter queues

Every pipeline stage requiring retry must have:

- reason;
- original evidence;
- retry count;
- last error;
- source correlation;
- remediation action;
- replay path.

Kyber must expose them.

---

## 140. Day-1 observability

Every Communication360 operation must emit:

```text
trace_id
observation_id
tenant_id
provider
communication_id?
conversation_id?
agent_execution_id?
job_id?
```

This allows cross-plane debugging.

---

## 141. Performance strategy

Communication volume can exceed other graph data by orders of magnitude.

Required design:

```text
Raw payload storage
        ↓
Canonical communication facts
        ↓
Selective graph materialization
        ↓
Aggregated projections
```

Do not graph-expand every text fragment by default.

---

## 142. Indexing

Indexes should support:

```text
tenant + time
provider + provider_message_id
participant
conversation
campaign
agent execution
delegation
information
claim
topic
matter
outcome
```

Semantic vector/index infrastructure remains policy controlled.

---

## 143. Hot / warm / cold

Recommended logical lifecycle:

```text
HOT
recent searchable communication

WARM
historical canonical communication

COLD
archived payload/evidence

GRAPH
durable relationships

SEMANTIC INDEX
retrieval representation

PROJECTIONS
optimized 360 views
```

---

## 144. Communication360 frontend states

Every screen requires:

```text
loading
ready
empty
partial
stale
suppressed
degraded
error
```

Empty state must explain whether:

- there are no communications;
- connector is absent;
- access is unavailable;
- data is out of scope.

---

## 145. Evidence Inspector integration

Every derived field can be inspected.

Example:

```text
Intent:
INFERRED
confidence 0.86
model: model-x

Recipient:
RESOLVED
confidence 0.99
evidence:
Gmail address + CRM identifier

Delivery:
OBSERVED
provider:
Gmail

Principal:
VERIFIED
delegation:
D-819

Outcome contribution:
ATTRIBUTED
model:
A-17
```

No frontend-only inference.

---

## 146. Communication lens

The Exploration Fabric needs a registered Communication Lens.

It allows users to project graph truth as information flow.

```text
Entity
 ↓
Communication
 ↓
Information
 ↓
Recipient
 ↓
Decision
 ↓
Outcome
```

---

## 147. Agent lens integration

When Agent Lens + Communication Lens overlap, the graph should prioritize:

```text
principal
delegation
agent instance
subagents
information transfers
context
responses
decisions
outcomes
```

This is a composable lens, not a bespoke Agent360 graph.

---

## 148. Campaign lens integration

Campaign + Communication lens:

```text
Campaign
 ↓
Artifact / Variant
 ↓
Recipient
 ↓
Human or Agent
 ↓
Interaction
 ↓
Journey
 ↓
Outcome
```

---

## 149. Temporal lens integration

Communication + Temporal:

```text
What communication existed at T?
What content version existed?
Who could access it?
What authority was active?
What information had arrived?
What had not yet arrived?
```

---

## 150. Security lens integration

Communication + Security:

```text
restricted information
 ↓
Agent
 ↓
unauthorized recipient
```

or:

```text
malicious external message
 ↓
Agent context
 ↓
policy-violating instruction
```

---

## 151. Day-1 provider minimum

Day-1 does not require every supported provider family to expose all capabilities.

It requires at least:

1. one marketing provider path;
2. one mailbox provider path;
3. Aether SDK/harness agent path;
4. provider-neutral contracts;
5. capability degradation;
6. replay;
7. projection support.

Additional providers can conform to the same adapter contract.

---

## 152. Day-1 campaign scenario

Golden production flow:

```text
Klaviyo Campaign
 ↓
Email Artifact
 ↓
Delivery
 ↓
Human
 ↓
Open
 ↓
Click
 ↓
Application Session
 ↓
Promotion
 ↓
Conversion
 ↓
Outcome
```

Validate:

- campaign IDs;
- profile IDs;
- link IDs;
- journey;
- attribution;
- Communication360;
- Campaign360;
- Profile360;
- evidence;
- reconciliation.

---

## 153. Day-1 agent campaign scenario

```text
Agent creates campaign content
 ↓
Human approval
 ↓
Klaviyo
 ↓
Customer
 ↓
Click
 ↓
Application
 ↓
Outcome
```

Validate:

- generator;
- editor;
- approver;
- sender;
- principal;
- campaign;
- outcome.

---

## 154. Day-1 agent recipient scenario

```text
Promotion
 ↓
Customer Agent
 ↓
Research Agent
 ↓
Application
 ↓
Purchase Agent
 ↓
Purchase
 ↓
Human Beneficiary
```

Validate actor/principal/beneficiary separation.

---

## 155. Day-1 non-campaign agent scenario

```text
Human
 ↓
GPT/Claude/Hermes Orchestrator
 ↓
Subagents
 ↓
Research
 ↓
Gmail/MCP
 ↓
Business
 ↓
Response
 ↓
Orchestrator
 ↓
Human
```

Validate full communication lineage.

---

## 156. Day-1 shared-state scenario

```text
Agent A
 ↓
Shared store
 ↓
Agent B
```

Validate InformationTransfer without Message.

---

## 157. Day-1 context-loss scenario

Input:

```text
Find vendors:
- FedRAMP
- under $100K
```

Subagent receives:

```text
Find enterprise vendors.
```

Expected:

```text
constraint retention < 100%
FedRAMP omitted
budget omitted
```

---

## 158. Day-1 agent-death scenario

```text
Agent B communicates findings.
Agent B terminates.
```

Expected:

- AgentInstance state = terminated;
- communication remains;
- information remains;
- Episode remains;
- lineage remains;
- raw payload obeys retention policy.

---

## 159. Day-1 authority scenario

Agent authorized:

```text
research_only
```

attempts:

```text
send external vendor email
```

Expected:

```text
authority_state = scope_exceeded
security finding created
communication attempt preserved as evidence
policy behavior follows configured enforcement
```

---

## 160. Day-1 deletion scenario

Provider deletes message.

Expected:

```text
source_state = provider_deleted
payload availability = unavailable/deleted
historical relationship preserved where policy allows
```

---

## 161. Day-1 provider-degradation scenario

Provider exposes:

```text
agent created
delegation created
agent completed
```

but not internal messages.

UI:

```text
Communication completeness:
PARTIAL

Internal messages:
UNAVAILABLE
```

No fabricated zero.

---

## 162. Day-1 cross-channel scenario

```text
Campaign email
 ↓
Website
 ↓
Chat
 ↓
Agent
 ↓
Human support email
 ↓
Resolution
```

Expected:

- multiple provider threads;
- one resolved Matter;
- Episode reconstruction;
- Outcome linkage.

---

## 163. Testing strategy

Required categories:

```text
contract tests
adapter tests
normalization tests
idempotency tests
dedupe tests
identity resolution tests
delegation tests
conversation tests
temporal tests
information extraction tests
claim tests
graph tests
metric tests
UI tests
security tests
tenant-isolation tests
replay tests
reconciliation tests
load tests
chaos/provider failure tests
```

---

## 164. Golden fixtures

Fixtures must cover:

```text
single email
bulk campaign
email reply
email forward
quoted message
edited chat message
agent delegation
subagent response
shared state
context transfer
human approval
agent termination
retention deletion
provider partial data
unauthorized communication
cross-channel episode
```

---

## 165. Contract tests

Every object validates:

- required fields;
- enum validity;
- temporal fields;
- tenant scope;
- evidence references;
- compatibility;
- version migration.

---

## 166. Identity tests

Must verify:

```text
same human aliases merge when supported
different humans do not merge
agent aliases resolve correctly
unresolved participants remain unresolved
cross-tenant identities remain isolated
```

---

## 167. Temporal tests

Must verify:

```text
message edit history
delegation validity
principal changes
knowledge state timing
causal ordering
parallel subagents
historical replay
```

---

## 168. Semantic tests

Must verify:

```text
multiple acts per message
claims preserved
claims transformed
constraints dropped
unsupported additions
contradictions
quoted content deduplication
```

---

## 169. Graph tests

Verify:

```text
all graph edges reference canonical objects
no duplicate relationships after replay
temporal validity
evidence linkage
progressive projection
```

---

## 170. Security tests

Required:

```text
tenant escape attempts
unauthorized raw body access
attachment access
agent scope violation
provider spoofing
sender impersonation
prompt injection signal propagation
redaction
policy purge
```

---

## 171. Capacity tests

Communication workloads should test:

```text
bulk campaign fanout
high agent-message volume
large thread histories
large attachment counts
concurrent subagents
semantic extraction queues
graph mutation throughput
Communication360 query latency
```

---

## 172. Release train

Implementation should be organized into four coordinated PR trains.

---

## 173. PR1 — Canonical contracts and governance

Deliver:

```text
InformationTransfer
CommunicationArtifact
CommunicationBatch
CommunicationDelivery
CommunicationMessage
CommunicationPayload
CommunicationSegment

Information
InformationTransformation

Conversation
ProviderThread
Matter

CommunicationAct
Request
Commitment
ResponseExpectation

Delegation
Interpretation
KnowledgeState
ContextInclusion

Capability
Quality
```

Also:

- registry updates;
- relationship definitions;
- metric definitions;
- migration scaffolding;
- golden fixtures;
- contract tests.

### PR1 exit gate

No provider code relies on private one-off communication schemas.

---

## 174. PR2 — Capture, evidence, identity, temporal, graph

Deliver:

```text
provider adapter interface
initial marketing connector
initial mailbox connector
Aether harness integration

Bronze persistence
Silver normalization
dedupe
participant resolution
principal resolution
delegation resolution
conversation resolution
matter resolution

temporal ordering
message versioning

graph mutation
replay
repair
```

### PR2 exit gate

Golden source events reproduce the same canonical graph after replay.

---

## 175. PR3 — Intelligence, metrics, exploration, surfaces

Deliver:

```text
information extraction
claim extraction
communication acts
information transformations
knowledge states
context-retention metrics

communication metrics
metric algebra
findings

Communication360 API
Communication360 UI
Communication Lens

Profile360 integration
Agent360 integration
Relationship360 integration
Campaign360 integration
Episode360 integration
Execution360 integration
Outcome360 links

Noesis query path
Investigation integration
```

### PR3 exit gate

A user can move:

```text
provider evidence
→ communication
→ information
→ claim
→ graph
→ episode
→ outcome
```

and back.

---

## 176. PR4 — Production hardening and Day-1 release proof

Deliver:

```text
field authorization
retention
deletion
tenant isolation
policy enforcement
security findings
Kyber operations

SLO metrics
alerts
runbooks
dead-letter repair
replay tooling
capacity validation
provider failure tests
staging burn-in
release dashboards
```

### PR4 exit gate

Production release proof passes.

---

## 177. Migration and coexistence

Existing campaign/email fields may already exist.

Do not rewrite working domains destructively.

Migration process:

1. inventory existing communication-like fields;
2. identify canonical owner;
3. map them to Communication360 objects;
4. preserve compatibility adapters;
5. dual-read during migration if necessary;
6. verify reconciliation;
7. switch projections;
8. deprecate duplicate schemas.

---

## 178. Legacy fields likely requiring normalization

Examples:

```text
campaign email send
touchpoint message
email open
email click
agent transcript
agent prompt
provider thread
support response
```

The migration should determine whether each is:

```text
Observation
Communication
Delivery
Touchpoint
InformationTransfer
Execution
Episode event
```

rather than treating all as Message.

---

## 179. Day-1 frontend migration

Existing campaign screens should not be replaced.

Instead:

```text
Campaign360
   ↓
Communication projection
```

feeds existing and new communication components.

Profile360 and Agent360 gain Communication tabs/projections.

---

## 180. Day-1 API compatibility

Legacy provider-specific endpoints may remain as adapters where necessary.

Canonical output should converge on Communication360 contracts.

Deprecation requires:

- usage visibility;
- replacement endpoint;
- compatibility window;
- migration documentation.

---

## 181. Ownership matrix

### Contract Spine

Owns schemas and registries.

### Capture/Connector system

Owns provider acquisition.

### Evidence/Data plane

Owns raw and normalized storage.

### Identity subsystem

Owns canonical identity.

### Temporal subsystem

Owns time validity.

### Graph subsystem

Owns relationships and traversal.

### Communication360

Owns communication semantics and information-flow projection.

### Campaign360

Owns campaign projection.

### Agent360

Owns agent projection.

### Kyber

Owns operational visibility/control.

This prevents architecture overlap.

---

## 182. Day-1 documentation requirements

Ship:

```text
Communication360 doctrine
object reference
provider adapter contract
agent harness guide
SDK instrumentation guide
graph relationships
semantic contract
capability/degradation semantics
API documentation
UI behavior
security model
retention behavior
Kyber runbook
replay/runbook
troubleshooting guide
```

---

## 183. Day-1 observability documentation

Operators need explicit diagnosis for:

```text
Why is a conversation partial?
Why did participant resolution fail?
Why does Campaign360 disagree with provider count?
Why are agent messages unavailable?
Why is content redacted?
Why did a semantic extraction fail?
Why does a claim have low confidence?
```

---

## 184. Day-1 release evidence

Release artifact must contain:

```text
contract test results
integration test results
golden scenario results
security test results
tenant isolation result
load-test result
replay result
reconciliation result
Kyber health result
migration verification
known provider limitations
```

---

## 185. Go-live gates

No production launch until all are true.

### Contract

- canonical schemas frozen for release;
- schema compatibility tests pass;
- no duplicate registries.

### Data

- Bronze/Silver/Gold path verified;
- dedupe passes;
- replay passes.

### Identity

- human resolution validated;
- agent resolution validated;
- cross-tenant isolation validated.

### Agent authority

- delegation lineage works;
- unknown authority is typed;
- scope violation test passes.

### Temporal

- message mutation replay works;
- delegation validity works;
- causal ordering works.

---

## 186. Go-live gates continued

### Graph

- relationship mutations are idempotent;
- claim lineage traverses;
- agent death does not remove lineage.

### Intelligence

- information/claim extraction works;
- context-loss scenario works;
- findings expose evidence.

### Metrics

- universal measurement contract used;
- campaign reconciliation passes;
- agent communication metrics reconcile.

### Experience

- Communication360 views work;
- 360 projections work;
- Evidence Inspector works;
- partial/suppressed states render correctly.

---

## 187. Go-live gates continued

### Security

- field authorization works;
- raw-body access protected;
- tenant isolation passes;
- authority violation creates appropriate finding.

### Operations

- Kyber health views available;
- alerts configured;
- dead-letter repair tested;
- replay runbook tested.

### Documentation

- developer docs shipped;
- operator docs shipped;
- provider limitations documented.

---

## 188. Day-1 non-deferrable requirements

The following cannot be postponed without undermining the architecture:

1. Information separate from Message.
2. Claim/evidence lineage.
3. InformationTransfer abstraction.
4. Participant-role model.
5. Principal/delegation/authority.
6. Agent lifecycle persistence.
7. Context transfer.
8. Shared-state transfer.
9. Conversation resolution.
10. Provider capability truth.
11. Typed degradation.
12. Bitemporal history.
13. Message version history.
14. Dedupe/idempotency.
15. Policy classification.
16. Field authorization.
17. Tenant isolation.
18. Retention/deletion semantics.
19. Communication metrics.
20. Information-fidelity metrics.
21. Campaign360 integration.
22. Profile360 integration.
23. Agent360 integration.
24. Relationship360 integration.
25. Episode360 integration.
26. Execution360 integration.
27. Outcome linking.
28. Exploration Fabric integration.
29. Evidence Inspector.
30. Findings.
31. Kyber operations.
32. Reconciliation.
33. Replay.
34. Golden-scenario tests.
35. Production release proof.

---

## 189. Features that may deepen after Day 1 without changing architecture

Once the above architecture ships correctly, future development can deepen:

```text
voice communications
meeting intelligence
video communications
advanced conversation summarization
advanced negotiation analysis
advanced multimodal context
additional providers
richer agent protocols
cross-language semantic normalization
advanced causal communication analysis
communication forecasting
```

These should extend the same canonical contracts.

---

## 190. Final Day-1 system architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                     EXTERNAL ACTORS                          │
│ Humans • Agents • Organizations • Services • Applications  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ PROVIDERS / RUNTIMES                                        │
│ Gmail • Klaviyo • Mailchimp • MCP • Agent Harness • SDK    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ CONTRACT + GOVERNANCE                                       │
│ Contract Spine • Scope • Consent • Policy • Capabilities   │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ CAPTURE                                                      │
│ Adapters • SDK • Harness • API • Webhook                   │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ EVIDENCE                                                     │
│ Bronze → Silver → Gold • Provenance • Replay               │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ RESOLUTION                                                   │
│ Human • Agent • Org • Principal • Delegation • Recipient   │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ TEMPORAL / CONTEXT                                           │
│ Thread • Conversation • Matter • Episode • Execution       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ GRAPH                                                        │
│ Communication • Information • Claims • Relationships       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ INTELLIGENCE                                                 │
│ Semantics • Knowledge • Fidelity • Metrics • Findings      │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ PRODUCT / OPERATIONS                                         │
│ Communication360                                            │
│ Profile360 • Agent360 • Relationship360 • Campaign360      │
│ Episode360 • Execution360 • Outcome360                     │
│ Exploration • Noesis • Investigations • Exports            │
│ Kyber • Security • Reliability                             │
└──────────────────────────────────────────────────────────────┘
```

---

## 191. Canonical information-flow model

The semantic chain underneath Communication360 is:

```text
OBSERVATION
    ↓
EVIDENCE
    ↓
INFORMATION
    ↓
CLAIM
    ↓
INFORMATION TRANSFER
    ↓
COMMUNICATION
    ↓
RECEPTION
    ↓
INTERPRETATION
    ↓
KNOWLEDGE STATE
    ↓
DECISION
    ↓
ACTION
    ↓
OUTCOME
```

The accountability chain runs beside it:

```text
PRINCIPAL
    ↓
DELEGATION
    ↓
ACTOR
    ↓
EXECUTION
    ↓
COMMUNICATION
    ↓
RECIPIENT
    ↓
BENEFICIARY
```

The contextual chain runs beside both:

```text
CAMPAIGN
MATTER
CONVERSATION
EPISODE
TIME
GEOGRAPHY
POPULATION
POLICY
EVIDENCE
```

Those three chains together define the production architecture of Communication360.

---

## 192. Final release principle

The Day-1 Communication360 implementation is successful when Aether can take an arbitrary meaningful communication—from a Klaviyo campaign email, a Gmail outreach message, a Claude/GPT subagent delegation, an MCP context exchange, a shared-state handoff, or an agent acting on behalf of a human—and reconstruct:

> **what information moved, where it originated, how it changed, who received it, who was acting for whom, whether the action was authorized, what the participants knew at the relevant time, what actions followed, how the communication connected to the graph, and what measurable outcome resulted.**

At that point Communication360 is not an email feature bolted onto Campaign360.

It is a first-class **information-flow intelligence substrate** spanning Aether's graph, agents, campaigns, relationships, episodes, decisions, findings, outcomes, and operational control plane.

That is the Day-1 production definition.
