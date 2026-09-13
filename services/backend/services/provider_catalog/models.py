"""
Aether — Provider Source Catalog Models

Data models for the Olympus-owned external provider corpus (Layer 1).
This catalog is NOT tenant BYOD — it represents Olympus Labs' controlled
provider integrations feeding the baseline intelligence corpus.

Every entry declares: access mode, lake policy, provenance requirements,
cost/rate-limit profiles, source manifests, and model training eligibility.
"""
from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field

from services.integrations.connectors.base import (
    ConnectorClass,
    ConnectorRole,
    DataFlowDirection,
    LakeWritePolicy,
    GraphWritePolicy,
    ModelTrainingEligibility,
    ImplementationStatus,
    PriorityPhase,
    RiskTier,
)


# ═══════════════════════════════════════════════════════════════════════════
# DUNE ACCESS MODES
# ═══════════════════════════════════════════════════════════════════════════

class DuneAccessMode(BaseModel):
    """One of three distinct Dune Analytics access modes.

    Dune is the historical on-chain core. The three modes are distinct:
    - dune_api: prototyping, parameterized SQL, supplemental extraction
    - dune_datashare: full warehouse bootstrap via Snowflake/BigQuery/Databricks
    - dune_sim: real-time wallet enrichment (not bulk historical)
    """
    mode_id: str  # dune_api | dune_datashare | dune_sim
    display_name: str
    purpose: str
    connector_role: ConnectorRole
    supports_query_execution: bool = False
    supports_warehouse_datashare: bool = False
    supports_realtime_stream: bool = False
    supports_historical_backfill: bool = False
    max_result_size_metadata: Optional[str] = None
    pagination_supported: bool = False
    read_only_source: bool = True
    source_owner: str = "Dune Analytics"
    olympus_materialized_copy_owner: str = "Olympus Labs (subject to contract)"
    license_basis: str = "pending_review"
    model_training_basis: str = "compliance_review_required"
    implementation_status: ImplementationStatus = ImplementationStatus.CREDENTIAL_GATED
    staging_blocker: Optional[str] = None
    rate_limit_profile_id: str
    cost_profile_id: str
    # Datashare-specific
    warehouse_provider: Optional[str] = None  # snowflake | bigquery | databricks
    refresh_cadence: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# CHAIN EXTRACTION PLAN
# ═══════════════════════════════════════════════════════════════════════════

class ChainExtractionPlan(BaseModel):
    """Extraction plan for a single blockchain via Dune.

    Priority tiers:
    P0_CRITICAL: Ethereum, Solana, BNB, Polygon, Arbitrum, Base
    P1_HIGH: Optimism, Avalanche, TRON, Bitcoin, NEAR, Sui
    P2_MEDIUM: remaining L2s, appchains, new ecosystems
    """
    chain_id: str
    chain_name: str
    priority: str  # P0_CRITICAL | P1_HIGH | P2_MEDIUM
    estimated_size_low: str
    estimated_size_high: str
    decoded_size_estimate: str
    timeframe: str
    dune_table_names: List[str]
    bronze_target: str
    silver_target: str
    gold_feature_targets: List[str]
    neptune_graph_targets: List[str]
    model_consumers: List[str]
    status: str = "planned"  # planned | in_progress | completed | blocked
    last_extracted_at: Optional[str] = None
    coverage_percentage: float = 0.0
    blocking_reason: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION PRODUCT
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionProduct(BaseModel):
    """A named Dune extraction product with schema, quality, and lineage specs."""
    product_id: str
    product_name: str
    source_tables: List[str]
    query_template: Optional[str] = None
    datashare_table: Optional[str] = None
    bronze_schema: dict = Field(default_factory=dict)
    silver_schema: dict = Field(default_factory=dict)
    gold_schema: dict = Field(default_factory=dict)
    quality_checks: List[str] = Field(default_factory=list)
    freshness_checks: List[str] = Field(default_factory=list)
    dedupe_key: str
    lineage_fields: List[str] = Field(default_factory=list)
    model_consumers: List[str] = Field(default_factory=list)
    graph_consumers: List[str] = Field(default_factory=list)
    profile360_consumers: List[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# COST AND RATE-LIMIT PROFILES
# ═══════════════════════════════════════════════════════════════════════════

class CostProfile(BaseModel):
    """Cost metadata for an external provider."""
    cost_profile_id: str
    free_tier_available: bool = False
    free_tier_description: Optional[str] = None
    paid_tier_required_for_full_coverage: bool = True
    estimated_monthly_cost_low: Optional[str] = None
    estimated_monthly_cost_high: Optional[str] = None
    cost_driver: str  # per_request | per_row | per_query | enterprise_contract | free
    requires_enterprise_contract: bool = False
    requires_commercial_use_review: bool = True
    last_verified_at: Optional[str] = None
    verification_source: Optional[str] = None


class RateLimitProfile(BaseModel):
    """Rate-limit metadata for an external provider."""
    rate_limit_profile_id: str
    free_rate_limit: Optional[str] = None
    paid_rate_limit: Optional[str] = None
    burst_limit: Optional[str] = None
    daily_limit: Optional[str] = None
    monthly_limit: Optional[str] = None
    websocket_limit: Optional[str] = None
    pagination_limit: Optional[str] = None
    warehouse_cost_driver: Optional[str] = None
    requires_key: bool = True
    requires_oauth: bool = False
    last_verified_at: Optional[str] = None
    verification_source: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE MANIFEST
# ═══════════════════════════════════════════════════════════════════════════

class SourceManifest(BaseModel):
    """Lake source manifest for one provider source.

    Every provider source must have a manifest. The manifest defines:
    - Which lake layer the data lands in
    - Schema expectations for Bronze/Silver/Gold
    - Feature, model, graph, and Profile360 consumers
    - Provenance, license, and compliance requirements
    """
    source_manifest_id: str
    provider_name: str
    connector_id: str
    connector_class: ConnectorClass
    source_category: str
    lake_layer: str  # onchain_core | defi_protocol | cex_market_data | price_reference |
                     # prediction_markets | social_twitter | social_web3_native | social_web2 |
                     # nft_identity | derived_ml_features | sdk_live_behavioral | tenant_byod
    access_method: str  # api | warehouse_datashare | websocket | webhook | sdk
    bronze_table: str
    silver_schema: str
    gold_feature_outputs: List[str] = Field(default_factory=list)
    refresh_cadence: str  # realtime | 5m | 1h | 24h | weekly | on_demand
    historical_backfill_supported: bool = False
    realtime_supported: bool = False
    websocket_supported: bool = False
    warehouse_datashare_supported: bool = False
    query_execution_supported: bool = False
    data_coverage_summary: str = ""
    record_count_estimate: Optional[str] = None
    size_estimate_low: Optional[str] = None
    size_estimate_high: Optional[str] = None
    expected_growth_rate: Optional[str] = None
    source_priority_phase: PriorityPhase = PriorityPhase.NOT_SCHEDULED
    feature_consumers: List[str] = Field(default_factory=list)
    model_consumers: List[str] = Field(default_factory=list)
    graph_consumers: List[str] = Field(default_factory=list)
    profile360_consumers: List[str] = Field(default_factory=list)
    kyber_consumers: List[str] = Field(default_factory=list)
    provenance_required: bool = True
    license_required: bool = True
    terms_review_required: bool = True
    commercial_use_review_required: bool = True
    model_training_review_required: bool = True
    sensitivity_classification: str = "unclassified"
    risk_tier: RiskTier = RiskTier.MEDIUM
    compliance_status: str = "pending_review"


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER SOURCE ENTRY (Catalog Record)
# ═══════════════════════════════════════════════════════════════════════════

class ProviderSourceEntry(BaseModel):
    """Canonical catalog entry for one Olympus-owned external provider source.

    Default policy for all catalog entries:
    - connector_class = OLYMPUS_PROVIDER
    - lake_write_policy = OLYMPUS_BASELINE_ELIGIBLE
    - graph_write_policy = OLYMPUS_GRAPH_ALLOWED only after Silver/Gold validation
    - provenance_required = true
    - license_metadata_required = true
    - tenant_visible = false by default
    - kyber_visible = true
    """
    provider_id: str
    provider_name: str
    provider_category: str  # onchain | cex | prediction_market | social_web3 | social_web2 | protocol_specific
    source_category: str
    data_coverage_summary: str
    access_method: str  # api | warehouse_datashare | websocket | public_endpoint
    connector_class: ConnectorClass = ConnectorClass.OLYMPUS_PROVIDER
    connector_role: ConnectorRole = ConnectorRole.DATA_INGESTION
    data_flow_direction: DataFlowDirection = DataFlowDirection.INBOUND
    lake_write_policy: LakeWritePolicy = LakeWritePolicy.OLYMPUS_BASELINE_ELIGIBLE
    graph_write_policy: GraphWritePolicy = GraphWritePolicy.OLYMPUS_GRAPH_ALLOWED
    model_training_eligibility: ModelTrainingEligibility = ModelTrainingEligibility.COMPLIANCE_REVIEW_REQUIRED
    priority_phase: PriorityPhase = PriorityPhase.NOT_SCHEDULED
    cost_profile_id: str
    rate_limit_profile_id: str
    source_manifest_id: str
    license_status: str = "pending_review"  # public_api | open_license | terms_review_required | enterprise_contract
    terms_status: str = "pending_review"
    commercial_use_status: str = "pending_review"
    model_training_status: str = "pending_review"
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLDED
    risk_tier: RiskTier = RiskTier.MEDIUM
    provenance_required: bool = True
    license_metadata_required: bool = True
    terms_metadata_required: bool = True
    commercial_use_review_required: bool = True
    model_training_review_required: bool = True
    tenant_visible: bool = False  # Olympus provider internals not exposed to tenants by default
    kyber_visible: bool = True
    operator_owner: str = "olympus_labs"
    last_verified_at: Optional[str] = None
    compliance_status: str = "pending_review"
    ml_value_tags: List[str] = Field(default_factory=list)
    lake_layer_tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# ENRICHMENT LINEAGE
# ═══════════════════════════════════════════════════════════════════════════

class EnrichmentLineage(BaseModel):
    """Lineage record for every enriched artifact (Gold, Profile360, graph edges).

    Every Gold-tier record, intelligence output, feature row, graph edge derived
    from enrichment, and model-training record must carry a lineage_id referencing
    one of these records. This enables revocation, audit, and policy compliance.
    """
    lineage_id: str
    artifact_id: str
    artifact_type: str  # gold_record | profile360_output | graph_edge | feature_row | model_training_record
    tenant_id: Optional[str] = None
    source_event_ids: List[str] = Field(default_factory=list)
    source_connector_ids: List[str] = Field(default_factory=list)
    source_manifest_ids: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    input_hashes: List[str] = Field(default_factory=list)
    input_schema_versions: List[str] = Field(default_factory=list)
    normalization_version: str = "1.0"
    enrichment_version: str = "1.0"
    feature_set_version: Optional[str] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None
    graph_snapshot_version: Optional[str] = None
    confidence_score: float = 0.0
    freshness_score: float = 0.0
    computed_at: str
    valid_until: Optional[str] = None
    data_rights_grant_ids: List[str] = Field(default_factory=list)
    allowed_use_policy: str = "tenant_only"
    model_training_eligible: bool = False
    aggregate_eligible: bool = False
    commercial_reuse_eligible: bool = False
    revocation_dependencies: List[str] = Field(default_factory=list)
    created_by_service: str
    created_by_job_id: Optional[str] = None
    audit_event_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE SOURCE COVERAGE (Freshness Modes)
# ═══════════════════════════════════════════════════════════════════════════

class IntelligenceSourceCoverage(BaseModel):
    """Describes which data sources contributed to an intelligence output.

    Included in all intelligence API responses so tenants and operators can
    see whether results are baseline-only or enriched with tenant/SDK data.
    """
    source_mode: str  # baseline_only | baseline_plus_tenant_connector |
                      # baseline_plus_sdk_live | baseline_plus_tenant_connector_plus_sdk_live
    baseline_coverage: float = 0.0   # 0-1: fraction of signal from Olympus corpus
    connector_coverage: float = 0.0  # 0-1: fraction from tenant BYOD connectors
    sdk_live_coverage: float = 0.0   # 0-1: fraction from live SDK behavioral data
    identity_confidence: float = 0.0
    data_freshness_score: float = 0.0
    model_confidence: float = 0.0
    last_refreshed_at: Optional[str] = None
