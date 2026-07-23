"""Canonical Pydantic contracts for the measurement domain.

All measurement objects use these contracts at API boundaries.
Internal data access uses these models for validation and serialization.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enumerations ────────────────────────────────────────────────────────────

class TouchpointType(str, Enum):
    impression = "impression"
    viewable_impression = "viewable_impression"
    ad_exposure = "ad_exposure"
    engaged_view = "engaged_view"
    click = "click"
    landing = "landing"
    session_entry = "session_entry"
    page_view = "page_view"
    product_view = "product_view"
    search_exposure = "search_exposure"
    recommendation_exposure = "recommendation_exposure"
    email_delivery = "email_delivery"
    email_open = "email_open"
    email_click = "email_click"
    email_reply = "email_reply"
    push_presentation = "push_presentation"
    push_click = "push_click"
    sms_interaction = "sms_interaction"
    referral = "referral"
    affiliate_interaction = "affiliate_interaction"
    sales_interaction = "sales_interaction"
    crm_interaction = "crm_interaction"
    organic_discovery = "organic_discovery"
    direct_interaction = "direct_interaction"
    wallet_interaction = "wallet_interaction"
    agent_mediated = "agent_mediated"
    offline_interaction = "offline_interaction"
    custom = "custom"
    # Legacy alias accepted from campaign API
    pageview = "page_view"


class ConversionType(str, Enum):
    lead = "lead"
    qualified_lead = "qualified_lead"
    signup = "signup"
    trial = "trial"
    trial_conversion = "trial_conversion"
    purchase = "purchase"
    order = "order"
    payment = "payment"
    subscription = "subscription"
    renewal = "renewal"
    upgrade = "upgrade"
    downgrade = "downgrade"
    opportunity = "opportunity"
    closed_won = "closed_won"
    on_chain_settlement = "on_chain_settlement"
    x402_settlement = "x402_settlement"
    reward_redemption = "reward_redemption"
    custom = "custom"


class ConversionStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    reversed = "reversed"
    adjusted = "adjusted"
    ineligible = "ineligible"


class AdjustmentType(str, Enum):
    refund = "refund"
    partial_refund = "partial_refund"
    return_ = "return"
    chargeback = "chargeback"
    cancellation = "cancellation"
    discount_correction = "discount_correction"
    tax_correction = "tax_correction"
    fee_correction = "fee_correction"
    renewal = "renewal"
    upgrade = "upgrade"
    downgrade = "downgrade"
    manual_governed = "manual_governed"


class AttributionRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class QualityStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    estimated = "estimated"
    stale = "stale"
    invalid = "invalid"
    degraded = "degraded"
    not_provisioned = "not_provisioned"
    failed = "failed"


# ── Quality Metadata ────────────────────────────────────────────────────────

class QualityMetadata(BaseModel):
    status: QualityStatus = QualityStatus.complete
    freshness: Optional[datetime] = None
    coverage: Optional[float] = None
    confidence: Optional[float] = None
    source_count: Optional[int] = None
    excluded_record_count: Optional[int] = None
    unresolved_record_count: Optional[int] = None
    last_complete_period: Optional[datetime] = None
    provenance: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    message: Optional[str] = None


# ── Canonical Touchpoint ─────────────────────────────────────────────────────

class CanonicalTouchpoint(BaseModel):
    touchpoint_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    account_id: Optional[str] = None
    organization_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_set_id: Optional[str] = None
    creative_id: Optional[str] = None
    ad_id: Optional[str] = None
    placement_id: Optional[str] = None
    keyword_id: Optional[str] = None
    audience_id: Optional[str] = None
    offer_id: Optional[str] = None
    landing_page_id: Optional[str] = None
    channel: Optional[str] = None
    source: Optional[str] = None
    medium: Optional[str] = None
    platform: Optional[str] = None
    source_class: Optional[str] = None
    referral_mediation_type: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_product: Optional[str] = None
    actor_type: Optional[str] = None
    journey_role: Optional[str] = None
    evidence_confidence: Optional[float] = None
    verification_level: Optional[str] = None
    source_classifier_version: Optional[str] = None
    source_classified_at: Optional[datetime] = None
    normalized_referrer_domain: Optional[str] = None
    referrer_path_hash: Optional[str] = None
    source_classification_evidence: dict[str, Any] = Field(default_factory=dict)
    source_classification_id: Optional[str] = None
    attribution_eligible: bool = True
    verified_referral_link_id: Optional[str] = None
    touchpoint_type: TouchpointType = TouchpointType.page_view
    interaction_type: Optional[str] = None
    is_view_through: bool = False
    is_click_through: bool = False
    viewable: Optional[bool] = None
    engaged: Optional[bool] = None
    dwell_ms: Optional[int] = None
    position: Optional[int] = None
    frequency: Optional[int] = None
    occurred_at: datetime
    received_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    source_event_id: Optional[str] = None
    connector_record_id: Optional[str] = None
    source_connector_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    click_id: Optional[str] = None
    referrer: Optional[str] = None
    landing_url: Optional[str] = None
    identity_resolution_method: Optional[str] = None
    identity_confidence: Optional[float] = None
    identity_version: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    privacy_class: str = "behavioral"
    provenance: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    idempotency_key: str
    schema_version: int = 1


# ── Canonical Conversion ─────────────────────────────────────────────────────

class CanonicalConversion(BaseModel):
    conversion_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    conversion_type: ConversionType
    conversion_name: Optional[str] = None
    goal_id: Optional[str] = None
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    account_id: Optional[str] = None
    organization_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    subscription_id: Optional[str] = None
    invoice_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    transaction_hash: Optional[str] = None
    external_conversion_id: Optional[str] = None
    gross_value: Optional[Decimal] = None
    discount_value: Decimal = Decimal("0")
    tax_value: Decimal = Decimal("0")
    shipping_value: Decimal = Decimal("0")
    fee_value: Decimal = Decimal("0")
    refund_value: Decimal = Decimal("0")
    chargeback_value: Decimal = Decimal("0")
    contribution_value: Optional[Decimal] = None
    net_value: Optional[Decimal] = None
    currency: str = "USD"
    normalized_currency: str = "USD"
    exchange_rate: Decimal = Decimal("1.0")
    quantity: int = 1
    product_ids: list[str] = Field(default_factory=list)
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    occurred_at: datetime
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None
    adjusted_at: Optional[datetime] = None
    reversed_at: Optional[datetime] = None
    conversion_status: ConversionStatus = ConversionStatus.confirmed
    conversion_source: Optional[str] = None
    authority_rank: int = 50
    deduplication_key: str
    attribution_eligible: bool = True
    consent_snapshot_id: Optional[str] = None
    identity_version: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    source_connector_id: Optional[str] = None
    source_event_id: Optional[str] = None
    schema_version: int = 1

    @model_validator(mode="after")
    def compute_net_value(self) -> "CanonicalConversion":
        if self.net_value is None and self.gross_value is not None:
            self.net_value = (
                self.gross_value
                - self.discount_value
                - self.refund_value
                - self.chargeback_value
            )
        return self


# ── Revenue Adjustment ──────────────────────────────────────────────────────

class RevenueAdjustment(BaseModel):
    adjustment_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    conversion_id: UUID
    adjustment_type: AdjustmentType
    amount: Decimal
    currency: str = "USD"
    normalized_amount: Optional[Decimal] = None
    occurred_at: datetime
    reason: Optional[str] = None
    source_event_id: Optional[str] = None
    connector_record_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    idempotency_key: str
    schema_version: int = 1


# ── Spend Record ────────────────────────────────────────────────────────────

class SpendRecord(BaseModel):
    spend_record_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    platform: Optional[str] = None
    ad_account_id: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_set_id: Optional[str] = None
    creative_id: Optional[str] = None
    ad_id: Optional[str] = None
    placement_id: Optional[str] = None
    keyword_id: Optional[str] = None
    period_start: datetime
    period_end: datetime
    source_timezone: str = "UTC"
    billing_currency: str = "USD"
    normalized_currency: str = "USD"
    exchange_rate: Decimal = Decimal("1.0")
    impressions: int = 0
    reach: int = 0
    frequency: Optional[Decimal] = None
    clicks: int = 0
    engagements: int = 0
    video_views: int = 0
    viewable_impressions: int = 0
    media_spend: Decimal = Decimal("0")
    platform_fees: Decimal = Decimal("0")
    agency_fees: Decimal = Decimal("0")
    creative_cost: Decimal = Decimal("0")
    affiliate_cost: Decimal = Decimal("0")
    other_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    source_record_id: Optional[str] = None
    source_connector_id: Optional[str] = None
    sync_run_id: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    schema_version: int = 1

    @model_validator(mode="after")
    def compute_total_cost(self) -> "SpendRecord":
        if self.total_cost == Decimal("0"):
            self.total_cost = (
                self.media_spend
                + self.platform_fees
                + self.agency_fees
                + self.creative_cost
                + self.affiliate_cost
                + self.other_cost
            )
        return self


# ── Journey Version ─────────────────────────────────────────────────────────

class JourneyVersion(BaseModel):
    journey_version_id: UUID = Field(default_factory=uuid4)
    journey_id: UUID
    tenant_id: str
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    account_id: Optional[str] = None
    organization_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    journey_type: str = "profile"
    journey_state: str = "open"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    converted_at: Optional[datetime] = None
    entry_touchpoint_id: Optional[UUID] = None
    exit_touchpoint_id: Optional[UUID] = None
    conversion_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    touchpoint_ids: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)
    campaign_ids: list[str] = Field(default_factory=list)
    channel_sequence: list[str] = Field(default_factory=list)
    previous_version_id: Optional[UUID] = None
    rebuild_reason: Optional[str] = None
    identity_version: Optional[str] = None
    data_watermark: Optional[datetime] = None
    compiler_version: str = "1.0"
    excluded_source_noise_count: int = 0
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    is_current: bool = True


# ── Attribution Model Config ────────────────────────────────────────────────

class AttributionModelConfig(BaseModel):
    model_config_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    name: str
    model_type: str
    model_version: str = "1.0"
    conversion_types: list[str] = Field(default_factory=lambda: ["all"])
    click_lookback_window: int = 720
    view_lookback_window: int = 168
    engaged_view_threshold_ms: int = 1000
    session_timeout_seconds: int = 1800
    direct_traffic_policy: str = "include"
    organic_policy: str = "include"
    brand_search_policy: str = "include"
    cross_device_policy: str = "enabled"
    identity_confidence_min: float = 0.5
    fraud_policy: str = "exclude"
    internal_traffic_policy: str = "exclude"
    repeat_conversion_policy: str = "include_all"
    currency_policy: str = "normalize_usd"
    status: str = "active"
    effective_from: datetime = Field(default_factory=datetime.utcnow)
    effective_until: Optional[datetime] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None


# ── Attribution Run ─────────────────────────────────────────────────────────

class AttributionRun(BaseModel):
    attribution_run_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    conversion_id: UUID
    conversion_version: Optional[str] = None
    journey_id: Optional[UUID] = None
    journey_version_id: Optional[UUID] = None
    model_config_id: Optional[UUID] = None
    model_type: str
    model_version: str = "1.0"
    code_version: Optional[str] = None
    trigger_reason: Optional[str] = None
    source_classifier_version: Optional[str] = None
    model_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    prior_attribution_run_id: Optional[UUID] = None
    input_touchpoint_ids: list[str] = Field(default_factory=list)
    excluded_touchpoint_ids: list[str] = Field(default_factory=list)
    exclusion_reasons: dict[str, str] = Field(default_factory=dict)
    eligible_revenue: Optional[Decimal] = None
    credit_total: Decimal = Decimal("1.0")
    unattributed_credit: Decimal = Decimal("0.0")
    identity_confidence: Optional[float] = None
    model_confidence: Optional[float] = None
    data_watermark: Optional[datetime] = None
    currency: str = "USD"
    status: AttributionRunStatus = AttributionRunStatus.pending
    failure_reason: Optional[str] = None
    is_active: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Attribution Credit ──────────────────────────────────────────────────────

class AttributionCredit(BaseModel):
    credit_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    attribution_run_id: UUID
    conversion_id: UUID
    touchpoint_id: Optional[UUID] = None
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_set_id: Optional[str] = None
    creative_id: Optional[str] = None
    ad_id: Optional[str] = None
    placement_id: Optional[str] = None
    keyword_id: Optional[str] = None
    channel: Optional[str] = None
    source: Optional[str] = None
    source_class: Optional[str] = None
    referral_mediation_type: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_product: Optional[str] = None
    actor_type: Optional[str] = None
    journey_role: Optional[str] = None
    evidence_confidence: Optional[float] = None
    verification_level: Optional[str] = None
    source_classifier_version: Optional[str] = None
    normalized_referrer_domain: Optional[str] = None
    source_classification_id: Optional[str] = None
    attribution_eligible: bool = True
    verified_referral_link_id: Optional[str] = None
    credit_weight: Decimal
    attributed_conversion_count: Decimal = Decimal("0")
    attributed_gross_revenue: Optional[Decimal] = None
    attributed_net_revenue: Optional[Decimal] = None
    attributed_contribution_value: Optional[Decimal] = None
    identity_confidence: Optional[float] = None
    model_confidence: Optional[float] = None
    explanation: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("credit_weight")
    @classmethod
    def credit_weight_range(cls, v: Decimal) -> Decimal:
        if v < Decimal("0") or v > Decimal("1"):
            raise ValueError(f"credit_weight must be in [0, 1], got {v}")
        return v


# ── Canonical Activity ────────────────────────────────────────────────────────

class ActivityFamily(str, Enum):
    web2 = "web2"
    web3 = "web3"
    campaign = "campaign"
    commerce = "commerce"
    agent = "agent"
    x402 = "x402"
    outcome = "outcome"


class ActivityStatus(str, Enum):
    observed = "observed"
    pending = "pending"
    confirmed = "confirmed"
    finalized = "finalized"
    failed = "failed"
    reverted = "reverted"
    reorged = "reorged"
    adjusted = "adjusted"
    deleted = "deleted"
    tombstoned = "tombstoned"
    consent_restricted = "consent_restricted"
    unresolved = "unresolved"


class TransitionType(str, Enum):
    same_session = "same_session"
    new_session = "new_session"
    cross_device = "cross_device"
    cross_browser = "cross_browser"
    cross_domain = "cross_domain"
    web_to_mobile = "web_to_mobile"
    mobile_to_web = "mobile_to_web"
    web_to_dapp = "web_to_dapp"
    dapp_to_web = "dapp_to_web"
    web2_to_web3 = "web2_to_web3"
    web3_to_web2 = "web3_to_web2"
    wallet_connected = "wallet_connected"
    wallet_disconnected = "wallet_disconnected"
    cross_wallet = "cross_wallet"
    cross_chain = "cross_chain"
    cross_protocol = "cross_protocol"
    human_to_agent = "human_to_agent"
    agent_to_human = "agent_to_human"
    agent_to_agent = "agent_to_agent"
    campaign_to_owned_surface = "campaign_to_owned_surface"
    owned_surface_to_conversion = "owned_surface_to_conversion"
    identity_resolved = "identity_resolved"
    identity_merged = "identity_merged"
    identity_split = "identity_split"
    consent_state_changed = "consent_state_changed"
    unknown = "unknown"


class CanonicalActivity(BaseModel):
    activity_id: Optional[UUID] = Field(default_factory=uuid4)
    tenant_id: str
    idempotency_key: str

    # Identity links
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    account_id: Optional[str] = None
    organization_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    browser_id: Optional[str] = None
    install_id: Optional[str] = None
    wallet_id: Optional[str] = None
    wallet_address: Optional[str] = None
    agent_id: Optional[str] = None

    # Classification
    activity_family: ActivityFamily
    activity_type: str
    actor_type: Optional[str] = None

    # Surface / location
    channel: Optional[str] = None
    source: Optional[str] = None
    medium: Optional[str] = None
    platform: Optional[str] = None
    surface: Optional[str] = None
    source_class: Optional[str] = None
    referral_mediation_type: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_product: Optional[str] = None
    journey_role: Optional[str] = None
    evidence_confidence: Optional[float] = None
    verification_level: Optional[str] = None
    source_classifier_version: Optional[str] = None
    normalized_referrer_domain: Optional[str] = None
    source_classification_id: Optional[str] = None
    attribution_eligible: bool = True
    verified_referral_link_id: Optional[str] = None
    domain: Optional[str] = None
    app_id: Optional[str] = None
    screen: Optional[str] = None
    landing_url: Optional[str] = None
    referrer: Optional[str] = None
    dapp_id: Optional[str] = None
    protocol_id: Optional[str] = None
    chain_id: Optional[str] = None
    contract_address: Optional[str] = None

    # Web3 specifics
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None

    # Campaign linkage
    campaign_id: Optional[str] = None
    conversion_id: Optional[str] = None

    # Timing
    occurred_at: datetime
    client_occurred_at: Optional[datetime] = None
    server_received_at: datetime = Field(default_factory=datetime.utcnow)
    chain_observed_at: Optional[datetime] = None
    chain_confirmed_at: Optional[datetime] = None

    # Lifecycle
    activity_status: ActivityStatus = ActivityStatus.observed

    # Provenance
    source_event_id: str
    source_system: Optional[str] = None
    source_connector_id: Optional[str] = None

    # Identity evidence
    identity_method: Optional[str] = None
    identity_confidence: Optional[float] = None
    identity_version: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    privacy_class: str = "behavioral"

    # Ordering / replay
    sequence_key: Optional[str] = None
    schema_version: int = 1

    # Silver lineage
    silver_fact_id: Optional[UUID] = None
    silver_table: Optional[str] = None

    # Economic semantics
    gross_amount: Optional[Decimal] = None
    net_amount: Optional[Decimal] = None
    fee_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    token_address: Optional[str] = None
    value_wei: Optional[str] = None


# ── Journey Step ──────────────────────────────────────────────────────────────

class JourneyStep(BaseModel):
    step_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    journey_id: UUID
    journey_version_id: UUID
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None

    step_position: int
    occurred_at: datetime

    activity_id: UUID
    activity_family: ActivityFamily
    activity_type: str

    transition_type: Optional[TransitionType] = None
    transition_evidence: dict[str, Any] = Field(default_factory=dict)

    # Denormalized display fields
    actor_type: Optional[str] = None
    channel: Optional[str] = None
    source: Optional[str] = None
    source_class: Optional[str] = None
    referral_mediation_type: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_product: Optional[str] = None
    journey_role: Optional[str] = None
    evidence_confidence: Optional[float] = None
    verification_level: Optional[str] = None
    source_classifier_version: Optional[str] = None
    normalized_referrer_domain: Optional[str] = None
    source_classification_id: Optional[str] = None
    attribution_eligible: bool = True
    verified_referral_link_id: Optional[str] = None
    domain: Optional[str] = None
    app_id: Optional[str] = None
    dapp_id: Optional[str] = None
    chain_id: Optional[str] = None
    campaign_id: Optional[str] = None
    conversion_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    activity_status: ActivityStatus = ActivityStatus.observed

    identity_confidence: Optional[float] = None
    identity_method: Optional[str] = None
    identity_version: Optional[str] = None
    evidence_summary: dict[str, Any] = Field(default_factory=dict)

    schema_version: int = 1
