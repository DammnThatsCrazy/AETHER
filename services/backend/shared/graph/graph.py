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

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.graph")

# ── Tenant property ──────────────────────────────────────────────────────────
#
# The graph has carried two spellings of the same concept. Vertex producers
# write camelCase ``tenantId`` (services/silver/projectors/silver_graph_projector.py)
# and every route filters on it; edge producers write snake_case ``tenant_id``
# (shared/graph/edge_properties.py) and so do ``revoke_edge`` /
# ``delete_vertex_if_orphaned``.
#
# That split was not cosmetic. ``current_graph_digest`` filtered vertices on
# ``tenant_id``, so it matched nothing a real producer had written: the digest
# over a populated graph was byte-identical to the digest over an empty one,
# and the replay-parity check it backs was vacuously green.
#
# ``TENANT_PROPERTY`` is the canonical spelling for new writes and for the
# Neptune predicate. ``tenant_of`` reads either, so existing rows in both
# spellings resolve correctly and nothing has to be backfilled before the
# scoped reads become correct.

TENANT_PROPERTY = "tenantId"
_TENANT_PROPERTY_ALIASES = ("tenantId", "tenant_id")


def tenant_of(properties: Optional[dict[str, Any]]) -> Optional[str]:
    """The tenant a vertex or edge belongs to, in either spelling.

    Returns ``None`` when no tenant property is present, which callers must
    treat as "not this tenant" rather than as a wildcard.
    """
    if not properties:
        return None
    for key in _TENANT_PROPERTY_ALIASES:
        value = properties.get(key)
        if value is not None and value != "":
            return str(value)
    return None

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

    # ── Cluster types — full taxonomy ─────────────────────────────────────
    HOUSEHOLD_CLUSTER = "HouseholdCluster"
    ORG_CLUSTER = "OrgCluster"
    DEVICE_CLUSTER = "DeviceCluster"
    WALLET_CLUSTER = "WalletCluster"
    BEHAVIORAL_CLUSTER = "BehavioralCluster"
    GEOGRAPHIC_CLUSTER = "GeographicCluster"
    ECONOMIC_SEGMENT = "EconomicSegment"
    CAMPAIGN_COHORT = "CampaignCohort"
    JOURNEY_CLUSTER = "JourneyCluster"
    FRAUD_NETWORK_CLUSTER = "FraudNetworkCluster"
    RISK_CLUSTER = "RiskCluster"
    DORMANT_COHORT = "DormantCohort"
    REACTIVATED_COHORT = "ReactivatedCohort"
    UNRESOLVED_CLUSTER = "UnresolvedCluster"

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

    # ── Geographic360 — location resolution targets (additive) ─────────
    # Canonical location-fact targets resolved by services/geo from the
    # location registry / LocationFact model surface. They back the
    # EXCLUDED-layer located/observed/jurisdiction edges — no canonical
    # RelationshipLayer bucket membership required (like Source nodes).
    PLACE = "Place"
    REGION = "Region"
    JURISDICTION = "Jurisdiction"

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

    # ── Agent Lifecycle — Task / Tool / Outcome vertices (additive) ──────
    TASK = "Task"                            # A unit of work assigned to an agent
    TOOL = "Tool"                            # An external tool or capability called by an agent
    OUTCOME = "Outcome"                      # Terminal result of a task/execution
    POLICY = "Policy"                        # A governance or budget policy evaluated
    CAPABILITY = "Capability"                # A granted capability scoped to an agent

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
    ECONOMIC_CLUSTER = "EconomicCluster"

    # ── Agentic Observability — External account / MCP / tool vertices ────
    # AETHER OBSERVES. AETHER DOES NOT EXECUTE.
    EXTERNAL_AGENT = "ExternalAgent"
    MCP_CONNECTION = "MCPConnection"
    AGENT_TOOL_OBS = "AgentToolObserved"
    AGENT_PERMISSION_SET = "AgentPermissionSet"
    AGENT_ACTIVITY = "AgentActivity"
    AGENT_RISK_SIGNAL = "AgentRiskSignal"
    EXTERNAL_AGENTIC_ACCOUNT = "ExternalAgenticAccount"
    EXTERNAL_BROKERAGE_ACCOUNT = "ExternalBrokerageAccount"
    AGENT_BUDGET_OBSERVED = "AgentBudgetObserved"
    TRADING_STRATEGY_OBSERVED = "TradingStrategyObserved"
    TRADE_INTENT_OBSERVED = "TradeIntentObserved"
    TRADE_ORDER_OBSERVED = "TradeOrderObserved"
    TRADE_FILL_OBSERVED = "TradeFillObserved"
    TRADE_REJECTION_OBSERVED = "TradeRejectionObserved"
    PORTFOLIO_SNAPSHOT_OBSERVED = "PortfolioSnapshotObserved"
    POSITION_SNAPSHOT_OBSERVED = "PositionSnapshotObserved"
    AGENT_PERFORMANCE_SNAPSHOT = "AgentPerformanceSnapshotObserved"
    AGENT_DISCONNECT_OBSERVED = "AgentDisconnectObserved"
    AGENT_NOTIFICATION_OBSERVED = "AgentNotificationObserved"

    # ── Agentic Observability — Communication vertices ─────────────────────
    AGENT_INBOX_OBSERVED = "AgentInboxObserved"
    AGENT_EMAIL_ADDRESS_OBSERVED = "AgentEmailAddressObserved"
    AGENT_THREAD_OBSERVED = "AgentThreadObserved"
    AGENT_MESSAGE_OBSERVED = "AgentMessageObserved"
    AGENT_ATTACHMENT_OBSERVED = "AgentAttachmentObserved"
    EXTRACTED_ENTITY_OBSERVED = "ExtractedEntityObserved"
    OTP_OBSERVATION = "OTPObservation"
    INVOICE_OBSERVATION = "InvoiceObservation"
    RECEIPT_OBSERVATION = "ReceiptObservation"
    CALENDAR_INTENT_OBSERVED = "CalendarIntentObserved"
    SUPPORT_ROUTING_OBSERVED = "SupportRoutingObserved"
    MESSAGE_PROVIDER_OBSERVED = "MessageProviderObserved"

    # ── Agentic Observability — x402/protocol vertices ─────────────────────
    X402_INTERACTION_OBSERVED = "X402InteractionObserved"
    X402_CHALLENGE_OBSERVED = "X402ChallengeObserved"
    X402_PAYMENT_REQUIREMENT_OBSERVED = "X402PaymentRequirementObserved"
    X402_SIGNATURE_OBSERVED = "X402SignatureObserved"
    X402_FACILITATOR_OBSERVED = "X402FacilitatorObserved"
    X402_VERIFICATION_OBSERVED = "X402VerificationObserved"
    X402_SETTLEMENT_OBSERVED = "X402SettlementObserved"
    X402_RESOURCE_ACCESS_OBSERVED = "X402ResourceAccessObserved"
    PAID_RESOURCE_OBSERVED = "PaidResourceObserved"
    RESOURCE_PROVIDER_OBSERVED = "ResourceProviderObserved"
    PROTOCOL_PROVIDER_OBSERVED = "ProtocolProviderObserved"

    # ── Fraud Network Intelligence ─────────────────────────────────────────
    FRAUD_NETWORK = "FraudNetwork"
    FLOW_TRACE    = "FlowTrace"
    RISK_OVERLAY  = "RiskOverlay"

    # ── Derivatives Intelligence — canonical registries (observation-only) ──
    # Orders/fills/positions stay silver facts, not vertices (cardinality).
    # Venues reuse MARKET_VENUE; instruments reuse INSTRUMENT; markets reuse
    # MARKET; strategies reuse STRATEGY. Only the account is new.
    TRADING_ACCOUNT = "TradingAccount"

    # ── Stablecoin Intelligence — deployment identity (asset reuses
    # STABLECOIN_ASSET; chains reuse CHAIN; bridges reuse BRIDGE_ROUTE) ──────
    STABLECOIN_DEPLOYMENT = "StablecoinDeployment"

    # ── Financial Normalization — canonical reference vertices (WP6a) ──────
    # Universal financial-registry reference data. These vertices live on the
    # NON-actor reference layer (never H2H/H2A/A2H/A2A subject vertices) and are
    # GLOBAL (tenant_scoped=False): tenant-owned records reference them by id,
    # but the reference layer itself is not tenant-mutable. ASSET and CHAIN
    # already exist above (Profile-360 generic abstraction + Web3 chain node);
    # they are reused here as the canonical-asset / canonical-chain registry
    # nodes. The remaining members are additive reference vertices.
    ASSET_DEPLOYMENT = "AssetDeployment"    # deploy:<asset_id>@<chain>:<contract>
    FIAT_CURRENCY = "FiatCurrency"          # ISO-4217 reference row (FIAT_REFERENCE_SEED)
    ISSUER = "Issuer"                       # canonical issuer of an asset/stablecoin
    PRICE_PROVIDER = "PriceProvider"        # price-feed / oracle provider
    VENUE = "Venue"                         # trading / listing venue reference
    BRIDGE = "Bridge"                       # bridge operator/router reference

    # ── Card-linked payment rails (V1: catalog dims + flow facts) ──
    CARD_PROGRAM = "CardProgram"
    CARD_ISSUER = "CardIssuer"
    PAYMENT_NETWORK = "PaymentNetwork"
    CARD_LINKED_FLOW = "CardLinkedFlow"
    CARD_BENCHMARK = "CardBenchmark"

    # ── Interoperability Intelligence — protocol-neutral topology ──────────
    # Messages stay silver facts, not vertices (cardinality).
    INTEROP_PROVIDER = "InteropProvider"
    INTEROP_GATEWAY = "InteropGateway"
    INTEROP_PATH = "InteropPath"
    INTEROP_APPLICATION = "InteropApplication"
    VERIFICATION_ACTOR = "VerificationActor"
    DELIVERY_ACTOR = "DeliveryActor"


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
    # Semantic-intelligence relationship overlay (derived analytics, EXCLUDED
    # layer): a directed entity->entity edge projected from
    # gold_relationship_semantic_state by the semantic graph projector.
    SEMANTIC_RELATES_TO = "SEMANTIC_RELATES_TO"

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

    # ── Agent Lifecycle — Ownership / Identity edges (additive) ──────────
    OWNS_AGENT = "OWNS_AGENT"                        # User/Org → Agent (ownership)
    AUTHORIZED_AGENT = "AUTHORIZED_AGENT"            # User/Org → Agent (authorization grant)
    HAS_CAPABILITY = "HAS_CAPABILITY"                # Agent → Capability (granted capability)
    REVOKED_CAPABILITY = "REVOKED_CAPABILITY"        # Agent → Capability (revoked)
    ACTED_FOR = "ACTED_FOR"                          # Agent → User/Entity (acting on behalf of)

    # ── Agent Lifecycle — Task control-flow edges (additive) ──────────────
    CREATED_TASK = "CREATED_TASK"                    # Agent/User → Task
    DECOMPOSED_INTO = "DECOMPOSED_INTO"              # Task → Task (subtask decomposition)
    STARTED_TASK = "STARTED_TASK"                    # Agent → Task
    COMPLETED_TASK = "COMPLETED_TASK"                # Agent → Task
    FAILED_TASK = "FAILED_TASK"                      # Agent → Task
    CALLED_TOOL = "CALLED_TOOL"                      # Agent → Tool (tool invocation)
    REQUESTED_RESOURCE = "REQUESTED_RESOURCE"        # Agent → EconomicResource (resource request)
    DELEGATED_TO = "DELEGATED_TO"                    # Agent/User → Agent (task delegation)
    SPAWNED_SUBAGENT = "SPAWNED_SUBAGENT"            # Agent → Agent (dynamic subagent creation)
    EVALUATED_BY_POLICY = "EVALUATED_BY_POLICY"      # Agent/Task → Policy (policy evaluation)
    HANDED_OFF_TO = "HANDED_OFF_TO"                  # Agent → Agent (task handoff)
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"        # Agent → User (human escalation)

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

    # ── Geographic360 — canonical location-fact edges (EXCLUDED layer) ─
    # Evidence-carrying WHERE edges written via the GraphMutationGateway
    # (the projection is read_only; the location facts these edges carry are
    # governed writes). Classified EXCLUDED (Python-only, like
    # SEMANTIC_RELATES_TO): domain location facts, not human/agent
    # interaction-layer edges.
    LOCATED_AT = "LOCATED_AT"                  # subject → Place|Region (resolved, declared precision)
    OBSERVED_IN = "OBSERVED_IN"                # subject/source → Region|coarse_cell (one observation)
    UNDER_JURISDICTION = "UNDER_JURISDICTION"  # subject → Jurisdiction (governing policy scope)

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

    # ── Agentic Observability — Human/Agent delegation edges ──────────────
    # AETHER OBSERVES. AETHER DOES NOT EXECUTE.
    HUMAN_DELEGATED_TO_AGENT = "HUMAN_DELEGATED_TO_AGENT"
    ORG_DELEGATED_TO_AGENT = "ORG_DELEGATED_TO_AGENT"
    AGENT_ACTED_ON_BEHALF_OF = "AGENT_ACTED_ON_BEHALF_OF"
    AGENT_CONNECTED_VIA_MCP = "AGENT_CONNECTED_VIA_MCP"
    AGENT_USED_TOOL_OBS = "AGENT_USED_TOOL_OBS"
    AGENT_TRIGGERED_ACTIVITY = "AGENT_TRIGGERED_ACTIVITY"
    AGENT_PRODUCED_RISK_SIGNAL = "AGENT_PRODUCED_RISK_SIGNAL"

    # ── Agentic Observability — External account edges ─────────────────────
    AGENT_LINKED_TO_EXTERNAL_ACCOUNT = "AGENT_LINKED_TO_EXTERNAL_ACCOUNT"
    EXTERNAL_ACCOUNT_HAS_BUDGET_OBSERVED = "EXTERNAL_ACCOUNT_HAS_BUDGET_OBSERVED"
    EXTERNAL_ACCOUNT_HAS_PERMISSION_OBSERVED = "EXTERNAL_ACCOUNT_HAS_PERMISSION_OBSERVED"
    EXTERNAL_ACCOUNT_EMITTED_ACTIVITY = "EXTERNAL_ACCOUNT_EMITTED_ACTIVITY"
    EXTERNAL_ACCOUNT_EMITTED_NOTIFICATION = "EXTERNAL_ACCOUNT_EMITTED_NOTIFICATION"
    EXTERNAL_ACCOUNT_DISCONNECTED = "EXTERNAL_ACCOUNT_DISCONNECTED"

    # ── Agentic Observability — Trading observation edges ─────────────────
    AGENT_GENERATED_TRADE_INTENT = "AGENT_GENERATED_TRADE_INTENT"
    EXTERNAL_ACCOUNT_OBSERVED_ORDER = "EXTERNAL_ACCOUNT_OBSERVED_ORDER"
    EXTERNAL_ACCOUNT_OBSERVED_FILL = "EXTERNAL_ACCOUNT_OBSERVED_FILL"
    EXTERNAL_ACCOUNT_OBSERVED_REJECTION = "EXTERNAL_ACCOUNT_OBSERVED_REJECTION"
    EXTERNAL_ACCOUNT_OBSERVED_POSITION = "EXTERNAL_ACCOUNT_OBSERVED_POSITION"
    EXTERNAL_ACCOUNT_OBSERVED_PORTFOLIO = "EXTERNAL_ACCOUNT_OBSERVED_PORTFOLIO"
    STRATEGY_PRODUCED_INTENT = "STRATEGY_PRODUCED_INTENT"

    # ── Agentic Observability — Communication edges ────────────────────────
    AGENT_HAS_INBOX = "AGENT_HAS_INBOX"
    INBOX_HAS_EMAIL_ADDRESS = "INBOX_HAS_EMAIL_ADDRESS"
    INBOX_CONTAINS_THREAD = "INBOX_CONTAINS_THREAD"
    THREAD_CONTAINS_MESSAGE = "THREAD_CONTAINS_MESSAGE"
    MESSAGE_HAS_ATTACHMENT = "MESSAGE_HAS_ATTACHMENT"
    MESSAGE_EXTRACTED_ENTITY = "MESSAGE_EXTRACTED_ENTITY"
    MESSAGE_REFERENCES_INVOICE = "MESSAGE_REFERENCES_INVOICE"
    MESSAGE_REFERENCES_SUPPORT_CASE = "MESSAGE_REFERENCES_SUPPORT_CASE"

    # ── Agentic Observability — x402/protocol edges ────────────────────────
    AGENT_REQUESTED_RESOURCE_OBS = "AGENT_REQUESTED_RESOURCE_OBS"
    RESOURCE_RETURNED_X402_CHALLENGE = "RESOURCE_RETURNED_X402_CHALLENGE"
    CHALLENGE_HAS_PAYMENT_REQUIREMENT = "CHALLENGE_HAS_PAYMENT_REQUIREMENT"
    INTERACTION_HAS_SIGNATURE_OBSERVED = "INTERACTION_HAS_SIGNATURE_OBSERVED"
    INTERACTION_HAS_VERIFICATION_OBSERVED = "INTERACTION_HAS_VERIFICATION_OBSERVED"
    INTERACTION_HAS_SETTLEMENT_OBSERVED = "INTERACTION_HAS_SETTLEMENT_OBSERVED"
    INTERACTION_HAS_RESOURCE_ACCESS_OUTCOME = "INTERACTION_HAS_RESOURCE_ACCESS_OUTCOME"
    RESOURCE_PROVIDED_BY = "RESOURCE_PROVIDED_BY"
    PROTOCOL_OBSERVED_FROM_PROVIDER = "PROTOCOL_OBSERVED_FROM_PROVIDER"
    INTERACTION_FLAGGED_REPLAY_RISK = "INTERACTION_FLAGGED_REPLAY_RISK"

    # ── Fraud Network Intelligence ─────────────────────────────────────────
    MEMBER_OF_FRAUD_NETWORK  = "MEMBER_OF_FRAUD_NETWORK"   # Entity → FraudNetwork
    HAS_RISK_ROLE            = "HAS_RISK_ROLE"             # Entity → FraudNetwork (with role property)
    SCORED_AS_RISKY          = "SCORED_AS_RISKY"           # Entity/Edge → RiskOverlay
    SUPPORTED_BY_EVIDENCE    = "SUPPORTED_BY_EVIDENCE"     # FraudNetwork/FlowTrace → EvidenceRef node
    PART_OF_FLOW_TRACE       = "PART_OF_FLOW_TRACE"        # Entity → FlowTrace
    FLOW_PATH_NEXT           = "FLOW_PATH_NEXT"            # FlowTraceNode → FlowTraceNode (path hop)
    HAS_SOURCE               = "HAS_SOURCE"                # FlowTrace → source Entity/Wallet
    HAS_SINK                 = "HAS_SINK"                  # FlowTrace → sink Entity/Wallet
    HAS_CONTROLLER           = "HAS_CONTROLLER"            # FraudNetwork → controller Entity
    USES_MULE                = "USES_MULE"                 # FraudNetwork → mule Entity
    LINKED_BY_DEVICE         = "LINKED_BY_DEVICE"          # Entity → Entity (shared device signal)
    LINKED_BY_IP             = "LINKED_BY_IP"              # Entity → Entity (shared IP signal)
    LINKED_BY_WALLET         = "LINKED_BY_WALLET"          # Entity → Entity (shared wallet signal)
    LINKED_BY_AGENT          = "LINKED_BY_AGENT"           # Agent → Agent (shared agent infrastructure)
    LINKED_BY_DELEGATION     = "LINKED_BY_DELEGATION"      # Human → Agent (delegation abuse signal)
    ATTACHED_TO_CASE         = "ATTACHED_TO_CASE"          # FraudNetwork/FlowTrace → InvestigationCase

    # ── Silver-sourced commerce & outcome edges ──────────────────────────
    PURCHASED                = "PURCHASED"                 # User/Entity → Product/Order (from silver_revenue_facts)
    ACHIEVED_OUTCOME         = "ACHIEVED_OUTCOME"          # User/Entity → Goal (from silver_outcome_facts)
    CONTACTED                = "CONTACTED"                 # Agent/System → User (from silver_comms_facts)

    # ── Phase 2: Economic flow edges ─────────────────────────────────────
    TRANSFERS_TO             = "TRANSFERS_TO"              # Entity → Entity (fiat/onchain transfer)
    REFUNDED_BY              = "REFUNDED_BY"               # Order/Payment → Entity (refund)
    CHARGED_BACK_BY          = "CHARGED_BACK_BY"           # Order/Payment → Entity (chargeback)

    # ── Phase 2: Fraud ring edges ─────────────────────────────────────────
    LAYERED_THROUGH          = "LAYERED_THROUGH"           # Entity → Entity (money layering)
    SMURFED_VIA              = "SMURFED_VIA"               # Entity → Entity (smurfing / structuring)

    # ── Phase 2: Campaign and attribution edges ───────────────────────────
    ACQUIRED_VIA             = "ACQUIRED_VIA"              # Entity → Campaign (acquisition channel)
    CONVERTED_FROM           = "CONVERTED_FROM"            # Entity → Touchpoint (conversion source)
    ATTRIBUTED_TO_CAMPAIGN   = "ATTRIBUTED_TO_CAMPAIGN"    # Event/Conversion → Campaign
    TOUCHPOINT_IN            = "TOUCHPOINT_IN"             # Touchpoint → Journey

    # ── Traffic intelligence — source/attribution edges (spec §13.6) ───────
    # Canonical source-classification relationships projected from
    # silver_campaign_touchpoint_facts. Source/Placement/SourceLink/
    # PlatformEvidence are non-human attribution nodes, so entity→node edges
    # are EXCLUDED from the four operational layers; REFERRED_ENTITY
    # (agent/AI → entity) is a genuine A2H interaction.
    ARRIVED_THROUGH_SOURCE          = "ARRIVED_THROUGH_SOURCE"          # Entity/Session → Source
    USED_PLACEMENT                  = "USED_PLACEMENT"                  # Session → Placement
    ORIGINATED_FROM_LINK            = "ORIGINATED_FROM_LINK"            # Journey/Session → VerifiedSourceLink
    ATTRIBUTED_TO_PLATFORM_EVIDENCE = "ATTRIBUTED_TO_PLATFORM_EVIDENCE"  # Install/Entity → PlatformEvidence
    REFERRED_ENTITY                 = "REFERRED_ENTITY"                 # Agent/AI → Entity

    # ── Phase 2: Journey step edges ──────────────────────────────────────
    NEXT_IN_JOURNEY          = "NEXT_IN_JOURNEY"           # Touchpoint → Touchpoint (ordered)
    ABANDONED_AT             = "ABANDONED_AT"              # Entity → Touchpoint (drop-off)
    CONVERTED_AT             = "CONVERTED_AT"              # Entity → Touchpoint (conversion)

    # ── Phase 2: Cluster lifecycle edges ─────────────────────────────────
    BRIDGES                  = "BRIDGES"                   # Entity → Cluster (bridge node)
    MERGED_INTO              = "MERGED_INTO"               # Cluster → Cluster (merge event)
    SPLIT_FROM               = "SPLIT_FROM"                # Cluster → Cluster (split event)

    # ── Derivatives Intelligence — actor edges (TS parity:
    #    DERIVATIVES_ACTOR_EDGE_LAYER_MAP in packages/shared/derivatives.ts;
    #    REQUESTS_APPROVAL_FROM already exists above) ───────────────────────
    REFERRED_TO_VENUE           = "REFERRED_TO_VENUE"            # Human → Human (H2H)
    FUNDED                      = "FUNDED"                       # Human → Human (H2H)
    SHARES_TRADING_ACCOUNT_WITH = "SHARES_TRADING_ACCOUNT_WITH"  # Human → Human (H2H)
    AUTHORIZED                  = "AUTHORIZED"                   # Human → Human (H2H)
    COPIES_STRATEGY_FROM        = "COPIES_STRATEGY_FROM"         # Human → Human (H2H)
    PARTICIPATES_IN_VAULT_WITH  = "PARTICIPATES_IN_VAULT_WITH"   # Human → Human (H2H)
    MEMBER_OF_TRADING_ORG_WITH  = "MEMBER_OF_TRADING_ORG_WITH"   # Human → Human (H2H)
    POSSIBLY_COORDINATED_WITH   = "POSSIBLY_COORDINATED_WITH"    # Human → Human (H2H, inferred)
    POSSIBLY_MIRRORS            = "POSSIBLY_MIRRORS"             # Human → Human (H2H, inferred)
    DELEGATES_TRADING_TO        = "DELEGATES_TRADING_TO"         # Human → Agent (H2A)
    AUTHORIZES_MARKETS_FOR      = "AUTHORIZES_MARKETS_FOR"       # Human → Agent (H2A)
    SETS_RISK_POLICY_FOR        = "SETS_RISK_POLICY_FOR"         # Human → Agent (H2A)
    APPROVES_TRADE_FROM         = "APPROVES_TRADE_FROM"          # Human → Agent (H2A)
    FUNDS_AGENT                 = "FUNDS_AGENT"                  # Human → Agent (H2A)
    OVERRIDES_AGENT             = "OVERRIDES_AGENT"              # Human → Agent (H2A)
    REVOKES_TRADING_AUTHORITY   = "REVOKES_TRADING_AUTHORITY"    # Human → Agent (H2A)
    RECOMMENDS_TRADE_TO         = "RECOMMENDS_TRADE_TO"          # Agent → Human (A2H)
    WARNS                       = "WARNS"                        # Agent → Human (A2H)
    REQUESTS_MARGIN_FROM        = "REQUESTS_MARGIN_FROM"         # Agent → Human (A2H)
    REPORTS_PNL_TO              = "REPORTS_PNL_TO"               # Agent → Human (A2H)
    ESCALATES_RISK_TO           = "ESCALATES_RISK_TO"            # Agent → Human (A2H)
    EXPLAINS_DECISION_TO        = "EXPLAINS_DECISION_TO"         # Agent → Human (A2H)
    PROPOSES_TRADE_TO           = "PROPOSES_TRADE_TO"            # Agent → Agent (A2A)
    REQUESTS_RISK_REVIEW_FROM   = "REQUESTS_RISK_REVIEW_FROM"    # Agent → Agent (A2A)
    APPROVES_EXECUTION_FOR      = "APPROVES_EXECUTION_FOR"       # Agent → Agent (A2A)
    VETOES_EXECUTION_FOR        = "VETOES_EXECUTION_FOR"         # Agent → Agent (A2A)
    ROUTES_ORDER_TO             = "ROUTES_ORDER_TO"              # Agent → Agent (A2A)
    VERIFIES_FILL_FROM          = "VERIFIES_FILL_FROM"           # Agent → Agent (A2A)
    RECONCILES_POSITION_FOR     = "RECONCILES_POSITION_FOR"      # Agent → Agent (A2A)

    # ── Derivatives Intelligence — domain edges (EXCLUDED from actor layers;
    #    CONTROLS / HOLDS_POSITION / EXECUTED_ON / LISTED_ON /
    #    GOVERNED_BY_POLICY / ATTRIBUTED_TO_CAMPAIGN reuse existing edges) ───
    AUTHENTICATES         = "AUTHENTICATES"          # Account → Venue
    HAS_SUBACCOUNT        = "HAS_SUBACCOUNT"         # Account → Subaccount
    PARTICIPATES_IN_VAULT = "PARTICIPATES_IN_VAULT"  # Entity → Vault
    CREATED_ORDER         = "CREATED_ORDER"          # Account → Order fact
    CONTAINS_FILL         = "CONTAINS_FILL"          # Order fact → Fill fact
    ON_MARKET             = "ON_MARKET"              # Position → Market
    SETTLES_IN            = "SETTLES_IN"             # Market → Asset
    MARGINED_BY           = "MARGINED_BY"            # Position → MarginState
    BACKED_BY             = "BACKED_BY"              # Position → Collateral
    PRICED_BY             = "PRICED_BY"              # Market → PriceObservation
    INCURRED_FEE          = "INCURRED_FEE"           # Position → Fee
    PAID_FUNDING          = "PAID_FUNDING"           # Position → FundingPayment
    RECEIVED_FUNDING      = "RECEIVED_FUNDING"       # Position → FundingPayment
    LIQUIDATED_BY         = "LIQUIDATED_BY"          # Position → LiquidationEvent
    GENERATED_PNL         = "GENERATED_PNL"          # Position → PnlSnapshot
    PART_OF_JOURNEY       = "PART_OF_JOURNEY"        # Fact → Journey
    DERIVED_FROM_EVENT    = "DERIVED_FROM_EVENT"     # Projection → source event

    # ── Stablecoin Intelligence — actor edges ───────────────────────────────
    SENT_STABLECOIN_TO           = "SENT_STABLECOIN_TO"            # Human → Human (H2H)
    PAID_MERCHANT                = "PAID_MERCHANT"                 # Human → Human (H2H)
    SHARES_TREASURY_WITH         = "SHARES_TREASURY_WITH"          # Human → Human (H2H)
    AUTHORIZED_STABLECOIN_SPEND  = "AUTHORIZED_STABLECOIN_SPEND"   # Human → Agent (H2A)
    FUNDS_AGENT_WALLET           = "FUNDS_AGENT_WALLET"            # Human → Agent (H2A)
    REQUESTED_STABLECOIN_PAYMENT = "REQUESTED_STABLECOIN_PAYMENT"  # Agent → Human (A2H)
    REPORTS_FLOW_TO              = "REPORTS_FLOW_TO"               # Agent → Human (A2H)
    SETTLES_WITH_AGENT           = "SETTLES_WITH_AGENT"            # Agent → Agent (A2A)
    ROUTES_PAYMENT_TO            = "ROUTES_PAYMENT_TO"             # Agent → Agent (A2A)

    # ── Stablecoin Intelligence — domain edges (EXCLUDED; ISSUED_BY reuses
    #    the existing edge) ─────────────────────────────────────────────────
    TRANSFERRED_STABLECOIN = "TRANSFERRED_STABLECOIN"  # Wallet → Wallet (fact link)

    # ── Card-linked payment rails (evidence-backed, observation-only) ──
    CAME_FROM               = "CAME_FROM"                # User → Campaign (acquisition evidence)
    PARTICIPATED_IN         = "PARTICIPATED_IN"          # User → Journey
    USED_PROVIDER           = "USED_PROVIDER"            # User → CardProgram
    FUNDED                  = "FUNDED"                   # Wallet → CardLinkedFlow
    OCCURRED_ON             = "OCCURRED_ON"              # CardLinkedFlow → Chain
    USED_ASSET              = "USED_ASSET"               # CardLinkedFlow → Token
    RUNS_ON                 = "RUNS_ON"                  # CardProgram → PaymentNetwork
    FOLLOWED_BY             = "FOLLOWED_BY"              # CardLinkedFlow → CardLinkedFlow
    INITIATED_OR_INFLUENCED = "INITIATED_OR_INFLUENCED"  # Agent → CardLinkedFlow
    BRIDGED_STABLECOIN     = "BRIDGED_STABLECOIN"      # Deployment → Deployment
    SWAPPED_STABLECOIN     = "SWAPPED_STABLECOIN"      # Wallet → Deployment
    DEPLOYED_ON_CHAIN      = "DEPLOYED_ON_CHAIN"       # Deployment → Chain
    SUPPORTS_ASSET         = "SUPPORTS_ASSET"          # Org/App → Deployment
    PEGGED_TO              = "PEGGED_TO"               # Asset → reference currency
    VALUED_AT              = "VALUED_AT"               # Deployment → Valuation
    RECONCILED_WITH        = "RECONCILED_WITH"         # Observation → Reconciliation

    # ── Financial Normalization — reference edges (WP6a, non-actor reference
    #    layer). DEPLOYED_ON_CHAIN / PEGGED_TO / VALUED_AT / RECONCILED_WITH /
    #    PRICED_BY are declared above (stablecoin + derivatives domains);
    #    ISSUED_BY is the existing cross-domain edge. These members are additive
    #    to complete the universal financial reference edge surface (see
    #    docs/source-of-truth/FINANCIAL_NORMALIZATION.md §9). ────────────────
    DENOMINATED_IN = "DENOMINATED_IN"        # Value leg/instrument → FiatCurrency|Asset
    PAID_WITH = "PAID_WITH"                  # Payment/leg → Asset|AssetDeployment
    SETTLED_IN = "SETTLED_IN"                # Settlement/leg → Asset|AssetDeployment|FiatCurrency
    CHARGED_IN = "CHARGED_IN"                # Charge/leg → FiatCurrency|Asset
    ASSESSED_IN = "ASSESSED_IN"              # Assessment/liability → FiatCurrency|Asset
    WRAPS = "WRAPS"                          # AssetDeployment → AssetDeployment (wrapped)
    BRIDGED_FROM = "BRIDGED_FROM"            # AssetDeployment → AssetDeployment (origin)
    VALUED_IN = "VALUED_IN"                  # Event/Observation → FiatCurrency|Asset (native context)
    DERIVED_FROM = "DERIVED_FROM"            # Projection/Valuation → source asset/observation
    REVERSES = "REVERSES"                    # Flow/entry → Flow/entry (reversal)
    DISPUTES = "DISPUTES"                    # Flow/entry → Flow/entry (dispute)

    # ── Interoperability Intelligence — actor edges ─────────────────────────
    INITIATED_CROSS_CHAIN_WITH = "INITIATED_CROSS_CHAIN_WITH"  # Human → Human (H2H)
    SHARES_APPLICATION_WITH    = "SHARES_APPLICATION_WITH"     # Human → Human (H2H)
    REQUESTED_DELIVERY_FROM    = "REQUESTED_DELIVERY_FROM"     # Human → Agent (H2A)
    AUTHORIZED_INTEROP_SPEND   = "AUTHORIZED_INTEROP_SPEND"    # Human → Agent (H2A)
    RELAYED_FOR                = "RELAYED_FOR"                 # Agent → Human (A2H)
    REPORTS_DELIVERY_TO        = "REPORTS_DELIVERY_TO"         # Agent → Human (A2H)
    COORDINATES_INTENT_WITH    = "COORDINATES_INTENT_WITH"     # Agent → Agent (A2A)
    VERIFIES_FOR               = "VERIFIES_FOR"                # Agent → Agent (A2A)

    # ── Interoperability Intelligence — domain edges (EXCLUDED; VERIFIED_BY
    #    reuses the existing edge) ──────────────────────────────────────────
    SENT_VIA_PATH         = "SENT_VIA_PATH"          # Message fact → Path
    DELIVERED_VIA_GATEWAY = "DELIVERED_VIA_GATEWAY"  # Message fact → Gateway
    ROUTES_THROUGH        = "ROUTES_THROUGH"         # Path → Gateway
    CONNECTS_CHAIN        = "CONNECTS_CHAIN"         # Gateway → Chain
    SECURED_BY_POLICY     = "SECURED_BY_POLICY"      # Path → SecurityPolicySnapshot
    USES_PROVIDER         = "USES_PROVIDER"          # Application → Provider
    ORIGINATES_FROM_APP   = "ORIGINATES_FROM_APP"    # Message fact → Application
    DELIVERS_TO_APP       = "DELIVERS_TO_APP"        # Message fact → Application
    HAS_ASSET_LEG         = "HAS_ASSET_LEG"          # Message fact → AssetLeg fact
    HAS_SECURITY_SNAPSHOT = "HAS_SECURITY_SNAPSHOT"  # Message fact → Snapshot
    FULFILLED_INTENT      = "FULFILLED_INTENT"       # Message fact → Intent

    # ── Relationship Intelligence Spine — registered Social360 predicate
    #    edges (Milestone M6). One EdgeType per relationship predicate in
    #    packages/shared/contracts/relationship-predicate-registry.json whose
    #    graphRegistrationState is REGISTERED and whose graphEdgeType resolves
    #    here. Two names are deliberately SOCIAL_-prefixed because the bare
    #    predicate name already exists on this class with DIFFERENT semantics:
    #      * SOCIAL_INTERACTS_WITH  (entity→entity social interaction) vs the
    #        existing INTERACTS_WITH   (User → Protocol, H2A).
    #      * SOCIAL_SUBSCRIBES_TO   (entity→entity social channel subscription)
    #        vs the existing SUBSCRIBES_TO (User/Agent → ServicePlan, H2A).
    #    FOLLOWS follows the same disambiguation precedent (FOLLOWS_SOCIAL).
    #    Registered edges are NEVER classified RelationshipLayer.EXCLUDED;
    #    entity→entity / principal relationship predicates are H2H, the
    #    reciprocal-communication aggregate is A2A (its direct COMMUNICATES_WITH
    #    substrate is A2A), and the agent-chain-principal predicate is H2H at the
    #    principal endpoints the edge is written between. Layer map:
    #    shared/graph/relationship_layers.py.
    MUTUAL_SOCIAL_CONNECTION = "MUTUAL_SOCIAL_CONNECTION"   # Entity ↔ Entity (reciprocal follows)
    SOCIAL_SUBSCRIBES_TO = "SOCIAL_SUBSCRIBES_TO"           # Entity → Entity (social channel subscription)
    SOCIAL_INTERACTS_WITH = "SOCIAL_INTERACTS_WITH"         # Entity → Entity (durable social interaction)
    COLLABORATES_WITH = "COLLABORATES_WITH"                 # Entity ↔ Entity (verified collaboration)
    PARTICIPATES_WITH = "PARTICIPATES_WITH"                 # Entity ↔ Entity (shared participation)
    COMMUNITY_ASSOCIATION = "COMMUNITY_ASSOCIATION"         # Entity ↔ Entity (shared community + interaction)
    RECURRING_SOCIAL_INTERACTION = "RECURRING_SOCIAL_INTERACTION"  # Entity → Entity (aggregate interaction)
    RECIPROCAL_COMMUNICATION = "RECIPROCAL_COMMUNICATION"   # Entity/Agent ↔ Entity/Agent (reciprocal comms)
    RECURRING_CO_PRESENCE = "RECURRING_CO_PRESENCE"         # Entity ↔ Entity (recurring co-presence episodes)
    PERSISTENT_MULTI_CONTEXT_ASSOCIATION = "PERSISTENT_MULTI_CONTEXT_ASSOCIATION"  # Entity ↔ Entity
    SHARES_AFFINITY_WITH = "SHARES_AFFINITY_WITH"           # Entity/Agent → Entity/Agent (behavioral affinity)
    AGENT_MEDIATED_PRINCIPAL_INTERACTION = "AGENT_MEDIATED_PRINCIPAL_INTERACTION"  # Principal ↔ Principal
    REFERRED_BY = "REFERRED_BY"                             # Entity → Entity (campaign attribution)
    CO_EXPOSED = "CO_EXPOSED"                               # Entity ↔ Entity (campaign exposure)
    SHARES_RISK_CONTEXT_WITH = "SHARES_RISK_CONTEXT_WITH"   # Entity/Agent ↔ Entity/Agent (shared risk context)
    CO_PRESENT_WITH = "CO_PRESENT_WITH"                     # Entity ↔ Entity (single-episode co-presence)


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


def _graph_backend() -> str:
    """The declared graph backend for non-local, non-Neptune profiles.

    Mirrors ``config.settings.RuntimeConfig.graph_backend`` (default
    ``postgres``); read from the environment here so ``shared.graph`` stays free
    of a settings import. Only consulted by ``GraphClient.connect`` when no
    Neptune endpoint is configured and the process is not local.
    """
    return os.getenv("GRAPH_BACKEND", "postgres").strip().lower()


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

    async def revoke_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        edge_type: str,
        reason: str,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Soft-revoke matching edge(s); return the count of matching edges.

        Sets ``revoked``/``revoked_at``/``revoke_reason`` on every stored edge
        matching ``(from, to, edge_type[, tenant_id])``. Does not hard-delete.
        Idempotent: already-revoked edges keep their original ``revoked_at`` and
        are still counted, so re-revoking is a safe no-op-ish success.
        """
        revoked_at = datetime.now(timezone.utc).isoformat()
        count = 0
        for edge in self._edges:
            if (
                edge.from_vertex_id == from_vertex_id
                and edge.to_vertex_id == to_vertex_id
                and edge.edge_type == edge_type
            ):
                if tenant_id is not None and str(
                    edge.properties.get("tenant_id")
                ) != str(tenant_id):
                    continue
                if not edge.properties.get("revoked"):
                    edge.properties["revoked"] = True
                    edge.properties["revoked_at"] = revoked_at
                    edge.properties["revoke_reason"] = reason
                count += 1
        return count

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        return self._vertices.get(vertex_id)

    async def delete_vertex_if_orphaned(
        self,
        vertex_id: str,
        tenant_id: str,
        import_commit_id: str,
    ) -> tuple[bool, str]:
        """Delete only a vertex exclusively owned by the rolled-back import."""
        vertex = self._vertices.get(vertex_id)
        if vertex is None:
            return False, "not_found"
        props = vertex.properties or {}
        if str(props.get("tenant_id")) != str(tenant_id):
            return False, "tenant_mismatch"
        if str(props.get("import_commit_id")) != str(import_commit_id):
            return False, "ownership_changed"
        owners = {str(value) for value in (props.get("import_commit_ids") or [])}
        if owners - {str(import_commit_id)}:
            return False, "shared_history"
        incident = [
            edge
            for edge in self._edges
            if edge.from_vertex_id == vertex_id or edge.to_vertex_id == vertex_id
        ]
        if any(not (edge.properties or {}).get("revoked") for edge in incident):
            return False, "active_reference"
        if any(
            str((edge.properties or {}).get("import_commit_id")) != str(import_commit_id)
            for edge in incident
        ):
            return False, "shared_history"
        self._vertices.pop(vertex_id, None)
        self._edges = [
            edge
            for edge in self._edges
            if edge.from_vertex_id != vertex_id and edge.to_vertex_id != vertex_id
        ]
        return True, "deleted"

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Vertex]:
        results: list[Vertex] = []
        for edge in self._edges:
            if not include_revoked and edge.properties.get("revoked"):
                continue
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
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list["Edge"]:
        results: list[Edge] = []
        for edge in self._edges:
            if not include_revoked and edge.properties.get("revoked"):
                continue
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

    async def get_vertices_for_tenant(
        self, tenant_id: str, limit: int = 1000, *, vertex_type: Optional[str] = None
    ) -> list["Vertex"]:
        """Vertices belonging to one tenant. The cap applies to THAT tenant.

        Filtering before slicing is the whole point: callers used to fetch a
        global page and filter it afterwards, so a tenant whose vertices sorted
        past the cap silently received a partial page or none at all.
        """
        matched: list[Vertex] = []
        for vertex in self._vertices.values():
            if tenant_of(vertex.properties) != tenant_id:
                continue
            if vertex_type is not None and vertex.vertex_type != vertex_type:
                continue
            matched.append(vertex)
            if len(matched) >= limit:
                break
        return matched

    async def delete_tenant_data(self, tenant_id: str) -> int:
        """Hard-delete graph projection data owned by one tenant.

        The admin rehearsal-cleanup path uses this after credential revocation
        and before removing the tenant row.  Ownership is checked with
        :func:`tenant_of` so both historical ``tenantId`` and legacy
        ``tenant_id`` records are handled, while unscoped/system vertices are
        never touched.  Dropping the owned vertices also removes their
        incident edges, including edges whose endpoint itself is unscoped.

        Tenant-tagged edges are swept even when the tenant owns NO vertices —
        the semantic projector writes ``SEMANTIC_RELATES_TO`` edges without
        projecting vertices by default, so an early "no owned vertices → nothing
        to erase" return would leak those edges past a tenant erasure. This
        matches the Postgres and Neptune backends, which delete tenant-tagged
        edges unconditionally.
        """
        owned = {
            vertex.vertex_id
            for vertex in self._vertices.values()
            if tenant_of(vertex.properties) == str(tenant_id)
        }
        self._vertices = {
            vertex_id: vertex
            for vertex_id, vertex in self._vertices.items()
            if vertex_id not in owned
        }
        before = len(self._edges)
        self._edges = [
            edge
            for edge in self._edges
            if edge.from_vertex_id not in owned
            and edge.to_vertex_id not in owned
            and tenant_of(edge.properties) != str(tenant_id)
        ]
        return len(owned) + (before - len(self._edges))

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
# POSTGRES BACKEND (non-local profiles that declare graph: postgres, no Neptune)
# ═══════════════════════════════════════════════════════════════════════════

# Idempotent DDL mirroring the ``20260902_graph_pg_backend`` Alembic migration
# (the canonical, production schema owner). ``ensure_schema`` uses it so a test
# or a bootstrap can materialise the two tables on a database whose migrations
# have not been applied; production always applies the migration. Keep the two
# in exact agreement — a column added here must be added to the migration too.
_PG_GRAPH_SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS graph_vertices (
        vertex_id   TEXT PRIMARY KEY,
        vertex_type TEXT NOT NULL,
        tenant_id   TEXT,
        properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at  TEXT NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_graph_vertices_tenant ON graph_vertices (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_graph_vertices_tenant_type "
    "ON graph_vertices (tenant_id, vertex_type)",
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        edge_id         BIGSERIAL PRIMARY KEY,
        edge_type       TEXT NOT NULL,
        from_vertex_id  TEXT NOT NULL,
        to_vertex_id    TEXT NOT NULL,
        tenant_id       TEXT,
        properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at      TEXT NOT NULL,
        revoked         BOOLEAN NOT NULL DEFAULT FALSE,
        revoked_at      TEXT,
        revoke_reason   TEXT,
        idempotency_key TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_from "
    "ON graph_edges (from_vertex_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_to "
    "ON graph_edges (to_vertex_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_tenant ON graph_edges (tenant_id)",
)


def _delete_rowcount(status_tag: str) -> int:
    """Parse the row count out of an asyncpg ``DELETE <n>`` command tag."""
    try:
        return int(str(status_tag).split()[-1])
    except (ValueError, IndexError):
        return 0


# Fixed advisory-lock key that serialises concurrent ``ensure_schema`` callers.
# Postgres ``CREATE TABLE / INDEX IF NOT EXISTS`` is NOT safe under concurrency
# (it can raise a duplicate-key / tuple-concurrently-updated error when two
# sessions run it at once), so the idempotent bootstrap DDL runs under a
# transaction-scoped ``pg_advisory_xact_lock``.
_PG_GRAPH_SCHEMA_LOCK_KEY = 0x67726170  # "grap"


class _PostgresGraphBackend:
    """Durable graph over Postgres for profiles that declare ``graph: postgres``.

    The staging and production-lean deployment profiles declare ``graph:
    postgres`` but run no Neptune cluster. Before this backend existed,
    :meth:`GraphClient.connect` fail-closed with a ``RuntimeError`` in exactly
    those profiles — the declared backend was never implemented. This backend
    closes that gap over two JSONB tables (``graph_vertices`` / ``graph_edges``,
    owned by the ``20260902_graph_pg_backend`` migration) and implements the same
    narrow async protocol as the in-memory and Neptune backends.

    Its observable semantics are byte-for-byte those of
    :class:`_InMemoryGraphBackend` — the parity reference the contract tests pin
    both backends against:

    * **Append-only edges.** Edges are rows, not keyed by ``(from, to, type)``;
      the same pair may carry several edges (a replica race), exactly as the
      in-memory list allows, and the projector's reconciliation collapses the
      duplicates. There are deliberately no foreign keys to ``graph_vertices`` —
      an edge may exist before/without its endpoint vertices, mirroring the flat
      in-memory edge store the projector relies on.
    * **Soft revoke.** :meth:`revoke_edge` marks the ``revoked`` COLUMN (never a
      hard delete) and is idempotent (already-revoked rows keep their original
      ``revoked_at`` and are still counted). Every read folds the revoke columns
      back into the returned edge's ``properties`` so callers that inspect
      ``properties['revoked']`` behave identically to the in-memory path.
    * **Indexed tenant scoping.** Ownership is resolved with :func:`tenant_of`
      (either spelling) and persisted in a ``tenant_id`` column, so tenant-scoped
      reads and erasure are index lookups — never a global scan filtered
      afterwards (which ``validate_graph_scoped_reads`` forbids for callers).

    The pool is the process-wide asyncpg pool owned by ``repositories.repos``;
    this backend never closes it (that would break every other repository).
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ── (de)serialisation ────────────────────────────────────────────────────
    @staticmethod
    def _dump(properties: Optional[dict[str, Any]]) -> str:
        return json.dumps(properties or {}, default=str)

    @staticmethod
    def _load(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        return json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)

    @classmethod
    def _vertex_from_row(cls, row: Any) -> Vertex:
        return Vertex(
            vertex_type=row["vertex_type"],
            vertex_id=row["vertex_id"],
            properties=cls._load(row["properties"]),
            created_at=row["created_at"],
        )

    @classmethod
    def _edge_from_row(cls, row: Any) -> Edge:
        props = cls._load(row["properties"])
        # Fold the soft-revoke columns back into ``properties`` so downstream
        # readers (overlay, projector reconciliation) see the same shape the
        # in-memory backend writes in place on revoke.
        if row["revoked"]:
            props["revoked"] = True
            if row["revoked_at"] is not None:
                props["revoked_at"] = row["revoked_at"]
            if row["revoke_reason"] is not None:
                props["revoke_reason"] = row["revoke_reason"]
        return Edge(
            edge_type=row["edge_type"],
            from_vertex_id=row["from_vertex_id"],
            to_vertex_id=row["to_vertex_id"],
            properties=props,
            created_at=row["created_at"],
        )

    async def ensure_schema(self) -> None:
        """Idempotently create the two tables (test/bootstrap convenience).

        Production applies the ``20260902_graph_pg_backend`` migration; this
        mirrors it with ``CREATE TABLE IF NOT EXISTS`` so a DATABASE_URL-gated
        test can run against a database whose migrations were not applied. The
        DDL runs under a transaction-scoped advisory lock so concurrent callers
        (e.g. parallel test workers) serialise rather than racing PG's
        not-concurrency-safe ``IF NOT EXISTS`` DDL.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1)", _PG_GRAPH_SCHEMA_LOCK_KEY
                )
                for ddl in _PG_GRAPH_SCHEMA_DDL:
                    await conn.execute(ddl)

    # ── writes ───────────────────────────────────────────────────────────────
    async def add_vertex(self, vertex: Vertex) -> str:
        # Last-write-wins overwrite (in-memory: ``self._vertices[id] = vertex``).
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO graph_vertices
                    (vertex_id, vertex_type, tenant_id, properties, created_at)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                ON CONFLICT (vertex_id) DO UPDATE SET
                    vertex_type = EXCLUDED.vertex_type,
                    tenant_id   = EXCLUDED.tenant_id,
                    properties  = EXCLUDED.properties,
                    created_at  = EXCLUDED.created_at,
                    updated_at  = NOW()
                """,
                vertex.vertex_id,
                vertex.vertex_type,
                tenant_of(vertex.properties),
                self._dump(vertex.properties),
                vertex.created_at,
            )
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        props = edge.properties or {}
        idem = props.get("idempotency_key")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO graph_edges
                    (edge_type, from_vertex_id, to_vertex_id, tenant_id,
                     properties, created_at, revoked, revoked_at, revoke_reason,
                     idempotency_key)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
                """,
                edge.edge_type,
                edge.from_vertex_id,
                edge.to_vertex_id,
                tenant_of(props),
                self._dump(props),
                edge.created_at,
                bool(props.get("revoked")),
                props.get("revoked_at"),
                props.get("revoke_reason"),
                str(idem) if idem is not None else None,
            )

    async def revoke_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        edge_type: str,
        reason: str,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Soft-revoke matching edge(s); return the count of matching edges.

        Marks the ``revoked`` column on every not-yet-revoked edge matching
        ``(from, to, edge_type[, tenant_id])`` and returns the count of ALL
        matching edges (already-revoked included, whose ``revoked_at`` is
        preserved) — identical to the in-memory backend. ``tenant_id`` matches
        the ``tenant_id`` column (``tenant_of`` of the edge's properties).
        """
        revoked_at = datetime.now(timezone.utc).isoformat()
        conditions = ["from_vertex_id = $1", "to_vertex_id = $2", "edge_type = $3"]
        params: list[Any] = [from_vertex_id, to_vertex_id, edge_type]
        if tenant_id is not None:
            params.append(str(tenant_id))
            conditions.append(f"tenant_id = ${len(params)}")
        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                f"SELECT COUNT(*) FROM graph_edges WHERE {where}", *params
            )
            if count:
                await conn.execute(
                    f"""
                    UPDATE graph_edges
                    SET revoked = TRUE,
                        revoked_at = ${len(params) + 1},
                        revoke_reason = ${len(params) + 2}
                    WHERE {where} AND revoked = FALSE
                    """,
                    *params,
                    revoked_at,
                    reason,
                )
        return int(count or 0)

    async def upsert_vertex(self, vertex: Vertex) -> str:
        """Merge new properties over an existing vertex, or insert it.

        Mirrors ``existing.properties.update(vertex.properties)`` (new values
        win, ``vertex_type``/``created_at`` unchanged) under ``FOR UPDATE`` so a
        concurrent upsert of the same id cannot lose a write.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT properties FROM graph_vertices WHERE vertex_id = $1 "
                    "FOR UPDATE",
                    vertex.vertex_id,
                )
                if row is not None:
                    merged = {**self._load(row["properties"]), **(vertex.properties or {})}
                    await conn.execute(
                        "UPDATE graph_vertices SET properties = $2::jsonb, "
                        "tenant_id = $3, updated_at = NOW() WHERE vertex_id = $1",
                        vertex.vertex_id,
                        self._dump(merged),
                        tenant_of(merged),
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO graph_vertices
                            (vertex_id, vertex_type, tenant_id, properties, created_at)
                        VALUES ($1, $2, $3, $4::jsonb, $5)
                        """,
                        vertex.vertex_id,
                        vertex.vertex_type,
                        tenant_of(vertex.properties),
                        self._dump(vertex.properties),
                        vertex.created_at,
                    )
        return vertex.vertex_id

    # ── reads ────────────────────────────────────────────────────────────────
    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM graph_vertices WHERE vertex_id = $1", vertex_id
            )
        return self._vertex_from_row(row) if row else None

    async def _neighbors_one_direction(
        self,
        conn: Any,
        vertex_id: str,
        edge_type: Optional[str],
        include_revoked: bool,
        direction: str,
    ) -> list[Vertex]:
        if direction == "out":
            edge_col, join_col = "from_vertex_id", "to_vertex_id"
        else:
            edge_col, join_col = "to_vertex_id", "from_vertex_id"
        conds = [f"e.{edge_col} = $1"]
        params: list[Any] = [vertex_id]
        if edge_type is not None:
            params.append(edge_type)
            conds.append(f"e.edge_type = ${len(params)}")
        if not include_revoked:
            conds.append("e.revoked = FALSE")
        rows = await conn.fetch(
            f"SELECT v.* FROM graph_edges e "
            f"JOIN graph_vertices v ON v.vertex_id = e.{join_col} "
            f"WHERE {' AND '.join(conds)} ORDER BY e.edge_id",
            *params,
        )
        return [self._vertex_from_row(r) for r in rows]

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Vertex]:
        # A neighbour is only returned when its vertex exists (the JOIN), exactly
        # like the in-memory backend which appends only a target present in
        # ``self._vertices``.
        results: list[Vertex] = []
        async with self._pool.acquire() as conn:
            if direction in ("out", "both"):
                results += await self._neighbors_one_direction(
                    conn, vertex_id, edge_type, include_revoked, "out"
                )
            if direction in ("in", "both"):
                results += await self._neighbors_one_direction(
                    conn, vertex_id, edge_type, include_revoked, "in"
                )
        return results

    async def get_edges(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Edge]:
        if direction == "out":
            conds = ["from_vertex_id = $1"]
        elif direction == "in":
            conds = ["to_vertex_id = $1"]
        else:
            conds = ["(from_vertex_id = $1 OR to_vertex_id = $1)"]
        params: list[Any] = [vertex_id]
        if edge_type is not None:
            params.append(edge_type)
            conds.append(f"edge_type = ${len(params)}")
        if not include_revoked:
            conds.append("revoked = FALSE")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM graph_edges WHERE {' AND '.join(conds)} "
                f"ORDER BY edge_id",
                *params,
            )
        return [self._edge_from_row(r) for r in rows]

    async def get_all_vertices(self, limit: int = 1000) -> list[Vertex]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM graph_vertices ORDER BY vertex_id LIMIT $1", limit
            )
        return [self._vertex_from_row(r) for r in rows]

    async def get_vertices_for_tenant(
        self, tenant_id: str, limit: int = 1000, *, vertex_type: Optional[str] = None
    ) -> list[Vertex]:
        """Vertices for one tenant, the cap applied to that tenant's own rows.

        The tenant predicate is pushed into the WHERE clause (index
        ``ix_graph_vertices_tenant``), never a global page filtered afterwards.
        """
        conds = ["tenant_id = $1"]
        params: list[Any] = [str(tenant_id)]
        if vertex_type is not None:
            params.append(vertex_type)
            conds.append(f"vertex_type = ${len(params)}")
        params.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM graph_vertices WHERE {' AND '.join(conds)} "
                f"ORDER BY vertex_id LIMIT ${len(params)}",
                *params,
            )
        return [self._vertex_from_row(r) for r in rows]

    async def delete_tenant_data(self, tenant_id: str) -> int:
        """Hard-delete graph projection data owned by one tenant.

        Removes the tenant's own vertices and every edge that either touches one
        of those vertices or is itself tenant-owned, and returns
        ``len(owned_vertices) + edges_removed`` — the same total the in-memory
        backend reports. Unscoped/system records (no tenant) are never selected.
        """
        if not tenant_id:
            return 0
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                owned = await conn.fetch(
                    "SELECT vertex_id FROM graph_vertices WHERE tenant_id = $1",
                    str(tenant_id),
                )
                owned_ids = [r["vertex_id"] for r in owned]
                edge_tag = await conn.execute(
                    """
                    DELETE FROM graph_edges
                    WHERE from_vertex_id = ANY($1::text[])
                       OR to_vertex_id = ANY($1::text[])
                       OR tenant_id = $2
                    """,
                    owned_ids,
                    str(tenant_id),
                )
                await conn.execute(
                    "DELETE FROM graph_vertices WHERE tenant_id = $1", str(tenant_id)
                )
        return len(owned_ids) + _delete_rowcount(edge_tag)

    async def delete_vertex_if_orphaned(
        self,
        vertex_id: str,
        tenant_id: str,
        import_commit_id: str,
    ) -> tuple[bool, str]:
        """Delete only a vertex exclusively owned by the rolled-back import.

        The ownership / active-reference / shared-history checks are the
        in-memory backend's, evaluated over the fetched rows inside one
        transaction so the verify-then-delete is atomic.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                vrow = await conn.fetchrow(
                    "SELECT properties FROM graph_vertices WHERE vertex_id = $1 "
                    "FOR UPDATE",
                    vertex_id,
                )
                if vrow is None:
                    return False, "not_found"
                props = self._load(vrow["properties"])
                if str(props.get("tenant_id")) != str(tenant_id):
                    return False, "tenant_mismatch"
                if str(props.get("import_commit_id")) != str(import_commit_id):
                    return False, "ownership_changed"
                owners = {str(value) for value in (props.get("import_commit_ids") or [])}
                if owners - {str(import_commit_id)}:
                    return False, "shared_history"
                incident = await conn.fetch(
                    "SELECT properties, revoked FROM graph_edges "
                    "WHERE from_vertex_id = $1 OR to_vertex_id = $1",
                    vertex_id,
                )
                for e in incident:
                    eprops = self._load(e["properties"])
                    if not (e["revoked"] or eprops.get("revoked")):
                        return False, "active_reference"
                for e in incident:
                    eprops = self._load(e["properties"])
                    if str(eprops.get("import_commit_id")) != str(import_commit_id):
                        return False, "shared_history"
                await conn.execute(
                    "DELETE FROM graph_edges WHERE from_vertex_id = $1 "
                    "OR to_vertex_id = $1",
                    vertex_id,
                )
                await conn.execute(
                    "DELETE FROM graph_vertices WHERE vertex_id = $1", vertex_id
                )
        return True, "deleted"

    async def query(self, gremlin: str) -> list[dict]:
        logger.debug("Postgres graph QUERY (no-op, not a gremlin backend): %s...", gremlin[:80])
        return []

    async def ping(self) -> bool:
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        # The asyncpg pool is process-wide and owned by ``repositories.repos``;
        # closing it here would break every other repository. Nothing to do.
        return None


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

    async def revoke_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        edge_type: str,
        reason: str,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Soft-revoke matching edge(s) via a Gremlin property-set traversal.

        Selects edges by ``(from, to, edge_type[, tenant_id])`` and sets
        ``revoked``/``revoked_at``/``revoke_reason`` — it does not drop the
        edge. Idempotent: only not-yet-revoked edges are written (so
        ``revoked_at`` stays stable), while all matching edges are counted.
        Returns the number of matching edges.
        """
        g = await self._ensure_connected()
        revoked_at = datetime.now(timezone.utc).isoformat()

        def _match() -> Any:
            trav = (
                g.V(from_vertex_id)
                .outE()
                .hasLabel(edge_type)
                .where(__.inV().hasId(to_vertex_id))
            )
            if tenant_id is not None:
                trav = trav.has("tenant_id", str(tenant_id))
            return trav

        count = 0
        try:
            count = int(_match().count().next())
            if count:
                (
                    _match()
                    .hasNot("revoked")
                    .property("revoked", True)
                    .property("revoked_at", revoked_at)
                    .property("revoke_reason", reason)
                    .toList()
                )
            logger.info(
                f"Neptune REVOKE_E {edge_type} "
                f"{from_vertex_id} -> {to_vertex_id} count={count}"
            )
        except Exception as e:
            logger.error(
                f"Neptune revoke_edge error {from_vertex_id}->{to_vertex_id}: {e}"
            )
        return count

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

    async def delete_vertex_if_orphaned(
        self,
        vertex_id: str,
        tenant_id: str,
        import_commit_id: str,
    ) -> tuple[bool, str]:
        """Atomically verify import ownership/no active references, then drop."""
        g = await self._ensure_connected()
        try:
            rows = g.V(vertex_id).valueMap().toList()
            if not rows:
                return False, "not_found"
            props = rows[0]
            tenant_value = props.get("tenant_id", [None])
            commit_value = props.get("import_commit_id", [None])
            tenant_value = tenant_value[0] if isinstance(tenant_value, list) else tenant_value
            commit_value = commit_value[0] if isinstance(commit_value, list) else commit_value
            if str(tenant_value) != str(tenant_id):
                return False, "tenant_mismatch"
            if str(commit_value) != str(import_commit_id):
                return False, "ownership_changed"
            owners_value = props.get("import_commit_ids", [])
            owners = {
                str(value)
                for value in (
                    owners_value
                    if isinstance(owners_value, list)
                    else [owners_value]
                )
            }
            if owners - {str(import_commit_id)}:
                return False, "shared_history"
            if int(g.V(vertex_id).bothE().hasNot("revoked").count().next()) > 0:
                return False, "active_reference"
            foreign_history = (
                g.V(vertex_id)
                .bothE()
                .not_(__.has("import_commit_id", str(import_commit_id)))
                .count()
                .next()
            )
            if int(foreign_history) > 0:
                return False, "shared_history"
            g.V(vertex_id).drop().iterate()
            return True, "deleted"
        except Exception as exc:
            logger.error("Neptune orphan vertex deletion failed for %s: %s", vertex_id, exc)
            return False, "backend_error"

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
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

            # Soft-revoked edges carry a `revoked` property; exclude by default.
            if not include_revoked:
                t = t.hasNot("revoked")

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

    async def k_hop_neighbors(
        self, vertex_id: str, max_depth: int = 2, direction: str = "both", max_results: int = 100,
    ) -> list["Vertex"]:
        g = await self._ensure_connected()
        max_depth = min(max_depth, 3)
        results: list[Vertex] = []
        try:
            if direction == "out":
                step = __.out()
            elif direction == "in":
                step = __.in_()
            else:
                step = __.both()
            vmap_list = (
                g.V(vertex_id)
                .repeat(step.simplePath())
                .times(max_depth)
                .dedup()
                .limit(max_results)
                .valueMap(True)
                .toList()
            )
            for v_map in vmap_list:
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
            logger.error(f"Neptune k_hop_neighbors error for {vertex_id}: {e}")
        return results

    async def get_edges(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
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
                # Soft-revoked edges carry a `revoked` property; exclude by default.
                if not include_revoked:
                    trav = trav.hasNot("revoked")
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

    async def get_vertices_for_tenant(
        self, tenant_id: str, limit: int = 1000, *, vertex_type: Optional[str] = None
    ) -> list["Vertex"]:
        """Vertices for one tenant, with the predicate pushed into the query.

        ``has(...)`` before ``limit(...)`` so the database applies the cap to the
        tenant's own rows rather than to a global page that is then filtered.
        """
        g = await self._ensure_connected()
        results: list[Vertex] = []
        try:
            traversal = g.V()
            if vertex_type is not None:
                traversal = traversal.hasLabel(vertex_type)
            traversal = traversal.has(TENANT_PROPERTY, tenant_id).limit(limit)
            for v_map in traversal.valueMap(True).toList():
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
            logger.error(f"Neptune get_vertices_for_tenant error: {e}")
        return results

    async def delete_tenant_data(self, tenant_id: str) -> int:
        """Drop all Neptune vertices and edges owned by ``tenant_id``.

        Neptune stores vertex and edge ownership under the canonical
        ``tenantId`` key for new writes and ``tenant_id`` for legacy writes.
        Explicit edge traversals handle records whose endpoints are shared or
        unscoped; dropping an owned vertex alone would not remove such an edge
        in every graph implementation.  The predicates also ensure an
        unscoped/system record is never selected by a missing or empty tenant
        value.
        """
        if not tenant_id:
            return 0
        g = await self._ensure_connected()
        try:
            canonical_edges = int(
                g.E().has(TENANT_PROPERTY, str(tenant_id)).count().next()
            )
            legacy_edges = int(
                g.E().has("tenant_id", str(tenant_id)).count().next()
            )
            canonical = int(
                g.V().has(TENANT_PROPERTY, str(tenant_id)).count().next()
            )
            legacy = int(
                g.V().has("tenant_id", str(tenant_id)).count().next()
            )
            g.E().has(TENANT_PROPERTY, str(tenant_id)).drop().iterate()
            g.E().has("tenant_id", str(tenant_id)).drop().iterate()
            g.V().has(TENANT_PROPERTY, str(tenant_id)).drop().iterate()
            g.V().has("tenant_id", str(tenant_id)).drop().iterate()
            return canonical + legacy + canonical_edges + legacy_edges
        except Exception as exc:
            logger.error("Neptune tenant erasure failed for %s: %s", tenant_id, exc)
            raise RuntimeError(f"Neptune tenant erasure failed: {exc}") from exc

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
    - Non-local, no Neptune, GRAPH_BACKEND=postgres + a database pool → Postgres
    - Non-local without any usable backend → RuntimeError (fail-closed)
    """

    def __init__(self) -> None:
        self._backend: Optional[
            _InMemoryGraphBackend | _NeptuneGraphBackend | _PostgresGraphBackend
        ] = None
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
        elif _graph_backend() == "postgres":
            # Non-local profiles that declare ``graph: postgres`` (staging /
            # production-lean) and run no Neptune cluster. ``get_pool`` itself
            # fail-closes with a RuntimeError when DATABASE_URL is unset in a
            # non-local environment, so a misconfigured deployment never boots a
            # graph client silently.
            from repositories.repos import get_pool

            pool = await get_pool()
            if pool is None:
                raise RuntimeError(
                    "GRAPH_BACKEND=postgres but no database pool is available. "
                    "Configure DATABASE_URL, or set AETHER_ENV=local for the "
                    "in-memory fallback."
                )
            self._backend = _PostgresGraphBackend(pool)
            self._mode = "postgres"
            logger.info("GraphClient connected (Postgres backend)")
        else:
            raise RuntimeError(
                f"No usable graph backend: NEPTUNE_ENDPOINT unset and "
                f"GRAPH_BACKEND={_graph_backend()!r} (expected 'postgres'). "
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
        # Pre-write validation: enforces required properties when writing to Neptune.
        # In local/in-memory mode the validator logs violations but does not raise.
        from shared.graph.write_validator import GraphWriteValidationError, GraphWriteValidator
        _env = "production" if self._mode == "neptune" else "local"
        result = GraphWriteValidator().validate(edge, env=_env)
        if not result.passed and self._mode == "neptune":
            raise GraphWriteValidationError(result.violations)
        await self._backend.add_edge(edge)  # type: ignore[union-attr]

    async def revoke_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        edge_type: str,
        reason: str,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Soft-revoke matching edge(s): mark them revoked without deleting.

        Sets ``revoked=True``, ``revoked_at=<iso8601>`` and
        ``revoke_reason=<reason>`` on every edge matching
        ``(from_vertex_id, to_vertex_id, edge_type)``. When ``tenant_id`` is
        provided, only edges carrying that tenant are touched. Revoking a
        non-existent edge is a safe no-op (returns 0); re-revoking is
        idempotent and preserves the original ``revoked_at``. Returns the
        number of matching edges. Revoked edges are excluded from
        ``get_edges``/``get_neighbors`` unless ``include_revoked=True``.
        """
        if self._backend is None:
            await self.connect()
        return await self._backend.revoke_edge(  # type: ignore[union-attr]
            from_vertex_id, to_vertex_id, edge_type, reason, tenant_id
        )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_vertex(vertex_id)  # type: ignore[union-attr]

    async def delete_vertex_if_orphaned(
        self,
        vertex_id: str,
        tenant_id: str,
        import_commit_id: str,
    ) -> tuple[bool, str]:
        """Delete a rolled-back import vertex only when the backend proves safety."""
        if self._backend is None:
            await self.connect()
        return await self._backend.delete_vertex_if_orphaned(  # type: ignore[union-attr]
            vertex_id, tenant_id, import_commit_id
        )

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_neighbors(  # type: ignore[union-attr]
            vertex_id, edge_type, direction, include_revoked
        )

    async def k_hop_neighbors(
        self,
        vertex_id: str,
        max_depth: int = 2,
        direction: str = "both",
        max_results: int = 100,
    ) -> list[Vertex]:
        """BFS up to max_depth hops from vertex_id.

        max_depth is hard-capped at 3 to prevent runaway traversals.
        Returns deduplicated vertices (excluding the start vertex itself).

        In-memory backend: pure Python BFS.
        Neptune backend: single parameterized Gremlin query.
        """
        max_depth = min(max_depth, 3)
        if self._backend is None:
            await self.connect()
        backend = self._backend  # type: ignore[union-attr]

        # Neptune path: single Gremlin traversal avoids N+1 round-trips
        if isinstance(backend, _NeptuneGraphBackend):
            return await backend.k_hop_neighbors(vertex_id, max_depth, direction, max_results)

        # In-memory path: iterative BFS
        visited: set[str] = {vertex_id}
        frontier: list[str] = [vertex_id]
        results: list[Vertex] = []
        for _ in range(max_depth):
            if not frontier or len(results) >= max_results:
                break
            next_frontier: list[str] = []
            for vid in frontier:
                neighbours = await backend.get_neighbors(vid, direction=direction)
                for v in neighbours:
                    if v.vertex_id not in visited:
                        visited.add(v.vertex_id)
                        results.append(v)
                        next_frontier.append(v.vertex_id)
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
            frontier = next_frontier
        return results

    async def get_edges(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Edge]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_edges(  # type: ignore[union-attr]
            vertex_id, edge_type, direction, include_revoked
        )

    async def get_all_vertices(self, limit: int = 1000) -> list[Vertex]:
        """Unscoped read across every tenant. Prefer ``get_vertices_for_tenant``.

        This applies ``limit`` to the WHOLE graph. A caller that filters the
        result by tenant afterwards gets silent truncation — the tenant's rows
        may sort past the cap and never appear — so service code must not use
        this to answer a per-tenant question. ``scripts/validate_graph_scoped_reads.py``
        enforces that.
        """
        if self._backend is None:
            await self.connect()
        return await self._backend.get_all_vertices(limit)  # type: ignore[union-attr]

    async def get_vertices_for_tenant(
        self, tenant_id: str, limit: int = 1000, *, vertex_type: Optional[str] = None
    ) -> list[Vertex]:
        """Vertices for exactly one tenant, with the cap applied to that tenant.

        The tenant predicate is part of the query, not a filter applied to a
        global page, so the caller receives up to ``limit`` of the tenant's own
        rows regardless of how the rest of the graph sorts.

        An empty or missing ``tenant_id`` returns nothing rather than
        everything: a scoped read that cannot name its tenant must not silently
        widen into a cross-tenant one.
        """
        if not tenant_id:
            return []
        if self._backend is None:
            await self.connect()
        return await self._backend.get_vertices_for_tenant(  # type: ignore[union-attr]
            tenant_id, limit, vertex_type=vertex_type
        )

    async def delete_tenant_data(self, tenant_id: str) -> int:
        """Erase only graph projection data owned by one tenant.

        This is intentionally a first-class backend operation rather than a
        caller-issued raw Gremlin query, so local tests and Neptune enforce the
        same tenant ownership and fail-closed behavior.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for graph erasure")
        if self._backend is None:
            await self.connect()
        return await self._backend.delete_tenant_data(tenant_id)  # type: ignore[union-attr]

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


# ── Module-level accessor ────────────────────────────────────────────────────

_shared_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    """Return the process-wide GraphClient.

    Prefers the provider registry's client (already connected and
    lifecycle-managed by main.py); falls back to a lazily connected module
    singleton for workers and scripts that run outside the API process.
    """
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        client = getattr(registry, "graph", None)
        if client is not None:
            return client
    except Exception:
        pass

    global _shared_client
    if _shared_client is None:
        _shared_client = GraphClient()
    return _shared_client
