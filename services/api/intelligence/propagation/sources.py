"""Repository-backed inputs for a propagation run (read-only, tenant-exact).

Every read is bounded and scoped to one tenant:

* **Population and account map** — active venue account links
  (``VenueAccountLinkService``). Only linked subjects are in scope.
* **Fills** — persisted ``derivatives_fills`` rows of linked accounts that were
  admitted under a held grant (their ``source_refs`` carry ``source_grant_ref``
  and ``rights_decision_ref``). ``include_live`` first runs a bounded account
  sync for the tenant's links (``VenueAccountSync``), which goes through the
  same raw admission; nothing is read around it.
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


def _source_context(row: dict[str, Any]) -> dict[str, str]:
    refs = row.get("source_refs")
    if isinstance(refs, str):
        try:
            import json

            refs = json.loads(refs)
        except ValueError:
            refs = []
    if isinstance(refs, dict):
        return {k: str(v) for k, v in refs.items() if v}
    if isinstance(refs, list):
        return dict(str(r).split("=", 1) for r in refs if "=" in str(r))
    return {}


def _admitted(row: dict[str, Any]) -> bool:
    context = _source_context(row)
    return bool(context.get("source_grant_ref") and context.get("rights_decision_ref"))


def _grant_currently_permits(grant: Any, tenant_id: str) -> bool:
    from connectors.provider_runtime.rights_admission import raw_retention_use

    if grant is None:
        return False
    status = getattr(grant, "status", None)
    use = raw_retention_use(grant)
    return bool(
        str(getattr(grant, "tenant_id", "") or "") == tenant_id
        and getattr(status, "value", status) == "active"
        and getattr(grant, "revoked_at", None) is None
        and use is not None
        and getattr(grant, f"{use}_allowed", False)
    )


def _fill_row_to_event(row: dict[str, Any], linked_account_ref: str = "") -> dict[str, Any]:
    market = str(row.get("canonical_market_id") or "")
    payload = {
        "venue_id": market.split(":", 1)[0],
        "canonical_market_id": market,
        "trading_account_id": row.get("trading_account_id"),
        # The linked account this fill was loaded for (server-side link, not the
        # fill). Adapters may key fills differently from the link (dYdX default
        # subaccount ``acct_<addr>_0``), so attribution must not reverse the key.
        **({"linked_account_ref": linked_account_ref} if linked_account_ref else {}),
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
    context = _source_context(row)
    for key in ("instrument_type", "event_contract_ref", "outcome", "direction",
                "source_id", "source_grant_ref", "rights_decision_ref"):
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
        account_sync: Any = None,
        account_key: Any = None,
        grant_lookup: Any = None,
    ) -> None:
        self._links = link_service
        # ``async (grant_id, *, tenant_id) -> grant``; defaults to the canonical
        # data-rights service. Tests inject their own.
        self._grant_lookup = grant_lookup
        self._fills = fill_repo
        self._graph = graph_client
        self._pool_factory = pool_factory
        self._account_sync = account_sync
        self._account_key = account_key or _adapter_account_key

    async def load(self, query: PropagationQuery, *, include_live: bool = False) -> SourceBundle:
        reasons: set[str] = set()
        subjects = await self._subjects(query.tenant_id, reasons)
        if include_live and subjects:
            await self._sync(query.tenant_id, reasons)
        fills = await self._stored_fills(query.tenant_id, subjects, reasons)
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
            if getattr(self._links, "last_ambiguous_accounts", None):
                reasons.add("venue_account_link_ownership_ambiguous")
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
        excluded = 0
        revoked = 0
        grant_cache: dict[str, Optional[bool]] = {}
        try:
            for venue, account in sorted(subjects):
                # derivatives_fills has no created_at column: order explicitly.
                rows = await self._fills.find_many(
                    {"tenant_id": tenant_id, "trading_account_id": self._account_key(venue, account)},
                    limit=_FILL_LIMIT,
                    order_by="executed_at",
                    descending=False,
                )
                if len(rows) >= _FILL_LIMIT:
                    reasons.add("stored_fill_scan_capped")
                for row in rows:
                    if row.get("tenant_id") != tenant_id:
                        continue
                    if not _admitted(row):
                        # Never admitted under a grant (legacy intake): not used.
                        excluded += 1
                        continue
                    # Admission proves the fill was allowed when it was stored,
                    # not that it still is. The referenced grant must permit the
                    # use now; a revoked grant (or one replaced by re-linking)
                    # takes its fills out of every later computation.
                    permitted = await self._grant_permits(
                        tenant_id, _source_context(row)["source_grant_ref"], grant_cache,
                    )
                    if permitted is None:
                        reasons.add("fill_grant_authority_unavailable")
                        continue
                    if not permitted:
                        revoked += 1
                        continue
                    events.append(_fill_row_to_event(row, account))
        except Exception:  # noqa: BLE001
            reasons.add("stored_fill_authority_unavailable")
        if excluded:
            reasons.add("unadmitted_fills_excluded")
        if revoked:
            reasons.add("revoked_grant_fills_excluded")
        return events

    async def _grant_permits(
        self, tenant_id: str, grant_ref: str, cache: dict[str, Optional[bool]],
    ) -> Optional[bool]:
        """Whether the fill's grant permits its use now; None if unknowable.

        Checked once per grant per computation: the grant must belong to the
        tenant, be active and unrevoked, and still allow the retention use its
        rights-source class grants (the same rule raw admission applies).
        """
        if grant_ref in cache:
            return cache[grant_ref]
        lookup = self._grant_lookup
        if lookup is None:
            from connectors.integrations.data_rights.service import data_rights_service

            lookup = data_rights_service.get_grant
        try:
            grant = await lookup(grant_ref, tenant_id=tenant_id)
        except Exception:  # noqa: BLE001 - an unreadable authority never admits
            cache[grant_ref] = None
            return None
        cache[grant_ref] = _grant_currently_permits(grant, tenant_id)
        return cache[grant_ref]

    async def _sync(self, tenant_id: str, reasons: set[str]) -> None:
        sync = self._account_sync
        if sync is None:
            from value.derivatives.account_sync import VenueAccountSync

            sync = VenueAccountSync(link_service=self._links)
        try:
            result = await sync.sync_tenant(tenant_id)
        except Exception:  # noqa: BLE001 - a sync outage never fails the run
            reasons.add("account_sync_unavailable")
            return
        if result.truncated:
            reasons.add("account_sync_link_scan_capped")
        for link in result.links:
            if link.status in ("failed", "denied", "degraded"):
                reasons.add(f"account_sync_{link.status}")

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


def _adapter_account_key(venue: str, account_ref: str) -> str:
    """The stored ``trading_account_id`` for a linked account, from its adapter."""
    from value.derivatives.adapters import VENUE_ADAPTERS

    adapter = VENUE_ADAPTERS.get(venue)
    if adapter is None or not hasattr(adapter, "trading_account_id_for"):
        return f"acct_{account_ref}"
    return adapter.trading_account_id_for(account_ref)


__all__ = ["PropagationSources", "RepositoryPropagationSources", "SourceBundle"]
