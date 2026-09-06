/**
 * Canonical Reconciled Control Plane contract — ManagedIntegrations.
 *
 * The control plane is Aether's operational authority that continuously
 * converges every managed integration (SDKs, connectors, provider connections,
 * webhooks, imports, feeds) toward an authorized, healthy, supportable desired
 * state. Governing principles: *the SDK observes; the control plane manages;
 * the backend reasons*; "install once, continuously reconcile".
 *
 * Phase 0 shipped the ManagedIntegration abstraction + reconcile *skeleton*:
 * no live reconcile trigger and no actuator; drift was classified and evidence
 * persisted (CP-08 boundary — a ChangeSet was never applied).
 *
 * Phase 1 (the additions below) ships the *planning* half of the reconcile
 * loop: the canonical §33 drift taxonomy, the §34 ChangeSet status vocabulary,
 * the §39 risk classes, the §36 change-action kinds, and the ChangeSet plan /
 * risk-assessment / blast-radius views. A plan is still never applied —
 * execution (actuator engine, approval, rollout) is a later phase.
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
 * - drift types (emitted subset)   §33. `managedDriftTypes` is the Phase-0
 *                                     *emitted* subset — the six dimensions the
 *                                     Phase-0 reconciler diffs. Every emitted
 *                                     value is a member of the canonical
 *                                     taxonomy; the two must never drift apart.
 * - drift taxonomy (canonical)     §33. `driftTaxonomyTypes` is the full 22-type
 *                                     taxonomy. Not every drift requires a
 *                                     mutation; planning may treat many as
 *                                     non-actionable.
 * - ChangeSet status vocabulary    §34. `changeSetStatuses` models the full
 *                                     state-machine vocabulary. Illegal
 *                                     transitions fail closed; transition
 *                                     *legality* is enforced by the executor
 *                                     (a later phase), not by this vocabulary.
 * - risk classes                   §39. `changeRiskClasses` = R0 trivial →
 *                                     R5 destructive/high-consequence, plus the
 *                                     security-emergency class governed by
 *                                     Security Blueprint policy.
 * - change-action kinds            §36. `changeActionKinds` names the typed
 *                                     operations the Day-1 actuators perform.
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

// ── §33 canonical drift taxonomy (full 22-type set) ─────────────────────────

export const driftTaxonomyTypes = [
  'version_drift',
  'capability_drift',
  'contract_drift',
  'schema_drift',
  'mapping_drift',
  'config_drift',
  'policy_drift',
  'authority_drift',
  'consent_drift',
  'platform_permission_drift',
  'provider_scope_drift',
  'provider_terms_drift',
  'endpoint_drift',
  'health_drift',
  'data_quality_drift',
  'release_support_drift',
  'fleet_identity_drift',
  'region_drift',
  'credential_drift',
  'source_authority_drift',
  'volume_drift',
  'cost_drift',
] as const;
export type DriftTaxonomyType = (typeof driftTaxonomyTypes)[number];

// ── §34 ChangeSet status vocabulary ─────────────────────────────────────────

export const changeSetStatuses = [
  'draft',
  'planned',
  'preparing',
  'validating',
  'simulating',
  'waiting_approval',
  'ready',
  'canary',
  'rolling_out',
  'verifying',
  'committed',
  'rolling_back',
  'rolled_back',
  'cancelled',
  'blocked',
  'failed',
  'superseded',
] as const;
export type ChangeSetStatus = (typeof changeSetStatuses)[number];

// ── §39 change-risk classes ─────────────────────────────────────────────────

export const changeRiskClasses = [
  'R0',
  'R1',
  'R2',
  'R3',
  'R4',
  'R5',
  'security_emergency',
] as const;
export type ChangeRiskClass = (typeof changeRiskClasses)[number];

// ── §36 change-action kinds (Day-1 typed actuator operations) ───────────────

export const changeActionKinds = [
  'remote_manifest_change',
  'managed_connector_change',
  'provider_runtime_change',
  'mapping_change',
  'compatibility_projection_change',
  'repository_upgrade',
  'authorization_change',
  'quarantine',
  'replay',
  'backfill',
  'rollback',
  'notification_action',
] as const;
export type ChangeActionKind = (typeof changeActionKinds)[number];

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

export function isDriftTaxonomyType(value: string): value is DriftTaxonomyType {
  return (driftTaxonomyTypes as readonly string[]).includes(value);
}

export function isChangeSetStatus(value: string): value is ChangeSetStatus {
  return (changeSetStatuses as readonly string[]).includes(value);
}

export function isChangeRiskClass(value: string): value is ChangeRiskClass {
  return (changeRiskClasses as readonly string[]).includes(value);
}

export function isChangeActionKind(value: string): value is ChangeActionKind {
  return (changeActionKinds as readonly string[]).includes(value);
}

export function isControlFindingKind(value: string): value is ControlFindingKind {
  return (controlFindingKinds as readonly string[]).includes(value);
}

export function isVerifyOutcome(value: string): value is VerifyOutcome {
  return (verifyOutcomes as readonly string[]).includes(value);
}

export function isRollbackStatus(value: string): value is RollbackStatus {
  return (rollbackStatuses as readonly string[]).includes(value);
}

export function isActionRequiredStatus(
  value: string,
): value is ActionRequiredStatus {
  return (actionRequiredStatuses as readonly string[]).includes(value);
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

// ── §36 ChangeSpec — one typed mutation a plan may carry ─────────────────────

export interface ChangeSpec {
  /** The typed operation (named after the §36 Day-1 actuator that would run
   * it). Vocabulary only in Phase 1 — nothing executes a plan. */
  action: ChangeActionKind;
  /** The managed integration / contract / artifact the action targets. */
  target_ref: string;
  /** Action-specific parameters; typed by the owning actuator in Phase 2. */
  params?: Record<string, unknown> | null;
  reason?: string | null;
}

// ── §32-14 risk assessment (§12.6 RiskAssessmentContract subset) ────────────

export interface RiskAssessmentView {
  risk_class: ChangeRiskClass;
  /** True when the class may proceed automatically under policy. Every other
   * class routes to the approval/action authority (§32 step 15). */
  automation_allowed: boolean;
  required_approval_refs: string[];
  explanation_refs: string[];
}

// ── §32-13 control-topology blast radius ────────────────────────────────────

export interface BlastRadiusView {
  integration_count: number;
  tenant_count: number;
  environment_count: number;
  source_origins: IntegrationSourceOrigin[];
  /** Canonical drift types the candidate change would actually touch. */
  actionable_drift_types: DriftTaxonomyType[];
}

// ── §12.15 control-finding kinds (canonical epistemic model) ────────────────

export const controlFindingKinds = [
  'observed',
  'verified',
  'correlated',
  'inferred',
  'predicted',
] as const;
export type ControlFindingKind = (typeof controlFindingKinds)[number];

// ── §32 step 19 verify outcomes (technical + semantic health) ───────────────

export const verifyOutcomes = ['passed', 'failed'] as const;
export type VerifyOutcome = (typeof verifyOutcomes)[number];

// ── §12.13 evidence confidence scale (mirrors the §39 rollback-confidence
//    high/medium/low scale) ─────────────────────────────────────────────────

export const evidenceConfidenceValues = ['high', 'medium', 'low'] as const;
export type EvidenceConfidence = (typeof evidenceConfidenceValues)[number];

// ── §12.11 rollback-record lifecycle ─────────────────────────────────────────

export const rollbackStatuses = [
  'pending',
  'rolling_back',
  'rolled_back',
  'failed',
] as const;
export type RollbackStatus = (typeof rollbackStatuses)[number];

// ── §12.14 action-required lifecycle ─────────────────────────────────────────

export const actionRequiredStatuses = ['open', 'resolved'] as const;
export type ActionRequiredStatus = (typeof actionRequiredStatuses)[number];

// ── §32 step 12 + §12.5 ChangeSetPlanView (planning subset, never applied) ──

export interface ChangeSetPlanView {
  changeset_id: string;
  tenant_id: string;
  environment_id: string;
  /** Control-topology scope: managed integrations the change would reach. */
  integration_scope: string[];
  /** §35 concurrency guard: never execute a plan whose guard revisions do not
   * match the state a later run reconciled against. */
  desired_revision: string;
  observed_revision: string;
  reconcile_sequence: string;
  idempotency_key: string;
  changes: ChangeSpec[];
  reason?: string | null;
  initiator: string;
  policy_ref?: string | null;
  risk: RiskAssessmentView;
  blast_radius: BlastRadiusView;
  /** §34 status. Phase 1 plans reach at most `planned`; a guard invalidation
   * moves a plan to `superseded`. Execution statuses are unreachable here. */
  status: ChangeSetStatus;
  created_at: string;
  superseded_at?: string | null;
}

// ── §32 step 19 VerifyReport (technical + semantic health) ──────────────────

export interface VerifyReport {
  changeset_id: string;
  technical_health: VerifyOutcome;
  semantic_health: VerifyOutcome;
  /** Refs to per-change verification evidence (actuator verify outcomes). */
  validation_refs: string[];
  note?: string | null;
  verified_at: string;
}

// ── §12.13 ChangeEvidenceView ────────────────────────────────────────────────

export interface ChangeEvidenceView {
  change_evidence_id: string;
  changeset_ref: string;
  tenant_id: string;
  environment_id: string;
  initiator: string;
  policy_ref?: string | null;
  /** Refs to the durable states before/after the change (existing refs when
   * the actuator performed no mutation; both empty on a blocked attempt). */
  before_state_refs: string[];
  after_state_refs: string[];
  reason?: string | null;
  /** Epistemic status of the before/after claim over the §12.15 model — the
   * control plane never labels a correlation as causality. */
  claim_type: ControlFindingKind;
  confidence: EvidenceConfidence;
  risk_ref?: string | null;
  simulation_ref?: string | null;
  rollout_ref?: string | null;
  validation_refs: string[];
  approval_refs: string[];
  rollback_ref?: string | null;
  tenant_action_required: boolean;
  evidence_refs: string[];
  contradictory_evidence_refs: string[];
  started_at: string;
  completed_at: string;
}

// ── §12.12 LastKnownGoodView ─────────────────────────────────────────────────

export interface LastKnownGoodView {
  lkg_id: string;
  managed_integration_ref: string;
  tenant_id: string;
  environment_id: string;
  desired_state_ref?: string | null;
  artifact_ref?: string | null;
  runtime_config_ref?: string | null;
  schema_ref?: string | null;
  mapping_refs: string[];
  integration_contract_ref?: string | null;
  policy_ref?: string | null;
  provider_state_ref?: string | null;
  verified_health_ref?: string | null;
  /** A rollout is not LKG until verification passes (§32 step 21 / §12.12). */
  established_at: string;
}

// ── §12.11 RollbackRecordView ────────────────────────────────────────────────

export interface RollbackRecordView {
  rollback_id: string;
  changeset_ref: string;
  tenant_id: string;
  environment_id: string;
  last_known_good_ref?: string | null;
  /** Typed §36 rollback actions the rollback executed (ordered). */
  rollback_actions: string[];
  queue_recovery_policy?: string | null;
  replay_policy?: string | null;
  validation_requirements: string[];
  status: RollbackStatus;
  created_at: string;
  completed_at?: string | null;
}

// ── §12.14 ActionRequiredView ────────────────────────────────────────────────

export interface ActionRequiredView {
  action_id: string;
  tenant_ref: string;
  managed_integration_ref: string;
  environment_id: string;
  /** Open vocabulary — emitted by the executor/actuator that cannot resolve a
   * change (approval, exception, data-loss decision, quarantine, ...). */
  action_type: string;
  reason: string;
  impact?: string | null;
  deadline?: string | null;
  required_actor: string;
  required_action: string;
  continuity_state?: string | null;
  data_loss_expected: boolean;
  resolution_ref?: string | null;
  status: ActionRequiredStatus;
  created_at: string;
}

// ── §16 admission lifecycle ──────────────────────────────────────────────────

export const admissionStages = [
  'discover',
  'understand',
  'classify',
  'reconcile_source_authority',
  'authorize',
  'simulate',
  'approve',
  'compile',
  'activate',
  'observe',
] as const;
export type AdmissionStage = (typeof admissionStages)[number];

/** §16 continuous-lifecycle moves once an integration is admitted and observed:
 * monitor → drift → reconcile → change / review / suspend / revoke. */
export const continuousLifecycleActions = [
  'monitor',
  'drift',
  'reconcile',
  'change',
  'review',
  'suspend',
  'revoke',
] as const;
export type ContinuousLifecycleAction = (typeof continuousLifecycleActions)[number];

// ── §17 / §7.4 discovery manifest data classes ───────────────────────────────

/** Local-first discovery upload behavior — `metadata_only` by default; source
 * code and production values are never uploaded by default (§17). */
export const discoveryDataClasses = [
  'metadata_only',
  'source_code',
  'production_values',
] as const;
export type DiscoveryDataClass = (typeof discoveryDataClasses)[number];

/** §7.4 DiscoveryManifestContract — metadata-first structural discovery output. */
export interface DiscoveryManifestView {
  discovery_id: string;
  source_ref: string;
  discovery_engine_version: string;
  artifact_hash: string;
  frameworks: string[];
  packages: string[];
  routes: string[];
  models: string[];
  schemas: string[];
  events: string[];
  analytics_contracts: string[];
  identity_contracts: string[];
  commerce_contracts: string[];
  payment_contracts: string[];
  consent_contracts: string[];
  agent_contracts: string[];
  network_contracts: string[];
  sensitive_candidates: string[];
  secret_candidates: string[];
  /** `metadata_only` by default — source/production values need explicit opt-in. */
  uploaded_data_class: DiscoveryDataClass;
  tenant_id?: string | null;
  environment_id?: string | null;
  discovered_at: string;
}

// ── §8.1 SemanticMappingCandidateContract ────────────────────────────────────

export const mappingMethodValues = [
  'static',
  'provider_known',
  'heuristic',
  'model_assisted',
  'human',
] as const;
export type MappingMethod = (typeof mappingMethodValues)[number];

/** §8.1 confidence policy: >=0.98 auto-propose only; 0.80–0.979 review
 * recommended; <0.80 unresolved. Sensitive mappings still require
 * authorization regardless of confidence. */
export const mappingReviewStates = ['auto_propose', 'review', 'unresolved'] as const;
export type MappingReviewState = (typeof mappingReviewStates)[number];

export interface SemanticMappingCandidateView {
  candidate_id: string;
  source_ref: string;
  source_path: string;
  canonical_target: string;
  mapping_method: MappingMethod;
  confidence: number;
  rationale?: string | null;
  sensitivity_class?: string | null;
  transform_ref?: string | null;
  /** `auto_propose` / `review` / `unresolved` per §8.1 confidence policy. */
  review_state: MappingReviewState;
  tenant_id?: string | null;
  environment_id?: string | null;
  created_at: string;
}

// ── §9.1 SourceAuthorityRuleContract ─────────────────────────────────────────

/** Authority is domain/property specific — never a blanket statement that one
 * provider is always superior (§9.1). */
export interface SourceAuthorityRuleView {
  rule_id: string;
  domain: string;
  property_path: string;
  source_precedence: string[];
  conflict_strategy?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  policy_ref?: string | null;
  tenant_id?: string | null;
  environment_id?: string | null;
}

// ── §9.2 ObservationEquivalenceKeyContract ───────────────────────────────────

/** Separates transport idempotency from semantic equivalence (§9.2). */
export interface ObservationEquivalenceKeyView {
  key_id: string;
  domain: string;
  candidate_types: string[];
  key_components: string[];
  window?: string | null;
  normalization_rules?: string[] | null;
  semantic_dedupe_policy?: string | null;
  tenant_id?: string | null;
  environment_id?: string | null;
}

// ── §12.7 SimulationResultContract ───────────────────────────────────────────

export const simulationResultValues = ['pass', 'conditional', 'fail'] as const;
export type SimulationResult = (typeof simulationResultValues)[number];

export interface SimulationResultView {
  simulation_id: string;
  changeset_ref?: string | null;
  input_snapshot_refs: string[];
  fixture_refs: string[];
  contract_result?: string | null;
  schema_result?: string | null;
  mapping_result?: string | null;
  privacy_result?: string | null;
  authorization_result?: string | null;
  volume_result?: string | null;
  metric_reconciliation?: string | null;
  identity_continuity?: string | null;
  journey_continuity?: string | null;
  outcome_continuity?: string | null;
  latency_delta?: string | null;
  cost_delta?: string | null;
  unknowns: string[];
  warnings: string[];
  result: SimulationResult;
  tenant_id?: string | null;
  environment_id?: string | null;
  simulation_mode?: string | null;
  ran_at: string;
}

// ── §38 schema/mapping drift automation gates ────────────────────────────────

/** Automatic promotion is allowed only when ALL gates hold (§38); otherwise a
 * review/action is generated. */
export const schemaMappingAutoPromoteGates = [
  'high_confidence',
  'no_new_data_category',
  'no_new_sensitive_field',
  'no_new_processing_purpose',
  'no_new_platform_provider_permission',
  'no_material_semantic_loss',
  'shadow_result_passes',
  'health_within_gates',
] as const;
export type SchemaMappingAutoPromoteGate = (typeof schemaMappingAutoPromoteGates)[number];

// ── §40 universal progressive delivery rings ─────────────────────────────────

/** Canonical §40 sequence for every managed artifact. Exact order is law: a
 * rollout advances one ring at a time, never skipping a stage. */
export const rolloutRingValues = [
  'olympus_internal',
  'test_tenants',
  '1%',
  '5%',
  '20%',
  '50%',
  '100%',
] as const;
export type RolloutRing = (typeof rolloutRingValues)[number];

/** The §40 applicability list — what rings deliver (every managed artifact). */
export const rolloutArtifactKinds = [
  'runtime_config',
  'sdk_compatible_projection',
  'connector_release',
  'mapping_revision',
  'schema_projection',
  'classifier_version',
  'endpoint_migration',
  'operational_policy',
] as const;
export type RolloutArtifactKind = (typeof rolloutArtifactKinds)[number];

// ── §12.9 health snapshot axes + gate evaluation ─────────────────────────────

/** §12.9 HealthContract metric axes a health gate may reference. */
export const healthSnapshotAxes = [
  'availability',
  'freshness',
  'ingestion_success',
  'queue_depth',
  'drop_rate',
  'retry_rate',
  'latency',
  'schema_validity',
  'mapping_coverage',
  'identity_continuity',
  'authorization_validity',
  'consent_validity',
  'metric_reconciliation',
] as const;
export type HealthSnapshotAxis = (typeof healthSnapshotAxes)[number];

/** Comparison operators a §12.9 health gate applies to its axis. */
export const healthGateOperators = ['lt', 'le', 'gt', 'ge'] as const;
export type HealthGateOperator = (typeof healthGateOperators)[number];

/** One §12.9 health gate: axis compared against a numeric threshold. */
export interface HealthGateSpec {
  axis: HealthSnapshotAxis;
  operator: HealthGateOperator;
  threshold: number;
}

/** §12.9 HealthContract snapshot (gate evaluation input). */
export interface HealthSnapshotView {
  health_id: string;
  subject_ref: string;
  window: string;
  availability: string; // §6/CP-12 typed availability
  freshness: number | null;
  ingestion_success: number | null;
  queue_depth: number | null;
  drop_rate: number | null;
  retry_rate: number | null;
  latency: number | null;
  schema_validity: string | null;
  mapping_coverage: string | null;
  identity_continuity: string | null;
  authorization_validity: string | null;
  consent_validity: string | null;
  metric_reconciliation: string | null;
  status: string;
  violations: string[];
  computed_at: string;
}

// ── §30 platform-specific upgrade behavior ───────────────────────────────────

/** §30 normalized managed-behavior tokens (host application releases and
 * native releases are both `host_release`). */
export const upgradeBehaviorValues = [
  'fully_managed',
  'remotely_managed',
  'repository_or_build',
  'compatible_managed_artifact',
  'host_updater_or_build',
  'deployment_model_dependent',
  'host_release',
] as const;
export type UpgradeBehavior = (typeof upgradeBehaviorValues)[number];

/** §30 runtime → managed-behavior table. Aether never claims it can rewrite a
 * customer-controlled binary: non-managed rows resolve to host_release /
 * repository_or_build / deployment_model_dependent. */
export const platformUpgradeBehaviors = {
  aether_hosted_connector: 'fully_managed',
  aether_backend_ingestion: 'fully_managed',
  runtime_config_mapping: 'remotely_managed',
  web_pinned_package: 'repository_or_build',
  web_managed_loader: 'compatible_managed_artifact',
  server_sdk: 'repository_or_build',
  desktop_sdk: 'host_updater_or_build',
  react_native_js_only: 'deployment_model_dependent',
  react_native_native_module: 'host_release',
  ios_native_sdk: 'host_release',
  android_native_sdk: 'host_release',
} as const;
export type PlatformUpgradeBehaviorKey = keyof typeof platformUpgradeBehaviors;

// ── §12.8 RolloutContract ────────────────────────────────────────────────────

/** §12.8 RolloutContract mirror. Rollout records are the §40 delivery facts;
 * execution rides the §34/§35 governed path and a completed rollout is never
 * LKG until §32-step-19 verification passes (§12.12). */
export interface RolloutView {
  rollout_id: string;
  changeset_ref?: string | null;
  artifact_kind: RolloutArtifactKind;
  strategy: string;
  cohorts: string[];
  current_stage: RolloutRing;
  percentage: number;
  health_gates: HealthGateSpec[];
  advance_conditions: string[];
  pause_conditions: string[];
  rollback_conditions: string[];
  tenant_id: string;
  environment_id: string;
  started_at?: string | null;
  last_transition_at?: string | null;
  completed_at?: string | null;
}
