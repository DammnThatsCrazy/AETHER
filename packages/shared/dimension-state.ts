/**
 * Canonical dimension-state contract.
 *
 * A "dimension" is one slice of a profile / analytics surface (events, wallets,
 * consent, campaigns, …). Every dimension read reports one canonical
 * DimensionState so a surface can honestly say WHY a slice is empty or degraded
 * instead of rendering a blank that looks like "no activity". The Python mirror
 * lives at `shared/dimension_state.py`; the two are parity-tested.
 */

/** Canonical per-dimension data-availability states. */
export const dimensionStates = [
  'ready',              // data present and within its freshness SLA
  'empty',              // no data exists yet (legitimately — e.g. a new entity)
  'partial',            // some expected inputs present, not all
  'stale',              // data present but older than the freshness SLA
  'insufficient_data',  // below the minimum volume required to report
  'degraded',           // a dependency failed; showing reduced / last-known data
  'suppressed',         // data exists but withheld by consent / policy
  'not_applicable',     // the dimension does not apply to this entity type
  'pending',            // computation in progress / awaiting reconciliation
  'error',              // the dimension failed to compute
] as const;

export type DimensionState = typeof dimensionStates[number];

/**
 * Precedence for rolling many dimension states into one, ORDERED BEST → WORST.
 * The worst (highest-index) state wins, so a surface's overall readiness never
 * looks better than its weakest dimension.
 */
export const dimensionStatePrecedence: readonly DimensionState[] = [
  'ready',
  'not_applicable',
  'empty',
  'pending',
  'partial',
  'insufficient_data',
  'stale',
  'suppressed',
  'degraded',
  'error',
] as const;

/** Machine-readable reason a dimension is in its state. */
export const dimensionReasonCodes = [
  'ok',
  'no_data',
  'below_min_events',
  'past_freshness_sla',
  'partial_inputs',
  'dependency_failed',
  'consent_withheld',
  'entity_type_mismatch',
  'awaiting_reconciliation',
  'computation_error',
] as const;

export type DimensionReasonCode = typeof dimensionReasonCodes[number];

/** Freshness facts for a dimension (all optional — freshness may be unknown). */
export interface DimensionFreshness {
  /** ISO-8601 timestamp of the newest record contributing to this dimension. */
  watermark?: string | null;
  age_seconds?: number | null;
  sla_seconds?: number | null;
  is_stale?: boolean;
}

/** The canonical envelope every dimension read returns. */
export interface DimensionEnvelope {
  dimension: string;
  state: DimensionState;
  reason_code: DimensionReasonCode;
  freshness?: DimensionFreshness | null;
  /** Records contributing to the dimension, when countable. */
  count?: number | null;
  /** Human-readable, non-secret explanation. */
  message?: string | null;
}

/** Roll many states into the single worst one (empty → 'ready'). */
export function worstDimensionState(states: readonly DimensionState[]): DimensionState {
  let worst: DimensionState = 'ready';
  let worstRank = 0;
  for (const s of states) {
    const rank = dimensionStatePrecedence.indexOf(s);
    if (rank > worstRank) {
      worstRank = rank;
      worst = s;
    }
  }
  return worst;
}
