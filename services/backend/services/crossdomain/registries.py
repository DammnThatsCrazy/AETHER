"""
Aether Cross-Domain — Registries

All registries extend BaseRepository (asyncpg PostgreSQL in staging/production,
in-memory fallback for local development). Reuses the Web3 registry pattern.
"""

from __future__ import annotations

import uuid
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.crossdomain.registries")


class InstitutionRegistry(BaseRepository):
    """Financial and business institution registry."""
    def __init__(self) -> None:
        super().__init__("cd_institutions")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("institution_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_type(self, institution_type: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"institution_type": institution_type}, limit=limit)

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        all_records = await self.find_many(limit=2000)
        q = query.lower()
        return [r for r in all_records
                if q in r.get("canonical_name", "").lower()
                or q in r.get("institution_id", "").lower()
                or any(q in a.lower() for a in r.get("aliases", []))][:limit]


class AccountRegistry(BaseRepository):
    """Financial account registry (brokerage, bank, custody, etc.)."""
    def __init__(self) -> None:
        super().__init__("cd_accounts")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("account_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_owner(self, owner_entity_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"owner_entity_id": owner_entity_id}, limit=limit)

    async def list_by_institution(self, institution_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"institution_id": institution_id}, limit=limit)

    async def list_by_type(self, account_type: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"account_type": account_type}, limit=limit)


class InstrumentRegistry(BaseRepository):
    """Market instrument registry (stocks, ETFs, options, bonds, etc.)."""
    def __init__(self) -> None:
        super().__init__("cd_instruments")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("instrument_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_symbol(self, symbol: str) -> Optional[dict]:
        results = await self.find_many(filters={"symbol": symbol.upper()}, limit=1)
        return results[0] if results else None

    async def get_by_cusip(self, cusip: str) -> Optional[dict]:
        results = await self.find_many(filters={"cusip": cusip}, limit=1)
        return results[0] if results else None

    async def list_by_type(self, instrument_type: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"instrument_type": instrument_type}, limit=limit)

    async def list_by_issuer(self, issuer_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"issuer_id": issuer_id}, limit=limit)

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        all_records = await self.find_many(limit=5000)
        q = query.lower()
        return [r for r in all_records
                if q in r.get("symbol", "").lower()
                or q in r.get("name", "").lower()
                or q in r.get("instrument_id", "").lower()][:limit]


class PositionRepository(BaseRepository):
    """Account position records."""
    def __init__(self) -> None:
        super().__init__("cd_positions")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = data.get("position_id", f"{data.get('account_id', '')}:{data.get('instrument_id', '')}:{data.get('as_of', utc_now())}")
        data["position_id"] = record_id
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_account(self, account_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"account_id": account_id}, limit=limit)

    async def list_by_instrument(self, instrument_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"instrument_id": instrument_id}, limit=limit)


class OrderRepository(BaseRepository):
    """Trade order records."""
    def __init__(self) -> None:
        super().__init__("cd_orders")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = data.get("order_id", str(uuid.uuid4()))
        data.setdefault("submitted_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_account(self, account_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"account_id": account_id}, limit=limit, sort_by="submitted_at")


class ExecutionRepository(BaseRepository):
    """Trade execution/fill records."""
    def __init__(self) -> None:
        super().__init__("cd_executions")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = data.get("execution_id", str(uuid.uuid4()))
        data.setdefault("executed_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_order(self, order_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"order_id": order_id}, limit=limit)

    async def list_by_account(self, account_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"account_id": account_id}, limit=limit, sort_by="executed_at")


class BalanceRepository(BaseRepository):
    """Account balance snapshot records."""
    def __init__(self) -> None:
        super().__init__("cd_balances")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = f"{data.get('account_id', '')}:{data.get('as_of', utc_now())}"
        return await self.upsert(record_id, data, tenant_id)

    async def latest_for_account(self, account_id: str) -> Optional[dict]:
        results = await self.find_many(filters={"account_id": account_id}, limit=1, sort_by="as_of", sort_order="desc")
        return results[0] if results else None


class CashMovementRepository(BaseRepository):
    """Cash movement records (deposits, withdrawals, transfers)."""
    def __init__(self) -> None:
        super().__init__("cd_cash_movements")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = data.get("movement_id", str(uuid.uuid4()))
        data["movement_id"] = record_id
        data.setdefault("initiated_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_account(self, account_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"account_id": account_id}, limit=limit, sort_by="initiated_at")


class ComplianceActionRepository(BaseRepository):
    """Internal compliance/business action records."""
    def __init__(self) -> None:
        super().__init__("cd_compliance_actions")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = data.get("action_id", str(uuid.uuid4()))
        data["action_id"] = record_id
        data.setdefault("effective_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_entity(self, entity_id: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"entity_id": entity_id}, limit=limit, sort_by="effective_at")


class BusinessEventRepository(BaseRepository):
    """Business application behavioral events."""
    def __init__(self) -> None:
        super().__init__("cd_business_events")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = str(uuid.uuid4())
        data.setdefault("timestamp", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_entity(self, entity_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"entity_id": entity_id}, limit=limit, sort_by="timestamp")

    async def list_by_instrument(self, instrument_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"instrument_id": instrument_id}, limit=limit, sort_by="timestamp")


class CrossDomainLinkRepository(BaseRepository):
    """Cross-domain identity links with confidence scoring."""
    def __init__(self) -> None:
        super().__init__("cd_identity_links")

    async def create_link(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = f"{data.get('source_entity_id', '')}:{data.get('target_entity_id', '')}:{data.get('link_signal', '')}"
        data.setdefault("created_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def list_for_entity(self, entity_id: str, limit: int = 100) -> list[dict]:
        all_links = await self.find_many(limit=5000)
        return [l for l in all_links
                if l.get("source_entity_id") == entity_id
                or l.get("target_entity_id") == entity_id][:limit]

    async def list_high_confidence(self, min_confidence: float = 0.7, limit: int = 200) -> list[dict]:
        all_links = await self.find_many(limit=5000)
        return [l for l in all_links if l.get("confidence", 0) >= min_confidence][:limit]
