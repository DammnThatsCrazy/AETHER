"""
Aether Shared — @aether/graph
Neptune/Neo4j query builders, graph traversal helpers, vertex/edge factories.
Used by: Identity, Analytics, Agent services.

Backend selection:
- AETHER_ENV=local → in-memory graph (no Neptune required)
- AETHER_ENV=staging/production → Neptune via websocket (gremlinpython)
  Set NEPTUNE_ENDPOINT env var to the Neptune cluster endpoint.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.graph")

# Optional gremlinpython import
try:
    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal
    from gremlin_python.process.graph_traversal import __
    from gremlin_python.process.traversal import Cardinality, T
    GREMLIN_AVAILABLE = True
except ImportError:
    GREMLIN_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
# VERTEX & EDGE TYPES (from spec Section 4)
# ═══════════════════════════════════════════════════════════════════════════

class VertexType:
    USER = "User"
    SESSION = "Session"
    PAGE_VIEW = "PageView"
    EVENT = "Event"
    DEVICE = "Device"
    COMPANY = "Company"
    CAMPAIGN = "Campaign"
    EXTERNAL_DATA = "ExternalData"

    # Identity Resolution
    DEVICE_FINGERPRINT = "DeviceFingerprint"
    IP_ADDRESS = "IPAddress"
    LOCATION = "Location"
    EMAIL = "Email"
    PHONE = "Phone"
    WALLET = "Wallet"
    IDENTITY_CLUSTER = "IdentityCluster"

    # Intelligence Graph — Actor nodes
    AGENT = "Agent"
    SERVICE = "Service"
    CONTRACT = "Contract"
    PROTOCOL = "Protocol"

    # ── Profile 360 — Multi-Entity Identity (additive) ───────────────────
    # Generic abstractions used by the Profile 360 layer. Existing services
    # may keep using USER / AGENT / LEGAL_ENTITY directly; the new
    # services/entities, services/delegation, services/flows layers prefer
    # ENTITY / ORGANIZATION / ASSET / DELEGATION for cross-type queries.
    ENTITY = "Entity"
    ORGANIZATION = "Organization"
    ASSET = "Asset"
    DELEGATION = "Delegation"

    # Intelligence Graph — Record nodes
    PAYMENT = "Payment"
    ACTION_RECORD = "ActionRecord"
    RECOMMENDATION = "Recommendation"
    DECISION_RECORD = "DecisionRecord"
    OUTCOME_OBSERVATION = "OutcomeObservation"
    PLAYBOOK_RUN = "PlaybookRun"

    # Web3 Coverage — Registry-native graph objects
    CHAIN = "Chain"
    TOKEN = "Token"
    TOKEN_POSITION = "TokenPosition"
    POOL = "Pool"
    VAULT = "Vault"
    MARKET = "Market"
    STRATEGY = "Strategy"
    APP = "App"
    FRONTEND_DOMAIN = "FrontendDomain"
    GOVERNANCE_SPACE = "GovernanceSpace"
    GOVERNANCE_PROPOSAL = "GovernanceProposal"
    BRIDGE_ROUTE = "BridgeRoute"
    NFT_COLLECTION = "NftCollection"
    DEPLOYER_ENTITY = "DeployerEntity"
    MARKET_VENUE = "MarketVenue"
    CONTRACT_SYSTEM = "ContractSystem"
    PROTOCOL_VERSION = "ProtocolVersion"
    UNKNOWN_CONTRACT = "UnknownContract"

    # Cross-Domain — TradFi / Business / Web2 graph objects
    INSTITUTION = "Institution"
    FINANCIAL_ACCOUNT = "FinancialAccount"
    INSTRUMENT = "Instrument"
    ORDER = "Order"
    EXECUTION = "Execution"
    POSITION = "Position"
    BALANCE_SNAPSHOT = "BalanceSnapshot"
    CASH_MOVEMENT = "CashMovement"
    COMPLIANCE_ACTION = "ComplianceAction"
    BUSINESS_EVENT = "BusinessEvent"
    HOUSEHOLD = "Household"
    LEGAL_ENTITY = "LegalEntity"
    FUND_ENTITY = "FundEntity"
    DESK = "Desk"
    SECTOR = "Sector"
    CORPORATE_ACTION = "CorporateAction"

    # ── Economic Graph Layer — Agent economies (additive) ──────────────
    # These nodes model autonomous agents as economic actors without
    # replacing the existing commerce control-plane vertices below.
    PAYMENT_INTENT = "PaymentIntent"
    SETTLEMENT_EVENT = "SettlementEvent"
    ECONOMIC_RESOURCE = "EconomicResource"
    AGENT_ECONOMIC_IDENTITY = "AgentEconomicIdentity"
    AGENT_PROFILE360 = "AgentProfile360"

    # ── Intelligence & Computed ────────────────────────────────────────
    TIER_GROUP = "TierGroup"                           # one per tier per tenant
    BEHAVIORAL_SIGNAL_NODE = "BehavioralSignalNode"   # per-signal instance
    SOCIAL_PROFILE_NODE = "SocialProfileNode"         # aggregated cross-platform identity
    LOCATION_SUMMARY = "LocationSummary"              # city-level aggregated access

    # ── Unified Entity Categories (Web2 + Web3, domain-agnostic) ─────
    # These replace domain-specific names. Aliases below preserve backward compat.
    GOVERNANCE_ORG = "GovernanceOrg"      # DAO, NGO, cooperative, government body
    BRAND = "Brand"                       # company, product brand, SaaS, startup
    MARKETPLACE = "Marketplace"           # e-commerce platform, app store, gig platform
    MEDIA_ENTITY = "MediaEntity"          # publisher, content creator, influencer
    YIELD_PLATFORM = "YieldPlatform"      # staking protocol, savings account, robo-advisor

    # ── Backward Compat Aliases (deprecated — prefer unified kinds above) ──
    DAO = "DAO"                           # → GOVERNANCE_ORG
    DEX = "DEX"                           # → EXCHANGE
    STAKING_PLATFORM = "StakingPlatform"  # → YIELD_PLATFORM
    EXCHANGE = "Exchange"                 # unified (covers DEX + CEX + stock exchange)

    # ── External Integration ──────────────────────────────────────────
    PLAID_ACCOUNT = "PlaidAccount"
    CREDIT_PROFILE = "CreditProfile"
    TRADFI_POSITION = "TradFiPosition"

    # ── Campaign Intelligence ─────────────────────────────────────────
    RETARGET_RECOMMENDATION = "RetargetRecommendation"
    AD_CAMPAIGN = "AdCampaign"

    # ── Agentic Commerce — Control Plane vertices ──────────────────────
    PAYMENT_REQUIREMENT = "PaymentRequirement"
    PAYMENT_AUTHORIZATION = "PaymentAuthorization"
    PAYMENT_RECEIPT = "PaymentReceipt"
    SETTLEMENT = "Settlement"
    ENTITLEMENT = "Entitlement"
    ACCESS_GRANT = "AccessGrant"
    FACILITATOR = "Facilitator"
    PRICE_POLICY = "PricePolicy"
    BUDGET_POLICY = "BudgetPolicy"
    TREASURY = "Treasury"
    STABLECOIN_ASSET = "StablecoinAsset"
    SERVICE_PLAN = "ServicePlan"
    PAYMENT_ROUTE = "PaymentRoute"
    FULFILLMENT = "Fulfillment"
    POLICY_DECISION = "PolicyDecision"
    APPROVAL_REQUEST = "ApprovalRequest"
    APPROVAL_DECISION = "ApprovalDecision"
    PROTECTED_RESOURCE = "ProtectedResource"


class EdgeType:
    HAS_SESSION = "HAS_SESSION"
    VIEWED_PAGE = "VIEWED_PAGE"
    TRIGGERED_EVENT = "TRIGGERED_EVENT"
    USED_DEVICE = "USED_DEVICE"
    BELONGS_TO = "BELONGS_TO"
    ATTRIBUTED_TO = "ATTRIBUTED_TO"
    RESOLVED_AS = "RESOLVED_AS"
    ENRICHED_BY = "ENRICHED_BY"

    # Identity Resolution
    HAS_FINGERPRINT = "HAS_FINGERPRINT"
    SEEN_FROM_IP = "SEEN_FROM_IP"
    LOCATED_IN = "LOCATED_IN"
    HAS_EMAIL = "HAS_EMAIL"
    HAS_PHONE = "HAS_PHONE"
    OWNS_WALLET = "OWNS_WALLET"
    MEMBER_OF_CLUSTER = "MEMBER_OF_CLUSTER"
    SIMILAR_TO = "SIMILAR_TO"
    IP_MAPS_TO = "IP_MAPS_TO"

    # Intelligence Graph — Human-to-Agent (H2A)
    LAUNCHED_BY = "LAUNCHED_BY"           # Agent → User who created it
    DELEGATES = "DELEGATES"               # User → Agent (task delegation)
    INTERACTS_WITH = "INTERACTS_WITH"     # User → Protocol

    # ── Profile 360 — Generic relationship edges (additive) ──────────────
    # Time-aware, metadata-bearing edges used by Profile 360. Properties
    # carried on every instance: tenant_id, valid_from, valid_to, scope_hash.
    OWNS = "OWNS"                         # Entity → Wallet|Agent|Asset (generic)
    MEMBER_OF = "MEMBER_OF"               # Entity → Organization (generic)
    GRANTED_BY = "GRANTED_BY"             # Delegation → Entity (grantor)
    GRANTED_TO = "GRANTED_TO"             # Delegation → Entity (grantee)
    EXECUTED = "EXECUTED"                 # Agent → AgentExecution
    TRANSFERRED = "TRANSFERRED"           # Entity → Entity (financial flow, with asset_id)

    # Intelligence Graph — Economic edges
    PAYS = "PAYS"                         # Agent/User → Agent/Service
    CONSUMES = "CONSUMES"                 # Agent → Service (API consumption)
    HIRED = "HIRED"                       # Agent → Agent (task hiring)

    # Intelligence Graph — Protocol / On-Chain (A2A)
    DEPLOYED = "DEPLOYED"                 # Agent → Contract
    CALLED = "CALLED"                     # Agent/User → Contract
    COMPOSED_WITH = "COMPOSED_WITH"       # Contract → Contract
    UPGRADED = "UPGRADED"                 # Contract → Contract (proxy upgrade)
    GOVERNED_BY = "GOVERNED_BY"           # Protocol → Contract (governance)
    DEPENDS_ON = "DEPENDS_ON"             # Agent → Agent (dependency)

    # Intelligence Graph — Agent-to-Human (A2H)
    NOTIFIES = "NOTIFIES"                 # Agent → User (alerts, status updates)
    RECOMMENDS = "RECOMMENDS"             # Agent → User (agent-initiated suggestions)
    DELIVERS_TO = "DELIVERS_TO"           # Agent → User (task result delivery)
    ESCALATES_TO = "ESCALATES_TO"         # Agent → User (human-in-the-loop escalation)

    # Intelligence Graph — Action tracking
    PERFORMED_ACTION = "PERFORMED_ACTION"  # Agent → ActionRecord

    # Decision & Outcome Intelligence OODA loop
    HAS_RECOMMENDATION = "HAS_RECOMMENDATION"
    SUPPORTED_BY = "SUPPORTED_BY"
    SELECTED_BY = "SELECTED_BY"
    EXECUTED_AS = "EXECUTED_AS"
    PRODUCED = "PRODUCED"
    UPDATES_CONFIDENCE_FOR = "UPDATES_CONFIDENCE_FOR"

    # ── Web3 Coverage — Wallet ↔ Entity edges ──────────────────────────
    USES_PROTOCOL = "USES_PROTOCOL"           # Wallet → Protocol
    USES_APP = "USES_APP"                     # Wallet → App
    TOUCHES_DOMAIN = "TOUCHES_DOMAIN"         # Wallet → FrontendDomain
    HOLDS_TOKEN = "HOLDS_TOKEN"               # Wallet → Token
    BRIDGES_VIA = "BRIDGES_VIA"               # Wallet → BridgeRoute
    PARTICIPATES_IN = "PARTICIPATES_IN"       # Wallet → GovernanceSpace
    VOTES_ON = "VOTES_ON"                     # Wallet → GovernanceProposal
    DELEGATES_TO = "DELEGATES_TO"             # Wallet → Wallet (governance delegation)
    LINKED_TO_SOCIAL = "LINKED_TO_SOCIAL"     # Wallet → User (social identity)
    TRADED_ON = "TRADED_ON"                   # Wallet → MarketVenue
    EXPOSED_TO = "EXPOSED_TO"                 # Profile/Wallet → Protocol/Token/Asset

    # ── Web3 Coverage — Contract/Protocol topology ─────────────────────
    INSTANCE_OF = "INSTANCE_OF"               # Contract → ContractSystem
    PART_OF_SYSTEM = "PART_OF_SYSTEM"         # ContractSystem → Protocol
    SUCCESSOR_OF = "SUCCESSOR_OF"             # ProtocolVersion → ProtocolVersion
    MIGRATED_TO = "MIGRATED_TO"               # Contract → Contract (migration)
    CONTROLS = "CONTROLS"                     # DeployerEntity → Contract
    DEPLOYED_ON = "DEPLOYED_ON"               # Protocol/Contract → Chain

    # ── Web3 Coverage — App/Frontend attribution ───────────────────────
    FRONTS_PROTOCOL = "FRONTS_PROTOCOL"       # App/FrontendDomain → Protocol
    ASSOCIATED_WITH = "ASSOCIATED_WITH"       # FrontendDomain → ContractSystem
    SERVED_BY = "SERVED_BY"                   # Protocol → FrontendDomain

    # ── Web3 Coverage — Market/Token edges ─────────────────────────────
    TOKEN_OF = "TOKEN_OF"                     # Token → Protocol
    TRADED_ON_VENUE = "TRADED_ON_VENUE"       # Token → MarketVenue
    POOL_FOR = "POOL_FOR"                     # Pool → Token (pair tokens)
    GOVERNED_BY_SPACE = "GOVERNED_BY_SPACE"   # Protocol → GovernanceSpace

    # ── Web3 Coverage — Classification edges ───────────────────────────
    LATER_CLASSIFIED_AS = "LATER_CLASSIFIED_AS"  # UnknownContract → Protocol/ContractSystem

    # ── Cross-Domain — Entity ↔ Account edges ─────────────────────────
    OWNS_ACCOUNT = "OWNS_ACCOUNT"             # Entity → FinancialAccount (with OwnershipRole)
    BENEFICIAL_OF = "BENEFICIAL_OF"           # Entity → FinancialAccount
    AUTHORIZED_ON = "AUTHORIZED_ON"           # Entity → FinancialAccount
    ADVISES = "ADVISES"                       # Entity → Entity (advisor/broker relationship)
    PARENT_OF = "PARENT_OF"                   # LegalEntity → LegalEntity (corporate hierarchy)
    MEMBER_OF_HOUSEHOLD = "MEMBER_OF_HOUSEHOLD"  # Entity → Household

    # ── Cross-Domain — Account ↔ Instrument edges ─────────────────────
    HOLDS_POSITION = "HOLDS_POSITION"         # Account → Instrument (position)
    PLACED_ORDER = "PLACED_ORDER"             # Account → Order
    ORDER_FOR = "ORDER_FOR"                   # Order → Instrument
    EXECUTED_AS = "EXECUTED_AS"               # Order → Execution
    TRADED_AT_VENUE = "TRADED_AT_VENUE"       # Execution → MarketVenue
    CASH_FLOW = "CASH_FLOW"                   # Account → Account (cash movement)
    FUNDED_BY = "FUNDED_BY"                   # Account → Account (funding source)

    # ── Cross-Domain — Institution/Business edges ──────────────────────
    SERVICES_ACCOUNT = "SERVICES_ACCOUNT"     # Institution → FinancialAccount
    ISSUES = "ISSUES"                         # Institution/Issuer → Instrument
    CUSTODIES = "CUSTODIES"                   # Institution → FinancialAccount/Holdings
    MARKETS_TO = "MARKETS_TO"                 # Business → Profile/Cohort (CRM/campaign)
    OPERATES = "OPERATES"                     # Business → App/FrontendDomain
    OFFERS_PRODUCT = "OFFERS_PRODUCT"         # Institution → Instrument/Product

    # ── Cross-Domain — Instrument topology ─────────────────────────────
    ISSUED_BY = "ISSUED_BY"                   # Instrument → Institution/Issuer
    IN_SECTOR = "IN_SECTOR"                   # Instrument → Sector
    UNDERLYING_OF = "UNDERLYING_OF"           # Instrument → Instrument (derivatives)
    TOKENIZED_AS = "TOKENIZED_AS"             # Instrument → Token (RWA bridge)
    CORRELATED_WITH = "CORRELATED_WITH"       # Instrument → Instrument

    # ── Cross-Domain — Compliance/Risk edges ───────────────────────────
    RESTRICTED_ON = "RESTRICTED_ON"           # Entity/Account → Instrument/Venue
    COMPLIANCE_ACTED_ON = "COMPLIANCE_ACTED_ON"  # ComplianceAction → Entity/Account
    KYC_FOR = "KYC_FOR"                       # KYC record → Entity

    # ── Cross-Domain — Behavioral / Pre-trade edges ────────────────────
    RESEARCHED = "RESEARCHED"                 # Entity → Instrument (quote/chart/news)
    WATCHLISTED = "WATCHLISTED"               # Entity → Instrument
    INQUIRED_ABOUT = "INQUIRED_ABOUT"         # Entity → Product/Instrument
    VISITED = "VISITED"                       # Entity → App/FrontendDomain

    # ── Cross-Domain — Identity fusion ─────────────────────────────────
    OVERLAPS_WITH = "OVERLAPS_WITH"           # Profile → Profile (cross-domain identity)
    LINKED_VIA = "LINKED_VIA"                 # Entity → Entity (with link_signal property)

    # ── Economic Graph Layer — Agent economies (additive) ──────────────
    PAYS_FOR = "PAYS_FOR"                         # Agent → EconomicResource|PaymentIntent
    PURCHASES_EXECUTION_FROM = "PURCHASES_EXECUTION_FROM"  # Agent → Provider/Agent/Service
    SETTLED_VIA = "SETTLED_VIA"                   # PaymentIntent/SettlementEvent → Facilitator
    REQUESTED_QUOTE_FROM = "REQUESTED_QUOTE_FROM"  # PaymentIntent → Provider/Facilitator
    ABANDONED_DUE_TO_COST = "ABANDONED_DUE_TO_COST"  # Agent/PaymentIntent → EconomicResource
    RELIES_ON_PROVIDER = "RELIES_ON_PROVIDER"     # Agent/Profile → Service/Provider
    USES_APPLICATION = "USES_APPLICATION"         # Agent/Profile → App/Application
    USES_EMAIL_SERVICE = "USES_EMAIL_SERVICE"     # Agent/Profile → Service/Email domain
    SPECIALIZES_IN = "SPECIALIZES_IN"             # Agent/Profile → Capability/EconomicResource
    COMMUNICATES_WITH = "COMMUNICATES_WITH"       # Agent/Profile → Entity/Service/Agent
    EXECUTED_ON = "EXECUTED_ON"                   # Execution/Action → Provider/Resource
    ECONOMICALLY_IDENTIFIED_AS = "ECONOMICALLY_IDENTIFIED_AS"  # Agent → AgentEconomicIdentity
    PROFILED_AS = "PROFILED_AS"                   # Agent/Entity → AgentProfile360
    QUOTED_AS = "QUOTED_AS"                       # PaymentIntent → PaymentRequirement/Quote
    EVALUATED_AS = "EVALUATED_AS"                 # PaymentIntent → PolicyDecision
    SETTLED_AS = "SETTLED_AS"                     # PaymentIntent → SettlementEvent
    RESULTED_IN_EXECUTION = "RESULTED_IN_EXECUTION"  # SettlementEvent → Execution/ActionRecord
    RESULTED_IN_OUTCOME = "RESULTED_IN_OUTCOME"   # Execution/ActionRecord → Event/Fulfillment

    # ── Agentic Commerce — Control Plane edges ─────────────────────────
    REQUIRES_PAYMENT = "REQUIRES_PAYMENT"         # ProtectedResource → PaymentRequirement
    OFFERS_PAYMENT_OPTION = "OFFERS_PAYMENT_OPTION"  # PaymentRequirement → StablecoinAsset
    AUTHORIZED_BY = "AUTHORIZED_BY"               # PaymentRequirement → PaymentAuthorization
    VERIFIED_BY = "VERIFIED_BY"                   # PaymentAuthorization → Facilitator
    SETTLED_BY = "SETTLED_BY"                     # PaymentReceipt → Settlement
    GRANTS_ACCESS_TO = "GRANTS_ACCESS_TO"         # Entitlement → ProtectedResource
    FULFILLED_BY = "FULFILLED_BY"                 # AccessGrant → Fulfillment
    PRICES_IN = "PRICES_IN"                       # ServicePlan → StablecoinAsset
    ACCEPTS_ASSET = "ACCEPTS_ASSET"               # ProtectedResource → StablecoinAsset
    PREFERS_NETWORK = "PREFERS_NETWORK"           # Treasury → Chain
    CONSTRAINED_BY = "CONSTRAINED_BY"             # Agent/User → BudgetPolicy
    SUBSCRIBES_TO = "SUBSCRIBES_TO"               # User/Agent → ServicePlan
    REUSES_ENTITLEMENT = "REUSES_ENTITLEMENT"     # Agent → Entitlement
    RETRIED_AS = "RETRIED_AS"                     # Settlement → Settlement
    ESCALATES_PAYMENT_TO = "ESCALATES_PAYMENT_TO"  # ApprovalRequest → User
    GUARDED_BY_POLICY = "GUARDED_BY_POLICY"       # ProtectedResource → PricePolicy/BudgetPolicy
    ROUTES_VIA = "ROUTES_VIA"                     # PaymentAuthorization → PaymentRoute
    APPROVED_BY = "APPROVED_BY"                   # ApprovalDecision → User
    REJECTED_BY = "REJECTED_BY"                   # ApprovalDecision → User
    REQUESTS_APPROVAL_FROM = "REQUESTS_APPROVAL_FROM"  # ApprovalRequest → User
    GOVERNED_BY_POLICY = "GOVERNED_BY_POLICY"     # Tenant/Agent → PolicyDecision
    FUNDED_FROM_TREASURY = "FUNDED_FROM_TREASURY"  # PaymentAuthorization → Treasury

    # ── Tier ──────────────────────────────────────────────────────────
    IN_TIER_GROUP = "IN_TIER_GROUP"                  # Entity → TierGroup

    # ── Behavioral ────────────────────────────────────────────────────
    HAS_BEHAVIORAL_SIGNAL = "HAS_BEHAVIORAL_SIGNAL"  # Entity → BehavioralSignalNode

    # ── Social ────────────────────────────────────────────────────────
    HAS_SOCIAL_PROFILE = "HAS_SOCIAL_PROFILE"        # Entity → SocialProfileNode
    FOLLOWS_SOCIAL = "FOLLOWS_SOCIAL"                # Entity → Entity (cross-platform follow)

    # ── Location ──────────────────────────────────────────────────────
    PRIMARY_LOCATION = "PRIMARY_LOCATION"            # Entity → LocationSummary (>50% sessions)
    SECONDARY_LOCATION = "SECONDARY_LOCATION"        # Entity → LocationSummary (5-50%)
    ACCESSED_FROM = "ACCESSED_FROM"                  # Entity → LocationSummary (generic)

    # ── Unified entity specialization (domain-agnostic) ─────────────────
    IS_GOVERNANCE_ORG = "IS_GOVERNANCE_ORG"         # Entity → GovernanceOrg
    IS_BRAND = "IS_BRAND"                           # Entity → Brand
    IS_MARKETPLACE = "IS_MARKETPLACE"               # Entity → Marketplace
    IS_MEDIA_ENTITY = "IS_MEDIA_ENTITY"             # Entity → MediaEntity
    IS_YIELD_PLATFORM = "IS_YIELD_PLATFORM"         # Entity → YieldPlatform
    # Backward compat aliases
    IS_DAO = "IS_DAO"                               # → IS_GOVERNANCE_ORG
    IS_DEX = "IS_DEX"                               # → (use EXCHANGE vertex directly)

    # ── External account linkage ──────────────────────────────────────
    HAS_PLAID_ACCOUNT = "HAS_PLAID_ACCOUNT"          # Entity → PlaidAccount
    HAS_CREDIT_PROFILE = "HAS_CREDIT_PROFILE"        # Entity → CreditProfile
    HAS_TRADFI_POSITION = "HAS_TRADFI_POSITION"      # Entity → TradFiPosition

    # ── Campaign ──────────────────────────────────────────────────────
    TARGETED_BY_CAMPAIGN = "TARGETED_BY_CAMPAIGN"   # Entity → AdCampaign
    HAS_RETARGET_RECOMMENDATION = "HAS_RETARGET_RECOMMENDATION"  # Entity → RetargetRecommendation

    # ── Entity → Protocol / Onchain ───────────────────────────────────
    TRADES_ON_PROTOCOL = "TRADES_ON_PROTOCOL"       # Wallet → Protocol (swap events)
    STAKES_IN = "STAKES_IN"                         # Wallet → Protocol (staking/restaking)
    DEPLOYS_CONTRACT_FROM = "DEPLOYS_CONTRACT_FROM"  # Wallet → Contract (contract creation)

    # ── Entity → Entity (universal relationship graph) ────────────────
    CO_INVESTS_WITH = "CO_INVESTS_WITH"             # Entity → Entity (shared investment position)
    LISTED_ON = "LISTED_ON"                         # Brand/Product → Marketplace or Exchange
    DISTRIBUTES_VIA = "DISTRIBUTES_VIA"             # Entity → Channel/Platform (distribution)
    CONTENT_ON = "CONTENT_ON"                       # Entity → MediaEntity/Platform (presence)
    COMPETES_WITH = "COMPETES_WITH"                 # Entity → Entity (competitive relationship)
    REVIEWS = "REVIEWS"                             # Entity → Entity (review/rating)
    SELLS_ON = "SELLS_ON"                           # Brand → Marketplace (seller relationship)
    OPERATES_CHANNEL = "OPERATES_CHANNEL"           # Entity → MediaEntity (owns/runs channel)

    # ── Human → Business / Org ────────────────────────────────────────
    EMPLOYEE_OF = "EMPLOYEE_OF"                     # Entity → Organization/Brand
    FOUNDER_OF = "FOUNDER_OF"                       # Entity → Organization/Brand
    CUSTOMER_OF = "CUSTOMER_OF"                     # Entity → Organization/Brand
    INVESTOR_IN = "INVESTOR_IN"                     # Entity → Organization/Brand
    CONTRACTOR_FOR = "CONTRACTOR_FOR"               # Entity → Organization (time-bounded)


# ═══════════════════════════════════════════════════════════════════════════
# SAFE VALUE ESCAPING
# ═══════════════════════════════════════════════════════════════════════════

_GREMLIN_UNSAFE = re.compile(r"['\"\\\x00-\x1f`;]")


def _escape_gremlin(value: Any) -> str:
    """Escape a value for safe Gremlin string interpolation."""
    s = str(value)
    return _GREMLIN_UNSAFE.sub(lambda m: "\\" + m.group(0), s)


# ═══════════════════════════════════════════════════════════════════════════
# VERTEX / EDGE FACTORIES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Vertex:
    vertex_type: str
    vertex_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_gremlin(self) -> str:
        """Generate a Gremlin addV() traversal string with escaped values."""
        props = "".join(
            f".property('{_escape_gremlin(k)}', '{_escape_gremlin(v)}')"
            for k, v in self.properties.items()
        )
        return (
            f"g.addV('{_escape_gremlin(self.vertex_type)}')"
            f".property('id', '{_escape_gremlin(self.vertex_id)}')"
            f".property('created_at', '{_escape_gremlin(self.created_at)}')"
            f"{props}"
        )


@dataclass
class Edge:
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_gremlin(self) -> str:
        """Generate a Gremlin addE() traversal string with escaped values."""
        props = "".join(
            f".property('{_escape_gremlin(k)}', '{_escape_gremlin(v)}')"
            for k, v in self.properties.items()
        )
        return (
            f"g.V('{_escape_gremlin(self.from_vertex_id)}')"
            f".addE('{_escape_gremlin(self.edge_type)}')"
            f".to(g.V('{_escape_gremlin(self.to_vertex_id)}'))"
            f".property('created_at', '{_escape_gremlin(self.created_at)}')"
            f"{props}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _neptune_endpoint() -> str:
    return os.getenv("NEPTUNE_ENDPOINT", "")


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND (local/dev)
# ═══════════════════════════════════════════════════════════════════════════

class _InMemoryGraphBackend:
    """Dict-based graph for local development."""

    def __init__(self) -> None:
        self._vertices: dict[str, Vertex] = {}
        self._edges: list[Edge] = []

    async def add_vertex(self, vertex: Vertex) -> str:
        self._vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        self._edges.append(edge)

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        return self._vertices.get(vertex_id)

    async def get_neighbors(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list[Vertex]:
        results: list[Vertex] = []
        for edge in self._edges:
            if direction in ("out", "both") and edge.from_vertex_id == vertex_id:
                if edge_type is None or edge.edge_type == edge_type:
                    target = self._vertices.get(edge.to_vertex_id)
                    if target:
                        results.append(target)
            if direction in ("in", "both") and edge.to_vertex_id == vertex_id:
                if edge_type is None or edge.edge_type == edge_type:
                    target = self._vertices.get(edge.from_vertex_id)
                    if target:
                        results.append(target)
        return results

    async def get_edges(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list["Edge"]:
        results: list[Edge] = []
        for edge in self._edges:
            touches = False
            if direction == "out" and edge.from_vertex_id == vertex_id:
                touches = True
            elif direction == "in" and edge.to_vertex_id == vertex_id:
                touches = True
            elif direction == "both" and (
                edge.from_vertex_id == vertex_id or edge.to_vertex_id == vertex_id
            ):
                touches = True
            if touches and (edge_type is None or edge.edge_type == edge_type):
                results.append(edge)
        return results

    async def get_all_vertices(self, limit: int = 1000) -> list["Vertex"]:
        return list(self._vertices.values())[:limit]

    async def query(self, gremlin: str) -> list[dict]:
        logger.debug(f"In-memory graph QUERY (no-op): {gremlin[:80]}...")
        return []

    async def upsert_vertex(self, vertex: Vertex) -> str:
        existing = self._vertices.get(vertex.vertex_id)
        if existing:
            existing.properties.update(vertex.properties)
        else:
            self._vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._vertices.clear()
        self._edges.clear()


# ═══════════════════════════════════════════════════════════════════════════
# NEPTUNE BACKEND (production via gremlinpython)
# ═══════════════════════════════════════════════════════════════════════════

class _NeptuneGraphBackend:
    """Real Neptune graph backend using gremlinpython."""

    def __init__(self, endpoint: str) -> None:
        if not GREMLIN_AVAILABLE:
            raise RuntimeError(
                "gremlinpython is required for Neptune: pip install gremlinpython>=3.7"
            )
        self._endpoint = endpoint
        self._connection: Optional[Any] = None
        self._g: Optional[Any] = None

    async def _ensure_connected(self) -> Any:
        if self._g is None:
            url = f"wss://{self._endpoint}:8182/gremlin"
            self._connection = DriverRemoteConnection(url, "g")
            self._g = traversal().withRemote(self._connection)
            logger.info(f"Neptune connected: {self._endpoint}")
        return self._g

    async def add_vertex(self, vertex: Vertex) -> str:
        g = await self._ensure_connected()
        t = g.addV(vertex.vertex_type).property(T.id, vertex.vertex_id)
        t = t.property("created_at", vertex.created_at)
        for k, v in vertex.properties.items():
            t = t.property(k, str(v))
        t.next()
        logger.info(f"Neptune ADD_V {vertex.vertex_type} id={vertex.vertex_id}")
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        g = await self._ensure_connected()
        t = g.V(edge.from_vertex_id).addE(edge.edge_type).to(__.V(edge.to_vertex_id))
        t = t.property("created_at", edge.created_at)
        for k, v in edge.properties.items():
            t = t.property(k, str(v))
        t.next()
        logger.info(
            f"Neptune ADD_E {edge.edge_type} "
            f"{edge.from_vertex_id} -> {edge.to_vertex_id}"
        )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        g = await self._ensure_connected()
        try:
            result = g.V(vertex_id).valueMap(True).next()
            return Vertex(
                vertex_type=result.get(T.label, "unknown"),
                vertex_id=str(result.get(T.id, vertex_id)),
                properties={
                    k: v[0] if isinstance(v, list) and len(v) == 1 else v
                    for k, v in result.items()
                    if k not in (T.id, T.label)
                },
            )
        except StopIteration:
            return None
        except Exception as e:
            logger.error(f"Neptune get_vertex error for {vertex_id}: {e}")
            return None

    async def get_neighbors(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list[Vertex]:
        g = await self._ensure_connected()
        results: list[Vertex] = []
        try:
            if direction == "out":
                t = g.V(vertex_id).outE()
            elif direction == "in":
                t = g.V(vertex_id).inE()
            else:
                t = g.V(vertex_id).bothE()

            if edge_type:
                t = t.hasLabel(edge_type)

            if direction == "out":
                t = t.inV()
            elif direction == "in":
                t = t.outV()
            else:
                t = t.otherV()

            for v_map in t.valueMap(True).toList():
                results.append(Vertex(
                    vertex_type=v_map.get(T.label, "unknown"),
                    vertex_id=str(v_map.get(T.id, "")),
                    properties={
                        k: v[0] if isinstance(v, list) and len(v) == 1 else v
                        for k, v in v_map.items()
                        if k not in (T.id, T.label)
                    },
                ))
        except Exception as e:
            logger.error(f"Neptune get_neighbors error for {vertex_id}: {e}")
        return results

    async def get_edges(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list["Edge"]:
        g = await self._ensure_connected()
        results: list[Edge] = []
        try:
            dirs: list[tuple[str, Any]] = []
            if direction in ("out", "both"):
                dirs.append(("out", g.V(vertex_id).outE()))
            if direction in ("in", "both"):
                dirs.append(("in", g.V(vertex_id).inE()))
            for _dir, trav in dirs:
                if edge_type:
                    trav = trav.hasLabel(edge_type)
                edge_maps = (
                    trav.project("lbl", "props", "from_id", "to_id")
                    .by(T.label)
                    .by(__.valueMap())
                    .by(__.outV().id())
                    .by(__.inV().id())
                    .toList()
                )
                for em in edge_maps:
                    raw_props: dict = em.get("props", {})
                    props = {
                        k: v[0] if isinstance(v, list) and len(v) == 1 else v
                        for k, v in raw_props.items()
                    }
                    created = str(props.pop("created_at", ""))
                    results.append(Edge(
                        edge_type=str(em["lbl"]),
                        from_vertex_id=str(em["from_id"]),
                        to_vertex_id=str(em["to_id"]),
                        properties=props,
                        created_at=created,
                    ))
        except Exception as e:
            logger.error(f"Neptune get_edges error for {vertex_id}: {e}")
        return results

    async def get_all_vertices(self, limit: int = 1000) -> list["Vertex"]:
        g = await self._ensure_connected()
        results: list[Vertex] = []
        try:
            for v_map in g.V().limit(limit).valueMap(True).toList():
                results.append(Vertex(
                    vertex_type=str(v_map.get(T.label, "unknown")),
                    vertex_id=str(v_map.get(T.id, "")),
                    properties={
                        k: v[0] if isinstance(v, list) and len(v) == 1 else v
                        for k, v in v_map.items()
                        if k not in (T.id, T.label)
                    },
                ))
        except Exception as e:
            logger.error(f"Neptune get_all_vertices error: {e}")
        return results

    async def query(self, gremlin: str) -> list[dict]:
        await self._ensure_connected()
        try:
            # Submit raw Gremlin string via the connection's client
            if self._connection and hasattr(self._connection, '_client'):
                result = self._connection._client.submit(gremlin).all().result()
                return [dict(r) if hasattr(r, 'items') else {"value": r} for r in result]
        except Exception as e:
            logger.error(f"Neptune raw query error: {e}")
        return []

    async def upsert_vertex(self, vertex: Vertex) -> str:
        g = await self._ensure_connected()
        try:
            # Try to find existing vertex first
            existing = g.V(vertex.vertex_id).hasNext()
            if existing:
                t = g.V(vertex.vertex_id)
                for k, v in vertex.properties.items():
                    t = t.property(Cardinality.single, k, str(v))
                t.next()
            else:
                await self.add_vertex(vertex)
        except Exception:
            await self.add_vertex(vertex)
        return vertex.vertex_id

    async def ping(self) -> bool:
        try:
            g = await self._ensure_connected()
            g.V().limit(1).hasNext()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
            self._g = None
            logger.info("Neptune connection closed")


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH CLIENT (public API — auto-selects backend)
# ═══════════════════════════════════════════════════════════════════════════

class GraphClient:
    """
    Async graph client with automatic backend selection.

    - AETHER_ENV=local → in-memory graph
    - AETHER_ENV=staging/production + NEPTUNE_ENDPOINT → Neptune via gremlinpython
    - Non-local without Neptune → RuntimeError (fail-closed)
    """

    def __init__(self) -> None:
        self._backend: Optional[_InMemoryGraphBackend | _NeptuneGraphBackend] = None
        self._connected = False
        self._mode = "uninitialized"

    async def connect(self) -> None:
        endpoint = _neptune_endpoint()
        if endpoint and GREMLIN_AVAILABLE:
            self._backend = _NeptuneGraphBackend(endpoint)
            if await self._backend.ping():
                self._mode = "neptune"
                logger.info(f"GraphClient connected (Neptune: {endpoint})")
            else:
                if _is_local_env():
                    logger.warning("Neptune not reachable — falling back to in-memory graph")
                    self._backend = _InMemoryGraphBackend()
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"Neptune not reachable at {endpoint}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
        elif _is_local_env():
            self._backend = _InMemoryGraphBackend()
            self._mode = "in-memory"
            logger.info("GraphClient connected (in-memory, local mode)")
        else:
            raise RuntimeError(
                "NEPTUNE_ENDPOINT not configured. Required in non-local environments. "
                "Set AETHER_ENV=local for in-memory fallback."
            )
        self._connected = True

    async def close(self) -> None:
        if self._backend:
            await self._backend.close()
        self._connected = False
        logger.info("GraphClient closed")

    async def add_vertex(self, vertex: Vertex) -> str:
        if self._backend is None:
            await self.connect()
        return await self._backend.add_vertex(vertex)  # type: ignore[union-attr]

    async def add_edge(self, edge: Edge) -> None:
        if self._backend is None:
            await self.connect()
        await self._backend.add_edge(edge)  # type: ignore[union-attr]

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_vertex(vertex_id)  # type: ignore[union-attr]

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
    ) -> list[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_neighbors(vertex_id, edge_type, direction)  # type: ignore[union-attr]

    async def get_edges(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
    ) -> list[Edge]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_edges(vertex_id, edge_type, direction)  # type: ignore[union-attr]

    async def get_all_vertices(self, limit: int = 1000) -> list[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_all_vertices(limit)  # type: ignore[union-attr]

    async def query(self, gremlin: str) -> list[dict]:
        if self._backend is None:
            await self.connect()
        return await self._backend.query(gremlin)  # type: ignore[union-attr]

    async def upsert_vertex(self, vertex: Vertex) -> str:
        if self._backend is None:
            await self.connect()
        return await self._backend.upsert_vertex(vertex)  # type: ignore[union-attr]

    async def health_check(self) -> bool:
        if self._backend is None:
            return False
        try:
            return await self._backend.ping()
        except Exception:
            return False

    @property
    def mode(self) -> str:
        return self._mode
