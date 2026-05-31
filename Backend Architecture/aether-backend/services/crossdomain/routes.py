"""
Aether Cross-Domain — API Routes

Provides TradFi/Web2/business entity management, financial account tracking,
instrument registry, trade lifecycle, compliance actions, business events,
and cross-domain identity fusion endpoints.

Endpoints (38 total):
  Institutions (3): register, list, get
  Accounts (4): register, list by owner/institution, get
  Instruments (4): register, list, search, get
  Positions (3): record, list by account, list by instrument
  Orders (3): record, list by account, get
  Executions (3): record, list by order, list by account
  Balances (2): record, get latest
  Cash Movements (2): record, list by account
  Compliance Actions (2): record, list by entity
  Business Events (3): record, list by entity, list by instrument
  Cross-Domain Links (3): create, list for entity, list high-confidence
  Fusion (3): entity exposure, cross-domain profile, identity candidates
  Coverage (2): status, health
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Query

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.decorators import require_permission

from services.crossdomain.registries import (
    InstitutionRegistry,
    AccountRegistry,
    InstrumentRegistry,
    PositionRepository,
    OrderRepository,
    ExecutionRepository,
    BalanceRepository,
    CashMovementRepository,
    ComplianceActionRepository,
    BusinessEventRepository,
    CrossDomainLinkRepository,
)

logger = get_logger("aether.crossdomain.routes")
router = APIRouter(prefix="/v1/crossdomain", tags=["crossdomain"])

# ── Repository singletons ──────────────────────────────────────────────
institution_reg = InstitutionRegistry()
account_reg = AccountRegistry()
instrument_reg = InstrumentRegistry()
position_repo = PositionRepository()
order_repo = OrderRepository()
execution_repo = ExecutionRepository()
balance_repo = BalanceRepository()
cash_movement_repo = CashMovementRepository()
compliance_repo = ComplianceActionRepository()
business_event_repo = BusinessEventRepository()
link_repo = CrossDomainLinkRepository()


# ═══════════════════════════════════════════════════════════════════════════
# INSTITUTIONS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/institutions")
async def register_institution(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await institution_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "institution_id": body.get("institution_id"), "data": result}

@router.get("/institutions")
async def list_institutions(
    request: Request,
    institution_type: str = Query("", description="Filter by type"),
    q: str = Query("", description="Search query"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    if q:
        institutions = await institution_reg.search(q, limit)
    elif institution_type:
        institutions = await institution_reg.list_by_type(institution_type, limit)
    else:
        institutions = await institution_reg.find_many(limit=limit)
    return {"institutions": institutions, "count": len(institutions)}

@router.get("/institutions/{institution_id}")
async def get_institution(request: Request, institution_id: str) -> dict:
    inst = await institution_reg.find_by_id(institution_id)
    if not inst:
        return {"error": "Institution not found", "institution_id": institution_id}
    return {"institution": inst}


# ═══════════════════════════════════════════════════════════════════════════
# ACCOUNTS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/accounts")
async def register_account(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await account_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "account_id": body.get("account_id"), "data": result}

@router.get("/accounts")
async def list_accounts(
    request: Request,
    owner: str = Query("", description="Filter by owner entity ID"),
    institution: str = Query("", description="Filter by institution ID"),
    account_type: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    if owner:
        accounts = await account_reg.list_by_owner(owner, limit)
    elif institution:
        accounts = await account_reg.list_by_institution(institution, limit)
    elif account_type:
        accounts = await account_reg.list_by_type(account_type, limit)
    else:
        accounts = await account_reg.find_many(limit=limit)
    return {"accounts": accounts, "count": len(accounts)}

@router.get("/accounts/{account_id}")
async def get_account(request: Request, account_id: str) -> dict:
    account = await account_reg.find_by_id(account_id)
    if not account:
        return {"error": "Account not found", "account_id": account_id}
    return {"account": account}

@router.get("/accounts/{account_id}/positions")
async def list_account_positions(request: Request, account_id: str, limit: int = Query(200)) -> dict:
    positions = await position_repo.list_by_account(account_id, limit)
    return {"account_id": account_id, "positions": positions, "count": len(positions)}


# ═══════════════════════════════════════════════════════════════════════════
# INSTRUMENTS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/instruments")
async def register_instrument(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await instrument_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "instrument_id": body.get("instrument_id"), "data": result}

@router.get("/instruments")
async def list_instruments(
    request: Request,
    instrument_type: str = Query(""),
    issuer: str = Query(""),
    q: str = Query(""),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    if q:
        instruments = await instrument_reg.search(q, limit)
    elif instrument_type:
        instruments = await instrument_reg.list_by_type(instrument_type, limit)
    elif issuer:
        instruments = await instrument_reg.list_by_issuer(issuer, limit)
    else:
        instruments = await instrument_reg.find_many(limit=limit)
    return {"instruments": instruments, "count": len(instruments)}

@router.get("/instruments/{instrument_id}")
async def get_instrument(request: Request, instrument_id: str) -> dict:
    instrument = await instrument_reg.find_by_id(instrument_id)
    if not instrument:
        return {"error": "Instrument not found", "instrument_id": instrument_id}
    return {"instrument": instrument}

@router.get("/instruments/symbol/{symbol}")
async def get_instrument_by_symbol(request: Request, symbol: str) -> dict:
    instrument = await instrument_reg.get_by_symbol(symbol)
    if not instrument:
        return {"error": "Instrument not found", "symbol": symbol}
    return {"instrument": instrument}


# ═══════════════════════════════════════════════════════════════════════════
# POSITIONS / ORDERS / EXECUTIONS / BALANCES / CASH
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/positions")
async def record_position(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await position_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/positions/instrument/{instrument_id}")
async def list_positions_by_instrument(request: Request, instrument_id: str, limit: int = Query(200)) -> dict:
    positions = await position_repo.list_by_instrument(instrument_id, limit)
    return {"instrument_id": instrument_id, "positions": positions, "count": len(positions)}

@router.post("/orders")
async def record_order(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await order_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/orders/{account_id}")
async def list_orders_by_account(request: Request, account_id: str, limit: int = Query(200)) -> dict:
    orders = await order_repo.list_by_account(account_id, limit)
    return {"account_id": account_id, "orders": orders, "count": len(orders)}

@router.post("/executions")
async def record_execution(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await execution_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/executions/order/{order_id}")
async def list_executions_by_order(request: Request, order_id: str, limit: int = Query(50)) -> dict:
    executions = await execution_repo.list_by_order(order_id, limit)
    return {"order_id": order_id, "executions": executions, "count": len(executions)}

@router.get("/executions/account/{account_id}")
async def list_executions_by_account(request: Request, account_id: str, limit: int = Query(200)) -> dict:
    executions = await execution_repo.list_by_account(account_id, limit)
    return {"account_id": account_id, "executions": executions, "count": len(executions)}

@router.post("/balances")
async def record_balance(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await balance_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/balances/{account_id}/latest")
async def get_latest_balance(request: Request, account_id: str) -> dict:
    balance = await balance_repo.latest_for_account(account_id)
    if not balance:
        return {"error": "No balance found", "account_id": account_id}
    return {"balance": balance}

@router.post("/cash-movements")
async def record_cash_movement(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await cash_movement_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/cash-movements/{account_id}")
async def list_cash_movements(request: Request, account_id: str, limit: int = Query(200)) -> dict:
    movements = await cash_movement_repo.list_by_account(account_id, limit)
    return {"account_id": account_id, "movements": movements, "count": len(movements)}


# ═══════════════════════════════════════════════════════════════════════════
# COMPLIANCE / BUSINESS EVENTS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/compliance/actions")
async def record_compliance_action(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await compliance_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/compliance/actions/{entity_id}")
async def list_compliance_actions(request: Request, entity_id: str, limit: int = Query(100)) -> dict:
    actions = await compliance_repo.list_by_entity(entity_id, limit)
    return {"entity_id": entity_id, "actions": actions, "count": len(actions)}

@router.post("/events")
async def record_business_event(request: Request) -> dict:
    body = await request.json()
    result = await business_event_repo.record(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}

@router.get("/events/entity/{entity_id}")
async def list_events_by_entity(request: Request, entity_id: str, limit: int = Query(200)) -> dict:
    events = await business_event_repo.list_by_entity(entity_id, limit)
    return {"entity_id": entity_id, "events": events, "count": len(events)}

@router.get("/events/instrument/{instrument_id}")
async def list_events_by_instrument(request: Request, instrument_id: str, limit: int = Query(200)) -> dict:
    events = await business_event_repo.list_by_instrument(instrument_id, limit)
    return {"instrument_id": instrument_id, "events": events, "count": len(events)}


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-DOMAIN IDENTITY LINKS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/links")
async def create_identity_link(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await link_repo.create_link(body, request.state.tenant_id)
    return {"status": "linked", "data": result}

@router.get("/links/{entity_id}")
async def list_entity_links(request: Request, entity_id: str, limit: int = Query(100)) -> dict:
    links = await link_repo.list_for_entity(entity_id, limit)
    return {"entity_id": entity_id, "links": links, "count": len(links)}

@router.get("/links/high-confidence")
async def list_high_confidence_links(
    request: Request,
    min_confidence: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(200),
) -> dict:
    links = await link_repo.list_high_confidence(min_confidence, limit)
    return {"links": links, "count": len(links), "min_confidence": min_confidence}


# ═══════════════════════════════════════════════════════════════════════════
# FUSION / INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/fusion/exposure/{entity_id}")
async def get_entity_exposure(request: Request, entity_id: str) -> dict:
    """
    Cross-domain exposure for an entity: accounts, instruments, wallets,
    protocols, apps, and domains they're connected to.
    """
    accounts = await account_reg.list_by_owner(entity_id, 100)
    links = await link_repo.list_for_entity(entity_id, 100)
    compliance_actions = await compliance_repo.list_by_entity(entity_id, 50)

    # Aggregate positions across all accounts
    all_positions: list[dict] = []
    for acct in accounts:
        acct_id = acct.get("account_id", "")
        positions = await position_repo.list_by_account(acct_id, 200)
        all_positions.extend(positions)

    # Get unique instruments held
    instrument_ids = list({p.get("instrument_id", "") for p in all_positions if p.get("instrument_id")})

    return {
        "entity_id": entity_id,
        "accounts": len(accounts),
        "positions": len(all_positions),
        "unique_instruments": len(instrument_ids),
        "instrument_ids": instrument_ids[:50],
        "cross_domain_links": len(links),
        "compliance_actions": len(compliance_actions),
        "domains": list({l.get("domains", []) for l in links if isinstance(l.get("domains"), str)}),
        "computed_at": utc_now(),
    }

@router.get("/fusion/profile/{entity_id}")
async def get_cross_domain_profile(request: Request, entity_id: str) -> dict:
    """
    Unified cross-domain profile: identity links, accounts, positions,
    recent activity, compliance status, and behavioral events.
    """
    accounts = await account_reg.list_by_owner(entity_id, 50)
    links = await link_repo.list_for_entity(entity_id, 50)
    events = await business_event_repo.list_by_entity(entity_id, 50)
    compliance_actions = await compliance_repo.list_by_entity(entity_id, 20)

    # Latest balances per account
    balances: list[dict] = []
    for acct in accounts:
        bal = await balance_repo.latest_for_account(acct.get("account_id", ""))
        if bal:
            balances.append(bal)

    return {
        "entity_id": entity_id,
        "identity": {
            "cross_domain_links": links[:20],
            "domains_present": list({d for l in links for d in (l.get("domains") or []) if isinstance(d, str)}),
        },
        "tradfi": {
            "accounts": accounts[:20],
            "balances": balances[:20],
            "account_count": len(accounts),
        },
        "activity": {
            "recent_events": events[:20],
            "event_count": len(events),
        },
        "compliance": {
            "actions": compliance_actions[:10],
            "action_count": len(compliance_actions),
        },
        "computed_at": utc_now(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# COVERAGE STATUS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/coverage/status")
async def get_coverage_status(request: Request) -> dict:
    institutions = await institution_reg.find_many(limit=5000)
    accounts = await account_reg.find_many(limit=10000)
    instruments = await instrument_reg.find_many(limit=10000)
    links = await link_repo.find_many(limit=10000)
    return {
        "coverage": {
            "institutions": len(institutions),
            "accounts": len(accounts),
            "instruments": len(instruments),
            "cross_domain_links": len(links),
        },
        "computed_at": utc_now(),
    }

@router.get("/coverage/health")
async def coverage_health(request: Request) -> dict:
    inst_count = len(await institution_reg.find_many(limit=100))
    return {
        "status": "healthy" if inst_count > 0 else "unseeded",
        "institutions": inst_count,
    }
