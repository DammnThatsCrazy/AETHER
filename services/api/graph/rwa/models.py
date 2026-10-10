"""
RWA Intelligence Graph — Data Models

Canonical objects for tokenized real-world assets, their legal/policy
structure, economic/cashflow events, and identity/behavior linkages.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field
from shared.common.common import utc_now


# ═══════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════

class RWAAssetClass(str, Enum):
    TREASURY = "tokenized_treasury"
    MONEY_MARKET = "money_market_fund"
    PRIVATE_CREDIT = "private_credit"
    FUND_INTEREST = "fund_interest"
    STRUCTURED_CREDIT = "structured_credit"
    TOKENIZED_DEPOSIT = "tokenized_deposit"
    REAL_ESTATE = "real_estate"
    INVOICE = "invoice_receivable"
    TRADE_FINANCE = "trade_finance"
    COMMODITY = "commodity"
    CARBON = "carbon_credit"
    EQUITY = "tokenized_equity"
    ETF = "tokenized_etf"
    OTHER = "other"


class RWAChain(str, Enum):
    ETHEREUM = "ethereum"
    BASE = "base"
    ARBITRUM = "arbitrum"
    POLYGON = "polygon"
    SOLANA = "solana"
    STELLAR = "stellar"
    AVALANCHE = "avalanche"
    PERMISSIONED_EVM = "permissioned_evm"
    OTHER = "other"


class PolicyType(str, Enum):
    WHITELIST = "whitelist"
    ACCREDITATION = "accreditation"
    JURISDICTION = "jurisdiction"
    LOCKUP = "lockup"
    HOLDER_CAP = "holder_cap"
    SECONDARY_TRANSFER = "secondary_transfer"
    AML_KYC = "aml_kyc"


class CashflowType(str, Enum):
    COUPON = "coupon"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    REDEMPTION = "redemption"
    SERVICING = "servicing"
    FEE = "fee"
    SETTLEMENT = "settlement"
    RESERVE_MOVEMENT = "reserve_movement"
    NAV_UPDATE = "nav_update"
    ATTESTATION = "attestation"
    IMPAIRMENT = "impairment"
    DEFAULT = "default"
    RESTRUCTURING = "restructuring"


class ExposureType(str, Enum):
    DIRECT = "direct"
    INFERRED = "inferred"
    BENEFICIAL_OWNER = "beneficial_owner"
    OMNIBUS = "omnibus"
    CUSTODY = "custody"
    DISTRIBUTOR = "distributor"


# ═══════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════

class RWAAssetCreate(BaseModel):
    name: str
    asset_class: RWAAssetClass
    chain: RWAChain = RWAChain.ETHEREUM
    token_address: str = ""
    issuer_id: str = ""
    issuer_name: str = ""
    custodian_id: str = ""
    custodian_name: str = ""
    total_supply: float = 0.0
    nav_per_token: float = 0.0
    currency: str = "USD"
    jurisdiction: str = ""
    metadata: dict = Field(default_factory=dict)
    source_tag: str = ""


class PolicyCreate(BaseModel):
    asset_id: str
    policy_type: PolicyType
    rules: dict = Field(default_factory=dict)
    jurisdictions: list[str] = Field(default_factory=list)
    effective_from: str = ""
    effective_until: str = ""
    source_tag: str = ""


class CashflowEventCreate(BaseModel):
    asset_id: str
    cashflow_type: CashflowType
    amount: float = 0.0
    currency: str = "USD"
    counterparty_id: str = ""
    reference: str = ""
    metadata: dict = Field(default_factory=dict)
    source_tag: str = ""


class ExposureQuery(BaseModel):
    entity_id: str
    entity_type: str = "wallet"
    include_inferred: bool = True
    include_beneficial: bool = True
    include_omnibus: bool = True


class PolicySimulation(BaseModel):
    asset_id: str
    from_entity: str
    to_entity: str
    amount: float = 0.0
    transfer_type: str = "secondary"


# ═══════════════════════════════════════════════════════════════════
# RECORD FACTORIES
# ═══════════════════════════════════════════════════════════════════

def make_rwa_asset(data: RWAAssetCreate, tenant_id: str = "") -> dict:
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "asset_class": data.asset_class.value,
        "chain": data.chain.value,
        "token_address": data.token_address,
        "issuer_id": data.issuer_id,
        "issuer_name": data.issuer_name,
        "custodian_id": data.custodian_id,
        "custodian_name": data.custodian_name,
        "total_supply": data.total_supply,
        "nav_per_token": data.nav_per_token,
        "currency": data.currency,
        "jurisdiction": data.jurisdiction,
        "metadata": data.metadata,
        "source_tag": data.source_tag,
        "tenant_id": tenant_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def make_policy(data: PolicyCreate, tenant_id: str = "") -> dict:
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "asset_id": data.asset_id,
        "policy_type": data.policy_type.value,
        "rules": data.rules,
        "jurisdictions": data.jurisdictions,
        "effective_from": data.effective_from or now,
        "effective_until": data.effective_until,
        "source_tag": data.source_tag,
        "tenant_id": tenant_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def make_cashflow_event(data: CashflowEventCreate, tenant_id: str = "") -> dict:
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "asset_id": data.asset_id,
        "cashflow_type": data.cashflow_type.value,
        "amount": data.amount,
        "currency": data.currency,
        "counterparty_id": data.counterparty_id,
        "reference": data.reference,
        "metadata": data.metadata,
        "source_tag": data.source_tag,
        "tenant_id": tenant_id,
        "event_at": now,
        "created_at": now,
        "updated_at": now,
    }
