// =============================================================================
// Aether SDK — Economic Observability (drop-in extension)
//
// Adds agentic transaction awareness on top of the existing graph contracts
// without introducing a new layer or breaking any current schema. All exports
// in this module are additive and optional. Existing data remains valid; no
// migration is required.
//
// What this module contributes:
//   • EconomicPayload      — embeddable economic block for any Action
//   • Handshake            — minimal node modelling x402-style payment
//                            request/resolve handshakes
//   • ResourceNode         — unified generic resource node (campaign,
//                            ad_account, bank_account, api, model)
//   • RelationshipExtensions — flow_ref, interaction_mode, outcome
//   • EconomicState        — derived economic aggregates over Actions
//   • Authorization        — embedded auth scope for actions / agents
//   • Validation guards + structured error types
//   • Aggregation utilities for derived state
//
// See docs/ECONOMIC-OBSERVABILITY.md for the full spec and examples.
// =============================================================================

// ---------------------------------------------------------------------------
// 1. Economic payload — embedded in an Action
// ---------------------------------------------------------------------------

/** Direction of value transfer relative to the actor performing the Action. */
export type EconomicDirection = 'pay' | 'receive';

/** Counterparty taxonomy at the agentic-commerce level. */
export type EconomicCounterpartyType = 'agent' | 'service' | 'platform';

/** Transport rail for the value transfer. */
export type EconomicRail = 'stripe' | 'bank' | 'crypto' | 'internal';

/**
 * Economic block embeddable on any canonical Action / event. Fully optional;
 * absence means the Action carries no monetary value.
 */
export interface EconomicPayload {
  amount: number;
  currency: string;
  direction: EconomicDirection;
  counterparty_type: EconomicCounterpartyType;
  counterparty_id: string;
  rail: EconomicRail;
}

const ECONOMIC_DIRECTIONS: ReadonlySet<EconomicDirection> = new Set(['pay', 'receive']);
const ECONOMIC_COUNTERPARTIES: ReadonlySet<EconomicCounterpartyType> = new Set([
  'agent',
  'service',
  'platform',
]);
const ECONOMIC_RAILS: ReadonlySet<EconomicRail> = new Set([
  'stripe',
  'bank',
  'crypto',
  'internal',
]);

// ---------------------------------------------------------------------------
// 2. Handshake — minimal node for x402-style payment handshakes
// ---------------------------------------------------------------------------

export type HandshakeStatus = 'pending' | 'paid' | 'failed';

/**
 * A Handshake captures a payment request made by a service and its eventual
 * resolution. Edges:
 *   Action     → initiates    → Handshake
 *   Handshake  → resolves_to  → Action
 */
export interface Handshake {
  id: string;
  request_id: string;
  required_amount: number;
  status: HandshakeStatus;
  timestamp: number;
}

/** Allowed status transitions for a Handshake. */
const HANDSHAKE_TRANSITIONS: Record<HandshakeStatus, ReadonlySet<HandshakeStatus>> = {
  pending: new Set<HandshakeStatus>(['paid', 'failed']),
  paid: new Set<HandshakeStatus>(),
  failed: new Set<HandshakeStatus>(),
};

// ---------------------------------------------------------------------------
// 3. Unified Resource node — replaces ad-hoc specialised nodes
// ---------------------------------------------------------------------------

export type ResourceNodeType =
  | 'campaign'
  | 'ad_account'
  | 'bank_account'
  | 'api'
  | 'model';

const RESOURCE_NODE_TYPES: ReadonlySet<ResourceNodeType> = new Set([
  'campaign',
  'ad_account',
  'bank_account',
  'api',
  'model',
]);

/**
 * Generic resource node. Use `metadata` for type-specific attributes so the
 * schema can grow without breaking changes.
 */
export interface ResourceNode {
  id: string;
  type: ResourceNodeType;
  platform?: string;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// 4. Relationship extensions
// ---------------------------------------------------------------------------

/** Sequencing reference for grouping a chain of related Actions/edges. */
export interface FlowRef {
  flow_id: string;
  sequence: number;
}

/** Who participated in the interaction. */
export type InteractionMode = 'H2H' | 'H2A' | 'A2A' | 'A2H';

const INTERACTION_MODES: ReadonlySet<InteractionMode> = new Set([
  'H2H',
  'H2A',
  'A2A',
  'A2H',
]);

/** Causal outcome attached to a relationship/edge. */
export type OutcomeMetric = 'revenue' | 'conversion' | 'latency';

const OUTCOME_METRICS: ReadonlySet<OutcomeMetric> = new Set([
  'revenue',
  'conversion',
  'latency',
]);

export interface RelationshipOutcome {
  metric: OutcomeMetric;
  value: number;
}

/**
 * Optional fields layered on top of the existing Relationship/edge model.
 * All fields are optional and backward compatible.
 */
export interface RelationshipExtensions {
  flow_ref?: FlowRef;
  interaction_mode?: InteractionMode;
  economic_involved?: boolean;
  outcome?: RelationshipOutcome;
}

// ---------------------------------------------------------------------------
// 5. Authorization — embedded reference (no separate permission graph)
// ---------------------------------------------------------------------------

export type AuthorizationSource = 'human' | 'org' | 'policy';

const AUTH_SOURCES: ReadonlySet<AuthorizationSource> = new Set([
  'human',
  'org',
  'policy',
]);

export interface Authorization {
  source: AuthorizationSource;
  scope: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// 6. Action shape (extension-only) and State (derived only)
// ---------------------------------------------------------------------------

/**
 * Subset of Action fields this module reasons about. The actual canonical
 * Action type lives in the host system (event envelopes, backend graph,
 * etc.); this interface exists so aggregation utilities can be statically
 * typed without re-defining the full Action.
 */
export interface EconomicActionLike {
  /** Stable id of the action, when available. */
  id?: string;
  /** Optional embedded economic block. */
  economic?: EconomicPayload;
  /** Optional embedded authorization scope. */
  authorization?: Authorization;
}

/**
 * Derived economic aggregate. NEVER persisted directly — always computed
 * from the underlying Actions via `aggregateEconomicState`.
 */
export interface EconomicState {
  spend_rate?: number;
  total_spend?: number;
  total_revenue?: number;
  unit_cost?: number;
}

// ---------------------------------------------------------------------------
// 7. Error types
// ---------------------------------------------------------------------------

class AetherEconomicError extends Error {
  /** Stable, machine-readable code. */
  readonly code: string;
  /** Optional structured detail bag for log enrichment. */
  readonly details?: Record<string, unknown>;

  constructor(name: string, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = name;
    this.code = code;
    if (details !== undefined) this.details = details;
  }
}

export class EconomicValidationError extends AetherEconomicError {
  constructor(message: string, details?: Record<string, unknown>) {
    super('EconomicValidationError', 'ECONOMIC_VALIDATION', message, details);
  }
}

export class HandshakeStateError extends AetherEconomicError {
  constructor(message: string, details?: Record<string, unknown>) {
    super('HandshakeStateError', 'HANDSHAKE_STATE', message, details);
  }
}

export class RelationshipIntegrityError extends AetherEconomicError {
  constructor(message: string, details?: Record<string, unknown>) {
    super('RelationshipIntegrityError', 'RELATIONSHIP_INTEGRITY', message, details);
  }
}

// ---------------------------------------------------------------------------
// 8. Validation guards
// ---------------------------------------------------------------------------

const isFiniteNumber = (n: unknown): n is number =>
  typeof n === 'number' && Number.isFinite(n);

const isNonEmptyString = (s: unknown): s is string =>
  typeof s === 'string' && s.length > 0;

/**
 * Validate an economic payload. Throws EconomicValidationError on failure.
 * Returns the payload unchanged on success so callers can chain.
 */
export function validateEconomicPayload(value: unknown): EconomicPayload {
  if (value === null || typeof value !== 'object') {
    throw new EconomicValidationError('economic payload must be an object', { value });
  }
  const v = value as Record<string, unknown>;

  if (!isFiniteNumber(v.amount) || v.amount < 0) {
    throw new EconomicValidationError('amount must be a finite number >= 0', { amount: v.amount });
  }
  if (!isNonEmptyString(v.currency)) {
    throw new EconomicValidationError('currency must be a non-empty string', { currency: v.currency });
  }
  if (typeof v.direction !== 'string' || !ECONOMIC_DIRECTIONS.has(v.direction as EconomicDirection)) {
    throw new EconomicValidationError('direction must be "pay" | "receive"', { direction: v.direction });
  }
  if (
    typeof v.counterparty_type !== 'string' ||
    !ECONOMIC_COUNTERPARTIES.has(v.counterparty_type as EconomicCounterpartyType)
  ) {
    throw new EconomicValidationError(
      'counterparty_type must be "agent" | "service" | "platform"',
      { counterparty_type: v.counterparty_type },
    );
  }
  if (!isNonEmptyString(v.counterparty_id)) {
    throw new EconomicValidationError('counterparty_id must be a non-empty string', {
      counterparty_id: v.counterparty_id,
    });
  }
  if (typeof v.rail !== 'string' || !ECONOMIC_RAILS.has(v.rail as EconomicRail)) {
    throw new EconomicValidationError('rail must be "stripe" | "bank" | "crypto" | "internal"', {
      rail: v.rail,
    });
  }

  return {
    amount: v.amount,
    currency: v.currency,
    direction: v.direction as EconomicDirection,
    counterparty_type: v.counterparty_type as EconomicCounterpartyType,
    counterparty_id: v.counterparty_id,
    rail: v.rail as EconomicRail,
  };
}

export function isEconomicPayload(value: unknown): value is EconomicPayload {
  try {
    validateEconomicPayload(value);
    return true;
  } catch {
    return false;
  }
}

export function validateHandshake(value: unknown): Handshake {
  if (value === null || typeof value !== 'object') {
    throw new EconomicValidationError('handshake must be an object', { value });
  }
  const v = value as Record<string, unknown>;
  if (!isNonEmptyString(v.id)) {
    throw new EconomicValidationError('handshake.id must be a non-empty string', { id: v.id });
  }
  if (!isNonEmptyString(v.request_id)) {
    throw new EconomicValidationError('handshake.request_id must be a non-empty string', {
      request_id: v.request_id,
    });
  }
  if (!isFiniteNumber(v.required_amount) || v.required_amount < 0) {
    throw new EconomicValidationError('handshake.required_amount must be a finite number >= 0', {
      required_amount: v.required_amount,
    });
  }
  if (
    typeof v.status !== 'string' ||
    !(v.status === 'pending' || v.status === 'paid' || v.status === 'failed')
  ) {
    throw new EconomicValidationError('handshake.status must be pending|paid|failed', {
      status: v.status,
    });
  }
  if (!isFiniteNumber(v.timestamp)) {
    throw new EconomicValidationError('handshake.timestamp must be a finite number', {
      timestamp: v.timestamp,
    });
  }
  return {
    id: v.id,
    request_id: v.request_id,
    required_amount: v.required_amount,
    status: v.status as HandshakeStatus,
    timestamp: v.timestamp,
  };
}

/**
 * Enforce handshake status transitions. Throws HandshakeStateError on an
 * illegal move. `pending -> paid|failed` are the only allowed transitions;
 * `paid` and `failed` are terminal.
 */
export function assertHandshakeTransition(from: HandshakeStatus, to: HandshakeStatus): void {
  if (from === to) {
    throw new HandshakeStateError(`handshake already in status "${from}"`, { from, to });
  }
  const allowed = HANDSHAKE_TRANSITIONS[from];
  if (!allowed.has(to)) {
    throw new HandshakeStateError(`illegal handshake transition ${from} -> ${to}`, { from, to });
  }
}

/** Returns the next handshake state if the transition is legal; throws otherwise. */
export function transitionHandshake(handshake: Handshake, to: HandshakeStatus): Handshake {
  assertHandshakeTransition(handshake.status, to);
  return { ...handshake, status: to };
}

export function validateResourceNode(value: unknown): ResourceNode {
  if (value === null || typeof value !== 'object') {
    throw new EconomicValidationError('resource must be an object', { value });
  }
  const v = value as Record<string, unknown>;
  if (!isNonEmptyString(v.id)) {
    throw new EconomicValidationError('resource.id must be a non-empty string', { id: v.id });
  }
  if (typeof v.type !== 'string' || !RESOURCE_NODE_TYPES.has(v.type as ResourceNodeType)) {
    throw new EconomicValidationError(
      'resource.type must be one of campaign|ad_account|bank_account|api|model',
      { type: v.type },
    );
  }
  if (v.platform !== undefined && !isNonEmptyString(v.platform)) {
    throw new EconomicValidationError('resource.platform, if present, must be a non-empty string', {
      platform: v.platform,
    });
  }
  if (v.metadata !== undefined && (v.metadata === null || typeof v.metadata !== 'object')) {
    throw new EconomicValidationError('resource.metadata, if present, must be an object', {
      metadata: v.metadata,
    });
  }
  const out: ResourceNode = { id: v.id, type: v.type as ResourceNodeType };
  if (v.platform !== undefined) out.platform = v.platform;
  if (v.metadata !== undefined) out.metadata = v.metadata as Record<string, unknown>;
  return out;
}

export function validateRelationshipExtensions(value: unknown): RelationshipExtensions {
  if (value === null || typeof value !== 'object') {
    throw new EconomicValidationError('relationship extensions must be an object', { value });
  }
  const v = value as Record<string, unknown>;
  const out: RelationshipExtensions = {};

  if (v.flow_ref !== undefined) {
    if (v.flow_ref === null || typeof v.flow_ref !== 'object') {
      throw new EconomicValidationError('flow_ref must be an object', { flow_ref: v.flow_ref });
    }
    const fr = v.flow_ref as Record<string, unknown>;
    if (!isNonEmptyString(fr.flow_id)) {
      throw new EconomicValidationError('flow_ref.flow_id must be a non-empty string', {
        flow_id: fr.flow_id,
      });
    }
    if (!isFiniteNumber(fr.sequence) || !Number.isInteger(fr.sequence) || fr.sequence < 0) {
      throw new EconomicValidationError('flow_ref.sequence must be an integer >= 0', {
        sequence: fr.sequence,
      });
    }
    out.flow_ref = { flow_id: fr.flow_id, sequence: fr.sequence };
  }

  if (v.interaction_mode !== undefined) {
    if (
      typeof v.interaction_mode !== 'string' ||
      !INTERACTION_MODES.has(v.interaction_mode as InteractionMode)
    ) {
      throw new EconomicValidationError('interaction_mode must be H2H|H2A|A2A|A2H', {
        interaction_mode: v.interaction_mode,
      });
    }
    out.interaction_mode = v.interaction_mode as InteractionMode;
  }

  if (v.economic_involved !== undefined) {
    if (typeof v.economic_involved !== 'boolean') {
      throw new EconomicValidationError('economic_involved must be a boolean', {
        economic_involved: v.economic_involved,
      });
    }
    out.economic_involved = v.economic_involved;
  }

  if (v.outcome !== undefined) {
    if (v.outcome === null || typeof v.outcome !== 'object') {
      throw new EconomicValidationError('outcome must be an object', { outcome: v.outcome });
    }
    const o = v.outcome as Record<string, unknown>;
    if (typeof o.metric !== 'string' || !OUTCOME_METRICS.has(o.metric as OutcomeMetric)) {
      throw new EconomicValidationError('outcome.metric must be revenue|conversion|latency', {
        metric: o.metric,
      });
    }
    if (!isFiniteNumber(o.value)) {
      throw new EconomicValidationError('outcome.value must be a finite number', {
        value: o.value,
      });
    }
    out.outcome = { metric: o.metric as OutcomeMetric, value: o.value };
  }

  return out;
}

export function validateAuthorization(value: unknown): Authorization {
  if (value === null || typeof value !== 'object') {
    throw new EconomicValidationError('authorization must be an object', { value });
  }
  const v = value as Record<string, unknown>;
  if (typeof v.source !== 'string' || !AUTH_SOURCES.has(v.source as AuthorizationSource)) {
    throw new EconomicValidationError('authorization.source must be human|org|policy', {
      source: v.source,
    });
  }
  if (!isNonEmptyString(v.scope)) {
    throw new EconomicValidationError('authorization.scope must be a non-empty string', {
      scope: v.scope,
    });
  }
  if (v.limit !== undefined) {
    if (!isFiniteNumber(v.limit) || v.limit < 0) {
      throw new EconomicValidationError('authorization.limit must be a finite number >= 0', {
        limit: v.limit,
      });
    }
  }
  const out: Authorization = { source: v.source as AuthorizationSource, scope: v.scope };
  if (v.limit !== undefined) out.limit = v.limit as number;
  return out;
}

// ---------------------------------------------------------------------------
// 9. Referential integrity helpers
// ---------------------------------------------------------------------------

/**
 * Check that an Action → Handshake `initiates` edge points at a known
 * handshake. Throws RelationshipIntegrityError on a dangling reference.
 */
export function assertHandshakeReference(
  handshakeId: string,
  knownHandshakes: ReadonlyMap<string, Handshake> | ReadonlyArray<Handshake>,
): void {
  const exists = Array.isArray(knownHandshakes)
    ? knownHandshakes.some((h) => h.id === handshakeId)
    : (knownHandshakes as ReadonlyMap<string, Handshake>).has(handshakeId);
  if (!exists) {
    throw new RelationshipIntegrityError(`unknown handshake reference: ${handshakeId}`, {
      handshakeId,
    });
  }
}

/**
 * Check that a `resolves_to` edge from a Handshake points at a known Action.
 * Pure structural check — does not enforce semantic correctness.
 */
export function assertActionReference(
  actionId: string,
  knownActions: ReadonlyMap<string, EconomicActionLike> | ReadonlyArray<EconomicActionLike>,
): void {
  const exists = Array.isArray(knownActions)
    ? knownActions.some((a) => a.id === actionId)
    : (knownActions as ReadonlyMap<string, EconomicActionLike>).has(actionId);
  if (!exists) {
    throw new RelationshipIntegrityError(`unknown action reference: ${actionId}`, { actionId });
  }
}

// ---------------------------------------------------------------------------
// 10. Aggregation — derived EconomicState
// ---------------------------------------------------------------------------

export interface AggregateOptions {
  /**
   * Time window in milliseconds used to compute spend_rate. If omitted or
   * non-positive, spend_rate is left undefined.
   */
  windowMs?: number;
  /**
   * Number of units delivered for unit_cost calculation. If omitted or 0,
   * unit_cost is left undefined.
   */
  units?: number;
}

/**
 * Aggregate a list of Actions into a derived EconomicState.
 *
 * Complexity: O(n) over the input — no joins, no graph traversal.
 *
 * Rules:
 *  - Actions without an `economic` block are ignored.
 *  - direction === 'pay'     contributes to total_spend
 *  - direction === 'receive' contributes to total_revenue
 *  - spend_rate  = total_spend / (windowMs / 1000) when windowMs > 0
 *  - unit_cost   = total_spend / units            when units > 0
 */
export function aggregateEconomicState(
  actions: ReadonlyArray<EconomicActionLike>,
  options: AggregateOptions = {},
): EconomicState {
  let totalSpend = 0;
  let totalRevenue = 0;
  let sawAny = false;

  for (const action of actions) {
    const econ = action.economic;
    if (!econ) continue;
    sawAny = true;
    if (econ.direction === 'pay') totalSpend += econ.amount;
    else totalRevenue += econ.amount;
  }

  if (!sawAny) return {};

  const state: EconomicState = {
    total_spend: totalSpend,
    total_revenue: totalRevenue,
  };

  if (options.windowMs !== undefined && options.windowMs > 0) {
    state.spend_rate = totalSpend / (options.windowMs / 1000);
  }
  if (options.units !== undefined && options.units > 0) {
    state.unit_cost = totalSpend / options.units;
  }

  return state;
}

// ---------------------------------------------------------------------------
// 11. Convenience constructors
// ---------------------------------------------------------------------------

export function createHandshake(
  input: Omit<Handshake, 'status'> & { status?: HandshakeStatus },
): Handshake {
  return validateHandshake({
    id: input.id,
    request_id: input.request_id,
    required_amount: input.required_amount,
    status: input.status ?? 'pending',
    timestamp: input.timestamp,
  });
}

export function createResourceNode(input: ResourceNode): ResourceNode {
  return validateResourceNode(input);
}
