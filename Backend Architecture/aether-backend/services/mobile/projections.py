"""Mobile gateway projections — bounded, redacted views (M3a, decision-log D12).

Composes the five mobile surfaces (``/today``, ``/profile``, ``/campaign``,
``/alerts``, ``/briefing``) from the OWNING services — it NEVER re-calculates
Profile360 / Campaign360 / graph truth. Every projection is:

* **bounded** — lists are truncated and per-field lengths are capped;
* **redacted** — amounts, emails, phones, and long digit runs become
  ``[redacted]``. The D11 projection helper
  (``services/notification_intelligence/projection.py``) is REUSED — its
  ``build_projection`` and redaction/truncation routines — never duplicated;
* **data-truth-preserving** — owning-service values pass through composed /
  bounded / redacted only, never recomputed.

Wire fields are snake_case (decision-log D6); owning-service values that arrive
camelCase (e.g. the profile-360 ``entity`` block) are re-keyed at this boundary,
not re-derived. ``MobileProjectionService`` accepts injected owning-service
collaborators so unit tests exercise it with fakes (no DB).

Owners reused (prohibited-duplicate ledger, decision-log D12):
* profile summary  -> ``Profile360Aggregator.summary`` (services/profile)
* campaign summary -> ``CampaignRepository`` + ``CampaignPopulationExplorer``
  (services/campaign)
* alerts inbox     -> ``notification_intelligence.inbox`` (single inbox)
* explore briefing -> ``services/exploration.store`` + ``services/noesis``
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from shared.common.common import NotFoundError

# ── D11 redaction helper — reused, never duplicated ─────────────────────────
# The projection boundary owns the redaction regexes / truncation policy
# (amounts, emails, phones, long digit runs). We import its helpers rather than
# re-declaring them so a single canonical implementation stays authoritative.
from services.notification_intelligence.projection import (
    _redact,  # canonical redaction (D11) — reused, not duplicated
    _truncate,  # canonical truncation (D11) — reused, not duplicated
    build_projection,
)

REDACTED = "[redacted]"

# ── Bounding limits (each surface is a short attention pointer, not a page) ──
DIGEST_RECENT_ALERTS = 5          # recent redacted titles on the Today screen
DIGEST_ALERT_SCAN_LIMIT = 100     # bounded scan for the top-severity count
INBOX_DEFAULT_LIMIT = 50
INBOX_MAX_LIMIT = 200
PROFILE_ANOMALY_FLAGS_MAX = 10
BRIEFING_VIEWS_DEFAULT = 5
BRIEFING_CONVERSATIONS_DEFAULT = 5

# Per-field length caps (mirrors the D11 push caps; content beyond is truncated).
TITLE_MAX_CHARS = 80
BODY_MAX_CHARS = 160
SUMMARY_MAX_CHARS = 120
ENTITY_NAME_MAX_CHARS = 80

# "Top severity" is a bounded presentation choice on the mobile surface — the
# inbox rows themselves remain the canonical severity truth.
TOP_SEVERITIES: tuple[str, ...] = ("P0", "P1")


def _redact_sensitive(value: Any) -> Optional[str]:
    """A sensitive scalar (amount / account id by contract) -> ``[redacted]``.

    Data-truth-preserving: ``None`` stays ``None``, any present value collapses
    to the redaction marker, so a client can tell "absent" apart from
    "present-but-redacted" without ever seeing the value.
    """
    if value is None or value == "":
        return None
    return REDACTED


def _text(value: Any, max_chars: int = BODY_MAX_CHARS) -> str:
    """Redact + truncate a free-text field (``""`` for ``None``/empty)."""
    return _truncate(_redact(value), max_chars)


# ── Profile summary projection (Profile360 truth, composed not recomputed) ────

_PROFILE_FINANCIAL_FIELDS: tuple[str, ...] = (
    "inflow_total",
    "outflow_total",
    "net",
    "inflow_usd",
    "outflow_usd",
    "net_usd",
)


def _project_profile_financials(financials: Any) -> Optional[dict]:
    if not isinstance(financials, dict):
        return None
    projected: dict[str, Any] = {}
    for key in _PROFILE_FINANCIAL_FIELDS:
        projected[key] = _redact_sensitive(financials.get(key))
    # rollup_status is a status vocabulary value, not an amount.
    projected["rollup_status"] = financials.get("rollup_status")
    return projected


def _project_profile_entity(entity: Any) -> Optional[dict]:
    if not isinstance(entity, dict):
        return None
    timestamps = entity.get("timestamps") if isinstance(entity.get("timestamps"), dict) else {}
    return {
        "id": entity.get("id"),
        "type": entity.get("type"),
        "display_label": (
            _text(
                entity.get("displayLabel") or entity.get("display_label"),
                ENTITY_NAME_MAX_CHARS,
            )
            or None
        ),
        "parent_entity_id": entity.get("parentEntityId") or entity.get("parent_entity_id"),
        "known": entity.get("known"),
        "created_at": timestamps.get("createdAt") or entity.get("created_at"),
        "updated_at": timestamps.get("updatedAt") or entity.get("updated_at"),
    }


def _project_profile_behavior(behavior: Any) -> Optional[dict]:
    if not isinstance(behavior, dict):
        return None
    flags = [_redact(flag) for flag in (behavior.get("anomaly_flags") or []) if flag]
    return {
        "automation_ratio": behavior.get("automation_ratio"),
        "decision_latency_ms": behavior.get("decision_latency_ms"),
        "risk_score": behavior.get("risk_score"),
        "anomaly_flags": flags[:PROFILE_ANOMALY_FLAGS_MAX],
        "computed_at": behavior.get("computed_at"),
        "computed": behavior.get("computed"),
    }


def _profile_snapshot(summary: dict) -> dict:
    """The Profile360 block inside a ``Profile360Aggregator.summary`` result.

    The owning service nests the profile truth under ``snapshot`` (top level
    carries only ``entity_id`` / ``tenant_id`` / ``kind`` / ``dependency_status``
    / ``computed_at`` / ``provenance``). Read from ``snapshot``; fall back to the
    raw dict for injected fakes that pass a flat block.
    """
    snapshot = summary.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else summary


def project_profile_summary(summary: Any) -> Optional[dict]:
    """Bounded redaction of a ``Profile360Aggregator.summary`` result.

    The owning service's counts pass through unchanged (composed, never
    recomputed); amounts and PII collapse to ``[redacted]``.
    """
    if not isinstance(summary, dict):
        return None
    block = _profile_snapshot(summary)
    return {
        "entity_id": block.get("canonical_entity_id"),
        "entity": _project_profile_entity(block.get("entity")),
        "counts": block.get("counts") or {},
        "financials": _project_profile_financials(block.get("financials")),
        "behavior": _project_profile_behavior(block.get("behavior")),
    }


def project_profile_peek(summary: Any) -> Optional[dict]:
    """A bounded 'relevant peek' of the profile summary for the Today digest."""
    projected = project_profile_summary(summary)
    if projected is None:
        return None
    behavior = projected.get("behavior") or {}
    counts = projected.get("counts") or {}
    return {
        "entity_id": projected.get("entity_id"),
        "entity": projected.get("entity"),
        "counts": {
            key: counts.get(key)
            for key in ("agents", "wallets", "active_delegations_received", "journey_chains")
        },
        "risk_score": behavior.get("risk_score"),
        "anomaly_flags": behavior.get("anomaly_flags") or [],
        "financials": projected.get("financials"),
    }


# ── Campaign summary projection (Campaign360 truth, composed not recomputed) ──

_CAMPAIGN_COUNT_FIELDS: tuple[str, ...] = (
    "observed_count",
    "resolved_count",
    "engaged_count",
    "converted_count",
    "attributed_count",
    "conversion_count",
    "touchpoint_count",
    "impressions",
    "clicks",
)
_CAMPAIGN_RATIO_FIELDS: tuple[str, ...] = (
    "ctr",
    "identity_resolution_rate",
    "fractional_attributed_conversions",
)
_CAMPAIGN_AMOUNT_FIELDS: tuple[str, ...] = (
    "spend_usd",
    "cpm",
    "cpc",
    "gross_attributed_revenue",
    "net_attributed_revenue",
    "roas",
)


def project_campaign_summary(overview: Any) -> Optional[dict]:
    """Bounded redaction of a ``CampaignPopulationExplorer.get_overview`` result."""
    if not isinstance(overview, dict):
        return None
    return {
        "campaign_id": overview.get("campaign_id"),
        "name": _text(overview.get("campaign_name"), ENTITY_NAME_MAX_CHARS) or None,
        "status": overview.get("status"),
        "channel": overview.get("channel"),
        "period": overview.get("period") or {},
        "counts": {key: overview.get(key) for key in _CAMPAIGN_COUNT_FIELDS},
        "ratios": {key: overview.get(key) for key in _CAMPAIGN_RATIO_FIELDS},
        "amounts": {key: _redact_sensitive(overview.get(key)) for key in _CAMPAIGN_AMOUNT_FIELDS},
        "attribution_model": overview.get("attribution_model"),
        "data_quality": overview.get("data_quality"),
    }


# ── Alerts projection (single canonical inbox, redacted via D11) ─────────────

def project_alert(row: Mapping[str, Any]) -> dict:
    """Redact one canonical inbox row via the D11 projection helper.

    ``build_projection`` redacts/bounds title/body/summary and derives the
    continuation-plane deep-link class — the same single projection boundary the
    push adapters consume.
    """
    proj = build_projection(row)
    return {
        "id": row.get("id"),
        "category": row.get("category") or proj.push_category,
        "severity": row.get("severity"),
        "title": proj.push_title,
        "body": proj.push_body,
        "summary": proj.push_summary,
        "deep_link_class": proj.push_deep_link_class,
        "read": bool(row.get("read")),
        "count": row.get("count", 1),
        "created_at": row.get("created_at"),
    }


# ── Explore briefing projections (saved views + noesis conversations) ────────

def project_view(view: Any) -> Optional[dict]:
    if not isinstance(view, dict):
        return None
    return {
        "view_id": view.get("view_id"),
        "name": _text(view.get("name"), ENTITY_NAME_MAX_CHARS) or None,
        "saved_at": view.get("saved_at"),
    }


def project_conversation(conversation: Any) -> Optional[dict]:
    if not isinstance(conversation, dict):
        return None
    return {
        "conversation_id": conversation.get("conversation_id"),
        "last_message": _text(conversation.get("last_message"), SUMMARY_MAX_CHARS) or None,
        "last_intent": _text(conversation.get("last_intent"), TITLE_MAX_CHARS) or None,
        "last_ts": conversation.get("last_ts"),
    }


# ── MobileProjectionService ──────────────────────────────────────────────────

class MobileProjectionService:
    """Compose bounded, redacted mobile projections from owning services.

    Collaborators are injected for tests; when ``None`` the production defaults
    are lazily resolved to the SAME owning-service components the canonical
    routes use (Profile360Aggregator, CampaignRepository + explorer, inbox,
    saved-views store, Noesis conversation store). No projection re-calculates
    owning-service truth.
    """

    def __init__(
        self,
        *,
        profile_aggregator: Any = None,
        campaign_repo: Any = None,
        campaign_explorer: Any = None,
        inbox_list: Any = None,
        inbox_unread: Any = None,
        views_repo: Any = None,
        noesis_store: Any = None,
        noesis_status: Any = None,
    ) -> None:
        self._profile = profile_aggregator
        self._campaign_repo = campaign_repo
        self._campaign_explorer = campaign_explorer
        self._inbox_list = inbox_list
        self._inbox_unread = inbox_unread
        self._views = views_repo
        self._noesis = noesis_store
        self._noesis_status = noesis_status

    # ── owning-service resolvers (lazy production defaults) ──────────────

    async def _profile_summary(self, entity_id: str, tenant_id: str) -> dict:
        if self._profile is None:
            from services.profile.aggregator import Profile360Aggregator

            self._profile = Profile360Aggregator()
        return await self._profile.summary(entity_id=entity_id, tenant_id=tenant_id)

    async def _find_campaign(self, campaign_id: str) -> Optional[dict]:
        if self._campaign_repo is None:
            from repositories.repos import CampaignRepository

            self._campaign_repo = CampaignRepository()
        return await self._campaign_repo.find_by_id(campaign_id)

    async def _campaign_overview(
        self, tenant_id: str, campaign_id: str, campaign: Optional[dict]
    ) -> dict:
        if self._campaign_explorer is None:
            # Mirrors the exact explorer construction in services/campaign/routes.py.
            from services.campaign.exploration import CampaignPopulationExplorer
            from services.measurement.repositories.attribution_run_repo import (
                AttributionRunRepository,
            )
            from services.measurement.repositories.conversion_repo import ConversionRepository
            from services.measurement.repositories.journey_repo import JourneyRepository
            from services.measurement.repositories.spend_repo import SpendRepository
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository

            self._campaign_explorer = CampaignPopulationExplorer(
                touchpoint_repo=TouchpointRepository(),
                conversion_repo=ConversionRepository(),
                run_repo=AttributionRunRepository(),
                journey_repo=JourneyRepository(),
                spend_repo=SpendRepository(),
            )
        return await self._campaign_explorer.get_overview(
            tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign or {}
        )

    async def _list_inbox(self, tenant_id: str, **kwargs: Any) -> list[dict]:
        if self._inbox_list is None:
            from services.notification_intelligence.inbox import list_inbox_notifications

            self._inbox_list = list_inbox_notifications
        return await self._inbox_list(tenant_id=tenant_id, **kwargs)

    async def _unread_count(self, tenant_id: str) -> int:
        if self._inbox_unread is None:
            from services.notification_intelligence.inbox import unread_notification_count

            self._inbox_unread = unread_notification_count
        return await self._inbox_unread(tenant_id=tenant_id)

    async def _list_views(self, tenant_id: str, limit: int, offset: int) -> list[dict]:
        if self._views is None:
            from services.exploration.store import ExplorationViewRepository

            self._views = ExplorationViewRepository()
        return await self._views.list_scoped(tenant_id=tenant_id, limit=limit, offset=offset)

    async def _list_conversations(self, tenant_id: str, limit: int) -> list[dict]:
        if self._noesis is None:
            from services.noesis.conversation import NoesisConversationStore

            self._noesis = NoesisConversationStore()
        return await self._noesis.list_for_tenant(tenant_id=tenant_id, limit=limit)

    def _conversation_source_status(self, degraded: bool, items: list) -> str:
        # Reuses the exact noesis route vocabulary helper (missing/empty/available).
        if self._noesis_status is None:
            from services.noesis.routes import _conversation_source_status

            self._noesis_status = _conversation_source_status
        return self._noesis_status(degraded, items)

    # ── projection surface methods ────────────────────────────────────────

    async def today_digest(self, *, tenant_id: str, profile_user_id: Optional[str] = None) -> dict:
        """Today digest — alert counts + recent redacted titles + profile peek."""
        alerts = await self._list_inbox(
            tenant_id, unread_only=True, limit=DIGEST_ALERT_SCAN_LIMIT
        )
        unread = await self._unread_count(tenant_id)
        top_severity = sum(1 for a in alerts if (a.get("severity") or "") in TOP_SEVERITIES)
        recent = [
            {
                "id": a.get("id"),
                "title": build_projection(a).push_title,
                "category": a.get("category"),
                "severity": a.get("severity"),
                "created_at": a.get("created_at"),
            }
            for a in alerts[:DIGEST_RECENT_ALERTS]
        ]
        profile_peek = None
        if profile_user_id:
            profile_peek = project_profile_peek(
                await self._profile_summary(profile_user_id, tenant_id)
            )
        return {
            "unread_alert_count": unread,
            "top_severity_alert_count": top_severity,
            "recent_alerts": recent,
            "profile_peek": profile_peek,
        }

    async def profile_summary(self, *, tenant_id: str, user_id: str) -> Optional[dict]:
        summary = await self._profile_summary(user_id, tenant_id)
        return project_profile_summary(summary)

    async def campaign_summary(self, *, tenant_id: str, campaign_id: str) -> dict:
        campaign = await self._find_campaign(campaign_id)
        if campaign is None or campaign.get("tenant_id") != tenant_id:
            raise NotFoundError("campaign")
        overview = await self._campaign_overview(tenant_id, campaign_id, campaign)
        projected = project_campaign_summary(overview)
        if projected is None:
            raise NotFoundError("campaign")
        return projected

    async def alerts_inbox(
        self,
        *,
        tenant_id: str,
        unread_only: bool = False,
        limit: int = INBOX_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict:
        rows = await self._list_inbox(
            tenant_id, unread_only=unread_only, limit=min(limit, INBOX_MAX_LIMIT), offset=offset
        )
        unread = await self._unread_count(tenant_id)
        return {
            "alerts": [project_alert(row) for row in rows],
            "unread_count": unread,
            "count": len(rows),
        }

    async def explore_briefing(
        self,
        *,
        tenant_id: str,
        views_limit: int = BRIEFING_VIEWS_DEFAULT,
        conversations_limit: int = BRIEFING_CONVERSATIONS_DEFAULT,
    ) -> dict:
        views = await self._list_views(tenant_id, limit=views_limit, offset=0)
        try:
            conversations = await self._list_conversations(tenant_id, limit=conversations_limit)
            degraded = False
        except Exception:  # noqa: BLE001 — honest source status, mirrors noesis route
            conversations = []
            degraded = True
        return {
            "saved_views": [project_view(v) for v in views if project_view(v) is not None],
            "conversations": [
                project_conversation(c) for c in conversations if project_conversation(c) is not None
            ],
            "conversations_source_status": self._conversation_source_status(degraded, conversations),
        }


__all__ = [
    "MobileProjectionService",
    "project_alert",
    "project_campaign_summary",
    "project_conversation",
    "project_profile_peek",
    "project_profile_summary",
    "project_view",
]
