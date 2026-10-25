"""Explicit, append-only campaign-to-population association authority.

These links are tenant operator assertions against exact canonical campaign
and population records. They do not infer cohort membership from touchpoints,
profiles, or shared identifiers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from graph.operational_intelligence.models import EvidenceRef
from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_CAMPAIGN_POPULATION_LINKS = 100
CampaignPopulationLinkType = Literal["linked", "unlinked"]


class CampaignPopulationLinkAuthorityError(RuntimeError):
    """A link is not bound to canonical tenant campaign/population records."""


class CampaignPopulationLinkConflict(CampaignPopulationLinkAuthorityError):
    """An idempotency event was replayed with conflicting assertion content."""


class CampaignPopulationLinkInput(BaseModel):
    """Caller assertions without tenant or actor identity fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    population_id: str = Field(min_length=1, max_length=256)
    event_type: CampaignPopulationLinkType
    source_record_id: str = Field(min_length=1, max_length=512)
    source_revision_id: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    source_observed_at: datetime
    effective_at: datetime

    @field_validator("source_observed_at", "effective_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CampaignPopulationLinkRead:
    """Bounded latest explicit association state per exact population ID."""

    tenant_id: str
    campaign_id: str
    rows: tuple[dict[str, Any], ...]
    available: bool
    truncated: bool = False
    reason: Optional[str] = None


class CampaignPopulationLinkStore(Protocol):
    async def append(self, event: dict[str, Any]) -> dict[str, Any]: ...

    async def latest_for_campaign(
        self, tenant_id: str, campaign_id: str, *, limit: int, effective_as_of: datetime
    ) -> tuple[list[dict[str, Any]], bool]: ...


class RepositoryCampaignPopulationLinkStore:
    """Tenant/campaign exact event ledger with DB-free test fallback."""

    _local_events: dict[tuple[str, str], dict[str, Any]] = {}

    async def append(self, event: dict[str, Any]) -> dict[str, Any]:
        from repositories.repos import get_pool

        key = (event["tenant_id"], event["link_event_id"])
        pool = await get_pool()
        if pool is None:
            existing = self._local_events.get(key)
            if existing is not None:
                if _idempotent_payload(existing) == _idempotent_payload(event):
                    return dict(existing)
                raise CampaignPopulationLinkConflict("campaign population event conflicts with an existing event")
            self._local_events[key] = dict(event)
            return dict(event)

        async with pool.acquire() as connection:
            status = await connection.execute(
                """INSERT INTO campaign_population_link_events (
                       tenant_id, link_event_id, campaign_id, population_id,
                       event_type, source_id, source_record_id, source_revision_id,
                       source_event_id, actor_id, actor_type, source_observed_at,
                       effective_at, recorded_at, evidence_refs, payload
                   ) VALUES (
                       $1, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9,
                       $10, $11, $12, $13, $14, $15::jsonb, $16::jsonb
                   ) ON CONFLICT DO NOTHING""",
                event["tenant_id"], event["link_event_id"], event["campaign_id"],
                event["population_id"], event["event_type"], event["source_id"],
                event["source_record_id"], event["source_revision_id"], event["source_event_id"],
                event["actor_id"], event["actor_type"], _as_datetime(event["source_observed_at"]),
                _as_datetime(event["effective_at"]), _as_datetime(event["recorded_at"]),
                json.dumps(event["evidence_refs"], default=str), json.dumps(event, default=str),
            )
            if status.endswith(" 1"):
                return dict(event)
            existing = await connection.fetchrow(
                """SELECT payload FROM campaign_population_link_events
                   WHERE tenant_id = $1 AND source_id = $2 AND source_event_id = $3""",
                event["tenant_id"], event["source_id"], event["source_event_id"],
            )
        if existing is None:
            raise CampaignPopulationLinkConflict("campaign population event idempotency state is inconsistent")
        payload = _decode_mapping(existing["payload"])
        if _idempotent_payload(payload) != _idempotent_payload(event):
            raise CampaignPopulationLinkConflict("campaign population event conflicts with an existing event")
        return payload

    async def latest_for_campaign(
        self, tenant_id: str, campaign_id: str, *, limit: int, effective_as_of: datetime
    ) -> tuple[list[dict[str, Any]], bool]:
        from repositories.repos import get_pool

        effective_anchor = _as_datetime(effective_as_of)
        if effective_anchor is None:
            raise ValueError("current campaign population read requires a timezone-aware instant")
        bounded = min(max(int(limit), 1), MAX_CAMPAIGN_POPULATION_LINKS)
        pool = await get_pool()
        if pool is None:
            events: list[dict[str, Any]] = []
            for (row_tenant, _), event in self._local_events.items():
                if (
                    row_tenant != tenant_id
                    or event.get("tenant_id") != tenant_id
                    or event.get("campaign_id") != campaign_id
                ):
                    continue
                effective = _as_datetime(event.get("effective_at"))
                if effective is None:
                    raise ValueError("campaign population event has invalid effective time")
                if effective <= effective_anchor:
                    events.append(dict(event))
            latest: dict[str, dict[str, Any]] = {}
            for event in events:
                population_id = event.get("population_id")
                if not isinstance(population_id, str):
                    continue
                prior = latest.get(population_id)
                if prior is None or _event_order(event) > _event_order(prior):
                    latest[population_id] = event
            ordered = sorted(latest.values(), key=lambda row: _event_order(row), reverse=True)
            return ordered[:bounded], len(ordered) > bounded

        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """WITH latest AS (
                       SELECT DISTINCT ON (population_id) payload, effective_at,
                              recorded_at, link_event_id
                         FROM campaign_population_link_events
                        WHERE tenant_id = $1 AND campaign_id = $2::uuid
                          AND effective_at <= $3
                        ORDER BY population_id, effective_at DESC, recorded_at DESC,
                                 link_event_id DESC
                   )
                   SELECT payload FROM latest
                    ORDER BY effective_at DESC, recorded_at DESC, link_event_id DESC
                    LIMIT $4""",
                tenant_id,
                campaign_id,
                effective_anchor,
                bounded + 1,
            )
        records = [_decode_mapping(row["payload"]) for row in rows]
        return records[:bounded], len(records) > bounded


class CampaignPopulationLinkAuthority:
    """Exact canonical campaign/population validation and append-only writes."""

    def __init__(
        self,
        *,
        store: Optional[CampaignPopulationLinkStore] = None,
        campaign_reader: Any = None,
        population_reader: Any = None,
    ) -> None:
        self._store = store or RepositoryCampaignPopulationLinkStore()
        self._campaign_reader = campaign_reader
        self._population_reader = population_reader

    async def record(
        self,
        tenant_id: str,
        campaign_id: str,
        event: CampaignPopulationLinkInput,
        *,
        actor_id: str,
        actor_type: str,
    ) -> dict[str, Any]:
        if not tenant_id or not actor_id or not actor_type:
            raise CampaignPopulationLinkAuthorityError("authenticated tenant and actor context are required")
        try:
            campaign_uuid = UUID(campaign_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise CampaignPopulationLinkAuthorityError("canonical campaign UUID is required") from exc

        campaign_reader = self._campaign_reader
        if campaign_reader is None:
            from journeys.campaign.repository import CampaignRegistryRepository

            campaign_reader = CampaignRegistryRepository()
        try:
            campaign = await campaign_reader.get_by_id(tenant_id, campaign_uuid)
        except Exception as exc:  # noqa: BLE001 - canonical identity is fail-closed
            raise CampaignPopulationLinkAuthorityError("campaign registry is unavailable") from exc
        if (
            not isinstance(campaign, dict)
            or str(campaign.get("tenant_id") or "") != tenant_id
            or str(campaign.get("campaign_id") or "") != str(campaign_uuid)
        ):
            raise CampaignPopulationLinkAuthorityError("exact tenant campaign was not found")

        population_reader = self._population_reader
        if population_reader is None:
            from identity.population.registry import population_repo

            population_reader = population_repo
        try:
            population = await population_reader.find_by_id(event.population_id)
        except Exception as exc:  # noqa: BLE001 - canonical identity is fail-closed
            raise CampaignPopulationLinkAuthorityError("population registry is unavailable") from exc
        if (
            not isinstance(population, dict)
            or population.get("id") != event.population_id
            or population.get("tenant_id") != tenant_id
        ):
            raise CampaignPopulationLinkAuthorityError("exact tenant population was not found")

        campaign_ref = EvidenceRef(
            id=str(campaign_uuid),
            type="entity",
            source="services/api/journeys/campaign/repository.py:campaigns",
            observedAt=_iso(campaign.get("updated_at") or campaign.get("created_at")),
            uri=f"store://campaigns/{campaign_uuid}",
        )
        population_ref = EvidenceRef(
            id=event.population_id,
            type="entity",
            source="identity_populations",
            observedAt=_iso(population.get("updated_at") or population.get("created_at")),
            uri=f"store://populations/{event.population_id}",
        )
        source_id = f"aether.operator:{actor_id}"
        row = {
            "link_event_id": str(
                uuid5(NAMESPACE_URL, f"aether:campaign-population:{tenant_id}:{source_id}:{event.source_event_id}")
            ),
            "tenant_id": tenant_id,
            "campaign_id": str(campaign_uuid),
            "population_id": event.population_id,
            "event_type": event.event_type,
            "source_id": source_id,
            "source_record_id": event.source_record_id,
            "source_revision_id": event.source_revision_id,
            "source_event_id": event.source_event_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "source_observed_at": event.source_observed_at.isoformat(),
            "effective_at": event.effective_at.isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "evidence_refs": [
                campaign_ref.model_dump(mode="json"),
                population_ref.model_dump(mode="json"),
            ],
        }
        return await self._store.append(row)

    async def read_current(
        self, tenant_id: str, campaign_id: str, *, limit: int = MAX_CAMPAIGN_POPULATION_LINKS
    ) -> CampaignPopulationLinkRead:
        try:
            campaign_uuid = str(UUID(campaign_id))
            rows, truncated = await self._store.latest_for_campaign(
                tenant_id,
                campaign_uuid,
                limit=min(max(limit, 1), MAX_CAMPAIGN_POPULATION_LINKS),
                effective_as_of=datetime.now(timezone.utc),
            )
        except Exception:  # noqa: BLE001 - source diagnostics stay private
            return CampaignPopulationLinkRead(
                tenant_id, campaign_id, (), available=False,
                reason="campaign_population_link_authority_unavailable",
            )
        for row in rows:
            if (
                row.get("tenant_id") != tenant_id
                or row.get("campaign_id") != campaign_uuid
                or not isinstance(row.get("population_id"), str)
                or row.get("event_type") not in {"linked", "unlinked"}
                or not isinstance(row.get("evidence_refs"), list)
            ):
                return CampaignPopulationLinkRead(
                    tenant_id, campaign_uuid, (), available=False,
                    reason="campaign_population_link_scope_or_record_invalid",
                )
        return CampaignPopulationLinkRead(
            tenant_id, campaign_uuid, tuple(rows), available=True,
            truncated=truncated,
            reason="campaign_population_link_read_truncated" if truncated else None,
        )


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    parsed = _as_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _event_order(event: dict[str, Any]) -> tuple[datetime, datetime, str]:
    effective = _as_datetime(event.get("effective_at")) or datetime.min.replace(tzinfo=timezone.utc)
    recorded = _as_datetime(event.get("recorded_at")) or datetime.min.replace(tzinfo=timezone.utc)
    return effective, recorded, str(event.get("link_event_id") or "")


def _idempotent_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key not in {"link_event_id", "recorded_at"}}


def _decode_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


__all__ = [
    "CampaignPopulationLinkAuthority",
    "CampaignPopulationLinkAuthorityError",
    "CampaignPopulationLinkConflict",
    "CampaignPopulationLinkInput",
    "CampaignPopulationLinkRead",
    "MAX_CAMPAIGN_POPULATION_LINKS",
    "RepositoryCampaignPopulationLinkStore",
]
