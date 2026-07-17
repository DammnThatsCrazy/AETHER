/**
 * DO NOT EDIT — generated from packages/shared/contracts/context-capsule-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const contextCapsuleContractVersion = '1.0.0' as const;

/** Where a location observation came from. */
export const locationSources = [
  'server_network_ip',
  'device_coarse',
  'device_precise',
  'verified_venue',
  'tenant_supplied_venue',
  'qr_or_checkin',
  'shipping_address',
  'billing_address',
  'payment_instrument_country',
  'provider_reported',
  'organization_registered',
  'agent_execution_region',
  'server_execution_region',
  'imported_historical',
] as const;
export type LocationSource = typeof locationSources[number];

/** What a location observation actually means. */
export const locationSemantics = [
  'network_egress',
  'likely_physical_presence',
  'verified_physical_presence',
  'declared_address',
  'commercial_destination',
  'billing_jurisdiction',
  'organization_location',
  'execution_region',
  'venue_association',
  'unknown',
] as const;
export type LocationSemantic = typeof locationSemantics[number];

/** Coarsest-to-finest location precision classes. */
export const locationPrecisionClasses = [
  'country',
  'region',
  'city',
  'coarse_cell',
  'precise',
] as const;
export type LocationPrecisionClass = typeof locationPrecisionClasses[number];

/** Agreement state between concurrent location observations. */
export const locationConflictStates = [
  'none',
  'explainable',
  'unresolved',
  'contradictory',
] as const;
export type LocationConflictState = typeof locationConflictStates[number];

/** Interpreted context state for a subject at capsule time. */
export const contextStates = [
  'normal_primary',
  'normal_secondary',
  'expected_recurring',
  'temporary_travel',
  'transient',
  'new_context',
  'returning_to_baseline',
  'commute_pattern',
  'network_egress_only',
  'possible_vpn',
  'possible_datacenter',
  'location_uncertain',
  'location_conflict',
  'improbable_transition',
  'not_applicable',
  'suppressed',
  'insufficient_evidence',
] as const;
export type ContextState = typeof contextStates[number];

/** Named retention classes (constraints in contextRetentionClasses). */
export const contextRetentionClassNames = [
  'coarse_location_observation',
  'context_capsule',
  'derived_baseline',
  'ephemeral_network_token',
  'precise_location_observation',
  'raw_ip',
] as const;
export type ContextRetentionClass = typeof contextRetentionClassNames[number];

/** Retention constraint attached to each retention class. */
export interface ContextRetentionPolicy {
  maxHours?: number;
  maxDays?: number;
  tenantPolicy?: boolean;
  inheritsStrictest?: boolean;
  aggregateOnly?: boolean;
}

export const contextRetentionClasses: Record<ContextRetentionClass, ContextRetentionPolicy> = {
  coarse_location_observation: { maxDays: 30 },
  context_capsule: { inheritsStrictest: true },
  derived_baseline: { aggregateOnly: true },
  ephemeral_network_token: { maxHours: 24 },
  precise_location_observation: { tenantPolicy: true },
  raw_ip: { maxHours: 0 },
};

/** Why a new context capsule superseded the previous one. */
export const capsuleTransitionTypes = [
  'session_start',
  'device_change',
  'network_change',
  'location_cluster_change',
  'campaign_change',
  'consent_change',
  'identity_resolved',
  'actor_change',
  'journey_handoff',
  'runtime_change',
  'precision_upgrade',
] as const;
export type CapsuleTransitionType = typeof capsuleTransitionTypes[number];

/** One privacy-shaped location observation — no raw IP, no lat/lon (Python twin: shared/context_capsule/models.py). */
export interface LocationObservation {
  observation_id: string;
  tenant_id: string;
  subject_type?: string | null;
  subject_id?: string | null;
  session_id?: string | null;
  source_event_id?: string | null;
  source: string;
  semantics: string;
  precision_class: string;
  country_code?: string | null;
  region_code?: string | null;
  city?: string | null;
  coarse_cell?: string | null;
  accuracy_radius_meters?: number | null;
  confidence?: number | null;
  observed_at: string;
  received_at?: string | null;
  provider?: string | null;
  provider_database_version?: string | null;
  vpn_likelihood?: number | null;
  proxy_likelihood?: number | null;
  tor_likelihood?: number | null;
  datacenter_likelihood?: number | null;
  consent_snapshot_id?: string | null;
  retention_class?: string | null;
  suppression_state?: string | null;
  schema_version?: string | null;
}

/** Versioned context capsule for a session slice (Python twin: shared/context_capsule/models.py). */
export interface ContextCapsule {
  capsule_id: string;
  tenant_id: string;
  session_id?: string | null;
  capsule_version: number;
  valid_from: string;
  valid_to?: string | null;
  actor_id?: string | null;
  actor_kind?: string | null;
  canonical_entity_id?: string | null;
  identity_confidence?: number | null;
  device_id?: string | null;
  device_platform?: string | null;
  device_class?: string | null;
  app_version?: string | null;
  sdk_name?: string | null;
  sdk_version?: string | null;
  network_observation_id?: string | null;
  network_connection_type?: string | null;
  network_asn_class?: string | null;
  network_vpn_likelihood?: number | null;
  network_proxy_likelihood?: number | null;
  network_datacenter_likelihood?: number | null;
  geo_resolved_location_id?: string | null;
  geo_source_semantics?: string | null;
  geo_country_code?: string | null;
  geo_region_code?: string | null;
  geo_city?: string | null;
  geo_coarse_cell?: string | null;
  geo_confidence?: number | null;
  geo_conflict_state?: string | null;
  campaign_id?: string | null;
  campaign_source?: string | null;
  campaign_medium?: string | null;
  journey_id?: string | null;
  journey_stage?: string | null;
  prior_capsule_id?: string | null;
  consent_snapshot_id?: string | null;
  policy_jurisdiction?: string | null;
  retention_class?: string | null;
  suppression_state?: string | null;
  source_event_id?: string | null;
  schema_version?: string | null;
  context_hash?: string | null;
}
