/**
 * Canonical temporal contract.
 *
 * Platform invariant: exact moments are UTC instants; source-local context is
 * evidence; calendar rules name an explicit temporal authority; interactive
 * presentation defaults to the viewer. The Python twin of these vocabularies
 * lives at `shared/temporal/` (parity-tested by
 * `tests/contracts/test_temporal_contract_parity.py`).
 */

/** Stable machine-readable reasons a temporal value was rejected/flagged. */
export const temporalReasonCodes = [
  'timestamp_invalid',          // malformed / unparseable
  'timestamp_naive',            // no offset or Z — never silently assumed UTC
  'timestamp_future',           // beyond tolerated forward clock skew
  'timestamp_too_old',          // beyond the allowed lateness policy
  'timezone_invalid',           // not an IANA zone id (abbreviations rejected)
  'timezone_offset_mismatch',   // claimed zone and offset disagree at the instant
  'local_time_ambiguous',       // DST fall-back — wall time occurs twice
  'local_time_nonexistent',     // DST spring-forward — wall time never occurs
  'temporal_authority_missing', // calendar rule evaluated without an authority
  'temporal_policy_violation',  // registered temporal policy was violated
  'temporal_provenance_missing',// exact instant valid but source tz unavailable
  'clock_skew_warning',         // skew above warn threshold, within tolerance
  'delivery_lag_warning',       // delivery delay above warn threshold
] as const;

export type TemporalReasonCode = typeof temporalReasonCodes[number];

/** Classified temporal state of an accepted (or quarantined) event. */
export const temporalStates = [
  'valid',
  'normalized',
  'legacy_inferred',
  'skewed',
  'late',
  'future',
  'ambiguous',
  'timezone_unknown',
  'authority_missing',
  'invalid',
  'quarantined',
] as const;

export type TemporalState = typeof temporalStates[number];

/** Where a source timezone claim came from. */
export const timeZoneSources = [
  'device',
  'user_preference',
  'provider',
  'tenant',
  'geoip',
  'import_mapping',
  'server',
  'unknown',
] as const;

export type TimeZoneSource = typeof timeZoneSources[number];

/** Which clock produced an event timestamp. */
export const clockSources = [
  'device',
  'provider',
  'server',
  'blockchain',
  'import',
] as const;

export type ClockSource = typeof clockSources[number];

/** Declared precision of a source timestamp. */
export const temporalPrecisions = [
  'second',
  'millisecond',
  'microsecond',
  'nanosecond',
] as const;

export type TemporalPrecision = typeof temporalPrecisions[number];

/** Who owns the calendar for a calendar-based operation. */
export const temporalAuthorities = [
  'viewer',
  'source',
  'tenant_business',
  'campaign',
  'contract',
  'provider',
  'market',
  'legal_policy',
  'investigation',
  'server',
  'utc',
] as const;

export type TemporalAuthority = typeof temporalAuthorities[number];

/** DST gap (spring-forward) resolution policies. */
export const dstGapPolicies = ['shift_forward', 'reject'] as const;
export type DstGapPolicy = typeof dstGapPolicies[number];

/** DST overlap (fall-back) resolution policies. */
export const dstOverlapPolicies = ['earlier_offset', 'later_offset', 'reject'] as const;
export type DstOverlapPolicy = typeof dstOverlapPolicies[number];

/**
 * Server-computed temporal facts for one accepted event (Python twin:
 * `shared/temporal/envelope.py::EventTemporalEnvelope`). Serialized snake_case
 * because it is persisted server-side alongside Bronze rows.
 */
export interface EventTemporalEnvelope {
  occurred_at: string;
  sent_at?: string | null;
  received_at: string;

  source_timestamp_original?: string | null;
  source_time_zone?: string | null;
  source_utc_offset_minutes?: number | null;
  source_locale?: string | null;

  time_zone_source: TimeZoneSource;
  clock_source: ClockSource;
  precision: TemporalPrecision;

  clock_skew_ms?: number | null;
  delivery_lag_ms?: number | null;

  temporal_state: TemporalState;
  reason_codes: TemporalReasonCode[];

  temporal_policy_version?: string | null;
  tzdb_version?: string | null;
}

/**
 * Optional client-supplied temporal provenance on the event `context`
 * (wire-format camelCase, matching the ingestion contract). All fields are
 * evidence — the server computes the authoritative envelope.
 */
export interface TemporalContextHint {
  timezone?: string;           // IANA zone id captured at occurrence
  utcOffsetMinutes?: number;   // offset at occurrence (not at SDK init)
  timeZoneSource?: TimeZoneSource;
  clockSource?: ClockSource;
  locale?: string;
}

/** An exact half-open instant interval. */
export interface InstantRange {
  kind: 'instant';
  start: string;          // inclusive, canonical UTC `Z`
  endExclusive: string;   // exclusive
}

/** A local calendar-date range awaiting zone resolution. */
export interface LocalDateRange {
  kind: 'local_date';
  startDate: string;          // inclusive, `YYYY-MM-DD`
  endDateExclusive: string;   // exclusive, `YYYY-MM-DD`
  timeZone: string;           // IANA zone id
}

export type TemporalRange = InstantRange | LocalDateRange;

/** Temporal metadata every range-resolving response should expose. */
export interface TemporalMeta {
  requestedTimeZone?: string | null;
  effectiveTimeZone: string;
  authority: TemporalAuthority;
  windowUtc: { start: string; endExclusive: string };
  tzdbVersion?: string | null;
  temporalPolicyVersion?: string | null;
}
