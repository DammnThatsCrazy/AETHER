"""Tenant-scoped card-linked payment repositories.

The V1 store is deliberately observation-only and idempotent. It persists
normalized facts and benchmark observations, never raw card/KYC/bank data.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from shared.store import get_store

from services.card_linked_payments.models import (
    CardBenchmarkObservation,
    CardLinkedFlowObserved,
    reject_blocked_fields,
)


def _to_record(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


class CardLinkedFlowRepository:
    def __init__(self) -> None:
        self._store = get_store("card_linked_flows")

    @staticmethod
    def key(tenant_id: str, flow_id: str) -> str:
        return f"{tenant_id}:{flow_id}"

    async def upsert(self, flow: CardLinkedFlowObserved | dict[str, Any]) -> dict[str, Any]:
        record = _to_record(flow)
        reject_blocked_fields(record)
        await self._store.set(self.key(record["tenant_id"], record["id"]), record)
        return record

    async def get(self, tenant_id: str, flow_id: str) -> dict[str, Any] | None:
        return await self._store.get(self.key(tenant_id, flow_id))

    async def list_for_tenant(self, tenant_id: str, **filters: Any) -> list[dict[str, Any]]:
        rows = await self._store.find(tenant_id=tenant_id)
        return _filter(rows, filters)

    async def list_for_entity(self, tenant_id: str, entity_id: str, **filters: Any) -> list[dict[str, Any]]:
        rows = await self.list_for_tenant(tenant_id, **filters)
        return [r for r in rows if entity_id in {r.get("canonical_entity_id"), r.get("user_id"), r.get("agent_id"), r.get("org_id"), r.get("wallet_address_hash")}]

    async def list_for_campaign(self, tenant_id: str, campaign_id: str, **filters: Any) -> list[dict[str, Any]]:
        return await self.list_for_tenant(tenant_id, campaign_id=campaign_id, **filters)

    async def list_all(self) -> list[dict[str, Any]]:
        return await self._store.find()


class CardBenchmarkRepository:
    def __init__(self) -> None:
        self._store = get_store("card_linked_benchmarks")

    @staticmethod
    def key(record: dict[str, Any]) -> str:
        return ":".join([
            record["tenant_id"], record["catalog_entity_id"], record["metric_name"],
            record["metric_window"], record["observed_at"],
        ])

    async def upsert(self, observation: CardBenchmarkObservation | dict[str, Any]) -> dict[str, Any]:
        record = _to_record(observation)
        record.setdefault("basis", "benchmark_only")
        record.setdefault("source", "paymentscan")
        record.setdefault("confidence", "weak")
        await self._store.set(self.key(record), record)
        return record

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._store.find(tenant_id=tenant_id)

    async def list_all(self) -> list[dict[str, Any]]:
        return await self._store.find()


class CardLinkedPaymentRepositories:
    def __init__(self) -> None:
        self.flows = CardLinkedFlowRepository()
        self.benchmarks = CardBenchmarkRepository()


_repositories: CardLinkedPaymentRepositories | None = None


def get_card_linked_repositories() -> CardLinkedPaymentRepositories:
    global _repositories
    if _repositories is None:
        _repositories = CardLinkedPaymentRepositories()
    return _repositories


def _filter(rows: Iterable[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ok = True
        for key, value in filters.items():
            if value in (None, "", [], {}):
                continue
            if key == "volume_min" and row.get("amount_usd") is not None:
                ok = float(row.get("amount_usd") or 0) >= float(value)
            elif key == "volume_max" and row.get("amount_usd") is not None:
                ok = float(row.get("amount_usd") or 0) <= float(value)
            elif key == "card_program" and row.get("card_program_id") != value:
                ok = False
            elif key == "asset_currency" and row.get("asset") != value:
                ok = False
            elif row.get(key) != value:
                ok = False
            if not ok:
                break
        if ok:
            out.append(row)
    return sorted(out, key=lambda r: r.get("occurred_at", ""))
