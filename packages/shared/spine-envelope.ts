// =============================================================================
// Aether SDK — Common Spine Envelope (ADR-011 D3)
// HAND-MAINTAINED contract — NOT generated (do not run generate_platform_contracts.py
// against this file). Python twin:
//   Backend Architecture/aether-backend/shared/spine/spine_envelope.py
// Parity is enforced by tests/unit/test_spine_envelope_parity.py.
//
// ADR-011 D3: "The common spine envelope composes the canonical primitives —
// EntityRef, EvidenceRef, PageRequest, the temporal envelope fields,
// ContextCapsule, provenance — and adds the envelope fields the architecture
// calls for (tenant_id, request_id, scope_ref, subject_refs, as_of, valid_time,
// identity_watermark, data_watermark, policy_ref, consent_decision_ref,
// rights_decision_ref, evidence_refs, quality, contract_versions, model_refs,
// lineage_refs). Fields with no producer yet (identity_watermark,
// rights_decision_ref) are declared present-but-unpopulated (@unpopulated); no
// producer is claimed until one ships. Nothing is re-defined."
//
// Composition rule honored here: the fields below REUSE the canonical
// primitives where the ADR field maps onto one (EntityRef → subject_refs,
// EvidenceRef → evidence_refs, TemporalRange → valid_time, the as_of /
// graph-watermark string-position idiom → as_of / data_watermark). Fields with
// no canonical field type in packages/shared are typed narrowly and the ADR is
// cited in JSDoc. No primitive is redefined and no envelope field beyond the
// ADR-011 D3 list is invented.
// =============================================================================

import type { EntityRef } from './entities';
import type { EvidenceRef } from './operational-intelligence';
import type { TemporalRange } from './temporal';

/**
 * Narrow quality/availability statement carried on every SpineEnvelope.
 *
 * No canonical quality primitive exists in packages/shared today, so this is a
 * narrow, envelope-local shape that follows the founding architecture example
 * (SPINE_P0_ARCHITECTURE.md §6): `{ "state": "available", "limitations": [] }`.
 * The `state` values are the publish states the architecture names — a
 * not-yet-complete spine publishes `degraded`, `unavailable`, `unknown`, or
 * `not_applicable` through the same envelope instead of inventing behavior.
 * ADR-011 D3, D5.
 */
export interface SpineEnvelopeQuality {
  /**
   * Availability of this envelope's contents.
   * `available` — contents reflect governed truth; `degraded` — partial;
   * `unavailable` — the interaction could not be completed; `unknown` — state
   * not yet known; `not_applicable` — the field/step does not apply here.
   */
  state: 'available' | 'degraded' | 'unavailable' | 'unknown' | 'not_applicable';
  /** Human-readable limitations behind a non-`available` state. Empty when available. */
  limitations: string[];
}

/**
 * The common spine envelope (ADR-011 D3).
 *
 * One governed envelope every cross-spine interaction resolves to. Every field
 * below is declared present (no `?`); values without a producer yet are
 * present-but-`null` and carry an `@unpopulated` tag. Reuses canonical
 * primitives — nothing here is redefined.
 */
export interface SpineEnvelope {
  /** Tenant that owns this cross-spine interaction. Plain canonical id string. */
  tenant_id: string;
  /** Opaque id correlating this envelope to the originating request/trace (cf. `ApiErrorBody.error.requestId`, `EventPipelineEnvelope.correlationId`). */
  request_id: string;
  /**
   * Opaque id of the governing scope record this interaction resolves against
   * (tenant/surface/deployment scope). Narrow string ref — no canonical
   * `ScopeRef` type exists in packages/shared; scope identity today is carried
   * as `ExplorationContextV1.scope { tenant_id, surface }` and by surface
   * capability ids. ADR-011 D3.
   */
  scope_ref: string;
  /** Canonical subjects this interaction is about. Reuses `EntityRef` (entities.ts). */
  subject_refs: EntityRef[];
  /**
   * Canonical UTC instant the envelope reads the world at — point-in-time /
   * replay semantics. Same string type as `UniversalGraphQueryRequest.as_of`
   * and `GraphResultMeta.as_of` in graph-contract.ts (~lines 525, 544).
   */
  as_of: string;
  /** Valid-time context of the envelope's facts. Reuses the canonical temporal range primitive (temporal.ts). */
  valid_time: TemporalRange | null;
  /**
   * @unpopulated
   * Present-but-unpopulated. No producer until the Identity Resolution spine
   * ships a watermark / freshness position — the identity-resolution authority
   * exists and produces an `EntityRef` (or an explicitly unresolved state), but
   * nothing emits an identity-resolution watermark yet, and no producer is
   * claimed until that ships. Honest resting state: `null`. ADR-011 D3;
   * SPINE_P0_ARCHITECTURE.md §§3, 6 ("identity watermark behind").
   */
  identity_watermark: string | null;
  /**
   * Opaque position of the data/graph watermark this envelope read against —
   * the same string-position idiom the graph/temporal kernel already stamps as
   * `GraphDecisionRecord.graph_watermark` / `TraversalSnapshot.graph_watermark`
   * (graph-mutation.ts, operational-intelligence.ts). Producer exists (scattered
   * today); the unified envelope names it `data_watermark`. ADR-011 D3.
   */
  data_watermark: string | null;
  /**
   * Opaque id of the governing policy. Narrow string ref — policy ids already
   * appear canonically as `GovernanceDecision.policies`,
   * `ExplainabilityMetadata.policyIds`, `MutationRecord.policy_refs`. ADR-011 D3.
   */
  policy_ref: string | null;
  /**
   * Opaque id of the `ConsentPolicyDecision` (services/policy) that authorized
   * this interaction. The producer exists (ADR-011 D4 names it as existing
   * machinery); no canonical decision-ref type exists in packages/shared, so
   * typed narrowly as a string id. ADR-011 D3.
   */
  consent_decision_ref: string | null;
  /**
   * @unpopulated
   * Present-but-unpopulated. No producer until the IRRL naming overlay ships
   * (SPINE_P0_PHASES phase 5; ADR-011 D4) — `RightsDecision` exists today only
   * as declared IRRL vocabulary over existing machinery (`DataRightsGrant`,
   * `ConsentPolicyDecision`); no IRRL rights-decision id is produced until that
   * overlay is enforced. Honest resting state: `null`. ADR-011 D3;
   * SPINE_P0_ARCHITECTURE.md §6.
   */
  rights_decision_ref: string | null;
  /** Supporting evidence for the envelope's claims. Reuses `EvidenceRef` (operational-intelligence.ts). */
  evidence_refs: EvidenceRef[];
  /** Quality/availability statement for this envelope's contents. See `SpineEnvelopeQuality`. */
  quality: SpineEnvelopeQuality;
  /**
   * Resolved versions of the canonical contracts this envelope conforms to —
   * maps contract name → version string. Same `Record<string, string>`
   * "versions map" idiom as `GraphDecisionRecord.model_versions` /
   * `policy_versions` (graph-mutation.ts); each versioned canonical contract
   * already exposes its own version const (e.g. `contextCapsuleContractVersion`).
   */
  contract_versions: Record<string, string>;
  /** Canonical modelIds whose outputs/decisions this envelope consumed or depends on (model-registry.ts `modelId`). Same string-id idiom as `MutationRecord.model_refs`. */
  model_refs: string[];
  /** Opaque ids of the lineage/restatement records this envelope's facts trace to (evidence lineage; cf. `ExplainabilityMetadata.lineageEventIds`). */
  lineage_refs: string[];
}

/**
 * Envelope fields with no producer yet (ADR-011 D3). Declared present-but-
 * unpopulated (`@unpopulated`) on the interface; the parity test asserts this
 * set matches the Python twin (`shared/spine/spine_envelope.py`) exactly.
 */
export const spineEnvelopeUnpopulatedFields = ['identity_watermark', 'rights_decision_ref'] as const;
