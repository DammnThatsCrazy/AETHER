// =============================================================================
// Aether SDK — Shared Entity Model
// Canonical entities the SDK may reference. Mirrors backend VertexType enum
// in Backend Architecture/aether-backend/shared/graph/graph.py.
// See docs/source-of-truth/ENTITY_MODEL.md.
// =============================================================================

/** Every canonical entity ref is { kind, id } — SDKs never construct full nodes. */
export type EntityKind =
  // Core (always present)
  | 'tenant'
  | 'org'
  | 'user'
  | 'session'
  | 'device'
  | 'application'
  // Access plane
  | 'resource'
  | 'approval'
  | 'entitlement'
  // Commerce plane
  | 'payment'
  | 'invoice'
  | 'subscription'
  | 'plan'
  // Web3 plane (optional)
  | 'wallet'
  | 'contract'
  | 'chain'
  | 'token'
  | 'protocol'
  // Agent plane (optional)
  | 'agent'
  | 'service'
  // Economic graph layer (optional/additive)
  | 'payment_intent'
  | 'settlement_event'
  | 'economic_resource'
  | 'facilitator'
  | 'agent_economic_identity'
  | 'agent_profile360';

/** Lightweight reference emitted in event properties. */
export interface EntityRef {
  kind: EntityKind;
  id: string;
  /** Optional human label (SDK may leave blank; backend enriches). */
  label?: string;
}
