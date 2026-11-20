"""Repository-backed inputs for a propagation run (read-only, tenant-exact).

Every read is bounded and scoped to one tenant:

* **Population and account map** — active venue account links
  (``VenueAccountLinkService``). Only linked subjects are in scope.
* **Fills** — persisted ``derivatives_fills`` rows of linked accounts, or a
  bounded live read-only pull through the venue adapters for public-wallet
  venues (``include_live``). Live pulls never write and need no credential.
* **Relationship exposures** — tenant graph edges of the registered exposure
  predicates (``get_edges_for_tenant``), mapped by ``exposure.py``.
* **In-app exposures** — ``silver_exposure_facts`` rows in the run window that
  carry ``payload.exposedSubjectRef``.

A source that is unavailable yields nothing plus a reason code; it never
fabricates input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from intelligence.propagation.contracts import ExposureChannel, PropagationQuery

_EDGE_LIMIT = 10_000
_FILL_LIMIT = 5_000
_IN_APP_LIMIT = 10_000
_LIVE_LINK_LIMIT = 50
_LIVE_VENUES = frozenset({"hyperliquid", "polymarket"})


@dataclass
class SourceBundle:
    subjects_by_account: dict[tuple[str, str], str]
    fill_events: list[dict[str, Any]]
    edges: list[Any]
    in_app_rows: list[dict[str, Any]]
    reasons: set[str] = field(default_factory=set)

    @property
    def population(self) -> set[str]:
        return set(self.subjects_by_account.values())


class PropagationSources(Protocol):
    async def load(self, query: PropagationQuery, *, include_live: bool = False) -> SourceBundle: ...


def _fill_row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    market = str(row.get("canonical_market_id") or "")
    payload = {
        "venue_id": market.split(":", 1)[0],
        "canonical_market_id": market,
        "trading_account_id": row.get("trading_account_id"),
        "fill_id": row.get("fill_id"),
        "side": row.get("side"),
        "price": str(row.get("price")),
        "quantity": str(row.get("quantity")),
        "executed_at": (
            row["executed_at"].isoformat() if hasattr(row.get("executed_at"), "isoformat")
            else str(row.get("executed_at") or "")
        ),
    }
    # Event-contract identity and venue direction travel in source_refs when the
    # runtime stored them; absent fields stay absent (token-level instrument).
    refs = row.get("source_refs")
    if isinstance(refs, str):
        try:
            import json

            refs = json.loads(refs)
        except ValueError:
            refs = []
    context: dict[str, str] = {}
    if isinstance(refs, dict):
        context = {k: str(v) for k, v in refs.items() if v}
    elif isinstance(refs, list):
        context = dict(str(r).split("=", 1) for r in refs if "=" in str(r))
    for key in ("instrument_type", "event_contract_ref", "outcome", "direction"):
        if context.get(key):
            payload[key] = context[key]
    return {"event_name": "derivatives_fill_observed", "payload": payload}


class RepositoryPropagationSources:
    """Default sources over the canonical stores."""

    def __init__(
        self,
        *,
        link_service: Any = None,
        fill_repo: Any = None,
        graph_client: Any = None,
        pool_factory: Any = None,
        adapter_factory: Any = None,
    ) -> None:
        self._links = link_service
        self._fills = fill_repo
        self._graph = graph_client
        self._pool_factory = pool_factory
        self._adapter_factory = adapter_factory

    async def load(self, query: PropagationQuery, *, include_live: bool = False) -> SourceBundle:
        reasons: set[str] = set()
        subjects = await self._subjects(query.tenant_id, reasons)
        fills = await self._stored_fills(query.tenant_id, subjects, reasons)
        if include_live:
            fills.extend(await self._live_fills(query.tenant_id, subjects, reasons))
        edges = await self._edges(query, reasons)
        in_app = await self._in_app(query, reasons)
        return SourceBundle(subjects, fills, edges, in_app, reasons)

    async def _subjects(self, tenant_id: str, reasons: set[str]) -> dict[tuple[str, str], str]:
        if self._links is None:
            from value.derivatives.account_links import VenueAccountLinkService

            self._links = VenueAccountLinkService()
        try:
            bounded = getattr(self._links, "subjects_by_account_bounded", None)
            if bounded is None:
                return await self._links.subjects_by_account(tenant_id)
            mapping, truncated = await bounded(tenant_id)
            if truncated:
                # The population (and so adoptions and baseline denominators)
                # is a capped subset; say so rather than present it as complete.
                reasons.add("venue_account_link_scan_capped")
            return mapping
        except Exception:  # noqa: BLE001 - link authority failures stay explicit
            reasons.add("venue_account_link_authority_unavailable")
            return {}

    async def _stored_fills(
        self, tenant_id: str, subjects: dict[tuple[str, str], str], reasons: set[str],
    ) -> list[dict[str, Any]]:
        if not subjects:
            return []
        if self._fills is None:
            from repositories.derivatives_repos import FillRepo

            self._fills = FillRepo()
        events: list[dict[str, Any]] = []
        try:
            for _venue, account in sorted(subjects):
                # derivatives_fills has no created_at column: order explicitly.
                rows = await self._fills.find_many(
                    {"tenant_id": tenant_id, "trading_account_id": f"acct_{account}"},
                    limit=_FILL_LIMIT,
                    order_by="executed_at",
                    descending=False,
                )
                if len(rows) >= _FILL_LIMIT:
                    reasons.add("stored_fill_scan_capped")
                events.extend(_fill_row_to_event(r) for r in rows if r.get("tenant_id") == tenant_id)
        except Exception:  # noqa: BLE001
            reasons.add("stored_fill_authority_unavailable")
        return events

    async def _live_fills(
        self, tenant_id: str, subjects: dict[tuple[str, str], str], reasons: set[str],
    ) -> list[dict[str, Any]]:
        factory = self._adapter_factory or _default_adapter_factory
        events: list[dict[str, Any]] = []
        live = [(v, a) for v, a in sorted(subjects) if v in _LIVE_VENUES]
        if len(live) > _LIVE_LINK_LIMIT:
            reasons.add("live_fill_link_scan_capped")
            live = live[:_LIVE_LINK_LIMIT]
        for venue, account in live:
            try:
                adapter = factory(venue, account)
                pulled, checkpoint = await adapter.pull_events()
            except Exception:  # noqa: BLE001 - one venue outage never fails the run
                reasons.add(f"live_fill_pull_failed:{venue}")
                continue
            if checkpoint.get("provider_health") not in (None, "ok"):
                reasons.add(f"live_fill_provider_degraded:{venue}")
            events.extend(pulled)
        return events

    async def _edges(self, query: PropagationQuery, reasons: set[str]) -> list[Any]:
        from intelligence.propagation.exposure import exposure_edge_types

        wanted = {ExposureChannel.SOCIAL, ExposureChannel.ONCHAIN, ExposureChannel.RELATIONSHIP}
        if not (wanted & set(query.channels)):
            return []
        client = self._graph
        if client is None:
            from shared.graph.graph import get_graph_client

            client = get_graph_client()
        try:
            edges, truncated = await client.get_edges_for_tenant(
                query.tenant_id, limit=_EDGE_LIMIT, edge_types=list(exposure_edge_types()), include_revoked=False,
            )
        except Exception:  # noqa: BLE001
            reasons.add("canonical_graph_authority_unavailable")
            return []
        if truncated:
            reasons.add("exposure_edge_scan_capped")
        return list(edges)

    async def _in_app(self, query: PropagationQuery, reasons: set[str]) -> list[dict[str, Any]]:
        if ExposureChannel.IN_APP not in set(query.channels):
            return []
        try:
            if self._pool_factory is not None:
                pool = await self._pool_factory()
            else:
                from repositories.repos import get_pool

                pool = await get_pool()
        except Exception:  # noqa: BLE001
            pool = None
        if pool is None:
            reasons.add("in_app_exposure_store_unavailable")
            return []
        from intelligence.propagation.engine import _parse

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT tenant_id, source_event_id, source_event_type, user_id,
                           occurred_at, payload
                      FROM silver_exposure_facts
                     WHERE tenant_id = $1
                       AND occurred_at >= $2 AND occurred_at <= $3
                       AND payload ? 'exposedSubjectRef'
                     ORDER BY occurred_at
                     LIMIT $4
                    """,
                    query.tenant_id, _parse(query.window_start), _parse(query.window_end), _IN_APP_LIMIT,
                )
        except Exception:  # noqa: BLE001
            reasons.add("in_app_exposure_store_unavailable")
            return []
        if len(rows) >= _IN_APP_LIMIT:
            reasons.add("in_app_exposure_scan_capped")
        out = []
        for row in rows:
            item = dict(row)
            payload = item.get("payload")
            if isinstance(payload, str):
                import json

                try:
                    item["payload"] = json.loads(payload)
                except ValueError:
                    item["payload"] = {}
            out.append(item)
        return out


def _default_adapter_factory(venue: str, account_ref: str) -> Any:
    import httpx

    from value.derivatives.adapters import VENUE_ADAPTERS

    adapter_cls = type(VENUE_ADAPTERS[venue])
    return adapter_cls(http_transport=httpx.AsyncHTTPTransport(), account_ref=account_ref, max_pages=5)


__all__ = ["PropagationSources", "RepositoryPropagationSources", "SourceBundle"]
