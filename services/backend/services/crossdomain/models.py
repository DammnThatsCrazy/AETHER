"""
Aether Cross-Domain — Models

Covers entity types, financial accounts, instruments, trade lifecycle,
business entities, compliance, and cross-domain identity linking.

Reuses Web3 coverage patterns: CompletenessStatus, ObjectStatus, Provenance.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# Reuse shared enums from Web3 coverage
from services.web3.models import CompletenessStatus, ObjectStatus, Provenance


# ═══════════════════════════════════════════════════════════════════════════
# ENTITY TYPES
# ═══════════════════════════════════════════════════════════════════════════


class EntityType(str, Enum):
    """All entity types in the cross-domain graph."""
    PERSON = "person"
    PROFILE = "profile"
    LEGAL_ENTITY = "legal_entity"
    BUSINESS = "business"
    HOUSEHOLD = "household"
    INSTITUTION = "institution"
    FUND = "fund"
    DESK = "desk"
    STRATEGY = "strategy"
    ISSUER = "issuer"


class OwnershipRole(str, Enum):
    """How an entity relates to an account or asset."""
    LEGAL_OWNER = "legal_owner"
    BENEFICIAL_OWNER = "beneficial_owner"
    AUTHORIZED_USER = "authorized_user"
    OPERATOR_ADMIN = "operator_admin"
    ADVISOR = "advisor"
    BROKER = "broker"
    AGENT = "agent"
    OMNIBUS_HOLDER = "omnibus_holder"
    CUSTODIAL_HOLDER = "custodial_holder"
    CORPORATE_PARENT = "corporate_parent"
    CORPORATE_SUBSIDIARY = "corporate_subsidiary"
    TRUSTEE = "trustee"
    NOMINEE = "nominee"


class InstitutionType(str, Enum):
    """Classification of financial/business institutions."""
    BROKER_DEALER = "broker_dealer"
    BANK = "bank"
    CUSTODIAN = "custodian"
    EXCHANGE = "exchange"
    MARKET_MAKER = "market_maker"
    PAYMENT_PROCESSOR = "payment_processor"
    TRANSFER_AGENT = "transfer_agent"
    FUND_ADMINISTRATOR = "fund_administrator"
    CLEARING_HOUSE = "clearing_house"
    INSURANCE = "insurance"
    CREDIT_UNION = "credit_union"
    MERCHANT = "merchant"
    ISSUER = "issuer"
    DISTRIBUTOR = "distributor"
    CRM_PROVIDER = "crm_provider"
    SERVICE_PROVIDER = "service_provider"
    OTHER = "other"


# ═══════════════════════════════════════════════════════════════════════════
# FINANCIAL ACCOUNT TYPES
# ═══════════════════════════════════════════════════════════════════════════


class AccountType(str, Enum):
    """Financial account classification."""
    BROKERAGE = "brokerage"
    BANK_CHECKING = "bank_checking"
    BANK_SAVINGS = "bank_savings"
    CUSTODY = "custody"
    MARGIN = "margin"
    RETIREMENT_IRA = "retirement_ira"
    RETIREMENT_401K = "retirement_401k"
    RETIREMENT_ROTH = "retirement_roth"
    TRUST = "trust"
    OMNIBUS = "omnibus"
    SUB_ACCOUNT = "sub_account"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    MERCHANT = "merchant"
    WALLET = "wallet"
    OTHER = "other"


class AccountStatus(str, Enum):
    """Account lifecycle status."""
    PENDING = "pending"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    FROZEN = "frozen"
    CLOSED = "closed"
    DORMANT = "dormant"


# ═══════════════════════════════════════════════════════════════════════════
# INSTRUMENT TYPES
# ═══════════════════════════════════════════════════════════════════════════


class InstrumentType(str, Enum):
    """Market instrument classification."""
    STOCK = "stock"
    ETF = "etf"
    OPTION = "option"
    FUTURE = "future"
    BOND = "bond"
    FUND = "fund"
    BASKET = "basket"
    INDEX = "index"
    TOKENIZED_SECURITY = "tokenized_security"
    STRUCTURED_PRODUCT = "structured_product"
    RATE = "rate"
    FX = "fx"
    COMMODITY = "commodity"
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_DERIVATIVE = "crypto_derivative"
    OTHER = "other"


class InstrumentStatus(str, Enum):
    ACTIVE = "active"
    HALTED = "halted"
    DELISTED = "delisted"
    MATURED = "matured"
    EXPIRED = "expired"


# ═══════════════════════════════════════════════════════════════════════════
# TRADE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT_SELL = "short_sell"
    BUY_TO_COVER = "buy_to_cover"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    MOC = "market_on_close"
    MOO = "market_on_open"
    OTHER = "other"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REPLACED = "replaced"


class CashMovementType(str, Enum):
    """Types of cash movement into/out of accounts."""
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    MARGIN_CALL = "margin_call"
    TAX_WITHHOLDING = "tax_withholding"
    REFUND = "refund"
    REBATE = "rebate"
    WIRE = "wire"
    ACH = "ach"
    CARD_PAYMENT = "card_payment"
    CRYPTO_TRANSFER = "crypto_transfer"
    OTHER = "other"


class CashMovementRail(str, Enum):
    """Payment/transfer rail used."""
    ACH = "ach"
    WIRE = "wire"
    CARD = "card"
    CHECK = "check"
    INTERNAL = "internal"
    CRYPTO = "crypto"
    SEPA = "sepa"
    SWIFT = "swift"
    REALTIME = "realtime"
    OTHER = "other"


# ═══════════════════════════════════════════════════════════════════════════
# COMPLIANCE / KYC / RISK
# ═══════════════════════════════════════════════════════════════════════════


class KYCStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ENHANCED_DUE_DILIGENCE = "enhanced_due_diligence"


class ComplianceActionType(str, Enum):
    """Internal business/compliance actions."""
    ACCOUNT_FREEZE = "account_freeze"
    ACCOUNT_UNFREEZE = "account_unfreeze"
    COMPLIANCE_REVIEW = "compliance_review"
    SUPPORT_INTERVENTION = "support_intervention"
    ADVISOR_OUTREACH = "advisor_outreach"
    MARGIN_ADJUSTMENT = "margin_adjustment"
    CREDIT_LIMIT_CHANGE = "credit_limit_change"
    ELIGIBILITY_APPROVAL = "eligibility_approval"
    ELIGIBILITY_DENIAL = "eligibility_denial"
    CORPORATE_ACTION_NOTICE = "corporate_action_notice"
    RESTRICTION_APPLIED = "restriction_applied"
    RESTRICTION_REMOVED = "restriction_removed"
    SAR_FILED = "sar_filed"
    CTR_FILED = "ctr_filed"
    RISK_ESCALATION = "risk_escalation"


class RestrictionType(str, Enum):
    TRADING = "trading"
    WITHDRAWAL = "withdrawal"
    DEPOSIT = "deposit"
    MARGIN = "margin"
    OPTIONS = "options"
    SHORT_SELLING = "short_selling"
    JURISDICTION = "jurisdiction"
    REGULATORY = "regulatory"
    COMPLIANCE_HOLD = "compliance_hold"


# ═══════════════════════════════════════════════════════════════════════════
# BUSINESS APPLICATION EVENTS
# ═══════════════════════════════════════════════════════════════════════════


class BusinessEventType(str, Enum):
    """Pre-trade and business application behavioral events."""
    # Auth
    LOGIN = "login"
    LOGOUT = "logout"
    PASSWORD_RESET = "password_reset"
    MFA_CHALLENGE = "mfa_challenge"

    # Research / Pre-trade
    QUOTE_LOOKUP = "quote_lookup"
    WATCHLIST_ADD = "watchlist_add"
    WATCHLIST_REMOVE = "watchlist_remove"
    CHART_INTERACTION = "chart_interaction"
    RESEARCH_READ = "research_read"
    OPTION_CHAIN_VIEW = "option_chain_view"
    SCREENER_USE = "screener_use"
    NEWS_READ = "news_read"

    # Trade intent
    ORDER_TICKET_OPEN = "order_ticket_open"
    ORDER_TICKET_ABANDON = "order_ticket_abandon"
    ORDER_EDIT = "order_edit"
    ORDER_CANCEL = "order_cancel"

    # Account management
    DEPOSIT_ATTEMPT = "deposit_attempt"
    WITHDRAW_ATTEMPT = "withdraw_attempt"
    TRANSFER_ATTEMPT = "transfer_attempt"
    KYC_STEP = "kyc_step"
    STATEMENT_DOWNLOAD = "statement_download"
    TAX_DOC_DOWNLOAD = "tax_doc_download"
    PORTFOLIO_REVIEW = "portfolio_review"

    # Support / CRM
    SUPPORT_TICKET_OPEN = "support_ticket_open"
    SUPPORT_CHAT_START = "support_chat_start"
    SUPPORT_RESOLUTION = "support_resolution"
    NPS_SURVEY = "nps_survey"

    # Campaign
    CAMPAIGN_IMPRESSION = "campaign_impression"
    REFERRAL_CLICK = "referral_click"
    PRODUCT_ELIGIBILITY_CHECK = "product_eligibility_check"

    # Custom
    CUSTOM = "custom"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-DOMAIN IDENTITY LINKING
# ═══════════════════════════════════════════════════════════════════════════


class LinkType(str, Enum):
    """How two identities are linked across domains."""
    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"
    INFERRED = "inferred"
    MANUAL = "manual"
    SYSTEM = "system"


class CrossDomainLink(BaseModel):
    """A scored link between two entities across domains."""
    source_entity_id: str
    source_entity_type: str = Field(default="profile")
    target_entity_id: str
    target_entity_type: str = Field(default="profile")
    link_type: LinkType = LinkType.DETERMINISTIC
    link_signal: str = Field(default="", description="What signal created this link (email, phone, account_owner, etc.)")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    domains: list[str] = Field(default_factory=list, description="Which domains this link spans (web2, tradfi, web3)")
    provenance: Provenance = Field(default_factory=lambda: Provenance(source="unknown"))
    reversible: bool = Field(default=True)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY CREATE / RECORD MODELS
# ═══════════════════════════════════════════════════════════════════════════


class InstitutionCreate(BaseModel):
    """Register a financial/business institution."""
    institution_id: str = Field(..., description="Stable ID (e.g., 'schwab', 'jpmorgan', 'robinhood')")
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    institution_type: InstitutionType = InstitutionType.OTHER
    lei: str = Field(default="", description="Legal Entity Identifier (20-char)")
    country: str = Field(default="US")
    website: str = Field(default="")
    parent_institution_id: str = Field(default="")
    api_provider: str = Field(default="", description="Provider adapter name if available")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class InstitutionRecord(InstitutionCreate):
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    account_count: int = Field(default=0)


class AccountCreate(BaseModel):
    """Register a financial account."""
    account_id: str = Field(..., description="Stable internal ID")
    account_type: AccountType = AccountType.BROKERAGE
    institution_id: str = Field(default="")
    owner_entity_id: str = Field(default="", description="Legal owner entity")
    owner_role: OwnershipRole = OwnershipRole.LEGAL_OWNER
    account_number_hash: str = Field(default="", description="SHA256 hash of account number")
    currency: str = Field(default="USD")
    opened_at: str = Field(default="")
    status: AccountStatus = AccountStatus.ACTIVE
    restrictions: list[str] = Field(default_factory=list, description="Active restriction types")
    kyc_status: KYCStatus = KYCStatus.NOT_STARTED
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class AccountRecord(AccountCreate):
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


class InstrumentCreate(BaseModel):
    """Register a market instrument."""
    instrument_id: str = Field(..., description="Stable ID (e.g., 'AAPL', 'SPY', 'US10Y')")
    symbol: str
    name: str
    instrument_type: InstrumentType = InstrumentType.STOCK
    exchange: str = Field(default="", description="Primary exchange/venue")
    issuer_id: str = Field(default="")
    sector: str = Field(default="")
    industry: str = Field(default="")
    country: str = Field(default="US")
    currency: str = Field(default="USD")
    cusip: str = Field(default="")
    isin: str = Field(default="")
    figi: str = Field(default="")
    expiry: str = Field(default="", description="For options/futures")
    strike: Optional[float] = None
    underlying_id: str = Field(default="", description="For derivatives")
    tokenized_wrapper_id: str = Field(default="", description="Web3 token ID if tokenized")
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class InstrumentRecord(InstrumentCreate):
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    price_usd: Optional[float] = None
    price_updated_at: str = Field(default="")
    market_cap_usd: Optional[float] = None


class PositionCreate(BaseModel):
    """Record an account position."""
    position_id: str = Field(default="")
    account_id: str
    instrument_id: str
    quantity: float
    cost_basis: float = Field(default=0.0)
    market_value: float = Field(default=0.0)
    unrealized_pnl: float = Field(default=0.0)
    currency: str = Field(default="USD")
    as_of: str = Field(default="", description="Point-in-time snapshot date")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class OrderCreate(BaseModel):
    """Record a trade order."""
    order_id: str
    account_id: str
    instrument_id: str
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    venue_id: str = Field(default="")
    submitted_at: str = Field(default="")
    filled_at: str = Field(default="")
    cancelled_at: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ExecutionCreate(BaseModel):
    """Record a trade execution/fill."""
    execution_id: str
    order_id: str
    account_id: str
    instrument_id: str
    side: OrderSide = OrderSide.BUY
    fill_quantity: float
    fill_price: float
    venue_id: str = Field(default="")
    fees: float = Field(default=0.0)
    settlement_date: str = Field(default="")
    executed_at: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class BalanceCreate(BaseModel):
    """Record an account balance snapshot."""
    account_id: str
    currency: str = Field(default="USD")
    total: float = Field(default=0.0)
    available: float = Field(default=0.0)
    pending: float = Field(default=0.0)
    held: float = Field(default=0.0)
    margin_buying_power: float = Field(default=0.0)
    as_of: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class CashMovementCreate(BaseModel):
    """Record a cash movement (deposit, withdrawal, transfer, etc.)."""
    movement_id: str = Field(default="")
    account_id: str
    movement_type: CashMovementType = CashMovementType.DEPOSIT
    rail: CashMovementRail = CashMovementRail.ACH
    amount: float
    currency: str = Field(default="USD")
    counterparty_account_id: str = Field(default="", description="For transfers between accounts")
    reference: str = Field(default="")
    status: str = Field(default="completed")
    initiated_at: str = Field(default="")
    settled_at: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ComplianceActionCreate(BaseModel):
    """Record an internal compliance/business action."""
    action_id: str = Field(default="")
    entity_id: str = Field(..., description="Entity this action affects")
    account_id: str = Field(default="")
    action_type: ComplianceActionType
    reason: str = Field(default="")
    performed_by: str = Field(default="", description="Internal actor/system")
    details: dict[str, Any] = Field(default_factory=dict)
    effective_at: str = Field(default="")
    expires_at: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class BusinessEventCreate(BaseModel):
    """Record a business application behavioral event."""
    event_type: BusinessEventType
    entity_id: str = Field(default="", description="User/profile ID")
    account_id: str = Field(default="")
    session_id: str = Field(default="")
    instrument_id: str = Field(default="", description="For quote/watchlist/chart events")
    domain: str = Field(default="", description="App/website domain")
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default="")
    source: str = Field(default="sdk")
    source_tag: str = Field(default="")
