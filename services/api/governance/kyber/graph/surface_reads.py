"""Mirror reads for Aether surfaces whose data lives outside graph vertices.

The Tenant Mirror owes each surface the tenant's own result. For these surfaces
that result comes from relational stores through Aether's route handlers, so a
reader here calls those same handlers rather than querying the stores itself. A
second query would be a second implementation of the tenant's product, which is
what the mirror exists to rule out.

Each handler runs under a synthetic tenant context that holds read permissions
only. A handler that asks for anything more raises ``ForbiddenError`` and the
read fails. The tenant id comes from the gateway's authorized scope, never from a
request parameter, and handler ownership checks answer a foreign id with the same
404 as a missing one.

The limits and id caps match what the Aether pages request, so the mirror reads
what the tenant's page reads. A failed source is reported as unavailable and left
as ``None``, never as an empty list: a failed read must not look like a tenant
with no data.

``governance.kyber.graph.scoped_gateway`` is the only caller. It runs the ordered
authorization gate first.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.params import Depends, Param

from shared.auth.auth import Role, TenantContext
from shared.common.common import ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

logger = get_logger("aether.kyber.graph.surface_reads")

#: Everything the handlers below ask for. Nothing here can write.
READ_PERMISSIONS = ("read", "campaign:read")

#: `apps/aether-web/src/features/journeys/use-journey-fanout.ts` JOURNEY_FANOUT_CAP.
JOURNEY_FANOUT_CAP = 24
#: `apps/aether-web/src/features/communications/use-communications.ts` COMMS_INDEX_MAX_CAMPAIGNS.
COMMS_INDEX_MAX_CAMPAIGNS = 25
#: The same file's COMMS_CAMPAIGN_CHANNELS, which selects the campaigns the page reads.
COMMS_CAMPAIGN_CHANNELS = frozenset({
    "email", "sms", "push", "lifecycle", "transactional", "in_app", "in-app", "inapp", "outbound", "agent",
})
#: `BaseRepository.find_many`'s default limit.
ALERT_RULE_PAGE = 50


def _tenant_request(tenant_id: str) -> Any:
    """The minimum a route handler reads from a request: a read-only tenant."""
    tenant = TenantContext(tenant_id=tenant_id, role=Role.VIEWER, permissions=list(READ_PERMISSIONS))
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


async def _call(handler: Callable[..., Awaitable[Any]], tenant_id: str, **arguments: Any) -> Any:
    """Run a route handler outside FastAPI and return its JSON-shaped payload.

    Called directly, a handler would receive its ``Query(...)`` markers as values,
    so unset query parameters take their declared defaults. An unset ``Depends`` is
    a wiring mistake and raises rather than running with a marker as a dependency.
    """
    for name, parameter in inspect.signature(handler).parameters.items():
        if name == "request" or name in arguments:
            continue
        default = parameter.default
        if default is inspect.Parameter.empty:
            raise TypeError(f"{handler.__name__} needs argument {name!r} supplied")
        if isinstance(default, Depends):
            raise TypeError(f"{handler.__name__} needs dependency {name!r} supplied")
        if isinstance(default, Param):
            if default.is_required():
                raise TypeError(f"{handler.__name__} needs query parameter {name!r} supplied")
            default = default.default
        arguments[name] = default
    body = jsonable_encoder(await handler(request=_tenant_request(tenant_id), **arguments))
    # The envelope's timestamp and request meta differ per call and are not the result.
    return body["data"] if isinstance(body, dict) and "data" in body else body


@dataclass
class _Reads:
    """Collects one surface's sources and what is known to be missing from them."""

    tenant_id: str
    sources: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    unavailable: list[str] = field(default_factory=list)

    async def take(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        *,
        rows_key: Optional[str] = None,
        **arguments: Any,
    ) -> Any:
        """Read one source. A 404 or a refusal propagates; any other failure is disclosed."""
        try:
            value = await _call(handler, self.tenant_id, **arguments)
        except (NotFoundError, ForbiddenError):
            raise
        except Exception as exc:
            logger.warning(f"kyber: mirror source {name} failed: {type(exc).__name__}")
            self.unavailable.append(name)
            self.sources[name] = None
            return None
        limit = arguments.get("limit")
        if limit is not None:
            rows = value.get(rows_key) if rows_key and isinstance(value, dict) else value
            self.truncated = self.truncated or (isinstance(rows, list) and len(rows) >= limit)
        self.sources[name] = value
        return value


# ── Readers ──────────────────────────────────────────────────────────────────


async def _read_syndicates(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from identity.population.routes import list_groups

    await reads.take("groups", list_groups, limit=200, rows_key="groups")


async def _read_syndicate(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from identity.population.routes import get_group, get_members

    population_id = params["syndicate_id"]
    await reads.take("group", get_group, population_id=population_id)
    await reads.take("members", get_members, population_id=population_id, limit=1000, rows_key="members")


async def _journey(reads: _Reads, name: str, profile_id: str, graph: Any) -> Any:
    from dependencies.providers import get_cache
    from identity.profile.routes import _get_aggregator, get_unified_journey

    return await reads.take(
        name, get_unified_journey, user_id=profile_id, limit=200,
        agg=_get_aggregator(graph=graph, cache=get_cache()),
    )


async def _read_journey_index(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from identity.entities.routes import list_entities

    listed = await reads.take("entities", list_entities, limit=100, rows_key="entities")
    rows = (listed or {}).get("entities") or []
    reads.truncated = reads.truncated or len(rows) > JOURNEY_FANOUT_CAP
    # The Journeys page reads this fan-out. Episodes reads one journey per selection from it.
    # Sources are named by position because a name is never masked, and an id would leak.
    for position, row in enumerate(rows[:JOURNEY_FANOUT_CAP]):
        profile_id = str(row.get("entity_id") or row.get("id") or "")
        if profile_id:
            await _journey(reads, f"journey[{position}]", profile_id, graph)


async def _read_journey(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    await _journey(reads, "journey", params["profile_id"], graph)


async def _read_communications(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from journeys.campaign.routes import get_campaign_messages, list_campaigns
    from journeys.comms.routes import comms_health

    await reads.take("health", comms_health)
    campaigns = await reads.take("campaigns", list_campaigns, limit=100) or []
    selected = [
        row for row in campaigns
        if str(row.get("channel") or "").strip().lower() in COMMS_CAMPAIGN_CHANNELS
        and (row.get("campaign_id") or row.get("id"))
    ]
    reads.truncated = reads.truncated or len(selected) > COMMS_INDEX_MAX_CAMPAIGNS
    for position, row in enumerate(selected[:COMMS_INDEX_MAX_CAMPAIGNS]):
        campaign_id = str(row.get("campaign_id") or row.get("id"))
        await reads.take(f"messages[{position}]", get_campaign_messages, campaign_id=campaign_id)


async def _read_communication(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from journeys.campaign.routes import (
        get_campaign,
        get_campaign_comms_funnel,
        get_campaign_comms_population,
        get_campaign_conversions,
        get_campaign_journeys,
        get_campaign_message_detail,
    )

    campaign_id = params["campaign_id"]
    await reads.take("campaign", get_campaign, campaign_id=campaign_id)
    await reads.take(
        "message", get_campaign_message_detail, campaign_id=campaign_id,
        external_message_id=params["message_id"],
    )
    await reads.take("funnel", get_campaign_comms_funnel, campaign_id=campaign_id)
    await reads.take("recipients", get_campaign_comms_population, campaign_id=campaign_id, limit=100, rows_key="items")
    await reads.take("journeys", get_campaign_journeys, campaign_id=campaign_id, limit=50, rows_key="items")
    await reads.take("conversions", get_campaign_conversions, campaign_id=campaign_id, limit=100, rows_key="items")


async def _read_signals(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from journeys.notification_intelligence.routes import get_config, list_alerts, list_inbox

    await reads.take("inbox", list_inbox, include_archived=True, limit=200)
    rules = await reads.take("alert_rules", list_alerts)
    # The handler takes no limit and reads the repository's default page.
    reads.truncated = reads.truncated or len(rules or ()) >= ALERT_RULE_PAGE
    await reads.take("preferences", get_config, tenantId=reads.tenant_id)


async def _read_risk(reads: _Reads, params: dict[str, str], graph: Any) -> None:
    from actions.agent_access_intelligence.risk_routes import list_risk_findings
    from governance.data_quality.routes import data_quality_overview
    from governance.investigation.routes import list_cases

    await reads.take("cases", list_cases, tenantId=reads.tenant_id, limit=200)
    await reads.take("data_quality", data_quality_overview)
    await reads.take("capability_findings", list_risk_findings, limit=100, rows_key="items")


#: The query parameters each surface requires, in order. ``relationships*`` read
#: through the gateway's neighbourhood walk, so they have no reader below.
SURFACE_READ_PARAMS: dict[str, tuple[str, ...]] = {
    "relationships": ("entity_id",),
    "relationships-entityId": ("entity_id",),
    "syndicates": (),
    "syndicates-syndicateId": ("syndicate_id",),
    "journeys": (),
    "journeys-profileId": ("profile_id",),
    "episodes": (),
    "episodes-profileId-episodeId": ("profile_id", "episode_id"),
    "communications": (),
    "communications-campaignId-messageId": ("campaign_id", "message_id"),
    "signals": (),
    "risk": (),
}

NEIGHBORHOOD_SURFACES = frozenset({"relationships", "relationships-entityId"})

_READERS: dict[str, Callable[[_Reads, dict[str, str], Any], Awaitable[None]]] = {
    "syndicates": _read_syndicates,
    "syndicates-syndicateId": _read_syndicate,
    "journeys": _read_journey_index,
    "journeys-profileId": _read_journey,
    "episodes": _read_journey_index,
    "episodes-profileId-episodeId": _read_journey,
    "communications": _read_communications,
    "communications-campaignId-messageId": _read_communication,
    "signals": _read_signals,
    "risk": _read_risk,
}


async def read_tenant_surface(surface: str, tenant_id: str, params: dict[str, str], *, graph: Any) -> _Reads:
    """Read one surface for one authorized tenant."""
    reads = _Reads(tenant_id=tenant_id)
    await _READERS[surface](reads, params, graph)
    return reads


__all__ = [
    "NEIGHBORHOOD_SURFACES",
    "SURFACE_READ_PARAMS",
    "read_tenant_surface",
]
