// =============================================================================
// Aether SDK — DataRightsGrant structured authorities (rights_irrl) — canonical TS twin
// HAND-MAINTAINED contract — NOT generated (do not run generate_platform_contracts.py
// against this file). Python twin:
//   Backend Architecture/aether-backend/services/integrations/data_rights/models.py
// Parity is enforced by tests/unit/test_data_rights_contract_parity.py.
//
// This module is the TypeScript twin of the Python DataRightsGrant structured
// authorities frozen in docs/source-of-truth/RIGHTS_AUTHORITY_BLUEPRINT.md
// §3 (canonical contract model) and §5 (rights derivation taxonomy). Every
// vocabulary below is an `as const` array with a derived snake_case literal-
// union type (`typeof X[number]`); every interface mirrors a Python pydantic
// nested model with the same snake_case field set. The vocabulary member sets
// and field sets are the frozen contract — never broaden one here; widen the
// blueprint first, then update the Python twin and this file together so the
// parity gate stays green.
//
// Rights doctrine (blueprint §1): contribution rights, ownership rights, use
// rights, retention rights, derivation rights, learning rights, disclosure
// rights, portability rights, and deletion rights are SEPARATE authorities.
// These structured authorities never collapse them into a single `owner` field
// with all downstream permissions inferred, and absence of an explicit
// authority stays fail-closed (deny).
// =============================================================================

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: rights derivation classes (blueprint §5)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Rights derivation classes (blueprint §5). The rights-derivation dimension is
 * independent of epistemic trust class and semantic level: an artifact may be
 * trustClass INFERRED, semanticLevel C, and rightsDerivation
 * AETHER_GENERATED_INTELLIGENCE — the dimensions never merge.
 */
export const rightsDerivationClasses = [
  'source_representation',
  'normalized',
  'tenant_identifiable_derivative',
  'aether_generated_intelligence',
  'aggregated',
  'generalized',
  'model_derived',
  'platform_knowledge',
] as const;

/** Canonical rights derivation class (blueprint §5). */
export type RightsDerivationClass = (typeof rightsDerivationClasses)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: learning classes (blueprint §3.3)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Learning classes (blueprint §3.3) — replaces the single legacy
 * `model_training_allowed` boolean with granular per-class authorities so a
 * tenant can allow generalized learning while refusing raw-data model training.
 * `contributed_model_training` is the direct successor of the legacy
 * `model_training_allowed` flag (must NOT broaden silently on migration).
 */
export const learningClasses = [
  'inference',
  'tenant_adaptation',
  'generalized_learning',
  'resolver_calibration',
  'ontology_learning',
  'schema_mapping_learning',
  'benchmarking',
  'contributed_model_training',
  'olympus_internal_intelligence',
] as const;

/** Canonical learning class (blueprint §3.3). */
export type LearningClass = (typeof learningClasses)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: ownership classes (blueprint §2 four primary information classes)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Ownership classes (blueprint §2) — the four primary information classes of
 * the final rights taxonomy: contributed information, canonicalized
 * information, Aether-generated intelligence, and generalized Aether knowledge.
 * Ownership/authority is never encoded as one `owner` field.
 */
export const ownershipClasses = [
  'contributed_source',
  'canonicalized',
  'aether_generated_intelligence',
  'generalized_knowledge',
] as const;

/** Canonical ownership class (blueprint §2). */
export type OwnershipClass = (typeof ownershipClasses)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: intelligence rights profiles (blueprint §3.6)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Intelligence Rights Profiles (blueprint §3.6) — policy presets, never
 * different code paths: sovereign, private, standard, collaborative.
 */
export const intelligenceRightsProfiles = [
  'sovereign',
  'private',
  'standard',
  'collaborative',
] as const;

/** Canonical Intelligence Rights Profile (blueprint §3.6). */
export type IntelligenceRightsProfile = (typeof intelligenceRightsProfiles)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: disclosure boundaries (blueprint §3.4)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Disclosure boundaries (blueprint §3.4). The `governed` sentinel used by
 * `generalized`/`generalized_external` fields is intentionally NOT a member of
 * this vocabulary — it means "resolve through the governed generalization
 * path" rather than naming a concrete destination boundary.
 */
export const disclosureBoundaries = [
  'tenant_internal',
  'olympus_internal',
  'cross_tenant_identifiable',
  'external_identifiable',
  'generalized_cross_tenant',
  'generalized_external',
] as const;

/** Canonical disclosure boundary (blueprint §3.4). */
export type DisclosureBoundary = (typeof disclosureBoundaries)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: Olympus internal purposes (blueprint §7)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Olympus internal intelligence purposes (blueprint §7). Olympus-internal
 * access is purpose-bound — there is NO global superuser.
 */
export const olympusPurposes = [
  'platform_research',
  'model_improvement',
  'security_research',
  'fraud_research',
  'resolver_calibration',
  'ontology_research',
  'product_analytics',
  'benchmark_analysis',
  'support_investigation',
  'incident_response',
] as const;

/** Canonical Olympus internal purpose (blueprint §7). */
export type OlympusPurpose = (typeof olympusPurposes)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: lifecycle actions (blueprint §9)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Retention/lifecycle actions (blueprint §9). Deletion is dependency-aware and
 * rights-aware — never a universal hard delete; each dependent component of a
 * governed artifact receives its appropriate action.
 */
export const lifecycleActions = [
  'preserve',
  'delete',
  'hard_delete',
  'tombstone',
  'quarantine',
  'suppress',
  'invalidate',
  'recompute',
  'retrain',
  'anonymize',
  'generalize',
  'legal_hold',
] as const;

/** Canonical lifecycle action (blueprint §9). */
export type LifecycleAction = (typeof lifecycleActions)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: model revocation states (blueprint §8)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Model revocation states (blueprint §8). A model is never claimed "deleted"
 * merely because training rows disappeared; revocation maps to the concrete
 * remediation the model actually requires.
 */
export const modelRevocationStates = [
  'no_action_required',
  'retrain_required',
  'model_quarantine_required',
  'evaluation_required',
  'legal_review_required',
  'blocked',
] as const;

/** Canonical model revocation state (blueprint §8). */
export type ModelRevocationState = (typeof modelRevocationStates)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Vocabulary: rights decision dispositions (blueprint §4)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * RightsDecision dispositions (blueprint §4). A denial is a typed
 * suppression/redaction, never a silent drop.
 */
export const rightsDecisionDispositions = [
  'allowed',
  'denied',
  'redacted',
  'suppressed',
] as const;

/** Canonical RightsDecision disposition (blueprint §4). */
export type RightsDecisionDisposition = (typeof rightsDecisionDispositions)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Nested governed component interfaces (blueprint §3)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SourceUseAuthority (blueprint §3.1) — use authorities over contributed
 * source material. Migrates the legacy top-level write-permission booleans
 * with no semantic change on migration.
 */
export interface SourceUseAuthority {
  /** Tenant may read/store contributed material in its own lake. */
  tenant_lake: boolean;
  /** Tenant may load contributed material into its tenant graph. */
  tenant_graph: boolean;
  /** Tenant may use contributed material to derive its tenant insights. */
  tenant_insights: boolean;
  /** Olympus may include the source in its baseline (platform) knowledge. */
  olympus_baseline: boolean;
  /** The source may be folded into cross-tenant aggregates. */
  cross_tenant_aggregate: boolean;
  /** The source may be commercially reused. */
  commercial_reuse: boolean;
}

/**
 * TenantLicenseRights (blueprint §3.2) — the tenant's governed usage rights
 * over Aether-generated intelligence output.
 */
export interface TenantLicenseRights {
  /** Tenant may view the generated output. */
  view: boolean;
  /** Tenant may use the generated output for its business. */
  use: boolean;
  /** Tenant may reproduce the generated output. */
  reproduce: boolean;
  /** Tenant may integrate the generated output into its systems. */
  integrate: boolean;
  /** Tenant may export the generated output. */
  export: boolean;
  /** Tenant may use the generated output for internal commercial purposes. */
  internal_commercial_use: boolean;
}

/**
 * OlympusDerivationRights (blueprint §3.2) — Olympus's governed proprietary /
 * derivation rights over Aether-generated intelligence.
 */
export interface OlympusDerivationRights {
  /** Olympus may retain the generated output. */
  retain: boolean;
  /** Olympus may analyze the generated output. */
  analyze: boolean;
  /** Olympus may transform the generated output. */
  transform: boolean;
  /** Olympus may derive further intelligence from the generated output. */
  derive: boolean;
  /** Olympus may use the generated output for platform improvement. */
  platform_improvement: boolean;
  /** Olympus may use the generated output for internal research. */
  internal_research: boolean;
}

/**
 * ExternalDisclosureRights (blueprint §3.2) — how far Aether-generated
 * intelligence may be disclosed outside the tenant.
 */
export interface ExternalDisclosureRights {
  /** Identifiable disclosure to an external party is permitted. */
  identifiable: boolean;
  /**
   * Generalized disclosure boundary. A concrete `DisclosureBoundary`, or the
   * `governed` sentinel meaning "resolve through the governed generalization
   * path" (blueprint §6 Generalization Gateway).
   */
  generalized?: DisclosureBoundary | 'governed';
}

/**
 * SurvivalRights (blueprint §3.2) — which artifacts survive tenant
 * termination/revocation.
 */
export interface SurvivalRights {
  /** Outputs the tenant already exported survive for the tenant. */
  tenant_exported_outputs: boolean;
  /** Olympus's generalized derivatives survive independently. */
  olympus_generalized_derivatives: boolean;
}

/**
 * GeneratedOutputRights (blueprint §3.2) — the primary Olympus-strengthening
 * contract over Aether-generated intelligence: proprietary holder, tenant
 * license, Olympus derivation rights, external-disclosure rights, and survival
 * rights are composed (never collapsed into a single owner field).
 */
export interface GeneratedOutputRights {
  /** Proprietary holder of the generated computational artifact. Frozen: `olympus`. */
  proprietary_holder: 'olympus';
  /** Tenant's governed usage rights over the generated output. */
  tenant_license: TenantLicenseRights;
  /** Olympus's governed proprietary / derivation rights. */
  olympus: OlympusDerivationRights;
  /** External-disclosure limits on the generated output. */
  external_disclosure: ExternalDisclosureRights;
  /** Survival of generated output after termination/revocation. */
  survival: SurvivalRights;
}

/**
 * LearningAuthority (blueprint §3.3) — per-class learning authorities,
 * replacing the single legacy `model_training_allowed` boolean.
 */
export interface LearningAuthority {
  /** Inference over the tenant's material is permitted. */
  inference: boolean;
  /** Tenant-local adaptation is permitted. */
  tenant_adaptation: boolean;
  /** Generalized (non-identifying) learning is permitted. */
  generalized_learning: boolean;
  /** Resolver calibration learning is permitted. */
  resolver_calibration: boolean;
  /** Ontology learning is permitted. */
  ontology_learning: boolean;
  /** Schema-mapping learning is permitted. */
  schema_mapping_learning: boolean;
  /** Benchmarking use is permitted. */
  benchmarking: boolean;
  /** Contributed raw-data model training is permitted (legacy `model_training_allowed` successor). */
  contributed_model_training: boolean;
  /** Olympus internal-intelligence use is permitted. */
  olympus_internal_intelligence: boolean;
}

/**
 * DisclosureAuthority (blueprint §3.4) — disclosure boundaries for the tenant's
 * material and its derivatives.
 */
export interface DisclosureAuthority {
  /** Disclosure within the tenant is permitted. */
  tenant_internal: boolean;
  /** Disclosure to Olympus-internal operators is permitted. */
  olympus_internal: boolean;
  /** Identifiable cross-tenant disclosure is permitted. */
  cross_tenant_identifiable: boolean;
  /** Identifiable external disclosure is permitted. */
  external_identifiable: boolean;
  /** Generalized cross-tenant disclosure is permitted. */
  generalized_cross_tenant: boolean;
  /**
   * Generalized external disclosure boundary. A concrete `DisclosureBoundary`,
   * or the `governed` sentinel (blueprint §6).
   */
  generalized_external?: DisclosureBoundary | 'governed';
}

/** RetentionAuthority (blueprint §3.5) — explicit lifecycle precedence and
 * defaults; omission is an undecided, fail-closed authority. */
export interface RetentionAuthority {
  precedence?: string;
  lifecycle_defaults?: readonly string[];
}

/**
 * TerminationAuthority (blueprint §3.5) — the rights-aware lifecycle outcomes
 * on tenant termination. Termination is NOT a universal hard delete; every
 * governed artifact class resolves to its own governed retention outcome.
 */
export interface TerminationAuthority {
  /**
   * Free-form §14 mapping for any row / extension not covered by the typed
   * fields below. Mirrors the Python twin `actions: Dict[str, str]`
   * (models.py, TerminationAuthority) — always present there (default {}),
   * optional here so consumers may omit it.
   */
  actions?: Record<string, string>;
  /** Outcome for contributed source data (e.g. delete_by_policy). */
  contributed_source_data?: string;
  /** Outcome for tenant-identifiable derived data (e.g. recompute_or_delete). */
  tenant_identifiable_derived_data?: string;
  /** Outcome for tenant exports (e.g. tenant_retains). */
  tenant_exports?: string;
  /** Outcome for audit records (e.g. retain_as_required). */
  audit_records?: string;
  /** Outcome for generalized derivatives (e.g. retain_if_independently_qualified). */
  generalized_derivatives?: string;
  /** Outcome for model weights (e.g. retain_if_non_reconstructable_and_permitted). */
  model_weights?: string;
  /** Outcome for benchmarks (e.g. retain_if_generalization_passed). */
  benchmarks?: string;
  /** Outcome for ontology improvements (e.g. retain). */
  ontology_improvements?: string;
  /** Outcome for security/fraud signatures (e.g. governed_retention). */
  security_fraud_signatures?: string;
}

/**
 * RightsProfileDefaults (blueprint §3.6) — the policy-preset knobs a profile
 * sets. Presets are policy, never different code paths.
 */
export interface RightsProfileDefaults {
  /** Olympus generated-output retention posture (e.g. 'yes' | 'minimal'). */
  generated_output_retention: string;
  /** Generalized (non-identifying) learning is permitted. */
  generalized_learning: boolean;
  /** Olympus internal-intelligence use is permitted. */
  olympus_internal_intelligence: boolean;
  /** Contributed raw-data model training is permitted. */
  contributed_model_training: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Default factories (blueprint §3.2 / §3.6 tables)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Standard-profile GeneratedOutputRights default (blueprint §3.2 YAML). Tenant
 * receives broad governed use; Olympus retains governed proprietary /
 * derivation rights; identifiable external disclosure is denied; generalized
 * disclosure resolves through the governed path.
 */
export const standardGeneratedOutputRights: GeneratedOutputRights = {
  proprietary_holder: 'olympus',
  tenant_license: {
    view: true,
    use: true,
    reproduce: true,
    integrate: true,
    export: true,
    internal_commercial_use: true,
  },
  olympus: {
    retain: true,
    analyze: true,
    transform: true,
    derive: true,
    platform_improvement: true,
    internal_research: true,
  },
  external_disclosure: {
    identifiable: false,
    generalized: 'governed',
  },
  survival: {
    tenant_exported_outputs: true,
    olympus_generalized_derivatives: true,
  },
};

/**
 * Standard-profile DisclosureAuthority default (blueprint §3.4 YAML):
 * tenant-internal and Olympus-internal disclosure allowed, generalized
 * cross-tenant allowed, identifiable cross-tenant / external disclosure denied,
 * generalized external disclosure governed.
 */
export const standardDisclosureAuthority: DisclosureAuthority = {
  tenant_internal: true,
  olympus_internal: true,
  cross_tenant_identifiable: false,
  external_identifiable: false,
  generalized_cross_tenant: true,
  generalized_external: 'governed',
};

/** Sovereign profile defaults (blueprint §3.6): minimal retention, no learning, no model training. */
export const sovereignRightsProfileDefaults: RightsProfileDefaults = {
  generated_output_retention: 'minimal',
  generalized_learning: false,
  olympus_internal_intelligence: false,
  contributed_model_training: false,
};

/** Standard profile defaults (blueprint §3.6): yes retention, bounded Olympus internal intelligence, no contributed training. */
export const standardRightsProfileDefaults: RightsProfileDefaults = {
  generated_output_retention: 'yes',
  generalized_learning: true,
  olympus_internal_intelligence: true,
  contributed_model_training: false,
};

/** Collaborative profile defaults (blueprint §3.6): yes retention, yes learning, explicitly governed contributed training. */
export const collaborativeRightsProfileDefaults: RightsProfileDefaults = {
  generated_output_retention: 'yes',
  generalized_learning: true,
  olympus_internal_intelligence: true,
  contributed_model_training: true,
};

// ─────────────────────────────────────────────────────────────────────────────
// DataRightsGrantStructured (blueprint §3) — legacy grant shape + nested authorities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The upgraded DataRightsGrant (blueprint §3): the legacy grant shape (scalar
 * identity / fail-closed write-permission booleans / policy metadata, matching
 * the Python `DataRightsGrant` in
 * `services/integrations/data_rights/models.py`) PLUS the optional nested
 * structured authorities. Legacy booleans remain authoritative during the
 * blueprint §16 M0–M3 migration (structured authorities are shadow-derived and
 * optional); when a nested authority is absent its legacy boolean field(s)
 * govern, and unknown/new fields fail closed.
 */
export interface DataRightsGrantStructured {
  // ── Identity / ownership ─────────────────────────────────────────────────
  data_rights_grant_id: string;
  tenant_id: string;
  contract_id?: string;
  source_id: string;
  connector_id: string;
  connector_class: string;
  source_manifest_id?: string;
  data_category: string;
  data_sensitivity: string;
  raw_data_owner: string;

  // ── Legacy write-permission booleans (fail closed; authoritative M0–M3) ──
  tenant_lake_allowed: boolean;
  tenant_graph_allowed: boolean;
  tenant_insights_allowed: boolean;
  olympus_baseline_allowed: boolean;
  cross_tenant_aggregate_allowed: boolean;
  model_training_allowed: boolean;
  commercial_reuse_allowed: boolean;

  // ── Policy metadata ───────────────────────────────────────────────────────
  legal_basis: string;
  consent_basis?: string;
  subject_ref?: string;
  granted_by_user_id: string;
  granted_at: string;
  expires_at?: string;
  revoked_at?: string;
  revocation_reason?: string;
  status: 'active' | 'revoked' | 'expired' | 'pending_review' | 'suspended';
  audit_event_id: string;

  // ── Nested structured authorities (blueprint §3; optional during migration) ──
  /** Structured source-use authority (§3.1). */
  source_use?: SourceUseAuthority;
  /** Structured generated-output rights (§3.2). */
  generated_output_rights?: GeneratedOutputRights;
  /** Structured per-class learning authority (§3.3). */
  learning_authority?: LearningAuthority;
  /** Structured disclosure authority (§3.4). */
  disclosure_authority?: DisclosureAuthority;
  /** Structured termination authority (§3.5). */
  termination_authority?: TerminationAuthority;
  /** Structured retention authority (§3.5). */
  retention_authority?: RetentionAuthority;
  /** Intelligence Rights Profile preset this grant conforms to (§3.6). */
  rights_profile?: IntelligenceRightsProfile;
}

// ─────────────────────────────────────────────────────────────────────────────
// Structured surface enumeration
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Every structured nested-field name added to the legacy grant plus the name of
 * every `as const` vocabulary array in this module. Lets parity tests and
 * consumers iterate the whole DataRightsGrantStructured surface without
 * hard-coding each identifier.
 */
export const dataRightsStructuredFieldKeys = [
  // nested structured grant fields (blueprint §3)
  'source_use',
  'generated_output_rights',
  'learning_authority',
  'disclosure_authority',
  'termination_authority',
  'retention_authority',
  'rights_profile',
  // vocabulary `as const` array names
  'rightsDerivationClasses',
  'learningClasses',
  'ownershipClasses',
  'intelligenceRightsProfiles',
  'disclosureBoundaries',
  'olympusPurposes',
  'lifecycleActions',
  'modelRevocationStates',
  'rightsDecisionDispositions',
] as const;

/** Union over `dataRightsStructuredFieldKeys`. */
export type DataRightsStructuredFieldKey = (typeof dataRightsStructuredFieldKeys)[number];
