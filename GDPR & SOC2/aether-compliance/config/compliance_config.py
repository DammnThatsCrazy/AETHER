"""
Aether Compliance — Central Configuration
GDPR framework, SOC 2 Trust Service Criteria, SLAs, consent architecture,
data protection controls, audit requirements, ROPA, and cross-border transfers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════════════════════════════════════
# ROLES
# ═══════════════════════════════════════════════════════════════════════════

class DataRole(str, Enum):
    PROCESSOR = "Data Processor"      # Aether
    CONTROLLER = "Data Controller"    # Customer
    SUB_PROCESSOR = "Sub-Processor"   # AWS, third-party APIs


# ═══════════════════════════════════════════════════════════════════════════
# GDPR DATA SUBJECT RIGHTS (Articles 15-21)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DataSubjectRight:
    article: str
    name: str
    implementation: str
    sla: str
    api_endpoint: str
    immediate: bool = False


GDPR_RIGHTS = [
    DataSubjectRight(
        article="Art. 15",
        name="Right to Access",
        implementation="Export API returns all data associated with a user ID, email, or wallet address in JSON format",
        sla="Within 30 days",
        api_endpoint="POST /v1/consent/dsr  {type: 'access'}",
    ),
    DataSubjectRight(
        article="Art. 16",
        name="Right to Rectification",
        implementation="Update API allows correction of user traits and profile data",
        sla="Within 5 business days",
        api_endpoint="POST /v1/consent/dsr  {type: 'rectification'}",
    ),
    DataSubjectRight(
        article="Art. 17",
        name="Right to Erasure",
        implementation="Delete API triggers cascading deletion across all stores: graph, event store, cache, features, predictions",
        sla="Within 30 days, backups within 90 days",
        api_endpoint="POST /v1/consent/dsr  {type: 'erasure'}",
    ),
    DataSubjectRight(
        article="Art. 18",
        name="Right to Restriction",
        implementation="Freeze API marks identity as restricted; data retained but not processed",
        sla="Immediate",
        api_endpoint="POST /v1/consent/dsr  {type: 'restriction'}",
        immediate=True,
    ),
    DataSubjectRight(
        article="Art. 20",
        name="Right to Portability",
        implementation="Export API provides data in machine-readable JSON with documented schema",
        sla="Within 30 days",
        api_endpoint="POST /v1/consent/dsr  {type: 'portability'}",
    ),
    DataSubjectRight(
        article="Art. 21",
        name="Right to Object",
        implementation="Opt-out API stops all processing for a specific identity",
        sla="Immediate",
        api_endpoint="POST /v1/consent/dsr  {type: 'objection'}",
        immediate=True,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# DATA PROTECTION BY DESIGN (Article 25)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DataProtectionControl:
    name: str
    description: str
    technical_implementation: str


DATA_PROTECTION_CONTROLS = [
    DataProtectionControl(
        "IP Anonymization",
        "All IP addresses anonymized by default before storage",
        "Last octet zeroed for IPv4, last 80 bits zeroed for IPv6",
    ),
    DataProtectionControl(
        "Data Vectorization",
        "SDK can transmit ML-computed vectors instead of raw behavioral data",
        "Backend never receives identifiable browsing patterns when vectorization enabled",
    ),
    DataProtectionControl(
        "Pseudonymization",
        "User identifiers hashed in the data lake; only Identity Service holds mapping",
        "SHA-256 with per-tenant salt",
    ),
    DataProtectionControl(
        "Data Minimization",
        "SDK collects only data categories explicitly enabled in configuration",
        "No shadow collection; each category independently toggleable",
    ),
    DataProtectionControl(
        "Encryption in Transit",
        "All data encrypted in transit",
        "TLS 1.3 enforced on all endpoints",
    ),
    DataProtectionControl(
        "Encryption at Rest",
        "All data stores encrypted at rest",
        "AES-256 via AWS KMS for all data stores",
    ),
    DataProtectionControl(
        "Access Controls",
        "Role-based access control with principle of least privilege",
        "RBAC across all services, JWT + API key auth, permission-based authorization",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# CONSENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

class ConsentPurpose(str, Enum):
    """Granular consent purposes.

    The canonical set is the 11-purpose consent registry at
    ``packages/shared/contracts/consent-registry.json`` (the single source of
    truth). Every member's value MUST equal a canonical registry ``key``; drift
    is caught by ``config.consent_registry_sync.assert_consent_registry_in_sync``.

    Legacy purpose keys that are no longer first-class are declared in
    ``LEGACY_PURPOSE_ALIASES`` and resolved via ``ConsentPurpose.from_key`` — they
    are never enumerated as canonical members. There are none today (every member
    below maps 1:1 to a registry key), but the mechanism keeps historic keys
    resolvable if the registry ever renames a purpose.
    """

    # ── Implicit purposes (registry explicitOptInRequired = false) ───────────
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    PERSONALIZATION = "personalization"  # cross-device fingerprint / recommendations
    WEB3 = "web3"
    AGENT = "agent"                      # Intelligence Graph — agent behavioral tracking
    COMMERCE = "commerce"                # Intelligence Graph — commerce/payment processing

    # ── Explicit opt-in purposes (registry explicitOptInRequired = true) ─────
    FINANCIAL_ACTIVITY = "financial_activity"          # derivatives trading analytics
    CREDIT = "credit"                                  # credit signals / decisions
    LOCATION = "location"                              # precise / coarse location
    ECONOMIC_OBSERVABILITY = "economic_observability"  # stablecoin economic intelligence
    CROSS_CHAIN_OBSERVABILITY = "cross_chain_observability"  # interop / cross-network

    @property
    def requires_explicit_opt_in(self) -> bool:
        """True when the canonical registry marks this purpose explicitOptInRequired."""
        return self in EXPLICIT_OPT_IN_PURPOSES

    @classmethod
    def from_key(cls, key: str) -> "ConsentPurpose":
        """Resolve a purpose key (canonical or legacy alias) to a canonical member.

        Raises ``ValueError`` for keys that are neither canonical nor aliased.
        """
        if key in LEGACY_PURPOSE_ALIASES:
            return LEGACY_PURPOSE_ALIASES[key]
        return cls(key)


# Purposes requiring explicit, affirmative opt-in — mirrors the registry
# ``explicitOptInRequired: true`` flag. Implicit purposes rely on legitimate
# interest / defaultEnabled semantics and are intentionally NOT listed here.
EXPLICIT_OPT_IN_PURPOSES: frozenset = frozenset({
    ConsentPurpose.FINANCIAL_ACTIVITY,
    ConsentPurpose.CREDIT,
    ConsentPurpose.LOCATION,
    ConsentPurpose.ECONOMIC_OBSERVABILITY,
    ConsentPurpose.CROSS_CHAIN_OBSERVABILITY,
})

# Legacy → canonical purpose aliases for back-compat. Maps a historical purpose
# key (as previously stored on consent records) to its canonical ConsentPurpose,
# so old keys resolve via ``ConsentPurpose.from_key`` without being treated as
# first-class purposes. Empty today — every current member is canonical.
LEGACY_PURPOSE_ALIASES: dict = {
    # "legacy_key": ConsentPurpose.CANONICAL_MEMBER,
}


@dataclass(frozen=True)
class ConsentConfig:
    # Derived from ConsentPurpose so the config never drifts from the enum
    # (which is itself reconciled against the canonical registry).
    purposes: list = field(default_factory=lambda: [p.value for p in ConsentPurpose])
    explicit_opt_in_purposes: list = field(
        default_factory=lambda: [p.value for p in ConsentPurpose if p.requires_explicit_opt_in]
    )
    storage: str = "DynamoDB with immutable audit trail"
    audit_fields: list = field(default_factory=lambda: [
        "user_id", "tenant_id", "purpose", "granted", "timestamp",
        "ip_address_hash", "user_agent_hash", "policy_version", "source",
    ])
    dnt_respected: bool = True
    withdrawal_effect: str = "Immediate cessation of data collection for that user"
    sdk_enforcement: str = "All SDK methods check consent status before collecting/transmitting data"


CONSENT_CONFIG = ConsentConfig()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STORES REQUIRING GDPR COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GDPRDataStore:
    name: str
    data_types: list
    deletion_method: str
    retention_default: str


GDPR_DATA_STORES = [
    GDPRDataStore("Neptune (Graph DB)",    ["identity nodes", "session edges", "device links", "company associations"],
                  "DELETE vertex + all connected edges by user_id",    "Until erasure request"),
    GDPRDataStore("TimescaleDB (Events)",  ["behavioral events", "page views", "custom events"],
                  "DELETE FROM events WHERE user_id = ?",              "Per tenant retention policy"),
    GDPRDataStore("ElastiCache (Redis)",   ["session cache", "profile cache", "prediction cache"],
                  "DEL key pattern user:{user_id}:*",                 "TTL-based auto-expiry"),
    GDPRDataStore("S3 (Data Lake)",        ["raw events (Parquet)", "processed events", "export files"],
                  "S3 object deletion by prefix + lifecycle policy",   "Per tenant, max 7 years"),
    GDPRDataStore("OpenSearch (Vectors)",  ["embedding vectors", "search indices"],
                  "DELETE by user_id query",                           "Aligned with source data"),
    GDPRDataStore("DynamoDB (Config)",     ["consent records", "API keys", "tenant config"],
                  "DeleteItem by key",                                 "Consent: indefinite audit trail"),
    GDPRDataStore("SageMaker (Features)",  ["ML features", "predictions", "model inputs"],
                  "Delete feature records + retrain models",           "Until erasure request"),
]


# ═══════════════════════════════════════════════════════════════════════════
# SOC 2 TRUST SERVICE CRITERIA
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TrustCriteria:
    name: str
    current_implementation: list
    gaps_for_certification: list


SOC2_TRUST_CRITERIA = [
    TrustCriteria(
        name="Security",
        current_implementation=[
            "Encryption (TLS 1.3 transit, AES-256 at rest)",
            "RBAC across all services",
            "AWS WAF (DDoS, rate limiting, bot mitigation)",
            "GuardDuty threat detection",
            "Security Hub compliance scoring",
            "VPC isolation per environment",
            "Secrets Manager for credential storage",
        ],
        gaps_for_certification=[
            "Formal security policy documentation",
            "Penetration testing report",
        ],
    ),
    TrustCriteria(
        name="Availability",
        current_implementation=[
            "Multi-AZ deployment across 3 AZs",
            "Auto-scaling on CPU/memory/request count",
            "Health checks with circuit breaker rollback",
            "DR plan (RPO 1h, RTO 4h)",
            "99.9% SLA target",
        ],
        gaps_for_certification=[
            "Formal availability SLA documentation",
            "Incident response tabletop exercises",
        ],
    ),
    TrustCriteria(
        name="Processing Integrity",
        current_implementation=[
            "Schema validation (Pydantic) on all inputs",
            "Idempotent processing with deduplication",
            "Event sourcing for audit trail",
            "Data quality scoring in ML pipeline",
        ],
        gaps_for_certification=[
            "Formal processing integrity controls documentation",
        ],
    ),
    TrustCriteria(
        name="Confidentiality",
        current_implementation=[
            "Encryption at rest and in transit",
            "Access controls (RBAC + API keys + JWT)",
            "DPA template for customers",
            "Sub-processor list maintained",
        ],
        gaps_for_certification=[
            "Formal data classification policy",
            "Quarterly access review process",
        ],
    ),
    TrustCriteria(
        name="Privacy",
        current_implementation=[
            "GDPR framework (data protection by design)",
            "Consent management architecture",
            "Data minimization in SDK",
            "Retention policies per data store",
        ],
        gaps_for_certification=[
            "Privacy impact assessment template",
            "Annual privacy review process",
        ],
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AuditTrailConfig:
    name: str
    description: str
    storage: str
    retention_days: int


AUDIT_TRAILS = [
    AuditTrailConfig("CloudTrail",          "All AWS API calls",                                    "S3 in security account", 365),
    AuditTrailConfig("Application Audit",   "All data access, modification, deletion with context", "TimescaleDB + S3",       365),
    AuditTrailConfig("Consent Audit",       "All consent grants, revocations, DSRs (immutable)",    "DynamoDB",               2555),  # 7 years
    AuditTrailConfig("Agent Audit",         "Every AI agent action with provenance and I/O",        "TimescaleDB + S3",       365),
    AuditTrailConfig("Access Reviews",      "Quarterly IAM permission reviews",                     "S3 reports",             1095),  # 3 years
]


# ═══════════════════════════════════════════════════════════════════════════
# BREACH NOTIFICATION (Article 33)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BreachNotificationConfig:
    notification_window_hours: int = 72
    dpa_authority: str = "Lead supervisory authority (determined by tenant's establishment)"
    internal_escalation_minutes: int = 30
    channels: list = field(default_factory=lambda: [
        "PagerDuty (immediate)",
        "Slack #security-incidents",
        "Email: security@aether.network",
        "DPA notification (within 72 hours)",
        "Affected data subjects (if high risk)",
    ])


BREACH_CONFIG = BreachNotificationConfig()


# ═══════════════════════════════════════════════════════════════════════════
# RECORD OF PROCESSING ACTIVITIES — ROPA (Article 30)  [NEW]
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ProcessingActivity:
    """Art. 30 — Record of Processing Activities entry."""
    name: str
    purpose: str
    legal_basis: str
    data_categories: list
    data_subjects: str
    recipients: list
    cross_border: bool
    retention: str
    safeguards: str


PROCESSING_ACTIVITIES = [
    ProcessingActivity(
        name="Behavioral Analytics",
        purpose="Website/app user behavior tracking for analytics dashboards",
        legal_basis="Art. 6(1)(a) — Consent, or Art. 6(1)(f) — Legitimate Interest",
        data_categories=["page views", "clicks", "scroll depth", "custom events", "device info"],
        data_subjects="End users of customer websites/apps",
        recipients=["Aether (processor)", "AWS (sub-processor)"],
        cross_border=True,
        retention="Per tenant config, default 90 days, max 7 years",
        safeguards="SCCs + encryption + pseudonymization",
    ),
    ProcessingActivity(
        name="Identity Resolution",
        purpose="Merge anonymous sessions into known identity profiles",
        legal_basis="Art. 6(1)(a) — Consent",
        data_categories=["user ID", "email hash", "device fingerprint", "session data", "wallet address"],
        data_subjects="End users who have been identified",
        recipients=["Aether (processor)", "AWS (sub-processor)"],
        cross_border=True,
        retention="Until erasure request",
        safeguards="Pseudonymization + graph-level isolation",
    ),
    ProcessingActivity(
        name="ML Predictions",
        purpose="Churn prediction, journey forecasting, audience segmentation",
        legal_basis="Art. 6(1)(a) — Consent for profiling, or Art. 6(1)(f) — Legitimate Interest",
        data_categories=["behavioral features", "identity features", "prediction scores"],
        data_subjects="End users with sufficient behavioral data",
        recipients=["Aether (processor)", "AWS SageMaker (sub-processor)"],
        cross_border=True,
        retention="Until erasure request, models retrained without deleted data",
        safeguards="Feature-level pseudonymization + model access controls",
    ),
    ProcessingActivity(
        name="Campaign Orchestration",
        purpose="Trigger personalized campaigns based on user segments and predictions",
        legal_basis="Art. 6(1)(a) — Consent (marketing purpose)",
        data_categories=["segment membership", "prediction scores", "campaign interactions"],
        data_subjects="End users in marketing-consented segments",
        recipients=["Aether (processor)", "Customer email/SMS providers (sub-processors)"],
        cross_border=True,
        retention="Campaign: 1 year, interactions: per tenant policy",
        safeguards="Consent check before every campaign action",
    ),
    ProcessingActivity(
        name="Consent Record Keeping",
        purpose="Maintain immutable audit trail of consent grants, revocations, and DSRs",
        legal_basis="Art. 6(1)(c) — Legal Obligation (Art. 7(1) proof of consent)",
        data_categories=["consent records", "timestamps", "IP hash", "user agent hash", "policy version"],
        data_subjects="All end users interacting with consent mechanisms",
        recipients=["Aether (processor)"],
        cross_border=False,
        retention="7 years (legal obligation)",
        safeguards="Immutable DynamoDB records + encryption at rest",
    ),
    ProcessingActivity(
        name="Web3 Wallet Analytics",
        purpose="Track wallet connections and on-chain interactions for analytics",
        legal_basis="Art. 6(1)(a) — Consent (web3 purpose)",
        data_categories=["wallet address", "chain ID", "connection events", "transaction hashes"],
        data_subjects="End users connecting Web3 wallets",
        recipients=["Aether (processor)", "Blockchain RPCs (public)"],
        cross_border=True,
        retention="Per tenant config",
        safeguards="Wallet address pseudonymization + consent gating",
    ),

    # Intelligence Graph — 3 new processing activities

    ProcessingActivity(
        name="Agent Behavioral Tracking",
        purpose="Track AI agent task lifecycle, decisions, state snapshots, and ground truth feedback",
        legal_basis="Art. 6(1)(f) — Legitimate Interest",
        data_categories=["agent_id", "task_data", "decision_records", "state_snapshots", "confidence_delta"],
        data_subjects="AI agents operated by end users",
        recipients=["Aether (processor)", "AWS (sub-processor)"],
        cross_border=True,
        retention="365 days",
        safeguards="Agent ID pseudonymization + owner consent gating",
    ),
    ProcessingActivity(
        name="Commerce Payment Processing",
        purpose="Record payments between humans, agents, and services; compute fee elimination",
        legal_basis="Art. 6(1)(b) — Contract",
        data_categories=["payment_amounts", "transaction_hashes", "fee_computations", "payer/payee_ids"],
        data_subjects="End users and AI agents making/receiving payments",
        recipients=["Aether (processor)", "Blockchain networks (public settlement)"],
        cross_border=True,
        retention="7 years (financial records)",
        safeguards="Payment ID pseudonymization + consent gating (commerce purpose)",
    ),
    ProcessingActivity(
        name="On-Chain Action Intelligence",
        purpose="Record smart contract deployments, calls, and upgrades; assess bytecode risk",
        legal_basis="Art. 6(1)(f) — Legitimate Interest",
        data_categories=["contract_addresses", "bytecode_hashes", "action_intents", "risk_scores"],
        data_subjects="AI agents deploying/calling smart contracts",
        recipients=["Aether (processor)", "QuickNode (sub-processor)", "Blockchain RPCs (public)"],
        cross_border=True,
        retention="Indefinite (on-chain data is public/immutable)",
        safeguards="Agent ID pseudonymization + bytecode-only analysis (no private keys)",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-BORDER TRANSFERS (Chapter V)  [NEW]
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CrossBorderTransfer:
    """Art. 44-49 — Cross-border data transfer record."""
    destination: str
    sub_processor: str
    transfer_mechanism: str
    data_categories: list
    tia_completed: bool  # Transfer Impact Assessment


CROSS_BORDER_TRANSFERS = [
    CrossBorderTransfer(
        destination="US (us-east-1, us-west-2)",
        sub_processor="AWS",
        transfer_mechanism="EU SCCs (Module 3: Processor to Sub-Processor) + supplementary measures",
        data_categories=["behavioral events", "identity profiles", "ML features"],
        tia_completed=True,
    ),
    CrossBorderTransfer(
        destination="US (us-east-1)",
        sub_processor="AWS SageMaker",
        transfer_mechanism="EU SCCs (Module 3) + encryption in transit and at rest",
        data_categories=["ML features", "predictions"],
        tia_completed=True,
    ),
    CrossBorderTransfer(
        destination="Global (CDN edge)",
        sub_processor="AWS CloudFront",
        transfer_mechanism="EU SCCs + data minimization (SDK code only, no personal data at edge)",
        data_categories=["SDK JavaScript bundle (no personal data)"],
        tia_completed=True,
    ),
]
