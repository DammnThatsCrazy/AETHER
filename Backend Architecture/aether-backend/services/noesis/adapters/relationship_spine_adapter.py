"""Noesis Relationship / Spine Intelligence adapter — read-only relationship reads.

Answers four read-only relationship / spine questions over the relationship
intelligence read plane:

* ``relationship_explain``        — basis / evidence / motifs / incentive
  context explanation for a relationship or entity pair.
* ``influence_path``              — measured influence decomposition along the
  best evidence-backed path (via the influence-propagation substrate).
* ``engagement_fidelity``         — the latest persisted relationship-fidelity
  vector engagement dims (interaction_frequency, interaction_depth,
  reciprocity, persistence).
* ``incentive_context_explain``   — persisted incentive-context assessment for
  the subject when present.

Same posture as every Noesis adapter:

* **read-only** — this adapter only reads; it has no write path and never
  mutates relationship state.
* **tenant-gated** — reads are only ever requested for the ``tenant_id`` the
  service dispatch (which already enforced the tenant / permission gate)
  provides; there is no cross-tenant path here.
* **flag-gate lives upstream** — the service layer owns the
  ``AETHER_RELATIONSHIP_SPINE_NOESIS_ENABLED`` read and answers a
  ``service_disabled`` degradation while it is OFF. This adapter never reads
  the flag; it only ever runs on an enabled surface.
* **consent hook (D-05)** — the Social360 surface requires historical-consent
  evaluation. ``consent_provider`` is injectable; its default lazily imports
  ``services.relationship_intelligence.consent`` inside the method and is
  fail-closed (deny) when that module cannot be resolved. When consent is not
  established the adapter returns the honest ``consent_required`` degradation.
* **read runtime is injectable** — ``read_runtime`` defaults to a lazy import
  of ``services.relationship_intelligence.reads`` (built concurrently by the
  relationship-intelligence lane); when the module cannot be resolved the
  adapter degrades with ``provider_unavailable`` rather than raising.
* **fail-isolated + content-free** — degraded answers are static,
  content-free reason codes (``provider_unavailable`` / ``consent_required`` /
  ``no_data``); a read diagnostic is never echoed.
* **never fabricates** — an empty / unmeasured read answers honestly with
  ``sufficient=False``; measured facts are reported with ``None`` preserved for
  unknowns and a missing value is never reported as zero.

Each method returns the standard adapter envelope::

    {"answer": str, "results": list, "sources": list, "sufficient": bool,
     "degraded": bool, "reason": str | None}

Read-runtime contract (implemented by ``services.relationship_intelligence.reads``
and mirrored by the injected fakes in the adapter unit tests):

    async def relationship_explain(tenant_id: str, target: str | None,
                                   limit: int) -> dict | None
    async def influence_path(tenant_id: str, target: str | None,
                             limit: int) -> dict | None
    async def engagement_fidelity(tenant_id: str, target: str | None,
                                  limit: int) -> dict | None
    async def incentive_context_explain(tenant_id: str, target: str | None,
                                        limit: int) -> dict | None

Each returns ``None`` when no persisted evidence exists for the subject, or a
dict shaped as::

    {"subject": str, "summary": str, "as_of": str | None, "rows": [dict, ...]}

``summary`` is the read plane's measured natural-language digest — the adapter
never invents prose or numbers; ``rows`` carry the underlying measured facts
(with ``None`` preserved). A falsy / empty ``summary`` with no ``rows`` is
treated as no evidence.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.relationship_spine")

# The read plane this adapter honestly reports under ``sources`` per intent.
_SOURCE_SPINE = "relationship_spine"
_SOURCE_FIDELITY = "relationship_fidelity"
_SOURCE_INCENTIVE = "incentive_context"
_SOURCE_INFLUENCE = "influence_propagation"
_SOURCE_COMPUTATION = "computation_substrate"

# Content-free degraded reason codes (a read diagnostic is never surfaced).
_REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
_REASON_CONSENT_REQUIRED = "consent_required"
_REASON_NO_DATA = "no_data"

# Static, content-free degraded answers keyed by reason code.
_DEGRADED_ANSWERS: dict[str, str] = {
    _REASON_PROVIDER_UNAVAILABLE: (
        "Relationship intelligence reads are not available in this deployment."
    ),
    _REASON_CONSENT_REQUIRED: (
        "Historical-consent evaluation is required before this relationship "
        "intelligence can be surfaced."
    ),
    _REASON_NO_DATA: (
        "The relationship intelligence surface has no persisted evidence for "
        "that subject yet."
    ),
}


def _degraded(reason: str) -> dict[str, Any]:
    return {
        "answer": _DEGRADED_ANSWERS.get(
            reason, "The requested relationship intelligence could not be produced."
        ),
        "results": [],
        "sources": [_SOURCE_SPINE],
        "sufficient": False,
        "degraded": True,
        "reason": reason,
    }


# Type aliases for the injectable seams (kept structural so tests can bind
# lightweight fakes without importing the in-flight relationship-intelligence
# package).
ReadRuntime = Any
ConsentProvider = Callable[[str, Optional[str]], Any]


async def _maybe_await(value: Any) -> Any:
    """Await the value when it is awaitable, otherwise return it unchanged."""
    if isinstance(value, Awaitable) or asyncio.iscoroutine(value):
        return await value
    return value


class RelationshipSpineNoesisAdapter:
    """Deterministic, read-only relationship / spine intelligence lookups.

    ``read_runtime`` and ``consent_provider`` are injectable so tests bind
    fakes without importing the concurrent relationship-intelligence package;
    defaults lazily import that package inside each method and degrade
    fail-closed when it is unavailable.
    """

    def __init__(
        self,
        read_runtime: Optional[ReadRuntime] = None,
        consent_provider: Optional[ConsentProvider] = None,
    ) -> None:
        self._read_runtime = read_runtime
        self._consent_provider = consent_provider

    # ── Injectable-seam resolution ─────────────────────────────────────────

    def _resolve_read_runtime(self) -> Optional[ReadRuntime]:
        """Return the bound read runtime, lazily resolving the default.

        The default is the in-flight ``services.relationship_intelligence.reads``
        module; when it cannot be imported (not yet built / not deployed) the
        adapter degrades to ``provider_unavailable`` instead of raising.
        """
        if self._read_runtime is not None:
            return self._read_runtime
        try:
            from services.relationship_intelligence import reads as default_reads
        except Exception as exc:  # noqa: BLE001 - fail-isolated read seam
            logger.warning(
                "Noesis relationship read runtime unavailable: %s",
                type(exc).__name__,
            )
            return None
        self._read_runtime = default_reads
        return self._read_runtime

    def _resolve_consent_provider(self) -> Optional[ConsentProvider]:
        """Return the bound consent provider, lazily resolving the default.

        The default lazily imports ``services.relationship_intelligence.consent``
        and prefers that module's ``require_social_read_consent`` gate (which is
        itself a NO-OP while the master social360 surface is OFF and raises a
        content-free ``ConsentRequired`` when ON without established consent);
        ``has_consent`` is accepted as a secondary shape. Consent is fail-closed:
        when the module cannot be resolved the provider resolves to ``None``,
        which callers treat as deny (the ``consent_required`` degradation). The
        social360 surface only reaches this adapter when its noesis flag is ON
        (the service answers ``service_disabled`` otherwise), so a deny here is
        the honest path.
        """
        if self._consent_provider is not None:
            return self._consent_provider
        try:
            from services.relationship_intelligence import consent as default_consent
        except Exception as exc:  # noqa: BLE001 - fail-closed consent seam
            logger.warning(
                "Noesis relationship consent module unavailable: %s",
                type(exc).__name__,
            )
            return None

        if callable(getattr(default_consent, "require_social_read_consent", None)):
            require_gate = default_consent.require_social_read_consent

            async def _require_gate(tenant_id: str, subject: Optional[str]) -> bool:
                try:
                    await _maybe_await(
                        require_gate(tenant_id, subject_entity_id=subject or "")
                    )
                except Exception:  # noqa: BLE001 - ConsentRequired or any failure denies
                    return False
                return True

            self._consent_provider = _require_gate
            return self._consent_provider

        if callable(getattr(default_consent, "has_consent", None)):
            self._consent_provider = default_consent.has_consent
            return self._consent_provider

        logger.warning("Noesis relationship consent module missing a usable gate")
        return None

    async def _consent_allowed(self, tenant_id: str, target: Optional[str]) -> bool:
        provider = self._resolve_consent_provider()
        if provider is None:
            return False
        try:
            outcome = provider(tenant_id, target)
            outcome = await _maybe_await(outcome)
        except Exception as exc:  # noqa: BLE001 - fail-closed consent seam
            logger.warning("Noesis relationship consent check failed: %s", type(exc).__name__)
            return False
        return bool(outcome)

    # ── Per-intent envelope methods ────────────────────────────────────────

    async def relationship_explain(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Explain the observed basis / evidence / motifs / incentive context
        for a relationship or entity pair. Returns measured facts only."""
        return await self._read(
            read_name="relationship_explain",
            sources=[_SOURCE_SPINE, _SOURCE_FIDELITY, _SOURCE_INCENTIVE],
            tenant_id=tenant_id,
            target=target,
            limit=limit,
            label="relationship explanation",
        )

    async def influence_path(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return the measured influence decomposition along the best
        evidence-backed path between subjects."""
        return await self._read(
            read_name="influence_path",
            sources=[_SOURCE_SPINE, _SOURCE_INFLUENCE, _SOURCE_COMPUTATION],
            tenant_id=tenant_id,
            target=target,
            limit=limit,
            label="influence path",
        )

    async def engagement_fidelity(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Report the subject / relationship's latest persisted fidelity-vector
        engagement dims (interaction_frequency, interaction_depth, reciprocity,
        persistence). Missing dims stay null."""
        return await self._read(
            read_name="engagement_fidelity",
            sources=[_SOURCE_FIDELITY, _SOURCE_SPINE],
            tenant_id=tenant_id,
            target=target,
            limit=limit,
            label="engagement fidelity",
        )

    async def incentive_context_explain(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return the persisted incentive-context assessment for the subject
        when present. An incentive is never asserted where none is persisted."""
        return await self._read(
            read_name="incentive_context_explain",
            sources=[_SOURCE_INCENTIVE, _SOURCE_SPINE],
            tenant_id=tenant_id,
            target=target,
            limit=limit,
            label="incentive context",
        )

    # ── Shared read plumbing ───────────────────────────────────────────────

    async def _read(
        self,
        *,
        read_name: str,
        sources: list[str],
        tenant_id: str,
        target: Optional[str],
        limit: int,
        label: str,
    ) -> dict[str, Any]:
        """Resolve consent + the read runtime, run one read, and wrap it in the
        standard envelope. Degrades honestly and content-free on every failure
        path — never raises, never fabricates."""
        if not await self._consent_allowed(tenant_id, target):
            return _degraded(_REASON_CONSENT_REQUIRED)

        runtime = self._resolve_read_runtime()
        if runtime is None:
            return _degraded(_REASON_PROVIDER_UNAVAILABLE)

        read_fn = getattr(runtime, read_name, None)
        if not callable(read_fn):
            logger.warning("Noesis relationship read '%s' not exposed by runtime", read_name)
            return _degraded(_REASON_PROVIDER_UNAVAILABLE)

        try:
            result = await _maybe_await(
                read_fn(tenant_id=tenant_id, target=target, limit=limit)
            )
        except Exception as exc:  # noqa: BLE001 - fail-isolated read seam
            logger.warning(
                "Noesis relationship read '%s' failed: %s", read_name, type(exc).__name__
            )
            return _degraded(_REASON_PROVIDER_UNAVAILABLE)

        if result is None:
            return _degraded(_REASON_NO_DATA)
        if not isinstance(result, dict):
            # A read returning an unexpected shape is treated as unavailable
            # rather than being force-fit into an answer.
            return _degraded(_REASON_PROVIDER_UNAVAILABLE)

        summary = (result.get("summary") or "").strip()
        raw_rows = result.get("rows")
        if isinstance(raw_rows, list):
            results = list(raw_rows)
        elif raw_rows is None:
            results = []
        else:
            results = [raw_rows]

        if not results and not summary:
            return _degraded(_REASON_NO_DATA)

        if summary:
            answer = summary
        else:
            subject = target or "this subject"
            answer = (
                f"Relationship intelligence found {len(results)} persisted "
                f"{label} row(s) for {subject}; see results for measured detail."
            )
        return {
            "answer": answer,
            "results": results,
            "sources": sources,
            "sufficient": True,
            "degraded": False,
            "reason": None,
        }


__all__ = ["RelationshipSpineNoesisAdapter"]
