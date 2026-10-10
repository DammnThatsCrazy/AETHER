/**
 * Canonical capability credential-lifecycle state matrix.
 *
 * A "capability surface" (payment rails, card-linked, stablecoin, derivatives,
 * interop, rewards, agent command-center) can be in exactly one of these states
 * at read time. The point of a single shared vocabulary is honesty: a surface
 * must never let a not-yet-credentialed, sandbox-only, degraded, or mock-served
 * capability read as "live". Every state below is visually DISTINCT.
 *
 * These tokens are a superset that unifies two backend contracts already used
 * across the platform:
 *   - `ImplementationStatus` (packages/shared/connector-taxonomy.ts) — how far a
 *     capability's implementation has progressed (mocked → credential-gated →
 *     provider-live …).
 *   - `DimensionState` (packages/shared/dimension-state.ts) — the data-availability
 *     state of a live read (ready / partial / stale / degraded / error …).
 *
 * `fromImplementationStatus` / `fromDimensionState` / `resolveCapabilityState`
 * map those server-reported values onto this presentation vocabulary so both
 * apps render capability status consistently and never invent a "live" badge.
 */

import type { ImplementationStatus } from '@aether/shared/connector-taxonomy';
import type { DimensionState } from '@aether/shared/dimension-state';

/** The full credential-waiting / capability state matrix, ordered by lifecycle. */
export const capabilityStates = [
  // ── Availability gates (capability is off / withheld) ─────────────────────
  'disabled', // turned off by operator or compliance hold
  'disabled_intentionally', // deliberately omitted by product / release policy
  'not_in_release', // not shipped in the active release class
  'not_entitled', // tenant plan / entitlement does not include this capability
  'unavailable', // runtime capability truth could not be established
  'externally_blocked', // an external provider / approval is blocking progress
  // ── Configuration + credential lifecycle ──────────────────────────────────
  'not_configured', // no credentials or config supplied yet
  'credential_required', // config present but credentials still needed
  'credential_invalid', // supplied credentials were rejected by the provider
  'connection_testing', // actively probing the provider connection
  'credential_waiting', // credentials accepted; awaiting async activation/propagation
  'credential_supplied', // an active credential version exists; connection test pending
  'provisioning', // provider resources are actively being created
  // ── Validation ladder (working, but not partner-live) ─────────────────────
  'replay_validated', // verified against replayed/recorded provider traffic
  'connection_validated', // supplied credential passed a real connection/identity test
  'sandbox_validated', // verified end-to-end in the provider sandbox
  'partner_live', // fully live against the production provider
  'live', // canonical live spelling; partner_live remains for compatibility
  // ── Live-but-imperfect data states ────────────────────────────────────────
  'degraded', // a dependency failed; showing reduced / last-known data
  'stale', // data present but older than its freshness SLA
  'partial', // some expected inputs present, not all
  'error', // the capability read failed
  // ── Emergency / off-ramps ─────────────────────────────────────────────────
  'suspended', // reversible operator / kill-switch stop of the capability
  'revoked', // credentials revoked; requires resubmission
  'kill_switch_active', // capability halted by an active kill switch
] as const;

export type CapabilityState = (typeof capabilityStates)[number];

/**
 * Semantic tone groups. Tone is a coarser axis than the badge palette (6 colors
 * for 15 states); it drives the color family while the per-state label + glyph +
 * `data-capability-state` marker guarantee each state is individually distinct.
 */
export type CapabilityTone =
  | 'neutral' // off / not-yet-started, no action implied by color
  | 'action' // user action needed to progress
  | 'progress' // work in flight, transient
  | 'validating' // working but explicitly NOT production-live
  | 'live' // fully live
  | 'caution' // live data with a quality caveat
  | 'critical'; // broken / halted / rejected

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const TONE_VARIANT: Record<CapabilityTone, BadgeVariant> = {
  neutral: 'default',
  action: 'warning',
  progress: 'info',
  validating: 'accent',
  live: 'success',
  caution: 'warning',
  critical: 'danger',
};

export function toneVariant(tone: CapabilityTone): BadgeVariant {
  return TONE_VARIANT[tone];
}

export interface CapabilityStateStyle {
  readonly tone: CapabilityTone;
  readonly variant: BadgeVariant;
  /** Short human-readable label. */
  readonly label: string;
  /** Monospace glyph, matching the terminal aesthetic of the shared components. */
  readonly glyph: string;
  /** One-line, non-secret explanation safe to show a tenant/operator. */
  readonly description: string;
  /** True when this state must never be presented as production-live. */
  readonly notLive: boolean;
}

function style(
  tone: CapabilityTone,
  label: string,
  glyph: string,
  description: string,
  notLive: boolean,
): CapabilityStateStyle {
  return { tone, variant: TONE_VARIANT[tone], label, glyph, description, notLive };
}

const CAPABILITY_STATE_STYLES: Record<CapabilityState, CapabilityStateStyle> = {
  disabled: style('neutral', 'Disabled', '⊘', 'Turned off by an operator or a compliance hold.', true),
  disabled_intentionally: style('neutral', 'Disabled intentionally', '⊖', 'Deliberately omitted by product or release policy.', true),
  not_in_release: style('neutral', 'Not in release', '⊏', 'Not shipped in the active release class.', true),
  not_entitled: style('neutral', 'Not entitled', '⊝', 'Your plan does not include this capability.', true),
  unavailable: style('critical', 'Unavailable', '◇', 'Capability availability could not be established.', true),
  externally_blocked: style('action', 'Externally blocked', '⧖', 'An external provider or approval is blocking progress.', true),
  not_configured: style('neutral', 'Not configured', '○', 'No credentials or configuration supplied yet.', true),
  credential_required: style('action', 'Credential required', '⚿', 'Configuration present — provider credentials still needed.', true),
  credential_invalid: style('critical', 'Credential invalid', '⊗', 'The provider rejected the supplied credentials.', true),
  connection_testing: style('progress', 'Testing connection', '⟳', 'Probing the provider connection now.', true),
  credential_waiting: style('progress', 'Awaiting activation', '⋯', 'Credentials accepted — awaiting provider activation.', true),
  credential_supplied: style('progress', 'Credential supplied', '⊕', 'An active credential version exists — connection test pending.', true),
  provisioning: style('progress', 'Provisioning', '◌', 'Provider resources are being created.', true),
  replay_validated: style('validating', 'Replay validated', '⎌', 'Verified against replayed provider traffic — not live.', true),
  connection_validated: style('validating', 'Connection validated', '⊙', 'The supplied credential passed a real connection test — not live.', true),
  sandbox_validated: style('validating', 'Sandbox validated', '❖', 'Verified end-to-end in the provider sandbox — not production.', true),
  partner_live: style('live', 'Partner live', '●', 'Live against the production provider.', false),
  live: style('live', 'Live', '◆', 'Live against the production provider.', false),
  degraded: style('critical', 'Degraded', '▲', 'A dependency failed; showing reduced or last-known data.', false),
  stale: style('caution', 'Stale', '◔', 'Data is older than its freshness SLA.', false),
  partial: style('caution', 'Partial', '◑', 'Some expected inputs are present, not all.', false),
  error: style('critical', 'Error', '⚠', 'The capability read failed.', false),
  suspended: style('critical', 'Suspended', '⏸', 'Reversibly stopped by an operator or kill switch.', true),
  revoked: style('critical', 'Revoked', '⌀', 'Credentials were revoked — resubmission required.', true),
  kill_switch_active: style('critical', 'Kill switch active', '⛔', 'Halted by an active kill switch.', true),
};

export function capabilityStateStyle(state: CapabilityState): CapabilityStateStyle {
  return CAPABILITY_STATE_STYLES[state];
}

export function isCapabilityState(value: unknown): value is CapabilityState {
  return typeof value === 'string' && (capabilityStates as readonly string[]).includes(value);
}

/**
 * Precedence for rolling many capability states into one, ORDERED BEST → WORST.
 * A surface's overall badge never looks better than its weakest sub-capability.
 */
export const capabilityStatePrecedence: readonly CapabilityState[] = [
  'live',
  'partner_live',
  'sandbox_validated',
  'connection_validated',
  'credential_supplied',
  'replay_validated',
  'partial',
  'stale',
  'provisioning',
  'credential_waiting',
  'connection_testing',
  'credential_required',
  'not_configured',
  'not_entitled',
  'disabled',
  'disabled_intentionally',
  'not_in_release',
  'unavailable',
  'externally_blocked',
  'degraded',
  'credential_invalid',
  'error',
  'suspended',
  'revoked',
  'kill_switch_active',
];

/** Roll many capability states into the single worst one. */
export function worstCapabilityState(states: readonly CapabilityState[]): CapabilityState {
  if (states.length === 0) return 'unavailable';
  let worst = states[0]!;
  let worstRank = capabilityStatePrecedence.indexOf(worst);
  for (const s of states.slice(1)) {
    const rank = capabilityStatePrecedence.indexOf(s);
    if (rank > worstRank) {
      worstRank = rank;
      worst = s;
    }
  }
  return worst;
}

/**
 * Map a backend `ImplementationStatus` onto the capability matrix. Best-effort:
 * implementation maturity is a coarser signal than runtime credential state, so
 * anything pre-credential collapses to `not_configured` / `credential_required`.
 */
export function fromImplementationStatus(status: ImplementationStatus): CapabilityState {
  switch (status) {
    case 'mocked_local':
    case 'scaffolded':
      return 'not_configured';
    case 'production_shaped':
      return 'credential_required';
    case 'credential_gated':
      return 'credential_required';
    case 'staging_validation_required':
    case 'warehouse_datashare_ready':
      return 'sandbox_validated';
    case 'provider_live':
      return 'partner_live';
    case 'disabled_compliance_review':
    case 'deprecated':
      return 'disabled';
    default:
      return 'not_configured';
  }
}

/** Map a backend `DimensionState` (live data-availability) onto the matrix. */
export function fromDimensionState(state: DimensionState): CapabilityState {
  switch (state) {
    case 'ready':
      return 'partner_live';
    case 'empty':
      return 'not_configured';
    case 'partial':
    case 'insufficient_data':
      return 'partial';
    case 'stale':
      return 'stale';
    case 'degraded':
      return 'degraded';
    case 'suppressed':
    case 'not_applicable':
      return 'not_entitled';
    case 'pending':
      return 'credential_waiting';
    case 'error':
      return 'error';
    default:
      return 'error';
  }
}

/**
 * Lenient normalizer for the small ad-hoc status enums surfaces already receive
 * from the server (e.g. PaymentProviderAccount.status = 'configured' |
 * 'not_configured' | 'error' | 'disabled'; PaymentRailHealth.status = 'healthy' |
 * 'degraded' | 'not_configured' | 'error'). Returns `null` for unrecognized
 * input so callers can pick an explicit fallback rather than inventing a state.
 */
export function resolveCapabilityState(raw: string | null | undefined): CapabilityState | null {
  if (raw == null) return null;
  const key = raw.trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (key === '') return null;
  if (isCapabilityState(key)) return key;
  switch (key) {
    case 'configured':
    case 'active':
    case 'enabled':
    case 'healthy':
    case 'live':
    case 'ready':
    case 'ok':
    case 'connected':
    case 'provider_live':
      return 'partner_live';
    case 'sandbox':
    case 'sandbox_ok':
    case 'staging':
    case 'staging_validation_required':
    case 'warehouse_datashare_ready':
      return 'sandbox_validated';
    case 'replay':
    case 'replay_ok':
      return 'replay_validated';
    case 'unconfigured':
    case 'none':
    case 'missing':
    case 'empty':
    case 'not_set':
    case 'mocked_local':
    case 'scaffolded':
      return 'not_configured';
    case 'credential_gated':
    case 'needs_credentials':
    case 'awaiting_credentials':
    case 'production_shaped':
      return 'credential_required';
    case 'invalid':
    case 'unauthorized':
    case 'rejected':
    case 'auth_failed':
      return 'credential_invalid';
    case 'testing':
    case 'probing':
    case 'verifying':
    case 'pending_verification':
      return 'connection_testing';
    case 'pending':
    case 'provisioning':
    case 'activating':
    case 'waiting':
      return 'credential_waiting';
    case 'not_entitled':
    case 'unlicensed':
    case 'suppressed':
    case 'not_applicable':
    case 'forbidden':
      return 'not_entitled';
    case 'disabled':
    case 'deprecated':
    case 'disabled_compliance_review':
    case 'off':
    case 'inactive':
    case 'deactivated':
      return 'disabled';
    case 'degraded':
    case 'unhealthy':
      return 'degraded';
    case 'stale':
      return 'stale';
    case 'partial':
    case 'insufficient_data':
      return 'partial';
    case 'error':
    case 'failed':
    case 'failure':
    case 'fault':
      return 'error';
    case 'kill_switch':
    case 'killswitch':
    case 'halted':
    case 'tripped':
      return 'kill_switch_active';
    default:
      return null;
  }
}
