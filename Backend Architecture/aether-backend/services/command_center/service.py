"""Read-only tenant Command Center aggregator.

Composes nine tenant sections into a single :class:`CommandCenterView` by
calling EXISTING tenant-scoped reads IN-PROCESS — never synthetic data, never a
re-HTTP round-trip. Every builder returns the underlying sub-service payload
verbatim (nothing tenant-visible is added or redacted); a builder whose read
fails degrades to ``unavailable``/``error`` with ``data=None`` rather than a
fabricated forward value, and a read that succeeds but is empty degrades to
``no_data`` (never ``error``).

Section → in-process source (all tenant-scoped, all tenant-safe):

* ``activation``          → :meth:`services.activation.service.ActivationService.get_status`
* ``value_strip``         → the outcome-ledger ``summary`` slice
  (``services.intelligence.routes._tenant_ledger``)
* ``ops_feed``            → intelligence recommendations + the tenant-safe
  reliability projection (``services.reliability.tenant_impact``)
* ``graph_snapshot``      → ``services.operational_intelligence.routes.graph_health``
  (own, shorter timeout — the graph read can be heavy)
* ``campaign_movement``   → the tenant campaign registry read
  (``repositories.repos.CampaignRepository``)
* ``data_confidence``     → ``services.data_quality`` tenant overview
* ``integration_health``  → SDK fleet + imports list + connectors list
* ``outcomes``            → the FULL outcome ledger (SAME read as ``value_strip``:
  read once, slice twice — no double fetch)
* ``next_best_actions``   → the tenant-safe (redacted) suggestions feed

OPERATOR BOUNDARY
-----------------
This aggregator is a TENANT surface. It composes ONLY tenant-scoped,
tenant-safe reads and NEVER imports operator-only services — not
``services/agent/ops_alerts.py``, not ``services/agent/briefings.py``, and not
any ``/v1/admin/kyber/*`` twin or Kyber operator module. The reliability and
suggestions sections deliberately call their tenant-safe projections
(``tenant_impact`` / ``redact_for_tenant``), so no operator-only field can leak
into a tenant view. The aggregator forwards ONLY ``tenant_id`` downstream; it
never threads the caller's raw request state into a sub-service read.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import Request

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from .models import CommandCenterView, SectionEnvelope, SectionState

logger = get_logger("aether.service.command_center")

# The graph section reads every vertex+edge for the tenant and can be heavy, so
# it gets its OWN, shorter budget inside the gather. On timeout it degrades to
# ``unavailable`` — never a fabricated snapshot.
_GRAPH_SECTION_TIMEOUT_SECONDS: float = 3.0

# Section key order is stable and matches CommandCenterView.sections.
_SECTION_KEYS: tuple[str, ...] = (
    "activation",
    "value_strip",
    "ops_feed",
    "graph_snapshot",
    "campaign_movement",
    "data_confidence",
    "integration_health",
    "outcomes",
    "next_best_actions",
)

# Provenance string surfaced on every envelope (including failed reads).
_SECTION_SOURCES: dict[str, str] = {
    "activation": "services.activation.ActivationService.get_status",
    "value_strip": "services.intelligence.outcome_ledger.summary",
    "ops_feed": "services.intelligence.recommendations+services.reliability.tenant_impact",
    "graph_snapshot": "services.operational_intelligence.graph_health",
    "campaign_movement": "repositories.CampaignRepository.find_many",
    "data_confidence": "services.data_quality.IntelligenceQualityService.overview",
    "integration_health": "services.sdk_health.fleet+services.imports.list+services.integrations.connectors",
    "outcomes": "services.intelligence.outcome_ledger",
    "next_best_actions": "services.suggestions.aether_feed(redacted)",
}


class _ScopedTenant:
    """Minimal tenant carrying ONLY the aggregator's ``tenant_id`` downstream.

    A couple of the composed reads (the graph-health route handler, the
    suggestions query) expect a tenant object rather than a bare id. This shim
    hands them the aggregator's ``tenant_id`` and nothing else — no request
    headers, no client, no other request state — which is exactly the isolation
    guarantee the Command Center makes: sub-service reads see the caller's
    tenant id and nothing more. ``require_permission`` is a no-op because the
    route boundary already enforced ``read`` before ``get_view`` was called.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def require_permission(self, permission: Any) -> None:  # noqa: D401
        return None


def _scoped_request(tenant_id: str) -> SimpleNamespace:
    """A request-shaped object exposing only ``state.tenant`` scoped to tenant_id."""
    return SimpleNamespace(state=SimpleNamespace(tenant=_ScopedTenant(tenant_id)))


class CommandCenterService:
    """Composes the read-only tenant Command Center view.

    OPERATOR BOUNDARY: operator-only services are never imported here. See the
    module docstring — every section is a tenant-scoped, tenant-safe read, and
    the aggregator passes only ``tenant_id`` (never the raw request) downstream.
    """

    async def get_view(
        self, tenant_id: str, request: Optional[Request] = None
    ) -> CommandCenterView:
        """Compose the nine sections for ``tenant_id``.

        ``request`` is accepted for signature parity with the route, but it is
        intentionally NOT forwarded downstream: every section read is scoped to
        ``tenant_id`` alone, so nothing but the tenant id crosses into a
        sub-service. The outcome ledger is read exactly once here and sliced by
        both ``value_strip`` and ``outcomes`` (read once, slice twice).
        """
        ledger, ledger_error = await self._load_ledger_once(tenant_id)

        results = await asyncio.gather(
            self._run_section("activation", lambda: self._build_activation(tenant_id)),
            self._run_section("value_strip", lambda: self._build_value_strip(ledger, ledger_error)),
            self._run_section("ops_feed", lambda: self._build_ops_feed(tenant_id)),
            self._run_section("graph_snapshot", lambda: self._build_graph_snapshot(tenant_id)),
            self._run_section("campaign_movement", lambda: self._build_campaign_movement(tenant_id)),
            self._run_section("data_confidence", lambda: self._build_data_confidence(tenant_id)),
            self._run_section("integration_health", lambda: self._build_integration_health(tenant_id)),
            self._run_section("outcomes", lambda: self._build_outcomes(ledger, ledger_error)),
            self._run_section("next_best_actions", lambda: self._build_next_best_actions(tenant_id)),
            return_exceptions=True,
        )

        sections: dict[str, SectionEnvelope] = {}
        for key, result in zip(_SECTION_KEYS, results):
            if isinstance(result, SectionEnvelope):
                sections[key] = result
            else:
                # _run_section catches builder exceptions, so this is only a
                # defensive fallback if gather itself surfaced one.
                logger.warning(f"command_center section crashed: key={key} error={result!r}")
                sections[key] = self._envelope(key, SectionState.error, None)

        return CommandCenterView(
            tenant_id=tenant_id,
            generated_at=utc_now().isoformat(),
            sections=sections,
        )

    # ── Envelope + section runner ────────────────────────────────────────────

    def _envelope(
        self, key: str, state: SectionState, data: Any
    ) -> SectionEnvelope:
        return SectionEnvelope(
            key=key,
            state=state,
            data=data,
            source=_SECTION_SOURCES.get(key, "unknown"),
            generated_at=utc_now().isoformat(),
        )

    async def _run_section(self, key: str, builder: Any) -> SectionEnvelope:
        """Run one builder, converting any failure into an honest envelope.

        A timeout → ``unavailable``; any other exception → ``error``. Neither
        path ever fabricates ``data`` — a failed read carries ``data=None``.
        """
        try:
            state, data = await builder()
            return self._envelope(key, state, data)
        except asyncio.TimeoutError:
            logger.warning(f"command_center section timed out: key={key}")
            return self._envelope(key, SectionState.unavailable, None)
        except Exception as exc:
            logger.warning(f"command_center section failed: key={key} error={exc}")
            return self._envelope(key, SectionState.error, None)

    # ── Shared outcome-ledger read (read once, slice twice) ──────────────────

    async def _load_ledger_once(
        self, tenant_id: str
    ) -> tuple[Optional[dict[str, Any]], Optional[Exception]]:
        """Fetch the tenant outcome ledger exactly once for value_strip+outcomes."""
        try:
            from services.intelligence.routes import _tenant_ledger

            return await _tenant_ledger(tenant_id), None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                f"command_center ledger read failed: tenant={tenant_id} error={exc}"
            )
            return None, exc

    @staticmethod
    def _ledger_summary_is_empty(summary: dict[str, Any]) -> bool:
        return (
            int(summary.get("recommendations_generated", 0)) == 0
            and int(summary.get("outcomes_observed", 0)) == 0
            and int(summary.get("decisions_recorded", 0)) == 0
            and int(summary.get("actions_logged", 0)) == 0
        )

    # ── Section builders (each returns (SectionState, verbatim payload)) ─────

    async def _build_activation(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from services.activation.service import ActivationService

        status = await ActivationService().get_status(tenant_id)
        # A fresh authenticated tenant already carries a real, DERIVED activation
        # state (account_verified) — genuine data, not a synthetic forward value.
        return SectionState.live, status

    async def _build_value_strip(
        self, ledger: Optional[dict[str, Any]], ledger_error: Optional[Exception]
    ) -> tuple[SectionState, Any]:
        if ledger_error is not None or ledger is None:
            return SectionState.unavailable, None
        summary = ledger.get("summary") or {}
        if self._ledger_summary_is_empty(summary):
            return SectionState.no_data, summary
        return SectionState.live, summary

    async def _build_ops_feed(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from services.intelligence.repositories import RecommendationRepository
        from services.reliability.tenant_impact import tenant_impact

        recommendations = await RecommendationRepository().list_for_tenant(
            tenant_id, limit=20
        )
        incidents = await tenant_impact.tenant_incidents_safe(tenant_id)
        status = await tenant_impact.tenant_safe_summary(tenant_id)
        payload = {
            "recommendations": recommendations,
            "incidents": incidents,
            "data_freshness": status,
        }
        active = incidents.get("active") or []
        resolved = incidents.get("resolved") or []
        if not recommendations and not active and not resolved:
            return SectionState.no_data, payload
        return SectionState.live, payload

    async def _build_graph_snapshot(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        # The graph read gets its own, shorter budget; on timeout _run_section
        # maps the TimeoutError to ``unavailable``.
        return await asyncio.wait_for(
            self._graph_snapshot_inner(tenant_id),
            timeout=_GRAPH_SECTION_TIMEOUT_SECONDS,
        )

    async def _graph_snapshot_inner(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from dependencies.providers import get_graph
        from services.operational_intelligence.routes import graph_health

        resp = await graph_health(_scoped_request(tenant_id), get_graph(), None)
        payload = resp.get("data", {}) if isinstance(resp, dict) else {}
        # graph_health returns status="no_data" when the tenant graph is empty.
        state = (
            SectionState.no_data
            if payload.get("status") == "no_data"
            else SectionState.live
        )
        return state, payload

    async def _build_campaign_movement(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from repositories.repos import CampaignRepository

        campaigns = await CampaignRepository().find_many(
            filters={"tenant_id": tenant_id}, limit=50, offset=0
        )
        if not campaigns:
            return SectionState.no_data, campaigns
        return SectionState.live, campaigns

    async def _build_data_confidence(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from services.data_quality.service import intelligence_quality_service

        overview = await intelligence_quality_service.overview(tenant_id)
        score = overview.get("score") or {}
        # compute_score stamps availability="insufficient_evidence" when no score
        # has ever been reported for the tenant.
        if (
            score.get("availability") == "insufficient_evidence"
            and int(overview.get("open_drift_event_count", 0)) == 0
        ):
            return SectionState.no_data, overview
        return SectionState.live, overview

    async def _build_integration_health(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from services.imports.service import list_imports
        from services.integrations.connectors.service import connector_service
        from services.sdk_health.service import get_sdk_health_service

        fleet = (await get_sdk_health_service().get_fleet_status(tenant_id)).to_dict()
        imports = await list_imports(tenant_id, limit=50, offset=0)
        # ``list_for_tenant`` returns the connector catalog MERGED with this
        # tenant's per-connector config/status — so a tenant that has wired
        # nothing still gets every descriptor with ``enabled=False`` and
        # ``sync_status="never_synced"``. Emptiness keys off actually-configured
        # connectors, but the verbatim catalog+status list stays in the payload.
        connectors = await connector_service.list_for_tenant(tenant_id)
        configured = [
            c
            for c in connectors
            if c.get("enabled")
            or c.get("secret_configured")
            or (c.get("sync_status") not in (None, "never_synced"))
        ]
        payload = {
            "sdk_fleet": fleet,
            "imports": imports,
            "connectors": connectors,
        }
        if (
            int(fleet.get("total_instances", 0)) == 0
            and not imports
            and not configured
        ):
            return SectionState.no_data, payload
        return SectionState.live, payload

    async def _build_outcomes(
        self, ledger: Optional[dict[str, Any]], ledger_error: Optional[Exception]
    ) -> tuple[SectionState, Any]:
        if ledger_error is not None or ledger is None:
            return SectionState.unavailable, None
        items = ledger.get("items") or []
        summary = ledger.get("summary") or {}
        if not items and int(summary.get("outcomes_observed", 0)) == 0:
            return SectionState.no_data, ledger
        return SectionState.live, ledger

    async def _build_next_best_actions(
        self, tenant_id: str
    ) -> tuple[SectionState, Any]:
        from services.suggestions.models import SuggestionQuery
        from services.suggestions.policy import redact_for_tenant
        from services.suggestions.routes import _get_service

        svc = _get_service()
        query = SuggestionQuery(
            tenant_id=tenant_id, include_closed=False, limit=20, offset=0
        )
        rows, _total = await svc.query_suggestions(query, _ScopedTenant(tenant_id))
        # redact_for_tenant strips operator-internal fields — the same tenant-safe
        # projection the /v1/aether/suggestions feed serves.
        safe = [redact_for_tenant(r) for r in rows]
        if not safe:
            return SectionState.no_data, safe
        return SectionState.live, safe
