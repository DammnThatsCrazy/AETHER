/**
 * Canonical Reconciled Control Plane contract — ManagedIntegrations.
 *
 * The control plane is Aether's operational authority that continuously
 * converges every managed integration (SDKs, connectors, provider connections,
 * webhooks, imports, feeds) toward an authorized, healthy, supportable desired
 * state. Governing principles: *the SDK observes; the control plane manages;
 * the backend reasons*; "install once, continuously reconcile".
 *
 * Phase 0 ships the ManagedIntegration abstraction + reconcile *skeleton* only.
 * Nothing here enables a mutation: there is no live reconcile trigger and no
 * actuator. Drift is classified and evidence is persisted; applying a
 * ChangeSet is explicitly deferred (CP-08 boundary).
 *
 * The Python mirror lives at
 * `Backend Architecture/aether-backend/services/managed_integrations/contracts.py`;
 * the const arrays below are parity-tested against it by
 * `tests/contracts/test_managed_integrations_parity.py`.
 *
 * Vocabulary provenance (Reconciled Control Plane Blueprint):
 * - Managed integration kinds      §6
 * - typed availability (CP-12)     §4  — `missing`, `empty`, `zero`, `degraded`
 *                                     and `not_applicable` remain distinct; no
 *                                     operator surface fabricates zero/empty for
 *                                     missing evidence.
 * - source origin / owner          §6
 * - tenant update channels         §28
 * - reconcile result               §32 (steps 10–11)
 * - observed-state provenance      §12.2
 * - drift types                    §33. `managedDriftTypes` is the Phase-0
 *                                     *emitted* subset (six dimensions the Phase-0
 *                                     reconciler actually diffs); the full §33
 *                                     taxonomy (contract/mapping/config/policy/
 *                                     consent/... drift) is reserved for later
 *                                     phases and must not be narrowed here.
 */

// ── §6 supported kinds ──────────────────────────────────────────────────────

export const managedIntegrationKinds = [
  'sdk_web',
  'sdk_ios',
  'sdk_android',
  'sdk_react_native',
  'sdk_desktop',
  'sdk_node',
  'sdk_python',
  'sdk_rust',
  'sdk_other',
  'connector_aether_hosted',
  'connector_customer_hosted',
  'provider_runtime_connection',
  'webhook',
  'api_ingress',
  'stream_ingress',
  'file_import',
  'warehouse_sync',
  'agent_harness',
  'agent_connector',
  'external_dataset',
  'olympus_curated_feed',
] as const;
export type ManagedIntegrationKind = (typeof managedIntegrationKinds)[number];

// ── §6 source origin / owner ────────────────────────────────────────────────

export const integrationSourceOrigins = [
  'tenant',
  'provider',
  'olympus',
  'shared_system',
] as const;
export type IntegrationSourceOrigin = (typeof integrationSourceOrigins)[number];

export const integrationSourceOwners = ['tenant', 'olympus', 'provider'] as const;
export type IntegrationSourceOwner = (typeof integrationSourceOwners)[number];

// ── §28 tenant update channels (desired release channel) ────────────────────

export const managedReleaseChannels = [
  'pinned',
  'security_auto',
  'patch_auto',
  'compatible_auto',
  'managed_stable',
] as const;
export type ManagedReleaseChannel = (typeof managedReleaseChannels)[number];

/** `managed_stable` is the Phase-0 desired-state default. It is NOT equivalent
 * to uncontrolled `latest`: the control plane reconciles *toward* the channel,
 * never blindly follows the newest published build. */
export const defaultManagedReleaseChannel = 'managed_stable' as const;

// ── CP-12 typed availability ────────────────────────────────────────────────

export const integrationAvailabilityValues = [
  'available',
  'empty',
  'missing',
  'degraded',
  'not_applicable',
  'unknown',
] as const;
export type IntegrationAvailability = (typeof integrationAvailabilityValues)[number];

// ── §32 reconcile results (steps 10–11) ─────────────────────────────────────

export const reconcileResultValues = [
  'match',
  'acceptable_drift',
  'actionable_drift',
  'blocked',
  'unknown',
] as const;
export type ReconcileResult = (typeof reconcileResultValues)[number];

// ── §33 drift types (Phase-0 emitted subset) ────────────────────────────────

export const managedDriftTypes = [
  'version_drift',
  'capability_drift',
  'schema_drift',
  'health_drift',
  'release_support_drift',
  'fleet_identity_drift',
] as const;
export type ManagedDriftType = (typeof managedDriftTypes)[number];

// ── §12.2 observed-state provenance ─────────────────────────────────────────

export const observedProvenanceValues = [
  'runtime_reported',
  'backend_verified',
  'provider_reported',
  'operator_supplied',
  'inferred',
  'unknown',
] as const;
export type ObservedProvenance = (typeof observedProvenanceValues)[number];

// ── helpers ─────────────────────────────────────────────────────────────────

export function isManagedIntegrationKind(value: string): value is ManagedIntegrationKind {
  return (managedIntegrationKinds as readonly string[]).includes(value);
}

export function isIntegrationAvailability(value: string): value is IntegrationAvailability {
  return (integrationAvailabilityValues as readonly string[]).includes(value);
}

export function isReconcileResult(value: string): value is ReconcileResult {
  return (reconcileResultValues as readonly string[]).includes(value);
}

export function isManagedDriftType(value: string): value is ManagedDriftType {
  return (managedDriftTypes as readonly string[]).includes(value);
}

// ── §6 ManagedIntegrationView (Phase-0 operator read surface) ───────────────
// Mirrors the durable `managed_integrations` row. Health/lifecycle states are
// strings sourced from the observing authority (SDK health, provider runtime,
// capability activation); they are never inferred from row existence.

export interface ManagedIntegrationView {
  managed_integration_id: string;
  tenant_id: string;
  environment_id: string;
  integration_kind: ManagedIntegrationKind;
  source_ref: string;
  provider_ref?: string | null;
  source_origin: IntegrationSourceOrigin;
  source_owner: IntegrationSourceOwner;
  release_channel: ManagedReleaseChannel;
  health_state: string;
  lifecycle_state: string;
  schema_fingerprint?: string | null;
  desired_state_ref?: string | null;
  observed_state_ref?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  last_reconcile_at?: string | null;
  last_reconcile_result?: ReconcileResult | null;
  created_at: string;
  updated_at: string;
}

// ── §12.1 DesiredStateSpec (Phase-0 assembled subset) ───────────────────────

export interface MinimumCapabilityRequirement {
  capability: string;
  required_availability: IntegrationAvailability;
}

export interface DesiredStateSpec {
  desired_state_id: string;
  managed_integration_ref: string;
  tenant_id: string;
  environment_id: string;
  revision: string;
  release_channel: ManagedReleaseChannel;
  /** Inclusive runtime/SDK version floor the observed runtime must meet
   * (resolved from the desired release channel against SDK version tiers). */
  minimum_runtime_version?: string | null;
  minimum_capabilities: MinimumCapabilityRequirement[];
  /** Canonical event-schema fingerprint the observed runtime must match
   * (resolved from the active schema authority; null = not reconciled). */
  schema_fingerprint?: string | null;
  health_policy_ref?: string | null;
  integration_contract_ref?: string | null;
  created_at: string;
}

// ── §12.2 ObservedStateSnapshot (Phase-0 sensor-assembled subset) ───────────

export interface ObservedStateSnapshot {
  observed_state_id: string;
  managed_integration_ref: string;
  tenant_id: string;
  environment_id: string;
  observed_at: string;
  received_at: string;
  /** Distinguishes runtime-reported / backend-verified / provider-reported /
   * operator-supplied / inferred / unknown facts (blueprint §12.2). */
  provenance: ObservedProvenance;
  availability: IntegrationAvailability;
  runtime_version?: string | null;
  platform?: string | null;
  schema_fingerprint?: string | null;
  queue_state?: Record<string, unknown> | null;
  ingestion_state?: string | null;
  auth_state?: string | null;
  consent_state?: string | null;
  provider_state?: string | null;
  endpoint_state?: string | null;
  health_ref?: string | null;
  /** Health classification reported by the observing health authority
   * (`healthy` | `degraded` | `unhealthy` | `silent` for SDK health). */
  health_status?: string | null;
  /** The fleet identity the runtime claims (e.g. SDK installation id / provider
   * identity) — compared against the managed integration's registered source_ref. */
  reported_source_identity?: string | null;
  last_successful_observation_at?: string | null;
}

// ── §12.4 DriftRecord (Phase-0 subset) ──────────────────────────────────────

export interface DriftRecord {
  drift_id: string;
  managed_integration_ref: string;
  desired_state_ref?: string | null;
  observed_state_ref?: string | null;
  drift_type: ManagedDriftType;
  detail: string;
  first_seen_at: string;
  last_seen_at: string;
}

// ── §32 ReconcileRunView ────────────────────────────────────────────────────

export interface ReconcileRunView {
  reconcile_id: string;
  managed_integration_ref: string;
  desired_state_ref: string;
  observed_state_ref: string;
  desired_revision: string;
  observed_revision: string;
  freshness_ok: boolean;
  result: ReconcileResult;
  /** Human-readable explanation when drift is not actionable — why the run was
   * `unknown` (stale / no observation), `blocked` (upstream fail-closed), or
   * which evidence is missing. Null on a plain match/actionable run. */
  note?: string | null;
  /** DRAFT change summary — evidence only. Never applied by Phase 0 (CP-08). */
  drift: DriftRecord[];
  created_at: string;
}
