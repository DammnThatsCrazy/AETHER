"""
Aether Privacy — Data Classification System

Formal repo-wide classification taxonomy with enforcement rules.
Every field, object, edge, feature, and export surface maps to a tier.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFICATION TIERS
# ═══════════════════════════════════════════════════════════════════════════


class DataClassification(str, Enum):
    """7-tier data classification taxonomy."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SENSITIVE_PII = "sensitive_pii"
    FINANCIAL = "financial"
    REGULATED = "regulated"
    HIGHLY_SENSITIVE = "highly_sensitive"


class LawfulBasis(str, Enum):
    """GDPR Article 6 lawful bases for processing."""
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTEREST = "vital_interest"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTEREST = "legitimate_interest"


class RetentionClass(str, Enum):
    """How long data should be retained."""
    EPHEMERAL = "ephemeral"          # Delete after use (session data)
    SHORT = "short"                  # 30 days
    STANDARD = "standard"            # 1 year
    EXTENDED = "extended"            # 3 years
    COMPLIANCE = "compliance"        # 7 years (regulatory)
    PERMANENT = "permanent"          # Never delete (audit logs)
    LEGAL_HOLD = "legal_hold"        # Retained until hold released


class DeletionBehavior(str, Enum):
    """What happens when deletion is requested."""
    HARD_DELETE = "hard_delete"
    PSEUDONYMIZE = "pseudonymize"
    TOMBSTONE = "tombstone"
    HASH_IRREVERSIBLE = "hash_irreversible"
    KEY_DESTROY = "key_destroy"
    EDGE_SEVER = "edge_sever"
    RETAIN_AGGREGATE = "retain_aggregate"
    IMMUTABLE = "immutable"          # Cannot be deleted (audit/compliance)


class AccessLevel(str, Enum):
    """Field-level access control."""
    FULL = "full"
    MASKED = "masked"
    METADATA_ONLY = "metadata_only"
    DENIED = "denied"
    PURPOSE_BOUND = "purpose_bound"
    INTERNAL_ONLY = "internal_only"


class TrainingEligibility(str, Enum):
    """Whether data can be used for ML training."""
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    CONSENT_REQUIRED = "consent_required"
    ANONYMIZED_ONLY = "anonymized_only"
    AGGREGATE_ONLY = "aggregate_only"


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFICATION RULES PER TIER
# ═══════════════════════════════════════════════════════════════════════════


class ClassificationRules(BaseModel):
    """Rules enforced for a data classification tier."""
    tier: DataClassification
    encryption_at_rest: bool = False
    encryption_in_transit: bool = True
    field_level_encryption: bool = False
    requires_consent: bool = False
    default_lawful_basis: LawfulBasis = LawfulBasis.LEGITIMATE_INTEREST
    retention: RetentionClass = RetentionClass.STANDARD
    deletion_behavior: DeletionBehavior = DeletionBehavior.HARD_DELETE
    exportable: bool = True
    export_requires_approval: bool = False
    training_eligibility: TrainingEligibility = TrainingEligibility.ELIGIBLE
    externally_visible: bool = True
    log_redaction_required: bool = False
    min_access_role: str = Field(default="viewer", description="Minimum role: viewer/editor/admin/compliance/auditor")
    graph_traversal_allowed: bool = True
    cross_domain_linking_allowed: bool = True


# Default rules per tier
CLASSIFICATION_RULES: dict[DataClassification, ClassificationRules] = {
    DataClassification.PUBLIC: ClassificationRules(
        tier=DataClassification.PUBLIC,
        encryption_at_rest=False,
        retention=RetentionClass.PERMANENT,
        deletion_behavior=DeletionBehavior.HARD_DELETE,
        training_eligibility=TrainingEligibility.ELIGIBLE,
    ),
    DataClassification.INTERNAL: ClassificationRules(
        tier=DataClassification.INTERNAL,
        encryption_at_rest=True,
        retention=RetentionClass.STANDARD,
        deletion_behavior=DeletionBehavior.HARD_DELETE,
        training_eligibility=TrainingEligibility.ELIGIBLE,
        externally_visible=False,
    ),
    DataClassification.CONFIDENTIAL: ClassificationRules(
        tier=DataClassification.CONFIDENTIAL,
        encryption_at_rest=True,
        retention=RetentionClass.STANDARD,
        deletion_behavior=DeletionBehavior.HARD_DELETE,
        training_eligibility=TrainingEligibility.ELIGIBLE,
        externally_visible=False,
        min_access_role="editor",
    ),
    DataClassification.SENSITIVE_PII: ClassificationRules(
        tier=DataClassification.SENSITIVE_PII,
        encryption_at_rest=True,
        field_level_encryption=True,
        requires_consent=True,
        default_lawful_basis=LawfulBasis.CONSENT,
        retention=RetentionClass.STANDARD,
        deletion_behavior=DeletionBehavior.PSEUDONYMIZE,
        exportable=True,
        export_requires_approval=True,
        training_eligibility=TrainingEligibility.CONSENT_REQUIRED,
        externally_visible=False,
        log_redaction_required=True,
        min_access_role="editor",
    ),
    DataClassification.FINANCIAL: ClassificationRules(
        tier=DataClassification.FINANCIAL,
        encryption_at_rest=True,
        field_level_encryption=True,
        requires_consent=False,
        default_lawful_basis=LawfulBasis.CONTRACT,
        retention=RetentionClass.COMPLIANCE,
        deletion_behavior=DeletionBehavior.PSEUDONYMIZE,
        exportable=True,
        export_requires_approval=True,
        training_eligibility=TrainingEligibility.ANONYMIZED_ONLY,
        externally_visible=False,
        log_redaction_required=True,
        min_access_role="editor",
    ),
    DataClassification.REGULATED: ClassificationRules(
        tier=DataClassification.REGULATED,
        encryption_at_rest=True,
        field_level_encryption=True,
        requires_consent=False,
        default_lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
        retention=RetentionClass.COMPLIANCE,
        deletion_behavior=DeletionBehavior.TOMBSTONE,
        exportable=False,
        export_requires_approval=True,
        training_eligibility=TrainingEligibility.EXCLUDED,
        externally_visible=False,
        log_redaction_required=True,
        min_access_role="compliance",
        graph_traversal_allowed=False,
        cross_domain_linking_allowed=False,
    ),
    DataClassification.HIGHLY_SENSITIVE: ClassificationRules(
        tier=DataClassification.HIGHLY_SENSITIVE,
        encryption_at_rest=True,
        field_level_encryption=True,
        requires_consent=False,
        default_lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
        retention=RetentionClass.COMPLIANCE,
        deletion_behavior=DeletionBehavior.KEY_DESTROY,
        exportable=False,
        export_requires_approval=True,
        training_eligibility=TrainingEligibility.EXCLUDED,
        externally_visible=False,
        log_redaction_required=True,
        min_access_role="admin",
        graph_traversal_allowed=False,
        cross_domain_linking_allowed=False,
    ),
}


def get_rules(tier: DataClassification) -> ClassificationRules:
    """Get classification rules for a tier."""
    return CLASSIFICATION_RULES[tier]


# ═══════════════════════════════════════════════════════════════════════════
# FIELD CLASSIFICATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

# Maps field names (across all services) to classification tiers.
# Used by field-level access control and log redaction.
FIELD_CLASSIFICATIONS: dict[str, DataClassification] = {
    # SENSITIVE_PII
    "email": DataClassification.SENSITIVE_PII,
    "phone": DataClassification.SENSITIVE_PII,
    "name": DataClassification.SENSITIVE_PII,
    "first_name": DataClassification.SENSITIVE_PII,
    "last_name": DataClassification.SENSITIVE_PII,
    "date_of_birth": DataClassification.SENSITIVE_PII,
    "address": DataClassification.SENSITIVE_PII,
    "ip_address": DataClassification.SENSITIVE_PII,
    "user_agent": DataClassification.SENSITIVE_PII,

    # FINANCIAL
    "account_number": DataClassification.FINANCIAL,
    "account_number_hash": DataClassification.FINANCIAL,
    "routing_number": DataClassification.FINANCIAL,
    "balance": DataClassification.FINANCIAL,
    "total": DataClassification.FINANCIAL,
    "available": DataClassification.FINANCIAL,
    "cost_basis": DataClassification.FINANCIAL,
    "market_value": DataClassification.FINANCIAL,
    "unrealized_pnl": DataClassification.FINANCIAL,
    "fill_price": DataClassification.FINANCIAL,
    "limit_price": DataClassification.FINANCIAL,
    "nav_per_token": DataClassification.FINANCIAL,

    # REGULATED
    "beneficial_owner": DataClassification.REGULATED,
    "kyc_status": DataClassification.REGULATED,
    "aml_status": DataClassification.REGULATED,
    "sanctions_match": DataClassification.REGULATED,
    "accreditation_status": DataClassification.REGULATED,
    "compliance_flags": DataClassification.REGULATED,
    "restrictions": DataClassification.REGULATED,
    "wallet_to_identity_link": DataClassification.REGULATED,

    # HIGHLY_SENSITIVE
    "ssn": DataClassification.HIGHLY_SENSITIVE,
    "tin": DataClassification.HIGHLY_SENSITIVE,
    "passport_number": DataClassification.HIGHLY_SENSITIVE,
    "encryption_key": DataClassification.HIGHLY_SENSITIVE,
    "private_key": DataClassification.HIGHLY_SENSITIVE,
    "api_key_raw": DataClassification.HIGHLY_SENSITIVE,

    # CONFIDENTIAL
    "device_fingerprint": DataClassification.CONFIDENTIAL,
    "wallet_address": DataClassification.CONFIDENTIAL,
    "session_id": DataClassification.CONFIDENTIAL,
    "risk_score": DataClassification.CONFIDENTIAL,
    "trust_score": DataClassification.CONFIDENTIAL,
    "fraud_score": DataClassification.CONFIDENTIAL,
    "bytecode_hash": DataClassification.CONFIDENTIAL,
}


def classify_field(field_name: str) -> DataClassification:
    """Get classification for a field name. Defaults to INTERNAL."""
    return FIELD_CLASSIFICATIONS.get(field_name, DataClassification.INTERNAL)


# ═══════════════════════════════════════════════════════════════════════════
# POLICY METADATA (attached to graph objects, edges, features)
# ═══════════════════════════════════════════════════════════════════════════


class PolicyMetadata(BaseModel):
    """Policy metadata attachable to any object, edge, feature, or export."""
    classification: DataClassification = DataClassification.INTERNAL
    lawful_basis: LawfulBasis = LawfulBasis.LEGITIMATE_INTEREST
    consent_purpose: str = Field(default="", description="Required consent purpose if any")
    consent_granted: bool = Field(default=True)
    collection_source: str = Field(default="")
    permitted_uses: list[str] = Field(default_factory=lambda: ["operational"])
    residency_constraint: str = Field(default="", description="e.g., 'eu_only', 'us_only'")
    retention_class: RetentionClass = RetentionClass.STANDARD
    exportable: bool = True
    deletable: bool = True
    training_eligible: bool = True
    graph_traversal_eligible: bool = True
    external_visibility: bool = True
    cross_domain_linking: bool = True
    legal_hold: bool = False


def default_policy(classification: DataClassification) -> PolicyMetadata:
    """Generate default policy metadata from a classification tier."""
    rules = get_rules(classification)
    return PolicyMetadata(
        classification=classification,
        lawful_basis=rules.default_lawful_basis,
        consent_purpose="" if not rules.requires_consent else "analytics",
        consent_granted=not rules.requires_consent,
        exportable=rules.exportable,
        training_eligible=rules.training_eligibility != TrainingEligibility.EXCLUDED,
        graph_traversal_eligible=rules.graph_traversal_allowed,
        external_visibility=rules.externally_visible,
        cross_domain_linking=rules.cross_domain_linking_allowed,
        retention_class=rules.retention,
    )
