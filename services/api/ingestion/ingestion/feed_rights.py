"""Source rights for the server API feed (``POST /v1/ingest/feed``).

A feed source (``feed:<source>``, e.g. ``feed:dune``) is a tenant data source
like any connector, so new use is governed by the Rights Authority:

* **Granted** — an active ``DataRightsGrant`` for ``feed:<source>`` that allows
  the tenant lake. The row carries the grant's source relationship and refs.
* **Legacy** — the tenant already fed this source before grants were required.
  It keeps working, stamped ``unclassified`` and confined to the tenant lake
  (no Olympus baseline, aggregate or training use) until a grant converges it.
* **Denied** — first use of a source with no grant. The caller gets a 403 that
  names the source id to grant.

Transport never decides ownership: nothing in the request body can set the
relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from shared.integration_contracts.source_relationship import UNCLASSIFIED
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.ingestion.feed_rights")

FEED_SOURCE_PREFIX = "feed:"


def feed_source_id(source: str) -> str:
    return f"{FEED_SOURCE_PREFIX}{(source or '').strip().lower()}"


@dataclass(frozen=True)
class FeedRights:
    outcome: str  # "granted" | "legacy" | "denied"
    source_id: str
    source_relationship: str = UNCLASSIFIED
    grant_id: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.outcome != "denied"

    def stamp(self) -> dict:
        """Server-owned provenance written onto the Bronze feed row."""
        stamp = {
            "source_id": self.source_id,
            "source_relationship": self.source_relationship,
            "rights_outcome": self.outcome,
        }
        if self.grant_id:
            stamp["source_grant_refs"] = [self.grant_id]
        if self.outcome == "legacy":
            stamp["lake_scope"] = "tenant_only"
        return stamp


async def _has_fed_before(tenant_id: str, source: str) -> bool:
    from repositories.lake import BronzeRepository

    rows = await BronzeRepository("feeds").find_many(
        filters={"tenant_id": tenant_id, "source": source}, limit=1,
    )
    return bool(rows)


async def resolve_source_rights(
    tenant_id: str,
    source_id: str,
    *,
    has_history: "Callable[[], Awaitable[bool]]",
    grant_required: bool = True,
    metric: str = "ingestion_feed_rights_total",
) -> FeedRights:
    """Granted, legacy or denied for one source in one scope (tenant or ``olympus``)."""
    try:
        from connectors.integrations.data_rights.service import data_rights_service

        grant = await data_rights_service.get_effective_grant(tenant_id, source_id)
    except Exception as exc:  # rights authority unreachable: fail closed below
        logger.warning("source rights lookup failed tenant=%s source=%s: %s", tenant_id, source_id, type(exc).__name__)
        grant = None
    from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

    # The use that must be granted depends on the scope that will own the rows.
    needed = "olympus_baseline_allowed" if tenant_id == OLYMPUS_SOURCE_TENANT_ID else "tenant_lake_allowed"
    if grant is not None and getattr(grant, needed, False):
        metrics.increment(metric, labels={"outcome": "granted"})
        return FeedRights(
            outcome="granted",
            source_id=source_id,
            source_relationship=str(getattr(grant, "source_relationship", "") or UNCLASSIFIED),
            grant_id=str(getattr(grant, "data_rights_grant_id", "") or "") or None,
        )
    if not grant_required or await has_history():
        metrics.increment(metric, labels={"outcome": "legacy"})
        return FeedRights(outcome="legacy", source_id=source_id)
    metrics.increment(metric, labels={"outcome": "denied"})
    return FeedRights(outcome="denied", source_id=source_id)


async def resolve_feed_rights(tenant_id: str, source: str, *, grant_required: bool = True) -> FeedRights:
    return await resolve_source_rights(
        tenant_id,
        feed_source_id(source),
        has_history=lambda: _has_fed_before(tenant_id, source),
        grant_required=grant_required,
    )


__all__ = ["FeedRights", "feed_source_id", "resolve_feed_rights", "resolve_source_rights"]
