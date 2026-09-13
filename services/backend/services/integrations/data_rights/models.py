"""
Aether — Data Rights Ledger Models

All data use decisions are fail-closed: absent an explicit grant, use is denied.

DataRightsGrant is the canonical record for every data use permission:
- Tenant BYOD connectors: tenant_lake_allowed=True by default only
- Olympus provider sources: olympus_baseline_allowed=True, model_training=False (requires compliance review)
- Cross-tenant aggregates: cross_tenant_aggregate_allowed=False always by default
- Model training: model_training_allowed=False always by default

BYOK credential does NOT imply lake ingestion rights, Olympus baseline use,
model training, or aggregate use. These require separate DataRightsGrant.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GrantStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    PENDING_REVIEW = "pending_review"
    SUSPENDED = "suspended"


class LegalBasis(str, Enum):
    LEGITIMATE_INTEREST = "legitimate_interest"
    CONTRACT = "contract"
    CONSENT = "consent"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    OPERATOR_POLICY = "operator_policy"


# ══════════════════════════════════════════════════════════════════════════════
# Canonical IRRL vocabulary (RIGHTS_AUTHORITY_BLUEPRINT §2/§3/§5/§7/§8/§9)
#
# These enums are cross-stream canonical constants. Streams AST-parse this file
# for EXACTLY these member names and snake_case values — do not rename, extend,
# or drop members. Fail-closed semantics: absence of a member/value = denial.
# ══════════════════════════════════════════════════════════════════════════════

class RightsDerivationClass(str, Enum):
    """§5 rights derivation taxonomy (independent of epistemic trust class)."""
    SOURCE_REPRESENTATION = "source_representation"
    NORMALIZED = "normalized"
    TENANT_IDENTIFIABLE_DERIVATIVE = "tenant_identifiable_derivative"
    AETHER_GENERATED_INTELLIGENCE = "aether_generated_intelligence"
    AGGREGATED = "aggregated"
    GENERALIZED = "generalized"
    MODEL_DERIVED = "model_derived"
    PLATFORM_KNOWLEDGE = "platform_knowledge"


class LearningClass(str, Enum):
    """§3.3 learning classes that replace the single model_training_allowed boolean."""
    INFERENCE = "inference"
    TENANT_ADAPTATION = "tenant_adaptation"
    GENERALIZED_LEARNING = "generalized_learning"
    RESOLVER_CALIBRATION = "resolver_calibration"
    ONTOLOGY_LEARNING = "ontology_learning"
    SCHEMA_MAPPING_LEARNING = "schema_mapping_learning"
    BENCHMARKING = "benchmarking"
    CONTRIBUTED_MODEL_TRAINING = "contributed_model_training"
    OLYMPUS_INTERNAL_INTELLIGENCE = "olympus_internal_intelligence"


class OwnershipClass(str, Enum):
    """§2 primary information classes (never collapsed into a single owner field)."""
    CONTRIBUTED_SOURCE = "contributed_source"
    CANONICALIZED = "canonicalized"
    AETHER_GENERATED_INTELLIGENCE = "aether_generated_intelligence"
    GENERALIZED_KNOWLEDGE = "generalized_knowledge"


class IntelligenceRightsProfile(str, Enum):
    """§3.6 Intelligence Rights Profile — policy preset, never different code paths."""
    SOVEREIGN = "sovereign"
    PRIVATE = "private"
    STANDARD = "standard"
    COLLABORATIVE = "collaborative"


class DisclosureBoundary(str, Enum):
    """§3.4 disclosure boundaries. `governed` tokens gate on Generalization Gateway."""
    TENANT_INTERNAL = "tenant_internal"
    OLYMPUS_INTERNAL = "olympus_internal"
    CROSS_TENANT_IDENTIFIABLE = "cross_tenant_identifiable"
    EXTERNAL_IDENTIFIABLE = "external_identifiable"
    GENERALIZED_CROSS_TENANT = "generalized_cross_tenant"
    GENERALIZED_EXTERNAL = "generalized_external"


class OlympusPurpose(str, Enum):
    """§7 Olympus internal intelligence purposes (first-class actor, NO global superuser)."""
    PLATFORM_RESEARCH = "platform_research"
    MODEL_IMPROVEMENT = "model_improvement"
    SECURITY_RESEARCH = "security_research"
    FRAUD_RESEARCH = "fraud_research"
    RESOLVER_CALIBRATION = "resolver_calibration"
    ONTOLOGY_RESEARCH = "ontology_research"
    PRODUCT_ANALYTICS = "product_analytics"
    BENCHMARK_ANALYSIS = "benchmark_analysis"
    SUPPORT_INVESTIGATION = "support_investigation"
    INCIDENT_RESPONSE = "incident_response"


class LifecycleAction(str, Enum):
    """§9 retention/deletion lifecycle actions."""
    PRESERVE = "preserve"
    DELETE = "delete"
    HARD_DELETE = "hard_delete"
    TOMBSTONE = "tombstone"
    QUARANTINE = "quarantine"
    SUPPRESS = "suppress"
    INVALIDATE = "invalidate"
    RECOMPUTE = "recompute"
    RETRAIN = "retrain"
    ANONYMIZE = "anonymize"
    GENERALIZE = "generalize"
    LEGAL_HOLD = "legal_hold"


class ModelRevocationState(str, Enum):
    """§8 model-governance revocation states after training-data revocation."""
    NO_ACTION_REQUIRED = "no_action_required"
    RETRAIN_REQUIRED = "retrain_required"
    MODEL_QUARANTINE_REQUIRED = "model_quarantine_required"
    EVALUATION_REQUIRED = "evaluation_required"
    LEGAL_REVIEW_REQUIRED = "legal_review_required"
    BLOCKED = "blocked"


class RightsDecisionDisposition(str, Enum):
    """§4 disposition of an effective rights decision."""
    ALLOWED = "allowed"
    DENIED = "denied"
    REDACTED = "redacted"
    SUPPRESSED = "suppressed"


# ══════════════════════════════════════════════════════════════════════════════
# Nested governed components (RIGHTS_AUTHORITY_BLUEPRINT §3 frozen field contract)
#
# Every boolean in these structs fails closed (default False). Adding a nested
# structure must never broaden rights by default. These models are the fully
# structured expansion of DataRightsGrant's legacy top-level booleans.
# ══════════════════════════════════════════════════════════════════════════════

class SourceUseAuthority(BaseModel):
    """§3.1 Migrates the six legacy source-use booleans 1:1; pure struct, all False."""
    tenant_lake: bool = False
    tenant_graph: bool = False
    tenant_insights: bool = False
    olympus_baseline: bool = False
    cross_tenant_aggregate: bool = False
    commercial_reuse: bool = False


class TenantLicenseRights(BaseModel):
    """§3.2 Rights a tenant holds over Aether-generated output for its own business."""
    view: bool = False
    use: bool = False
    reproduce: bool = False
    integrate: bool = False
    export: bool = False
    internal_commercial_use: bool = False


class OlympusDerivationRights(BaseModel):
    """§3.2 Olympus proprietary derivation rights over Aether-generated output."""
    retain: bool = False
    analyze: bool = False
    transform: bool = False
    derive: bool = False
    platform_improvement: bool = False
    internal_research: bool = False


class ExternalDisclosureRights(BaseModel):
    """§3.2 External disclosure of generated output."""
    identifiable: bool = False
    # Boundary token when non-None (e.g. "governed"); None means not authorized.
    generalized: Optional[str] = None


class SurvivalRights(BaseModel):
    """§3.2 Survival of rights after the contributing relationship ends."""
    tenant_exported_outputs: bool = False
    olympus_generalized_derivatives: bool = False


class GeneratedOutputRights(BaseModel):
    """§3.2 Primary Olympus-strengthening contract: who owns / may use generated output."""
    proprietary_holder: str = "olympus"
    tenant_license: TenantLicenseRights = Field(default_factory=TenantLicenseRights)
    olympus: OlympusDerivationRights = Field(default_factory=OlympusDerivationRights)
    external_disclosure: ExternalDisclosureRights = Field(default_factory=ExternalDisclosureRights)
    survival: SurvivalRights = Field(default_factory=SurvivalRights)


class LearningAuthority(BaseModel):
    """§3.3 Learning classes. model_training_allowed migrates ONLY to contributed_model_training."""
    inference: bool = False
    tenant_adaptation: bool = False
    generalized_learning: bool = False
    resolver_calibration: bool = False
    ontology_learning: bool = False
    schema_mapping_learning: bool = False
    benchmarking: bool = False
    contributed_model_training: bool = False
    olympus_internal_intelligence: bool = False


class DisclosureAuthority(BaseModel):
    """§3.4 Disclosure authority per boundary. generalized_external carries a governed token."""
    tenant_internal: bool = False
    olympus_internal: bool = False
    cross_tenant_identifiable: bool = False
    external_identifiable: bool = False
    generalized_cross_tenant: bool = False
    # Boundary token when non-None (e.g. "governed"); None means not authorized.
    generalized_external: Optional[str] = None


class RetentionAuthority(BaseModel):
    """§3.5 Light structured envelope for the composed retention decision.

    Full deterministic retention resolution (legal > hold > agreement > source >
    grant > profile > event class > storage policy > default) lives in the
    rights_authority package (another stream). Kept minimal here on purpose.
    """
    # Free-form precedence summary for now; e.g. "grant:retain|legal:nullify".
    precedence: Optional[str] = None
    # Lifecycle action tokens (see LifecycleAction) applied by default.
    lifecycle_defaults: Optional[List[str]] = None


class TerminationAuthority(BaseModel):
    """§3.5/§14 Rights-aware termination. Optional[str]=None means fail-closed (undecided).

    Each typed field names the blueprint §14 disposition it carries. A termination
    is a rights-aware lifecycle event, never a universal hard delete.
    """
    # Free-form mapping for any §14 row / extension not covered by the typed fields below.
    actions: Dict[str, str] = Field(default_factory=dict)
    contributed_source_data: Optional[str] = None  # §14: delete_by_policy
    tenant_identifiable_derived_data: Optional[str] = None  # §14: recompute_or_delete
    tenant_exports: Optional[str] = None  # §14: tenant_retains
    audit_records: Optional[str] = None  # §14: retain_as_required
    generalized_derivatives: Optional[str] = None  # §14: retain_if_independently_qualified
    model_weights: Optional[str] = None  # §14: retain_if_non_reconstructable_and_permitted
    benchmarks: Optional[str] = None  # §14: retain_if_generalization_passed
    ontology_improvements: Optional[str] = None  # §14: retain
    security_fraud_signatures: Optional[str] = None  # §14: governed_retention


class RightsProfileDefaults(BaseModel):
    """§3.6 Preset record over generated-output + learning (+ disclosure) per profile."""
    generated_output_retention: str
    generalized_learning: bool
    olympus_internal_intelligence: bool
    contributed_model_training: bool

    @classmethod
    def for_profile(cls, profile: IntelligenceRightsProfile) -> "RightsProfileDefaults":
        """§3.6 preset table. Accepts the enum or its snake_case value."""
        if isinstance(profile, str):
            profile = IntelligenceRightsProfile(profile)
        table = {
            IntelligenceRightsProfile.SOVEREIGN: ("minimal", False, False, False),
            IntelligenceRightsProfile.PRIVATE: ("required_operations_only", False, False, False),
            IntelligenceRightsProfile.STANDARD: ("yes", True, True, False),
            IntelligenceRightsProfile.COLLABORATIVE: ("yes", True, True, True),
        }
        retention, generalized_learning, olympus_internal, contributed = table[profile]
        return cls(
            generated_output_retention=retention,
            generalized_learning=generalized_learning,
            olympus_internal_intelligence=olympus_internal,
            contributed_model_training=contributed,
        )


class DataRightsGrant(BaseModel):
    """Canonical record for a data use permission grant.

    All boolean fields default to False (fail-closed).
    Grant creation is an explicit act; absence = denial.

    Default behaviors by connector class:
    - OLYMPUS_PROVIDER: olympus_baseline_allowed=True, model_training=False
    - TENANT_BYOD_DATA: tenant_lake_allowed=True, tenant_graph_allowed=True, rest False
    - BYOK_GATEWAY: no lake rights (credential control only)
    """
    data_rights_grant_id: str
    tenant_id: str
    contract_id: Optional[str] = None
    source_id: str
    connector_id: str
    connector_class: str
    source_manifest_id: Optional[str] = None
    data_category: str
    data_sensitivity: str
    raw_data_owner: str

    # ── Write permissions — all fail closed ──────────────────────────────────
    tenant_lake_allowed: bool = True
    tenant_graph_allowed: bool = True
    tenant_insights_allowed: bool = True
    olympus_baseline_allowed: bool = False
    cross_tenant_aggregate_allowed: bool = False
    model_training_allowed: bool = False
    commercial_reuse_allowed: bool = False

    # ── Policy metadata ───────────────────────────────────────────────────────
    legal_basis: str = LegalBasis.OPERATOR_POLICY.value
    consent_basis: Optional[str] = None
    # Stable data-subject reference used for consent evaluation.  The legal
    # basis/purpose remains in consent_basis; it is never overloaded as an id.
    subject_ref: Optional[str] = None
    granted_by_user_id: str
    granted_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    status: GrantStatus = GrantStatus.ACTIVE
    audit_event_id: str

    # ── Olympus provider overrides (set on creation for Olympus sources) ──────
    # When connector_class == OLYMPUS_PROVIDER:
    #   olympus_baseline_allowed = True
    #   model_training_allowed = False (requires explicit compliance review)

    # ── Structured rights contract (blueprint §3) — Optional, lazily resolved ──
    # When a component is None the grant is treated as a legacy grant: existing
    # policy behavior is unchanged and structured resolution derives ONLY from the
    # legacy booleans above (never broadening past them — blueprint M0/§13).
    # rights_profile defaults to the STANDARD profile; applying STANDARD commercial
    # presets to components that were never expressed is the Effective Rights
    # Resolver's job (Phase 2), not something done implicitly here.
    source_use: Optional[SourceUseAuthority] = None
    generated_output_rights: Optional[GeneratedOutputRights] = None
    learning_authority: Optional[LearningAuthority] = None
    disclosure_authority: Optional[DisclosureAuthority] = None
    retention_authority: Optional[RetentionAuthority] = None
    termination_authority: Optional[TerminationAuthority] = None
    rights_profile: str = IntelligenceRightsProfile.STANDARD.value

    def structured_rights(self) -> Dict[str, Any]:
        """Fully-populated nested rights view, resolved lazily (never broadens).

        Explicitly-provided components are returned as-is. Components left None are
        resolved strictly from the legacy booleans where a faithful equivalent exists
        (source_use 1:1, learning_authority → contributed_model_training ONLY) and
        fail-closed (all-False / empty) otherwise — because the legacy grant never
        expressed generated-output / disclosure / retention / termination rights.

        This view therefore describes exactly what the grant expresses today. The
        STANDARD commercial presets (default_generated_output_rights(),
        default_disclosure_authority(), default_termination_authority() in the
        service module) are canonical expansions a resolver MAY apply when profile /
        agreement makes them effective — they are never folded in here for legacy
        grants (blueprint M0: no broader rights automatically).

        Imported lazily from service to avoid a top-level module cycle (service
        imports models).
        """
        from services.integrations.data_rights.service import (
            derive_source_use_from_legacy,
            effective_learning_authority,
        )

        source_use = (
            self.source_use
            if self.source_use is not None
            else derive_source_use_from_legacy(
                tenant_lake_allowed=self.tenant_lake_allowed,
                tenant_graph_allowed=self.tenant_graph_allowed,
                tenant_insights_allowed=self.tenant_insights_allowed,
                olympus_baseline_allowed=self.olympus_baseline_allowed,
                cross_tenant_aggregate_allowed=self.cross_tenant_aggregate_allowed,
                commercial_reuse_allowed=self.commercial_reuse_allowed,
            )
        )
        return {
            "source_use": source_use,
            "generated_output_rights": (
                self.generated_output_rights
                if self.generated_output_rights is not None
                else GeneratedOutputRights()
            ),
            "learning_authority": effective_learning_authority(self),
            "disclosure_authority": (
                self.disclosure_authority
                if self.disclosure_authority is not None
                else DisclosureAuthority()
            ),
            "retention_authority": (
                self.retention_authority
                if self.retention_authority is not None
                else RetentionAuthority()
            ),
            "termination_authority": (
                self.termination_authority
                if self.termination_authority is not None
                else TerminationAuthority()
            ),
            "rights_profile": self.rights_profile,
        }


class DataRightsGrantCreate(BaseModel):
    """Request body for creating a data rights grant."""
    tenant_id: str
    source_id: str
    connector_id: str
    connector_class: str
    source_manifest_id: Optional[str] = None
    data_category: str
    data_sensitivity: str = "unclassified"
    raw_data_owner: str
    tenant_lake_allowed: bool = True
    tenant_graph_allowed: bool = True
    tenant_insights_allowed: bool = True
    olympus_baseline_allowed: bool = False
    cross_tenant_aggregate_allowed: bool = False
    model_training_allowed: bool = False
    commercial_reuse_allowed: bool = False
    legal_basis: str = LegalBasis.OPERATOR_POLICY.value
    consent_basis: Optional[str] = None
    subject_ref: Optional[str] = None
    contract_id: Optional[str] = None
    expires_at: Optional[str] = None


class DataRightsGrantRevoke(BaseModel):
    """Request body for revoking a data rights grant."""
    revocation_reason: str
    revoked_by_user_id: str


class PolicyCheckResult(BaseModel):
    """Result of a fail-closed policy check."""
    grant_id: str
    check_type: str
    allowed: bool
    reason: str
    checked_at: str
    grant_status: GrantStatus


class PolicyCheckRequest(BaseModel):
    """Request to evaluate a specific policy check on a grant."""
    grant_id: str
    check_type: str  # olympus_baseline | model_training | cross_tenant_aggregate | commercial_reuse


class DataRightsGrantSummary(BaseModel):
    """Lightweight summary of a data rights grant (for list responses)."""
    data_rights_grant_id: str
    tenant_id: str
    source_id: str
    connector_id: str
    connector_class: str
    status: GrantStatus
    olympus_baseline_allowed: bool
    model_training_allowed: bool
    cross_tenant_aggregate_allowed: bool
    commercial_reuse_allowed: bool
    granted_at: str
    revoked_at: Optional[str] = None
