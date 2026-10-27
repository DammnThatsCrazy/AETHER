---
title: Agentic Observability Audit
slug: audits/agentic-observability-audit
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: 0.1.0
source_files: [services/api/value/x402/, services/api/actions/agent/, services/api/actions/delegation/engine.py, services/api/actions/agentic_observability/, services/api/actions/agent_marketplace/, services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py, services/api/alembic/versions/20261022_execution_approval_decisions.py, services/api/alembic/versions/20261022_risk_poisoning_evidence.py, services/api/alembic/versions/20261023_commerce_intent_authority.py, services/api/alembic/versions/20261023_support_callback_authority.py, services/api/value/commerce/, services/api/value/economic/economic360_contracts.py, services/api/value/economic/operation_linkage.py, services/api/value/economic/journey_operation_evidence.py, services/api/value/economic/economic360_provider.py, services/api/value/economic/ai_aggregation.py, services/api/journeys/communication360/, services/api/journeys/support360/, services/api/intelligence/workflow/workflow360_provider.py, services/api/identity/account360_provider.py, services/api/shared/intelligence_projections/frame_runtime.py, services/api/repositories/repos.py, services/api/intelligence/fraud_networks/risk360_projection.py, services/api/connectors/integrations/providers/payment_rails/models.py, services/api/connectors/integrations/providers/payment_rails/service.py, services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py, services/api/identity/profile/agent.py, services/api/intelligence/risk360/, services/api/ingestion/ingestion/lifecycle_worker.py, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/shared/store.py, services/api/workers/runtime/specs.py, packages/sdk/server/src/agent-telemetry.ts, packages/shared/events.ts, packages/shared/contracts/event-registry.json, packages/shared/contracts/intelligence-projection-registry.json, packages/shared/agentic-observability.ts]
source_hashes:
  "packages/sdk/server/src/agent-telemetry.ts": "sha256:95db783d969918011e29a3aeb96e837a559f547aec4c2efcee1679188b360f0b"
  "packages/shared/agentic-observability.ts": "sha256:b7619ae635280e2673b8632192005e24d7f2fdfbd4bbcb8f773b2efb5be6850e"
  "packages/shared/contracts/event-registry.json": "sha256:3d839b394ff0ee3a40679f92a9c38f2e321ab7785663d1a8ef047279d8b757f2"
  "packages/shared/contracts/intelligence-projection-registry.json": "sha256:2c09ffe2cbd46a3a2f29331b58496bdd63cc1494fad34dafbb86cca25b829fd3"
  "packages/shared/events.ts": "sha256:864fd17d5e7e842b8cc96970b4f79f43879b7564281c3f9b1cdd3c637e92ebdd"
  "services/api/actions/agent/": "sha256:f2357cc861075bb65092d1a4c8bf36a1a2baaae8ab2d9f7b35d6e7303130e91a"
  "services/api/actions/agent_marketplace/": "sha256:e5c25ced055d8f59d2d126a15d0e461e760c5dbaa28f19d4d9ed1567bb072568"
  "services/api/actions/agentic_observability/": "sha256:0153a7ccb49d8950fd38207044f932213db7ce191df455e6951b6483d5bf8e00"
  "services/api/actions/delegation/engine.py": "sha256:5b4face159fb5bd3f9d3e8be5a793d1a8f2f363316cf092b6e5a1593ecc59798"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/alembic/versions/20261022_risk_poisoning_evidence.py": "sha256:6ec173f0cf27ea51b0538bf1276e1afc7058e40c882c07bed61de6f44a84bc72"
  "services/api/alembic/versions/20261023_commerce_intent_authority.py": "sha256:81dbf80e8646034fe5f2b51e616ee71c4c758b6a4380b3ee44ff5ce114156e38"
  "services/api/alembic/versions/20261023_support_callback_authority.py": "sha256:33278fd0ba6103d8a3f37c87db66c8209d953555669d72647047674425a1bede"
  "services/api/connectors/integrations/providers/payment_rails/models.py": "sha256:fa63fb1a785b98a7ec322f0d06b13ed30ed722003daee53177ba13078a4c77ed"
  "services/api/connectors/integrations/providers/payment_rails/service.py": "sha256:8e681a79980dae410a82b15215fbc26fd73f55bdeefb5ded42b57675694ffa80"
  "services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py": "sha256:740b01479ca0ea5104850140eb269cfef35b9c60b4b848d0b0bd0ad7eecb3905"
  "services/api/identity/account360_provider.py": "sha256:a320533cd4d718ef9c616e4ed627b0581271bfc3d66484a2fa4ad92a5e5fe166"
  "services/api/identity/profile/agent.py": "sha256:f7aa0168d674cfe5241d169f6516478ef24c882e848dc097af98706f0aee576c"
  "services/api/ingestion/ingestion/lifecycle_worker.py": "sha256:7b6d7d2323a5646c0f7a7093e7ae256f943c70af07557080ef5949d09d07e5d8"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:1db7a6ff778ed3ca22ebae87717636c37f6b821b1e37ddc4d85161a5bb3bb4bf"
  "services/api/ingestion/silver/projectors/silver_graph_projector.py": "sha256:3c9fde55d39ff7aa80350bc67c165b6420775c4175faaad8c15d750ab2a61c93"
  "services/api/intelligence/fraud_networks/risk360_projection.py": "sha256:4ad7ac91c78b7f66f66e9abd986a723453a721e4868584fa1e349723d6cd306c"
  "services/api/intelligence/risk360/": "sha256:762ef5ac5e30355229599b49959ca43ec25cc408dd2c041e58af69009ea9ff99"
  "services/api/intelligence/workflow/workflow360_provider.py": "sha256:624596e71c20882086990c2f56c3067474927f84de0b343a1c55bc6e7d3103b3"
  "services/api/journeys/communication360/": "sha256:ba659f251b7fee8447346551f72354390c293179924ee24156c487b826c5d1a8"
  "services/api/journeys/support360/": "sha256:1b359b89b1ca74bdc9651d371667e6e888794388a9495506cc55defdcf5ebb4f"
  "services/api/repositories/repos.py": "sha256:fcaaad1267595bd0f2a936e0b39e402b9dacc909da5a4b74066023d99035e5c2"
  "services/api/shared/intelligence_projections/frame_runtime.py": "sha256:e1d39238f595d91a69347c76418cb2e4d79e860c8e254cebb5720343be4928d4"
  "services/api/shared/store.py": "sha256:f35311e40b7ab2c4a8ea90b0e26dd3bd2e4aefc855a0bd7b5efae1a9a6af9f94"
  "services/api/value/commerce/": "sha256:a23de7b3fd18ecf25fa78e7da791916c4b881c009cc03047b7a545d554c80cd7"
  "services/api/value/economic/ai_aggregation.py": "sha256:1c9a65985225dc3c25bb5f628610390cde15271dc320c0af6e0a2bbedd98c82f"
  "services/api/value/economic/economic360_contracts.py": "sha256:8a3053f8e23ed369850714d8e77525135dd8f4b2085ead3c89273f741923f4f5"
  "services/api/value/economic/economic360_provider.py": "sha256:c4876df0c44da2b2322921a43301c8917d40e9dda50d986890b537b3a4e9e844"
  "services/api/value/economic/journey_operation_evidence.py": "sha256:075dd15490f0ead55d8eaaae0c88580d7ea496b1173da190e28c3459ff74cb29"
  "services/api/value/economic/operation_linkage.py": "sha256:0f663fa20e86fdeaf99d9f27afebdb603423887458b5bbdd0c3450baecd5b9d4"
  "services/api/value/x402/": "sha256:a92283788ffc7dab83f99071da7dc9de7cd695eb5a46fb614afa5cbdbdadb708"
  "services/api/workers/runtime/specs.py": "sha256:b86659249b2f805b3ba81631c57e71ca57be089de07278fedccbe25b576df64b"
---

# Agentic Observability Audit

> AETHER may observe economic, protocol, trading, communication, and agentic activity.
> AETHER must not execute, originate, sign, custody, settle, or facilitate those actions
> unless a future explicit product scope, legal review, compliance review, and feature flag
> enable it. For now, all `execution_by_aether` fields must be `false`.

## Current-state addendum (2026-10-15)

PR #771 closes the external-agent execution-lineage and graph-recovery gaps
within its defined scope. The SDK contract, backend validation, Silver
projector, and graph projector now carry source-asserted deployment/run,
task/action, trigger, tool, policy, delegation, and outcome references. Agent
360 presents run evidence with source and coverage labels; it does not claim
hidden reasoning or independently verify source assertions. Kyber recovery
pages tenant deployment/Silver sources or platform catalog observations
separately from outbox status, checks missing work by deterministic outbox ID,
and writes only through the graph mutation gateway. Scan reports explicitly
identify `best_effort_non_snapshot` consistency and do not certify graph state.

The default-off xAI catalog observer adds minimal public listing metadata as a
separate `platform`-scoped source. It does not fetch bot configuration or join
public listing slugs to canonical Agents. Tenant admins can explicitly bind a
deployment source namespace/reference to a same-tenant canonical Agent; the
binding is separate from automatic identity merge and fails closed when absent
or ambiguous. A source delegation reference resolves to a same-tenant
canonical grant, and when actor/target bindings resolve, backend-owned grant
status, endpoints, effective/revocation window and supported scope are
evaluated at source event time. The result remains separate from execution
occurrence: action/resource/time are source claims, and without a server-owned
receipt occurrence is unverified. Deployment, payment, settlement, and
delegation identifiers plus `delegatedToNamespace` remain source references.
A new bounded read-only graph state check
compares supported tenant links to source evidence and reports partial,
non-snapshot coverage; it neither repairs nor certifies the whole graph.
Associated x.com posts and x.ai news, private bot contents, server-owned
external execution receipts, and comprehensive snapshot-consistent graph
certification remain follow-on work.

For economic outcomes, optional task/outcome payment-intent and settlement-event
references resolve only against exact same-tenant records with server-owned
x402 provenance and a matching deployment registry agent reference. Public SDK
x402 observations remain source claims and cannot replace server-authoritative
payment state. Linked amount, currency and lifecycle state come from the
authoritative record; the correlation does not establish causality, verify the
source action, or prove settlement finality.
The historical gap matrices below retain their original audit date and should
not be read as a current inventory without this addendum and the linked
source-of-truth documents.

## 360 provider addendum (2026-10-23)

The backend mounts `POST /v1/experience360/frames` and
`GET /v1/experience360/catalog` for the exact 18-surface backend contract in
`docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md`.
The supplemental architectural blueprint is supporting context; it does not
expand that backend catalog. All 18 catalog entries now carry source-aligned
contract metadata and required-slot IDs. This source-alignment marker does not
mean that a provider fills every required slot or meets the complete surface
contract. The registry contains 24 technical projections; 9 are marked
`implemented` and 15 `in_flight`, and all 24 register at startup.

Agent360 has tenant-scoped identity, delegation and action-scoped authority
evidence, observed capability reach, and execution/telemetry evidence. Its
bounded capability read counts only exact active invoke grants for the resolved
canonical Agent and tenant; missing, malformed, foreign, or truncated rows keep
coverage partial or unknown. The capability profile reports observed reach
and invoke-grant coverage; it does not decide whether a new action/resource
request is authorized. Its
`policy_boundary` section now carries historical, action-scoped server
decisions when observed while keeping effective policy unknown; it does not
expose a standing policy snapshot. Its `risk_summary` composes canonical
Risk360 evidence under the product frame's risk-summary binding and does not
compute a local risk score. Agent360 no longer reads raw `obs_agent_risk_signals`
for this slot. Its provider-level nested Risk360 reader requires exact Agent
identity, a current analytics-consent receipt, evidence lineage, and an
explicit `risk_summary` plus `risk360.read` authorization decision. The Agent
provider exposes its exact canonical identity join only for admitted risk output;
social observations remain unbound. The frame
runtime now forwards a request-scoped server-derived envelope only after the
exact slot was requested and allowed, the binding targets Risk360, and the
projection declares the required capability. The envelope carries the exact
tenant, surface, subject, slot, consumer, target, capability, and policy result.
An independent actor-granted `risk360.read` authority remains unrepresented.
Agent-specific freshness, historical replay, and causal contagion remain
unknown. Its `spawned_agents` slot reads only outgoing `SPAWNED_SUBAGENT` graph
ledger evidence through Relationship360. No observed edge is unknown rather
than empty, and any observed edge remains degraded because the ledger has no
completeness watermark. Account360's `communications` slot can now consume
Communication360 evidence only for an exact tenant-owned entity subject with
matching endpoint identity bindings; account/workspace aliases, membership
fanout, source freshness, and historical consent coverage remain unresolved.
Value360's `confidence` slot now carries Economic360 model confidence only when
the score and model type/version are present. It remains model-reported and
uncalibrated for realized value or ROI, with model-governance calibration
evidence unbound.

Execution360 derives server-recorded lifecycle elapsed time from valid,
timezone-aware start and end timestamps and carries the lifecycle evidence
into `latency_cost`. A new bounded join also admits canonical AI invocation
facts only when tenant, action ID, and canonical agent ID match an admitted
execution, preserving invocation evidence and reporting cost by currency only
for known selected costs with a known cost basis. This remains invocation
telemetry, not tool latency or business value; unknown or estimated source
semantics stay explicit. It still lacks a general server-owned external effect
receipt, canonical plan-step evidence, complete input/output capture, and
detailed failures. Its approval-chain join covers current x402 decisions only;
other approval authorities and historical run links remain unknown. For
`workflow_run` subjects it admits stored tenant-scoped AgentExecution references
only when each invocation ID matches a current tenant AI fact with the same
run, action, and agent. This does not establish full workflow step coverage,
completion, or a source telemetry crosswalk.
Execution360 actor attribution now records the authenticated initiating user
separately from the acting agent. A principal resolves to a canonical Human
only through an exact tenant-scoped active `USER_ID` alias and active surviving
identity subject, with both identity evidence references. Missing, conflicting,
or unavailable identity reads remain unknown, and the link does not establish
action authorization or delegation authority.
Its `risk_events` slot now joins bounded canonical RiskSignals and RiskAssessment
snapshots to exact execution IDs admitted by tenant server lifecycle records.
These records provide risk context, not proof that the execution caused a
signal or assessment. Producer coverage, assessment history, and freshness
thresholds remain unknown. The agentic risk-signal
compute/store producer described in Bucket 4 is still missing. Agentic
fraud-network detections are separately persisted to Risk360
only after a unique tenant-owned Agent binding is resolved and its valid,
timezone-aware binding timestamp is no later than the detector observation;
missing, conflicting, malformed, or future timestamps cause omission. This
prevents retrospective attribution but does not establish execution causality
or contagion. Its `tool_calls` slot also joins `CALLED_TOOL`
lifecycle edges only to exact tenant execution records with a canonical agent
binding, validates the tenant-owned Tool vertex, and requires timestamp and
edge-idempotency evidence. An observed edge proves only that AETHER recorded a
tool-call lifecycle fact; graph completeness, tool outcome, action authority,
and external effect remain unknown.

The frame runtime joins available provider output to communication, risk,
economic, and outcome projections. Tenant policy runs before provider reads.
Delegation parties resolve only through exact tenant-scoped canonical entity
rows; a missing or duplicate party binding leaves the authority slot unknown
or conflicted. Event-time delegation evidence remains separate from verified
external execution. All 24 technical providers register at app startup (9
`implemented`, 15 `in_flight`), but registration does not prove required-slot
conformance. Unknown, missing, and degraded states are preserved. Complete
episode-to-payment references, complete source evidence, policy and freshness
behavior, and surface-level golden coverage remain follow-on work across the
18 surfaces; none is claimed by the mounted route or catalog.

The 2026-10-23 provider wave adds three bounded joins without closing their
product surfaces. Episode360 `timeline` resolves only observation IDs persisted
on the tenant's episode records to exact, active semantic Silver observation
rows and preserves evidence. Semantic SDK rows now carry a backend-stamped
source namespace; the EpisodeEngine can persist a typed link when a caller
supplies an explicit semantic authority marker and episode association.
No live semantic-to-episode producer supplies that association yet. Broader
activity/session inventory, policy disposition, and freshness remain unknown.
Campaign360 `signal_sources` resolves exact canonical event IDs referenced
by campaign touchpoints, matching gateway-admitted SDK Bronze observations,
and exact current touchpoint classification revisions. The observation join
requires exact tenant, event ID, type, and event time. The source fact join
requires tenant, touchpoint, revision ID, class, classifier version, and time;
both expose limited metadata and canonical evidence. Campaign membership
is not inferred from labels or event properties. Broader observation producers,
campaign registry source, broader source facts, complete event coverage, and
freshness remain unknown. Memory360
`policy_state` renders exact
tenant-and-subject historical allow decisions with timestamped consent-policy
evidence; this records the decision made at memory write time and does not
evaluate current consent or policy. These joins are partial slot capabilities,
not surface completion or authority to execute actions.

Signals360 `quality` now exposes separate current site-install signal status
only for an accepted SDK observation with an authenticated server-stamped site
namespace and exact tenant/site installation record. `source_inventory` also
resolves the exact current site registration as a source fact for that namespace;
historical site status and fleet coverage remain unknown. This does not establish
event-time health, fleet health, mobile linkage, or source reliability.
A follow-up provider slice adds partial Signals360 `classification` evidence
for exact tenant SDK event types and families after gateway acceptance and
canonical event registry validation. It does not join tenant source attribution,
semantic model output, policy, or freshness in that slice. Workflow360 resolves human
execution initiators and approval deciders through unique active tenant
USER_ID aliases and joins exact x402 approvals referenced by run-linked
AgentExecutions. The writer stores workflow and invocation references only when
a unique tenant-scoped AI invocation has `action_id` equal to the stable
execution ID; Workflow360 rechecks tenant, run, agent, and action equality.
Workflow definition-to-run linkage, complete actor and step coverage,
workflow-wide approval authority, policy, and freshness remain unknown.
Workflow360 `triggers` now
resolves allowlisted metadata only for exact tenant analytics events named by
run-linked AgentExecution `triggered_by_event_id` references when the event
source reports an available read. It suppresses any supplied rows when the
source reports unavailable or not-read. The output proves the stored reference,
not event causation or complete trigger coverage; temporal requests suppress
this current-state read. Account360 adds bounded member
Risk360 frames only after the `MEMBER_OF` candidate resolves to a live exact
tenant graph-mutation-ledger aggregate and canonical tenant entity, followed by
account-slot and per-member policy checks. Roster completeness, temporal reads,
related-account aggregation, and freshness remain unknown.
Account360 contract evidence now requires the billing authority's explicit
`contract_profile_id`; a generic repository row ID cannot stand in for it.
Obligation execution, history, and freshness remain partial. Communications360 reads
exact-subject RiskSignals for mapped recipients and resolved sources under
current analytics consent; the resolved-agent path now also requires an exact
canonical identity and current analytics-consent receipt before reading
RiskSignals. Composite Risk360 output, message-edge transfer, complete identity
coverage, and freshness remain unknown. Journey360's required `communications`
slot now joins only tenant-scoped canonical facts with an exact typed journey
ID; message endpoints and free-text references do not qualify, while message-
spine coverage, completeness, freshness, and historical replay remain unknown.
Journey360 `attribution` now also resolves each recorded conversion and
touchpoint ID through an exact tenant-scoped canonical read. Eligible current
rows with event times no later than the completed run contribute evidence;
missing, conflicting, deleted, or unavailable rows remain unknown. The credit
still records model output, not causal proof or the subject's state at run time.
Risk360's required `policy_flags` slot also exposes exact tenant-and-Agent
`obs_agent_risk_signals` as reported observations with evidence. It states that
policy evaluation is unattested and the model-governance version is absent;
non-Agent and historical requests remain unknown. `anomaly_events` now admits
exact typed-subject Gold alerts with a matching RiskSignal event reference and
can verify one explicitly referenced tenant Bronze SDK event record without
reading payload. A RiskSignal alone remains an assessment input, not an anomaly
finding; detector coverage, cause, event completeness, and freshness are open.
Episode360 `agent_handoffs` remains unknown because episode records and
observations do not reference a canonical execution or handoff ID. Event labels
and agent metadata do not establish that relationship.

The next provider slice adds bounded Communications360 `policy_state`, Risk360
`propagation_paths`, and Value360 `reconciliation` evidence. Communications360
checks current server consent only for exact recipient-entity and purpose pairs
and keeps historical outcomes separate; non-consent policy and durable current
decision evidence remain unavailable. Risk360 exposes consent-gated observed
FOLLOWS paths with relationship evidence, but leaves causal social contagion
unknown. Value360 preserves separate economic and commerce observations and
resolves only explicit settlement-to-payment references within the same order;
it does not match economic rows across sources or calculate reconciled totals.
All three are partial slot paths and do not complete their product surfaces.

A further slice adds partial Profile360 `syndicates` and Commerce360
`availability_price` paths. Profile360 verifies exact current
`MEMBER_OF:<entity>:<population>` ledger edges only for explicitly opted-in,
tenant-owned Syndicates populations and cites the live mutation ID. Historical
membership, roster completeness, and freshness remain unknown. Commerce360
exposes product/offer catalog lifecycle evidence only; inventory availability,
current offer price, and freshness remain unknown. Location360 `timezone`
remains unknown because no exact tenant-scoped geographic timezone mapping is
connected; coordinates and place names are not used to infer it. None of these
changes completes a product surface or adds agent execution authority.

The current 2026-10-23 provider wave adds evidence-backed Identity360 source
identifier, namespace, and alias rows; namespace/provider-registry linkage
uses the exact recorded `source_system_id` to resolve allowlisted metadata
from the loaded provider runtime registry, while registry freshness remains
unknown. Social360 now exposes opted-in Syndicates membership only
after an exact tenant `MEMBER_OF` graph-ledger join, with roster completeness,
history, and freshness unknown. Value360 attribution credits now rejoin exact
conversion and campaign-touchpoint records, but historical attribution is not
available and the credit repository read remains unbounded.

Actor metadata in Agent360 and Execution360 now separates the authenticated
initiator from the action driver and carries independent driver scores for
human, agent, system, and unknown. Only an exact canonical server execution actor
claim currently supports an Agent driver score; source-reported telemetry alone
does not. Agent360's typed two-edge delegation view requires one complete,
continuous path with exact records and canonical party evidence. The view does
not establish transitive authority, effective authorization, or permission to
execute. These are partial backend paths and do not complete the 18 surfaces.

The 2026-10-23 provider slice also adds Value360 `ltv` evidence over exact
subject-linked canonical conversions. Only confirmed or adjusted rows with
occurred-at values inside the requested strict window contribute to native
currency subtotals; every row must retain canonical conversion evidence. The
slot never reports a scalar LTV amount because lifetime completeness, outcome
attribution, and freshness are unproved. Missing net values reduce reported
coverage, and absent rows remain empty rather than being treated as zero.

Value360 `web2_value` and `web3_value` now receive partial claims from the
exact order-linked commerce payment path. Web2 claims require a completed
payment with an explicit card, ACH, wire, SEPA, or bank-transfer rail. Web3
claims require a canonical crypto flow or on-chain rail, a complete source or
destination amount/asset/chain leg, and a transaction-hash EvidenceRef whose ID
exactly matches the source hash. Stripe onramp joins only when the verified
session carries an exact order reference and source amount/currency; unknown or
ambiguous PaymentIntent methods remain unclassified. Native values are not
aggregated or normalized, and wallet identity, source coverage, policy, and
freshness remain unknown.

The latest 2026-10-23 slice adds four partial provider joins. Signals360
`campaign_links` follows exact tenant/source-event touchpoints and exposes a
campaign only after a same-tenant canonical campaign lookup. Episode360
`conversion_events` joins only outcome IDs recorded on exact tenant episode
rows and admits registered conversion definitions with canonical evidence.
Workflow360 `outcomes` follows outcome IDs referenced by exact tenant/run AI
invocation facts through `OutcomeTruthStore`, without claiming workflow
causality; historical reads are suppressed. These paths preserve incomplete
coverage and unknown policy/freshness. They do not complete any of the 18
product surfaces or add action authority.

Journey360 `episodes` joins only tenant-scoped EpisodeRecords that explicitly
persist the exact `journey_id`, with record/source evidence. The bounded store
scan cannot establish complete association coverage; legacy or unlinked
records, freshness, policy, and historical replay remain unknown.

The 2026-10-26 Signals360 follow-up joins a capped current Silver semantic
observation read to the exact gateway-accepted SDK event only when tenant,
event ID, backend-stamped source namespace, event type, occurrence time, and
source evidence agree. It exposes status and model identity metadata without
derived labels, actor references, or subject references. Missing, truncated,
inactive, mismatched, and historical semantic reads remain unknown. Model
correctness, consent disposition, producer coverage, source reliability, and
freshness are still unverified; the event-type claim does not borrow semantic
evidence.

Value360 `financial_risk` now composes separate Economic360 and Risk360 claims
only when both carry evidence for the exact same tenant and subject. The risk
claim must be an assessed economic, payment, or transaction dimension; generic
RiskSignals do not qualify. Historical or explicitly ranged reads remain unknown because a
coordinated snapshot is unavailable, and current freshness remains unknown, so
the slot stays degraded. Three required slots remain incomplete: Episode360
touchpoints now resolve only explicitly recorded episode touchpoint IDs, with
legacy records, complete link inventory, policy, freshness, and attribution
links unknown; Risk360 anomaly events have only exact Gold alert and optional
Bronze event evidence, without detector coverage or cause; and Memory360
cards/embedding metadata lack canonical records. Timing and
generic identifiers are not used to invent these links.
The Value360 risk binding now requests only Risk360's narrow `financial_risk`
section, excluding unrelated findings, poisoning evidence, policy flags, and
social propagation from the composed value slot.

The latest backend slice adds partial Commerce360 `intent` evidence for
explicit human declarations against exact tenant-owned product/offer records;
views, carts, checkout, and payments are not treated as intent, while agent
writers and freshness remain unsupported. Support360 `callbacks` reads typed,
idempotent callback schedule/execution events bound to an exact case and
verified provider connection; provider signature, writer identity, source
history, and freshness remain unproved. Communication360 `participants` now
accepts source-authenticated typed role rosters and resolves identities only
through exact tenant/provider/account bindings. The HMAC authenticates the
source but does not verify participant identity or role, provider conversation
membership is not canonicalized, and delegation references remain source
claims. These new paths do not complete the affected surfaces.

The Agent authorship read now requires the author participant's exact canonical
Agent entity, tenant, provider account/conversation scope, a role interval
covering the recorded event, and both canonical fact and trusted provider role
evidence. Loose agent, principal, or actor references do not qualify.
Historical requests keep authorship unknown until participant-role replay is
available; signed provider rosters alone do not establish canonical
Conversation membership or complete authorship.

For Agent360 and Execution360, the delegation engine now records an explicit
timezone-aware `evaluated_at` on the action/resource-scoped decision log. The
providers use only that exact decision timestamp, keep legacy missing values
unknown, and degrade malformed or after-execution timestamps. This improves
decision-time evidence but does not establish current or standing authority,
historical replay, or additional authority scopes.

## Bucket 1 — Correctly observation-only

| File | Notes |
|---|---|
| `services/api/value/x402/control_plane.py` | Orchestrates workflow state (issues challenges, routes to approval, records settlement). Does NOT execute transfers. Naming "control plane" is appropriate: it controls AETHER's internal state machine, not external execution. |
| `services/api/value/x402/settlement.py` | FSM state tracker only. Records `pending→verifying→settled` transitions. No funds moved. |
| `services/api/value/x402/verification.py` | RPC *reads* only (`eth_getTransactionReceipt`, `getTransaction`). Does NOT submit transactions. |
| `services/api/value/x402/lifecycle_mapper.py` | Persists source lifecycle references; on submission it stores an authorization ID only when the tenant-scoped authorization record names the same challenge/intent. It does not authorize or execute a transfer. |
| `services/api/value/x402/approvals.py` | Approval workflow FSM. Routes and records human operator decisions. No autonomous execution. |
| `services/api/value/x402/entitlements.py` | Mints time-bound access tokens after external settlement confirmed. Governance artifact only. |
| `services/api/value/x402/policies.py` | Policy engine: evaluates allow/deny/require_approval. Emits decisions; does not enforce them autonomously. |
| `services/api/value/x402/interceptor.py` | Header parsing only. Observational. |
| `services/api/value/x402/economic_graph.py` | Graph mutations for lifecycle stages. Observational. |
| `services/api/actions/agent/economic.py`, `services/api/identity/profile/agent.py` | Agent economic views and Agent 360 expose evidence-only links from tenant-scoped payment intents to exact-match authorization, execution and settlement-event records. Authorization also requires an exact tenant/challenge/agent match to its authoritative PaymentRequirement. Source lifecycle status remains authoritative. |
| `services/api/value/economic/operation_linkage.py`, `services/api/value/commerce/order_payment_reconciliation.py` | Commerce and agent lifecycle links carry source-owned references only. Exact Stripe order/payment evidence can carry a distinct succeeded refund with an explicit `reverses` relation. The commerce ledger can also preserve an authoritative settled outcome and link it with `settled_by` only to explicit provider/payment IDs, including knowledge-time visibility; no current processor adapter emits this evidence. Neither link carries amounts, infers settlement from payment completion, executes a transfer, or changes the original payment's source status. |
| `services/api/ingestion/ingestion/lifecycle_worker.py` | Only closed-registry server-authoritative x402 topics project agent PaymentIntent/SettlementEvent records to existing graph vertices and registered edges; SDK terminal claims remain excluded. |
| `services/api/actions/agent/lifecycle_mapper.py` | Routes agent events to repositories and graph. Observational. |
| `services/api/actions/agent/worker_bridge.py` (2026-07-10) | Publishes internal objective-step envelopes to AETHER's own Agent Layer Celery broker by task name. Internal work dispatch only — no external execution, no payments, no trades. Hosted modes fail closed when the broker is unreachable. |
| `services/api/actions/agent/worker_routes.py` (2026-07-10) | Worker status callbacks (`agent:run_update` service credential). Records run state; executes nothing. |
| `services/api/actions/agent/mutation_commit.py` (2026-07-10) | Commits staged graph mutations ONLY after explicit human approval of a review batch; GraphWriteValidator + CIS quarantine gate every write. Mutates AETHER's internal graph, never external systems. |
| `services/api/actions/agent/briefings.py`, `services/api/actions/agent/ops_alerts.py` (2026-07-10) | Durable operator briefings and compressed ops alerts generated from internal runtime state. Read/aggregate only. |
| `services/agents/workers/discovery/` | Web crawling, chain monitoring, social listening. All observational. |
| `services/agents/workers/enrichment/` | Entity resolution, profile enrichment, semantic tagging. Data transformation only. |
| `packages/shared/trading-profile.ts` | Aggregated trading/financial profile data model. Observational. |
| `docs/reference/source-of-truth/REWARD_NO_CUSTODY_MODEL.md` | Explicit non-execution policy. Correctly defines AETHER as non-custodial. |

## Bucket 2 — Ambiguous: could imply AETHER executes

| File | Issue | Resolution |
|---|---|---|
| `docs/architecture/AGENTIC_COMMERCE_BUILD_SPEC.md` | Phrases like "AETHER settles" or "control plane settles payment" imply execution | Reframe as "externally observed settlement" and "AETHER records settlement" |
| `docs/reference/source-of-truth/EVENT_REGISTRY.md` | Events `x402_payment_submitted`, `x402_payment_settled` could imply AETHER submits/settles | **Partially resolved:** canonical x402 observation events now added in `packages/shared/contracts/event-registry.json` (`x402_payment_required_observed`, `x402_payment_initiated_observed`, `x402_payment_verified_observed`, `x402_payment_failed_observed`, `x402_resource_unlocked_observed`, `x402_settlement_confirmed_observed`). Legacy ambiguous names remain in non-generated section and should be deprecated in a follow-up PR. |
| `packages/shared/events.ts` | Same events in TypeScript union | **Partially resolved:** observation-style events added to the generated section. `x402_signature_observed`, `x402_settlement_observed` present. Legacy `x402_payment_submitted`, `x402_payment_settled` remain in non-generated section. **2026-07-08 update:** 5 sensitive agent trading events (`agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`) now require `financial_activity` consent purpose in `EVENT_CONSENT_PURPOSE`. Their `EVENT_FAMILY` remains `'agent'`. This gates sensitive financial data behind explicit user consent. **2026-07-08 update (derivatives):** 11 derivatives SDK lifecycle events (`trading_account_connected`, `trading_account_disconnected`, `trading_account_authorized`, `trading_account_deauthorized`, `trading_agent_enabled`, `trading_agent_disabled`, `trade_intent_created`, `trade_approval_requested`, `trade_approval_resolved`, `risk_policy_updated`, `human_trade_override_recorded`) added to the generated section with `financial_activity` consent and `financial_7y` retention. All are observation-only; `execution_by_aether` remains false. Web, Android, and iOS SDK event dispatch tables updated. **2026-07-09 update (AI economics):** `ai_invocation_observed` added to the generated section (family `agent`, consent purpose `agent`, retention `standard_90d`) — an observation-only AI execution telemetry event carrying identity/usage/cost/latency/quality metadata and never raw prompt or completion content; `execution_by_aether` semantics are unaffected. Web, Android, and iOS consent maps updated in the same commit. **2026-07-09 update (deployment telemetry):** `AgenticObservationRecord` gains an optional additive `deployment_id`; `graph_mutations.py` gains a flag-gated aggregate deployment projection reusing `EXTERNAL_AGENTIC_ACCOUNT` vertex + `AGENT_LINKED_TO_EXTERNAL_ACCOUNT` edge with `kind="agent_deployment"` (one vertex/edge per deployment, never per event). Observation-only; `execution_by_aether` unchanged. |
| `services/api/value/x402/settlement.py` | `SettlementState.SETTLED` transition could be misread as fund settlement | Resolved beyond comment level: outside local, `_advance` parks settlements in `PENDING` — `SETTLED` is asserted only by reconciliation or explicit operator action, so the recorded state can no longer overstate observed settlement |

## Bucket 3 — Incorrect: AETHER appears to originate/execute

No files in this bucket. The existing x402 and agent infrastructure is correctly observation-only.

## Bucket 4 — Missing: needed for observability

| Gap | What needs building |
|---|---|
| Robinhood-style external agentic account observability | `services/api/connectors/external_account_observability/` — observe account linkage, budgets, permissions, disconnect events |
| Robinhood-style trading observation | `services/api/connectors/external_account_observability/brokerage_models.py` — observe trade intents, orders, fills, rejections, positions, portfolios, performance |
| AgentMail-style inbox observation | `services/api/actions/agent_comm_observability/inbox_models.py` — observe inbox creation, email addresses, threads |
| AgentMail-style message/attachment observation | `services/api/actions/agent_comm_observability/message_models.py` — observe messages, attachments, extractions |
| AgentMail-style entity extraction observation | `services/api/actions/agent_comm_observability/extraction_models.py` — OTP, invoice, receipt, calendar intent, support routing |
| x402 protocol observation (from observer perspective) | `services/api/graph/protocol_observability/` — observe challenges, requirements, signatures, verifications, settlements, resource access as seen by an external observer |
| MCP connection observation | `services/api/actions/agentic_observability/` — observe MCP connections, tool invocations, agent activity |
| Agent risk signals | `services/api/actions/agentic_observability/risk_signals.py` — compute and record risk signals from observed activity |
| Canonical observation envelope | `packages/shared/agentic-observability.ts` — `AgenticObservationEvent` TypeScript type |

## Bucket 5 — Kyber visibility gap

| Gap |
|---|
| No Kyber module for agentic activity (MCP connections, tool invocations, external accounts) |
| No Kyber module for x402 lifecycle from observer perspective (challenges, signatures, resource access) |
| No Kyber module for agent inbox/message/attachment activity |
| No Kyber module for external brokerage account observations |
| No Kyber module for agent risk signals and drift detection |
| Missing: `GET /v1/admin/kyber/agentic-observability/*` routes |

## 2026-10-23 — Canonical evidence and authority joins

The current backend now writes an exact reciprocal link between supported
agent activity/tool/risk compatibility rows and their canonical Bronze event.
Agent360 verifies tenant, agent, evidence table and row ID, Bronze event ID,
schema, type, and timestamp before returning the provenance. It does not infer
links by matching provider names or nearby timestamps. Provider identity and
trust remain unresolved without a Rights `source_id`; freshness remains
unassessed because no source SLA is configured. Historical compatibility rows
without an explicit canonical link therefore remain degraded.

Agent360's required `owner_delegator` slot resolves the configured
`owner_entity_id` through an exact tenant-scoped entity lookup and joins it to
the resolved canonical Agent only when a bounded tenant graph read observes an
exact `OWNS` or `OWNS_AGENT` edge. Claims cite the graph edge, configuration,
and Agent identity evidence. A stored edge does not establish legal or effective
ownership, historical validity, freshness, or action authorization; truncation
and scope uncertainty remain explicit.

Execution360 joins AETHER-owned execution rows to typed x402 approval requests
and decisions by exact tenant, admitted execution ID, lifecycle approval ID,
and stored action/resource references where available. An action or resource
conflict suppresses the linked request and decision evidence. The view retains
the latest decision pointer and supported decision history, but covers x402
commerce only; effective authorization, other approval systems, historical run
replay, and a freshness threshold remain unknown. Risk360 can read
typed, tenant-scoped poisoning evidence with lifecycle and restatement history,
but no production detector currently writes those records. These additions
close evidence-path pieces; they do not complete Agent360, Execution360,
Risk360, or the full 18-surface contract.

Execution360 additionally joins an admitted external Silver telemetry event
to one exact tenant Bronze event when ID, event type, and occurrence time match
the recorded observation envelope. It publishes sanitized ingress provenance
and a Bronze evidence reference, with source identity and external execution
still unknown. Support360's journey context can report an exact episode
relation only if an EpisodeRecord cites the verified case journey-link event
and names the same journey. No live producer currently writes that association;
historical state, population completeness, and freshness are unproven.

Execution360's `authority_check` now exposes the delegation-engine outcome
stored in `agent_executions.policy_log.delegation_check` only when it joins to
the same exact tenant-scoped lifecycle record with its action, resource, and
lifecycle evidence. The delegation engine now records a timezone-aware
evaluation timestamp, and the provider accepts it only when it does not
postdate the execution record. Legacy missing timestamps remain unknown; the
recorded decision still does not claim current or standing authority.
Duplicate, malformed, or incomplete joins remain degraded, while x402
approvals and other authority sources remain separate or unknown.
If the persisted execution delegation ID and the stored policy decision's
delegation ID conflict, the provider omits that decision and its observed
authority claim, degrades the scope, and leaves the frame action outcome
unknown. This differs from a currently missing grant record, which does not
erase a valid recorded request-time decision.

Support360's required `risk` slot now routes to Risk360 after policy. Risk360
proves the canonical tenant/case pair before reading case-keyed RiskAssessment
and RiskSignal records and includes both risk and support-case evidence. If the
case record is missing, expired, unavailable, or out of tenant scope, risk
reads are suppressed. Case risk-history completeness, signal coverage,
freshness, business outcome, and contagion authority remain unknown.

The latest provider pass adds bounded standing-delegation observations to
Agent360 only after exact canonical agent and party evidence; the provider
continues to report effective authorization as unknown. Its communications
read now requires one resolved canonical tenant Agent before admitting
source-asserted inbox/message rows; a positive claim cites identity, inbox,
and message evidence but does not prove provider conversation membership.
Workflow360 has an append-only, authenticated definition authority with a
bounded exact-workflow historical `asOf` read; configured triggers and steps
are separate from observed runs and outcomes. For a current definition, the
backend-stamped registrar reference can resolve through one active tenant
`USER_ID` alias with canonical Human evidence. Historical registrar identity
remains unknown because alias history is unavailable, and the registrar is not
inferred to have initiated or approved any run. An authenticated AgentExecution
can retain a caller-reported definition ID, revision, and digest only after an
exact tenant AI invocation run link and active definition check; Workflow360
revalidates the persisted reference before showing a partial run association.
It does not establish trigger or step execution, causality, complete external
run coverage, or historical replay. Social360 has explicit
trust and transmission assertions backed by exact tenant entity, source
event, graph-path, and risk-signal references. Those assertions are not graph
mutations or causal contagion proof. Risk360 can admit an anomaly alert when
its exact RiskSignal and event evidence exist. Explicit `bronze_sdk_events`
references can now resolve one tenant Bronze record, but no production detector,
complete event coverage, cause, or freshness follows from that admission.
Episode semantic observations now carry a backend-stamped source namespace.
EpisodeEngine's exact-link producer requires an explicitly associated
semantic observation; live association and full timeline coverage are still
required. These changes leave the 18 product surfaces partial.

## Bucket 6 — Profile360/graph gap

| Gap |
|---|
| `docs/architecture/PROFILE-360-AGGREGATION.md` has no Agent entity section |
| No Profile360 tabs for: MCP connections, external accounts, inbox activity, x402 interactions, trade intent observations, risk signals |
| Graph schema (`shared/graph/graph.py`) missing 26 observation vertex types |
| Graph schema missing 38 observation edge types |

## Bucket 7 — Source-of-truth drift

| File | Drift |
|---|---|
| `docs/reference/source-of-truth/EVENT_REGISTRY.md` | Missing 47 new observability events across 4 families |
| `docs/reference/source-of-truth/ENTITY_MODEL.md` | Missing 44 new entity types across 4 groups |
| `docs/reference/source-of-truth/SDK_SCOPE.md` | No explicit no-execution rule |
| `docs/reference/BACKEND-API.md` | Missing 30+ observability routes, 7 Kyber admin routes |
| `docs/architecture/ECONOMIC-OBSERVABILITY.md` | Framing does not distinguish "externally observed" from "AETHER-originated" |
| `docs/architecture/PROFILE-360-AGGREGATION.md` | No Agent entity Profile360 sections |

## PR 1 current-state audit and gap matrix (2026-07-03)

| Capability | Current implementation | Current source files | Status | Required action | Target PR | Acceptance test |
|---|---|---|---|---|---|---|
| Router activation | Agentic, protocol, communication, and external-account routers are mounted from `main.py` behind `AGENTIC_*` feature flags. | `services/api/main.py`, `services/api/config/settings.py` | partial | Add capabilities endpoint exposure and deeper per-route disabled-state tests. | PR 1 follow-up | Router mounting and feature-flag tests. |
| Tenant authority | Routes now reject request-body tenant mismatches and use authenticated request tenant for persisted rows. | `services/api/actions/agentic_observability/foundation.py`, observability route modules | partial | Extend the same helper through x402 routes and legacy repositories. | PR 1/2 | Missing/mismatched/cross-tenant tests. |
| Graph tenant naming | Graph-boundary helper adds canonical `tenantId` while preserving legacy `tenant_id` for current graph readers. | `services/api/actions/agentic_observability/foundation.py` | partial | Complete graph-contract migration to one reader-visible canonical property. | PR 5 | Graph contract parity and cross-tenant graph tests. |
| Mutation counts | Agentic routes report built and persisted counts; compatibility `graph_mutations_queued` now equals persisted count. | `services/api/actions/agentic_observability/routes.py`, `schemas.py` | partial | Move all graph writes to durable outbox and update protocol/comm/external responses with the richer schema. | PR 2 | Truthful mutation count tests. |
| Silent graph failures | Shared helper logs structured graph projection failures and returns `failed` status without rejecting accepted observations. | `services/api/actions/agentic_observability/foundation.py` | partial | Store failures durably in outbox/dead-letter tables. | PR 2 | Worker retry/dead-letter tests. |
| Event name validation | Generic agent event endpoint rejects names not present in canonical generated registry. | `services/api/actions/agentic_observability/foundation.py`, `services/api/ingestion/ingestion/generated_registry.py` | partial | Add generated TS/Python/OpenAPI parity checks for all observability event families. | PR 1/3 | Unknown-event and parity tests. |
| No-execution invariant | Existing `Literal[False]` checks are backed by a shared route validator with clearer error text. | `services/api/actions/agentic_observability/foundation.py` | partial | Extend import-boundary/static dependency checks. | PR 8 | Negative route and import-boundary tests. |
| Kyber placeholders | Agentic, inbox, and external-account Kyber endpoints return repository-backed counts/lists instead of placeholder messages or hardcoded empty arrays. | observability route modules | partial | Build full Kyber lineage, replay, reconciliation, and health surfaces. | PR 7 | Non-placeholder route tests. |
| Canonical ingestion | Observability-specific JSONB repositories still accept production writes. | `repositories/agentic_observability_repos.py` | scaffold | Route through Bronze → Silver → canonical_activity → outbox. | PR 2 | Pipeline integration test. |
| Product surfaces | Profile 360, Journey v2, Cluster360, campaign, Noesis, and frontend propagation remain incomplete. | profile/journey/cluster/campaign/noesis/frontend services | missing | Implement propagation and evidence labeling. | PR 6/7 | End-to-end product scenario. |
