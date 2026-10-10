"""Noesis Projection-Intelligence adapter — read-only 360 projection reads.

Answers ``projection_read``: run one tenant-scoped intelligence projection
(outcome360 / economic360 / infrastructure360 / any registered projection id)
through the S1 engine
(:class:`ProjectionRuntime <shared.projection_engine.runtime.ProjectionRuntime>`)
and answer with the projection digest + per-section state.

Same posture as every Noesis adapter:

* **tenant-gated** — the projection is only ever requested for the
  ``tenant_id`` the caller (the service dispatch, which already enforced the
  tenant / permission gate) provides; there is no cross-tenant path and the
  adapter derives no tenant of its own.
* **read-only** — it only runs a projection; the projection plane is read-only
  and this adapter has no write path.
* **fail-isolated + content-free** — an unknown projection id, an invalid
  subject kind, a missing provider, or any engine error degrades to a static,
  content-free reason code (``unknown_projection`` / ``invalid_subject_kind`` /
  ``provider_unavailable`` / ``projection_failed``); a provider diagnostic is
  NEVER echoed.
* **never fabricates** — a failed / empty projection answers honestly with
  ``sufficient=False`` instead of a synthesized result.

Each method returns the standard adapter envelope::

    {"answer": str, "results": list, "sources": list, "sufficient": bool}
"""

from __future__ import annotations

from typing import Any, Optional

from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_SUBJECT_KINDS,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.projection_intelligence")

# The read plane this adapter honestly reports under ``sources``.
_SOURCE = "intelligence_projection_runtime"

# Content-free degraded reason codes (a provider diagnostic is never surfaced).
_REASON_UNKNOWN_PROJECTION = "unknown_projection"
_REASON_INVALID_SUBJECT_KIND = "invalid_subject_kind"
_REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
_REASON_PROJECTION_FAILED = "projection_failed"

_PROJECTION_IDS = frozenset(INTELLIGENCE_PROJECTION_IDS)
_SUBJECT_KINDS = frozenset(PROJECTION_SUBJECT_KINDS)


def _degraded(reason: str) -> dict[str, Any]:
    return {
        "answer": "The requested projection could not be produced.",
        "results": [],
        "sources": [_SOURCE],
        "sufficient": False,
        "degraded": True,
        "reason": reason,
    }


class ProjectionIntelligenceNoesisAdapter:
    """Deterministic, read-only projection-intelligence lookups.

    ``runtime`` is injectable so tests can bind a fresh-registry executor; the
    default is the module-level engine runtime over the global
    ``projection_registry`` (wired at app mount).
    """

    def __init__(self, runtime: Optional[Any] = None) -> None:
        if runtime is not None:
            self._runtime = runtime
        else:
            from shared.projection_engine.runtime import runtime as default_runtime

            self._runtime = default_runtime

    async def projection_read(
        self,
        tenant_id: str,
        projection_id: str,
        subject_kind: str = "entity",
        subject_id: str = "current",
        lens_ids: Optional[list[str]] = None,
        temporal_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run one tenant-scoped projection and answer its digest + sections.

        The projection is requested for exactly ``tenant_id``; an unknown
        projection id, an invalid subject kind, a missing provider, or any
        engine error degrades to a content-free envelope — never an exception,
        never a provider diagnostic.
        """
        if projection_id not in _PROJECTION_IDS:
            return _degraded(_REASON_UNKNOWN_PROJECTION)
        if subject_kind not in _SUBJECT_KINDS:
            return _degraded(_REASON_INVALID_SUBJECT_KIND)

        from shared.intelligence_projections.contracts import (
            ProjectionRequest,
            ProjectionSubject,
        )

        request = ProjectionRequest(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=ProjectionSubject(kind=subject_kind, id=subject_id),
            lensIds=lens_ids,
            temporalMode=temporal_mode,
        )
        try:
            result = await self._runtime.execute_projection(
                request,
                lens_ids=lens_ids,
                temporal_mode=temporal_mode,
            )
        except Exception:  # noqa: BLE001 - fail-isolated projection seam
            logger.warning("Noesis projection_read failed for %s", projection_id)
            return _degraded(_REASON_PROJECTION_FAILED)

        # A result with no sections means the target could not be satisfied
        # (no registered provider / a fail-isolated provider).
        if not result.sections:
            return _degraded(_REASON_PROVIDER_UNAVAILABLE)

        degradation_state = (
            result.degradation.level if result.degradation is not None else None
        )
        sections = [{"id": s.id, "state": s.state} for s in result.sections]
        available = any(s.state == "available" for s in result.sections)
        answer = (
            f"Projection {result.projectionId} for {subject_kind} {subject_id}: "
            f"{len(sections)} section(s) rendered"
            + (f" (degradation {degradation_state})" if degradation_state else "")
            + "."
        )
        return {
            "answer": answer,
            "results": [
                {
                    "projectionId": result.projectionId,
                    "tenantId": result.tenantId,
                    "digest": result.digest,
                    "asOf": result.asOf,
                    "lensIds": result.lensIds,
                    "temporalMode": result.temporalMode,
                    "degradationState": degradation_state,
                    "sections": sections,
                    "suppressedSections": result.suppressedSections,
                }
            ],
            "sources": [_SOURCE],
            "sufficient": available,
            "degraded": False,
            "reason": None,
        }


__all__ = ["ProjectionIntelligenceNoesisAdapter"]
