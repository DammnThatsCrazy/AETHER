/**
 * Canonical epistemic-status vocabulary — TypeScript mirror.
 *
 * Mirrors `Backend Architecture/aether-backend/shared/contracts_models/epistemic.py`.
 * Kept in lockstep by `tests/contracts/test_epistemic_status_parity.py`
 * (const-array set + order equality).
 *
 * A single, consolidated status vocabulary for how *trustworthy* a claim,
 * finding, or state is — whether it is a direct observation, an
 * evidence-grounded fact, or only a derived / inferred / correlated /
 * predicted suspicion.
 *
 * No-silent-escalation invariant:
 * a `derived` / `inferred` / `correlated` / `predicted` suspicion must NEVER
 * render as a factual declaration (`verified` / `causally_supported` /
 * `confirmed`) without an evidence-grounded upgrade. This vocabulary is the
 * single authority a ClaimEnvelope / FraudHypothesis state and any UI render
 * against; a UI may only display a more-confident status when the underlying
 * record transitioned with evidence, never by styling or copy preference.
 *
 * Banding (used by UI render rules):
 *  - Direct / factual: observed, verified, resolved, causally_supported.
 *  - Suspicion / derivative (must NOT self-escalate): derived, inferred,
 *    predicted, correlated, attributed.
 *  - Contested / withdrawn: disputed, superseded, stale.
 *  - Honest absence: unknown, unavailable, not_applicable.
 */

/** The canonical epistemic statuses, ordered like the Python enum members. */
export const EPISTEMIC_STATUSES = [
  'observed',            // raw observation / direct capture
  'verified',            // evidence-grounded factual declaration
  'resolved',            // an earlier dispute / conflict was resolved
  'derived',             // derivative value — NOT a factual declaration
  'inferred',            // inference — NOT a factual declaration
  'predicted',           // forward-looking estimate — NOT a factual declaration
  'correlated',          // statistical co-occurrence — NOT a factual declaration
  'attributed',          // attribution-model output
  'causally_supported',  // causal claim backed by experiment / established mechanism
  'disputed',            // contested
  'superseded',          // replaced by a later record
  'stale',               // present but older than its freshness bound
  'unknown',             // genuinely not known
  'unavailable',         // exists but withheld / not accessible
  'not_applicable',      // the question does not apply
] as const;

export type EpistemicStatus = typeof EPISTEMIC_STATUSES[number];
