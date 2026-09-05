/**
 * UniversalObservationEnvelope (Envelope B) — passive TypeScript contract twin.
 *
 * The canonical server-side observation model that every ingress adapter
 * builds and the universal ingestion gateway validates. This file is a
 * passive *contract* mirror of the runtime model in
 * `Backend Architecture/aether-backend/shared/observation/envelope.py`
 * and the canonical field registry at
 * `packages/shared/contracts/observation-envelope-registry.json`.
 *
 * It is deliberately NOT a client emitter: nothing here constructs or sends
 * envelopes (see packages/shared/sdk-parity.json — "observation-envelope
 * builder — no client-side emit pipeline"). Envelope B is created inside
 * Aether by adapters; the SDK keeps producing Envelope A (BaseEvent).
 *
 * Parity is enforced by tests/contracts/test_observation_envelope_parity.py.
 */

// ── Curated vocabularies (mirror of observation-envelope-registry.json) ───────

/** Ingress source types (blueprint §5 adapter families). */
export const SOURCE_TYPES = [
  'sdk',
  'webhook',
  'connector',
  'feed',
  'import',
  'harness',
  'replay',
] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

/** Subject identifier types (blueprint §6 identifier-type vocabulary). */
export const IDENTIFIER_TYPES = [
  'anonymous_id',
  'user_id',
  'account_id',
  'email_hash',
  'phone_hash',
  'wallet_address',
  'device_id',
  'session_id',
  'organization_user_id',
  'agent_id',
  'service_account_id',
  'external_customer_id',
  'provider_account_id',
] as const;
export type IdentifierType = (typeof IDENTIFIER_TYPES)[number];

/** Ingress credential/trust classes (blueprint §11). */
export const CREDENTIAL_CLASSES = [
  'PUBLIC_CLIENT',
  'TRUSTED_CLIENT',
  'TENANT_SERVER',
  'VERIFIED_WEBHOOK',
  'MANAGED_CONNECTOR',
  'AETHER_INTERNAL',
  'OPERATOR_REPLAY',
] as const;
export type CredentialClass = (typeof CREDENTIAL_CLASSES)[number];

/**
 * Field-authority trust classes, rank-ordered OBSERVED..OPERATOR_ASSERTED.
 * Owned by event-registry.json#trustClasses; the parity test asserts this
 * array equals generated_registry.TRUST_CLASS_ORDER.
 */
export const TRUST_CLASSES = [
  'OBSERVED',
  'SOURCE_ASSERTED',
  'SOURCE_REFERENCE',
  'CLIENT_HINT',
  'SERVER_STAMPED',
  'RESOLVED',
  'DERIVED',
  'INFERRED',
  'PREDICTED',
  'OPERATOR_ASSERTED',
] as const;
export type TrustClass = (typeof TRUST_CLASSES)[number];

export const OBSERVATION_ENVELOPE_SCHEMA_VERSION = '1.0.0';

// ── Envelope blocks (field names mirror the runtime model / registry) ─────────

export interface ObservationBlock {
  observation_id: string;
  observation_type: string;
  family?: string;
  occurred_at: string; // ISO-8601 instant
  received_at: string; // ISO-8601 instant
  ingested_at: string; // ISO-8601 instant
  schema_version: string;
}

export interface TenancyBlock {
  tenant_id: string;
  deployment_id?: string;
  environment?: string;
}

export interface SourceBlock {
  source_type: SourceType;
  source_provider?: string;
  source_instance?: string;
  source_native_id?: string;
  ingress_path?: string;
}

export interface SubjectRef {
  identifier_type: IdentifierType;
  identifier_value: string;
  actor_role?: string;
  /**
   * Field-authority trust class; the SDK boundary caps this at CLIENT_HINT.
   * Always present on a built envelope — the runtime model defaults an unset
   * subject to `OBSERVED` — so the contract type mirrors that guarantee.
   */
  trust_class: TrustClass;
  namespace?: string;
  verification_hint?: string;
  source?: string;
}

export interface TemporalBlock {
  /** Raw source-clock claim, preserved verbatim (never reinterpreted). */
  source_time?: string;
  timezone?: string;
  utc_offset?: string;
  clock_source?: string;
  sequence?: string;
  temporal_quality?: string;
}

export interface CorrelationBlock {
  correlation_id?: string;
  causation_id?: string;
  trace_id?: string;
  span_id?: string;
  parent_observation_id?: string;
}

export interface PrivacyBlock {
  consent_snapshot?: string;
  purposes?: readonly string[];
  GPC?: boolean;
  DNT?: boolean;
  policy_decisions?: readonly string[];
}

export interface ProvenanceBlock {
  credential_class?: CredentialClass;
  signature_status?: string;
  adapter?: string;
  adapter_version?: string;
  source_trust?: string;
}

export interface QualityBlock {
  completeness?: string;
  freshness?: string;
  sequencing_state?: string;
  validation_state?: string;
}

export interface LineageBlock {
  raw_record_ref?: string;
  normalization_version?: string;
  validation_version?: string;
}

/** Passthrough A-side sub-envelope (registry passthrough_blocks). */
export type AetherSubEnvelope = Record<string, unknown>;

export interface UniversalObservationEnvelope {
  observation: ObservationBlock;
  tenancy: TenancyBlock;
  source: SourceBlock;
  subjects?: readonly SubjectRef[];

  temporal?: TemporalBlock;
  correlation?: CorrelationBlock;

  acquisition?: AetherSubEnvelope;
  application?: AetherSubEnvelope;
  surface?: AetherSubEnvelope;
  device?: AetherSubEnvelope;
  network?: AetherSubEnvelope;
  payload?: AetherSubEnvelope;

  privacy?: PrivacyBlock;
  provenance?: ProvenanceBlock;
  quality?: QualityBlock;
  lineage?: LineageBlock;
}
