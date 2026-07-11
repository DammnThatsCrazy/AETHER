"""Internal domain models for the identity resolution subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class IdentitySignalType(str, Enum):
    USER_ID = "user_id"
    ANONYMOUS_ID = "anonymous_id"
    SESSION_ID = "session_id"
    DEVICE_FINGERPRINT = "device_fingerprint"
    EMAIL_HASH = "email_hash"
    PHONE_HASH = "phone_hash"
    EXTERNAL_ID = "external_id"
    WALLET_ADDRESS = "wallet_address"
    WALLET_SIGNATURE_VERIFIED = "wallet_signature_verified"
    AGENT_ID = "agent_id"
    ORG_ID = "org_id"
    CAMPAIGN_ID = "campaign_id"
    JOURNEY_ID = "journey_id"
    COMMERCE_CUSTOMER_ID = "commerce_customer_id"
    PAYMENT_CUSTOMER_ID = "payment_customer_id"
    ACCOUNT_ID = "account_id"
    INSTALLATION_ID = "installation_id"
    BROWSER_ID = "browser_id"
    MOBILE_INSTALL_ID = "mobile_install_id"


class ConfidenceTier(str, Enum):
    BLOCKED = "blocked"
    WEAK = "weak"
    PROBABLE = "probable"
    STRONG = "strong"
    DETERMINISTIC = "deterministic"


class MergeDecision(str, Enum):
    CREATE = "create"
    LINK = "link"
    MERGE = "merge"
    CANDIDATE = "candidate"
    REJECT = "reject"
    NOOP = "noop"
    BLOCKED = "blocked"


class EntityType(str, Enum):
    HUMAN = "human"
    ANONYMOUS_VISITOR = "anonymous_visitor"
    DEVICE = "device"
    SESSION = "session"
    WALLET = "wallet"
    AGENT = "agent"
    ORGANIZATION = "organization"
    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    JOURNEY = "journey"
    COMMERCE_CUSTOMER = "commerce_customer"
    PAYMENT_CUSTOMER = "payment_customer"


class EdgeType(str, Enum):
    SAME_AS = "same_as"
    OBSERVED_AS = "observed_as"
    LOGGED_IN_AS = "logged_in_as"
    USES_DEVICE = "uses_device"
    OWNS_WALLET = "owns_wallet"
    CONTROLS_WALLET = "controls_wallet"
    DELEGATES_TO_AGENT = "delegates_to_agent"
    AGENT_ACTS_FOR = "agent_acts_for"
    BELONGS_TO_ORG = "belongs_to_org"
    CAME_FROM_CAMPAIGN = "came_from_campaign"
    PARTICIPATED_IN_JOURNEY = "participated_in_journey"
    CONVERTED_AFTER_TOUCH = "converted_after_touch"


class ConflictStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class SubjectStatus(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"
    SPLIT = "split"


# ── Reason codes ──────────────────────────────────────────────────────────────

REASON_SAME_USER_ID = "same_user_id"
REASON_SAME_EXTERNAL_ID = "same_external_id"
REASON_SAME_VERIFIED_WALLET = "same_verified_wallet"
REASON_SAME_EMAIL_HASH = "same_email_hash"
REASON_SAME_PHONE_HASH = "same_phone_hash"
REASON_SAME_ANONYMOUS_ID = "same_anonymous_id"
REASON_SAME_SESSION_ID = "same_session_id"
REASON_SAME_DEVICE_INSTALL = "same_device_install"
REASON_SAME_CAMPAIGN_PATH = "same_campaign_path"
REASON_SAME_JOURNEY_PATH = "same_journey_path"
REASON_SAME_AGENT_DELEGATION = "same_agent_delegation"
REASON_SAME_ORG_ACCOUNT = "same_org_account"
REASON_CONSENT_ALLOWS_LINK = "consent_allows_link"
REASON_CONSENT_BLOCKS_LINK = "consent_blocks_link"
REASON_CROSS_TENANT_BLOCKED = "cross_tenant_blocked"
REASON_FINGERPRINT_ONLY_BLOCKED = "fingerprint_only_blocked"
REASON_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
REASON_CONFLICTING_ALIAS = "conflicting_alias"
REASON_REVOKED_ALIAS = "revoked_alias"
REASON_MANUAL_OPERATOR_MERGE = "manual_operator_merge"
REASON_MANUAL_OPERATOR_SPLIT = "manual_operator_split"
REASON_NEW_ENTITY = "new_entity"
# ── Fragment-aware identity repair (typed split rejections + markers) ──────────
REASON_FRAGMENT_SPLIT = "fragment_split"
REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED = "campaign_only_sameness_blocked"
REASON_CROSS_TENANT_FRAGMENT_BLOCKED = "cross_tenant_fragment_blocked"
REASON_IDENTITY_CYCLE_BLOCKED = "identity_cycle_detected"


# ── Domain model dataclasses ──────────────────────────────────────────────────

@dataclass
class IdentitySignal:
    type: IdentitySignalType
    value: str
    normalized_value_hash: Optional[str] = None
    confidence_hint: float = 1.0
    source: str = ""
    observed_at: str = ""
    source_event_id: str = ""
    source_platform: str = ""
    source_sdk: str = ""
    consent_snapshot: Optional[dict] = None


@dataclass
class IdentitySubject:
    id: str
    tenant_id: str
    canonical_entity_id: str
    entity_type: EntityType
    status: SubjectStatus = SubjectStatus.ACTIVE
    # When status == MERGED, the surviving canonical entity this subject was
    # merged into. Read by the survivor-redirect resolver so a lookup of a
    # merged (secondary) entity id follows the tombstone to the survivor.
    merged_into_entity_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class IdentityAlias:
    id: str
    tenant_id: str
    canonical_entity_id: str
    alias_type: IdentitySignalType
    alias_value_hash: str
    alias_display_value_redacted: str = ""
    source: str = ""
    source_event_id: str = ""
    source_platform: str = ""
    confidence: float = 1.0
    confidence_tier: ConfidenceTier = ConfidenceTier.DETERMINISTIC
    consent_snapshot: Optional[dict] = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    revoked_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class IdentitySignalObservation:
    id: str
    tenant_id: str
    source_event_id: str
    source_platform: str
    source_sdk: str
    signal_type: IdentitySignalType
    signal_value_hash: str
    raw_value_redacted: str = ""
    observed_at: str = ""
    consent_snapshot: Optional[dict] = None
    context: dict = field(default_factory=dict)
    created_at: str = ""


@dataclass
class IdentityCluster:
    id: str
    tenant_id: str
    canonical_entity_id: str
    cluster_version: int = 1
    status: str = "active"
    confidence: float = 1.0
    reason_codes: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class IdentityEdge:
    id: str
    tenant_id: str
    source_entity_id: str
    target_entity_id: str
    edge_type: EdgeType
    confidence: float = 1.0
    confidence_tier: ConfidenceTier = ConfidenceTier.DETERMINISTIC
    reason_codes: list[str] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    consent_snapshot: Optional[dict] = None
    created_at: str = ""
    revoked_at: Optional[str] = None


@dataclass
class IdentityResolutionDecision:
    tenant_id: str
    canonical_entity_id: str
    decision: MergeDecision
    confidence: float
    confidence_tier: ConfidenceTier
    reason_codes: list[str]
    linked_aliases: list[str] = field(default_factory=list)
    candidate_entity_ids: list[str] = field(default_factory=list)
    conflict_id: Optional[str] = None
    source_event_ids: list[str] = field(default_factory=list)
    graph_edges_written: list[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    audit_id: Optional[str] = None
    is_new_entity: bool = False


@dataclass
class IdentityMergeEvent:
    id: str
    tenant_id: str
    from_entity_id: str
    into_entity_id: str
    resulting_entity_id: str
    confidence: float
    confidence_tier: ConfidenceTier
    reason_codes: list[str]
    source_event_ids: list[str]
    actor_type: str
    actor_id: str
    created_at: str


@dataclass
class IdentitySplitEvent:
    id: str
    tenant_id: str
    original_entity_id: str
    resulting_entity_ids: list[str]
    reason: str
    actor_type: str
    actor_id: str
    source_merge_event_id: Optional[str]
    created_at: str


@dataclass
class IdentityConflict:
    id: str
    tenant_id: str
    candidate_entity_ids: list[str]
    candidate_aliases: list[dict]
    conflict_type: str
    confidence: float
    reason_codes: list[str]
    status: ConflictStatus = ConflictStatus.OPEN
    created_at: str = ""
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


@dataclass
class IdentityResolutionAuditRecord:
    id: str
    tenant_id: str
    decision: str
    canonical_entity_id: str
    candidate_entity_ids: list[str]
    confidence: float
    confidence_tier: ConfidenceTier
    reason_codes: list[str]
    source_event_ids: list[str]
    policy_result: str
    consent_snapshot: Optional[dict]
    created_at: str
