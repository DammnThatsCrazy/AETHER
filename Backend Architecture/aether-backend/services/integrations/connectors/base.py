"""Inbound connector framework — contracts + base adapter.

A connector pulls/receives events from an external SaaS platform and normalizes
them into Aether's event envelope for graph enrichment. Adapters are
import-safe and disabled by default; provider calls are credential-gated in
every environment. Secrets are never stored in `ConnectorConfig.config` or
returned via the API — only a non-secret `secret_configured` signal is exposed.

Taxonomy extension: ConnectorClass, ConnectorRole, DataFlowDirection,
LakeWritePolicy, GraphWritePolicy, ModelTrainingEligibility, ImplementationStatus,
and PriorityPhase define the six-layer Aether data corpus model.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

ConnectorType = Literal[
    "slack", "webhook", "shopify", "stripe", "hubspot", "salesforce",
    "klaviyo", "segment", "posthog", "ga4", "jira", "linear", "zendesk", "intercom", "dune",
    # Branded communications providers (comms.* data outputs, ADR-C11 cohort)
    "sendgrid", "customerio", "mailchimp", "postmark", "iterable",
    # Olympus-owned provider connectors (Layer 1)
    "dune_api", "dune_datashare", "dune_sim",
    "defi_llama", "coingecko", "coinmarketcap",
    "polymarket_gamma", "polymarket_clob", "kalshi", "metaculus", "manifold_markets",
    "binance_public", "coinbase_exchange", "kraken", "okx", "bybit", "ccxt",
    "etherscan", "the_graph", "flipside_crypto", "covalent_goldrush",
    "alchemy", "moralis", "transpose", "solscan",
    "farcaster_neynar", "lens_protocol", "ens_public", "snapshot", "github_api",
    "twitter_x", "reddit", "telegram_bot", "discord_bot",
    "uniswap_subgraph", "aave_subgraph", "chainlink_price_feeds",
    "opensea", "reservoir", "token_terminal",
]

ConnectorCategory = Literal[
    "messaging", "webhook", "commerce", "billing", "crm", "marketing",
    "product_analytics", "project", "support",
    # Provider corpus categories
    "onchain", "cex", "prediction_market", "social_web3", "social_web2",
    "protocol_specific", "nft_identity", "price_reference",
]

ConnectorSyncStatus = Literal[
    "never_synced", "syncing", "healthy", "degraded", "failed", "disabled",
]


# ═══════════════════════════════════════════════════════════════════════════
# CONNECTOR TAXONOMY — Six-Layer Corpus Model
# ═══════════════════════════════════════════════════════════════════════════

class ConnectorClass(str, Enum):
    """Which data corpus layer this connector belongs to.

    Layer 1 — OLYMPUS_PROVIDER: Olympus-owned external APIs (Dune, DeFi Llama, etc.)
    Layer 2 — TENANT_BYOD_DATA: Tenant-supplied CRM/commerce/analytics connectors
    Layer 4 — BYOK_GATEWAY: Tenant-owned credential gateway (credential control only)
    Layer 5 — ACTION_NOTIFIER: Outbound action connectors (Slack, Jira actions)
    DUAL_ROLE: Connector with both ingest and action capabilities (modeled as separate capabilities)
    """
    OLYMPUS_PROVIDER = "olympus_provider"
    TENANT_BYOD_DATA = "tenant_byod_data"
    BYOK_GATEWAY = "byok_gateway"
    ACTION_NOTIFIER = "action_notifier"
    DUAL_ROLE = "dual_role"


class ConnectorRole(str, Enum):
    """Primary operational role of the connector."""
    DATA_INGESTION = "data_ingestion"
    ACTION_DELIVERY = "action_delivery"
    CREDENTIAL_GATEWAY = "credential_gateway"
    ENRICHMENT_PROVIDER = "enrichment_provider"
    WEBHOOK_RECEIVER = "webhook_receiver"
    SYNC_SOURCE = "sync_source"
    REALTIME_STREAM = "realtime_stream"
    BATCH_BACKFILL = "batch_backfill"
    QUERY_EXECUTION = "query_execution"
    WAREHOUSE_DATASHARE = "warehouse_datashare"
    DUAL_ROLE = "dual_role"


class DataFlowDirection(str, Enum):
    """Direction of data flow for this connector."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"
    NONE = "none"


class LakeWritePolicy(str, Enum):
    """Controls which lake layers this connector's data may write to.

    NEVER: ACTION_NOTIFIER connectors — no lake writes permitted.
    TENANT_ONLY: Tenant BYOD data writes to tenant-scoped lake only.
    OLYMPUS_BASELINE_ELIGIBLE: Olympus provider data eligible for baseline lake (provenance required).
    OLYMPUS_BASELINE_ALLOWED: Olympus provider data cleared for baseline after review.
    QUARANTINE_ONLY: Data lands in quarantine until provenance/license review passes.
    """
    NEVER = "never"
    TENANT_ONLY = "tenant_only"
    OLYMPUS_BASELINE_ELIGIBLE = "olympus_baseline_eligible"
    OLYMPUS_BASELINE_ALLOWED = "olympus_baseline_allowed"
    QUARANTINE_ONLY = "quarantine_only"


class GraphWritePolicy(str, Enum):
    """Controls which graph layers this connector's data may write edges/vertices to."""
    NONE = "none"
    TENANT_GRAPH_ONLY = "tenant_graph_only"
    TENANT_GRAPH_AND_AGGREGATE_ELIGIBLE = "tenant_graph_and_aggregate_eligible"
    OLYMPUS_GRAPH_ALLOWED = "olympus_graph_allowed"
    QUARANTINE_ONLY = "quarantine_only"


class ModelTrainingEligibility(str, Enum):
    """Controls whether data from this connector may be used for ML model training."""
    NEVER = "never"
    TENANT_ONLY = "tenant_only"
    AGGREGATE_ONLY = "aggregate_only"
    OLYMPUS_ALLOWED = "olympus_allowed"
    COMPLIANCE_REVIEW_REQUIRED = "compliance_review_required"


class ImplementationStatus(str, Enum):
    """Current implementation readiness of the connector.

    Do not claim a connector is live if it is only mocked or credential-gated.
    """
    SCAFFOLDED = "scaffolded"
    PRODUCTION_SHAPED = "production_shaped"
    CREDENTIAL_GATED = "credential_gated"
    PROVIDER_LIVE = "provider_live"
    WAREHOUSE_DATASHARE_READY = "warehouse_datashare_ready"
    STAGING_VALIDATION_REQUIRED = "staging_validation_required"
    DISABLED_COMPLIANCE_REVIEW = "disabled_compliance_review"
    DEPRECATED = "deprecated"


class PriorityPhase(str, Enum):
    """Implementation priority phase for provider corpus build-out."""
    PHASE_1_FOUNDATION = "phase_1_foundation"
    PHASE_2_ENRICHMENT = "phase_2_enrichment"
    PHASE_3_DEPTH = "phase_3_depth"
    NOT_SCHEDULED = "not_scheduled"


class RiskTier(str, Enum):
    """Risk classification for compliance and legal review gating."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RESTRICTED = "restricted"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectorConfig(BaseModel):
    """Tenant-scoped connector configuration. Never carries raw secrets."""
    config_id: str = Field(default_factory=lambda: f"conn_{uuid.uuid4().hex[:12]}")
    tenant_id: str
    connector_type: ConnectorType
    name: str = ""
    enabled: bool = False  # disabled by default
    config: dict[str, Any] = Field(default_factory=dict)  # non-secret settings only
    secret_configured: bool = False  # whether a secret exists in the vault (no value)
    secret_ref: Optional[str] = None  # vault reference, never the secret itself
    last_synced_at: Optional[str] = None
    sync_status: ConnectorSyncStatus = "never_synced"
    error_count: int = 0
    last_error_at: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ConnectorDescriptor(BaseModel):
    connector_type: ConnectorType
    label: str
    category: ConnectorCategory
    description: str
    supports_webhook: bool
    supports_pull: bool
    requires_secret: bool
    premium: bool
    ingest_event_types: list[str]
    docs_slug: str
    # Taxonomy fields (populated for all connectors; defaults preserve backward compat)
    connector_class: ConnectorClass = ConnectorClass.TENANT_BYOD_DATA
    connector_role: ConnectorRole = ConnectorRole.DATA_INGESTION
    data_flow_direction: DataFlowDirection = DataFlowDirection.INBOUND
    lake_write_policy: LakeWritePolicy = LakeWritePolicy.TENANT_ONLY
    graph_write_policy: GraphWritePolicy = GraphWritePolicy.TENANT_GRAPH_ONLY
    model_training_eligibility: ModelTrainingEligibility = ModelTrainingEligibility.NEVER
    implementation_status: ImplementationStatus = ImplementationStatus.CREDENTIAL_GATED
    priority_phase: PriorityPhase = PriorityPhase.NOT_SCHEDULED
    risk_tier: RiskTier = RiskTier.LOW
    # Capability flags
    supports_byok: bool = False
    supports_oauth: bool = False
    supports_realtime_stream: bool = False
    supports_historical_backfill: bool = False
    supports_warehouse_datashare: bool = False
    supports_query_execution: bool = False
    supports_push_action: bool = False
    # Sync/account capability flags projected onto the canonical ProviderManifest.
    supports_reconciliation: bool = False
    supports_account_discovery: bool = False
    supports_account_selection: bool = False
    # Manifest enrichment — richer capability surface for the derived
    # ProviderManifest. Empty lists fall back to the connector-generic defaults
    # in shared.integration_contracts.catalog (single source of truth stays the
    # connector class; the catalog is a pure projection).
    manifest_data_outputs: List[str] = Field(default_factory=list)
    manifest_product_destinations: List[str] = Field(default_factory=list)
    # Governance requirements
    requires_contract_grant: bool = False
    requires_user_consent: bool = False
    requires_admin_install: bool = False
    requires_tenant_admin_approval: bool = False
    requires_olympus_operator_approval: bool = False
    provenance_required: bool = False
    license_metadata_required: bool = False
    # Visibility
    tenant_visible: bool = True
    kyber_visible: bool = True
    kyber_visibility_level: str = "full"
    # Metadata
    ml_value_tags: List[str] = Field(default_factory=list)
    lake_layer_tags: List[str] = Field(default_factory=list)
    feature_flag: Optional[str] = None
    default_enabled: bool = False


class ConnectorCapability(BaseModel):
    """Models one capability of a dual-role connector separately.

    Dual-role connectors (e.g. Jira) must declare separate capabilities for
    ingest vs. action so policies, grants, and health states remain isolated.
    """
    capability_id: str
    connector_type: ConnectorType
    capability_class: ConnectorClass
    capability_role: ConnectorRole
    data_flow_direction: DataFlowDirection
    lake_write_policy: LakeWritePolicy
    graph_write_policy: GraphWritePolicy
    model_training_eligibility: ModelTrainingEligibility
    requires_separate_grant: bool = True


class ConnectionTestResult(BaseModel):
    connector_type: ConnectorType
    ok: bool
    status: str  # "ok" | "not_configured" | "disabled" | "error"
    detail: str = ""
    checked_at: str = Field(default_factory=now_iso)


class NormalizedEvent(BaseModel):
    """Connector event normalized toward the SDK ingestion envelope."""
    event_type: str
    source: str  # connector_type
    external_id: Optional[str] = None
    occurred_at: str = Field(default_factory=now_iso)
    properties: dict[str, Any] = Field(default_factory=dict)


class SyncResult(BaseModel):
    connector_type: ConnectorType
    status: ConnectorSyncStatus
    events_ingested: int = 0
    events: list[NormalizedEvent] = Field(default_factory=list)
    detail: str = ""
    synced_at: str = Field(default_factory=now_iso)


class BaseConnector:
    """Base inbound connector. Subclasses set descriptors + mapping; the service
    layer owns metering/audit/reliability/data-quality side effects."""

    connector_type: ConnectorType = "webhook"
    label: str = "Base connector"
    category: ConnectorCategory = "webhook"
    description: str = "Base inbound connector"
    supports_webhook: bool = True
    supports_pull: bool = False
    requires_secret: bool = True
    premium: bool = False
    ingest_event_types: tuple[str, ...] = ()
    docs_slug: str = "operations/connectors"
    # Taxonomy defaults — subclasses override as needed
    connector_class: ConnectorClass = ConnectorClass.TENANT_BYOD_DATA
    connector_role: ConnectorRole = ConnectorRole.DATA_INGESTION
    data_flow_direction: DataFlowDirection = DataFlowDirection.INBOUND
    lake_write_policy: LakeWritePolicy = LakeWritePolicy.TENANT_ONLY
    graph_write_policy: GraphWritePolicy = GraphWritePolicy.TENANT_GRAPH_ONLY
    model_training_eligibility: ModelTrainingEligibility = ModelTrainingEligibility.NEVER
    implementation_status: ImplementationStatus = ImplementationStatus.CREDENTIAL_GATED
    priority_phase: PriorityPhase = PriorityPhase.NOT_SCHEDULED
    risk_tier: RiskTier = RiskTier.LOW
    supports_byok: bool = False
    supports_oauth: bool = False
    supports_realtime_stream: bool = False
    supports_historical_backfill: bool = False
    supports_warehouse_datashare: bool = False
    supports_query_execution: bool = False
    supports_push_action: bool = False
    supports_reconciliation: bool = False
    supports_account_discovery: bool = False
    supports_account_selection: bool = False
    # Providers that GET-probe the webhook URL on setup (Mailchimp) and expect a
    # 200. The probe verifies only that the URL is reachable and resolves to a
    # real endpoint; no signature is involved.
    supports_get_validation: bool = False
    manifest_data_outputs: tuple[str, ...] = ()
    manifest_product_destinations: tuple[str, ...] = ()
    # Native webhook signature scheme, if any (see signature_verify.py schemes).
    # ``None`` means the adapter verifies through Aether's generic timestamped
    # HMAC. Comms providers declare their provider-native scheme here (the
    # manifest's ``_NATIVE_WEBHOOK_SCHEMES`` mirrors it for provider-scoped
    # manifests). ``endpoint_secret`` marks no-signature providers (Mailchimp,
    # Postmark) whose durable server-controlled endpoint id is the credential.
    signature_scheme: Optional[str] = None
    # Credential slot names this adapter needs (read by comms conformance to
    # state honest required_credentials; comms secrets resolve through the
    # connector vault, not the payment-rail slot registry).
    required_credentials: tuple[str, ...] = ()
    # Pull-API protocol facts read by the comms conformance ``build_request``
    # hook to construct an honest synthetic probe request. The real pull
    # requests are built in the adapter (e.g. ``_get``); declaring the auth
    # header name and base URL here lets conformance mirror them without
    # branching on provider name (ADR-C11). ``None`` auth header means the
    # standard ``Authorization: Bearer <key>`` form.
    pull_auth_header: Optional[str] = None
    pull_api_base: Optional[str] = None
    requires_contract_grant: bool = False
    requires_user_consent: bool = False
    requires_admin_install: bool = False
    requires_tenant_admin_approval: bool = False
    requires_olympus_operator_approval: bool = False
    provenance_required: bool = False
    license_metadata_required: bool = False
    tenant_visible: bool = True
    kyber_visible: bool = True
    kyber_visibility_level: str = "full"
    ml_value_tags: tuple[str, ...] = ()
    lake_layer_tags: tuple[str, ...] = ()
    feature_flag: Optional[str] = None
    default_enabled: bool = False

    def descriptor(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=self.connector_type,
            label=self.label,
            category=self.category,
            description=self.description,
            supports_webhook=self.supports_webhook,
            supports_pull=self.supports_pull,
            requires_secret=self.requires_secret,
            premium=self.premium,
            ingest_event_types=list(self.ingest_event_types),
            docs_slug=self.docs_slug,
            connector_class=self.connector_class,
            connector_role=self.connector_role,
            data_flow_direction=self.data_flow_direction,
            lake_write_policy=self.lake_write_policy,
            graph_write_policy=self.graph_write_policy,
            model_training_eligibility=self.model_training_eligibility,
            implementation_status=self.implementation_status,
            priority_phase=self.priority_phase,
            risk_tier=self.risk_tier,
            supports_byok=self.supports_byok,
            supports_oauth=self.supports_oauth,
            supports_realtime_stream=self.supports_realtime_stream,
            supports_historical_backfill=self.supports_historical_backfill,
            supports_warehouse_datashare=self.supports_warehouse_datashare,
            supports_query_execution=self.supports_query_execution,
            supports_push_action=self.supports_push_action,
            supports_reconciliation=self.supports_reconciliation,
            supports_account_discovery=self.supports_account_discovery,
            supports_account_selection=self.supports_account_selection,
            manifest_data_outputs=list(self.manifest_data_outputs),
            manifest_product_destinations=list(self.manifest_product_destinations),
            requires_contract_grant=self.requires_contract_grant,
            requires_user_consent=self.requires_user_consent,
            requires_admin_install=self.requires_admin_install,
            requires_tenant_admin_approval=self.requires_tenant_admin_approval,
            requires_olympus_operator_approval=self.requires_olympus_operator_approval,
            provenance_required=self.provenance_required,
            license_metadata_required=self.license_metadata_required,
            tenant_visible=self.tenant_visible,
            kyber_visible=self.kyber_visible,
            kyber_visibility_level=self.kyber_visibility_level,
            ml_value_tags=list(self.ml_value_tags),
            lake_layer_tags=list(self.lake_layer_tags),
            feature_flag=self.feature_flag,
            default_enabled=self.default_enabled,
        )

    def validate_config(self, config: ConnectorConfig) -> None:
        if config.connector_type != self.connector_type:
            raise ValueError("connector_type mismatch")
        # Secrets must never be placed in the non-secret config blob.
        for key in config.config:
            if any(s in key.lower() for s in ("secret", "token", "api_key", "password", "credential")):
                raise ValueError(f"secret-like key {key!r} must not be stored in config; use the vault")

    async def test_connection(
        self, config: ConnectorConfig, secret: Optional[str] = None
    ) -> ConnectionTestResult:
        """Fail closed unless a subclass performs a real provider check."""
        if not config.enabled:
            return ConnectionTestResult(connector_type=self.connector_type, ok=False, status="disabled",
                                        detail="connector disabled")
        if self.requires_secret and not config.secret_configured:
            return ConnectionTestResult(connector_type=self.connector_type, ok=False, status="not_configured",
                                        detail="missing credential (configure secret in the vault)")
        if self.requires_secret and not secret:
            return ConnectionTestResult(
                connector_type=self.connector_type,
                ok=False,
                status="not_configured",
                detail="configured credential could not be resolved",
            )
        return ConnectionTestResult(
            connector_type=self.connector_type,
            ok=True,
            status="ready",
            detail="credential resolved; provider check required",
        )

    async def pull(
        self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None
    ) -> list[NormalizedEvent]:
        """Subclasses must implement a provider-backed pull."""
        raise NotImplementedError(
            f"{self.connector_type} does not implement a provider-backed pull"
        )

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified inbound webhook payload to normalized events.

        Default maps the whole payload to one event; adapters refine per provider.
        """
        event_type = str(payload.get("type") or payload.get("event") or f"{self.connector_type}.event")
        return [NormalizedEvent(
            event_type=event_type,
            source=self.connector_type,
            external_id=str(payload.get("id")) if payload.get("id") is not None else None,
            properties={k: v for k, v in payload.items() if k not in ("id",)},
        )]
