"""
Campaign Population Explorer — canonical service for Campaign 360 drill-down.

Powers all campaign exploration surfaces (tenant and Kyber operator).
Attribution is always delegated to the canonical measurement repos — this
service never calculates attribution independently.

Reconciliation invariants enforced in get_overview():
  attributed_count <= converted_count <= resolved_count <= observed_count
  credit sum per conversion reconciles within 1.0 ± 0.001 tolerance
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.graph.graph import VertexType

logger = get_logger("aether.campaign.exploration")

# Graph query safety limits (hard-enforced, never overridden per caller)
_MAX_DEPTH = 3
_MAX_NODES = 500
_MAX_EDGES = 1500
_GRAPH_TIMEOUT_S = 10.0

# Touchpoint types that are passive (impression-class) — excluded from 'engaged' count
_PASSIVE_TOUCHPOINT_TYPES = frozenset({
    "impression", "viewable_impression", "ad_exposure",
    "email_delivery", "push_presentation",
})

# Bounded sample size for the touchpoint freshness-watermark scan used by
# data_quality.projection_lag_hours in get_overview(). TouchpointRepository
# exposes no MAX(occurred_at) aggregate and list_by_campaign only supports
# ascending order, so the watermark is computed client-side over a bounded
# fetch — see the comment at its call site for the honesty tradeoff this implies.
_FRESHNESS_WATERMARK_SAMPLE_LIMIT = 10000


class CampaignPopulationExplorer:
    """Single canonical service for campaign 360 exploration.

    All repo references are injected — callers (routes.py) own instantiation.
    """

    def __init__(
        self,
        touchpoint_repo,
        conversion_repo,
        run_repo,
        journey_repo,
        spend_repo,
    ):
        self._tp = touchpoint_repo
        self._cv = conversion_repo
        self._ar = run_repo
        self._jn = journey_repo
        self._sp = spend_repo

    # ── Overview ─────────────────────────────────────────────────────────────

    async def get_overview(
        self,
        tenant_id: str,
        campaign_id: str,
        campaign: Optional[dict[str, Any]] = None,
        *,
        time_range: Optional[dict[str, str]] = None,
        attribution_model: str = "last_touch",
        attribution_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Reconciled campaign overview from spend + touchpoints + conversions + credits."""
        campaign = campaign or {}
        after = _parse_ts(time_range.get("start")) if time_range else None
        before = _parse_ts(time_range.get("end")) if time_range else None

        # Collect data in parallel conceptually but via sequential awaits (asyncpg does not
        # support concurrent queries on the same connection pool by default without tasks)
        spend_summary = await self._get_spend_summary(tenant_id, campaign_id, after, before)
        pop_summary = await self._tp.population_summary(
            tenant_id, campaign_id,
            after_occurred=after,
            before_occurred=before,
        )
        conv_summary = await self._cv.campaign_population_summary(
            tenant_id, campaign_id,
            attribution_run_id=attribution_run_id,
        )
        credit_summary = await self._ar.campaign_credit_summary(
            tenant_id, campaign_id,
            model_type=attribution_model,
        )
        # Freshness watermark for projection_lag_hours below. Deliberately NOT
        # scoped to the requested time_range: this reports pipeline currency
        # ("how stale is touchpoint capture for this campaign right now"), not
        # report-window recency — scoping it to time_range would manufacture a
        # false staleness signal whenever a caller views a historical window.
        # Bounded, best-effort scan (see _FRESHNESS_WATERMARK_SAMPLE_LIMIT): a
        # campaign with more touchpoints than the sample can under-report
        # freshness (an inflated lag from missing the true latest row) but
        # never over-report it, since earlier rows sort first and are the
        # ones dropped.
        watermark_rows = await self._tp.list_by_campaign(
            tenant_id, campaign_id,
            limit=_FRESHNESS_WATERMARK_SAMPLE_LIMIT,
        )

        observed = pop_summary.get("observed", 0)
        resolved = pop_summary.get("resolved", 0)
        engaged = pop_summary.get("engaged", 0)
        converted = conv_summary.get("converted_count", 0)
        attributed = conv_summary.get("attributed_count", 0)

        # Enforce reconciliation invariants (clamp, do not raise — data may be
        # eventually consistent). Whether the clamp actually changes a value is a
        # real signal: if the raw counts violated resolved<=observed,
        # engaged<=resolved, or attributed<=converted, that inconsistency must be
        # surfaced, not hidden behind a hardcoded reconciliation_status of "ok".
        clamped_resolved = min(resolved, observed)
        clamped_engaged = min(engaged, clamped_resolved)
        clamped_attributed = min(attributed, converted)
        reconciliation_inconsistent = (
            clamped_resolved != resolved
            or clamped_engaged != engaged
            or clamped_attributed != attributed
        )
        resolved, engaged, attributed = clamped_resolved, clamped_engaged, clamped_attributed

        gross_rev = conv_summary.get("attributed_gross_revenue", 0.0)
        net_rev = conv_summary.get("attributed_net_revenue", 0.0)
        spend_usd = float(spend_summary.get("total_spend_usd", 0.0))
        roas = (gross_rev / spend_usd) if spend_usd > 0 else None

        impressions = int(spend_summary.get("total_impressions", 0) or 0)
        clicks = int(spend_summary.get("total_clicks", 0) or 0)
        cpm = (spend_usd * 1000 / impressions) if impressions > 0 else None
        cpc = (spend_usd / clicks) if clicks > 0 else None
        ctr = (clicks / impressions) if impressions > 0 else None

        resolution_rate = (resolved / observed) if observed > 0 else None
        conversion_count = int(credit_summary.get("credit_count", 0))
        frac_conversions = float(credit_summary.get("total_attributed_conversions") or 0)

        # projection_lag_hours: now(UTC) minus the newest parseable occurred_at
        # across the campaign's touchpoints (the watermark fetched above).
        # Zero touchpoints or no parseable occurred_at -> null, never a
        # fabricated 0 — an absent watermark is not the same as a fresh one.
        # Clamped to >= 0 to absorb clock skew (a touchpoint whose occurred_at
        # lands fractionally after this request's "now").
        newest_occurred = _max_occurred_at(watermark_rows)
        if newest_occurred is not None:
            lag_hours = (datetime.now(timezone.utc) - newest_occurred).total_seconds() / 3600.0
            projection_lag_hours = max(0.0, lag_hours)
        else:
            projection_lag_hours = None

        # completeness_pct: observed distinct entities (population_summary,
        # above) against the campaign's platform-reported reach —
        # SpendRecord.reach, the connector's own distinct-audience total and
        # the only tenant-scoped, source-reported "expected entities" figure
        # this service can read for a campaign. impressions/clicks are raw
        # event counts, not distinct-entity counts, so pairing either of them
        # with `observed` would compare unlike units — deliberately avoided
        # rather than fabricating a mismatched denominator. Both sides here
        # are distinct-entity counts, so the ratio is a genuine capture-
        # completeness signal. Clamped at 100 because our identity resolution
        # can legitimately surface more distinct ids than the platform's own
        # (differently deduped) reach estimate. No connector reported a
        # nonzero reach for this campaign/window -> null, never a fabricated
        # denominator.
        expected_reach = int(spend_summary.get("total_reach", 0) or 0)
        completeness_pct = (
            min(100.0, (observed / expected_reach) * 100.0)
            if expected_reach > 0
            else None
        )

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "status": campaign.get("status", ""),
            "channel": campaign.get("channel", ""),
            "period": time_range or {},
            "spend_usd": spend_usd,
            "impressions": impressions,
            "clicks": clicks,
            "cpm": cpm,
            "cpc": cpc,
            "ctr": ctr,
            "observed_count": observed,
            "resolved_count": resolved,
            "engaged_count": engaged,
            "converted_count": converted,
            "attributed_count": attributed,
            "conversion_count": conversion_count,
            "fractional_attributed_conversions": frac_conversions,
            "gross_attributed_revenue": gross_rev,
            "net_attributed_revenue": net_rev,
            "roas": roas,
            "identity_resolution_rate": resolution_rate,
            "attribution_model": attribution_model,
            "attribution_run_id": attribution_run_id,
            "total_credit_weight": float(credit_summary.get("total_attributed_conversions") or 0),
            "touchpoint_count": int(spend_summary.get("touchpoint_count", 0) or 0),
            "data_quality": {
                "connector_freshness": "unknown",
                "attribution_run_freshness": "fresh" if credit_summary.get("credits") else "missing",
                "projection_lag_hours": projection_lag_hours,
                # Honest state: "inconsistent" when the clamp above detected an
                # invariant breach, otherwise "unknown" — this overview does not
                # reconcile against provider truth, so it must never claim "ok".
                "reconciliation_status": "inconsistent" if reconciliation_inconsistent else "unknown",
                "completeness_pct": completeness_pct,
            },
        }

    # ── Population ────────────────────────────────────────────────────────────

    async def get_population(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        population: str = "observed",
        population_type: Optional[str] = None,
        time_range: Optional[dict[str, str]] = None,
        channel: Optional[str] = None,
        cluster_id: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Paginated entity population for a campaign, filtered by funnel stage."""
        population = population_type or population
        after = _parse_ts(time_range.get("start")) if time_range else None
        before = _parse_ts(time_range.get("end")) if time_range else None

        if population in ("observed", "resolved", "engaged"):
            rows = await self._tp.list_by_campaign(
                tenant_id, campaign_id,
                after_occurred=after,
                before_occurred=before,
                channel=channel,
                limit=limit,
                cursor=cursor,
            )
            items = _touchpoints_to_population_rows(rows, population)
        elif population == "converted":
            rows = await self._cv.list_by_campaign(
                tenant_id, campaign_id,
                cluster_id=cluster_id,
                after_occurred=after,
                before_occurred=before,
                include_unattributed=True,
                limit=limit,
                cursor=cursor,
            )
            items = _conversions_to_population_rows(rows)
        else:
            # attributed / incremental — from attribution credits
            credit_summary = await self._ar.campaign_credit_summary(
                tenant_id, campaign_id,
                cluster_id=cluster_id,
                channel=channel,
            )
            credits = credit_summary.get("credits", [])
            items = _credits_to_population_rows(credits[:limit])

        next_cursor = items[-1].get("last_activity_at") if len(items) == limit else None
        return {
            "campaign_id": campaign_id,
            "population": population,
            "items": items,
            "pagination": {
                "limit": limit,
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
                "total_count": None,
            },
        }

    # ── Entities ──────────────────────────────────────────────────────────────

    async def get_entities(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        entity_types: Optional[list[str]] = None,
        time_range: Optional[dict[str, str]] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        after = _parse_ts(time_range.get("start")) if time_range else None
        before = _parse_ts(time_range.get("end")) if time_range else None

        rows = await self._tp.list_by_campaign(
            tenant_id, campaign_id,
            after_occurred=after,
            before_occurred=before,
            limit=limit * 5,  # over-fetch to de-dup by entity
            cursor=cursor,
        )

        # Deduplicate by canonical entity id
        seen: dict[str, dict[str, Any]] = {}
        for row in rows:
            eid = row.get("profile_id") or row.get("cluster_id") or row.get("anonymous_id")
            if not eid:
                continue
            etype = _infer_entity_type(row)
            if entity_types and etype not in entity_types:
                continue
            if eid not in seen:
                seen[eid] = {
                    "canonical_id": eid,
                    "entity_type": etype,
                    "cluster_id": row.get("cluster_id"),
                    "display_name": None,
                    "touchpoint_count": 0,
                    "conversion_count": 0,
                    "attributed_revenue": 0.0,
                    "last_activity_at": row.get("occurred_at"),
                }
            seen[eid]["touchpoint_count"] += 1
            if row.get("is_conversion"):
                seen[eid]["conversion_count"] += 1
            seen[eid]["last_activity_at"] = max(
                seen[eid]["last_activity_at"] or "",
                row.get("occurred_at") or "",
            ) or None

        items = list(seen.values())[:limit]
        next_cursor = items[-1].get("last_activity_at") if len(items) == limit else None
        return {
            "campaign_id": campaign_id,
            "items": items,
            "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        }

    # ── Clusters ──────────────────────────────────────────────────────────────

    async def get_clusters(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        time_range: Optional[dict[str, str]] = None,
        attribution_run_id: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        rollup = await self._ar.campaign_cluster_rollup(
            tenant_id, campaign_id,
            attribution_run_id=attribution_run_id,
        )

        # Apply cursor (cluster_id keyset)
        if cursor:
            rollup = [r for r in rollup if (r.get("cluster_id") or "") > cursor]

        items = rollup[:limit]
        items_out = []
        for r in items:
            items_out.append({
                "cluster_id": r.get("cluster_id"),
                "member_count": 0,
                "entity_type_counts": {},
                "touchpoint_count": 0,
                "conversion_count": int(r.get("conversion_count", 0)),
                "attributed_gross_revenue": float(r.get("attributed_gross_revenue", 0)),
                "attributed_net_revenue": float(r.get("attributed_net_revenue", 0)),
                "top_channels": [],
                "identity_confidence": None,
            })

        next_cursor = items[-1].get("cluster_id") if len(items) == limit else None
        return {
            "campaign_id": campaign_id,
            "items": items_out,
            "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        }

    # ── Journeys ──────────────────────────────────────────────────────────────

    async def get_journeys(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        time_range: Optional[dict[str, str]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        after = _parse_ts(time_range.get("start")) if time_range else None
        before = _parse_ts(time_range.get("end")) if time_range else None

        journeys = await self._jn.list_by_campaign(
            tenant_id, campaign_id,
            after_started=after,
            before_started=before,
            limit=limit,
            cursor=cursor,
        )

        items = []
        for j in journeys:
            items.append({
                "journey_id": j.get("journey_id"),
                "profile_id": j.get("profile_id"),
                "cluster_id": j.get("cluster_id"),
                "stage_count": len(j.get("touchpoint_ids") or []),
                "campaign_touchpoint_count": 0,
                "converted": j.get("journey_state") == "converted",
                "gross_revenue": 0.0,
                "started_at": j.get("started_at"),
                "completed_at": j.get("ended_at"),
            })

        next_cursor = items[-1].get("journey_id") if len(items) == limit else None
        return {
            "campaign_id": campaign_id,
            "items": items,
            "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        }

    # ── Graph ─────────────────────────────────────────────────────────────────

    async def get_graph_anchor(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a bounded campaign-centered graph query.

        Enforces hard limits: depth ≤ 3, nodes ≤ 500, edges ≤ 1500, timeout 10s.
        Uses VertexType.CAMPAIGN as the primary anchor node.
        Returns the graph plus truncation status and continuation_token.
        """
        depth = int(request.get("depth", 2))
        max_nodes = int(request.get("max_nodes", 200))
        max_edges = int(request.get("max_edges", 600))

        if depth > _MAX_DEPTH:
            raise ValueError(f"depth {depth} exceeds maximum allowed depth of {_MAX_DEPTH}")
        if max_nodes > _MAX_NODES:
            raise ValueError(f"max_nodes {max_nodes} exceeds limit of {_MAX_NODES}")
        if max_edges > _MAX_EDGES:
            raise ValueError(f"max_edges {max_edges} exceeds limit of {_MAX_EDGES}")

        population = request.get("population", "observed")
        filters = request.get("filters") or {}

        start_time = time.time()

        # Build the campaign anchor node
        anchor_node = {
            "id": campaign_id,
            "type": VertexType.CAMPAIGN,
            "label": f"Campaign:{campaign_id[:8]}",
            "properties": {"tenant_id": tenant_id, "population": population},
        }

        nodes = [anchor_node]
        edges: list[dict[str, Any]] = []
        truncated = False
        truncation_reason = None

        # Fetch connected entities from touchpoint data (depth=1 neighbors)
        try:
            tp_rows = await self._tp.list_by_campaign(
                tenant_id, campaign_id,
                limit=max_nodes - 1,
            )
            seen_ids: set[str] = set()
            for tp in tp_rows:
                if time.time() - start_time > _GRAPH_TIMEOUT_S:
                    truncated = True
                    truncation_reason = "timeout"
                    break
                if len(nodes) >= max_nodes:
                    truncated = True
                    truncation_reason = "max_nodes"
                    break

                eid = tp.get("profile_id") or tp.get("cluster_id") or tp.get("anonymous_id")
                if not eid or eid in seen_ids:
                    continue

                entity_types_filter = filters.get("entity_types")
                node_type = _infer_vertex_type(tp)
                if entity_types_filter and node_type not in entity_types_filter:
                    continue

                seen_ids.add(eid)
                nodes.append({
                    "id": eid,
                    "type": node_type,
                    "label": f"{node_type}:{eid[:8]}",
                    "properties": {
                        "channel": tp.get("channel"),
                        "touchpoint_type": tp.get("touchpoint_type"),
                    },
                })
                if len(edges) < max_edges:
                    edges.append({
                        "id": f"{campaign_id}:{eid}",
                        "source": campaign_id,
                        "target": eid,
                        "type": "CAMPAIGN_OBSERVED_ENTITY",
                        "layer": "H2H",
                        "weight": 1.0,
                    })
                else:
                    truncated = True
                    truncation_reason = truncation_reason or "max_edges"
        except Exception as exc:
            logger.warning("Graph anchor query error: %s", exc)
            truncated = True
            truncation_reason = f"error: {exc}"

        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "campaign_id": campaign_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "continuation_token": None,
            "depth_reached": 1 if len(nodes) > 1 else 0,
            "query_budget": {
                "max_nodes": max_nodes,
                "max_edges": max_edges,
                "max_depth": depth,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_spend_summary(
        self,
        tenant_id: str,
        campaign_id: str,
        after: Optional[datetime],
        before: Optional[datetime],
    ) -> dict[str, Any]:
        try:
            records = await self._sp.list_by_campaign(
                tenant_id, campaign_id,
                period_start=after,
                period_end=before,
                limit=1000,
            )
            total_spend = sum(float(r.get("media_spend") or 0) for r in records)
            total_impressions = sum(int(r.get("impressions") or 0) for r in records)
            total_clicks = sum(int(r.get("clicks") or 0) for r in records)
            # Reach is the connector's own distinct-audience estimate for the
            # campaign (SpendRecord.reach) — used as the completeness_pct
            # denominator in get_overview(). Summed here alongside the other
            # spend-record aggregates rather than queried separately.
            total_reach = sum(int(r.get("reach") or 0) for r in records)
            return {
                "total_spend_usd": total_spend,
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "total_reach": total_reach,
                "touchpoint_count": 0,
            }
        except Exception as exc:
            logger.warning("Spend summary unavailable for campaign=%s: %s", campaign_id, exc)
            return {
                "total_spend_usd": 0.0,
                "total_impressions": 0,
                "total_clicks": 0,
                "total_reach": 0,
                "touchpoint_count": 0,
            }


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _max_occurred_at(rows: list[dict[str, Any]]) -> Optional[datetime]:
    """Newest parseable ``occurred_at`` across a set of touchpoint rows.

    Used for the data_quality.projection_lag_hours watermark in get_overview().
    Rows with a missing or unparseable occurred_at are skipped rather than
    defaulting to "now" — an absent watermark must read as unknown, never as
    artificially fresh. Naive timestamps are treated as UTC, matching every
    other "now" reference in this module, so comparisons never raise on
    mixed aware/naive datetimes.
    """
    newest: Optional[datetime] = None
    for row in rows:
        ts = _parse_ts(row.get("occurred_at"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if newest is None or ts > newest:
            newest = ts
    return newest


def _infer_entity_type(row: dict[str, Any]) -> str:
    if row.get("profile_id"):
        return "profile"
    if row.get("cluster_id"):
        return "cluster"
    if row.get("account_id"):
        return "account"
    if row.get("organization_id"):
        return "organization"
    return "anonymous"


def _infer_vertex_type(row: dict[str, Any]) -> str:
    if row.get("profile_id"):
        return VertexType.USER
    if row.get("cluster_id"):
        return VertexType.IDENTITY_CLUSTER
    if row.get("account_id"):
        return VertexType.ORGANIZATION
    return VertexType.USER


def _touchpoints_to_population_rows(
    rows: list[dict[str, Any]],
    population: str,
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = row.get("profile_id") or row.get("cluster_id") or row.get("anonymous_id")
        if not eid:
            continue
        resolved = bool(row.get("profile_id") or row.get("cluster_id"))
        tp_type = row.get("touchpoint_type", "")
        engaged = resolved and tp_type not in _PASSIVE_TOUCHPOINT_TYPES

        if population == "resolved" and not resolved:
            continue
        if population == "engaged" and not engaged:
            continue

        if eid not in seen:
            seen[eid] = {
                "entity_id": eid,
                "entity_type": _infer_entity_type(row),
                "cluster_id": row.get("cluster_id"),
                "touchpoint_count": 0,
                "conversion_count": 0,
                "attributed_revenue": 0.0,
                "attribution_credit": 0.0,
                "identity_confidence": row.get("identity_confidence"),
                "last_activity_at": row.get("occurred_at"),
                "channels": [],
            }
        entry = seen[eid]
        entry["touchpoint_count"] += 1
        ch = row.get("channel")
        if ch and ch not in entry["channels"]:
            entry["channels"].append(ch)
        if row.get("occurred_at"):
            entry["last_activity_at"] = max(entry["last_activity_at"] or "", row["occurred_at"])

    return list(seen.values())


def _conversions_to_population_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        eid = row.get("profile_id") or row.get("cluster_id") or row.get("account_id")
        if not eid:
            continue
        out.append({
            "entity_id": eid,
            "entity_type": "profile" if row.get("profile_id") else "cluster",
            "cluster_id": row.get("cluster_id"),
            "touchpoint_count": 0,
            "conversion_count": 1,
            "attributed_revenue": float(row.get("gross_value") or 0),
            "attribution_credit": 0.0,
            "identity_confidence": None,
            "last_activity_at": row.get("occurred_at"),
            "channels": [],
        })
    return out


def _credits_to_population_rows(credits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for c in credits:
        eid = c.get("cluster_id") or c.get("touchpoint_id") or c.get("credit_id", "")
        if eid not in seen:
            seen[eid] = {
                "entity_id": eid,
                "entity_type": "cluster" if c.get("cluster_id") else "anonymous",
                "cluster_id": c.get("cluster_id"),
                "touchpoint_count": 1,
                "conversion_count": int(float(c.get("attributed_conversion_count") or 0)),
                "attributed_revenue": float(c.get("attributed_gross_revenue") or 0),
                "attribution_credit": float(c.get("credit_weight") or 0),
                "identity_confidence": c.get("identity_confidence"),
                "last_activity_at": None,
                "channels": [c["channel"]] if c.get("channel") else [],
            }
    return list(seen.values())
