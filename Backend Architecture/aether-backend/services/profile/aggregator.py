"""
Profile 360 Aggregator — frontend-ready drill-down layer.

This module sits on top of the existing Profile 360 subsystems (entities,
delegations, flows/wallets/transfers, agents, behavior, journey chains,
analytics, payment intents/settlements, graph) and produces normalized,
pagination-aware payloads that a UI can consume without performing any
cross-service joins of its own.

Design rules:
    1. **Additive only.** No existing repository, route, or composer behavior
       is changed. The aggregator only reads.
    2. **Tenant-scoped.** Every method requires a tenant_id and filters every
       repository hit on it before returning.
    3. **Normalized shape.** Every drill endpoint returns:

           {
             "entity_id": "...",
             "tenant_id": "...",
             "kind": "<dimension>",         # e.g. "wallets"
             "items": [ ...normalized items... ],
             "summary": { ...rollups... },
             "pagination": {"limit": N, "count": M, "has_more": bool},
             "computed_at": "<iso8601>",
             "provenance": {"sources": [...repositories actually touched...]},
           }

       Items expose `id`, `type`, `displayLabel`, `timestamps`, `metadata`,
       and `links` (drill refs other items can navigate to). Frontends should
       not need to know which underlying table a field originated from.
    4. **Best-effort fallback.** Any repository read that fails is caught and
       logged; the dimension degrades to an empty list rather than 500-ing the
       whole profile.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.profile.aggregator")


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _tenant_filter(rows: list[dict], tenant_id: str) -> list[dict]:
    """Keep only rows belonging to this tenant.

    Legacy unscoped rows (no tenant_id set at all) are permitted so existing
    production data is not dropped, but the alignment audit on the parent
    response flags them. This matches ProfileComposer._compose_graph.
    """
    out: list[dict] = []
    for r in rows:
        t = r.get("tenant_id")
        if t in (None, "", tenant_id):
            out.append(r)
    return out


def _scoped(tenant_id: str, **filters) -> dict:
    """Return a find_many filter dict that includes tenant_id.

    Direct callers should prefer `Profile360Aggregator._scoped_find_many`,
    which also preserves legacy unscoped rows. This helper exists for
    call sites that only need the current-tenant slice (e.g. a single
    query whose result is not paginated).
    """
    return {**filters, "tenant_id": tenant_id}


def _merge_sort_dedupe(*lists: list[dict], limit: int) -> list[dict]:
    """Merge, dedupe-by-id, sort newest-first, truncate to limit.

    Picks the freshest timestamp available on each row across the common
    Profile 360 timestamp fields. Rows with no id are kept (no dedupe).
    """
    seen: set[str] = set()
    merged: list[dict] = []
    for source in lists:
        if not isinstance(source, list):
            continue
        for r in source:
            rid = r.get("id")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            merged.append(r)

    def _key(r: dict) -> str:
        return (
            r.get("occurred_at")
            or r.get("created_at")
            or r.get("starts_at")
            or ""
        )

    merged.sort(key=_key, reverse=True)
    return merged[:limit]


def _ts(row: dict, *keys: str) -> Optional[str]:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v)
    return None


def _paginate(items: list[dict], limit: int) -> dict:
    return {
        "limit": limit,
        "count": len(items),
        "has_more": len(items) >= limit,
    }


def _envelope(
    entity_id: str,
    tenant_id: str,
    kind: str,
    items: list[dict],
    summary: dict,
    limit: int,
    sources: list[str],
) -> dict:
    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "kind": kind,
        "items": items,
        "summary": summary,
        "pagination": _paginate(items, limit),
        "computed_at": utc_now().isoformat(),
        "provenance": {"sources": sources},
    }


async def _safe(label: str, coro):
    """Run a coroutine and return [] on error, logging the failure.

    Aggregation endpoints must keep responding even if a single dependency is
    flaky, so degraded dimensions are preferable to 500s.
    """
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — aggregator must never raise
        logger.warning("profile360_aggregator_dimension_failed", extra={"dimension": label, "error": str(exc)})
        return []


# ───────────────────────────────────────────────────────────────────────
# Aggregator
# ───────────────────────────────────────────────────────────────────────


class Profile360Aggregator:
    """Reusable drill-down assembler over the existing Profile 360 repos.

    The aggregator does NOT own state. It instantiates (or accepts) the
    existing repository classes and reads through them so the same data the
    individual /v1/entities, /v1/delegations, /v1/flows, /v1/behavior,
    /v1/agents endpoints serve is what the frontend sees here, just shaped
    for a single profile view.
    """

    def __init__(
        self,
        *,
        entity_repo=None,
        cluster_repo=None,
        delegation_repo=None,
        wallet_repo=None,
        asset_repo=None,
        transfer_repo=None,
        agent_config_repo=None,
        agent_exec_repo=None,
        behavior_repo=None,
        journey_chain_repo=None,
        payment_intent_repo=None,
        settlement_repo=None,
        analytics_repo=None,
        identity_repo=None,
        graph=None,
    ) -> None:
        # Lazy import here so we don't widen the module import graph for
        # callers that pass their own collaborators (e.g. tests).
        if entity_repo is None:
            from repositories.repos import EntityRepository
            entity_repo = EntityRepository()
        if cluster_repo is None:
            from repositories.repos import IdentityClusterRepository
            cluster_repo = IdentityClusterRepository()
        if delegation_repo is None:
            from repositories.repos import DelegationRepository
            delegation_repo = DelegationRepository()
        if wallet_repo is None:
            from repositories.repos import WalletRepository
            wallet_repo = WalletRepository()
        if asset_repo is None:
            from repositories.repos import AssetRepository
            asset_repo = AssetRepository()
        if transfer_repo is None:
            from repositories.repos import TransferRepository
            transfer_repo = TransferRepository()
        if agent_config_repo is None:
            from repositories.repos import AgentConfigRepository
            agent_config_repo = AgentConfigRepository()
        if agent_exec_repo is None:
            from repositories.repos import AgentExecutionRepository
            agent_exec_repo = AgentExecutionRepository()
        if behavior_repo is None:
            from repositories.repos import BehaviorProfileRepository
            behavior_repo = BehaviorProfileRepository()
        if journey_chain_repo is None:
            from repositories.repos import JourneyChainRepository
            journey_chain_repo = JourneyChainRepository()
        if payment_intent_repo is None:
            from repositories.repos import PaymentIntentRepository
            payment_intent_repo = PaymentIntentRepository()
        if settlement_repo is None:
            from repositories.repos import SettlementEventRepository
            settlement_repo = SettlementEventRepository()

        self._entities = entity_repo
        self._clusters = cluster_repo
        self._delegations = delegation_repo
        self._wallets = wallet_repo
        self._assets = asset_repo
        self._transfers = transfer_repo
        self._agent_configs = agent_config_repo
        self._agent_execs = agent_exec_repo
        self._behavior = behavior_repo
        self._journeys = journey_chain_repo
        self._intents = payment_intent_repo
        self._settlements = settlement_repo
        self._analytics = analytics_repo
        self._identity = identity_repo
        self._graph = graph

    # ── Tenant-scoped query helpers ───────────────────────────────────

    async def _scoped_find_many(
        self,
        repo,
        *,
        tenant_id: str,
        filters: dict,
        limit: int,
    ) -> list[dict]:
        """Tenant-scoped find_many that preserves legacy unscoped rows.

        Issues two parallel queries:
          * primary: `{**filters, "tenant_id": tenant_id}`
          * legacy:  `{**filters, "tenant_id": None}` — matches rows where
            the tenant_id column is NULL or empty string (pre-multi-tenant
            production data). BaseRepository.find_many special-cases
            `tenant_id=None` to emit `(tenant_id IS NULL OR tenant_id = '')`
            on the SQL side; the in-memory dict path matches missing /
            None tenant_id naturally.

        Merges results, dedupes by id, sorts newest-first, truncates to
        `limit`. Without the legacy query, rows inserted before the
        multi-tenant rollout (or upserted via ON CONFLICT, which doesn't
        update the tenant column) would silently disappear from Profile
        360 endpoints — `_tenant_filter` explicitly admits those rows on
        the post-filter side, and the SQL find_many would never return
        them when filtered by `tenant_id = <requested>`.
        """
        primary_filter = {**filters, "tenant_id": tenant_id}
        legacy_filter = {**filters, "tenant_id": None}
        primary, legacy = await asyncio.gather(
            _safe("scoped.primary", repo.find_many(filters=primary_filter, limit=limit)),
            _safe("scoped.legacy", repo.find_many(filters=legacy_filter, limit=limit)),
            return_exceptions=False,
        )
        return _merge_sort_dedupe(primary, legacy, limit=limit)

    # ── Dimensions ────────────────────────────────────────────────────

    async def wallets(self, entity_id: str, tenant_id: str, limit: int = 100) -> dict:
        rows = await self._scoped_find_many(
            self._wallets, tenant_id=tenant_id,
            filters={"owner_entity_id": entity_id}, limit=limit,
        )
        rows = _tenant_filter(rows, tenant_id)
        items = [
            {
                "id": r.get("wallet_id") or r.get("id"),
                "type": "wallet",
                "displayLabel": r.get("address") or r.get("wallet_id"),
                "chain": r.get("chain"),
                "address": r.get("address"),
                "timestamps": {"linkedAt": _ts(r, "linked_at", "created_at")},
                "metadata": r,
                "links": {"transfers": f"/v1/profile/{entity_id}/flows"},
            }
            for r in rows
        ]
        summary = {
            "wallet_count": len(items),
            "chains": sorted({i["chain"] for i in items if i.get("chain")}),
        }
        return _envelope(entity_id, tenant_id, "wallets", items, summary, limit, ["entity_wallets"])

    async def sessions(self, entity_id: str, tenant_id: str, limit: int = 100) -> dict:
        # Sessions live on the analytics event stream and on the identity
        # graph as Session vertices. We read both and merge by session_id.
        events: list[dict] = []
        if self._analytics is not None:
            events = await _safe("sessions.analytics", self._analytics.query_events(
                tenant_id, {"user_id": entity_id}, limit=limit,
            ))

        session_props: dict[str, dict] = {}
        for e in events:
            sid = (e.get("properties") or {}).get("session_id") or e.get("session_id")
            if not sid:
                continue
            slot = session_props.setdefault(sid, {
                "id": sid,
                "type": "session",
                "displayLabel": sid,
                "event_count": 0,
                "first_seen": None,
                "last_seen": None,
                "platforms": set(),
                "devices": set(),
                "user_agents": set(),
            })
            slot["event_count"] += 1
            created = e.get("created_at") or e.get("timestamp")
            if created:
                if not slot["first_seen"] or created < slot["first_seen"]:
                    slot["first_seen"] = created
                if not slot["last_seen"] or created > slot["last_seen"]:
                    slot["last_seen"] = created
            props = e.get("properties") or {}
            for src, key in (
                ("platforms", "platform"), ("devices", "device_id"),
                ("user_agents", "user_agent"),
            ):
                # Canonical SDK events keep these at the top level; fall back
                # so the session rollup is correct for both payload shapes.
                v = props.get(key) or e.get(key)
                if v:
                    slot[src].add(v)

        items = []
        for slot in session_props.values():
            items.append({
                "id": slot["id"],
                "type": "session",
                "displayLabel": slot["displayLabel"],
                "eventCount": slot["event_count"],
                "platforms": sorted(slot["platforms"]),
                "devices": sorted(slot["devices"]),
                "userAgents": sorted(slot["user_agents"]),
                "timestamps": {
                    "firstSeen": slot["first_seen"],
                    "lastSeen": slot["last_seen"],
                },
                "metadata": {},
                "links": {"timeline": f"/v1/profile/{entity_id}/timeline?session_id={slot['id']}"},
            })
        items.sort(key=lambda r: r.get("timestamps", {}).get("lastSeen") or "", reverse=True)
        items = items[:limit]
        summary = {
            "session_count": len(items),
            "total_events": sum(i["eventCount"] for i in items),
        }
        return _envelope(entity_id, tenant_id, "sessions", items, summary, limit, ["analytics_events"])

    async def devices(self, entity_id: str, tenant_id: str, limit: int = 100) -> dict:
        # Devices come from two sources: identity clusters (deterministic links)
        # and analytics events (observed device_id attributions). We merge.
        # Inline find_many (instead of cluster_repo.list_for_entity) so the
        # query is tenant-scoped before `limit` truncates.
        clusters = await self._scoped_find_many(
            self._clusters, tenant_id=tenant_id,
            filters={"entity_id": entity_id}, limit=500,
        )
        clusters = [c for c in clusters if not c.get("unlinked_at")]
        clusters = _tenant_filter(clusters, tenant_id)

        cluster_items: dict[str, dict] = {}
        for c in clusters:
            if c.get("identifier_type") != "device":
                continue
            did = c.get("identifier_value")
            if not did:
                continue
            cluster_items[did] = {
                "id": did,
                "type": "device",
                "displayLabel": did,
                "source": "identity_cluster",
                "confidence": c.get("confidence", 1.0),
                "timestamps": {"linkedAt": _ts(c, "linked_at")},
                "metadata": c,
                "links": {"sessions": f"/v1/profile/{entity_id}/sessions"},
            }

        observed_counts: dict[str, int] = defaultdict(int)
        if self._analytics is not None:
            events = await _safe("devices.analytics", self._analytics.query_events(
                tenant_id, {"user_id": entity_id}, limit=limit * 5,
            ))
            for e in events:
                # Canonical SDK events normalized by services/ingestion store
                # device_id at the top level, not inside properties. Read both
                # so custom properties-based payloads still work.
                did = (e.get("properties") or {}).get("device_id") or e.get("device_id")
                if did:
                    observed_counts[did] += 1

        for did, count in observed_counts.items():
            if did not in cluster_items:
                cluster_items[did] = {
                    "id": did,
                    "type": "device",
                    "displayLabel": did,
                    "source": "observed",
                    "confidence": min(1.0, count / 20),
                    "timestamps": {},
                    "metadata": {"observed_event_count": count},
                    "links": {"sessions": f"/v1/profile/{entity_id}/sessions"},
                }
            else:
                cluster_items[did]["metadata"]["observed_event_count"] = count

        items = sorted(
            cluster_items.values(),
            key=lambda r: r.get("metadata", {}).get("observed_event_count", 0),
            reverse=True,
        )[:limit]
        summary = {
            "device_count": len(items),
            "deterministic": sum(1 for i in items if i["source"] == "identity_cluster"),
            "observed_only": sum(1 for i in items if i["source"] == "observed"),
        }
        return _envelope(entity_id, tenant_id, "devices", items, summary, limit, ["identity_clusters", "analytics_events"])

    async def platforms(self, entity_id: str, tenant_id: str, limit: int = 50) -> dict:
        return await self._attribution_breakdown(
            entity_id, tenant_id, prop_key="platform", kind="platforms", limit=limit,
        )

    async def campaigns(self, entity_id: str, tenant_id: str, limit: int = 50) -> dict:
        """Campaign attribution derived from the analytics event stream."""
        return await self._attribution_breakdown(
            entity_id, tenant_id, prop_key="campaign_id", kind="campaigns", limit=limit,
        )

    async def protocols(self, entity_id: str, tenant_id: str, limit: int = 50) -> dict:
        # Protocol attribution can arrive on either the event payload itself
        # or on payment intents (x402/economic graph).
        events_break = await self._attribution_breakdown(
            entity_id, tenant_id, prop_key="protocol", kind="protocols", limit=limit,
        )

        intents = await self._scoped_find_many(
            self._intents, tenant_id=tenant_id,
            filters={"agent_id": entity_id}, limit=200,
        )
        intents = _tenant_filter(intents, tenant_id)
        counter: Counter[str] = Counter()
        for r in intents:
            p = r.get("protocol")
            if p:
                counter[p] += 1
        for proto, count in counter.items():
            found = next((i for i in events_break["items"] if i["id"] == proto), None)
            if found is None:
                events_break["items"].append({
                    "id": proto,
                    "type": "protocol",
                    "displayLabel": proto,
                    "interactionCount": count,
                    "timestamps": {},
                    "metadata": {"source": "payment_intents"},
                    "links": {"timeline": f"/v1/profile/{entity_id}/timeline"},
                })
            else:
                found["interactionCount"] = (found.get("interactionCount") or 0) + count
        events_break["items"] = sorted(
            events_break["items"], key=lambda r: r.get("interactionCount", 0), reverse=True,
        )[:limit]
        # Recompute rollups after the intent merge so summary stays consistent
        # with the items list — _attribution_breakdown computed these from the
        # event stream only, and we've now added / incremented intent-derived
        # entries that must be reflected in both protocols count and total.
        events_break["summary"]["protocols"] = len(events_break["items"])
        events_break["summary"]["protocol_count"] = len(events_break["items"])
        events_break["summary"]["total_interactions"] = sum(
            i.get("interactionCount", 0) for i in events_break["items"]
        )
        events_break["pagination"] = _paginate(events_break["items"], limit)
        events_break["provenance"]["sources"].append("payment_intents")
        return events_break

    async def _attribution_breakdown(
        self, entity_id: str, tenant_id: str, *, prop_key: str, kind: str, limit: int,
    ) -> dict:
        events: list[dict] = []
        if self._analytics is not None:
            events = await _safe(f"{kind}.analytics", self._analytics.query_events(
                tenant_id, {"user_id": entity_id}, limit=500,
            ))
        counter: Counter[str] = Counter()
        last_seen: dict[str, str] = {}
        for e in events:
            v = (e.get("properties") or {}).get(prop_key) or e.get(prop_key)
            if not v:
                continue
            counter[v] += 1
            ts = e.get("created_at") or e.get("timestamp")
            if ts and (v not in last_seen or ts > last_seen[v]):
                last_seen[v] = ts
        items = [
            {
                "id": v,
                "type": kind.rstrip("s"),
                "displayLabel": v,
                "interactionCount": count,
                "timestamps": {"lastSeen": last_seen.get(v)},
                "metadata": {},
                "links": {"timeline": f"/v1/profile/{entity_id}/timeline?{prop_key}={v}"},
            }
            for v, count in counter.most_common(limit)
        ]
        summary = {
            f"{kind.rstrip('s')}_count": len(items),
            "total_interactions": sum(i["interactionCount"] for i in items),
        }
        return _envelope(entity_id, tenant_id, kind, items, summary, limit, ["analytics_events"])

    async def journeys(self, entity_id: str, tenant_id: str, limit: int = 50) -> dict:
        rows = await self._scoped_find_many(
            self._journeys, tenant_id=tenant_id,
            filters={"entity_id": entity_id}, limit=limit,
        )
        rows = _tenant_filter(rows, tenant_id)
        items = [
            {
                "id": r.get("chain_id") or r.get("id"),
                "type": "journey_chain",
                "displayLabel": f"chain:{r.get('chain_id', '')[:8]}",
                "journeyCount": r.get("journey_count", 0),
                "firstJourneyId": r.get("first_journey_id"),
                "lastJourneyId": r.get("last_journey_id"),
                "timestamps": {
                    "spansStartedAt": r.get("spans_started_at"),
                    "spansLastSeenAt": r.get("spans_last_seen_at"),
                },
                "metadata": r,
                "links": {
                    "lastJourney": f"/v1/profile/{entity_id}/drill/journey/{r.get('last_journey_id')}"
                    if r.get("last_journey_id") else None,
                },
            }
            for r in rows
        ]
        summary = {
            "chain_count": len(items),
            "total_journeys": sum(i["journeyCount"] for i in items),
        }
        return _envelope(entity_id, tenant_id, "journeys", items, summary, limit, ["journey_chains"])

    async def rewards(self, entity_id: str, tenant_id: str, limit: int = 100) -> dict:
        # Rewards live in the analytics event stream under the reward event
        # family (rewards.evaluated, rewards.granted). Aggregate from there
        # without coupling to the RewardsService internals.
        events: list[dict] = []
        if self._analytics is not None:
            events = await _safe("rewards.analytics", self._analytics.query_events(
                tenant_id, {"user_id": entity_id}, limit=limit * 3,
            ))
        items = []
        total_value = 0.0
        for e in events:
            et = (e.get("event_type") or "").lower()
            if not et.startswith("reward") and "reward" not in et:
                continue
            props = e.get("properties") or {}
            value = props.get("value") or props.get("amount") or 0
            try:
                total_value += float(value)
            except (TypeError, ValueError):
                pass
            items.append({
                "id": e.get("id") or e.get("event_id"),
                "type": "reward",
                "displayLabel": props.get("reason") or et,
                "value": value,
                "currency": props.get("currency"),
                "timestamps": {"awardedAt": e.get("created_at") or e.get("timestamp")},
                "metadata": props,
                "links": {"event": f"/v1/profile/{entity_id}/timeline"},
            })
        items = items[:limit]
        summary = {
            "reward_count": len(items),
            "total_value": total_value,
        }
        return _envelope(entity_id, tenant_id, "rewards", items, summary, limit, ["analytics_events"])

    async def _transfers_for_entity(
        self, entity_id: str, tenant_id: str, limit: int,
    ) -> list[dict]:
        """Tenant-scoped transfer list (both directions, deduped, newest first).

        Replaces TransferRepository.list_for_entity for aggregator use because
        list_for_entity does not pass a tenant filter into find_many — without
        the filter, an unrelated tenant with many transfers for the same id
        could fill the page and crowd out the requested tenant's rows.
        """
        as_from = await self._scoped_find_many(
            self._transfers, tenant_id=tenant_id,
            filters={"from_entity_id": entity_id}, limit=limit,
        )
        as_to = await self._scoped_find_many(
            self._transfers, tenant_id=tenant_id,
            filters={"to_entity_id": entity_id}, limit=limit,
        )
        # _scoped_find_many already dedupes within each direction; we still
        # need to dedupe across directions (e.g. self-transfers) and re-sort.
        seen: set[str] = set()
        merged: list[dict] = []
        for r in (*as_from, *as_to):
            tid = r.get("transfer_id") or r.get("id")
            if tid and tid not in seen:
                seen.add(tid)
                merged.append(r)
        merged.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return merged[:limit]

    async def financials(self, entity_id: str, tenant_id: str, limit: int = 200) -> dict:
        transfers = await self._transfers_for_entity(entity_id, tenant_id, limit=limit)
        transfers = _tenant_filter(transfers, tenant_id)

        intents = await self._scoped_find_many(
            self._intents, tenant_id=tenant_id,
            filters={"agent_id": entity_id}, limit=limit,
        )
        intents = _tenant_filter(intents, tenant_id)

        settlements = await self._scoped_find_many(
            self._settlements, tenant_id=tenant_id,
            filters={"agent_id": entity_id}, limit=limit,
        )
        settlements = _tenant_filter(settlements, tenant_id)

        inflow = 0.0
        outflow = 0.0
        for t in transfers:
            try:
                amount = float(t.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if t.get("to_entity_id") == entity_id:
                inflow += amount
            if t.get("from_entity_id") == entity_id:
                outflow += amount

        settled = 0.0
        for s in settlements:
            try:
                settled += float(s.get("amount") or 0)
            except (TypeError, ValueError):
                pass

        recent_items = [
            {
                "id": t.get("transfer_id") or t.get("id"),
                "type": "transfer",
                "displayLabel": f"{t.get('from_entity_id', '')[:8]} → {t.get('to_entity_id', '')[:8]}",
                "amount": t.get("amount"),
                "assetId": t.get("asset_id"),
                "direction": "in" if t.get("to_entity_id") == entity_id else "out",
                "timestamps": {"occurredAt": t.get("occurred_at")},
                "metadata": t,
                "links": {"asset": f"/v1/flows/assets/{t.get('asset_id')}" if t.get("asset_id") else None},
            }
            for t in transfers[:limit]
        ]
        summary = {
            "inflow_total": inflow,
            "outflow_total": outflow,
            "net": inflow - outflow,
            "transfer_count": len(transfers),
            "payment_intent_count": len(intents),
            "settlement_count": len(settlements),
            "settled_total": settled,
        }
        return _envelope(
            entity_id, tenant_id, "financials", recent_items, summary, limit,
            ["transfers", "payment_intents", "settlement_events"],
        )

    async def relationships(self, entity_id: str, tenant_id: str, limit: int = 200) -> dict:
        """Typed normalized relationship list across delegation, ownership, flows."""
        rels: list[dict] = []
        # Single now-anchor so the predicate is identical for in/out and stays
        # in lock-step with /summary's count math.
        now_iso = utc_now().isoformat()

        def _delegation_active(d: dict) -> bool:
            if d.get("revoked_at"):
                return False
            if (d.get("starts_at") or "") > now_iso:
                return False
            ends = d.get("ends_at")
            if ends and ends <= now_iso:
                return False
            return True

        # Ownership: agents owned by this entity
        owned = await self._scoped_find_many(
            self._agent_configs, tenant_id=tenant_id,
            filters={"owner_entity_id": entity_id}, limit=limit,
        )
        owned = _tenant_filter(owned, tenant_id)
        for r in owned:
            rels.append({
                "id": f"owns:{r.get('agent_id')}",
                "type": "ownership",
                "subType": "owns_agent",
                "direction": "out",
                "from": entity_id,
                "to": r.get("agent_id"),
                "displayLabel": f"owns agent {r.get('agent_id')}",
                "strength": 1.0,
                "confidence": 1.0,
                "timestamps": {"createdAt": _ts(r, "created_at")},
                "metadata": r,
                "links": {"target": f"/v1/profile/{r.get('agent_id')}"},
            })

        # Ownership: wallets
        wallets = await self._scoped_find_many(
            self._wallets, tenant_id=tenant_id,
            filters={"owner_entity_id": entity_id}, limit=limit,
        )
        wallets = _tenant_filter(wallets, tenant_id)
        for w in wallets:
            rels.append({
                "id": f"owns:{w.get('wallet_id')}",
                "type": "ownership",
                "subType": "owns_wallet",
                "direction": "out",
                "from": entity_id,
                "to": w.get("wallet_id"),
                "displayLabel": f"owns wallet {w.get('chain')}:{(w.get('address') or '')[:10]}",
                "strength": 1.0,
                "confidence": 1.0,
                "timestamps": {"createdAt": _ts(w, "linked_at", "created_at")},
                "metadata": w,
                "links": {"target": f"/v1/profile/{entity_id}/wallets"},
            })

        # Delegation (granted out)
        granted = await self._scoped_find_many(
            self._delegations, tenant_id=tenant_id,
            filters={"grantor_entity_id": entity_id}, limit=limit,
        )
        granted = _tenant_filter(granted, tenant_id)
        for d in granted:
            rels.append({
                "id": f"delegates:{d.get('delegation_id')}",
                "type": "delegation",
                "subType": "grants",
                "direction": "out",
                "from": entity_id,
                "to": d.get("grantee_entity_id"),
                "displayLabel": f"delegates to {d.get('grantee_entity_id')}",
                "strength": 1.0,
                "confidence": 1.0,
                "active": _delegation_active(d),
                "scope": d.get("scope"),
                "timestamps": {
                    "startsAt": d.get("starts_at"),
                    "endsAt": d.get("ends_at"),
                    "revokedAt": d.get("revoked_at"),
                },
                "metadata": d,
                "links": {"target": f"/v1/profile/{d.get('grantee_entity_id')}"},
            })

        # Delegation (received in)
        received = await self._scoped_find_many(
            self._delegations, tenant_id=tenant_id,
            filters={"grantee_entity_id": entity_id}, limit=limit,
        )
        received = _tenant_filter(received, tenant_id)
        for d in received:
            rels.append({
                "id": f"delegated_from:{d.get('delegation_id')}",
                "type": "delegation",
                "subType": "receives",
                "direction": "in",
                "from": d.get("grantor_entity_id"),
                "to": entity_id,
                "displayLabel": f"acts on behalf of {d.get('grantor_entity_id')}",
                "strength": 1.0,
                "confidence": 1.0,
                "active": _delegation_active(d),
                "scope": d.get("scope"),
                "timestamps": {
                    "startsAt": d.get("starts_at"),
                    "endsAt": d.get("ends_at"),
                    "revokedAt": d.get("revoked_at"),
                },
                "metadata": d,
                "links": {"target": f"/v1/profile/{d.get('grantor_entity_id')}"},
            })

        # Transfer counterparties — surface other entities financially linked
        transfers = await self._transfers_for_entity(entity_id, tenant_id, limit=limit)
        transfers = _tenant_filter(transfers, tenant_id)
        counterparties: Counter[str] = Counter()
        for t in transfers:
            other = t.get("to_entity_id") if t.get("from_entity_id") == entity_id else t.get("from_entity_id")
            if other and other != entity_id:
                counterparties[other] += 1
        for other, count in counterparties.most_common(50):
            rels.append({
                "id": f"flow_with:{other}",
                "type": "financial_flow",
                "subType": "transfer_counterparty",
                "direction": "bidirectional",
                "from": entity_id,
                "to": other,
                "displayLabel": f"transfers with {other}",
                "strength": min(1.0, count / 10),
                "confidence": 1.0,
                "interactionCount": count,
                "timestamps": {},
                "metadata": {},
                "links": {"target": f"/v1/profile/{other}"},
            })

        rels = rels[:limit]
        summary = {
            "relationship_count": len(rels),
            "by_type": dict(Counter(r["type"] for r in rels)),
        }
        return _envelope(
            entity_id, tenant_id, "relationships", rels, summary, limit,
            ["agent_configs", "entity_wallets", "delegations", "transfers"],
        )

    async def summary(self, entity_id: str, tenant_id: str) -> dict:
        """Dashboard-ready concise snapshot.

        Pre-computed counts across the most common Profile 360 dimensions so
        a UI tile bank only needs one call. Each sub-count is a `safe()` so
        partial failures don't hide the rest of the snapshot.
        """
        results = await asyncio.gather(
            _safe("summary.entity", self._entities.find_by_id(entity_id)),
            self._scoped_find_many(self._agent_configs, tenant_id=tenant_id,
                                   filters={"owner_entity_id": entity_id}, limit=200),
            self._scoped_find_many(self._wallets, tenant_id=tenant_id,
                                   filters={"owner_entity_id": entity_id}, limit=200),
            self._transfers_for_entity(entity_id, tenant_id, limit=500),
            self._scoped_find_many(self._delegations, tenant_id=tenant_id,
                                   filters={"grantor_entity_id": entity_id}, limit=200),
            self._scoped_find_many(self._delegations, tenant_id=tenant_id,
                                   filters={"grantee_entity_id": entity_id}, limit=200),
            _safe("summary.behavior", self._behavior.find_by_id(entity_id)),
            self._scoped_find_many(self._journeys, tenant_id=tenant_id,
                                   filters={"entity_id": entity_id}, limit=50),
            self._scoped_find_many(self._agent_execs, tenant_id=tenant_id,
                                   filters={"agent_id": entity_id}, limit=100),
        )
        entity, agents, wallets, transfers, deleg_out, deleg_in, behavior, chains, execs = results
        # Tenant guard on the entity row too — find_by_id is not tenant-scoped,
        # so a foreign-tenant entity with this id would otherwise leak its
        # display_name / metadata into the summary response.
        if isinstance(entity, dict) and entity.get("tenant_id") not in (None, "", tenant_id):
            entity = None
        entity = entity if isinstance(entity, dict) else None
        agents = _tenant_filter(agents or [], tenant_id)
        wallets = _tenant_filter(wallets or [], tenant_id)
        transfers = _tenant_filter(transfers or [], tenant_id)
        deleg_out = _tenant_filter(deleg_out or [], tenant_id)
        deleg_in = _tenant_filter(deleg_in or [], tenant_id)
        chains = _tenant_filter(chains or [], tenant_id)
        execs = _tenant_filter(execs or [], tenant_id)

        inflow = sum(_safe_float(t.get("amount")) for t in transfers if t.get("to_entity_id") == entity_id)
        outflow = sum(_safe_float(t.get("amount")) for t in transfers if t.get("from_entity_id") == entity_id)
        # Match DelegationRepository.active_for: a delegation is active iff it
        # is not revoked AND starts_at has passed AND ends_at is unset or in
        # the future. Without the time-window predicate, /summary inflated
        # active_delegations_* by including expired or not-yet-started grants.
        now_iso = utc_now().isoformat()

        def _is_active(d: dict) -> bool:
            if d.get("revoked_at"):
                return False
            if (d.get("starts_at") or "") > now_iso:
                return False
            ends = d.get("ends_at")
            if ends and ends <= now_iso:
                return False
            return True

        active_deleg_in = [d for d in deleg_in if _is_active(d)]
        active_deleg_out = [d for d in deleg_out if _is_active(d)]

        bx = behavior if isinstance(behavior, dict) and behavior.get("tenant_id") in (None, "", tenant_id) else None
        snapshot = {
            "entity": _normalize_entity(entity, entity_id, tenant_id),
            "counts": {
                "agents": len(agents),
                "wallets": len(wallets),
                "transfers": len(transfers),
                "delegations_granted": len(deleg_out),
                "delegations_received": len(deleg_in),
                "active_delegations_granted": len(active_deleg_out),
                "active_delegations_received": len(active_deleg_in),
                "journey_chains": len(chains),
                "agent_executions": len(execs),
            },
            "financials": {
                "inflow_total": inflow,
                "outflow_total": outflow,
                "net": inflow - outflow,
            },
            "behavior": {
                "automation_ratio": (bx or {}).get("automation_ratio"),
                "decision_latency_ms": (bx or {}).get("decision_latency_ms"),
                "risk_score": (bx or {}).get("risk_score"),
                "anomaly_flags": (bx or {}).get("anomaly_flags") or [],
                "computed_at": (bx or {}).get("computed_at"),
                "computed": bx is not None,
            },
            "links": {
                "graph": f"/v1/profile/{entity_id}/graph",
                "timeline": f"/v1/profile/{entity_id}/timeline",
                "relationships": f"/v1/profile/{entity_id}/relationships",
                "financials": f"/v1/profile/{entity_id}/financials",
                "agents": f"/v1/profile/{entity_id}/agents",
                "wallets": f"/v1/profile/{entity_id}/wallets",
                "journeys": f"/v1/profile/{entity_id}/journeys",
                "sessions": f"/v1/profile/{entity_id}/sessions",
                "devices": f"/v1/profile/{entity_id}/devices",
                "platforms": f"/v1/profile/{entity_id}/platforms",
                "protocols": f"/v1/profile/{entity_id}/protocols",
                "rewards": f"/v1/profile/{entity_id}/rewards",
                "delegations": f"/v1/profile/{entity_id}/delegations",
                "realtime": f"/v1/realtime/sse?entity_id={entity_id}",
            },
        }
        return {
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "kind": "summary",
            "snapshot": snapshot,
            "computed_at": utc_now().isoformat(),
            "provenance": {
                "sources": [
                    "entities", "agent_configs", "entity_wallets", "transfers",
                    "delegations", "behavior_profiles", "journey_chains",
                    "agent_executions",
                ],
            },
        }

    # ── Drill ────────────────────────────────────────────────────────

    async def drill(
        self,
        entity_id: str,
        tenant_id: str,
        object_type: str,
        object_id: str,
    ) -> dict:
        """Generic deep-drill into any related Profile 360 object.

        Returns the object itself plus normalized references to every
        directly related dimension. Designed so the UI can render a
        navigation breadcrumb without prior knowledge of which table the
        object lives in.
        """
        ot = object_type.lower()
        record: Optional[dict] = None
        related: dict[str, list[dict]] = {}

        if ot in ("agent", "agent_config"):
            record = await _safe("drill.agent", self._agent_configs.find_by_id(object_id))
            if record and record.get("tenant_id") in (None, "", tenant_id):
                execs = await self._scoped_find_many(
                    self._agent_execs, tenant_id=tenant_id,
                    filters={"agent_id": object_id}, limit=20,
                )
                related["executions"] = [_drill_ref(e, "agent_execution", "execution_id") for e in _tenant_filter(execs, tenant_id)]
                intents = await self._scoped_find_many(
                    self._intents, tenant_id=tenant_id,
                    filters={"agent_id": object_id}, limit=20,
                )
                related["payment_intents"] = [_drill_ref(i, "payment_intent", "intent_id") for i in _tenant_filter(intents, tenant_id)]

        elif ot in ("wallet",):
            record = await _safe("drill.wallet", self._wallets.find_by_id(object_id))
            if record and record.get("tenant_id") in (None, "", tenant_id):
                transfers = await self._transfers_for_entity(
                    record.get("owner_entity_id") or "", tenant_id, limit=20,
                )
                related["transfers"] = [_drill_ref(t, "transfer", "transfer_id") for t in _tenant_filter(transfers, tenant_id)]

        elif ot in ("delegation",):
            record = await _safe("drill.delegation", self._delegations.find_by_id(object_id))

        elif ot in ("transfer", "flow"):
            record = await _safe("drill.transfer", self._transfers.find_by_id(object_id))

        elif ot in ("asset",):
            record = await _safe("drill.asset", self._assets.find_by_id(object_id))

        elif ot in ("entity", "human", "organization", "org"):
            record = await _safe("drill.entity", self._entities.find_by_id(object_id))

        elif ot in ("journey", "journey_chain", "chain"):
            record = await _safe("drill.journey", self._journeys.find_by_id(object_id))

        elif ot in ("payment_intent", "intent"):
            record = await _safe("drill.intent", self._intents.find_by_id(object_id))

        elif ot in ("settlement",):
            record = await _safe("drill.settlement", self._settlements.find_by_id(object_id))

        elif ot in ("agent_execution", "execution"):
            record = await _safe("drill.execution", self._agent_execs.find_by_id(object_id))

        else:
            record = None

        if not record or record.get("tenant_id") not in (None, "", tenant_id):
            return _drill_not_found(entity_id, tenant_id, object_type, object_id)

        # This route is profile-scoped: the drilled object must be related to
        # the requesting entity_id, otherwise tenant-mates could enumerate each
        # other's wallets / delegations / transfers by id. Apply per-type
        # association checks.
        if not _drill_belongs_to_profile(ot, record, entity_id):
            return _drill_not_found(entity_id, tenant_id, object_type, object_id)

        return {
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "kind": "drill",
            "object_type": object_type,
            "object_id": object_id,
            "found": True,
            "object": record,
            "related": related,
            "computed_at": utc_now().isoformat(),
        }


def _drill_not_found(entity_id: str, tenant_id: str, object_type: str, object_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "kind": "drill",
        "object_type": object_type,
        "object_id": object_id,
        "found": False,
        "object": None,
        "related": {},
        "computed_at": utc_now().isoformat(),
    }


def _drill_belongs_to_profile(ot: str, record: dict, entity_id: str) -> bool:
    """Profile-scoped association guard for the drill endpoint.

    The drill route lives under /v1/profile/{entity_id}/drill/..., so the
    drilled object must be related to entity_id. Otherwise a caller with
    tenant-scoped read access could enumerate other entities' private
    objects (wallets, delegations, transfers, executions, ...) just by
    guessing ids. Each branch encodes the canonical relationship for that
    object type — owner_entity_id for assets, grantor/grantee for
    delegations, agent_id for agent-owned objects, from/to for transfers,
    etc.
    """
    if not record:
        return False

    if ot in ("agent", "agent_config"):
        return record.get("owner_entity_id") == entity_id or record.get("agent_id") == entity_id
    if ot == "wallet":
        return record.get("owner_entity_id") == entity_id
    if ot == "delegation":
        return entity_id in (record.get("grantor_entity_id"), record.get("grantee_entity_id"))
    if ot in ("transfer", "flow"):
        return entity_id in (record.get("from_entity_id"), record.get("to_entity_id"))
    if ot in ("entity", "human", "organization", "org"):
        return record.get("entity_id") == entity_id or record.get("id") == entity_id
    if ot in ("journey", "journey_chain", "chain"):
        return record.get("entity_id") == entity_id
    if ot in ("payment_intent", "intent"):
        return record.get("agent_id") == entity_id
    if ot == "settlement":
        return record.get("agent_id") == entity_id
    if ot in ("agent_execution", "execution"):
        return record.get("agent_id") == entity_id
    # Asset is a catalog entry (token/NFT/fiat) shared across entities; gating
    # by entity ownership would always fail. Permit it only when something in
    # the row carries the requesting entity (custom catalogs may store owner).
    if ot == "asset":
        return record.get("owner_entity_id") in (None, entity_id)
    return False


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _drill_ref(row: dict, type_label: str, id_key: str) -> dict:
    return {
        "id": row.get(id_key) or row.get("id"),
        "type": type_label,
        "displayLabel": row.get("display_name") or row.get(id_key) or row.get("id"),
        "timestamps": {"createdAt": _ts(row, "created_at", "occurred_at", "started_at")},
    }


def _normalize_entity(record: Optional[dict], entity_id: str, tenant_id: str) -> dict:
    if not record:
        return {
            "id": entity_id,
            "type": "unknown",
            "displayLabel": entity_id,
            "tenant_id": tenant_id,
            "known": False,
        }
    return {
        "id": record.get("entity_id") or entity_id,
        "type": record.get("entity_type") or "unknown",
        "displayLabel": record.get("display_name") or record.get("entity_id") or entity_id,
        "tenant_id": record.get("tenant_id") or tenant_id,
        "parentEntityId": record.get("parent_entity_id"),
        "metadata": record.get("metadata") or {},
        "timestamps": {
            "createdAt": record.get("created_at"),
            "updatedAt": record.get("updated_at"),
        },
        "known": True,
    }
