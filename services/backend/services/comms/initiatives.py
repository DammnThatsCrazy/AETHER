"""Cross-channel campaign initiatives — macro rollup over canonical campaigns
(Phase 10, ADR-C9).

An initiative groups canonical campaigns from any channel (email, paid
social, search, push, partner) under one macro umbrella, e.g.:

    Product Launch Initiative
    ├── Email campaign        (canonical UUID, provider reconciliation)
    ├── Paid-social campaign
    └── Search campaign

Each member keeps its own canonical UUID, funnel, and message hierarchy;
the initiative provides the rollup only. There is no second campaign
registry — members reference rows in the existing ``campaigns`` table.

Storage: ``campaign_initiatives`` + ``campaign_initiative_members``
(created by migration 20260703_comms_intel). Local/test mode uses
in-memory stores, mirroring the other comms repositories.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger, metrics
from repositories.repos import get_pool

logger = get_logger("aether.comms.initiatives")

_local_initiatives: dict[str, dict[str, Any]] = {}
_local_members: dict[str, set[str]] = {}  # "{tenant}:{initiative_id}" → {campaign_id}


def reset_local_initiatives() -> None:
    """Test helper — clears in-memory initiative stores."""
    _local_initiatives.clear()
    _local_members.clear()


class InitiativeRepository:
    """Durable access to campaign_initiatives / campaign_initiative_members."""

    async def _pool(self):
        return await get_pool()

    async def create(
        self, tenant_id: str, name: str, *,
        description: Optional[str] = None,
        created_by: str = "tenant",
        properties: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        initiative = {
            "initiative_id": str(uuid4()),
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "status": "active",
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "properties": properties or {},
        }
        pool = await self._pool()
        if pool is None:
            _local_initiatives[f"{tenant_id}:{initiative['initiative_id']}"] = initiative
            return initiative
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO campaign_initiatives (
                    initiative_id, tenant_id, name, description, status,
                    created_by, properties
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                initiative["initiative_id"], tenant_id, name, description,
                "active", created_by, json.dumps(properties or {}),
            )
        metrics.increment("comms_initiatives_created_total", labels={"tenant_id": tenant_id})
        return initiative

    async def get(self, tenant_id: str, initiative_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return _local_initiatives.get(f"{tenant_id}:{initiative_id}")
        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                "SELECT * FROM campaign_initiatives WHERE tenant_id = $1 AND initiative_id = $2",
                tenant_id, initiative_id,
            )
        return dict(rec) if rec else None

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                i for k, i in sorted(_local_initiatives.items())
                if i.get("tenant_id") == tenant_id
            ][:limit]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM campaign_initiatives
                WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT $2
                """,
                tenant_id, limit,
            )
        return [dict(r) for r in records]

    async def add_member(
        self, tenant_id: str, initiative_id: str, campaign_id: str,
        *, added_by: str = "tenant",
    ) -> bool:
        """Attach a canonical campaign. Idempotent; returns False on duplicate."""
        pool = await self._pool()
        if pool is None:
            members = _local_members.setdefault(f"{tenant_id}:{initiative_id}", set())
            if campaign_id in members:
                return False
            members.add(campaign_id)
            return True
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO campaign_initiative_members (
                    tenant_id, initiative_id, campaign_id, added_by
                ) VALUES ($1,$2,$3,$4)
                ON CONFLICT DO NOTHING
                """,
                tenant_id, initiative_id, campaign_id, added_by,
            )
        return result.endswith("1")

    async def remove_member(self, tenant_id: str, initiative_id: str, campaign_id: str) -> bool:
        pool = await self._pool()
        if pool is None:
            members = _local_members.get(f"{tenant_id}:{initiative_id}", set())
            if campaign_id not in members:
                return False
            members.discard(campaign_id)
            return True
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM campaign_initiative_members
                WHERE tenant_id = $1 AND initiative_id = $2 AND campaign_id = $3
                """,
                tenant_id, initiative_id, campaign_id,
            )
        return result.endswith("1")

    async def member_campaign_ids(self, tenant_id: str, initiative_id: str) -> list[str]:
        pool = await self._pool()
        if pool is None:
            return sorted(_local_members.get(f"{tenant_id}:{initiative_id}", set()))
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT campaign_id FROM campaign_initiative_members
                WHERE tenant_id = $1 AND initiative_id = $2 ORDER BY added_at
                """,
                tenant_id, initiative_id,
            )
        return [str(r["campaign_id"]) for r in records]


class InitiativeRollupService:
    """Macro rollup across member campaigns.

    Communications metrics come from the per-campaign comms funnel; each
    channel campaign keeps its own funnel and the rollup sums observed
    populations without inventing cross-channel dedupe (recipients are
    only deduped within a campaign — cross-channel identity overlap is a
    documented limitation surfaced in the response).
    """

    def __init__(self) -> None:
        self._repo = InitiativeRepository()

    async def rollup(self, tenant_id: str, initiative_id: str) -> Optional[dict[str, Any]]:
        initiative = await self._repo.get(tenant_id, initiative_id)
        if initiative is None:
            return None
        campaign_ids = await self._repo.member_campaign_ids(tenant_id, initiative_id)

        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()

        members: list[dict[str, Any]] = []
        totals = {
            "delivered": 0, "human_clicks": 0, "replies": 0,
            "hard_bounces": 0, "complaints": 0, "unsubscribes": 0,
            "machine_events": 0, "total_events": 0,
        }
        for campaign_id in campaign_ids:
            funnel = {k: int(v or 0) for k, v in
                      (await facts.campaign_funnel(tenant_id, campaign_id)).items()}
            campaign_meta = await self._campaign_meta(tenant_id, campaign_id)
            members.append({
                "campaign_id": campaign_id,
                "name": campaign_meta.get("name"),
                "channel": campaign_meta.get("channel"),
                "delivered": funnel.get("delivered", 0),
                "human_clicks": funnel.get("human_clicks", 0),
                "replies": funnel.get("replies", 0),
                "machine_events": funnel.get("machine_events", 0),
                "total_events": funnel.get("total_events", 0),
            })
            for key in totals:
                totals[key] += funnel.get(key, 0)

        return {
            "initiative": {
                k: (str(v) if hasattr(v, "isoformat") else v)
                for k, v in initiative.items()
            },
            "member_count": len(campaign_ids),
            "members": members,
            "totals": totals,
            "notes": [
                "Totals sum per-campaign unique recipients; cross-channel "
                "identity overlap is not deduplicated at the initiative level.",
            ],
        }

    async def _campaign_meta(self, tenant_id: str, campaign_id: str) -> dict[str, Any]:
        try:
            from uuid import UUID
            from services.campaign.repository import CampaignRegistryRepository
            campaign = await CampaignRegistryRepository().get_by_id(tenant_id, UUID(campaign_id))
            return dict(campaign) if campaign else {}
        except Exception:
            return {}
