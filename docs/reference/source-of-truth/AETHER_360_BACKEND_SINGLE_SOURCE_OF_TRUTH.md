# Aether 360 Backend Single Source of Truth

**Repo-executable implementation spec**<br>
**Scope:** backend only<br>
**Generated:** 2026-10-03<br>
**Target repo:** `DammnThatsCrazy/AETHER`

This document replaces the prior broad 360 architecture blueprint as the implementation authority for backend work. It defines the contracts, module layout, registry, services, migrations, risk/contagion subsystem, API handlers, tests, rollout order, and acceptance gates needed to build the entire 360 system inside the repo.

## Repository implementation status (2026-10-23)

This specification remains the acceptance contract for the complete 18-surface backend buildout. The repository has partial provider paths across required slots, with the remaining limits recorded explicitly; no product surface is complete:

- **Episode360 `timeline`:** resolves only observation IDs explicitly recorded by an episode through tenant-scoped semantic Silver rows. Untyped source namespaces, complete activity/session coverage, policy, and freshness remain unresolved.
- **Campaign360 `signal_sources`:** joins exact campaign touchpoint event references to tenant-scoped canonical events. Broader observation and source-fact authorities, complete event coverage, and freshness remain unresolved.
- **Memory360 `policy_state`:** exposes exact historical write-time allow decisions with timestamped consent-policy evidence. Current consent and policy evaluation remain unknown.
- **Signals360 `classification`:** validates the exact tenant-scoped, gateway-accepted SDK event type and family against the canonical event registry. Source attribution, semantic classification, policy, and freshness remain unknown.
- **Workflow360 `actors`:** projects exact run-linked AI invocation agents and resolves execution initiator and approval decider references only through unique active tenant USER_ID aliases. Workflow-wide actor coverage and authority remain unknown.
- **Workflow360 `triggers`:** projects a stored trigger event reference only when an admitted tenant/run-linked AgentExecution contains the exact event ID and the tenant-scoped event authority is available; the projection fails closed if rows arrive from an unavailable or unread source. Trigger definitions, workflow causality, complete coverage, policy authority, and freshness remain unknown.
- **Account360 `members`:** treats tenant `MEMBER_OF` graph edges as candidates, then requires the exact tenant aggregate replay in the graph mutation ledger to prove the membership is live before joining the canonical member entity. Roster completeness, historical membership, and freshness remain unknown; a truncated ledger scan returns no members.
- **Workflow360 `approvals`:** joins exact x402 approval requests and decisions referenced by admitted tenant/run-linked AgentExecutions. Workflow-wide approval coverage and authorization policy remain unknown.
- **Workflow360 `agent_steps`:** admits only tenant/run-linked AgentExecution rows whose stored invocation IDs match exact run-linked AI facts with the same agent and an `action_id` equal to the stable execution ID. Full workflow definitions, step coverage, policy, and freshness remain unknown; linkage is unavailable when the producer does not supply that exact ID.
- **Agent360 `owner_delegator`:** resolves a configured `owner_entity_id` only through the bounded, exact tenant-scoped entity lookup and preserves configuration plus entity evidence. The configuration reference does not establish legal or effective ownership, historical validity, freshness, or action authorization.
- **Agent360 `risk_summary`:** raw `obs_agent_risk_signals` are no longer read into the Agent360 projection or its claims. The frame runtime forwards a server-derived `risk_summary` authorization only for an explicitly requested, policy-allowed slot bound to `risk360.read`; Agent360 validates tenant, subject, consumer, target, policy receipt, and canonical Agent identity before its nested Risk360 read. Agent-specific freshness, historical replay, and causal contagion remain unknown.
- **Execution360 `authority_check`:** exposes an exact request-time delegation-engine outcome only when `agent_executions.policy_log.delegation_check` is joined to the same tenant-scoped lifecycle record and its recorded action, resource, evaluation timestamp, and lifecycle evidence. New evaluations persist `evaluated_at` in that policy log and the projection rejects timestamps after the execution record was created; legacy rows without the timestamp remain unknown. This application-recorded outcome does not establish current or standing authority, replay policy inputs, or cover x402 approvals and other authority sources.
- **Execution360 `approval_chain`:** joins exact tenant-scoped x402 approval requests and decisions to admitted execution IDs and lifecycle approval references, rejecting recorded action/resource conflicts. Other approval authorities, effective authorization, historical replay, and a freshness threshold remain unknown.
- **Execution360 `risk_events`:** joins bounded current RiskSignals and RiskAssessment snapshots to admitted lifecycle execution IDs using exact tenant and execution-subject keys, preserving record and component evidence. Producer coverage, assessment history, freshness, and causal attribution remain unknown; recorded risk does not establish that an execution caused a signal or assessment.
- **Support360 `resolution`:** exposes resolved or closed lifecycle state only when the applied case event timestamp matches the canonical case state and exact provider-event and connection evidence are present. Business outcome facts, history completeness, and freshness remain unresolved.
- **Support360 `case_timeline`:** each event is emitted only with its exact provider-event and provider-connection evidence, validated against the canonical case connection, provider identity, event ID, and timestamp. Missing event evidence degrades the timeline; history completeness and freshness remain unknown.
- **Support360 `risk`:** binds only after the canonical support-case repository proves the exact tenant and case ID, then reads case-keyed RiskAssessment and RiskSignal records with both risk and case evidence. Signal coverage, risk history, support-case freshness, outcome attribution, and contagion authority remain unknown; unproven case identity suppresses risk reads.
- **Support360 `callbacks`:** records typed schedule, reschedule, attempt, completion, failure, and cancellation events in a tenant/case/provider-connection scoped callback authority. Support360 validates the exact case, connection, callback, and event evidence; event replay is idempotent and stale events do not regress state. Provider origin and writer actor are not verified, and source-history completeness and freshness remain unknown.
- **Communications360 `policy_state`:** evaluates current server consent only for exact tenant, recipient-entity, and purpose pairs backed by communication identity and evidence. Historical write-time outcomes are kept separate and current consent is not evaluated for as-of frames; non-consent policy, durable current-decision evidence, complete recipient coverage, and freshness remain unknown.
- **Risk360 `propagation_paths`:** exposes bounded current tenant-scoped FOLLOWS paths only after analytics-consent, endpoint, graph-edge, relationship-evidence, and observed-time checks. The result is observed path context, not causal risk propagation; historical path reads, full coverage, and freshness remain unknown. `social_contagion` remains unbound because no causal detector/evidence authority is connected.
- **Value360 `reconciliation`:** exposes separate subject-scoped economic records and exact order-linked commerce facts, with settlement-to-payment references resolved only by explicit provider payment ID and the same commerce order. It accepts only native USD identity normalization, does not match economic records to commerce without exact shared identifiers, and does not compute reconciled totals or assert amount equality or settlement finality.
- **Value360 `ltv`:** exposes exact-subject confirmed or adjusted canonical conversion net values with conversion evidence and occurred-at scope. Totals stay partitioned by native currency; missing net values degrade coverage. This is an observed subtotal, not complete customer lifetime value: lifetime/history coverage, outcome attribution, and freshness remain unknown.
- **Profile360 `syndicates`:** enumerates bounded exact tenant/entity membership candidates, requires an explicitly opted-in Syndicates population, and verifies each positive membership against the exact current `MEMBER_OF:<entity>:<population>` graph-ledger aggregate. Positive claims cite the live edge-add mutation ID. Roster completeness, historical replay, and membership freshness remain unknown.
- **Commerce360 `availability_price`:** exposes exact tenant product/offer catalog lifecycle revisions with provenance as partial context. Inventory availability, current offer price, and freshness remain unknown; historical order prices are not joined to current offers or inventory.
- **Commerce360 `intent`:** records explicit tenant-owned intent against exact canonical product or offer IDs, preserving actor, source revision, effective/observed times, idempotency, and evidence. Only product and offer subjects are connected; commerce, SKU, and checkout intent authorities are absent. Freshness remains unknown without a configured threshold, and internal agent writers must validate delegation/execution authority upstream.
- **Account360 `risk`:** keeps direct account risk separate and adds bounded member Risk360 frames from exact tenant `MEMBER_OF` edges. The account risk slot and each member `risk_summary` policy must allow the read; roster completeness, temporal member risk, related-account aggregation, and freshness remain unknown.
- **Communications360 `risk_flags`:** reads exact-subject RiskSignals for resolved agents and sources and mapped recipient entities. All three paths require current analytics consent; recipient reads also require exact identity mappings and evidence. Message-edge transfer, composite Risk360 output, complete coverage, and freshness remain unknown.
- **Communications360 `profile_links`:** joins explicit profile identifiers on evidence-backed communication facts to exact tenant profile records. Historical identity snapshots, temporal validity, unresolved-link coverage, and freshness remain unknown.
- **Communications360 `participants`:** accepts typed participant-role rosters only through tenant-authenticated, HMAC-verified webhook ingestion, resolves provider recipient/profile IDs through exact tenant-owned identity mappings, and persists evidence-backed bindings in `communication360_facts`. The signature proves source authenticity, not identity; complete rosters remain partial until canonical Conversation membership and full message coverage are joined, and provider delegation references remain source claims.
- **Journey360 `agent_interventions`:** joins only activity IDs explicitly recorded on the current journey version to unique current tenant-scoped agent-family journey steps, with journey-version and step evidence. Agent identity, delegated authority, intervention outcome, and full step-inventory completeness remain unknown.
- **Journey360 `episodes`:** joins only tenant-scoped EpisodeRecords that explicitly persist the exact `journey_id`, with episode-record and source evidence. Legacy/unlinked records, relationship-population completeness, store freshness, policy, and historical replay remain unknown; absence is never inferred from a missing link.
- **Risk360 `audit_history`:** exposes bounded exact-subject assessment runs from the computation substrate with assessment, policy, system-time, and run evidence references. This remains partial: intervention audit events and full assessment restatement lineage are not available.
- **Identity360 `identifier_inventory`, `namespace_map`, and `aliases`:** source identifier and alias rows now require record-level evidence before they are emitted. Namespace entries remain partial because the canonical provider registry join is unavailable; missing or conflicting identifiers remain unknown.
- **Social360 `syndicates`:** joins explicitly opted-in Syndicates membership to an exact current `MEMBER_OF` graph mutation ledger edge, with evidence on every positive membership. Roster completeness, historical membership, and freshness remain unknown.
- **Social360 `influence_paths`:** projects bounded consent-authorized directed FOLLOWS paths and joins persisted tenant-scoped RelationshipFidelity measurements only when every vector evidence ID matches the exact graph edge's relationship-fact evidence. Per-hop components may be partial; path completeness, freshness, actual influence, trust, and causal contagion remain unknown. `social_contagion`, `trust_edges`, and `risk_edges` remain unbound.
- **Value360 `attribution_credits`:** rejoins each credit's conversion and touchpoint IDs to tenant-scoped canonical records and checks campaign consistency before exposing a claim. Historical attribution is unavailable, touchpoint reads are capped, and the underlying credit repository query remains unbounded.
- **Value360 `web2_value` and `web3_value`:** exact order-linked completed payment facts now preserve canonical rail, flow, native source/destination amount, asset, chain, and transaction-hash evidence. Web2 claims require explicit card, ACH, wire, SEPA, or bank-transfer rail evidence; Web3 claims require an explicit crypto flow or on-chain rail, a complete source/destination asset leg, and an exact transaction-hash evidence reference. Amounts remain native and unaggregated. Wallet identity, non-USD normalization, source coverage, policy, freshness, and full slot completion remain unknown.
- **Agent360 and Execution360 actor metadata:** typed driver scores separate the authenticated initiator from the action actor; agent-driven attribution requires exact canonical server execution evidence. Source-reported actor telemetry alone does not establish an action driver. The recorded delegation evaluation timestamp is carried into actor metadata only for one exact action-scoped decision; legacy or invalid timestamps remain unknown. Agent360 exposes a typed two-edge delegation observation only for one complete, continuous path with exact record and party evidence; it does not infer transitive authority or an effective authorization decision.

Episode360 `touchpoints` is now a partial exact-reference path: canonical episode records may explicitly record `journey_touchpoint_ids`, and Episode360 resolves those IDs against tenant-scoped canonical touchpoint rows with evidence. The recorded reference set does not establish complete journey inventory or attribution credit; policy and freshness remain unknown. Legacy episode records without the typed reference field remain unknown. Episode360 `agent_handoffs` remains unknown because episode records and observations do not reference a canonical execution or handoff ID; event labels and agent metadata do not establish that join. The product registry records these remaining gaps. None of these changes marks its surface complete or reduces the other requirements in this specification.

Location360 `timezone` remains unknown with `canonical_timezone_authority_not_joined`: location facts, geocoding labels, and source-clock timezone metadata do not provide an exact tenant-scoped geographic timezone mapping. No timezone is inferred from coordinates or place names.

## 0. Decision

Build the 360 system as a backend read-model layer over canonical Aether graph, identity, signal, journey, communication, value, risk, and agentic systems.

A 360 surface is **not** a source of truth. A 360 surface is a governed, evidence-backed, policy-filtered frame that lets the product ask:

> “For this tenant, subject, time range, policy scope, and lens set, what is the safest and most useful backend representation of this thing?”

## 1. Backend-only scope

### Included

- Backend contracts.
- Registry and surface definitions.
- Resolver/projector services.
- Lens integration.
- API route handlers.
- Database migrations and backfills.
- Snapshot/cache/evidence/policy services.
- Agent authority, actor attribution, poisoning, source trust, and contagion subsystems.
- Tests, fixtures, golden frames, telemetry, rollout gates, and acceptance criteria.

### Excluded

- Page design.
- React component implementation.
- Sidebar/navigation decisions.
- Visual layout, cards, charts, maps, animation, or styling.
- Frontend-only loading states.

The backend still returns state needed by a frontend, such as `loading`, `empty`, `degraded`, `policy_redacted`, `stale`, and `error`, but this spec does not implement frontend components.

## 2. Non-negotiable architecture laws

### 2.1 360s are read models

Every 360 endpoint returns a derived frame. It may read canonical data, graph edges, lens projections, snapshots, and evidence traces. It must not directly mutate canonical identity, campaign, journey, attribution, communication, commerce, value, risk, workflow, or agent state.

Allowed writes from the 360 module:

1. Frame cache.
2. Frame snapshot.
3. Evidence trace cache.
4. Policy audit record.
5. Diagnostics/metrics.
6. Backfill checkpoint.

Disallowed writes from the 360 module:

1. Canonical identity merges.
2. Campaign identity mutation.
3. Attribution credit mutation.
4. Profile mutation.
5. Agent permission mutation.
6. Communication content mutation.
7. Journey stage mutation.
8. Commerce/order/catalog mutation.
9. Risk score overwrites outside the risk subsystem's canonical write path.

### 2.2 Canonical ownership remains outside 360

The 360 layer can read and project canonical state. Ownership remains with the appropriate subsystem:

| Domain | Canonical owner |
|---|---|
| Raw events/signals | event/signal intake |
| Source classification | source classification subsystem |
| Campaign identity | campaign resolution subsystem |
| Identity stitching | identity resolution subsystem |
| Touchpoints | journey/touchpoint subsystem |
| Journeys | journey graph subsystem |
| Conversions | conversion subsystem |
| Attribution credits | attribution subsystem |
| Financial value | value/revenue subsystem |
| Cohorts/syndicates | grouping/syndicate subsystem |
| Geography/timezone | geo-temporal subsystem |
| Communications | communication graph subsystem |
| Agents/authority | agent identity and authority subsystem |
| Workflows/executions | execution/workflow runtime |
| Risk/poisoning/contagion | risk/trust subsystem |

### 2.3 Typed degradation is mandatory

A 360 response must never silently omit data. It must distinguish:

| State | Meaning |
|---|---|
| `missing` | Source data was expected but not found. |
| `empty` | Source was found and has no records. |
| `zero` | Numeric value is present and equals zero. |
| `redacted` | Data exists but policy removed it. |
| `stale` | Data exists but freshness SLA failed. |
| `degraded` | Frame is incomplete but usable. |
| `conflicted` | Evidence disagrees and needs review. |
| `unresolved` | Entity has not been stitched/resolved. |
| `unknown` | Entity state is unknown, not necessarily absent. |

### 2.4 Campaign identity and source classification stay separate

A source can classify an event as campaign-like. That is not the same as resolving a canonical campaign. Every Campaign, Signals, Journey, Episode, Profile, and Value frame must keep these as separate fields.

### 2.5 Journey touchpoints and attribution touchpoints stay separate

Journey touchpoints describe what happened. Attribution touchpoints explain how credit was assigned. A 360 may display both, but it must not collapse them.

### 2.6 Human, agent, and delegated action attribution is evidence-based

The system should identify who or what acted using non-biometric evidence by default:

- Authenticated subject.
- API key / token / service principal.
- Agent ID.
- Delegation contract.
- Tool call provenance.
- Execution trace.
- Session binding.
- Device/app context.
- Credential chain.
- Approval chain.
- Timing and causal sequence.
- Webhook source.
- SDK source.

Biometrics may be supported later as an optional tenant-controlled signal, but must not be required for the baseline actor attribution model.

## 3. Target backend repository topology

Create a single backend module for the 360 system:

```txt
src/modules/experience360/
  README.md
  contracts/
  registry/
  services/
  lenses/
  api/
  db/
    migrations/
    backfills/
    views/
  surfaces/
    agent/
    execution/
    episode/
    profile/
    identity/
    journey/
    communications/
    risk/
    value/
    social/
    campaign/
    signals/
    account/
    location/
    workflow/
    memory/
    commerce/
    support/
  fixtures/
  __tests__/
```

Framework-specific route wrappers should stay thin. If the repo uses Next app router, use:

```txt
app/api/360/[kind]/[subjectId]/route.ts
app/api/360/registry/route.ts
app/api/360/[kind]/[subjectId]/evidence/route.ts
app/api/360/[kind]/[subjectId]/snapshot/route.ts
```

The route wrappers must delegate to `src/modules/experience360/api/*`. Do not put business logic inside route files.

## 4. Backend file manifest

This is the build manifest. Each file listed here should exist when the backend 360 system is complete.

### 4.1 Shared files

| Target path | Action | Purpose |
|---|---:|---|
| `src/modules/experience360/README.md` | CREATE | Backend module operating guide and non-negotiables. |
| `src/modules/experience360/contracts/kinds.ts` | CREATE | All backend enums and literal unions. |
| `src/modules/experience360/contracts/frame.ts` | CREATE | Global Experience360Frame contract. |
| `src/modules/experience360/contracts/slot.ts` | CREATE | Slot state/data envelope contract. |
| `src/modules/experience360/contracts/evidence.ts` | CREATE | EvidenceRef, EvidenceTrace, source confidence. |
| `src/modules/experience360/contracts/freshness.ts` | CREATE | Freshness envelope and degradation reasons. |
| `src/modules/experience360/contracts/policy.ts` | CREATE | Policy envelope, redaction metadata, auth scopes. |
| `src/modules/experience360/contracts/lens.ts` | CREATE | Lens context/result contracts. |
| `src/modules/experience360/contracts/action-intent.ts` | CREATE | Read-model action intent contract; no direct execution. |
| `src/modules/experience360/contracts/errors.ts` | CREATE | Typed errors for invalid kind, policy denial, stale projections. |
| `src/modules/experience360/registry/experience360.registry.ts` | CREATE | Authoritative registry for all 360 backend surfaces. |
| `src/modules/experience360/registry/experience360.registry.schema.ts` | CREATE | Zod schema validating registry entries. |
| `src/modules/experience360/registry/experience360.registry.test.ts` | CREATE | Guarantees every registry surface has resolver/projector/policy/tests. |
| `src/modules/experience360/services/frame.service.ts` | CREATE | Canonical backend frame orchestration pipeline. |
| `src/modules/experience360/services/lens-context.service.ts` | CREATE | Composes requested/default lens context. |
| `src/modules/experience360/services/policy-filter.service.ts` | CREATE | Applies field and slot redaction before response. |
| `src/modules/experience360/services/freshness.service.ts` | CREATE | Computes freshness, staleness, degraded state. |
| `src/modules/experience360/services/evidence-trace.service.ts` | CREATE | Builds evidence lineage and confidence summary. |
| `src/modules/experience360/services/cache.service.ts` | CREATE | Frame cache using tenant/kind/subject/lens/policy/asOf key. |
| `src/modules/experience360/services/snapshot.service.ts` | CREATE | Snapshot write/read/diff for backend frames only. |
| `src/modules/experience360/services/diagnostics.service.ts` | CREATE | Backend-only diagnostics and metrics emission. |
| `src/modules/experience360/api/get-frame.handler.ts` | CREATE | Framework-neutral GET frame handler. |
| `src/modules/experience360/api/get-registry.handler.ts` | CREATE | Framework-neutral registry handler. |
| `src/modules/experience360/api/get-evidence.handler.ts` | CREATE | Framework-neutral evidence handler. |
| `src/modules/experience360/api/create-snapshot.handler.ts` | CREATE | Controlled snapshot creation endpoint handler. |
| `app/api/360/[kind]/[subjectId]/route.ts` | CREATE/MODIFY | Thin Next route wrapper if repo uses app router; delegates to api/get-frame.handler.ts. |
| `app/api/360/registry/route.ts` | CREATE/MODIFY | Thin registry route wrapper. |
| `app/api/360/[kind]/[subjectId]/evidence/route.ts` | CREATE/MODIFY | Thin evidence route wrapper. |
| `app/api/360/[kind]/[subjectId]/snapshot/route.ts` | CREATE/MODIFY | Thin snapshot route wrapper. |
| `src/modules/experience360/db/migrations/001_create_experience360_registry.sql` | CREATE | Registry and feature flag metadata. |
| `src/modules/experience360/db/migrations/002_create_experience360_snapshots.sql` | CREATE | Frame snapshot persistence. |
| `src/modules/experience360/db/migrations/003_create_lens_projection_index.sql` | CREATE | Projection index keyed by lens and subject. |
| `src/modules/experience360/db/migrations/004_create_evidence_trace.sql` | CREATE | Evidence trace and source confidence storage. |
| `src/modules/experience360/db/migrations/005_create_policy_audit.sql` | CREATE | Policy filter/redaction audit. |
| `src/modules/experience360/db/migrations/006_create_agent_authority_edges.sql` | CREATE | Agent authority/delegation graph edges. |
| `src/modules/experience360/db/migrations/007_create_risk_poisoning_evidence.sql` | CREATE | Data poisoning evidence and source trust. |
| `src/modules/experience360/db/migrations/008_create_risk_contagion_paths.sql` | CREATE | Social/financial/agent amplification contagion paths. |
| `src/modules/experience360/db/migrations/009_create_value_projection_views.sql` | CREATE | Read-only value attribution projection views. |
| `src/modules/experience360/db/migrations/010_backfill_initial_experience360_snapshots.sql` | CREATE | Initial backfill job for enabled tenants. |

### 4.2 Surface files

For every surface under `src/modules/experience360/surfaces/{kind}/`, create the following files.

| Target path pattern | Action | Purpose |
|---|---:|---|
| `src/modules/experience360/surfaces/{kind}/schema/{kind}.schema.ts` | CREATE | Zod schemas for frame slots and resolver inputs. |
| `src/modules/experience360/surfaces/{kind}/contracts/{kind}.contracts.ts` | CREATE | Surface-specific TypeScript slot/data contracts. |
| `src/modules/experience360/surfaces/{kind}/resolver/{kind}.resolver.ts` | CREATE | Loads canonical fragments and lens outputs. |
| `src/modules/experience360/surfaces/{kind}/projector/{kind}.projector.ts` | CREATE | Projects canonical fragments into the 360 frame. |
| `src/modules/experience360/surfaces/{kind}/policy/{kind}.policy.ts` | CREATE | Surface-specific redaction and scope rules. |
| `src/modules/experience360/surfaces/{kind}/freshness/{kind}.freshness.ts` | CREATE | Surface-specific freshness/degradation rules. |
| `src/modules/experience360/surfaces/{kind}/evidence/{kind}.evidence.ts` | CREATE | Surface-specific evidence mapping. |
| `src/modules/experience360/surfaces/{kind}/fixture/{kind}.fixture.ts` | CREATE | Representative complete/degraded/empty fixtures. |
| `src/modules/experience360/surfaces/{kind}/golden/{kind}.golden.json` | CREATE | Golden backend frame snapshot. |
| `src/modules/experience360/surfaces/{kind}/__tests__/{kind}.resolver.spec.ts` | CREATE | Resolver tests. |
| `src/modules/experience360/surfaces/{kind}/__tests__/{kind}.projector.spec.ts` | CREATE | Projector tests. |
| `src/modules/experience360/surfaces/{kind}/__tests__/{kind}.policy.spec.ts` | CREATE | Policy/redaction tests. |
| `src/modules/experience360/surfaces/{kind}/__tests__/{kind}.golden.spec.ts` | CREATE | Golden-frame snapshot tests. |

### 4.3 Concrete surface directories

These directories are required:

```txt
src/modules/experience360/surfaces/agent/
src/modules/experience360/surfaces/execution/
src/modules/experience360/surfaces/episode/
src/modules/experience360/surfaces/profile/
src/modules/experience360/surfaces/identity/
src/modules/experience360/surfaces/journey/
src/modules/experience360/surfaces/communications/
src/modules/experience360/surfaces/risk/
src/modules/experience360/surfaces/value/
src/modules/experience360/surfaces/social/
src/modules/experience360/surfaces/campaign/
src/modules/experience360/surfaces/signals/
src/modules/experience360/surfaces/account/
src/modules/experience360/surfaces/location/
src/modules/experience360/surfaces/workflow/
src/modules/experience360/surfaces/memory/
src/modules/experience360/surfaces/commerce/
src/modules/experience360/surfaces/support/
```

## 5. Global backend contracts

### 5.1 `contracts/kinds.ts`

```ts
export const EXPERIENCE_360_KINDS = [
  "agent",
  "execution",
  "episode",
  "profile",
  "identity",
  "journey",
  "communications",
  "risk",
  "value",
  "social",
  "campaign",
  "signals",
  "account",
  "location",
  "workflow",
  "memory",
  "commerce",
  "support",
] as const;

export type Experience360Kind = (typeof EXPERIENCE_360_KINDS)[number];

export const LENS_KINDS = [
  "identity",
  "activity",
  "journey",
  "campaign",
  "signals",
  "communications",
  "agentic",
  "authority",
  "execution",
  "relationship",
  "social",
  "syndicate",
  "value",
  "attribution",
  "commerce",
  "product-offer",
  "location",
  "risk",
  "policy",
  "provenance",
  "workflow",
  "automation",
  "semantic-memory",
  "topic",
  "support",
] as const;

export type LensKind = (typeof LENS_KINDS)[number];

export type FrameState =
  | "ready"
  | "empty"
  | "degraded"
  | "policy_redacted"
  | "stale"
  | "error";

export type SlotState =
  | "ready"
  | "empty"
  | "missing"
  | "zero"
  | "degraded"
  | "redacted"
  | "stale"
  | "conflicted"
  | "unresolved"
  | "unknown"
  | "error";

export type DegradationReason =
  | "source_missing"
  | "source_empty"
  | "policy_redacted"
  | "stale_projection"
  | "partial_identity"
  | "conflicting_evidence"
  | "resolver_timeout"
  | "projection_error"
  | "feature_disabled"
  | "permission_denied";
```

### 5.2 `contracts/evidence.ts`

```ts
import type { Experience360Kind, LensKind } from "./kinds";

export type EvidenceConfidence = "low" | "medium" | "high" | "verified";
export type EvidenceQuality = "raw" | "normalized" | "resolved" | "derived" | "generated";

export type EvidenceRef = {
  id: string;
  tenantId: string;
  sourceSystem: string;
  sourceType:
    | "sdk"
    | "webhook"
    | "connector"
    | "import"
    | "api"
    | "manual"
    | "agent_trace"
    | "execution_trace"
    | "communication"
    | "attribution"
    | "risk_signal";
  sourceRecordId: string;
  observedAt: string;
  ingestedAt: string;
  quality: EvidenceQuality;
  confidence: EvidenceConfidence;
  lens?: LensKind;
  surface?: Experience360Kind;
  redacted?: boolean;
  redactionReason?: string;
};

export type EvidenceTrace = {
  refs: EvidenceRef[];
  primaryRefIds: string[];
  conflictingRefIds: string[];
  generatedSummaryRefIds: string[];
  confidence: EvidenceConfidence;
  notes?: string[];
};
```

### 5.3 `contracts/policy.ts`

```ts
export type PolicyScope =
  | "tenant_admin"
  | "operator"
  | "analyst"
  | "finance"
  | "security"
  | "support"
  | "developer"
  | "viewer";

export type RedactionKind =
  | "none"
  | "mask"
  | "hash"
  | "aggregate"
  | "metadata_only"
  | "omit"
  | "deny";

export type PolicyDecision = {
  allowed: boolean;
  redaction: RedactionKind;
  reason?: string;
  fields?: string[];
};

export type PolicyEnvelope = {
  subjectPolicyKey: string;
  requestedScopes: PolicyScope[];
  appliedScopes: PolicyScope[];
  decisions: Record<string, PolicyDecision>;
  redactedFieldCount: number;
  redactedSlotCount: number;
  auditId: string;
};
```

### 5.4 `contracts/freshness.ts`

```ts
import type { DegradationReason } from "./kinds";

export type FreshnessGrade = "fresh" | "acceptable" | "stale" | "unknown";

export type FreshnessEnvelope = {
  grade: FreshnessGrade;
  resolvedAt: string;
  asOf: string;
  maxSourceObservedAt?: string;
  maxSourceIngestedAt?: string;
  staleAfterMs: number;
  projectionAgeMs?: number;
  cacheHit: boolean;
  degradationReasons: DegradationReason[];
};
```

### 5.5 `contracts/lens.ts`

```ts
import type { LensKind } from "./kinds";
import type { EvidenceTrace } from "./evidence";

export type LensContext = {
  requested: LensKind[];
  applied: LensKind[];
  omitted: Array<{ lens: LensKind; reason: string }>;
  hash: string;
};

export type LensResult<TData = unknown> = {
  lens: LensKind;
  tenantId: string;
  subjectId: string;
  asOf: string;
  data: TData;
  evidence: EvidenceTrace;
  stale: boolean;
  confidence: "low" | "medium" | "high" | "verified";
};
```

### 5.6 `contracts/slot.ts`

```ts
import type { SlotState } from "./kinds";
import type { EvidenceTrace } from "./evidence";

export type Experience360Slot<TData = unknown> = {
  key: string;
  label: string;
  state: SlotState;
  data: TData | null;
  evidence: EvidenceTrace;
  errors: Array<{ code: string; message: string }>;
  warnings: Array<{ code: string; message: string }>;
  diagnostics?: Record<string, unknown>;
};
```

### 5.7 `contracts/frame.ts`

```ts
import type { Experience360Kind, FrameState } from "./kinds";
import type { Experience360Slot } from "./slot";
import type { EvidenceTrace } from "./evidence";
import type { FreshnessEnvelope } from "./freshness";
import type { LensContext } from "./lens";
import type { PolicyEnvelope } from "./policy";

export type Experience360Subject = {
  subjectId: string;
  subjectType: string;
  canonicalRef?: {
    subsystem: string;
    id: string;
  };
};

export type GraphEdgeRef = {
  edgeId: string;
  edgeType: string;
  from: Experience360Subject;
  to: Experience360Subject;
  confidence: "low" | "medium" | "high" | "verified";
  evidenceRefIds: string[];
};

export type Recommendation = {
  id: string;
  type: string;
  label: string;
  rationale: string;
  confidence: "low" | "medium" | "high" | "verified";
  evidenceRefIds: string[];
};

export type ActionIntent = {
  id: string;
  type: string;
  label: string;
  requiresConfirmation: boolean;
  requiresPermission: string[];
  payloadPreview: Record<string, unknown>;
  evidenceRefIds: string[];
};

export type FrameDiagnostics = {
  resolverMs: number;
  projectorMs: number;
  policyMs: number;
  cacheKey: string;
  cacheHit: boolean;
  sourceCounts: Record<string, number>;
  slotStates: Record<string, string>;
};

export type Experience360Frame<TSlots extends Record<string, Experience360Slot> = Record<string, Experience360Slot>> = {
  kind: Experience360Kind;
  frameId: string;
  tenantId: string;
  subject: Experience360Subject;
  state: FrameState;
  asOf: string;
  resolvedAt: string;
  lensContext: LensContext;
  policy: PolicyEnvelope;
  freshness: FreshnessEnvelope;
  summary: {
    title: string;
    description: string;
    confidence: "low" | "medium" | "high" | "verified";
    warnings: string[];
  };
  slots: TSlots;
  graphEdges: GraphEdgeRef[];
  recommendations: Recommendation[];
  actionIntents: ActionIntent[];
  evidence: EvidenceTrace;
  diagnostics?: FrameDiagnostics;
};
```

## 6. Registry contract

### 6.1 `registry/experience360.registry.schema.ts`

```ts
import type { Experience360Kind, LensKind } from "../contracts/kinds";

export type CacheStrategy = "none" | "tenant" | "subject" | "lens" | "policy_lens_subject";

export type Experience360RegistryEntry = {
  kind: Experience360Kind;
  label: string;
  priority: "P0" | "P1" | "P2";
  canonicalOwner: string;
  route: `/api/360/${string}/${string}`;
  subjectTypes: string[];
  requiredLenses: LensKind[];
  optionalLenses: LensKind[];
  requiredSlots: string[];
  optionalSlots: string[];
  resolverPath: string;
  projectorPath: string;
  policyPath: string;
  fixturePath: string;
  goldenFramePath: string;
  featureFlag: string;
  freshnessSlaMs: number;
  cacheStrategy: CacheStrategy;
  directCanonicalWritesAllowed: false;
  tests: string[];
};
```

### 6.2 Required registry entries

`registry/experience360.registry.ts` must export one entry per surface below.

| Kind | Priority | Canonical owner | Required lenses | Required slots |
|---|---:|---|---|---|
| `agent` | P0 | `agent_identity_authority` | identity, agentic, authority, execution, risk, relationship, policy, provenance | `identity`, `owner_delegator`, `authority_envelope`, `delegation_chain`, `capabilities`, `execution_history`, `spawned_agents`, `tool_usage`, `policy_boundary`, `risk_summary`, `evidence_trace` |
| `execution` | P0 | `execution_runtime` | execution, authority, agentic, identity, policy, risk, provenance, value | `execution_summary`, `actor_attribution`, `plan_steps`, `tool_calls`, `approval_chain`, `authority_check`, `inputs_outputs`, `latency_cost`, `failures`, `risk_events`, `evidence_trace` |
| `episode` | P0 | `journey_event_reconstruction` | activity, journey, communications, campaign, identity, location, risk, provenance | `episode_summary`, `timeline`, `participants`, `sessions`, `touchpoints`, `communications`, `agent_handoffs`, `conversion_events`, `attribution_links`, `risk_flags`, `evidence_trace` |
| `profile` | P0 | `identity_profile` | identity, journey, communications, agentic, relationship, value, risk, location, campaign, provenance | `identity_spine`, `known_unknown_resolution`, `session_history`, `journey_participation`, `agent_delegations`, `communications`, `syndicates`, `relationships`, `value_summary`, `risk_summary`, `location_temporal`, `likely_next_states`, `evidence_trace` |
| `identity` | P0 | `identity_resolution` | identity, provenance, policy, risk, location | `identifier_inventory`, `namespace_map`, `match_evidence`, `conflicts`, `confidence`, `aliases`, `devices_sessions`, `wallets`, `policy_redactions`, `evidence_trace` |
| `journey` | P0 | `journey_graph` | journey, activity, campaign, communications, value, identity, agentic, location, risk | `journey_summary`, `stages`, `episodes`, `touchpoints`, `agent_interventions`, `communications`, `dropoffs`, `conversions`, `attribution`, `recommended_actions`, `evidence_trace` |
| `communications` | P0 | `communications_graph` | communications, identity, campaign, journey, risk, policy, provenance | `thread_summary`, `message_inventory`, `participants`, `campaign_links`, `profile_links`, `journey_links`, `response_events`, `agent_authorship`, `policy_state`, `risk_flags`, `evidence_trace` |
| `risk` | P0 | `risk_trust_safety` | risk, provenance, policy, identity, relationship, social, value, agentic, communications | `risk_summary`, `anomaly_events`, `policy_flags`, `poisoning_evidence`, `source_trust`, `propagation_paths`, `financial_contagion`, `social_contagion`, `agent_amplification`, `interventions`, `audit_history`, `evidence_trace` |
| `value` | P0 | `value_attribution` | value, attribution, campaign, identity, journey, commerce, risk, provenance | `value_summary`, `web2_value`, `web3_value`, `conversion_inventory`, `attribution_credits`, `revenue_events`, `ltv`, `reconciliation`, `financial_risk`, `confidence`, `evidence_trace` |
| `social` | P0 | `relationship_social_graph` | relationship, social, syndicate, identity, risk, communications, value, provenance | `relationship_map`, `multi_hop_paths`, `syndicates`, `communities`, `influence_paths`, `propagation`, `social_contagion`, `trust_edges`, `risk_edges`, `evidence_trace` |
| `campaign` | P1 | `campaign_resolution` | campaign, signals, journey, attribution, value, communications, risk, provenance | `campaign_identity`, `source_classification`, `signal_sources`, `touchpoints`, `journeys`, `conversions`, `attribution`, `cohorts_syndicates`, `performance`, `anomalies`, `evidence_trace` |
| `signals` | P1 | `signal_event_intake` | event-signal, provenance, campaign, identity, risk, location, policy | `signal_summary`, `source_inventory`, `classification`, `quality`, `normalization`, `linked_entities`, `campaign_links`, `risk_flags`, `freshness`, `evidence_trace` |
| `account` | P1 | `account_organization_graph` | account, identity, relationship, journey, value, communications, risk, policy | `account_summary`, `members`, `profiles`, `relationships`, `journeys`, `communications`, `value`, `risk`, `agents`, `contracts`, `evidence_trace` |
| `location` | P1 | `geo_temporal_graph` | location, identity, journey, signals, campaign, value, risk, provenance | `place_summary`, `geo_hierarchy`, `timezone`, `activity_density`, `journeys`, `campaigns`, `profiles`, `value`, `risk`, `normalization`, `evidence_trace` |
| `workflow` | P1 | `workflow_automation_runtime` | workflow, automation, execution, agentic, policy, identity, risk, value | `workflow_summary`, `triggers`, `runs`, `actors`, `approvals`, `agent_steps`, `actions`, `failures`, `outcomes`, `risk`, `evidence_trace` |
| `memory` | P2 | `semantic_memory_graph` | semantic-memory, topic, identity, provenance, risk, policy | `semantic_summary`, `memories`, `cards`, `topics`, `embeddings_meta`, `source_links`, `decay`, `conflicts`, `policy_state`, `evidence_trace` |
| `commerce` | P2 | `commerce_product_offer_graph` | commerce, product-offer, campaign, journey, value, identity, risk, provenance | `product_offer_summary`, `catalog_links`, `exposures`, `intent`, `cart_checkout`, `purchase`, `availability_price`, `campaign_links`, `value`, `risk`, `evidence_trace` |
| `support` | P2 | `support_callback_graph` | support, communications, journey, identity, risk, workflow, policy | `case_summary`, `conversation_history`, `callbacks`, `participants`, `sla`, `journey_links`, `agents`, `risk`, `resolution`, `evidence_trace` |

### 6.3 Registry acceptance rules

The registry test must fail if any surface lacks:

1. Registry entry.
2. Resolver file.
3. Projector file.
4. Policy file.
5. Schema file.
6. Fixture file.
7. Golden frame.
8. Resolver test.
9. Projector test.
10. Policy/redaction test.
11. Golden-frame snapshot test.
12. Feature flag.
13. Freshness SLA.
14. Required slot list.
15. Required lens list.
16. `directCanonicalWritesAllowed: false`.

Example test:

```ts
import { EXPERIENCE_360_REGISTRY } from "./experience360.registry";
import { EXPERIENCE_360_KINDS } from "../contracts/kinds";

it("registers every Experience 360 kind", () => {
  const registered = EXPERIENCE_360_REGISTRY.map((entry) => entry.kind).sort();
  expect(registered).toEqual([...EXPERIENCE_360_KINDS].sort());
});

it("forbids canonical writes from all 360 registry entries", () => {
  for (const entry of EXPERIENCE_360_REGISTRY) {
    expect(entry.directCanonicalWritesAllowed).toBe(false);
  }
});

it("requires backend implementation artifacts for every surface", () => {
  for (const entry of EXPERIENCE_360_REGISTRY) {
    expect(entry.resolverPath).toMatch(/resolver/);
    expect(entry.projectorPath).toMatch(/projector/);
    expect(entry.policyPath).toMatch(/policy/);
    expect(entry.fixturePath).toMatch(/fixture/);
    expect(entry.goldenFramePath).toMatch(/golden/);
    expect(entry.tests.length).toBeGreaterThanOrEqual(4);
  }
});
```

## 7. Backend request pipeline

Every 360 frame must be produced through this exact backend sequence:

```txt
1. Receive request
2. Validate tenant and authenticated principal
3. Validate kind and subjectId
4. Load registry entry
5. Resolve feature flag
6. Resolve requested policy scope
7. Build lens context
8. Build cache key
9. Attempt frame cache read
10. Load canonical fragments through resolver
11. Load lens results
12. Project frame slots
13. Compute freshness and degradation
14. Build evidence trace
15. Apply policy and field redaction
16. Emit diagnostics and policy audit
17. Write cache/snapshot when allowed
18. Return Experience360Frame
```

### 7.1 `services/frame.service.ts`

```ts
import type { Experience360Frame } from "../contracts/frame";
import type { Experience360Kind } from "../contracts/kinds";

export type ResolveFrameInput = {
  tenantId: string;
  principalId: string;
  principalScopes: string[];
  kind: Experience360Kind;
  subjectId: string;
  asOf?: string;
  requestedLenses?: string[];
  includeEvidence?: boolean;
  includeDiagnostics?: boolean;
};

export async function resolveExperience360Frame(
  input: ResolveFrameInput,
): Promise<Experience360Frame> {
  const registryEntry = await loadRegistryEntry(input.kind);
  await assertFeatureEnabled(registryEntry.featureFlag, input.tenantId);

  const policyContext = await resolvePolicyContext(input);
  const lensContext = await resolveLensContext(input, registryEntry);
  const cacheKey = buildFrameCacheKey(input, lensContext, policyContext);

  const cached = await readFrameCache(cacheKey);
  if (cached) return cached;

  const fragments = await registryEntry.resolver.resolve({
    tenantId: input.tenantId,
    subjectId: input.subjectId,
    asOf: input.asOf,
    lensContext,
    policyContext,
  });

  const projected = await registryEntry.projector.project({
    input,
    fragments,
    lensContext,
  });

  const withFreshness = await applyFreshness(projected, registryEntry);
  const withEvidence = await attachEvidenceTrace(withFreshness, fragments);
  const filtered = await applyPolicyFilter(withEvidence, policyContext);

  await emitExperience360Diagnostics(filtered);
  await writePolicyAudit(filtered);
  await writeFrameCache(cacheKey, filtered, registryEntry);

  return filtered;
}
```

The actual implementation can use classes or dependency injection. The invariant is that every surface must run through the same orchestration pipeline.

## 8. Backend API contract

### 8.1 Frame endpoint

```txt
GET /api/360/:kind/:subjectId
```

Query parameters:

| Param | Required | Meaning |
|---|---:|---|
| `tenantId` | yes | Tenant boundary. |
| `asOf` | no | ISO timestamp for historical projection. |
| `lenses` | no | Comma-separated requested lenses. |
| `includeEvidence` | no | Include full evidence trace when authorized. |
| `includeDiagnostics` | no | Include resolver/projector/cache timings when authorized. |
| `snapshotId` | no | Read from a known snapshot instead of live projection. |

Response:

```ts
Experience360Frame
```

Failure responses:

| Status | Code | Meaning |
|---:|---|---|
| 400 | `INVALID_KIND` | Kind is not registered. |
| 400 | `INVALID_SUBJECT` | Subject ID or type is invalid. |
| 401 | `UNAUTHENTICATED` | No authenticated principal. |
| 403 | `POLICY_DENIED` | Principal cannot access this frame. |
| 404 | `SUBJECT_NOT_FOUND` | Subject not found in canonical source. |
| 409 | `CONFLICTED_EVIDENCE` | Conflicts require explicit review. |
| 422 | `UNRESOLVED_IDENTITY` | Identity requirement cannot be satisfied. |
| 503 | `PROJECTION_UNAVAILABLE` | Resolver or lens dependency is unavailable. |

### 8.2 Registry endpoint

```txt
GET /api/360/registry
```

Returns enabled surfaces for the tenant and principal scope. It must not return surfaces disabled by feature flag or hidden by policy.

### 8.3 Evidence endpoint

```txt
GET /api/360/:kind/:subjectId/evidence
```

Returns evidence refs for a frame. This endpoint must apply stricter policy filtering than the frame endpoint because evidence can expose source-specific details.

### 8.4 Snapshot endpoint

```txt
POST /api/360/:kind/:subjectId/snapshot
GET /api/360/:kind/:subjectId/snapshot/:snapshotId
```

Snapshot writes are allowed because snapshots are read-model artifacts. Snapshot writes must not mutate canonical subsystem state.

## 9. Persistence and migrations

### 9.1 Migration sequence

Run migrations in this order:

```txt
001_create_experience360_registry.sql
002_create_experience360_snapshots.sql
003_create_lens_projection_index.sql
004_create_evidence_trace.sql
005_create_policy_audit.sql
006_create_agent_authority_edges.sql
007_create_risk_poisoning_evidence.sql
008_create_risk_contagion_paths.sql
009_create_value_projection_views.sql
010_backfill_initial_experience360_snapshots.sql
```

### 9.2 Core tables

```sql
CREATE TABLE IF NOT EXISTS experience360_snapshots (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  lens_hash TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  as_of TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP NOT NULL,
  frame_json JSONB NOT NULL,
  evidence_ref_ids TEXT[] NOT NULL DEFAULT '{}',
  freshness_grade TEXT NOT NULL,
  frame_state TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experience360_snapshots_lookup
  ON experience360_snapshots (tenant_id, kind, subject_id, lens_hash, policy_hash, as_of DESC);
```

```sql
CREATE TABLE IF NOT EXISTS experience360_evidence_trace (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  frame_id TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  observed_at TIMESTAMP,
  ingested_at TIMESTAMP,
  quality TEXT NOT NULL,
  confidence TEXT NOT NULL,
  redacted BOOLEAN NOT NULL DEFAULT FALSE,
  redaction_reason TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experience360_evidence_trace_frame
  ON experience360_evidence_trace (tenant_id, frame_id);
```

```sql
CREATE TABLE IF NOT EXISTS experience360_policy_audit (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  requested_scopes TEXT[] NOT NULL,
  applied_scopes TEXT[] NOT NULL,
  redacted_field_count INTEGER NOT NULL DEFAULT 0,
  redacted_slot_count INTEGER NOT NULL DEFAULT 0,
  denied BOOLEAN NOT NULL DEFAULT FALSE,
  reason TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### 9.3 Agent authority tables

```sql
CREATE TABLE IF NOT EXISTS agent_authority_edges (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  delegator_subject_id TEXT NOT NULL,
  delegated_subject_id TEXT,
  authority_type TEXT NOT NULL,
  scope TEXT[] NOT NULL DEFAULT '{}',
  source_record_id TEXT NOT NULL,
  starts_at TIMESTAMP,
  expires_at TIMESTAMP,
  revoked_at TIMESTAMP,
  confidence TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_authority_edges_agent
  ON agent_authority_edges (tenant_id, agent_id, starts_at DESC);
```

### 9.4 Poisoning and contagion tables

```sql
CREATE TABLE IF NOT EXISTS risk_poisoning_evidence (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  subject_id TEXT,
  kind TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  signal_strength NUMERIC NOT NULL,
  confidence TEXT NOT NULL,
  suspected_payload_hash TEXT,
  source_record_id TEXT NOT NULL,
  first_seen_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_poisoning_source
  ON risk_poisoning_evidence (tenant_id, source_id, last_seen_at DESC);
```

```sql
CREATE TABLE IF NOT EXISTS risk_contagion_paths (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  contagion_type TEXT NOT NULL,
  origin_subject_id TEXT NOT NULL,
  affected_subject_id TEXT NOT NULL,
  path JSONB NOT NULL,
  propagation_score NUMERIC NOT NULL,
  financial_exposure NUMERIC,
  social_exposure NUMERIC,
  agent_amplification_score NUMERIC,
  confidence TEXT NOT NULL,
  evidence_ref_ids TEXT[] NOT NULL DEFAULT '{}',
  first_seen_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_risk_contagion_affected
  ON risk_contagion_paths (tenant_id, affected_subject_id, last_seen_at DESC);
```

### 9.5 Migration validation queries

Each migration must include a validation query. Minimum validation set:

```sql
SELECT COUNT(*) FROM experience360_snapshots;
SELECT COUNT(*) FROM experience360_evidence_trace;
SELECT COUNT(*) FROM experience360_policy_audit;
SELECT COUNT(*) FROM agent_authority_edges;
SELECT COUNT(*) FROM risk_poisoning_evidence;
SELECT COUNT(*) FROM risk_contagion_paths;
```

Backfill validation must prove:

1. Every enabled tenant has registry-visible surfaces.
2. Every backfilled frame has a frame ID.
3. Every frame has a tenant ID.
4. Every frame has a policy envelope.
5. Every frame has a freshness envelope.
6. Every non-empty frame has at least one evidence ref.
7. No frame contains unredacted restricted data under a restricted principal scope.

## 10. Lens subsystem integration

The 360 module depends on lenses but does not own canonical lens data. Lenses produce reusable projections that surfaces compose.

### 10.1 Required backend lens adapters

Create adapters under:

```txt
src/modules/experience360/lenses/
```

Required files:

| File | Purpose |
|---|---|
| `lens-adapter.ts` | Common adapter interface. |
| `identity.adapter.ts` | Known/unknown identity, identifiers, conflicts. |
| `activity.adapter.ts` | Events, sessions, activity windows. |
| `journey.adapter.ts` | Journeys, stages, episodes, touchpoints. |
| `campaign.adapter.ts` | Campaign identity and campaign links. |
| `signals.adapter.ts` | Raw/normalized event and signal records. |
| `communications.adapter.ts` | Messages, threads, campaign communications. |
| `agentic.adapter.ts` | Agent lifecycle, agent ownership, delegation. |
| `authority.adapter.ts` | Permissions, approval, delegated authority. |
| `execution.adapter.ts` | Runs, commands, tool calls, outputs. |
| `relationship.adapter.ts` | Relationship edges and multi-hop graph paths. |
| `value.adapter.ts` | Revenue, conversion, attribution, Web3 value. |
| `risk.adapter.ts` | Risk events, anomaly, poisoning, contagion. |
| `location.adapter.ts` | Geo/timezone/place normalization. |
| `policy.adapter.ts` | Field scopes and redaction decisions. |
| `provenance.adapter.ts` | Source lineage and confidence. |
| `workflow.adapter.ts` | Workflow/automation definitions and runs. |
| `semantic-memory.adapter.ts` | Memory, semantic cards, topic context. |
| `commerce.adapter.ts` | Product, offer, cart, checkout, purchase. |
| `support.adapter.ts` | Cases, callbacks, conversations, SLA. |

### 10.2 Lens adapter interface

```ts
import type { LensKind } from "../contracts/kinds";
import type { LensResult } from "../contracts/lens";

export type LensAdapterInput = {
  tenantId: string;
  subjectId: string;
  subjectType: string;
  asOf?: string;
  policyContext: unknown;
};

export type LensAdapter<TData = unknown> = {
  kind: LensKind;
  resolve(input: LensAdapterInput): Promise<LensResult<TData>>;
};
```

### 10.3 Lens composition rules

1. Required lenses must either resolve or mark the frame degraded.
2. Optional lenses may fail without failing the frame.
3. A failed optional lens must create a warning.
4. Lens results must include evidence.
5. Lens result freshness contributes to frame freshness.
6. Lenses must not expose data beyond policy scope.

## 11. Surface-by-surface backend implementation

Each surface below must be implemented with the same backend structure:

```txt
src/modules/experience360/surfaces/{kind}/
  schema/{kind}.schema.ts
  contracts/{kind}.contracts.ts
  resolver/{kind}.resolver.ts
  projector/{kind}.projector.ts
  policy/{kind}.policy.ts
  freshness/{kind}.freshness.ts
  evidence/{kind}.evidence.ts
  fixture/{kind}.fixture.ts
  golden/{kind}.golden.json
  __tests__/{kind}.resolver.spec.ts
  __tests__/{kind}.projector.spec.ts
  __tests__/{kind}.policy.spec.ts
  __tests__/{kind}.golden.spec.ts
```

### 11.1 Agent 360 — `agent`

**Priority:** P0<br>
**Canonical owner:** `agent_identity_authority`<br>
**Subjects:** agent_id, delegated_agent_id, spawned_agent_id, tool_agent_id<br>
**Required lenses:** identity, agentic, authority, execution, risk, relationship, policy, provenance<br>
**Purpose:** Builds the governed read model for an autonomous or delegated agent, including ownership, authority, lifecycle, executions, and risk evidence.

**Required slots:**

- `identity`
- `owner_delegator`
- `authority_envelope`
- `delegation_chain`
- `capabilities`
- `execution_history`
- `spawned_agents`
- `tool_usage`
- `policy_boundary`
- `risk_summary`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/agent/schema/agent.schema.ts
src/modules/experience360/surfaces/agent/contracts/agent.contracts.ts
src/modules/experience360/surfaces/agent/resolver/agent.resolver.ts
src/modules/experience360/surfaces/agent/projector/agent.projector.ts
src/modules/experience360/surfaces/agent/policy/agent.policy.ts
src/modules/experience360/surfaces/agent/freshness/agent.freshness.ts
src/modules/experience360/surfaces/agent/evidence/agent.evidence.ts
src/modules/experience360/surfaces/agent/fixture/agent.fixture.ts
src/modules/experience360/surfaces/agent/golden/agent.golden.json
src/modules/experience360/surfaces/agent/__tests__/agent.resolver.spec.ts
src/modules/experience360/surfaces/agent/__tests__/agent.projector.spec.ts
src/modules/experience360/surfaces/agent/__tests__/agent.policy.spec.ts
src/modules/experience360/surfaces/agent/__tests__/agent.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "agent"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not infer personhood, biometric identity, or full authorization from user-agent strings, SDK presence, or tool use alone. Authority must come from explicit delegation, credential, policy, or audit evidence.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.2 Execution 360 — `execution`

**Priority:** P0<br>
**Canonical owner:** `execution_runtime`<br>
**Subjects:** execution_id, run_id, workflow_run_id, tool_call_id, command_id<br>
**Required lenses:** execution, authority, agentic, identity, policy, risk, provenance, value<br>
**Purpose:** Reconstructs who or what drove a backend action, what authority existed, what tools were used, and what outputs or failures occurred.

**Required slots:**

- `execution_summary`
- `actor_attribution`
- `plan_steps`
- `tool_calls`
- `approval_chain`
- `authority_check`
- `inputs_outputs`
- `latency_cost`
- `failures`
- `risk_events`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/execution/schema/execution.schema.ts
src/modules/experience360/surfaces/execution/contracts/execution.contracts.ts
src/modules/experience360/surfaces/execution/resolver/execution.resolver.ts
src/modules/experience360/surfaces/execution/projector/execution.projector.ts
src/modules/experience360/surfaces/execution/policy/execution.policy.ts
src/modules/experience360/surfaces/execution/freshness/execution.freshness.ts
src/modules/experience360/surfaces/execution/evidence/execution.evidence.ts
src/modules/experience360/surfaces/execution/fixture/execution.fixture.ts
src/modules/experience360/surfaces/execution/golden/execution.golden.json
src/modules/experience360/surfaces/execution/__tests__/execution.resolver.spec.ts
src/modules/experience360/surfaces/execution/__tests__/execution.projector.spec.ts
src/modules/experience360/surfaces/execution/__tests__/execution.policy.spec.ts
src/modules/experience360/surfaces/execution/__tests__/execution.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "execution"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not treat an execution as agent-driven or human-driven without actor attribution evidence and confidence bounds.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.3 Episode 360 — `episode`

**Priority:** P0<br>
**Canonical owner:** `journey_event_reconstruction`<br>
**Subjects:** episode_id, session_id, conversation_id, activity_window_id<br>
**Required lenses:** activity, journey, communications, campaign, identity, location, risk, provenance<br>
**Purpose:** Provides the backend reconstruction of a bounded session/activity narrative across humans, agents, communications, and outcomes.

**Required slots:**

- `episode_summary`
- `timeline`
- `participants`
- `sessions`
- `touchpoints`
- `communications`
- `agent_handoffs`
- `conversion_events`
- `attribution_links`
- `risk_flags`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/episode/schema/episode.schema.ts
src/modules/experience360/surfaces/episode/contracts/episode.contracts.ts
src/modules/experience360/surfaces/episode/resolver/episode.resolver.ts
src/modules/experience360/surfaces/episode/projector/episode.projector.ts
src/modules/experience360/surfaces/episode/policy/episode.policy.ts
src/modules/experience360/surfaces/episode/freshness/episode.freshness.ts
src/modules/experience360/surfaces/episode/evidence/episode.evidence.ts
src/modules/experience360/surfaces/episode/fixture/episode.fixture.ts
src/modules/experience360/surfaces/episode/golden/episode.golden.json
src/modules/experience360/surfaces/episode/__tests__/episode.resolver.spec.ts
src/modules/experience360/surfaces/episode/__tests__/episode.projector.spec.ts
src/modules/experience360/surfaces/episode/__tests__/episode.policy.spec.ts
src/modules/experience360/surfaces/episode/__tests__/episode.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "episode"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not collapse journey touchpoints and attribution touchpoints; both must remain separately represented.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.4 Profile 360 — `profile`

**Priority:** P0<br>
**Canonical owner:** `identity_profile`<br>
**Subjects:** profile_id, person_id, anonymous_subject_id, account_member_id, wallet_cluster_id<br>
**Required lenses:** identity, journey, communications, agentic, relationship, value, risk, location, campaign, provenance<br>
**Purpose:** Builds the backend read model for who a human or agent-associated profile has been, is now, and is likely to become across identity, sessions, journeys, agents, communications, value, and risk.

**Required slots:**

- `identity_spine`
- `known_unknown_resolution`
- `session_history`
- `journey_participation`
- `agent_delegations`
- `communications`
- `syndicates`
- `relationships`
- `value_summary`
- `risk_summary`
- `location_temporal`
- `likely_next_states`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/profile/schema/profile.schema.ts
src/modules/experience360/surfaces/profile/contracts/profile.contracts.ts
src/modules/experience360/surfaces/profile/resolver/profile.resolver.ts
src/modules/experience360/surfaces/profile/projector/profile.projector.ts
src/modules/experience360/surfaces/profile/policy/profile.policy.ts
src/modules/experience360/surfaces/profile/freshness/profile.freshness.ts
src/modules/experience360/surfaces/profile/evidence/profile.evidence.ts
src/modules/experience360/surfaces/profile/fixture/profile.fixture.ts
src/modules/experience360/surfaces/profile/golden/profile.golden.json
src/modules/experience360/surfaces/profile/__tests__/profile.resolver.spec.ts
src/modules/experience360/surfaces/profile/__tests__/profile.projector.spec.ts
src/modules/experience360/surfaces/profile/__tests__/profile.policy.spec.ts
src/modules/experience360/surfaces/profile/__tests__/profile.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "profile"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not overwrite canonical identity or merge profiles from this surface. Profile 360 may recommend review, not perform identity mutation.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.5 Identity 360 — `identity`

**Priority:** P0<br>
**Canonical owner:** `identity_resolution`<br>
**Subjects:** identity_id, profile_id, identifier_id, namespace_id, wallet_id, device_id<br>
**Required lenses:** identity, provenance, policy, risk, location<br>
**Purpose:** Surfaces identity stitching state and evidence while preserving known, unknown, partial, conflict, and degraded identity conditions.

**Required slots:**

- `identifier_inventory`
- `namespace_map`
- `match_evidence`
- `conflicts`
- `confidence`
- `aliases`
- `devices_sessions`
- `wallets`
- `policy_redactions`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/identity/schema/identity.schema.ts
src/modules/experience360/surfaces/identity/contracts/identity.contracts.ts
src/modules/experience360/surfaces/identity/resolver/identity.resolver.ts
src/modules/experience360/surfaces/identity/projector/identity.projector.ts
src/modules/experience360/surfaces/identity/policy/identity.policy.ts
src/modules/experience360/surfaces/identity/freshness/identity.freshness.ts
src/modules/experience360/surfaces/identity/evidence/identity.evidence.ts
src/modules/experience360/surfaces/identity/fixture/identity.fixture.ts
src/modules/experience360/surfaces/identity/golden/identity.golden.json
src/modules/experience360/surfaces/identity/__tests__/identity.resolver.spec.ts
src/modules/experience360/surfaces/identity/__tests__/identity.projector.spec.ts
src/modules/experience360/surfaces/identity/__tests__/identity.policy.spec.ts
src/modules/experience360/surfaces/identity/__tests__/identity.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "identity"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not treat absence of identity as zero identity. Unknown, anonymous, unresolved, and policy-redacted states must remain distinct.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.6 Journey 360 — `journey`

**Priority:** P0<br>
**Canonical owner:** `journey_graph`<br>
**Subjects:** journey_id, profile_id, account_id, campaign_id, episode_id<br>
**Required lenses:** journey, activity, campaign, communications, value, identity, agentic, location, risk<br>
**Purpose:** Composes cross-session journeys while maintaining boundaries between events, touchpoints, conversions, and immutable attribution credits.

**Required slots:**

- `journey_summary`
- `stages`
- `episodes`
- `touchpoints`
- `agent_interventions`
- `communications`
- `dropoffs`
- `conversions`
- `attribution`
- `recommended_actions`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/journey/schema/journey.schema.ts
src/modules/experience360/surfaces/journey/contracts/journey.contracts.ts
src/modules/experience360/surfaces/journey/resolver/journey.resolver.ts
src/modules/experience360/surfaces/journey/projector/journey.projector.ts
src/modules/experience360/surfaces/journey/policy/journey.policy.ts
src/modules/experience360/surfaces/journey/freshness/journey.freshness.ts
src/modules/experience360/surfaces/journey/evidence/journey.evidence.ts
src/modules/experience360/surfaces/journey/fixture/journey.fixture.ts
src/modules/experience360/surfaces/journey/golden/journey.golden.json
src/modules/experience360/surfaces/journey/__tests__/journey.resolver.spec.ts
src/modules/experience360/surfaces/journey/__tests__/journey.projector.spec.ts
src/modules/experience360/surfaces/journey/__tests__/journey.policy.spec.ts
src/modules/experience360/surfaces/journey/__tests__/journey.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "journey"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not mutate attribution credits from Journey 360. It reads immutable credits and can propose reconciliation work only.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.7 Communications 360 — `communications`

**Priority:** P0<br>
**Canonical owner:** `communications_graph`<br>
**Subjects:** message_id, thread_id, profile_id, campaign_id, episode_id<br>
**Required lenses:** communications, identity, campaign, journey, risk, policy, provenance<br>
**Purpose:** Attaches email/message/campaign communications to profiles, journeys, campaigns, episodes, and agent/human authorship evidence.

**Required slots:**

- `thread_summary`
- `message_inventory`
- `participants`
- `campaign_links`
- `profile_links`
- `journey_links`
- `response_events`
- `agent_authorship`
- `policy_state`
- `risk_flags`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/communications/schema/communications.schema.ts
src/modules/experience360/surfaces/communications/contracts/communications.contracts.ts
src/modules/experience360/surfaces/communications/resolver/communications.resolver.ts
src/modules/experience360/surfaces/communications/projector/communications.projector.ts
src/modules/experience360/surfaces/communications/policy/communications.policy.ts
src/modules/experience360/surfaces/communications/freshness/communications.freshness.ts
src/modules/experience360/surfaces/communications/evidence/communications.evidence.ts
src/modules/experience360/surfaces/communications/fixture/communications.fixture.ts
src/modules/experience360/surfaces/communications/golden/communications.golden.json
src/modules/experience360/surfaces/communications/__tests__/communications.resolver.spec.ts
src/modules/experience360/surfaces/communications/__tests__/communications.projector.spec.ts
src/modules/experience360/surfaces/communications/__tests__/communications.policy.spec.ts
src/modules/experience360/surfaces/communications/__tests__/communications.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "communications"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not expose message body content unless permissions allow it; metadata-only fallback is required.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.8 Risk 360 — `risk`

**Priority:** P0<br>
**Canonical owner:** `risk_trust_safety`<br>
**Subjects:** risk_subject_id, profile_id, agent_id, account_id, source_id, campaign_id, contagion_path_id<br>
**Required lenses:** risk, provenance, policy, identity, relationship, social, value, agentic, communications<br>
**Purpose:** Summarizes trust, anomaly, poisoning, contagion, policy, social, financial, and agent-amplified risk without hiding evidence lineage.

**Required slots:**

- `risk_summary`
- `anomaly_events`
- `policy_flags`
- `poisoning_evidence`
- `source_trust`
- `propagation_paths`
- `financial_contagion`
- `social_contagion`
- `agent_amplification`
- `interventions`
- `audit_history`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/risk/schema/risk.schema.ts
src/modules/experience360/surfaces/risk/contracts/risk.contracts.ts
src/modules/experience360/surfaces/risk/resolver/risk.resolver.ts
src/modules/experience360/surfaces/risk/projector/risk.projector.ts
src/modules/experience360/surfaces/risk/policy/risk.policy.ts
src/modules/experience360/surfaces/risk/freshness/risk.freshness.ts
src/modules/experience360/surfaces/risk/evidence/risk.evidence.ts
src/modules/experience360/surfaces/risk/fixture/risk.fixture.ts
src/modules/experience360/surfaces/risk/golden/risk.golden.json
src/modules/experience360/surfaces/risk/__tests__/risk.resolver.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.projector.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.policy.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "risk"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not produce unexplained risk scores. Every risk output needs evidence refs, freshness, and confidence.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.9 Value 360 — `value`

**Priority:** P0<br>
**Canonical owner:** `value_attribution`<br>
**Subjects:** value_subject_id, profile_id, account_id, conversion_id, wallet_cluster_id, campaign_id<br>
**Required lenses:** value, attribution, campaign, identity, journey, commerce, risk, provenance<br>
**Purpose:** Normalizes Web2 and Web3 value, conversions, revenue, and attribution credits into a governed backend frame.

**Required slots:**

- `value_summary`
- `web2_value`
- `web3_value`
- `conversion_inventory`
- `attribution_credits`
- `revenue_events`
- `ltv`
- `reconciliation`
- `financial_risk`
- `confidence`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/value/schema/value.schema.ts
src/modules/experience360/surfaces/value/contracts/value.contracts.ts
src/modules/experience360/surfaces/value/resolver/value.resolver.ts
src/modules/experience360/surfaces/value/projector/value.projector.ts
src/modules/experience360/surfaces/value/policy/value.policy.ts
src/modules/experience360/surfaces/value/freshness/value.freshness.ts
src/modules/experience360/surfaces/value/evidence/value.evidence.ts
src/modules/experience360/surfaces/value/fixture/value.fixture.ts
src/modules/experience360/surfaces/value/golden/value.golden.json
src/modules/experience360/surfaces/value/__tests__/value.resolver.spec.ts
src/modules/experience360/surfaces/value/__tests__/value.projector.spec.ts
src/modules/experience360/surfaces/value/__tests__/value.policy.spec.ts
src/modules/experience360/surfaces/value/__tests__/value.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "value"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not call missing revenue zero. Missing, zero, redacted, stale, and unresolved value are separate states.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.10 Social 360 — `social`

**Priority:** P0<br>
**Canonical owner:** `relationship_social_graph`<br>
**Subjects:** social_subject_id, profile_id, community_id, syndicate_id, relationship_edge_id<br>
**Required lenses:** relationship, social, syndicate, identity, risk, communications, value, provenance<br>
**Purpose:** Surfaces relationship graph, syndicates, communities, multi-hop paths, influence, and social propagation evidence.

**Required slots:**

- `relationship_map`
- `multi_hop_paths`
- `syndicates`
- `communities`
- `influence_paths`
- `propagation`
- `social_contagion`
- `trust_edges`
- `risk_edges`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/social/schema/social.schema.ts
src/modules/experience360/surfaces/social/contracts/social.contracts.ts
src/modules/experience360/surfaces/social/resolver/social.resolver.ts
src/modules/experience360/surfaces/social/projector/social.projector.ts
src/modules/experience360/surfaces/social/policy/social.policy.ts
src/modules/experience360/surfaces/social/freshness/social.freshness.ts
src/modules/experience360/surfaces/social/evidence/social.evidence.ts
src/modules/experience360/surfaces/social/fixture/social.fixture.ts
src/modules/experience360/surfaces/social/golden/social.golden.json
src/modules/experience360/surfaces/social/__tests__/social.resolver.spec.ts
src/modules/experience360/surfaces/social/__tests__/social.projector.spec.ts
src/modules/experience360/surfaces/social/__tests__/social.policy.spec.ts
src/modules/experience360/surfaces/social/__tests__/social.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "social"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not expose private relationship edges outside policy scope; redacted edges must remain counted separately from nonexistent edges.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.11 Campaign 360 — `campaign`

**Priority:** P1<br>
**Canonical owner:** `campaign_resolution`<br>
**Subjects:** campaign_id, source_campaign_id, campaign_group_id<br>
**Required lenses:** campaign, signals, journey, attribution, value, communications, risk, provenance<br>
**Purpose:** Builds campaign state while preserving source classification versus campaign identity and attribution boundaries.

**Required slots:**

- `campaign_identity`
- `source_classification`
- `signal_sources`
- `touchpoints`
- `journeys`
- `conversions`
- `attribution`
- `cohorts_syndicates`
- `performance`
- `anomalies`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/campaign/schema/campaign.schema.ts
src/modules/experience360/surfaces/campaign/contracts/campaign.contracts.ts
src/modules/experience360/surfaces/campaign/resolver/campaign.resolver.ts
src/modules/experience360/surfaces/campaign/projector/campaign.projector.ts
src/modules/experience360/surfaces/campaign/policy/campaign.policy.ts
src/modules/experience360/surfaces/campaign/freshness/campaign.freshness.ts
src/modules/experience360/surfaces/campaign/evidence/campaign.evidence.ts
src/modules/experience360/surfaces/campaign/fixture/campaign.fixture.ts
src/modules/experience360/surfaces/campaign/golden/campaign.golden.json
src/modules/experience360/surfaces/campaign/__tests__/campaign.resolver.spec.ts
src/modules/experience360/surfaces/campaign/__tests__/campaign.projector.spec.ts
src/modules/experience360/surfaces/campaign/__tests__/campaign.policy.spec.ts
src/modules/experience360/surfaces/campaign/__tests__/campaign.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "campaign"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not merge source classification with canonical campaign identity.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.12 Signals 360 — `signals`

**Priority:** P1<br>
**Canonical owner:** `signal_event_intake`<br>
**Subjects:** signal_id, source_id, event_id, observation_id, stream_id<br>
**Required lenses:** event-signal, provenance, campaign, identity, risk, location, policy<br>
**Purpose:** Shows source events/signals, normalization quality, classification, lineage, and downstream graph links.

**Required slots:**

- `signal_summary`
- `source_inventory`
- `classification`
- `quality`
- `normalization`
- `linked_entities`
- `campaign_links`
- `risk_flags`
- `freshness`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/signals/schema/signals.schema.ts
src/modules/experience360/surfaces/signals/contracts/signals.contracts.ts
src/modules/experience360/surfaces/signals/resolver/signals.resolver.ts
src/modules/experience360/surfaces/signals/projector/signals.projector.ts
src/modules/experience360/surfaces/signals/policy/signals.policy.ts
src/modules/experience360/surfaces/signals/freshness/signals.freshness.ts
src/modules/experience360/surfaces/signals/evidence/signals.evidence.ts
src/modules/experience360/surfaces/signals/fixture/signals.fixture.ts
src/modules/experience360/surfaces/signals/golden/signals.golden.json
src/modules/experience360/surfaces/signals/__tests__/signals.resolver.spec.ts
src/modules/experience360/surfaces/signals/__tests__/signals.projector.spec.ts
src/modules/experience360/surfaces/signals/__tests__/signals.policy.spec.ts
src/modules/experience360/surfaces/signals/__tests__/signals.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "signals"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not use the deprecated Audience term or treat raw events as validated truth.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.13 Account 360 — `account`

**Priority:** P1<br>
**Canonical owner:** `account_organization_graph`<br>
**Subjects:** account_id, organization_id, workspace_id, tenant_customer_id<br>
**Required lenses:** account, identity, relationship, journey, value, communications, risk, policy<br>
**Purpose:** Aggregates organization/account-level state across members, profiles, journeys, communications, agents, value, and risk.

**Required slots:**

- `account_summary`
- `members`
- `profiles`
- `relationships`
- `journeys`
- `communications`
- `value`
- `risk`
- `agents`
- `contracts`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/account/schema/account.schema.ts
src/modules/experience360/surfaces/account/contracts/account.contracts.ts
src/modules/experience360/surfaces/account/resolver/account.resolver.ts
src/modules/experience360/surfaces/account/projector/account.projector.ts
src/modules/experience360/surfaces/account/policy/account.policy.ts
src/modules/experience360/surfaces/account/freshness/account.freshness.ts
src/modules/experience360/surfaces/account/evidence/account.evidence.ts
src/modules/experience360/surfaces/account/fixture/account.fixture.ts
src/modules/experience360/surfaces/account/golden/account.golden.json
src/modules/experience360/surfaces/account/__tests__/account.resolver.spec.ts
src/modules/experience360/surfaces/account/__tests__/account.projector.spec.ts
src/modules/experience360/surfaces/account/__tests__/account.policy.spec.ts
src/modules/experience360/surfaces/account/__tests__/account.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "account"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not use account aggregation to bypass profile-level policy redaction.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.14 Location / Place 360 — `location`

**Priority:** P1<br>
**Canonical owner:** `geo_temporal_graph`<br>
**Subjects:** location_id, place_id, geohash, timezone_id, region_id<br>
**Required lenses:** location, identity, journey, signals, campaign, value, risk, provenance<br>
**Purpose:** Normalizes place, geography, timezone, and activity projections without over-precise location exposure.

**Required slots:**

- `place_summary`
- `geo_hierarchy`
- `timezone`
- `activity_density`
- `journeys`
- `campaigns`
- `profiles`
- `value`
- `risk`
- `normalization`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/location/schema/location.schema.ts
src/modules/experience360/surfaces/location/contracts/location.contracts.ts
src/modules/experience360/surfaces/location/resolver/location.resolver.ts
src/modules/experience360/surfaces/location/projector/location.projector.ts
src/modules/experience360/surfaces/location/policy/location.policy.ts
src/modules/experience360/surfaces/location/freshness/location.freshness.ts
src/modules/experience360/surfaces/location/evidence/location.evidence.ts
src/modules/experience360/surfaces/location/fixture/location.fixture.ts
src/modules/experience360/surfaces/location/golden/location.golden.json
src/modules/experience360/surfaces/location/__tests__/location.resolver.spec.ts
src/modules/experience360/surfaces/location/__tests__/location.projector.spec.ts
src/modules/experience360/surfaces/location/__tests__/location.policy.spec.ts
src/modules/experience360/surfaces/location/__tests__/location.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "location"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not expose exact location if policy requires bucketing or approximation.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.15 Workflow / Automation 360 — `workflow`

**Priority:** P1<br>
**Canonical owner:** `workflow_automation_runtime`<br>
**Subjects:** workflow_id, automation_id, trigger_id, run_id<br>
**Required lenses:** workflow, automation, execution, agentic, policy, identity, risk, value<br>
**Purpose:** Surfaces workflow definitions, automation triggers, runs, approvals, actions, and agent/human authority boundaries.

**Required slots:**

- `workflow_summary`
- `triggers`
- `runs`
- `actors`
- `approvals`
- `agent_steps`
- `actions`
- `failures`
- `outcomes`
- `risk`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/workflow/schema/workflow.schema.ts
src/modules/experience360/surfaces/workflow/contracts/workflow.contracts.ts
src/modules/experience360/surfaces/workflow/resolver/workflow.resolver.ts
src/modules/experience360/surfaces/workflow/projector/workflow.projector.ts
src/modules/experience360/surfaces/workflow/policy/workflow.policy.ts
src/modules/experience360/surfaces/workflow/freshness/workflow.freshness.ts
src/modules/experience360/surfaces/workflow/evidence/workflow.evidence.ts
src/modules/experience360/surfaces/workflow/fixture/workflow.fixture.ts
src/modules/experience360/surfaces/workflow/golden/workflow.golden.json
src/modules/experience360/surfaces/workflow/__tests__/workflow.resolver.spec.ts
src/modules/experience360/surfaces/workflow/__tests__/workflow.projector.spec.ts
src/modules/experience360/surfaces/workflow/__tests__/workflow.policy.spec.ts
src/modules/experience360/surfaces/workflow/__tests__/workflow.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "workflow"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not execute workflow actions from read model endpoints. Return action intents only.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.16 Memory / Semantic / Card 360 — `memory`

**Priority:** P2<br>
**Canonical owner:** `semantic_memory_graph`<br>
**Subjects:** memory_id, semantic_entity_id, card_id, topic_id<br>
**Required lenses:** semantic-memory, topic, identity, provenance, risk, policy<br>
**Purpose:** Backs semantic memory, knowledge cards, topic context, provenance, freshness, and conflict handling.

**Required slots:**

- `semantic_summary`
- `memories`
- `cards`
- `topics`
- `embeddings_meta`
- `source_links`
- `decay`
- `conflicts`
- `policy_state`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/memory/schema/memory.schema.ts
src/modules/experience360/surfaces/memory/contracts/memory.contracts.ts
src/modules/experience360/surfaces/memory/resolver/memory.resolver.ts
src/modules/experience360/surfaces/memory/projector/memory.projector.ts
src/modules/experience360/surfaces/memory/policy/memory.policy.ts
src/modules/experience360/surfaces/memory/freshness/memory.freshness.ts
src/modules/experience360/surfaces/memory/evidence/memory.evidence.ts
src/modules/experience360/surfaces/memory/fixture/memory.fixture.ts
src/modules/experience360/surfaces/memory/golden/memory.golden.json
src/modules/experience360/surfaces/memory/__tests__/memory.resolver.spec.ts
src/modules/experience360/surfaces/memory/__tests__/memory.projector.spec.ts
src/modules/experience360/surfaces/memory/__tests__/memory.policy.spec.ts
src/modules/experience360/surfaces/memory/__tests__/memory.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "memory"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not treat generated summaries as raw evidence. Generated text must link back to source records.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.17 Commerce / Product / Offer 360 — `commerce`

**Priority:** P2<br>
**Canonical owner:** `commerce_product_offer_graph`<br>
**Subjects:** commerce_id, product_id, offer_id, sku_id, checkout_id<br>
**Required lenses:** commerce, product-offer, campaign, journey, value, identity, risk, provenance<br>
**Purpose:** Composes product, offer, checkout, purchase, and campaign/value relationships for commerce journeys.

**Required slots:**

- `product_offer_summary`
- `catalog_links`
- `exposures`
- `intent`
- `cart_checkout`
- `purchase`
- `availability_price`
- `campaign_links`
- `value`
- `risk`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/commerce/schema/commerce.schema.ts
src/modules/experience360/surfaces/commerce/contracts/commerce.contracts.ts
src/modules/experience360/surfaces/commerce/resolver/commerce.resolver.ts
src/modules/experience360/surfaces/commerce/projector/commerce.projector.ts
src/modules/experience360/surfaces/commerce/policy/commerce.policy.ts
src/modules/experience360/surfaces/commerce/freshness/commerce.freshness.ts
src/modules/experience360/surfaces/commerce/evidence/commerce.evidence.ts
src/modules/experience360/surfaces/commerce/fixture/commerce.fixture.ts
src/modules/experience360/surfaces/commerce/golden/commerce.golden.json
src/modules/experience360/surfaces/commerce/__tests__/commerce.resolver.spec.ts
src/modules/experience360/surfaces/commerce/__tests__/commerce.projector.spec.ts
src/modules/experience360/surfaces/commerce/__tests__/commerce.policy.spec.ts
src/modules/experience360/surfaces/commerce/__tests__/commerce.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "commerce"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not mutate product catalog state or order state from 360 projections.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

### 11.18 Support / Callback 360 — `support`

**Priority:** P2<br>
**Canonical owner:** `support_callback_graph`<br>
**Subjects:** support_case_id, callback_id, conversation_id, ticket_id<br>
**Required lenses:** support, communications, journey, identity, risk, workflow, policy<br>
**Purpose:** Provides support cases, callbacks, conversations, participants, agent handoffs, SLA, and resolution state.

**Required slots:**

- `case_summary`
- `conversation_history`
- `callbacks`
- `participants`
- `sla`
- `journey_links`
- `agents`
- `risk`
- `resolution`
- `evidence_trace`

**Backend files:**

```txt
src/modules/experience360/surfaces/support/schema/support.schema.ts
src/modules/experience360/surfaces/support/contracts/support.contracts.ts
src/modules/experience360/surfaces/support/resolver/support.resolver.ts
src/modules/experience360/surfaces/support/projector/support.projector.ts
src/modules/experience360/surfaces/support/policy/support.policy.ts
src/modules/experience360/surfaces/support/freshness/support.freshness.ts
src/modules/experience360/surfaces/support/evidence/support.evidence.ts
src/modules/experience360/surfaces/support/fixture/support.fixture.ts
src/modules/experience360/surfaces/support/golden/support.golden.json
src/modules/experience360/surfaces/support/__tests__/support.resolver.spec.ts
src/modules/experience360/surfaces/support/__tests__/support.projector.spec.ts
src/modules/experience360/surfaces/support/__tests__/support.policy.spec.ts
src/modules/experience360/surfaces/support/__tests__/support.golden.spec.ts
```

**Resolver must load:**

1. Canonical subject reference.
2. Required lens outputs.
3. Optional lens outputs where available.
4. Evidence refs.
5. Policy context.
6. Freshness inputs.
7. Degradation reasons.

**Projector must produce:**

1. `Experience360Frame.kind = "support"`.
2. All required slots listed above.
3. Slot state for every required slot.
4. Evidence trace.
5. Freshness envelope.
6. Policy envelope.
7. Graph edge refs where applicable.
8. Recommendations and action intents only when backed by evidence.

**Hard prohibition:** Do not expose support content outside communication/content permissions.

**Acceptance tests:**

- Resolves complete fixture into a `ready` frame.
- Resolves partial fixture into a `degraded` frame with typed degradation reasons.
- Resolves empty canonical data into `empty`, not `missing`.
- Applies policy redaction before returning the frame.
- Includes evidence refs for every non-empty slot.
- Golden frame remains stable unless contract changes intentionally.

## 12. Data poisoning, source trust, and contagion subsystem

This is backend-critical and must not be treated as only a UI/risk panel feature. Poisoning and contagion can originate from signals, communications, agents, social propagation, financial value, campaigns, imports, webhooks, SDKs, or external connectors.

### 12.1 Required files

```txt
src/modules/experience360/surfaces/risk/poisoning/poisoning-evidence.schema.ts
src/modules/experience360/surfaces/risk/poisoning/source-trust.schema.ts
src/modules/experience360/surfaces/risk/poisoning/source-trust.service.ts
src/modules/experience360/surfaces/risk/poisoning/poisoning-detector.service.ts
src/modules/experience360/surfaces/risk/poisoning/poisoning-evidence.projector.ts
src/modules/experience360/surfaces/risk/poisoning/quarantine-recommendation.service.ts
src/modules/experience360/surfaces/risk/contagion/contagion-path.schema.ts
src/modules/experience360/surfaces/risk/contagion/contagion-path.projector.ts
src/modules/experience360/surfaces/risk/contagion/social-contagion.projector.ts
src/modules/experience360/surfaces/risk/contagion/financial-contagion.projector.ts
src/modules/experience360/surfaces/risk/contagion/agent-amplification.projector.ts
src/modules/experience360/surfaces/risk/__tests__/risk.poisoning.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.contagion.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.source-trust.spec.ts
```

### 12.2 Backend contracts

```ts
export type SourceTrustFrame = {
  sourceId: string;
  sourceSystem: string;
  trustGrade: "trusted" | "watch" | "degraded" | "quarantined" | "unknown";
  trustScore: number;
  reasons: string[];
  evidenceRefIds: string[];
};

export type PoisoningEvidenceFrame = {
  evidenceId: string;
  poisoningType:
    | "schema_drift"
    | "volume_spike"
    | "identity_collision"
    | "attribution_manipulation"
    | "campaign_spoofing"
    | "agent_trace_tampering"
    | "communication_injection"
    | "value_distortion"
    | "relationship_graph_manipulation";
  sourceId: string;
  affectedSubjectIds: string[];
  signalStrength: number;
  confidence: "low" | "medium" | "high" | "verified";
  firstSeenAt: string;
  lastSeenAt: string;
  evidenceRefIds: string[];
};

export type ContagionPathFrame = {
  pathId: string;
  contagionType: "social" | "financial" | "agent_amplified" | "campaign" | "communications";
  originSubjectId: string;
  affectedSubjectId: string;
  hops: Array<{
    fromSubjectId: string;
    toSubjectId: string;
    edgeType: string;
    timestamp?: string;
    evidenceRefIds: string[];
  }>;
  propagationScore: number;
  socialExposure?: number;
  financialExposure?: number;
  agentAmplificationScore?: number;
  confidence: "low" | "medium" | "high" | "verified";
};

export type RiskInterventionFrame = {
  interventionId: string;
  type:
    | "quarantine_source"
    | "downgrade_source_trust"
    | "require_human_review"
    | "freeze_attribution_updates"
    | "disable_agent_action"
    | "restrict_campaign_resolution"
    | "metadata_only_comms"
    | "alert_security_operator";
  label: string;
  requiresConfirmation: boolean;
  reversible: boolean;
  evidenceRefIds: string[];
};
```

### 12.3 Detection responsibilities

The backend must surface, not hide, these scenarios:

| Scenario | Required backend behavior |
|---|---|
| Source emits unusual event volume | Create poisoning evidence and source trust degradation. |
| Imported records collide with existing identity graph | Mark identity slots `conflicted`; do not auto-merge. |
| Webhook starts spoofing campaign/source fields | Preserve source classification separately from campaign identity. |
| Agent performs unexpected action | Build authority conflict and agent amplification evidence. |
| Bad communications propagate through a syndicate | Build social contagion path and communication evidence. |
| Financial/value events look manipulated | Mark value frame degraded and risk frame with value distortion evidence. |
| Risky source contributes to attribution | Freeze derived recommendation, not immutable credits. |

### 12.4 Quarantine rules

Quarantine is not deletion. Quarantine should:

1. Preserve raw evidence.
2. Stop risky source records from influencing high-confidence projections.
3. Mark affected frames degraded.
4. Add source trust evidence.
5. Emit security/operator action intents.
6. Keep tenant-level audit records.

Quarantine must not:

1. Delete raw events.
2. Rewrite historical attribution credits.
3. Auto-merge identities.
4. Suppress evidence visibility for authorized security roles.

## 13. Human, agent, and authority attribution subsystem

This subsystem is required for Agent 360, Execution 360, Profile 360, Journey 360, Workflow 360, Risk 360, and Social 360.

### 13.1 Required files

```txt
src/modules/experience360/services/actor-attribution.service.ts
src/modules/experience360/services/action-driver-score.service.ts
src/modules/experience360/services/authority-chain.service.ts
src/modules/experience360/contracts/actor-attribution.ts
src/modules/experience360/__tests__/actor-attribution.spec.ts
src/modules/experience360/__tests__/authority-chain.spec.ts
```

### 13.2 Contract

```ts
export type ActorKind = "human" | "agent" | "system" | "unknown";

export type ActorAttribution = {
  actorKind: ActorKind;
  actorSubjectId?: string;
  representedSubjectId?: string;
  agentId?: string;
  humanPrincipalId?: string;
  authorityEdgeIds: string[];
  evidenceRefIds: string[];
  driverScore: {
    humanDriven: number;
    agentDriven: number;
    systemDriven: number;
    unknown: number;
  };
  confidence: "low" | "medium" | "high" | "verified";
  explanation: string;
};
```

### 13.3 Scoring rules

The score is not a moral or quality score. It is attribution confidence.

Evidence that increases `agentDriven`:

- Agent ID on execution trace.
- Tool call emitted by agent runtime.
- Delegation contract active at execution time.
- Service credential associated with agent.
- Autonomous workflow trigger.
- Agent-generated plan step.

Evidence that increases `humanDriven`:

- Authenticated human principal.
- Manual approval event.
- Direct UI/session command.
- Explicit confirmation before action.
- Human-authored communication.

Evidence that increases `systemDriven`:

- Scheduled backend job.
- System migration.
- Deterministic system rule.
- Infrastructure event.

Evidence that increases `unknown`:

- Missing principal.
- Missing credential chain.
- Conflicting session and agent trace.
- Untrusted source.
- Policy-redacted actor evidence.

No biometric dependency is required.

## 14. Policy, security, and tenant isolation

### 14.1 Field-level redaction matrix

| Data class | Examples | Required behavior |
|---|---|---|
| Identity | Email, wallet, account ID, device ID | Mask/hash/omit based on scope. |
| Agent authority | Delegated permissions, active credentials | Security/admin scope only; otherwise summarize. |
| Communications | Message body, subject, thread content | Metadata-only fallback unless content scope exists. |
| Financial value | Revenue, Web3 value, conversion value | Finance/admin scope; aggregate fallback. |
| Risk | Risk score, poisoning evidence, contagion path | Security/admin scope; viewer gets summarized risk state. |
| Social graph | Relationship edges, multi-hop paths | Redact private edges and preserve edge counts. |
| Location | Exact place, geohash, timezone, session location | Bucket or approximate unless exact-location scope exists. |
| Evidence refs | Source record IDs, raw payload references | Hide raw source identifiers unless evidence scope exists. |

### 14.2 Tenant isolation rules

1. Every query must include `tenantId`.
2. Every cache key must include `tenantId`.
3. Every snapshot row must include `tenantId`.
4. Every evidence ref must include `tenantId`.
5. Cross-tenant graph edges are disallowed unless explicitly modeled through a safe shared-network contract.
6. Policy filtering must happen after projection and before response.
7. Policy audit must record redaction counts without storing restricted payloads.

### 14.3 Backend permissions

Minimum permission keys:

```txt
experience360.registry.read
experience360.frame.read
experience360.frame.diagnostics.read
experience360.evidence.read
experience360.snapshot.create
experience360.snapshot.read
experience360.risk.read
experience360.risk.evidence.read
experience360.financial.read
experience360.communications.content.read
experience360.agent.authority.read
experience360.location.exact.read
```

## 15. Observability and performance budgets

### 15.1 Required metrics

```txt
experience360.frame.resolve.ms
experience360.frame.project.ms
experience360.frame.policy.ms
experience360.frame.cache.hit_rate
experience360.frame.cache.write.count
experience360.frame.snapshot.write.count
experience360.frame.snapshot.diff.count
experience360.frame.degraded.count
experience360.frame.policy_redaction.count
experience360.slot.empty.count
experience360.slot.missing.count
experience360.slot.error.count
experience360.lens.resolve.ms
experience360.lens.failure.count
experience360.lens.projection.staleness_ms
experience360.identity.resolution.confidence
experience360.agent.authority_conflict.count
experience360.actor_attribution.unknown.count
experience360.risk.poisoning_evidence.count
experience360.risk.contagion_path.count
experience360.social.contagion_flag.count
experience360.value.reconciliation_gap.count
experience360.evidence.conflict.count
```

### 15.2 Performance budgets

| Operation | Target |
|---|---:|
| Registry lookup | < 10 ms |
| Cache key build | < 5 ms |
| Cache read | < 30 ms |
| Simple frame resolve | < 300 ms |
| Complex graph frame resolve | < 1,500 ms |
| Policy filtering | < 100 ms |
| Evidence trace attachment | < 250 ms |
| Snapshot write | < 300 ms async preferred |

Frames that exceed budget should still return when safe, but must include diagnostics when authorized and emit metrics.

## 16. Test matrix

### 16.1 Shared tests

```txt
src/modules/experience360/__tests__/registry.test.ts
src/modules/experience360/__tests__/frame.service.test.ts
src/modules/experience360/__tests__/policy-filter.test.ts
src/modules/experience360/__tests__/freshness.test.ts
src/modules/experience360/__tests__/evidence-trace.test.ts
src/modules/experience360/__tests__/cache-key.test.ts
src/modules/experience360/__tests__/snapshot.test.ts
src/modules/experience360/__tests__/actor-attribution.spec.ts
src/modules/experience360/__tests__/authority-chain.spec.ts
src/modules/experience360/__tests__/tenant-isolation.spec.ts
```

### 16.2 Per-surface tests

Every surface must include:

```txt
{kind}.resolver.spec.ts
{kind}.projector.spec.ts
{kind}.policy.spec.ts
{kind}.golden.spec.ts
```

Each surface test suite must prove:

1. Complete fixture resolves to `ready`.
2. Empty fixture resolves to `empty`.
3. Missing expected source resolves to `missing` or `degraded`, not `empty`.
4. Policy-restricted fixture redacts restricted fields.
5. Stale projection marks frame `stale`.
6. Conflicting evidence marks relevant slots `conflicted`.
7. Evidence refs exist for non-empty slots.
8. No resolver performs canonical writes.
9. Golden frame is stable.
10. Diagnostics are excluded unless requested and authorized.

### 16.3 Risk-specific tests

```txt
src/modules/experience360/surfaces/risk/__tests__/risk.poisoning.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.contagion.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.source-trust.spec.ts
src/modules/experience360/surfaces/risk/__tests__/risk.quarantine.spec.ts
```

These must prove:

1. Poisoned source degrades source trust.
2. Poisoned source does not disappear from evidence.
3. Quarantine prevents high-confidence projection influence.
4. Social contagion path includes relationship evidence.
5. Financial contagion path includes value exposure evidence.
6. Agent amplification path includes actor attribution and authority evidence.
7. Risk frame never returns unexplained scores.

## 17. Feature flags and rollout order

### 17.1 Required feature flags

```txt
experience360.enabled
experience360.registry.enabled
experience360.snapshots.enabled
experience360.evidence.enabled
experience360.diagnostics.enabled
experience360.agent.enabled
experience360.execution.enabled
experience360.episode.enabled
experience360.profile.enabled
experience360.identity.enabled
experience360.journey.enabled
experience360.communications.enabled
experience360.risk.enabled
experience360.value.enabled
experience360.social.enabled
experience360.campaign.enabled
experience360.signals.enabled
experience360.account.enabled
experience360.location.enabled
experience360.workflow.enabled
experience360.memory.enabled
experience360.commerce.enabled
experience360.support.enabled
experience360.risk.poisoning.enabled
experience360.risk.contagion.enabled
experience360.actor_attribution.enabled
```

### 17.2 Rollout phases

#### Phase 0 — Shared backend spine

Build first:

1. Contracts.
2. Registry.
3. Frame service.
4. Policy filter.
5. Evidence trace.
6. Freshness service.
7. Cache/snapshot service.
8. Route handlers.
9. Shared tests.

Exit criteria:

- Registry test passes.
- Frame service can return a mocked frame.
- Policy filter redacts restricted fields.
- Snapshot write/read works.
- No frontend code required.

#### Phase 1 — Core operational 360s

Build:

1. Agent 360.
2. Execution 360.
3. Episode 360.
4. Profile 360.
5. Identity 360.

Exit criteria:

- Actor attribution works.
- Authority chains work.
- Profile can show agent delegations.
- Episode can show agent/human participation.
- Execution can show who drove an action.

#### Phase 2 — Decision and risk surfaces

Build:

1. Journey 360.
2. Communications 360.
3. Risk 360.
4. Value 360.
5. Social 360.

Exit criteria:

- Communications attach to profile/journey/episode.
- Value keeps missing/zero/redacted distinct.
- Risk includes poisoning/source trust/contagion frames.
- Social includes relationship and multi-hop evidence.

#### Phase 3 — Signals, campaigns, accounts, location, workflow

Build:

1. Campaign 360.
2. Signals 360.
3. Account 360.
4. Location 360.
5. Workflow 360.

Exit criteria:

- Campaign identity is separate from source classification.
- Signals expose lineage and quality.
- Account aggregates without bypassing profile policy.
- Location buckets exact data when required.
- Workflow returns action intents, not direct executions.

#### Phase 4 — Extended surfaces

Build:

1. Memory 360.
2. Commerce 360.
3. Support 360.

Exit criteria:

- Generated semantic summaries cite source evidence.
- Commerce reads product/order/catalog state without mutating it.
- Support uses communications permissions.

#### Phase 5 — Backfill, performance, production hardening

Complete:

1. Backfill snapshots for pilot tenants.
2. Add metrics dashboards.
3. Add degradation reports.
4. Run tenant-isolation tests.
5. Run policy audit verification.
6. Run high-volume frame load tests.

## 18. Implementation commands and CI gates

Adapt script names to the repo's package manager, but the required gates are:

```bash
pnpm typecheck
pnpm lint
pnpm test src/modules/experience360
pnpm test src/modules/experience360/__tests__/registry.test.ts
pnpm test src/modules/experience360/__tests__/policy-filter.test.ts
pnpm test src/modules/experience360/surfaces/risk
pnpm test src/modules/experience360/surfaces/agent
pnpm test src/modules/experience360/surfaces/profile
pnpm db:migrate
pnpm db:migrate:validate
```

Minimum CI requirement:

1. Registry completeness test.
2. Contract typecheck.
3. Policy redaction test.
4. Tenant isolation test.
5. Golden frame tests for P0 surfaces.
6. Migration validation.
7. Risk poisoning/contagion tests.

## 19. Triple-check validation

This section is the implementation self-audit. The backend 360 system is not done unless all three checks pass.

### Check 1 — Architectural correctness

| Requirement | Pass condition |
|---|---|
| 360s are read models | No resolver/projector writes canonical state. |
| Canonical ownership preserved | Every surface declares canonical owner and reads through adapters. |
| Lens-composed | Every registry entry declares required and optional lenses. |
| Evidence-backed | Every non-empty slot has evidence refs. |
| Policy-filtered | Policy filter runs before response. |
| Typed degradation | Missing/empty/zero/redacted/stale/conflicted are distinct. |
| Campaign boundary preserved | Source classification and campaign identity are separate fields. |
| Journey/attribution boundary preserved | Journey touchpoints and attribution credits are separate fields. |
| Backend-only | No page/component/styling implementation in this scope. |

### Check 2 — Repo implementation completeness

| Requirement | Pass condition |
|---|---|
| Registry | All `EXPERIENCE_360_KINDS` have registry entries. |
| Files | Every surface has schema/contracts/resolver/projector/policy/freshness/evidence/fixture/golden/tests. |
| API | Frame, registry, evidence, and snapshot handlers exist. |
| DB | All migrations exist and validate. |
| Tests | Shared tests and per-surface tests pass. |
| Flags | Every surface has a feature flag. |
| Snapshots | Snapshot write/read/diff works. |
| Cache | Cache key includes tenant, kind, subject, lens hash, policy hash, and asOf. |
| Observability | Required metrics emit. |

### Check 3 — Product goal coverage

| Product goal | Backend support |
|---|---|
| Full Profile 360 | Profile, Identity, Journey, Agent, Communications, Value, Risk, Social frames. |
| Agent lifecycle tracking | Agent, Execution, Workflow, Authority, Actor Attribution frames. |
| Human vs agent action clarity | Actor attribution and action-driver score. |
| No biometric dependency | Non-biometric evidence model is baseline. |
| Data poisoning detection | Poisoning evidence, source trust, quarantine recommendations. |
| Social contagion surfacing | Social/Risk contagion paths and relationship evidence. |
| Financial contagion surfacing | Value/Risk financial exposure paths. |
| Campaign/signal correctness | Campaign and Signals 360 separation. |
| Backend-first implementation | All work is contracts, services, routes, DB, tests, observability. |

If any item above fails, the implementation is incomplete.

## 20. Final definition of done

The backend 360 system is implementation-complete when:

1. `src/modules/experience360` exists with the topology in this document.
2. Every surface in `EXPERIENCE_360_KINDS` has a registry entry.
3. Every registry entry points to real backend files.
4. Every surface has a resolver, projector, schema, policy file, fixture, golden frame, and tests.
5. Shared frame service resolves all P0 surfaces through the same pipeline.
6. API route wrappers contain no business logic.
7. Migrations run and validate.
8. Risk poisoning, source trust, and contagion are implemented as backend frames and services.
9. Actor attribution identifies human, agent, system, and unknown drivers with evidence.
10. Policy filter applies before any frame leaves the backend.
11. Cache/snapshot keys include tenant, subject, lens, policy, and time.
12. Tests prove missing/empty/zero/redacted/stale/conflicted are distinct.
13. Campaign identity remains separate from source classification.
14. Journey touchpoints remain separate from attribution touchpoints.
15. No frontend implementation is required for backend acceptance.

## 21. Implementation directive

Build the backend in this order:

```txt
1. contracts/
2. registry/
3. services/frame.service.ts
4. policy, evidence, freshness, cache, snapshot services
5. API handlers
6. DB migrations
7. Agent, Execution, Episode, Profile, Identity 360
8. Journey, Communications, Risk, Value, Social 360
9. Campaign, Signals, Account, Location, Workflow 360
10. Memory, Commerce, Support 360
11. Backfills, metrics, production hardening
```

Do not begin surface-specific feature work until the registry and shared frame service are implemented. The registry is the backend control plane. The frame service is the execution spine. The surfaces are projections.
