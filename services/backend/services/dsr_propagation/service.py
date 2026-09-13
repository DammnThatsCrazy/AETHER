"""DSR propagation service + repository (prompt §3.11).

``DSRPropagationService`` owns the lifecycle of a propagation record:

* ``open_request`` — seed a pending step for every backend component.
* ``mark_step``    — advance one component's step with evidence, fail-closed.
* ``status``       — return per-component steps plus a rolled-up overall status.

The record is tenant-scoped: reads/writes accept an optional ``tenant_id`` and,
when supplied, a mismatch is treated as *not found* so one tenant can never see
or mutate another tenant's DSR (no existence leak).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger

from repositories.repos import BaseRepository  # noqa: F401 (documents provenance of _ScopedRepo)
from services.security.repositories import _ScopedRepo

from .models import (
    DSR_COMPONENTS,
    DSR_PROPAGATION_STATUSES,
    DSR_TERMINAL_STATUSES,
    DSR_TYPES,
    STEP_EVIDENCE_FIELDS,
    DSRPropagationStep,
    ReattributionEvidence,
    now_iso,
    overall_status,
)

logger = get_logger("aether.dsr_propagation.service")

# Completion must cite the component's own receipt — one of these fields,
# explicitly supplied by the caller (zero counts allowed, absence is not).
_COMPLETION_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "records_impacted", "artifacts_impacted", "audit_event_id", "policy_decision_id",
})

# Program 3 M2 — re-attribution invalidation corrects attribution *records*
# (attribution_runs), so its evidence is recorded on the ``attribution_records``
# DSR component: the same component the consent-erasure job already marks with
# the measurement store's tombstone receipt (services/consent/erasure_jobs.py).
REATTRIBUTION_COMPONENT = "attribution_records"

# The ReattributionResult summary fields ``record_reattribution`` reads. Kept in
# sync with services/measurement/reattribution.py's ``ReattributionResult`` (M3)
# WITHOUT importing it — the DSR layer stays decoupled from the measurement
# package, and any trigger that produces this shape (privacy erasure OR fraud
# takedown) records identically.
_REATTRIBUTION_SUMMARY_FIELDS: tuple[str, ...] = (
    "reason",
    "conversions_scanned",
    "conversions_reattributed",
    "runs_deactivated",
    "runs_created",
    "touchpoints_scanned",
    "scope_limit",
    "truncated",
    "partial_failure",
    "errors",
    "errors_count",
)


class DSRPropagationRepository(_ScopedRepo):
    """Tenant-scoped store of DSR propagation records (one row per request).

    Reuses the JSONB-backed :class:`_ScopedRepo` (production PostgreSQL, local
    in-memory) so the layer works in both backends with no extra wiring.
    """

    def __init__(self) -> None:
        super().__init__("dsr_propagation_records")


class DSRPropagationService:
    def __init__(self, repo: Optional[DSRPropagationRepository] = None) -> None:
        self._repo = repo or DSRPropagationRepository()

    # ── open ──────────────────────────────────────────────────────────────────

    async def open_request(
        self, tenant_id: str, subject_ref: str, dsr_type: str,
    ) -> str:
        """Create a propagation record with one ``pending`` step per component.

        Returns the opaque ``request_id``. Fail-closed on missing tenant/subject
        or an unknown ``dsr_type``.
        """
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not subject_ref:
            raise BadRequestError("subject_ref is required")
        if dsr_type not in DSR_TYPES:
            raise BadRequestError(
                f"Invalid dsr_type {dsr_type!r}. Allowed: {list(DSR_TYPES)}"
            )

        request_id = f"dsrp_{uuid.uuid4().hex[:16]}"
        steps = [
            DSRPropagationStep(component=component).model_dump()
            for component in DSR_COMPONENTS
        ]
        record = {
            "request_id": request_id,
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "dsr_type": dsr_type,
            "steps": steps,
            "opened_at": now_iso(),
        }
        await self._repo.insert(request_id, record)
        logger.info(
            "DSR propagation opened request_id=%s tenant=%s type=%s components=%d",
            request_id, tenant_id, dsr_type, len(steps),
        )
        return request_id

    # ── internal load with tenant scoping ──────────────────────────────────────

    async def _load(self, request_id: str, tenant_id: Optional[str]) -> dict:
        record = await self._repo.find_by_id(request_id)
        # Fail-closed tenant isolation: a cross-tenant read/write is indistinguishable
        # from a missing record so existence never leaks across tenants.
        if record is None or (tenant_id is not None and record.get("tenant_id") != tenant_id):
            raise NotFoundError(f"DSR propagation record {request_id!r} not found")
        return record

    # ── mark ──────────────────────────────────────────────────────────────────

    async def mark_step(
        self,
        request_id: str,
        component: str,
        status: str,
        tenant_id: Optional[str] = None,
        **evidence: Any,
    ) -> dict:
        """Advance a single component's step.

        ``**evidence`` may carry any of ``STEP_EVIDENCE_FIELDS`` (blocked_reason,
        policy_decision_id, audit_event_id, records_impacted, artifacts_impacted,
        requires_retrain, requires_recompute, and explicit started_at/completed_at).
        Unknown evidence keys and unknown statuses/components are rejected.
        ``started_at``/``completed_at`` are auto-stamped when not supplied.

        Passing ``tenant_id`` enforces tenant isolation (mismatch -> not found).
        Returns the updated step dict.
        """
        if status not in DSR_PROPAGATION_STATUSES:
            raise BadRequestError(
                f"Invalid status {status!r}. Allowed: {list(DSR_PROPAGATION_STATUSES)}"
            )
        if component not in DSR_COMPONENTS:
            raise BadRequestError(
                f"Invalid component {component!r}. Allowed: {list(DSR_COMPONENTS)}"
            )
        unknown = set(evidence) - STEP_EVIDENCE_FIELDS
        if unknown:
            raise BadRequestError(
                f"Unknown evidence field(s): {sorted(unknown)}. "
                f"Allowed: {sorted(STEP_EVIDENCE_FIELDS)}"
            )
        # A blocked step must record *why* — a blocking record with no reason is
        # not actionable for compliance review.
        if status == "blocked" and not (evidence.get("blocked_reason") or "").strip():
            raise BadRequestError("blocked status requires a non-empty blocked_reason")
        # A completed step must carry the component's own receipt — a bare
        # "completed" is a caller-asserted claim nobody can audit. Zero counts
        # are fine (records_impacted=0 is a real receipt for an empty store);
        # supplying *no* evidence at all is not.
        if status == "completed" and not (_COMPLETION_EVIDENCE_FIELDS & set(evidence)):
            raise BadRequestError(
                "completed status requires component evidence: supply at least "
                f"one of {sorted(_COMPLETION_EVIDENCE_FIELDS)}"
            )

        record = await self._load(request_id, tenant_id)
        steps: list[dict] = record.get("steps", [])
        target = next((s for s in steps if s.get("component") == component), None)
        if target is None:
            # Record predates this component, or was hand-built — re-seed defensively.
            target = DSRPropagationStep(component=component).model_dump()  # type: ignore[arg-type]
            steps.append(target)

        target["status"] = status
        for key, value in evidence.items():
            target[key] = value

        now = now_iso()
        # Auto-stamp lifecycle timestamps unless the caller pinned them.
        if status != "pending" and not target.get("started_at"):
            target["started_at"] = now
        if status in DSR_TERMINAL_STATUSES and not evidence.get("completed_at"):
            target["completed_at"] = now

        # Re-validate the mutated step so a bad evidence value (e.g. negative
        # records_impacted) is rejected rather than persisted.
        validated = DSRPropagationStep(**target).model_dump()  # type: ignore[arg-type]
        for i, s in enumerate(steps):
            if s.get("component") == component:
                steps[i] = validated
                break

        record["steps"] = steps
        await self._repo.update(request_id, record)
        logger.info(
            "DSR propagation mark request_id=%s component=%s -> %s",
            request_id, component, status,
        )
        return validated

    # ── re-attribution evidence (Program 3 M2) ───────────────────────────────────

    async def record_reattribution(
        self,
        request_id: str,
        result: Any,
        tenant_id: Optional[str] = None,
        component: str = REATTRIBUTION_COMPONENT,
    ) -> dict:
        """Attach re-attribution evidence to a component step (Program 3 M2).

        ``result`` is a re-attribution summary — a
        ``services.measurement.reattribution.ReattributionResult`` (M3), its
        ``to_dict()`` output, or any mapping/object exposing the same fields
        (``reason``, ``conversions_reattributed``, ``runs_deactivated``,
        ``runs_created``, ``truncated`` …). It is coerced into a typed
        :class:`ReattributionEvidence` and attached to ``component``'s step
        (default ``attribution_records``) as first-class DSR propagation
        evidence, so a DSR/compliance audit shows the subject's attribution was
        corrected as part of the request. The same call serves BOTH triggers —
        privacy erasure (``reason="privacy_erasure"``) and fraud takedown
        (``reason="fraud_takedown"``) — since it keys only on the summary shape.

        Purely *additive*: it records the evidence WITHOUT changing the step's
        status or its own erasure receipt (tombstone counts / audit pointer), so
        it composes with the erasure job's ``mark_step`` marking regardless of
        the order the two run in. Tenant-scoped and fail-closed (a cross-tenant
        write is indistinguishable from a missing record); an unknown
        ``component`` or a summary with no ``reason`` is rejected. Returns the
        updated step dict.
        """
        if component not in DSR_COMPONENTS:
            raise BadRequestError(
                f"Invalid component {component!r}. Allowed: {list(DSR_COMPONENTS)}"
            )
        evidence = _coerce_reattribution_evidence(result)

        record = await self._load(request_id, tenant_id)
        steps: list[dict] = record.get("steps", [])
        target = next((s for s in steps if s.get("component") == component), None)
        if target is None:
            # Record predates this component, or was hand-built — re-seed defensively
            # (mirrors mark_step).
            target = DSRPropagationStep(component=component).model_dump()  # type: ignore[arg-type]
            steps.append(target)

        # Attach ONLY the re-attribution evidence; status/started_at/completed_at
        # and the store's own receipt are left exactly as the component's handler
        # set them.
        target["reattribution"] = evidence.model_dump()

        # Re-validate the mutated step so a bad evidence value is rejected rather
        # than persisted (same guard mark_step applies).
        validated = DSRPropagationStep(**target).model_dump()  # type: ignore[arg-type]
        for i, s in enumerate(steps):
            if s.get("component") == component:
                steps[i] = validated
                break

        record["steps"] = steps
        await self._repo.update(request_id, record)
        logger.info(
            "DSR propagation reattribution recorded request_id=%s component=%s "
            "reason=%s conversions_reattributed=%d runs_deactivated=%d "
            "runs_created=%d truncated=%s partial_failure=%s",
            request_id, component, evidence.reason,
            evidence.conversions_reattributed, evidence.runs_deactivated,
            evidence.runs_created, evidence.truncated, evidence.partial_failure,
        )
        return validated

    # ── status ──────────────────────────────────────────────────────────────────

    async def status(
        self, request_id: str, tenant_id: Optional[str] = None,
    ) -> dict:
        """Return ``{request_id, dsr_type, subject_ref, components:[...], overall}``.

        ``overall`` is the fail-closed roll-up (see :func:`models.overall_status`):
        ``blocked`` if any step is blocked, ``running`` if any is running,
        ``completed`` only when every step is completed/skipped_legal_hold.
        """
        record = await self._load(request_id, tenant_id)
        steps: list[dict] = record.get("steps", [])
        return {
            "request_id": record.get("request_id", request_id),
            "tenant_id": record.get("tenant_id"),
            "dsr_type": record.get("dsr_type"),
            "subject_ref": record.get("subject_ref"),
            "components": steps,
            "overall": overall_status(steps),
        }


def _coerce_reattribution_evidence(result: Any) -> ReattributionEvidence:
    """Normalize a re-attribution summary to a typed :class:`ReattributionEvidence`.

    Accepts, WITHOUT importing the measurement package (which would couple the
    DSR-evidence layer to it):

    * a ``ReattributionResult`` (M3) — anything exposing a callable ``to_dict()``;
    * that ``to_dict()`` output, or any other mapping carrying the same keys;
    * any object carrying the summary fields as attributes.

    ``errors`` (a list on ``ReattributionResult``) is summarized to
    ``errors_count`` — the evidence records *that* the invalidation was partial,
    never the raw per-conversion error strings (which can name conversion ids).
    ``partial_failure`` is taken from the summary when present, else derived from
    a non-zero ``errors_count`` (mirroring ``ReattributionResult.partial_failure``).
    Fail-closed: a missing summary, or one with no non-empty ``reason``, is
    rejected.
    """
    if result is None:
        raise BadRequestError("reattribution result is required")

    # ReattributionResult.to_dict() gives the canonical shape; a plain dict has
    # no ``to_dict`` attribute so it falls through to the Mapping branch.
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
    elif isinstance(result, Mapping):
        data = dict(result)
    else:
        data = {
            field: getattr(result, field)
            for field in _REATTRIBUTION_SUMMARY_FIELDS
            if hasattr(result, field)
        }

    if not isinstance(data, Mapping):
        raise BadRequestError("reattribution result did not resolve to a mapping")

    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("reattribution result requires a non-empty reason")

    errors = data.get("errors")
    if isinstance(errors, (list, tuple, set)):
        errors_count = len(errors)
    else:
        errors_count = int(data.get("errors_count") or 0)

    partial = data.get("partial_failure")
    if partial is None:
        partial = errors_count > 0

    return ReattributionEvidence(
        reason=reason,
        conversions_scanned=int(data.get("conversions_scanned") or 0),
        conversions_reattributed=int(data.get("conversions_reattributed") or 0),
        runs_deactivated=int(data.get("runs_deactivated") or 0),
        runs_created=int(data.get("runs_created") or 0),
        touchpoints_scanned=int(data.get("touchpoints_scanned") or 0),
        scope_limit=int(data.get("scope_limit") or 0),
        truncated=bool(data.get("truncated") or False),
        partial_failure=bool(partial),
        errors_count=errors_count,
    )


dsr_propagation_service = DSRPropagationService()
