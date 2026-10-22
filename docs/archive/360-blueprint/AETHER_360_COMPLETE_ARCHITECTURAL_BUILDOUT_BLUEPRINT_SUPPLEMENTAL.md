# Aether 360 Complete Architectural Buildout Blueprint

**Document type:** implementation build spec<br>
**Date:** 2026-09-07<br>
**Scope:** Entire Aether 360 matrix, graph lenses, contracts, supporting subsystems, UI surfaces, APIs, tests, fixtures, migrations, and rollout plan.<br>
**Instructional posture:** This is a build artifact. It is not a summary, not a design memo, and not a partial implementation plan.

---

## 0. Build mandate

Aether's 360 system must be implemented as a governed projection layer over canonical truth. Each 360 is a typed operating surface that composes canonical records, graph edges, reusable lenses, event signals, policy gates, snapshots, and dashboard slots into a single explainable frame.

The implementation must complete the existing blueprint-rich surfaces such as Agent 360, Episode 360, Execution 360, and Profile 360, then build or normalize the remaining surfaces across support, communications, social/community, trend/topic, semantic/memory, location/place, offer/commerce/product, campaign, value, workflow/automation, account, identity, and risk.

The completed system must make these things true:

1. Every 360 has a registry entry.
2. Every 360 has a typed frame DTO.
3. Every 360 has a resolver.
4. Every 360 has a projector.
5. Every 360 has a snapshot repository.
6. Every 360 has a JSON API.
7. Every 360 has a dashboard route.
8. Every dashboard slot maps exactly to a backend frame slot.
9. Every 360 uses graph lenses instead of duplicating relationship, identity, economic, semantic, policy, or execution logic.
10. Every 360 has fixtures, contract tests, UI tests, docs, telemetry, and acceptance criteria.
11. No 360 writes canonical source records directly.
12. All user-visible frames pass through policy, privacy, entitlement, and redaction controls before leaving the backend.
13. Every frame includes source records, lens provenance, freshness, confidence, related 360 links, and degradation metadata.
14. The system distinguishes `missing`, `empty`, `zero`, `redacted`, and `stale` rather than collapsing them into falsy values.

---

## 1. Non-negotiable architecture laws

### 1.1 360s are read models

A 360 is a composed read projection. It does not own canonical truth. It can rebuild, snapshot, explain, redact, and render canonical truth, but it cannot become the canonical store.

**Allowed inside a 360 module**

- Resolve canonical source records.
- Resolve graph edges.
- Call lenses.
- Compose frame slots.
- Read/write projection snapshots.
- Emit projection telemetry.
- Invalidate or request rebuilds.
- Return dashboard/API frames.

**Forbidden inside a 360 module**

- Creating canonical profiles, agents, accounts, offers, campaigns, payments, messages, or executions.
- Mutating identity merges.
- Mutating entitlements.
- Mutating policy decisions.
- Mutating payment/value records.
- Hiding data transformations inside UI components.
- Allowing frontend pages to perform graph joins independently of the backend frame.

### 1.2 Canonical write path

All writes must flow through the owning canonical module:

```txt
external source / user action / agent action
  -> canonical module command
  -> canonical repository mutation
  -> outbox event
  -> event bus
  -> graph edge update / lens invalidation
  -> 360 snapshot invalidation
  -> 360 projection rebuild
  -> dashboard/API frame
```

### 1.3 Projection path

All reads must flow through the 360 projection path:

```txt
dashboard/API request
  -> experience360 registry lookup
  -> surface service
  -> snapshot lookup
  -> resolver bundle
  -> lens calls
  -> projector
  -> policy/redaction finalization
  -> frame DTO
  -> dashboard slots / API JSON
```

---

## 2. Target repository topology

The repo must converge around this file structure. Existing files should be moved only when required; otherwise add adapters so old routes/components continue working until migration is complete.

```txt
src/
  modules/
    experience360/
      experience360.module.ts
      experience360.controller.ts
      experience360.service.ts
      experience360.registry.ts
      dto/
        experience360-registry.dto.ts
        surface360-request.dto.ts
        surface360-response.dto.ts
      contracts/
        frame360.contract.ts
        lens.contract.ts
        surface360.contract.ts
        freshness.contract.ts
        policy.contract.ts
        related360.contract.ts
      freshness/
        experience360-freshness.service.ts
        source-hash.service.ts
      policies/
        experience360-policy.service.ts
        redaction-reason.map.ts
      snapshots/
        experience360-snapshot.repository.ts
        projection-snapshot.entity.ts
      events/
        experience360.events.ts
        projection-invalidated.event.ts
        projection-rebuild-requested.event.ts
      telemetry/
        experience360.telemetry.ts
      tests/
        experience360.registry.spec.ts
        experience360.service.spec.ts
        experience360.policy.spec.ts

    graph-lenses/
      identity/
      relationship/
      semantic-memory/
      economic/
      value/
      policy/
      entitlement/
      execution/
      event-signal/
      location/
      product-offer/
      communications/
      campaign/
      risk/
      account/

    agent360/
    execution360/
    episode360/
    profile360/
    social360/
    community360/
    support360/
    conversation360/
    callback360/
    communications360/
    trend360/
    semantic360/
    memory360/
    location360/
    place360/
    offer360/
    commerce360/
    product360/
    campaign360/
    value360/
    workflow360/
    automation360/
    account360/
    identity360/
    risk360/

app/
  (dashboard)/
    agent360/
      page.tsx
      [id]/page.tsx
    execution360/
      page.tsx
      [id]/page.tsx
    episode360/
      page.tsx
      [id]/page.tsx
    profile360/
      page.tsx
      [id]/page.tsx
    social360/
      page.tsx
      [id]/page.tsx
    community360/
      page.tsx
      [id]/page.tsx
    support360/
      page.tsx
      [id]/page.tsx
    conversation360/
      page.tsx
      [id]/page.tsx
    callback360/
      page.tsx
      [id]/page.tsx
    communications360/
      page.tsx
      [id]/page.tsx
    trend360/
      page.tsx
      [id]/page.tsx
    semantic360/
      page.tsx
      [id]/page.tsx
    memory360/
      page.tsx
      [id]/page.tsx
    location360/
      page.tsx
      [id]/page.tsx
    place360/
      page.tsx
      [id]/page.tsx
    offer360/
      page.tsx
      [id]/page.tsx
    commerce360/
      page.tsx
      [id]/page.tsx
    product360/
      page.tsx
      [id]/page.tsx
    campaign360/
      page.tsx
      [id]/page.tsx
    value360/
      page.tsx
      [id]/page.tsx
    workflow360/
      page.tsx
      [id]/page.tsx
    automation360/
      page.tsx
      [id]/page.tsx
    account360/
      page.tsx
      [id]/page.tsx
    identity360/
      page.tsx
      [id]/page.tsx
    risk360/
      page.tsx
      [id]/page.tsx

  api/
    360/
      registry/route.ts
      [surface]/
        [id]/route.ts
        [id]/snapshot/route.ts
        [id]/rebuild/route.ts
        [id]/lenses/[lens]/route.ts

components/
  360/
    _shared/
      Surface360Shell.tsx
      Surface360Header.tsx
      Surface360FreshnessBanner.tsx
      Surface360PolicyBanner.tsx
      Surface360SlotBoundary.tsx
      Related360Rail.tsx
      SourceRecordDrawer.tsx
      LensProvenanceDrawer.tsx
      DegradationBadge.tsx
      RedactionNotice.tsx
      EmptyState.tsx
      StaleState.tsx
      ErrorState.tsx
    agent360/
    execution360/
    episode360/
    profile360/
    social360/
    community360/
    support360/
    conversation360/
    callback360/
    communications360/
    trend360/
    semantic360/
    memory360/
    location360/
    place360/
    offer360/
    commerce360/
    product360/
    campaign360/
    value360/
    workflow360/
    automation360/
    account360/
    identity360/
    risk360/

lib/
  360/
    client.ts
    frame-normalizers.ts
    surface-registry.ts
    slot-state.ts
    errors.ts

test/
  contract/
    360/
      registry.contract.spec.ts
      agent360.contract.spec.ts
      execution360.contract.spec.ts
      episode360.contract.spec.ts
      profile360.contract.spec.ts
      social360.contract.spec.ts
      community360.contract.spec.ts
      support360.contract.spec.ts
      conversation360.contract.spec.ts
      callback360.contract.spec.ts
      communications360.contract.spec.ts
      trend360.contract.spec.ts
      semantic360.contract.spec.ts
      memory360.contract.spec.ts
      location360.contract.spec.ts
      place360.contract.spec.ts
      offer360.contract.spec.ts
      commerce360.contract.spec.ts
      product360.contract.spec.ts
      campaign360.contract.spec.ts
      value360.contract.spec.ts
      workflow360.contract.spec.ts
      automation360.contract.spec.ts
      account360.contract.spec.ts
      identity360.contract.spec.ts
      risk360.contract.spec.ts
  fixtures/
    360/
      agent360.fixture.ts
      execution360.fixture.ts
      episode360.fixture.ts
      profile360.fixture.ts
      social360.fixture.ts
      community360.fixture.ts
      support360.fixture.ts
      conversation360.fixture.ts
      callback360.fixture.ts
      communications360.fixture.ts
      trend360.fixture.ts
      semantic360.fixture.ts
      memory360.fixture.ts
      location360.fixture.ts
      place360.fixture.ts
      offer360.fixture.ts
      commerce360.fixture.ts
      product360.fixture.ts
      campaign360.fixture.ts
      value360.fixture.ts
      workflow360.fixture.ts
      automation360.fixture.ts
      account360.fixture.ts
      identity360.fixture.ts
      risk360.fixture.ts

docs/
  architecture/
    360/
      README.md
      registry.md
      graph-lenses.md
      frame-contract.md
      agent360.md
      execution360.md
      episode360.md
      profile360.md
      social360.md
      community360.md
      support360.md
      conversation360.md
      callback360.md
      communications360.md
      trend360.md
      semantic360.md
      memory360.md
      location360.md
      place360.md
      offer360.md
      commerce360.md
      product360.md
      campaign360.md
      value360.md
      workflow360.md
      automation360.md
      account360.md
      identity360.md
      risk360.md

prisma/
  migrations/
    YYYYMMDDHHMMSS_create_experience360_projection_snapshots/
      migration.sql
    YYYYMMDDHHMMSS_create_graph_lens_projection_cache/
      migration.sql
    YYYYMMDDHHMMSS_add_360_event_invalidation_indexes/
      migration.sql
```

---

## 3. Global contracts

### 3.1 Surface keys

```ts
export type Surface360Key =
  | 'agent360'
  | 'execution360'
  | 'episode360'
  | 'profile360'
  | 'social360'
  | 'community360'
  | 'support360'
  | 'conversation360'
  | 'callback360'
  | 'communications360'
  | 'trend360'
  | 'semantic360'
  | 'memory360'
  | 'location360'
  | 'place360'
  | 'offer360'
  | 'commerce360'
  | 'product360'
  | 'campaign360'
  | 'value360'
  | 'workflow360'
  | 'automation360'
  | 'account360'
  | 'identity360'
  | 'risk360';

export type LensKey =
  | 'identity'
  | 'relationship'
  | 'semantic-memory'
  | 'economic'
  | 'value'
  | 'policy'
  | 'entitlement'
  | 'execution'
  | 'event-signal'
  | 'location'
  | 'product-offer'
  | 'communications'
  | 'campaign'
  | 'risk'
  | 'account';
```

### 3.2 Canonical refs and source records

```ts
export interface CanonicalRef {
  type:
    | 'profile'
    | 'identity'
    | 'account'
    | 'organization'
    | 'place'
    | 'product'
    | 'offer'
    | 'campaign'
    | 'agent'
    | 'episode'
    | 'execution_artifact'
    | 'exchange_thread'
    | 'conversation'
    | 'callback_request'
    | 'support_case'
    | 'workflow'
    | 'automation'
    | 'semantic_node'
    | 'memory_card'
    | 'risk_signal'
    | 'value_event'
    | 'event_signal';
  id: string;
  tenantId: string;
}

export interface SourceRecordRef {
  ref: CanonicalRef;
  module: string;
  table?: string;
  version?: string;
  lastUpdatedAt?: string;
  hash?: string;
  relationship?: string;
}

export interface GraphEdgeRef {
  from: CanonicalRef;
  to: CanonicalRef;
  edgeType: string;
  strength?: number;
  observedAt?: string;
  source?: SourceRecordRef;
}
```

### 3.3 Freshness and degradation

```ts
export type ProjectionDegradationKind =
  | 'missing'
  | 'empty'
  | 'zero'
  | 'redacted'
  | 'stale'
  | 'partial'
  | 'policy_blocked'
  | 'lens_failed'
  | 'source_unavailable';

export interface ProjectionDegradation {
  kind: ProjectionDegradationKind;
  slot?: string;
  lens?: LensKey;
  source?: SourceRecordRef;
  reason: string;
  userMessage?: string;
  severity: 'info' | 'warning' | 'error';
}

export interface ProjectionFreshness {
  generatedAt: string;
  sourceMaxUpdatedAt?: string;
  expiresAt?: string;
  isStale: boolean;
  ttlSeconds: number;
  sourceHash: string;
  lensVersions: Record<LensKey, string>;
  policyHash: string;
}
```

### 3.4 Lens context and result

```ts
export interface LensContext {
  tenantId: string;
  requester?: {
    profileId?: string;
    accountId?: string;
    roleIds?: string[];
    entitlements?: string[];
  };
  canonicalRefs: CanonicalRef[];
  asOf?: string;
  includeExplainability?: boolean;
  policyMode?: 'strict' | 'internal' | 'debug';
}

export interface ConfidenceScore {
  score: number;
  label: 'low' | 'medium' | 'high';
  reasons: string[];
}

export interface ExplanationRef {
  code: string;
  message: string;
  sourceRecords?: SourceRecordRef[];
  graphEdges?: GraphEdgeRef[];
}

export interface LensPolicyState {
  allowed: boolean;
  redactedFields: string[];
  reasonCodes: string[];
}

export interface LensResult<T> {
  lens: LensKey;
  version: string;
  data: T;
  sourceRecords: SourceRecordRef[];
  graphEdges?: GraphEdgeRef[];
  freshness: ProjectionFreshness;
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  policy: LensPolicyState;
  degradation?: ProjectionDegradation[];
}
```

### 3.5 Frame contract

```ts
export interface Related360Link {
  surface: Surface360Key;
  canonicalId: string;
  label: string;
  relationship:
    | 'owns'
    | 'belongs_to'
    | 'participates_in'
    | 'generated'
    | 'affected_by'
    | 'related_to'
    | 'risk_for'
    | 'value_for'
    | 'campaign_for'
    | 'support_for';
  strength?: number;
  policyState: 'visible' | 'redacted' | 'blocked';
}

export interface Frame360<TSlots extends Record<string, unknown>> {
  surface: Surface360Key;
  frameVersion: string;
  tenantId: string;
  canonicalId: string;
  generatedAt: string;
  freshness: ProjectionFreshness;
  sourceRecords: SourceRecordRef[];
  lenses: Array<{
    key: LensKey;
    version: string;
    freshness: ProjectionFreshness;
    confidence: ConfidenceScore;
    degradation?: ProjectionDegradation[];
  }>;
  policy: {
    allowed: boolean;
    redactedFields: string[];
    reasonCodes: string[];
  };
  slots: TSlots;
  related360s: Related360Link[];
  degradation?: ProjectionDegradation[];
  explainability?: ExplanationRef[];
}
```

### 3.6 Surface registry contract

```ts
export interface Surface360Definition<TFrame extends Frame360<Record<string, unknown>>> {
  key: Surface360Key;
  label: string;
  route: string;
  apiRoute: string;
  dashboardRoute: string;
  frameVersion: string;
  canonicalInputs: string[];
  requiredLenses: LensKey[];
  requiredSlots: string[];
  resolverToken: string;
  projectorToken: string;
  snapshotTtlSeconds: number;
  freshnessSlaSeconds: number;
  readiness: 'missing' | 'scaffolded' | 'partial' | 'production';
  aliases?: string[];
  deprecatedRoutes?: string[];
}
```

---

## 4. Registry build

### 4.1 Required file

`src/modules/experience360/experience360.registry.ts`

### 4.2 Registry entries

| Surface | Route | Canonical inputs | Required lenses | Required slots |
|---|---|---|---|---|
| `agent360` | `agent360` | `agent`, `profile`, `organization`, `execution_artifact`... | `identity`, `execution`, `semantic-memory`, `policy`, `entitlement`, `event-signal`, `risk`, `value` | `summary`, `identity`, `capabilities`, `assignments`, `executions`, `performance`, `knowledge`, `policy`, `risk`, `related360s` |
| `execution360` | `execution360` | `execution_artifact`, `agent`, `profile`, `episode`... | `execution`, `event-signal`, `identity`, `policy`, `risk`, `value`, `semantic-memory` | `summary`, `intent`, `actor`, `plan`, `steps`, `artifacts`, `toolTrace`, `confidence`, `value`, `risk`, `policy`, `related360s` |
| `episode360` | `episode360` | `episode`, `profile`, `agent`, `exchange_thread`... | `identity`, `relationship`, `execution`, `semantic-memory`, `policy`, `event-signal`, `risk`, `value` | `header`, `context`, `timeline`, `participants`, `decisions`, `artifacts`, `outcomes`, `policy`, `related360s` |
| `profile360` | `profile360` | `profile`, `identity`, `account`, `organization`... | `identity`, `relationship`, `economic`, `entitlement`, `communications`, `event-signal`, `policy`, `risk`, `value` | `header`, `identity`, `account`, `network`, `financial`, `offers`, `activity`, `support`, `governance`, `related360s` |
| `social360` | `social360` | `profile`, `community`, `organization`, `exchange_thread`... | `relationship`, `identity`, `event-signal`, `semantic-memory`, `campaign`, `risk`, `value` | `profile`, `network`, `communities`, `influence`, `activity`, `trust`, `signals`, `related360s` |
| `community360` | `community360` | `community`, `profile`, `organization`, `topic`... | `relationship`, `event-signal`, `semantic-memory`, `campaign`, `risk`, `value` | `community`, `members`, `network`, `activity`, `topics`, `influence`, `health`, `trust`, `related360s` |
| `support360` | `support360` | `support_case`, `callback_request`, `conversation`, `profile`... | `communications`, `identity`, `relationship`, `policy`, `execution`, `event-signal`, `risk`, `value` | `caseSummary`, `requester`, `conversations`, `callbackRequests`, `assignments`, `escalation`, `policy`, `outcomes`, `related360s` |
| `conversation360` | `conversation360` | `conversation`, `exchange_thread`, `message`, `profile`... | `communications`, `identity`, `semantic-memory`, `policy`, `event-signal`, `risk` | `thread`, `participants`, `messages`, `sentiment`, `intents`, `linkedCases`, `nextActions`, `compliance`, `related360s` |
| `callback360` | `callback360` | `callback_request`, `profile`, `conversation`, `support_case`... | `communications`, `identity`, `policy`, `execution`, `event-signal`, `risk` | `request`, `requester`, `scheduling`, `attempts`, `owner`, `escalation`, `consent`, `outcome`, `related360s` |
| `communications360` | `communications360` | `exchange_thread`, `conversation`, `message`, `notification`... | `communications`, `identity`, `policy`, `event-signal`, `risk`, `semantic-memory` | `unifiedInbox`, `participants`, `channels`, `threads`, `notifications`, `consent`, `deliveryHealth`, `nextActions`, `related360s` |
| `trend360` | `trend360` | `topic`, `trend`, `event_signal`, `profile`... | `event-signal`, `semantic-memory`, `relationship`, `location`, `campaign`, `risk`, `value` | `topic`, `timeline`, `signals`, `syndicates`, `geography`, `sentiment`, `opportunities`, `risk`, `related360s` |
| `semantic360` | `semantic360` | `semantic_node`, `memory_card`, `embedding`, `source_document`... | `semantic-memory`, `identity`, `event-signal`, `policy`, `risk` | `node`, `meaning`, `embeddings`, `linkedMemories`, `provenance`, `usage`, `drift`, `governance`, `related360s` |
| `memory360` | `memory360` | `memory_card`, `semantic_node`, `profile`, `agent`... | `semantic-memory`, `identity`, `policy`, `event-signal`, `risk` | `card`, `source`, `semanticLinks`, `reminders`, `confidence`, `retention`, `governance`, `related360s` |
| `location360` | `location360` | `place`, `location_event`, `profile`, `organization`... | `location`, `identity`, `event-signal`, `product-offer`, `risk`, `value` | `location`, `geography`, `nearbyEntities`, `activity`, `offers`, `risk`, `logistics`, `timezone`, `related360s` |
| `place360` | `place360` | `place`, `organization`, `profile`, `community`... | `location`, `relationship`, `product-offer`, `campaign`, `risk`, `value` | `place`, `geography`, `nearbyEntities`, `activity`, `offers`, `risk`, `logistics`, `related360s` |
| `offer360` | `offer360` | `offer`, `campaign`, `product`, `entitlement`... | `product-offer`, `entitlement`, `economic`, `campaign`, `identity`, `policy`, `risk`, `value` | `offer`, `catalog`, `pricing`, `eligibility`, `entitlement`, `campaigns`, `conversion`, `fulfillment`, `risk`, `related360s` |
| `commerce360` | `commerce360` | `product`, `offer`, `campaign`, `payment`... | `product-offer`, `economic`, `entitlement`, `campaign`, `identity`, `risk`, `value` | `commerceSummary`, `catalog`, `offers`, `payments`, `subscriptions`, `entitlements`, `conversion`, `fulfillment`, `risk`, `related360s` |
| `product360` | `product360` | `product`, `offer`, `campaign`, `entitlement`... | `product-offer`, `economic`, `entitlement`, `campaign`, `event-signal`, `risk`, `value` | `product`, `catalog`, `usage`, `offers`, `entitlements`, `revenue`, `conversion`, `risk`, `related360s` |
| `campaign360` | `campaign360` | `campaign`, `offer`, `profile`, `account`... | `campaign`, `event-signal`, `identity`, `economic`, `product-offer`, `policy`, `risk`, `value` | `campaign`, `signals`, `offers`, `channels`, `journeys`, `performance`, `budget`, `compliance`, `value`, `related360s` |
| `value360` | `value360` | `value_event`, `payment`, `invoice`, `subscription`... | `value`, `economic`, `campaign`, `identity`, `product-offer`, `entitlement`, `risk` | `economicSummary`, `accounts`, `payments`, `invoices`, `subscriptions`, `offers`, `attribution`, `forecast`, `risk`, `related360s` |
| `workflow360` | `workflow360` | `workflow`, `workflow_run`, `automation`, `schedule`... | `execution`, `policy`, `event-signal`, `identity`, `semantic-memory`, `risk`, `value` | `workflow`, `triggers`, `runs`, `steps`, `agents`, `schedules`, `artifacts`, `policy`, `reliability`, `related360s` |
| `automation360` | `automation360` | `automation`, `workflow`, `workflow_run`, `schedule`... | `execution`, `policy`, `event-signal`, `identity`, `risk`, `value` | `automation`, `triggers`, `runs`, `steps`, `agents`, `schedules`, `artifacts`, `policy`, `reliability`, `related360s` |
| `account360` | `account360` | `account`, `organization`, `profile`, `entitlement`... | `identity`, `relationship`, `economic`, `entitlement`, `policy`, `communications`, `risk`, `value` | `account`, `organization`, `users`, `entitlements`, `billing`, `supportHealth`, `activity`, `risk`, `related360s` |
| `identity360` | `identity360` | `identity`, `profile`, `account`, `identifier`... | `identity`, `relationship`, `policy`, `risk`, `event-signal` | `identity`, `identifiers`, `profiles`, `accounts`, `devices`, `verification`, `consent`, `merges`, `policy`, `related360s` |
| `risk360` | `risk360` | `risk_signal`, `policy_finding`, `audit_event`, `profile`... | `risk`, `policy`, `identity`, `execution`, `economic`, `event-signal` | `riskSummary`, `policyFindings`, `anomalies`, `exposure`, `mitigations`, `auditTrail`, `related360s` |

### 4.3 Registry implementation

```ts
export const EXPERIENCE_360_REGISTRY: Record<Surface360Key, Surface360Definition<any>> = {
  agent360: {
    key: 'agent360',
    label: 'Agent 360',
    route: 'agent360',
    apiRoute: '/api/360/agent360/:id',
    dashboardRoute: '/agent360/:id',
    frameVersion: '1.0.0',
    canonicalInputs: ['agent', 'profile', 'organization', 'execution_artifact', 'episode'],
    requiredLenses: ['identity', 'execution', 'semantic-memory', 'policy', 'entitlement', 'event-signal', 'risk', 'value'],
    requiredSlots: ['summary', 'identity', 'capabilities', 'assignments', 'executions', 'performance', 'knowledge', 'policy', 'risk', 'related360s'],
    resolverToken: 'AGENT_360_RESOLVER',
    projectorToken: 'AGENT_360_PROJECTOR',
    snapshotTtlSeconds: 300,
    freshnessSlaSeconds: 900,
    readiness: 'partial',
  },
  // Add every remaining surface from the registry table above with exact required inputs/lenses/slots.
};
```

### 4.4 Registry acceptance tests

`test/contract/360/registry.contract.spec.ts` must assert:

1. Every `Surface360Key` has one registry entry.
2. Every registry entry has one module folder under `src/modules/{surface}`.
3. Every registry entry has one route under `app/(dashboard)/{route}/[id]/page.tsx`.
4. Every registry slot exists in the DTO type and has a corresponding frontend slot component.
5. Every required lens exists under `src/modules/graph-lenses/{lens}`.
6. No registry surface points at a deprecated route unless the deprecated route has a redirect.
7. `aliases` are explicit for naming changes such as `economic360 -> value360`.
8. Readiness cannot be marked `production` unless API, dashboard, snapshot, policy, and contract tests exist.

---

## 5. API build

### 5.1 Required routes

| Route | Responsibility |
|---|---|
| `GET /api/360/registry` | Returns registry entries available to the requester after entitlement/policy filtering. |
| `GET /api/360/:surface/:id` | Returns current frame. Uses snapshot unless stale or `forceFresh=true`. |
| `GET /api/360/:surface/:id/snapshot` | Returns snapshot metadata, not raw hidden internals. Useful for debugging freshness. |
| `POST /api/360/:surface/:id/rebuild` | Requests rebuild. Requires privileged entitlement. Emits rebuild event and returns operation result. |
| `GET /api/360/:surface/:id/lenses/:lens` | Returns lens drilldown if allowed by policy. Used by provenance drawers and debug tools. |

### 5.2 Query parameters

```ts
export interface Surface360Request {
  tenantId: string;
  surface: Surface360Key;
  canonicalId: string;
  asOf?: string;
  include?: string[];
  slot?: string;
  forceFresh?: boolean;
  explain?: boolean;
  redactionMode?: 'default' | 'strict' | 'debug';
}
```

### 5.3 Standard response

```ts
export interface Surface360Response<TFrame extends Frame360<Record<string, unknown>>> {
  ok: true;
  frame: TFrame;
}

export interface Surface360ErrorResponse {
  ok: false;
  error: {
    code:
      | 'SURFACE_NOT_FOUND'
      | 'CANONICAL_RECORD_NOT_FOUND'
      | 'POLICY_BLOCKED'
      | 'LENS_FAILED'
      | 'SNAPSHOT_UNAVAILABLE'
      | 'FRAME_BUILD_FAILED';
    message: string;
    degradation?: ProjectionDegradation[];
    traceId: string;
  };
}
```

### 5.4 Controller responsibilities

`experience360.controller.ts` owns generic dispatch. Surface-specific controllers may exist for compatibility, but generic routing is the target.

```ts
@Controller('/api/360')
export class Experience360Controller {
  constructor(private readonly service: Experience360Service) {}

  @Get('/registry')
  getRegistry(@Req() req: Request) {
    return this.service.getRegistryForRequester(req);
  }

  @Get('/:surface/:id')
  getFrame(@Param('surface') surface: Surface360Key, @Param('id') id: string, @Query() query: Surface360Query) {
    return this.service.getFrame(surface, id, query);
  }

  @Post('/:surface/:id/rebuild')
  rebuild(@Param('surface') surface: Surface360Key, @Param('id') id: string, @Body() body: Rebuild360Request) {
    return this.service.rebuildFrame(surface, id, body);
  }
}
```

---

## 6. Persistence and migrations

### 6.1 Projection snapshot table

`prisma/migrations/YYYYMMDDHHMMSS_create_experience360_projection_snapshots/migration.sql`

```sql
CREATE TABLE experience360_projection_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  surface TEXT NOT NULL,
  canonical_id TEXT NOT NULL,
  frame_version TEXT NOT NULL,
  canonical_version TEXT,
  lens_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_record_hash TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  frame_json JSONB NOT NULL,
  degradation_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_max_updated_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  is_stale BOOLEAN NOT NULL DEFAULT FALSE,
  rebuild_reason TEXT,
  trace_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX experience360_projection_snapshot_unique_current
ON experience360_projection_snapshot (tenant_id, surface, canonical_id, frame_version, source_record_hash, policy_hash);

CREATE INDEX experience360_projection_snapshot_lookup
ON experience360_projection_snapshot (tenant_id, surface, canonical_id, generated_at DESC);

CREATE INDEX experience360_projection_snapshot_stale
ON experience360_projection_snapshot (tenant_id, surface, is_stale, expires_at);
```

### 6.2 Lens cache table

`prisma/migrations/YYYYMMDDHHMMSS_create_graph_lens_projection_cache/migration.sql`

```sql
CREATE TABLE graph_lens_projection_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  lens_key TEXT NOT NULL,
  lens_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  source_record_hash TEXT NOT NULL,
  result_json JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  is_stale BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE UNIQUE INDEX graph_lens_projection_cache_unique
ON graph_lens_projection_cache (tenant_id, lens_key, lens_version, input_hash, policy_hash, source_record_hash);

CREATE INDEX graph_lens_projection_cache_lookup
ON graph_lens_projection_cache (tenant_id, lens_key, input_hash, generated_at DESC);
```

### 6.3 Event invalidation indexes

`prisma/migrations/YYYYMMDDHHMMSS_add_360_event_invalidation_indexes/migration.sql`

```sql
CREATE INDEX domain_event_360_invalidation_lookup
ON domain_event_outbox (tenant_id, aggregate_type, aggregate_id, created_at DESC);

CREATE INDEX graph_edge_360_lookup_from
ON graph_edge (tenant_id, from_type, from_id, edge_type);

CREATE INDEX graph_edge_360_lookup_to
ON graph_edge (tenant_id, to_type, to_id, edge_type);
```

---

## 7. Graph lens subsystem

Every lens must follow the same module shape and result contract. Surface modules consume lens outputs. Lenses must not know about dashboard layout.


## Identity Lens (`identity`)

**Purpose:** Resolves profiles, identifiers, accounts, organizations, agents, devices, merges/splits, consent, and verification state.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/identity/identity.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/identity/identity.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/identity/identity.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/identity/identity.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/identity/identity.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/identity/identity.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/identity/identity.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface IdentityLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface IdentityLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type IdentityLensResult = LensResult<IdentityLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Relationship / Social Lens (`relationship`)

**Purpose:** Builds social, organization, account, community, member, owner, requester, participant, and related-entity graph edges.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/relationship/relationship.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/relationship/relationship.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/relationship/relationship.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/relationship/relationship.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/relationship/relationship.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/relationship/relationship.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/relationship/relationship.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface RelationshipLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface RelationshipLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type RelationshipLensResult = LensResult<RelationshipLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Semantic / Memory Lens (`semantic-memory`)

**Purpose:** Projects semantic nodes, memory cards, embeddings, provenance, drift, confidence, and linked knowledge.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/semantic-memory/semantic-memory.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/semantic-memory/semantic-memory.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface SemanticMemoryLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface SemanticMemoryLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type SemanticMemoryLensResult = LensResult<SemanticMemoryLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Economic Lens (`economic`)

**Purpose:** Normalizes payments, subscriptions, invoices, value events, recurring plans, attribution credits, and financial rollups.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/economic/economic.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/economic/economic.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/economic/economic.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/economic/economic.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/economic/economic.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/economic/economic.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/economic/economic.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface EconomicLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface EconomicLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type EconomicLensResult = LensResult<EconomicLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Value Lens (`value`)

**Purpose:** Product-facing value projection over economic truth: attribution, forecasts, revenue, cost, LTV, realized/unrealized value.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/value/value.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/value/value.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/value/value.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/value/value.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/value/value.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/value/value.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/value/value.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface ValueLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface ValueLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type ValueLensResult = LensResult<ValueLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Policy Lens (`policy`)

**Purpose:** Applies tenant policy, privacy, entitlements, consent, redaction, audit controls, and reason codes before frames leave backend.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/policy/policy.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/policy/policy.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/policy/policy.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/policy/policy.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/policy/policy.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/policy/policy.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/policy/policy.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface PolicyLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface PolicyLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type PolicyLensResult = LensResult<PolicyLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Entitlement Lens (`entitlement`)

**Purpose:** Resolves plan/feature/role/billing entitlements and eligibility for surfaces, offers, actions, and UI slots.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/entitlement/entitlement.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/entitlement/entitlement.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/entitlement/entitlement.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/entitlement/entitlement.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/entitlement/entitlement.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/entitlement/entitlement.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/entitlement/entitlement.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface EntitlementLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface EntitlementLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type EntitlementLensResult = LensResult<EntitlementLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Execution Lens (`execution`)

**Purpose:** Projects execution runs, plans, steps, tool traces, artifacts, confidence, reliability, and failure modes.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/execution/execution.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/execution/execution.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/execution/execution.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/execution/execution.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/execution/execution.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/execution/execution.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/execution/execution.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface ExecutionLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface ExecutionLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type ExecutionLensResult = LensResult<ExecutionLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Event Signal Lens (`event-signal`)

**Purpose:** Projects durable domain events into timeline, recency, freshness, signal counts, degradation, and causal explanations.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/event-signal/event-signal.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/event-signal/event-signal.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/event-signal/event-signal.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/event-signal/event-signal.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/event-signal/event-signal.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/event-signal/event-signal.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/event-signal/event-signal.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface EventSignalLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface EventSignalLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type EventSignalLensResult = LensResult<EventSignalLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Location / Place Lens (`location`)

**Purpose:** Normalizes place, geography, timezone, nearby entity, location-event, and logistic context.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/location/location.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/location/location.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/location/location.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/location/location.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/location/location.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/location/location.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/location/location.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface LocationLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface LocationLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type LocationLensResult = LensResult<LocationLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Product / Offer Lens (`product-offer`)

**Purpose:** Connects catalog, products, offers, campaigns, eligibility, conversion, fulfillment, and entitlements.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/product-offer/product-offer.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/product-offer/product-offer.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/product-offer/product-offer.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/product-offer/product-offer.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/product-offer/product-offer.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/product-offer/product-offer.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/product-offer/product-offer.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface ProductOfferLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface ProductOfferLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type ProductOfferLensResult = LensResult<ProductOfferLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Communications Lens (`communications`)

**Purpose:** Projects conversations, exchange threads, messages, notifications, delivery events, channels, consent, and next actions.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/communications/communications.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/communications/communications.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/communications/communications.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/communications/communications.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/communications/communications.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/communications/communications.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/communications/communications.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface CommunicationsLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface CommunicationsLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type CommunicationsLensResult = LensResult<CommunicationsLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Campaign Lens (`campaign`)

**Purpose:** Projects campaigns, signals, channels, journeys, touchpoints, conversions, budgets, and performance.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/campaign/campaign.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/campaign/campaign.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/campaign/campaign.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/campaign/campaign.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/campaign/campaign.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/campaign/campaign.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/campaign/campaign.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface CampaignLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface CampaignLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type CampaignLensResult = LensResult<CampaignLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Risk Lens (`risk`)

**Purpose:** Projects risk signals, policy findings, anomalies, exposure, mitigations, and audit trail records.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/risk/risk.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/risk/risk.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/risk/risk.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/risk/risk.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/risk/risk.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/risk/risk.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/risk/risk.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface RiskLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface RiskLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type RiskLensResult = LensResult<RiskLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


## Account Lens (`account`)

**Purpose:** Projects account/organization membership, users, entitlements, billing, usage, support health, and account-level risk.

### Required files

| File | Build responsibility |
|---|---|
| `src/modules/graph-lenses/account/account.module.ts` | Exposes resolver/provider for injection into `experience360` and surface modules. |
| `src/modules/graph-lenses/account/account.resolver.ts` | Executes source reads and graph traversal for the lens. No dashboard-specific logic. |
| `src/modules/graph-lenses/account/account.projector.ts` | Normalizes resolver output into the public lens result. |
| `src/modules/graph-lenses/account/account.contract.ts` | Declares input, output, confidence, explainability, and degradation types. |
| `src/modules/graph-lenses/account/account.policy.ts` | Applies lens-specific filtering and policy reason codes. |
| `src/modules/graph-lenses/account/account.fixture.ts` | Shared fixture used by all surface contract tests. |
| `src/modules/graph-lenses/account/account.spec.ts` | Unit/contract tests for input validation, degradation, policy, and deterministic output. |

### Lens result contract

```ts
export interface AccountLensInput extends LensContext {
  canonicalIds: CanonicalRef[];
  asOf?: string;
  tenantId: string;
}

export interface AccountLensOutput {
  summary: Record<string, unknown>;
  records: SourceRecordRef[];
  edges: GraphEdgeRef[];
  confidence: ConfidenceScore;
  explanations: ExplanationRef[];
  degradation?: ProjectionDegradation[];
}

export type AccountLensResult = LensResult<AccountLensOutput>;
```

### Mandatory behavior

1. Accept only tenant-scoped canonical references.
2. Return `LensResult<T>` with explicit `freshness`, `sourceRecords`, `confidence`, `policy`, and `degradation`.
3. Emit no domain writes. Domain writes remain in canonical modules.
4. Cache only by lens input hash, lens version, policy hash, and source-record freshness.
5. Preserve `missing`, `empty`, `zero`, `redacted`, and `stale` as separate typed states.


---

## 8. Shared frontend subsystem

### 8.1 Shared components

| File | Responsibility |
|---|---|
| `components/360/_shared/Surface360Shell.tsx` | Standard page layout, slot grid, related rail, policy/freshness banners. |
| `components/360/_shared/Surface360Header.tsx` | Surface title, canonical ID, source count, generated time, readiness state. |
| `components/360/_shared/Surface360FreshnessBanner.tsx` | Shows stale/partial/source-unavailable state with rebuild affordance if allowed. |
| `components/360/_shared/Surface360PolicyBanner.tsx` | Shows policy/redaction reason summaries without leaking blocked values. |
| `components/360/_shared/Surface360SlotBoundary.tsx` | Standard loading/empty/error/redacted/stale wrapper for each slot. |
| `components/360/_shared/Related360Rail.tsx` | Cross-surface navigation generated from `related360s`. |
| `components/360/_shared/SourceRecordDrawer.tsx` | Shows source record refs, timestamps, hashes, and owning modules. |
| `components/360/_shared/LensProvenanceDrawer.tsx` | Shows lens versions, confidence, source refs, and explanation refs. |
| `components/360/_shared/DegradationBadge.tsx` | Renders `missing`, `empty`, `zero`, `redacted`, `stale`, `partial`, `lens_failed`. |
| `components/360/_shared/RedactionNotice.tsx` | Standard redaction display. |
| `components/360/_shared/EmptyState.tsx` | Valid empty state. |
| `components/360/_shared/StaleState.tsx` | Stale frame state. |
| `components/360/_shared/ErrorState.tsx` | Recoverable and terminal errors. |

### 8.2 UI laws

1. UI must never infer hidden truth from absent fields.
2. UI must render `missing`, `empty`, `zero`, `redacted`, and `stale` differently.
3. UI must not perform independent graph joins.
4. UI must not call domain modules directly for a 360 page.
5. UI must only read the frame DTO and optional allowed lens drilldowns.
6. UI must show frame freshness and policy state on every detail page.
7. UI must include source/lens provenance drawers for debug/internal mode.

---

## 9. Surface-by-surface buildout


## Agent 360 (`agent360`)

**Build disposition:** Blueprint-rich / expected partial. Normalize into registry, lens-backed frame, snapshot repository, API, dashboard slots, and contract tests.

**Purpose:** Complete operating view for autonomous or assisted agents: who the agent is, what it can do, what it has done, what it is allowed to do, how it is performing, and what risks or degraded states affect it.

**Canonical inputs:** `agent`, `profile`, `organization`, `execution_artifact`, `episode`, `policy`, `entitlement`, `semantic_node`, `memory_card`, `event_signal`

**Required lenses:** `identity`, `execution`, `semantic-memory`, `policy`, `entitlement`, `event-signal`, `risk`, `value`

**Required frame slots:** `summary`, `identity`, `capabilities`, `assignments`, `executions`, `performance`, `knowledge`, `policy`, `risk`, `related360s`

**Invalidating domain events:** `agent.created`, `agent.capability.updated`, `agent.assignment.created`, `agent.execution.started`, `agent.execution.completed`, `agent.policy.violation.detected`, `agent.health.degraded`

### Frame contract

```ts
export const AGENT360_FRAME_VERSION = '1.0.0' as const;

export interface Agent360Frame extends Frame360<Agent360Slots> {
  surface: 'agent360';
}

export interface Agent360Slots {
  summary: SummarySlot;
  identity: IdentitySlot;
  capabilities: CapabilitiesSlot;
  assignments: AssignmentsSlot;
  executions: ExecutionsSlot;
  performance: PerformanceSlot;
  knowledge: KnowledgeSlot;
  policy: PolicySlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Agent360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Agent360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/agent360/agent360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/agent360/agent360.controller.ts` | JSON API boundary. Exposes `GET /api/360/agent360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/agent360/agent360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/agent360/contracts/agent360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/agent360/dto/agent360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/agent360/dto/agent360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/agent360/resolvers/agent360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/agent360/projectors/agent360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/agent360/snapshots/agent360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/agent360/policies/agent360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/agent360/events/agent360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/agent360/telemetry/agent360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/agent360/fixtures/agent360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/agent360/tests/agent360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/agent360/tests/agent360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/agent360/tests/agent360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/agent360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/agent360/[id]/page.tsx` | Detail route. Fetches only the `agent360` frame and passes slot data into components. |
| `app/api/360/agent360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/agent360/Agent360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/agent360/Agent360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/agent360/SummarySlot.tsx` | Renders `summary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/IdentitySlot.tsx` | Renders `identity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/CapabilitiesSlot.tsx` | Renders `capabilities` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/AssignmentsSlot.tsx` | Renders `assignments` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/ExecutionsSlot.tsx` | Renders `executions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/PerformanceSlot.tsx` | Renders `performance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/KnowledgeSlot.tsx` | Renders `knowledge` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/agent360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/agent360/index.ts` | Component exports. |
| `lib/360/agent360/fetchAgent360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/agent360/agent360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `agentId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/agent360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Execution 360 (`execution360`)

**Build disposition:** Blueprint-rich / incomplete runtime frame. Build canonical execution trace, artifacts, confidence, value attribution, and policy/risk overlays.

**Purpose:** Explain what ran, why it ran, who or what ran it, each step/tool/artifact involved, whether it should be trusted, and what value or risk resulted.

**Canonical inputs:** `execution_artifact`, `agent`, `profile`, `episode`, `workflow_run`, `tool_trace`, `policy`, `value_event`, `risk_signal`, `event_signal`

**Required lenses:** `execution`, `event-signal`, `identity`, `policy`, `risk`, `value`, `semantic-memory`

**Required frame slots:** `summary`, `intent`, `actor`, `plan`, `steps`, `artifacts`, `toolTrace`, `confidence`, `value`, `risk`, `policy`, `related360s`

**Invalidating domain events:** `execution.requested`, `execution.planned`, `execution.step.started`, `execution.step.completed`, `execution.tool.invoked`, `execution.artifact.created`, `execution.failed`, `execution.completed`

### Frame contract

```ts
export const EXECUTION360_FRAME_VERSION = '1.0.0' as const;

export interface Execution360Frame extends Frame360<Execution360Slots> {
  surface: 'execution360';
}

export interface Execution360Slots {
  summary: SummarySlot;
  intent: IntentSlot;
  actor: ActorSlot;
  plan: PlanSlot;
  steps: StepsSlot;
  artifacts: ArtifactsSlot;
  toolTrace: ToolTraceSlot;
  confidence: ConfidenceSlot;
  value: ValueSlot;
  risk: RiskSlot;
  policy: PolicySlot;
  related360s: Related360sSlot;
}

export interface Execution360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Execution360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/execution360/execution360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/execution360/execution360.controller.ts` | JSON API boundary. Exposes `GET /api/360/execution360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/execution360/execution360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/execution360/contracts/execution360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/execution360/dto/execution360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/execution360/dto/execution360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/execution360/resolvers/execution360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/execution360/projectors/execution360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/execution360/snapshots/execution360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/execution360/policies/execution360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/execution360/events/execution360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/execution360/telemetry/execution360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/execution360/fixtures/execution360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/execution360/tests/execution360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/execution360/tests/execution360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/execution360/tests/execution360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/execution360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/execution360/[id]/page.tsx` | Detail route. Fetches only the `execution360` frame and passes slot data into components. |
| `app/api/360/execution360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/execution360/Execution360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/execution360/Execution360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/execution360/SummarySlot.tsx` | Renders `summary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/IntentSlot.tsx` | Renders `intent` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/ActorSlot.tsx` | Renders `actor` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/PlanSlot.tsx` | Renders `plan` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/StepsSlot.tsx` | Renders `steps` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/ArtifactsSlot.tsx` | Renders `artifacts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/ToolTraceSlot.tsx` | Renders `toolTrace` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/ConfidenceSlot.tsx` | Renders `confidence` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/ValueSlot.tsx` | Renders `value` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/execution360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/execution360/index.ts` | Component exports. |
| `lib/360/execution360/fetchExecution360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/execution360/execution360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `executionId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/execution360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Episode 360 (`episode360`)

**Build disposition:** Blueprint-rich / likely scaffolded. Normalize frame contract and timeline projection; connect conversations, executions, decisions, artifacts, and outcomes.

**Purpose:** A full narrative unit of work or interaction: context, participants, chronology, decisions, artifacts, resolution, and links to affected profiles, agents, workflows, campaigns, or value records.

**Canonical inputs:** `episode`, `profile`, `agent`, `exchange_thread`, `conversation`, `execution_artifact`, `decision`, `artifact`, `outcome`, `policy`, `event_signal`

**Required lenses:** `identity`, `relationship`, `execution`, `semantic-memory`, `policy`, `event-signal`, `risk`, `value`

**Required frame slots:** `header`, `context`, `timeline`, `participants`, `decisions`, `artifacts`, `outcomes`, `policy`, `related360s`

**Invalidating domain events:** `episode.opened`, `episode.participant.joined`, `episode.decision.recorded`, `episode.artifact.attached`, `episode.outcome.recorded`, `episode.closed`

### Frame contract

```ts
export const EPISODE360_FRAME_VERSION = '1.0.0' as const;

export interface Episode360Frame extends Frame360<Episode360Slots> {
  surface: 'episode360';
}

export interface Episode360Slots {
  header: HeaderSlot;
  context: ContextSlot;
  timeline: TimelineSlot;
  participants: ParticipantsSlot;
  decisions: DecisionsSlot;
  artifacts: ArtifactsSlot;
  outcomes: OutcomesSlot;
  policy: PolicySlot;
  related360s: Related360sSlot;
}

export interface Episode360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Episode360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/episode360/episode360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/episode360/episode360.controller.ts` | JSON API boundary. Exposes `GET /api/360/episode360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/episode360/episode360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/episode360/contracts/episode360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/episode360/dto/episode360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/episode360/dto/episode360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/episode360/resolvers/episode360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/episode360/projectors/episode360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/episode360/snapshots/episode360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/episode360/policies/episode360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/episode360/events/episode360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/episode360/telemetry/episode360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/episode360/fixtures/episode360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/episode360/tests/episode360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/episode360/tests/episode360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/episode360/tests/episode360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/episode360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/episode360/[id]/page.tsx` | Detail route. Fetches only the `episode360` frame and passes slot data into components. |
| `app/api/360/episode360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/episode360/Episode360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/episode360/Episode360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/episode360/HeaderSlot.tsx` | Renders `header` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/ContextSlot.tsx` | Renders `context` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/TimelineSlot.tsx` | Renders `timeline` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/ParticipantsSlot.tsx` | Renders `participants` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/DecisionsSlot.tsx` | Renders `decisions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/ArtifactsSlot.tsx` | Renders `artifacts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/OutcomesSlot.tsx` | Renders `outcomes` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/episode360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/episode360/index.ts` | Component exports. |
| `lib/360/episode360/fetchEpisode360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/episode360/episode360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `episodeId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/episode360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Profile 360 (`profile360`)

**Build disposition:** Partially implemented according to prior inventory. Replace thin service/controller with lens-backed resolver/projector/snapshot and production dashboard.

**Purpose:** The unified view of a human or customer profile, including identity resolution, account memberships, relationship graph, financial/value posture, communications, offers, activity, support, and governance state.

**Canonical inputs:** `profile`, `identity`, `account`, `organization`, `exchange_thread`, `support_case`, `offer`, `entitlement`, `payment`, `campaign`, `event_signal`

**Required lenses:** `identity`, `relationship`, `economic`, `entitlement`, `communications`, `event-signal`, `policy`, `risk`, `value`

**Required frame slots:** `header`, `identity`, `account`, `network`, `financial`, `offers`, `activity`, `support`, `governance`, `related360s`

**Invalidating domain events:** `profile.created`, `profile.identifier.linked`, `profile.account.linked`, `profile.activity.recorded`, `profile.entitlement.changed`, `profile.risk.updated`

### Frame contract

```ts
export const PROFILE360_FRAME_VERSION = '1.0.0' as const;

export interface Profile360Frame extends Frame360<Profile360Slots> {
  surface: 'profile360';
}

export interface Profile360Slots {
  header: HeaderSlot;
  identity: IdentitySlot;
  account: AccountSlot;
  network: NetworkSlot;
  financial: FinancialSlot;
  offers: OffersSlot;
  activity: ActivitySlot;
  support: SupportSlot;
  governance: GovernanceSlot;
  related360s: Related360sSlot;
}

export interface Profile360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Profile360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/profile360/profile360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/profile360/profile360.controller.ts` | JSON API boundary. Exposes `GET /api/360/profile360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/profile360/profile360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/profile360/contracts/profile360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/profile360/dto/profile360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/profile360/dto/profile360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/profile360/resolvers/profile360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/profile360/projectors/profile360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/profile360/snapshots/profile360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/profile360/policies/profile360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/profile360/events/profile360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/profile360/telemetry/profile360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/profile360/fixtures/profile360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/profile360/tests/profile360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/profile360/tests/profile360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/profile360/tests/profile360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/profile360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/profile360/[id]/page.tsx` | Detail route. Fetches only the `profile360` frame and passes slot data into components. |
| `app/api/360/profile360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/profile360/Profile360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/profile360/Profile360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/profile360/HeaderSlot.tsx` | Renders `header` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/IdentitySlot.tsx` | Renders `identity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/AccountSlot.tsx` | Renders `account` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/NetworkSlot.tsx` | Renders `network` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/FinancialSlot.tsx` | Renders `financial` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/SupportSlot.tsx` | Renders `support` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/GovernanceSlot.tsx` | Renders `governance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/profile360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/profile360/index.ts` | Component exports. |
| `lib/360/profile360/fetchProfile360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/profile360/profile360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `profileId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/profile360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Social 360 (`social360`)

**Build disposition:** Conceptual/domain partial. Build from relationship/community/social-signal canonical records and register as distinct from Community 360.

**Purpose:** Person-anchored social context: network position, communities, influence, activity, trust, topic affinity, and social signals that explain engagement or risk.

**Canonical inputs:** `profile`, `community`, `organization`, `exchange_thread`, `social_signal`, `event_signal`, `campaign`, `topic`, `sentiment`

**Required lenses:** `relationship`, `identity`, `event-signal`, `semantic-memory`, `campaign`, `risk`, `value`

**Required frame slots:** `profile`, `network`, `communities`, `influence`, `activity`, `trust`, `signals`, `related360s`

**Invalidating domain events:** `social.signal.ingested`, `social.relationship.detected`, `social.influence.updated`, `social.trust.changed`, `social.community.joined`

### Frame contract

```ts
export const SOCIAL360_FRAME_VERSION = '1.0.0' as const;

export interface Social360Frame extends Frame360<Social360Slots> {
  surface: 'social360';
}

export interface Social360Slots {
  profile: ProfileSlot;
  network: NetworkSlot;
  communities: CommunitiesSlot;
  influence: InfluenceSlot;
  activity: ActivitySlot;
  trust: TrustSlot;
  signals: SignalsSlot;
  related360s: Related360sSlot;
}

export interface Social360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Social360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/social360/social360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/social360/social360.controller.ts` | JSON API boundary. Exposes `GET /api/360/social360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/social360/social360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/social360/contracts/social360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/social360/dto/social360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/social360/dto/social360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/social360/resolvers/social360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/social360/projectors/social360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/social360/snapshots/social360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/social360/policies/social360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/social360/events/social360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/social360/telemetry/social360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/social360/fixtures/social360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/social360/tests/social360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/social360/tests/social360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/social360/tests/social360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/social360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/social360/[id]/page.tsx` | Detail route. Fetches only the `social360` frame and passes slot data into components. |
| `app/api/360/social360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/social360/Social360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/social360/Social360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/social360/ProfileSlot.tsx` | Renders `profile` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/NetworkSlot.tsx` | Renders `network` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/CommunitiesSlot.tsx` | Renders `communities` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/InfluenceSlot.tsx` | Renders `influence` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/TrustSlot.tsx` | Renders `trust` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/SignalsSlot.tsx` | Renders `signals` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/social360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/social360/index.ts` | Component exports. |
| `lib/360/social360/fetchSocial360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/social360/social360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `socialId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/social360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Community 360 (`community360`)

**Build disposition:** Conceptual/domain partial. Promote community/social module concepts into a formal frame, resolver, dashboard, and contract suite.

**Purpose:** Group-anchored social surface: membership, engagement, growth/decay, key topics, influential members, health, risk, and related campaigns or episodes.

**Canonical inputs:** `community`, `profile`, `organization`, `topic`, `exchange_thread`, `event_signal`, `campaign`, `social_signal`

**Required lenses:** `relationship`, `event-signal`, `semantic-memory`, `campaign`, `risk`, `value`

**Required frame slots:** `community`, `members`, `network`, `activity`, `topics`, `influence`, `health`, `trust`, `related360s`

**Invalidating domain events:** `community.created`, `community.member.added`, `community.activity.spiked`, `community.topic.trended`, `community.health.changed`

### Frame contract

```ts
export const COMMUNITY360_FRAME_VERSION = '1.0.0' as const;

export interface Community360Frame extends Frame360<Community360Slots> {
  surface: 'community360';
}

export interface Community360Slots {
  community: CommunitySlot;
  members: MembersSlot;
  network: NetworkSlot;
  activity: ActivitySlot;
  topics: TopicsSlot;
  influence: InfluenceSlot;
  health: HealthSlot;
  trust: TrustSlot;
  related360s: Related360sSlot;
}

export interface Community360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Community360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/community360/community360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/community360/community360.controller.ts` | JSON API boundary. Exposes `GET /api/360/community360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/community360/community360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/community360/contracts/community360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/community360/dto/community360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/community360/dto/community360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/community360/resolvers/community360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/community360/projectors/community360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/community360/snapshots/community360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/community360/policies/community360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/community360/events/community360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/community360/telemetry/community360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/community360/fixtures/community360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/community360/tests/community360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/community360/tests/community360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/community360/tests/community360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/community360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/community360/[id]/page.tsx` | Detail route. Fetches only the `community360` frame and passes slot data into components. |
| `app/api/360/community360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/community360/Community360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/community360/Community360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/community360/CommunitySlot.tsx` | Renders `community` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/MembersSlot.tsx` | Renders `members` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/NetworkSlot.tsx` | Renders `network` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/TopicsSlot.tsx` | Renders `topics` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/InfluenceSlot.tsx` | Renders `influence` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/HealthSlot.tsx` | Renders `health` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/TrustSlot.tsx` | Renders `trust` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/community360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/community360/index.ts` | Component exports. |
| `lib/360/community360/fetchCommunity360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/community360/community360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `communityId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/community360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Support 360 (`support360`)

**Build disposition:** Domain module strong, not consistently registered as 360. Register, frame, and unify case/callback/conversation views.

**Purpose:** A complete support-operating surface for cases, callbacks, owners, escalations, conversations, outcomes, consent, and policy constraints.

**Canonical inputs:** `support_case`, `callback_request`, `conversation`, `profile`, `organization`, `agent`, `episode`, `policy`, `event_signal`

**Required lenses:** `communications`, `identity`, `relationship`, `policy`, `execution`, `event-signal`, `risk`, `value`

**Required frame slots:** `caseSummary`, `requester`, `conversations`, `callbackRequests`, `assignments`, `escalation`, `policy`, `outcomes`, `related360s`

**Invalidating domain events:** `support.case.created`, `support.case.assigned`, `support.case.escalated`, `support.callback.requested`, `support.outcome.recorded`, `support.case.closed`

### Frame contract

```ts
export const SUPPORT360_FRAME_VERSION = '1.0.0' as const;

export interface Support360Frame extends Frame360<Support360Slots> {
  surface: 'support360';
}

export interface Support360Slots {
  caseSummary: CaseSummarySlot;
  requester: RequesterSlot;
  conversations: ConversationsSlot;
  callbackRequests: CallbackRequestsSlot;
  assignments: AssignmentsSlot;
  escalation: EscalationSlot;
  policy: PolicySlot;
  outcomes: OutcomesSlot;
  related360s: Related360sSlot;
}

export interface Support360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Support360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/support360/support360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/support360/support360.controller.ts` | JSON API boundary. Exposes `GET /api/360/support360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/support360/support360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/support360/contracts/support360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/support360/dto/support360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/support360/dto/support360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/support360/resolvers/support360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/support360/projectors/support360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/support360/snapshots/support360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/support360/policies/support360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/support360/events/support360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/support360/telemetry/support360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/support360/fixtures/support360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/support360/tests/support360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/support360/tests/support360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/support360/tests/support360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/support360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/support360/[id]/page.tsx` | Detail route. Fetches only the `support360` frame and passes slot data into components. |
| `app/api/360/support360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/support360/Support360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/support360/Support360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/support360/CaseSummarySlot.tsx` | Renders `caseSummary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/RequesterSlot.tsx` | Renders `requester` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/ConversationsSlot.tsx` | Renders `conversations` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/CallbackRequestsSlot.tsx` | Renders `callbackRequests` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/AssignmentsSlot.tsx` | Renders `assignments` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/EscalationSlot.tsx` | Renders `escalation` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/OutcomesSlot.tsx` | Renders `outcomes` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/support360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/support360/index.ts` | Component exports. |
| `lib/360/support360/fetchSupport360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/support360/support360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `supportId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/support360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Conversation 360 (`conversation360`)

**Build disposition:** Domain module strong. Add 360 frame, participant identity lens, semantic/message analysis, and dashboard slots.

**Purpose:** Thread-level operating view that explains participants, message chronology, intent, sentiment, policy/consent status, linked cases, and next actions.

**Canonical inputs:** `conversation`, `exchange_thread`, `message`, `profile`, `agent`, `support_case`, `episode`, `policy`, `consent`, `event_signal`

**Required lenses:** `communications`, `identity`, `semantic-memory`, `policy`, `event-signal`, `risk`

**Required frame slots:** `thread`, `participants`, `messages`, `sentiment`, `intents`, `linkedCases`, `nextActions`, `compliance`, `related360s`

**Invalidating domain events:** `conversation.created`, `conversation.message.received`, `conversation.intent.detected`, `conversation.linked`, `conversation.closed`

### Frame contract

```ts
export const CONVERSATION360_FRAME_VERSION = '1.0.0' as const;

export interface Conversation360Frame extends Frame360<Conversation360Slots> {
  surface: 'conversation360';
}

export interface Conversation360Slots {
  thread: ThreadSlot;
  participants: ParticipantsSlot;
  messages: MessagesSlot;
  sentiment: SentimentSlot;
  intents: IntentsSlot;
  linkedCases: LinkedCasesSlot;
  nextActions: NextActionsSlot;
  compliance: ComplianceSlot;
  related360s: Related360sSlot;
}

export interface Conversation360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Conversation360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/conversation360/conversation360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/conversation360/conversation360.controller.ts` | JSON API boundary. Exposes `GET /api/360/conversation360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/conversation360/conversation360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/conversation360/contracts/conversation360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/conversation360/dto/conversation360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/conversation360/dto/conversation360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/conversation360/resolvers/conversation360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/conversation360/projectors/conversation360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/conversation360/snapshots/conversation360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/conversation360/policies/conversation360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/conversation360/events/conversation360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/conversation360/telemetry/conversation360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/conversation360/fixtures/conversation360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/conversation360/tests/conversation360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/conversation360/tests/conversation360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/conversation360/tests/conversation360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/conversation360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/conversation360/[id]/page.tsx` | Detail route. Fetches only the `conversation360` frame and passes slot data into components. |
| `app/api/360/conversation360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/conversation360/Conversation360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/conversation360/Conversation360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/conversation360/ThreadSlot.tsx` | Renders `thread` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/ParticipantsSlot.tsx` | Renders `participants` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/MessagesSlot.tsx` | Renders `messages` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/SentimentSlot.tsx` | Renders `sentiment` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/IntentsSlot.tsx` | Renders `intents` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/LinkedCasesSlot.tsx` | Renders `linkedCases` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/NextActionsSlot.tsx` | Renders `nextActions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/ComplianceSlot.tsx` | Renders `compliance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/conversation360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/conversation360/index.ts` | Component exports. |
| `lib/360/conversation360/fetchConversation360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/conversation360/conversation360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `conversationId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/conversation360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Callback 360 (`callback360`)

**Build disposition:** Domain module strong. Register as a 360 and connect scheduling/attempt/outcome events.

**Purpose:** The governed state of a callback request: who requested it, consent, scheduling window, attempts, owner, escalation path, outcome, and linked support context.

**Canonical inputs:** `callback_request`, `profile`, `conversation`, `support_case`, `agent`, `schedule`, `notification`, `consent`, `policy`, `event_signal`

**Required lenses:** `communications`, `identity`, `policy`, `execution`, `event-signal`, `risk`

**Required frame slots:** `request`, `requester`, `scheduling`, `attempts`, `owner`, `escalation`, `consent`, `outcome`, `related360s`

**Invalidating domain events:** `callback.requested`, `callback.scheduled`, `callback.attempt.started`, `callback.attempt.failed`, `callback.completed`, `callback.cancelled`

### Frame contract

```ts
export const CALLBACK360_FRAME_VERSION = '1.0.0' as const;

export interface Callback360Frame extends Frame360<Callback360Slots> {
  surface: 'callback360';
}

export interface Callback360Slots {
  request: RequestSlot;
  requester: RequesterSlot;
  scheduling: SchedulingSlot;
  attempts: AttemptsSlot;
  owner: OwnerSlot;
  escalation: EscalationSlot;
  consent: ConsentSlot;
  outcome: OutcomeSlot;
  related360s: Related360sSlot;
}

export interface Callback360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Callback360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/callback360/callback360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/callback360/callback360.controller.ts` | JSON API boundary. Exposes `GET /api/360/callback360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/callback360/callback360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/callback360/contracts/callback360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/callback360/dto/callback360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/callback360/dto/callback360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/callback360/resolvers/callback360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/callback360/projectors/callback360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/callback360/snapshots/callback360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/callback360/policies/callback360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/callback360/events/callback360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/callback360/telemetry/callback360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/callback360/fixtures/callback360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/callback360/tests/callback360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/callback360/tests/callback360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/callback360/tests/callback360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/callback360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/callback360/[id]/page.tsx` | Detail route. Fetches only the `callback360` frame and passes slot data into components. |
| `app/api/360/callback360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/callback360/Callback360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/callback360/Callback360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/callback360/RequestSlot.tsx` | Renders `request` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/RequesterSlot.tsx` | Renders `requester` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/SchedulingSlot.tsx` | Renders `scheduling` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/AttemptsSlot.tsx` | Renders `attempts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/OwnerSlot.tsx` | Renders `owner` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/EscalationSlot.tsx` | Renders `escalation` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/ConsentSlot.tsx` | Renders `consent` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/OutcomeSlot.tsx` | Renders `outcome` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/callback360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/callback360/index.ts` | Component exports. |
| `lib/360/callback360/fetchCallback360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/callback360/callback360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `callbackId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/callback360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Communications 360 (`communications360`)

**Build disposition:** Inferred from support/notifications ecosystem. Build as cross-channel parent surface for conversation/callback/support communications.

**Purpose:** Cross-channel communications control surface that unifies threads, notifications, participants, consent, delivery health, policy state, and recommended next actions.

**Canonical inputs:** `exchange_thread`, `conversation`, `message`, `notification`, `profile`, `organization`, `consent`, `channel`, `delivery_event`, `policy`

**Required lenses:** `communications`, `identity`, `policy`, `event-signal`, `risk`, `semantic-memory`

**Required frame slots:** `unifiedInbox`, `participants`, `channels`, `threads`, `notifications`, `consent`, `deliveryHealth`, `nextActions`, `related360s`

**Invalidating domain events:** `communication.sent`, `communication.delivered`, `communication.failed`, `communication.consent.changed`, `notification.created`, `notification.acknowledged`

### Frame contract

```ts
export const COMMUNICATIONS360_FRAME_VERSION = '1.0.0' as const;

export interface Communications360Frame extends Frame360<Communications360Slots> {
  surface: 'communications360';
}

export interface Communications360Slots {
  unifiedInbox: UnifiedInboxSlot;
  participants: ParticipantsSlot;
  channels: ChannelsSlot;
  threads: ThreadsSlot;
  notifications: NotificationsSlot;
  consent: ConsentSlot;
  deliveryHealth: DeliveryHealthSlot;
  nextActions: NextActionsSlot;
  related360s: Related360sSlot;
}

export interface Communications360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Communications360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/communications360/communications360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/communications360/communications360.controller.ts` | JSON API boundary. Exposes `GET /api/360/communications360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/communications360/communications360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/communications360/contracts/communications360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/communications360/dto/communications360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/communications360/dto/communications360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/communications360/resolvers/communications360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/communications360/projectors/communications360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/communications360/snapshots/communications360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/communications360/policies/communications360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/communications360/events/communications360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/communications360/telemetry/communications360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/communications360/fixtures/communications360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/communications360/tests/communications360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/communications360/tests/communications360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/communications360/tests/communications360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/communications360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/communications360/[id]/page.tsx` | Detail route. Fetches only the `communications360` frame and passes slot data into components. |
| `app/api/360/communications360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/communications360/Communications360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/communications360/Communications360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/communications360/UnifiedInboxSlot.tsx` | Renders `unifiedInbox` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/ParticipantsSlot.tsx` | Renders `participants` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/ChannelsSlot.tsx` | Renders `channels` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/ThreadsSlot.tsx` | Renders `threads` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/NotificationsSlot.tsx` | Renders `notifications` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/ConsentSlot.tsx` | Renders `consent` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/DeliveryHealthSlot.tsx` | Renders `deliveryHealth` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/NextActionsSlot.tsx` | Renders `nextActions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/communications360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/communications360/index.ts` | Component exports. |
| `lib/360/communications360/fetchCommunications360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/communications360/communications360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `communicationsId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/communications360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Trend 360 (`trend360`)

**Build disposition:** Mostly missing. Build canonical topic/trend records, topic resolver, trend projector, and dashboard.

**Purpose:** Topic-level intelligence surface showing how a trend is emerging, where it is moving, which syndicates are involved, what sentiment/signals support it, and what actions it suggests.

**Canonical inputs:** `topic`, `trend`, `event_signal`, `profile`, `community`, `campaign`, `place`, `semantic_node`, `sentiment`

**Required lenses:** `event-signal`, `semantic-memory`, `relationship`, `location`, `campaign`, `risk`, `value`

**Required frame slots:** `topic`, `timeline`, `signals`, `syndicates`, `geography`, `sentiment`, `opportunities`, `risk`, `related360s`

**Invalidating domain events:** `trend.detected`, `trend.signal.ingested`, `trend.topic.merged`, `trend.opportunity.created`, `trend.risk.updated`

### Frame contract

```ts
export const TREND360_FRAME_VERSION = '1.0.0' as const;

export interface Trend360Frame extends Frame360<Trend360Slots> {
  surface: 'trend360';
}

export interface Trend360Slots {
  topic: TopicSlot;
  timeline: TimelineSlot;
  signals: SignalsSlot;
  syndicates: SyndicatesSlot;
  geography: GeographySlot;
  sentiment: SentimentSlot;
  opportunities: OpportunitiesSlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Trend360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Trend360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/trend360/trend360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/trend360/trend360.controller.ts` | JSON API boundary. Exposes `GET /api/360/trend360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/trend360/trend360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/trend360/contracts/trend360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/trend360/dto/trend360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/trend360/dto/trend360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/trend360/resolvers/trend360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/trend360/projectors/trend360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/trend360/snapshots/trend360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/trend360/policies/trend360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/trend360/events/trend360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/trend360/telemetry/trend360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/trend360/fixtures/trend360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/trend360/tests/trend360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/trend360/tests/trend360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/trend360/tests/trend360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/trend360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/trend360/[id]/page.tsx` | Detail route. Fetches only the `trend360` frame and passes slot data into components. |
| `app/api/360/trend360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/trend360/Trend360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/trend360/Trend360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/trend360/TopicSlot.tsx` | Renders `topic` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/TimelineSlot.tsx` | Renders `timeline` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/SignalsSlot.tsx` | Renders `signals` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/SyndicatesSlot.tsx` | Renders `syndicates` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/GeographySlot.tsx` | Renders `geography` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/SentimentSlot.tsx` | Renders `sentiment` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/OpportunitiesSlot.tsx` | Renders `opportunities` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/trend360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/trend360/index.ts` | Component exports. |
| `lib/360/trend360/fetchTrend360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/trend360/trend360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `trendId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/trend360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Semantic 360 (`semantic360`)

**Build disposition:** Partial via memory/card concepts. Formalize semantic node canonical model and projection frame.

**Purpose:** Meaning-level view of a semantic node: definition, embeddings, provenance, linked memories, usage, drift, confidence, retention, and governance.

**Canonical inputs:** `semantic_node`, `memory_card`, `embedding`, `source_document`, `profile`, `agent`, `episode`, `event_signal`, `policy`

**Required lenses:** `semantic-memory`, `identity`, `event-signal`, `policy`, `risk`

**Required frame slots:** `node`, `meaning`, `embeddings`, `linkedMemories`, `provenance`, `usage`, `drift`, `governance`, `related360s`

**Invalidating domain events:** `semantic.node.created`, `semantic.embedding.updated`, `semantic.node.linked`, `semantic.drift.detected`, `semantic.node.retired`

### Frame contract

```ts
export const SEMANTIC360_FRAME_VERSION = '1.0.0' as const;

export interface Semantic360Frame extends Frame360<Semantic360Slots> {
  surface: 'semantic360';
}

export interface Semantic360Slots {
  node: NodeSlot;
  meaning: MeaningSlot;
  embeddings: EmbeddingsSlot;
  linkedMemories: LinkedMemoriesSlot;
  provenance: ProvenanceSlot;
  usage: UsageSlot;
  drift: DriftSlot;
  governance: GovernanceSlot;
  related360s: Related360sSlot;
}

export interface Semantic360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Semantic360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/semantic360/semantic360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/semantic360/semantic360.controller.ts` | JSON API boundary. Exposes `GET /api/360/semantic360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/semantic360/semantic360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/semantic360/contracts/semantic360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/semantic360/dto/semantic360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/semantic360/dto/semantic360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/semantic360/resolvers/semantic360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/semantic360/projectors/semantic360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/semantic360/snapshots/semantic360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/semantic360/policies/semantic360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/semantic360/events/semantic360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/semantic360/telemetry/semantic360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/semantic360/fixtures/semantic360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/semantic360/tests/semantic360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/semantic360/tests/semantic360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/semantic360/tests/semantic360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/semantic360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/semantic360/[id]/page.tsx` | Detail route. Fetches only the `semantic360` frame and passes slot data into components. |
| `app/api/360/semantic360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/semantic360/Semantic360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/semantic360/Semantic360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/semantic360/NodeSlot.tsx` | Renders `node` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/MeaningSlot.tsx` | Renders `meaning` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/EmbeddingsSlot.tsx` | Renders `embeddings` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/LinkedMemoriesSlot.tsx` | Renders `linkedMemories` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/ProvenanceSlot.tsx` | Renders `provenance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/UsageSlot.tsx` | Renders `usage` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/DriftSlot.tsx` | Renders `drift` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/GovernanceSlot.tsx` | Renders `governance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/semantic360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/semantic360/index.ts` | Component exports. |
| `lib/360/semantic360/fetchSemantic360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/semantic360/semantic360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `semanticId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/semantic360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Memory 360 (`memory360`)

**Build disposition:** Partial via card/memory ideas. Build as formal surface separate from Semantic360.

**Purpose:** Memory-card operating surface for durable facts, preferences, operational learnings, reminders, source provenance, confidence, retention, and policy controls.

**Canonical inputs:** `memory_card`, `semantic_node`, `profile`, `agent`, `episode`, `source_document`, `retention_policy`, `event_signal`

**Required lenses:** `semantic-memory`, `identity`, `policy`, `event-signal`, `risk`

**Required frame slots:** `card`, `source`, `semanticLinks`, `reminders`, `confidence`, `retention`, `governance`, `related360s`

**Invalidating domain events:** `memory.card.created`, `memory.card.updated`, `memory.card.linked`, `memory.confidence.changed`, `memory.retention.expired`

### Frame contract

```ts
export const MEMORY360_FRAME_VERSION = '1.0.0' as const;

export interface Memory360Frame extends Frame360<Memory360Slots> {
  surface: 'memory360';
}

export interface Memory360Slots {
  card: CardSlot;
  source: SourceSlot;
  semanticLinks: SemanticLinksSlot;
  reminders: RemindersSlot;
  confidence: ConfidenceSlot;
  retention: RetentionSlot;
  governance: GovernanceSlot;
  related360s: Related360sSlot;
}

export interface Memory360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Memory360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/memory360/memory360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/memory360/memory360.controller.ts` | JSON API boundary. Exposes `GET /api/360/memory360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/memory360/memory360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/memory360/contracts/memory360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/memory360/dto/memory360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/memory360/dto/memory360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/memory360/resolvers/memory360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/memory360/projectors/memory360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/memory360/snapshots/memory360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/memory360/policies/memory360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/memory360/events/memory360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/memory360/telemetry/memory360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/memory360/fixtures/memory360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/memory360/tests/memory360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/memory360/tests/memory360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/memory360/tests/memory360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/memory360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/memory360/[id]/page.tsx` | Detail route. Fetches only the `memory360` frame and passes slot data into components. |
| `app/api/360/memory360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/memory360/Memory360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/memory360/Memory360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/memory360/CardSlot.tsx` | Renders `card` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/SourceSlot.tsx` | Renders `source` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/SemanticLinksSlot.tsx` | Renders `semanticLinks` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/RemindersSlot.tsx` | Renders `reminders` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/ConfidenceSlot.tsx` | Renders `confidence` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/RetentionSlot.tsx` | Renders `retention` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/GovernanceSlot.tsx` | Renders `governance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/memory360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/memory360/index.ts` | Component exports. |
| `lib/360/memory360/fetchMemory360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/memory360/memory360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `memoryId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/memory360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Location 360 (`location360`)

**Build disposition:** Conceptual lens; lacks formal surface. Implement lens-backed canonical place/location event projection.

**Purpose:** Geographic intelligence surface for location events, timezone, entities in or near the location, offers/campaigns tied to the place, logistics, and risk.

**Canonical inputs:** `place`, `location_event`, `profile`, `organization`, `campaign`, `offer`, `risk_signal`, `event_signal`, `timezone_profile`

**Required lenses:** `location`, `identity`, `event-signal`, `product-offer`, `risk`, `value`

**Required frame slots:** `location`, `geography`, `nearbyEntities`, `activity`, `offers`, `risk`, `logistics`, `timezone`, `related360s`

**Invalidating domain events:** `location.event.ingested`, `location.profile.updated`, `location.risk.changed`, `location.offer.linked`

### Frame contract

```ts
export const LOCATION360_FRAME_VERSION = '1.0.0' as const;

export interface Location360Frame extends Frame360<Location360Slots> {
  surface: 'location360';
}

export interface Location360Slots {
  location: LocationSlot;
  geography: GeographySlot;
  nearbyEntities: NearbyEntitiesSlot;
  activity: ActivitySlot;
  offers: OffersSlot;
  risk: RiskSlot;
  logistics: LogisticsSlot;
  timezone: TimezoneSlot;
  related360s: Related360sSlot;
}

export interface Location360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Location360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/location360/location360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/location360/location360.controller.ts` | JSON API boundary. Exposes `GET /api/360/location360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/location360/location360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/location360/contracts/location360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/location360/dto/location360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/location360/dto/location360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/location360/resolvers/location360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/location360/projectors/location360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/location360/snapshots/location360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/location360/policies/location360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/location360/events/location360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/location360/telemetry/location360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/location360/fixtures/location360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/location360/tests/location360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/location360/tests/location360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/location360/tests/location360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/location360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/location360/[id]/page.tsx` | Detail route. Fetches only the `location360` frame and passes slot data into components. |
| `app/api/360/location360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/location360/Location360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/location360/Location360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/location360/LocationSlot.tsx` | Renders `location` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/GeographySlot.tsx` | Renders `geography` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/NearbyEntitiesSlot.tsx` | Renders `nearbyEntities` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/LogisticsSlot.tsx` | Renders `logistics` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/TimezoneSlot.tsx` | Renders `timezone` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/location360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/location360/index.ts` | Component exports. |
| `lib/360/location360/fetchLocation360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/location360/location360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `locationId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/location360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Place 360 (`place360`)

**Build disposition:** Name-normalized companion to Location360. Build if product needs place-specific entity page; otherwise alias Location360 with route redirect.

**Purpose:** Durable place profile: physical/digital place record, associated entities, observed activity, campaigns/offers, risk, logistics, and graph relationships.

**Canonical inputs:** `place`, `organization`, `profile`, `community`, `offer`, `campaign`, `location_event`, `risk_signal`, `event_signal`

**Required lenses:** `location`, `relationship`, `product-offer`, `campaign`, `risk`, `value`

**Required frame slots:** `place`, `geography`, `nearbyEntities`, `activity`, `offers`, `risk`, `logistics`, `related360s`

**Invalidating domain events:** `place.created`, `place.normalized`, `place.entity.linked`, `place.activity.recorded`, `place.risk.updated`

### Frame contract

```ts
export const PLACE360_FRAME_VERSION = '1.0.0' as const;

export interface Place360Frame extends Frame360<Place360Slots> {
  surface: 'place360';
}

export interface Place360Slots {
  place: PlaceSlot;
  geography: GeographySlot;
  nearbyEntities: NearbyEntitiesSlot;
  activity: ActivitySlot;
  offers: OffersSlot;
  risk: RiskSlot;
  logistics: LogisticsSlot;
  related360s: Related360sSlot;
}

export interface Place360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Place360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/place360/place360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/place360/place360.controller.ts` | JSON API boundary. Exposes `GET /api/360/place360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/place360/place360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/place360/contracts/place360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/place360/dto/place360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/place360/dto/place360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/place360/resolvers/place360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/place360/projectors/place360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/place360/snapshots/place360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/place360/policies/place360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/place360/events/place360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/place360/telemetry/place360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/place360/fixtures/place360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/place360/tests/place360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/place360/tests/place360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/place360/tests/place360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/place360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/place360/[id]/page.tsx` | Detail route. Fetches only the `place360` frame and passes slot data into components. |
| `app/api/360/place360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/place360/Place360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/place360/Place360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/place360/PlaceSlot.tsx` | Renders `place` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/GeographySlot.tsx` | Renders `geography` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/NearbyEntitiesSlot.tsx` | Renders `nearbyEntities` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/LogisticsSlot.tsx` | Renders `logistics` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/place360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/place360/index.ts` | Component exports. |
| `lib/360/place360/fetchPlace360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/place360/place360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `placeId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/place360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Offer 360 (`offer360`)

**Build disposition:** Partial via offers/payments/entitlements. Build coherent offer frame and connect to commerce/value/campaign surfaces.

**Purpose:** Offer-level operating surface: what is being offered, to whom, eligibility, pricing, campaign context, entitlements, conversions, fulfillment, and risk.

**Canonical inputs:** `offer`, `campaign`, `product`, `entitlement`, `profile`, `account`, `payment`, `conversion`, `event_signal`

**Required lenses:** `product-offer`, `entitlement`, `economic`, `campaign`, `identity`, `policy`, `risk`, `value`

**Required frame slots:** `offer`, `catalog`, `pricing`, `eligibility`, `entitlement`, `campaigns`, `conversion`, `fulfillment`, `risk`, `related360s`

**Invalidating domain events:** `offer.created`, `offer.eligibility.evaluated`, `offer.presented`, `offer.accepted`, `offer.converted`, `offer.expired`

### Frame contract

```ts
export const OFFER360_FRAME_VERSION = '1.0.0' as const;

export interface Offer360Frame extends Frame360<Offer360Slots> {
  surface: 'offer360';
}

export interface Offer360Slots {
  offer: OfferSlot;
  catalog: CatalogSlot;
  pricing: PricingSlot;
  eligibility: EligibilitySlot;
  entitlement: EntitlementSlot;
  campaigns: CampaignsSlot;
  conversion: ConversionSlot;
  fulfillment: FulfillmentSlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Offer360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Offer360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/offer360/offer360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/offer360/offer360.controller.ts` | JSON API boundary. Exposes `GET /api/360/offer360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/offer360/offer360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/offer360/contracts/offer360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/offer360/dto/offer360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/offer360/dto/offer360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/offer360/resolvers/offer360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/offer360/projectors/offer360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/offer360/snapshots/offer360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/offer360/policies/offer360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/offer360/events/offer360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/offer360/telemetry/offer360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/offer360/fixtures/offer360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/offer360/tests/offer360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/offer360/tests/offer360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/offer360/tests/offer360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/offer360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/offer360/[id]/page.tsx` | Detail route. Fetches only the `offer360` frame and passes slot data into components. |
| `app/api/360/offer360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/offer360/Offer360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/offer360/Offer360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/offer360/OfferSlot.tsx` | Renders `offer` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/CatalogSlot.tsx` | Renders `catalog` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/PricingSlot.tsx` | Renders `pricing` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/EligibilitySlot.tsx` | Renders `eligibility` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/EntitlementSlot.tsx` | Renders `entitlement` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/CampaignsSlot.tsx` | Renders `campaigns` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/ConversionSlot.tsx` | Renders `conversion` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/FulfillmentSlot.tsx` | Renders `fulfillment` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/offer360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/offer360/index.ts` | Component exports. |
| `lib/360/offer360/fetchOffer360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/offer360/offer360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `offerId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/offer360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Commerce 360 (`commerce360`)

**Build disposition:** Partial through payments/subscriptions/offer concepts. Build as commercial operating parent surface.

**Purpose:** Commercial view of catalog, offers, payments, subscriptions, invoices, entitlements, conversions, fulfillment, and financial risk.

**Canonical inputs:** `product`, `offer`, `campaign`, `payment`, `subscription`, `invoice`, `entitlement`, `profile`, `account`, `event_signal`

**Required lenses:** `product-offer`, `economic`, `entitlement`, `campaign`, `identity`, `risk`, `value`

**Required frame slots:** `commerceSummary`, `catalog`, `offers`, `payments`, `subscriptions`, `entitlements`, `conversion`, `fulfillment`, `risk`, `related360s`

**Invalidating domain events:** `commerce.payment.created`, `commerce.invoice.issued`, `commerce.subscription.updated`, `commerce.entitlement.granted`, `commerce.refund.created`

### Frame contract

```ts
export const COMMERCE360_FRAME_VERSION = '1.0.0' as const;

export interface Commerce360Frame extends Frame360<Commerce360Slots> {
  surface: 'commerce360';
}

export interface Commerce360Slots {
  commerceSummary: CommerceSummarySlot;
  catalog: CatalogSlot;
  offers: OffersSlot;
  payments: PaymentsSlot;
  subscriptions: SubscriptionsSlot;
  entitlements: EntitlementsSlot;
  conversion: ConversionSlot;
  fulfillment: FulfillmentSlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Commerce360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Commerce360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/commerce360/commerce360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/commerce360/commerce360.controller.ts` | JSON API boundary. Exposes `GET /api/360/commerce360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/commerce360/commerce360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/commerce360/contracts/commerce360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/commerce360/dto/commerce360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/commerce360/dto/commerce360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/commerce360/resolvers/commerce360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/commerce360/projectors/commerce360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/commerce360/snapshots/commerce360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/commerce360/policies/commerce360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/commerce360/events/commerce360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/commerce360/telemetry/commerce360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/commerce360/fixtures/commerce360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/commerce360/tests/commerce360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/commerce360/tests/commerce360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/commerce360/tests/commerce360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/commerce360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/commerce360/[id]/page.tsx` | Detail route. Fetches only the `commerce360` frame and passes slot data into components. |
| `app/api/360/commerce360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/commerce360/Commerce360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/commerce360/Commerce360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/commerce360/CommerceSummarySlot.tsx` | Renders `commerceSummary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/CatalogSlot.tsx` | Renders `catalog` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/PaymentsSlot.tsx` | Renders `payments` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/SubscriptionsSlot.tsx` | Renders `subscriptions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/EntitlementsSlot.tsx` | Renders `entitlements` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/ConversionSlot.tsx` | Renders `conversion` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/FulfillmentSlot.tsx` | Renders `fulfillment` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/commerce360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/commerce360/index.ts` | Component exports. |
| `lib/360/commerce360/fetchCommerce360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/commerce360/commerce360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `commerceId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/commerce360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Product 360 (`product360`)

**Build disposition:** Not explicit in earlier target list but required to support commerce/offer/product graph. Build as product-level projection.

**Purpose:** Product-level operating surface connecting product definition, usage, offers, entitlements, revenue, conversions, and risk.

**Canonical inputs:** `product`, `offer`, `campaign`, `entitlement`, `usage_event`, `payment`, `profile`, `account`, `event_signal`

**Required lenses:** `product-offer`, `economic`, `entitlement`, `campaign`, `event-signal`, `risk`, `value`

**Required frame slots:** `product`, `catalog`, `usage`, `offers`, `entitlements`, `revenue`, `conversion`, `risk`, `related360s`

**Invalidating domain events:** `product.created`, `product.catalog.updated`, `product.usage.recorded`, `product.offer.linked`, `product.revenue.updated`

### Frame contract

```ts
export const PRODUCT360_FRAME_VERSION = '1.0.0' as const;

export interface Product360Frame extends Frame360<Product360Slots> {
  surface: 'product360';
}

export interface Product360Slots {
  product: ProductSlot;
  catalog: CatalogSlot;
  usage: UsageSlot;
  offers: OffersSlot;
  entitlements: EntitlementsSlot;
  revenue: RevenueSlot;
  conversion: ConversionSlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Product360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Product360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/product360/product360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/product360/product360.controller.ts` | JSON API boundary. Exposes `GET /api/360/product360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/product360/product360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/product360/contracts/product360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/product360/dto/product360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/product360/dto/product360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/product360/resolvers/product360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/product360/projectors/product360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/product360/snapshots/product360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/product360/policies/product360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/product360/events/product360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/product360/telemetry/product360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/product360/fixtures/product360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/product360/tests/product360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/product360/tests/product360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/product360/tests/product360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/product360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/product360/[id]/page.tsx` | Detail route. Fetches only the `product360` frame and passes slot data into components. |
| `app/api/360/product360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/product360/Product360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/product360/Product360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/product360/ProductSlot.tsx` | Renders `product` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/CatalogSlot.tsx` | Renders `catalog` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/UsageSlot.tsx` | Renders `usage` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/EntitlementsSlot.tsx` | Renders `entitlements` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/RevenueSlot.tsx` | Renders `revenue` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/ConversionSlot.tsx` | Renders `conversion` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/product360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/product360/index.ts` | Component exports. |
| `lib/360/product360/fetchProduct360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/product360/product360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `productId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/product360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Campaign 360 (`campaign360`)

**Build disposition:** In-flight/product-critical based on prior Aether language work. Build or normalize as Signals-centered, not audience-centered.

**Purpose:** Campaign intelligence surface: Signals, channels, journeys, offers, performance, budget, attribution/value, compliance, and related profiles/accounts.

**Canonical inputs:** `campaign`, `offer`, `profile`, `account`, `journey`, `touchpoint`, `conversion`, `payment`, `event_signal`, `policy`

**Required lenses:** `campaign`, `event-signal`, `identity`, `economic`, `product-offer`, `policy`, `risk`, `value`

**Required frame slots:** `campaign`, `signals`, `offers`, `channels`, `journeys`, `performance`, `budget`, `compliance`, `value`, `related360s`

**Invalidating domain events:** `campaign.created`, `campaign.signal.linked`, `campaign.touchpoint.recorded`, `campaign.conversion.recorded`, `campaign.budget.updated`, `campaign.paused`

### Frame contract

```ts
export const CAMPAIGN360_FRAME_VERSION = '1.0.0' as const;

export interface Campaign360Frame extends Frame360<Campaign360Slots> {
  surface: 'campaign360';
}

export interface Campaign360Slots {
  campaign: CampaignSlot;
  signals: SignalsSlot;
  offers: OffersSlot;
  channels: ChannelsSlot;
  journeys: JourneysSlot;
  performance: PerformanceSlot;
  budget: BudgetSlot;
  compliance: ComplianceSlot;
  value: ValueSlot;
  related360s: Related360sSlot;
}

export interface Campaign360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Campaign360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/campaign360/campaign360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/campaign360/campaign360.controller.ts` | JSON API boundary. Exposes `GET /api/360/campaign360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/campaign360/campaign360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/campaign360/contracts/campaign360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/campaign360/dto/campaign360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/campaign360/dto/campaign360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/campaign360/resolvers/campaign360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/campaign360/projectors/campaign360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/campaign360/snapshots/campaign360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/campaign360/policies/campaign360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/campaign360/events/campaign360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/campaign360/telemetry/campaign360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/campaign360/fixtures/campaign360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/campaign360/tests/campaign360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/campaign360/tests/campaign360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/campaign360/tests/campaign360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/campaign360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/campaign360/[id]/page.tsx` | Detail route. Fetches only the `campaign360` frame and passes slot data into components. |
| `app/api/360/campaign360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/campaign360/Campaign360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/campaign360/Campaign360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/campaign360/CampaignSlot.tsx` | Renders `campaign` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/SignalsSlot.tsx` | Renders `signals` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/ChannelsSlot.tsx` | Renders `channels` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/JourneysSlot.tsx` | Renders `journeys` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/PerformanceSlot.tsx` | Renders `performance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/BudgetSlot.tsx` | Renders `budget` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/ComplianceSlot.tsx` | Renders `compliance` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/ValueSlot.tsx` | Renders `value` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/campaign360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/campaign360/index.ts` | Component exports. |
| `lib/360/campaign360/fetchCampaign360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/campaign360/campaign360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `campaignId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/campaign360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Value 360 (`value360`)

**Build disposition:** Partial through economic/payment concepts. Replace generic Economic360/Business Value language with Value360 frame.

**Purpose:** Economic truth surface that reconciles revenue, payments, subscriptions, invoices, attribution credits, value forecasts, and risk.

**Canonical inputs:** `value_event`, `payment`, `invoice`, `subscription`, `account`, `profile`, `campaign`, `offer`, `conversion`, `attribution_credit`, `event_signal`

**Required lenses:** `value`, `economic`, `campaign`, `identity`, `product-offer`, `entitlement`, `risk`

**Required frame slots:** `economicSummary`, `accounts`, `payments`, `invoices`, `subscriptions`, `offers`, `attribution`, `forecast`, `risk`, `related360s`

**Invalidating domain events:** `value.event.recorded`, `value.payment.settled`, `value.attribution.assigned`, `value.forecast.updated`, `value.risk.changed`

### Frame contract

```ts
export const VALUE360_FRAME_VERSION = '1.0.0' as const;

export interface Value360Frame extends Frame360<Value360Slots> {
  surface: 'value360';
}

export interface Value360Slots {
  economicSummary: EconomicSummarySlot;
  accounts: AccountsSlot;
  payments: PaymentsSlot;
  invoices: InvoicesSlot;
  subscriptions: SubscriptionsSlot;
  offers: OffersSlot;
  attribution: AttributionSlot;
  forecast: ForecastSlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Value360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Value360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/value360/value360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/value360/value360.controller.ts` | JSON API boundary. Exposes `GET /api/360/value360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/value360/value360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/value360/contracts/value360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/value360/dto/value360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/value360/dto/value360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/value360/resolvers/value360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/value360/projectors/value360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/value360/snapshots/value360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/value360/policies/value360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/value360/events/value360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/value360/telemetry/value360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/value360/fixtures/value360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/value360/tests/value360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/value360/tests/value360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/value360/tests/value360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/value360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/value360/[id]/page.tsx` | Detail route. Fetches only the `value360` frame and passes slot data into components. |
| `app/api/360/value360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/value360/Value360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/value360/Value360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/value360/EconomicSummarySlot.tsx` | Renders `economicSummary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/AccountsSlot.tsx` | Renders `accounts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/PaymentsSlot.tsx` | Renders `payments` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/InvoicesSlot.tsx` | Renders `invoices` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/SubscriptionsSlot.tsx` | Renders `subscriptions` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/OffersSlot.tsx` | Renders `offers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/AttributionSlot.tsx` | Renders `attribution` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/ForecastSlot.tsx` | Renders `forecast` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/value360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/value360/index.ts` | Component exports. |
| `lib/360/value360/fetchValue360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/value360/value360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `valueId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/value360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Workflow 360 (`workflow360`)

**Build disposition:** Partial via orchestration/jobs/adaptive-learning/agency-surface modules. Formalize workflow frame.

**Purpose:** Workflow-level operating surface for triggers, run history, step reliability, participating agents, schedules, artifacts, policy, and outcomes.

**Canonical inputs:** `workflow`, `workflow_run`, `automation`, `schedule`, `agent`, `execution_artifact`, `policy`, `event_signal`, `notification`

**Required lenses:** `execution`, `policy`, `event-signal`, `identity`, `semantic-memory`, `risk`, `value`

**Required frame slots:** `workflow`, `triggers`, `runs`, `steps`, `agents`, `schedules`, `artifacts`, `policy`, `reliability`, `related360s`

**Invalidating domain events:** `workflow.created`, `workflow.triggered`, `workflow.run.started`, `workflow.run.completed`, `workflow.run.failed`, `workflow.schedule.updated`

### Frame contract

```ts
export const WORKFLOW360_FRAME_VERSION = '1.0.0' as const;

export interface Workflow360Frame extends Frame360<Workflow360Slots> {
  surface: 'workflow360';
}

export interface Workflow360Slots {
  workflow: WorkflowSlot;
  triggers: TriggersSlot;
  runs: RunsSlot;
  steps: StepsSlot;
  agents: AgentsSlot;
  schedules: SchedulesSlot;
  artifacts: ArtifactsSlot;
  policy: PolicySlot;
  reliability: ReliabilitySlot;
  related360s: Related360sSlot;
}

export interface Workflow360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Workflow360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/workflow360/workflow360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/workflow360/workflow360.controller.ts` | JSON API boundary. Exposes `GET /api/360/workflow360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/workflow360/workflow360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/workflow360/contracts/workflow360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/workflow360/dto/workflow360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/workflow360/dto/workflow360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/workflow360/resolvers/workflow360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/workflow360/projectors/workflow360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/workflow360/snapshots/workflow360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/workflow360/policies/workflow360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/workflow360/events/workflow360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/workflow360/telemetry/workflow360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/workflow360/fixtures/workflow360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/workflow360/tests/workflow360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/workflow360/tests/workflow360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/workflow360/tests/workflow360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/workflow360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/workflow360/[id]/page.tsx` | Detail route. Fetches only the `workflow360` frame and passes slot data into components. |
| `app/api/360/workflow360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/workflow360/Workflow360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/workflow360/Workflow360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/workflow360/WorkflowSlot.tsx` | Renders `workflow` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/TriggersSlot.tsx` | Renders `triggers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/RunsSlot.tsx` | Renders `runs` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/StepsSlot.tsx` | Renders `steps` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/AgentsSlot.tsx` | Renders `agents` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/SchedulesSlot.tsx` | Renders `schedules` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/ArtifactsSlot.tsx` | Renders `artifacts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/ReliabilitySlot.tsx` | Renders `reliability` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/workflow360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/workflow360/index.ts` | Component exports. |
| `lib/360/workflow360/fetchWorkflow360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/workflow360/workflow360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `workflowId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/workflow360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Automation 360 (`automation360`)

**Build disposition:** Usually overlaps Workflow360. Build as automation-specific page or alias depending on product navigation.

**Purpose:** Automation-specific operating view: trigger definitions, schedules, runs, agents, failures, notifications, governance, and reliability.

**Canonical inputs:** `automation`, `workflow`, `workflow_run`, `schedule`, `agent`, `execution_artifact`, `policy`, `notification`, `event_signal`

**Required lenses:** `execution`, `policy`, `event-signal`, `identity`, `risk`, `value`

**Required frame slots:** `automation`, `triggers`, `runs`, `steps`, `agents`, `schedules`, `artifacts`, `policy`, `reliability`, `related360s`

**Invalidating domain events:** `automation.created`, `automation.enabled`, `automation.disabled`, `automation.triggered`, `automation.failed`, `automation.completed`

### Frame contract

```ts
export const AUTOMATION360_FRAME_VERSION = '1.0.0' as const;

export interface Automation360Frame extends Frame360<Automation360Slots> {
  surface: 'automation360';
}

export interface Automation360Slots {
  automation: AutomationSlot;
  triggers: TriggersSlot;
  runs: RunsSlot;
  steps: StepsSlot;
  agents: AgentsSlot;
  schedules: SchedulesSlot;
  artifacts: ArtifactsSlot;
  policy: PolicySlot;
  reliability: ReliabilitySlot;
  related360s: Related360sSlot;
}

export interface Automation360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Automation360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/automation360/automation360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/automation360/automation360.controller.ts` | JSON API boundary. Exposes `GET /api/360/automation360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/automation360/automation360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/automation360/contracts/automation360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/automation360/dto/automation360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/automation360/dto/automation360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/automation360/resolvers/automation360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/automation360/projectors/automation360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/automation360/snapshots/automation360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/automation360/policies/automation360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/automation360/events/automation360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/automation360/telemetry/automation360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/automation360/fixtures/automation360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/automation360/tests/automation360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/automation360/tests/automation360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/automation360/tests/automation360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/automation360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/automation360/[id]/page.tsx` | Detail route. Fetches only the `automation360` frame and passes slot data into components. |
| `app/api/360/automation360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/automation360/Automation360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/automation360/Automation360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/automation360/AutomationSlot.tsx` | Renders `automation` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/TriggersSlot.tsx` | Renders `triggers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/RunsSlot.tsx` | Renders `runs` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/StepsSlot.tsx` | Renders `steps` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/AgentsSlot.tsx` | Renders `agents` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/SchedulesSlot.tsx` | Renders `schedules` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/ArtifactsSlot.tsx` | Renders `artifacts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/ReliabilitySlot.tsx` | Renders `reliability` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/automation360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/automation360/index.ts` | Component exports. |
| `lib/360/automation360/fetchAutomation360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/automation360/automation360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `automationId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/automation360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Account 360 (`account360`)

**Build disposition:** Required by tenant/account productization; may be missing. Build as B2B account operating surface.

**Purpose:** Account/organization-level surface covering users, entitlements, billing, usage, support health, policy, and risk.

**Canonical inputs:** `account`, `organization`, `profile`, `entitlement`, `subscription`, `invoice`, `payment`, `support_case`, `risk_signal`, `event_signal`

**Required lenses:** `identity`, `relationship`, `economic`, `entitlement`, `policy`, `communications`, `risk`, `value`

**Required frame slots:** `account`, `organization`, `users`, `entitlements`, `billing`, `supportHealth`, `activity`, `risk`, `related360s`

**Invalidating domain events:** `account.created`, `account.member.added`, `account.entitlement.changed`, `account.billing.updated`, `account.risk.changed`

### Frame contract

```ts
export const ACCOUNT360_FRAME_VERSION = '1.0.0' as const;

export interface Account360Frame extends Frame360<Account360Slots> {
  surface: 'account360';
}

export interface Account360Slots {
  account: AccountSlot;
  organization: OrganizationSlot;
  users: UsersSlot;
  entitlements: EntitlementsSlot;
  billing: BillingSlot;
  supportHealth: SupportHealthSlot;
  activity: ActivitySlot;
  risk: RiskSlot;
  related360s: Related360sSlot;
}

export interface Account360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Account360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/account360/account360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/account360/account360.controller.ts` | JSON API boundary. Exposes `GET /api/360/account360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/account360/account360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/account360/contracts/account360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/account360/dto/account360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/account360/dto/account360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/account360/resolvers/account360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/account360/projectors/account360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/account360/snapshots/account360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/account360/policies/account360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/account360/events/account360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/account360/telemetry/account360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/account360/fixtures/account360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/account360/tests/account360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/account360/tests/account360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/account360/tests/account360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/account360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/account360/[id]/page.tsx` | Detail route. Fetches only the `account360` frame and passes slot data into components. |
| `app/api/360/account360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/account360/Account360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/account360/Account360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/account360/AccountSlot.tsx` | Renders `account` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/OrganizationSlot.tsx` | Renders `organization` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/UsersSlot.tsx` | Renders `users` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/EntitlementsSlot.tsx` | Renders `entitlements` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/BillingSlot.tsx` | Renders `billing` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/SupportHealthSlot.tsx` | Renders `supportHealth` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/ActivitySlot.tsx` | Renders `activity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/RiskSlot.tsx` | Renders `risk` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/account360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/account360/index.ts` | Component exports. |
| `lib/360/account360/fetchAccount360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/account360/account360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `accountId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/account360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Identity 360 (`identity360`)

**Build disposition:** Core lens exists conceptually; surface may be missing. Build as administrative/governance surface for identity resolution.

**Purpose:** Identity-resolution control surface for identifiers, profiles, accounts, devices, verification, consent, merges/splits, policy, and auditability.

**Canonical inputs:** `identity`, `profile`, `account`, `identifier`, `device`, `consent`, `verification`, `merge_record`, `policy`, `event_signal`

**Required lenses:** `identity`, `relationship`, `policy`, `risk`, `event-signal`

**Required frame slots:** `identity`, `identifiers`, `profiles`, `accounts`, `devices`, `verification`, `consent`, `merges`, `policy`, `related360s`

**Invalidating domain events:** `identity.created`, `identity.identifier.added`, `identity.profile.merged`, `identity.profile.split`, `identity.consent.changed`, `identity.verified`

### Frame contract

```ts
export const IDENTITY360_FRAME_VERSION = '1.0.0' as const;

export interface Identity360Frame extends Frame360<Identity360Slots> {
  surface: 'identity360';
}

export interface Identity360Slots {
  identity: IdentitySlot;
  identifiers: IdentifiersSlot;
  profiles: ProfilesSlot;
  accounts: AccountsSlot;
  devices: DevicesSlot;
  verification: VerificationSlot;
  consent: ConsentSlot;
  merges: MergesSlot;
  policy: PolicySlot;
  related360s: Related360sSlot;
}

export interface Identity360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Identity360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/identity360/identity360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/identity360/identity360.controller.ts` | JSON API boundary. Exposes `GET /api/360/identity360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/identity360/identity360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/identity360/contracts/identity360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/identity360/dto/identity360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/identity360/dto/identity360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/identity360/resolvers/identity360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/identity360/projectors/identity360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/identity360/snapshots/identity360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/identity360/policies/identity360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/identity360/events/identity360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/identity360/telemetry/identity360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/identity360/fixtures/identity360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/identity360/tests/identity360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/identity360/tests/identity360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/identity360/tests/identity360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/identity360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/identity360/[id]/page.tsx` | Detail route. Fetches only the `identity360` frame and passes slot data into components. |
| `app/api/360/identity360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/identity360/Identity360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/identity360/Identity360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/identity360/IdentitySlot.tsx` | Renders `identity` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/IdentifiersSlot.tsx` | Renders `identifiers` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/ProfilesSlot.tsx` | Renders `profiles` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/AccountsSlot.tsx` | Renders `accounts` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/DevicesSlot.tsx` | Renders `devices` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/VerificationSlot.tsx` | Renders `verification` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/ConsentSlot.tsx` | Renders `consent` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/MergesSlot.tsx` | Renders `merges` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/PolicySlot.tsx` | Renders `policy` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/identity360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/identity360/index.ts` | Component exports. |
| `lib/360/identity360/fetchIdentity360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/identity360/identity360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `identityId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/identity360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


## Risk 360 (`risk360`)

**Build disposition:** Risk retained as product language but likely underbuilt. Build as cross-surface risk projection and policy audit page.

**Purpose:** Cross-system risk surface for anomalies, policy findings, exposure, mitigations, audit evidence, and affected 360s.

**Canonical inputs:** `risk_signal`, `policy_finding`, `audit_event`, `profile`, `account`, `agent`, `execution_artifact`, `campaign`, `payment`, `event_signal`

**Required lenses:** `risk`, `policy`, `identity`, `execution`, `economic`, `event-signal`

**Required frame slots:** `riskSummary`, `policyFindings`, `anomalies`, `exposure`, `mitigations`, `auditTrail`, `related360s`

**Invalidating domain events:** `risk.signal.detected`, `risk.finding.created`, `risk.mitigation.created`, `risk.mitigation.completed`, `risk.finding.closed`

### Frame contract

```ts
export const RISK360_FRAME_VERSION = '1.0.0' as const;

export interface Risk360Frame extends Frame360<Risk360Slots> {
  surface: 'risk360';
}

export interface Risk360Slots {
  riskSummary: RiskSummarySlot;
  policyFindings: PolicyFindingsSlot;
  anomalies: AnomaliesSlot;
  exposure: ExposureSlot;
  mitigations: MitigationsSlot;
  auditTrail: AuditTrailSlot;
  related360s: Related360sSlot;
}

export interface Risk360Query extends Surface360Query {
  canonicalId: string;
  tenantId: string;
  asOf?: string;
  include?: Array<keyof Risk360Slots>;
  forceFresh?: boolean;
  explain?: boolean;
}
```

### Backend module files

| File | Build responsibility |
|---|---|
| `src/modules/risk360/risk360.module.ts` | Nest module wiring for controller, service, resolver, projector, snapshot repo, policy gate, lens clients, and event subscribers. |
| `src/modules/risk360/risk360.controller.ts` | JSON API boundary. Exposes `GET /api/360/risk360/:id`, `GET /snapshot`, `POST /rebuild`, and optional lens drilldowns. No domain writes. |
| `src/modules/risk360/risk360.service.ts` | Application service. Loads cached snapshot when valid; otherwise invokes resolver/projector; enforces policy; returns frame DTO. |
| `src/modules/risk360/contracts/risk360.contract.ts` | Public surface contract: query type, frame version, slot keys, included lenses, source refs, freshness, redaction contract, errors. |
| `src/modules/risk360/dto/risk360-frame.dto.ts` | Backend-to-frontend frame DTO. This is the only response object the dashboard reads. |
| `src/modules/risk360/dto/risk360-query.dto.ts` | Query params: `tenantId`, `asOf`, `include`, `slot`, `forceFresh`, `explain`, `redactionMode`. |
| `src/modules/risk360/resolvers/risk360.resolver.ts` | Canonical source resolver. Loads source records and related graph IDs; never writes canonical records. |
| `src/modules/risk360/projectors/risk360.projector.ts` | Composes lens results into deterministic frame slots. No hidden IO beyond declared lens calls. |
| `src/modules/risk360/snapshots/risk360.snapshot.repository.ts` | Reads/writes projection snapshots keyed by tenant, surface, canonical ID, frame version, lens/source hash. |
| `src/modules/risk360/policies/risk360.policy.ts` | Surface-specific policy constraints and redaction overlays on top of global policy lens. |
| `src/modules/risk360/events/risk360.events.ts` | Event names that can invalidate or rebuild this surface. |
| `src/modules/risk360/telemetry/risk360.telemetry.ts` | Metrics: build latency, lens latency, snapshot hit rate, redaction count, stale frame count, error count. |
| `src/modules/risk360/fixtures/risk360.fixture.ts` | Canonical records and event-signal fixture set for local/dev/contract tests. |
| `src/modules/risk360/tests/risk360.resolver.spec.ts` | Verifies canonical source resolution, missing vs empty vs zero semantics, and tenant isolation. |
| `src/modules/risk360/tests/risk360.projector.spec.ts` | Verifies slot composition, deterministic ordering, policy overlays, and partial-degradation handling. |
| `src/modules/risk360/tests/risk360.service.spec.ts` | Verifies snapshot use, rebuild behavior, freshness, and error mapping. |

### Frontend files

| File | Build responsibility |
|---|---|
| `app/(dashboard)/risk360/page.tsx` | Collection/list route for the surface with filters, search, recently viewed, and readiness indicators. |
| `app/(dashboard)/risk360/[id]/page.tsx` | Detail route. Fetches only the `risk360` frame and passes slot data into components. |
| `app/api/360/risk360/[id]/route.ts` | Next route proxy if the frontend consumes the Nest API through app-router handlers. |
| `components/360/risk360/Risk360Shell.tsx` | Surface shell: header, freshness banner, policy banner, related-360 rail, slot layout. |
| `components/360/risk360/Risk360Header.tsx` | Surface identity/header block with canonical ID, generated timestamp, source count, and readiness state. |
| `components/360/risk360/RiskSummarySlot.tsx` | Renders `riskSummary` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/PolicyFindingsSlot.tsx` | Renders `policyFindings` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/AnomaliesSlot.tsx` | Renders `anomalies` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/ExposureSlot.tsx` | Renders `exposure` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/MitigationsSlot.tsx` | Renders `mitigations` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/AuditTrailSlot.tsx` | Renders `auditTrail` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/Related360sSlot.tsx` | Renders `related360s` slot with loading, empty, stale, redacted, and error states. |
| `components/360/risk360/Related360Rail.tsx` | Cross-links to connected profile/account/agent/episode/execution/campaign/value/risk surfaces. |
| `components/360/risk360/index.ts` | Component exports. |
| `lib/360/risk360/fetchRisk360.ts` | Typed frame fetcher with abort, retry, stale handling, and error shape normalization. |
| `test/components/360/risk360/risk360.render.spec.tsx` | UI contract test for each slot state and required data-testid coverage. |

### Surface-specific resolver build

1. Resolve tenant-scoped canonical source record by `riskId` or canonical ID alias.
2. Resolve related IDs through graph edges declared in the registry entry, not through ad hoc joins in the UI.
3. Call lenses in dependency order: identity/account first, policy/entitlement second, domain-specific lenses third, risk/value last.
4. Return a `ResolverBundle` containing source records, graph refs, requested lens contexts, freshness inputs, and explainability trace.
5. Preserve typed degradation:
   - `missing`: source record expected but absent.
   - `empty`: source record valid but no related rows.
   - `zero`: valid numeric zero.
   - `redacted`: policy removed value.
   - `stale`: snapshot or lens result outside freshness SLA.

### Surface-specific projector build

1. Convert the resolver bundle into exactly the required frame slots.
2. Attach `sourceRecords` and `lenses` metadata at frame root and per slot.
3. Produce deterministic slot ordering and deterministic list ordering.
4. Include `related360s` as typed links: `surface`, `canonicalId`, `label`, `relationship`, `strength`, `policyState`.
5. Never compute product decisions directly in UI components; decisions are backend-projected with explanation metadata.

### Acceptance criteria

- `GET /api/360/risk360/:id` returns the typed frame with all required slots.
- Every slot has loading, error, empty, redacted, stale, and hydrated UI states.
- Contract test fails when a slot exists in DTO but not UI, or UI expects a slot not present in DTO.
- Resolver test proves tenant isolation and no direct canonical writes.
- Projector test proves deterministic output from the fixture.
- Snapshot test proves cache hit, stale rebuild, force rebuild, and source-hash invalidation.
- Policy test proves restricted fields are redacted before leaving backend.
- Related-360 rail links to every graph-related surface declared by the registry entry.


---

## 10. Cross-surface relationship map

The related-360 rail must be generated from canonical edges and registry declarations. It is not a hand-authored navigation list.

| Source surface | Must link to |
|---|---|
| `profile360` | `identity360`, `account360`, `social360`, `conversation360`, `support360`, `offer360`, `campaign360`, `value360`, `risk360` |
| `agent360` | `execution360`, `episode360`, `workflow360`, `automation360`, `semantic360`, `risk360` |
| `execution360` | `agent360`, `episode360`, `workflow360`, `automation360`, `value360`, `risk360` |
| `episode360` | `profile360`, `agent360`, `execution360`, `conversation360`, `support360`, `value360`, `risk360` |
| `campaign360` | `profile360`, `account360`, `offer360`, `product360`, journey/profile-related surfaces, `value360`, `risk360` |
| `value360` | `account360`, `profile360`, `campaign360`, `offer360`, `commerce360`, `product360`, `risk360` |
| `support360` | `profile360`, `account360`, `conversation360`, `callback360`, `episode360`, `communications360`, `risk360` |
| `conversation360` | `profile360`, `support360`, `callback360`, `episode360`, `communications360`, `semantic360` |
| `social360` | `profile360`, `community360`, `trend360`, `campaign360`, `risk360` |
| `community360` | `social360`, `profile360`, `trend360`, `campaign360`, `risk360` |
| `trend360` | `social360`, `community360`, `campaign360`, `location360`, `semantic360`, `risk360` |
| `semantic360` | `memory360`, `agent360`, `episode360`, `conversation360`, `trend360` |
| `memory360` | `semantic360`, `profile360`, `agent360`, `episode360` |
| `location360` | `place360`, `profile360`, `account360`, `campaign360`, `offer360`, `risk360` |
| `offer360` | `campaign360`, `commerce360`, `product360`, `profile360`, `account360`, `value360`, `risk360` |
| `workflow360` | `automation360`, `agent360`, `execution360`, `episode360`, `risk360` |
| `identity360` | `profile360`, `account360`, `risk360`, `communications360` |
| `risk360` | All surfaces that contribute risk signals or policy findings. |

---

## 11. Build sequence

### Phase 0 — inventory guardrails

**Files**

- `docs/architecture/360/README.md`
- `docs/architecture/360/registry.md`
- `src/modules/experience360/contracts/*.ts`
- `src/modules/experience360/experience360.registry.ts`
- `test/contract/360/registry.contract.spec.ts`

**Exit criteria**

- Registry compiles.
- Surface union and lens union compile.
- Contract test fails for every missing surface file.
- Readiness status is explicit for each surface.

### Phase 1 — experience360 spine

**Files**

- `src/modules/experience360/experience360.module.ts`
- `src/modules/experience360/experience360.controller.ts`
- `src/modules/experience360/experience360.service.ts`
- `src/modules/experience360/snapshots/experience360-snapshot.repository.ts`
- `src/modules/experience360/freshness/source-hash.service.ts`
- `src/modules/experience360/policies/experience360-policy.service.ts`
- migrations for projection snapshots and lens cache.

**Exit criteria**

- Generic API can dispatch to a mocked surface resolver/projector.
- Snapshot table can store and retrieve a mocked frame.
- Policy service can redact a mocked field.
- Freshness service can mark a frame stale.

### Phase 2 — core lenses

**Files**

- All `src/modules/graph-lenses/*` folders.
- Lens fixtures and tests.

**Exit criteria**

- Each lens returns `LensResult<T>`.
- Each lens supports source refs, confidence, explanations, policy state, and degradation.
- Lens tests cover tenant isolation and typed degradation.

### Phase 3 — normalize existing deep surfaces

**Surfaces**

- `agent360`
- `execution360`
- `episode360`
- `profile360`

**Exit criteria**

- All four surfaces pass API contract tests.
- All four surfaces have dashboard routes and slot components.
- Existing partial files are wrapped or migrated into resolver/projector/snapshot pattern.
- No UI page reads canonical services directly.

### Phase 4 — support and communications surfaces

**Surfaces**

- `support360`
- `conversation360`
- `callback360`
- `communications360`

**Exit criteria**

- Existing support/conversation/callback modules are registered as 360 surfaces.
- Consent, policy, delivery state, escalation, and outcome slots render correctly.
- Cross-links among support, conversation, callback, profile, account, and episode surfaces work.

### Phase 5 — social, semantic, trend, location

**Surfaces**

- `social360`
- `community360`
- `trend360`
- `semantic360`
- `memory360`
- `location360`
- `place360`

**Exit criteria**

- Social/community graph edges are generated by relationship lens.
- Trend/topic surfaces are driven by event-signal and semantic lenses.
- Semantic/memory surfaces expose provenance, confidence, retention, and drift.
- Location/place surfaces normalize geography and timezone.

### Phase 6 — commerce, campaign, value, account, identity, risk

**Surfaces**

- `offer360`
- `commerce360`
- `product360`
- `campaign360`
- `value360`
- `account360`
- `identity360`
- `risk360`

**Exit criteria**

- Offer/product/campaign/value frames reconcile without duplicate economic logic.
- Campaign 360 uses `Signals`, not legacy audience-centric naming.
- Value 360 replaces generic Economic360/Business Value phrasing.
- Account 360 consolidates organization/users/entitlements/billing/support health.
- Identity 360 exposes merge/split/consent/verification state.
- Risk 360 can aggregate findings across every other surface.

### Phase 7 — workflow and automation

**Surfaces**

- `workflow360`
- `automation360`

**Exit criteria**

- Workflow and automation projections read from orchestration/jobs/runtime artifacts.
- Runs, schedules, agents, policies, failures, and reliability are visible.
- Agent360 and Execution360 cross-link correctly.

### Phase 8 — hardening

**Files**

- `test/e2e/360/*.e2e-spec.ts`
- `test/performance/360/*.perf-spec.ts`
- `docs/architecture/360/operability.md`
- `docs/architecture/360/security.md`

**Exit criteria**

- Full 360 registry contract passes.
- All frame APIs return within target latency for cached and uncached paths.
- Snapshot hit rate is observable.
- Redaction telemetry is observable.
- Stale and partial projection states are observable.
- Staging seed tenant can demo every surface.

---

## 12. Testing architecture

### 12.1 Required test types

| Test type | File pattern | Required assertions |
|---|---|---|
| Registry contract | `test/contract/360/registry.contract.spec.ts` | Every surface/lens/file/slot/route exists and matches registry. |
| Surface contract | `test/contract/360/{surface}.contract.spec.ts` | DTO shape, slot keys, lens metadata, freshness, policy, source records, related links. |
| Resolver unit | `src/modules/{surface}/tests/{surface}.resolver.spec.ts` | Canonical source resolution, tenant isolation, missing/empty/zero semantics. |
| Projector unit | `src/modules/{surface}/tests/{surface}.projector.spec.ts` | Slot composition, deterministic ordering, degradation, related links. |
| Snapshot unit | `src/modules/{surface}/tests/{surface}.service.spec.ts` | Cache hit/miss/stale/force rebuild/source hash invalidation. |
| Lens unit | `src/modules/graph-lenses/{lens}/{lens}.spec.ts` | Lens input validation, output shape, confidence, policy, degradation. |
| UI slot | `test/components/360/{surface}/{surface}.render.spec.tsx` | Loading, empty, zero, redacted, stale, error, hydrated states. |
| E2E | `test/e2e/360/{surface}.e2e-spec.ts` | API + dashboard route render against seed tenant. |
| Performance | `test/performance/360/{surface}.perf-spec.ts` | Cached and uncached projection latency thresholds. |

### 12.2 Contract test template

```ts
describe('{surface}.contract', () => {
  it('matches registry slots and required lenses', async () => {
    const registry = getSurfaceDefinition('{surface}' as Surface360Key);
    const frame = await buildFixtureFrame('{surface}' as Surface360Key);

    expect(Object.keys(frame.slots).sort()).toEqual(registry.requiredSlots.sort());
    expect(frame.lenses.map(l => l.key).sort()).toEqual(registry.requiredLenses.sort());
    expect(frame.sourceRecords.length).toBeGreaterThan(0);
    expect(frame.freshness.generatedAt).toBeDefined();
    expect(frame.policy).toBeDefined();
  });

  it('does not collapse missing, empty, zero, redacted, and stale', async () => {
    const frame = await buildDegradedFixtureFrame('{surface}' as Surface360Key);
    expect(frame.degradation?.map(d => d.kind)).toEqual(
      expect.arrayContaining(['missing', 'empty', 'zero', 'redacted', 'stale'])
    );
  });
});
```

---

## 13. Seed tenant and fixtures

### 13.1 Required seed objects

A complete demo seed must include:

- 3 profiles.
- 1 organization/account.
- 2 agents.
- 3 executions.
- 2 episodes.
- 2 support cases.
- 2 conversations.
- 1 callback request.
- 1 community.
- 1 social network cluster.
- 2 topics/trends.
- 3 semantic nodes.
- 3 memory cards.
- 2 places.
- 2 products.
- 2 offers.
- 1 campaign.
- 5 journey/touchpoint/conversion events.
- 3 payments/value events.
- 1 workflow.
- 1 automation.
- 3 risk signals.
- 5 policy findings or policy decisions.
- Enough domain events to drive every event-signal lens.

### 13.2 Fixture rule

Every surface fixture must be able to produce:

1. Fully hydrated frame.
2. Empty-but-valid frame.
3. Missing-source frame.
4. Redacted frame.
5. Stale snapshot frame.
6. Partial lens failure frame.
7. Cross-tenant isolation denial.

---

## 14. Observability and telemetry

### 14.1 Metrics

Each surface must emit:

- `aether.360.frame.build.duration_ms`
- `aether.360.frame.snapshot.hit`
- `aether.360.frame.snapshot.miss`
- `aether.360.frame.stale`
- `aether.360.frame.redacted_fields.count`
- `aether.360.frame.degradation.count`
- `aether.360.lens.duration_ms`
- `aether.360.lens.failure`
- `aether.360.related_links.count`
- `aether.360.policy.blocked`

### 14.2 Logs

Projection logs must include:

- `traceId`
- `tenantId`
- `surface`
- `canonicalId`
- `frameVersion`
- `sourceRecordHash`
- `policyHash`
- `lensVersions`
- `snapshotState`
- `degradationKinds`
- `redactionReasonCodes`

### 14.3 Tracing

Trace span hierarchy:

```txt
experience360.getFrame
  -> registry.lookup
  -> snapshot.lookup
  -> surface.resolve
  -> lens.identity
  -> lens.policy
  -> lens.domainSpecific
  -> surface.project
  -> policy.finalize
  -> snapshot.write
```

---

## 15. Security, policy, privacy, and entitlement

### 15.1 Policy order

```txt
request authentication
  -> tenant resolution
  -> surface entitlement check
  -> canonical source access check
  -> lens-level policy
  -> frame-level policy
  -> slot-level redaction
  -> response
```

### 15.2 Required controls

- Surface access entitlement.
- Canonical record access entitlement.
- Lens drilldown entitlement.
- Debug/provenance entitlement.
- Rebuild entitlement.
- Cross-tenant denial.
- PII redaction.
- Consent-aware communications rendering.
- Payment/value field redaction.
- Policy decision reason codes.
- Audit trail for rebuilds and restricted access attempts.

### 15.3 Redaction contract

```ts
export interface RedactedValue {
  __redacted: true;
  reasonCode: string;
  replacementLabel: string;
}

export type Redactable<T> = T | RedactedValue;
```

---

## 16. Naming and product language rules

Use the normalized Aether language consistently:

| Legacy or weak term | Target term |
|---|---|
| Audience Intelligence | Signals |
| Audience Signals | Signals |
| Segments | Syndicates |
| Economic 360 | Value 360 |
| Business Value | Value |
| Observation | Signals or Events, depending on context |
| Graph Snapshot | Snapshot |
| Places | Place 360 or Location 360, depending on route context |
| Activity | Signals, Timeline, or Events depending on surface |

Rules:

1. `Campaign360` uses `Signals` and `Syndicates`; it does not expose legacy audience-centric labels.
2. `Value360` is the economic product surface.
3. Technical terms remain in internal contracts only when needed.
4. Frontend copy must describe decisions, context, status, and next actions rather than implementation mechanics.
5. Lenses remain technical subsystem names; dashboard slots should use product-facing labels.

---

## 17. Current-to-target gap closure matrix

| Area | Current disposition from blueprint inventory | Target state |
|---|---|---|
| Agent 360 | Blueprint-rich / scaffolded | Registry-backed production surface with canonical agent, executions, policy, knowledge, performance, and risk. |
| Execution 360 | Blueprint-rich but missing full runtime artifacts | Complete execution trace with plan, steps, tools, artifacts, confidence, value, risk, and related episodes/agents. |
| Episode 360 | Strong blueprint | Normalize into canonical episode frame and timeline projection. |
| Profile 360 | Some service/controller/frame already identified | Full lens-backed profile frame with identity, account, network, financial/value, offers, support, governance. |
| Support/Conversation/Callback 360 | Domain module strong but not consistently registered as 360 | Register and frame each as formal 360 surfaces. |
| Communications 360 | Implied by support/notifications | Build cross-channel communications parent surface. |
| Social/Community 360 | Conceptual/domain partial | Build social and community graph projections. |
| Trend/Topic 360 | Mostly missing | Build topic/trend canonical model, event-signal projection, and dashboard. |
| Semantic/Memory 360 | Partial memory/card concepts | Formalize semantic node and memory card 360s. |
| Location/Place 360 | Conceptual lens | Build geography/timezone/place projections. |
| Commerce/Offer/Product 360 | Partial offers/payments/entitlements | Build product/offer/commerce frames tied to entitlement and value. |
| Campaign 360 | Product-critical/in-flight | Build Signals-centered campaign surface. |
| Value 360 | Partial economic/payment concepts | Build economic truth projection and retire weak Business Value/Economic naming. |
| Workflow/Automation 360 | Partial orchestration/jobs ecosystem | Build formal workflow/automation frames. |
| Account 360 | Required by tenant/product runtime | Build account/organization entitlement/billing/support-health frame. |
| Identity 360 | Core lens concept | Build administrative identity resolution surface. |
| Risk 360 | Risk retained as concept | Build cross-surface risk and policy finding aggregator. |

---

## 18. Definition of done

A surface is production-complete only when all of the following are true:

1. Registry entry exists and readiness is accurate.
2. Backend module folder exists with controller, service, resolver, projector, snapshot repo, contract, DTO, fixture, policy, telemetry, and tests.
3. Frontend route exists with collection and detail pages.
4. Every frame slot has a component.
5. Every component handles loading, empty, zero, redacted, stale, error, and hydrated states.
6. Generic API dispatch works through `experience360`.
7. Surface-specific compatibility API either delegates to generic dispatch or is removed.
8. Projection snapshot works and invalidates on relevant events.
9. Lens results include source refs, confidence, freshness, policy, and degradation.
10. No direct canonical writes occur in the 360 module.
11. Policy and entitlement filters run before response.
12. Contract tests cover frame shape and slot parity.
13. UI tests cover slot states.
14. E2E tests run against seed tenant.
15. Docs exist under `docs/architecture/360/{surface}.md`.
16. Observability metrics exist.
17. Related360 links are generated and tested.
18. Staging can demo the surface with seeded data.

---

## 19. Implementation command plan for Codex/Claude branch

Use this as the branch implementation prompt.

```txt
Create a branch named feat/aether-360-complete-matrix.

Implement the Aether 360 matrix according to docs/architecture/360/aether-360-complete-architectural-buildout-blueprint.md.

Do not treat any 360 as a canonical source of truth. Build experience360 as the registry, API dispatch, snapshot, policy, freshness, and telemetry spine. Build graph-lenses as reusable resolvers/projectors with LensResult contracts. Normalize existing Agent360, Execution360, Episode360, and Profile360 into the shared resolver/projector/snapshot/frame pattern. Register Support360, Conversation360, Callback360, Communications360, Social360, Community360, Trend360, Semantic360, Memory360, Location360, Place360, Offer360, Commerce360, Product360, Campaign360, Value360, Workflow360, Automation360, Account360, Identity360, and Risk360.

For every surface:
- create/update src/modules/{surface}/ module files;
- create/update dto, contracts, resolvers, projectors, snapshots, policies, events, telemetry, fixtures, tests;
- create/update app/(dashboard)/{surface}/page.tsx and [id]/page.tsx;
- create/update components/360/{surface}/ slot components;
- add contract tests under test/contract/360;
- add fixtures under test/fixtures/360;
- add docs under docs/architecture/360.

Enforce slot parity between registry, DTO, backend frame, and frontend components. Preserve missing vs empty vs zero vs redacted vs stale. Add projection snapshot migrations and lens cache migrations. Add seed tenant data that can demo every 360. Update product language so Campaign360 uses Signals and Syndicates, and Value360 replaces Economic360/Business Value language.

Run typecheck, unit tests, contract tests, UI tests, and e2e tests. Produce a final implementation report listing files created/modified, surfaces completed, tests added, and any remaining blocked items.
```

---

## 20. Final build checklist

### Shared spine

- [ ] `experience360` module created.
- [ ] Registry implemented.
- [ ] Generic API implemented.
- [ ] Snapshot repository implemented.
- [ ] Freshness/source hash implemented.
- [ ] Policy/redaction finalizer implemented.
- [ ] Telemetry implemented.
- [ ] Registry contract tests implemented.

### Lenses

- [ ] Identity lens.
- [ ] Relationship/social lens.
- [ ] Semantic/memory lens.
- [ ] Economic lens.
- [ ] Value lens.
- [ ] Policy lens.
- [ ] Entitlement lens.
- [ ] Execution lens.
- [ ] Event-signal lens.
- [ ] Location/place lens.
- [ ] Product/offer lens.
- [ ] Communications lens.
- [ ] Campaign lens.
- [ ] Risk lens.
- [ ] Account lens.

### Surfaces

- [ ] `agent360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `execution360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `episode360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `profile360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `social360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `community360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `support360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `conversation360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `callback360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `communications360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `trend360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `semantic360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `memory360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `location360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `place360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `offer360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `commerce360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `product360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `campaign360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `value360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `workflow360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `automation360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `account360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `identity360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.
- [ ] `risk360` complete: registry + backend + frontend + fixture + tests + docs + telemetry.

### Release gates

- [ ] All `test/contract/360/*.spec.ts` pass.
- [ ] All graph lens tests pass.
- [ ] All surface resolver/projector/service tests pass.
- [ ] All UI slot tests pass.
- [ ] E2E seed tenant renders every 360.
- [ ] Snapshot invalidation verified.
- [ ] Redaction verified.
- [ ] Related360 navigation verified.
- [ ] Product language sweep complete.
- [ ] Staging demo script complete.
