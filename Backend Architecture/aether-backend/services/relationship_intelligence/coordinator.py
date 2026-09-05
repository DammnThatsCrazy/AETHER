"""Relationship-spine runtime coordinator (Social360 + Relationship Fidelity).

This module is the FIRST runtime caller of the M7 relationship-fidelity engine
(``services.relationship_fidelity.engine``) — the module the D-04 independence
seam (``services.relationship_promotion.evidence_independence``) was named to
feed. It orchestrates the spine WRITE path for one relationship:

1. **Incentive enrichment** (optional): when incentive-context is enabled and
   enrichment is requested, resolve ONE ``IncentiveContext`` per relationship
   (never per observation) and stamp the observations ``incentive_assessed`` /
   ``incentive_context`` honestly. When enrichment is disabled/unavailable the
   observations are left untouched — ``incentive_assessed`` stays ``False`` and
   activity is NEVER treated as organic. A resolution failure never aborts the
   run; it is recorded as a limitation.
2. **Independence** (optional, default on): obtain the independent-evidence
   account via ``load_m6_independence_resolver()`` (the D-04 seam) or accept an
   explicit ``independent_account``. Never fabricated: when the resolver is
   absent independence stays UNKNOWN and independence-gated dimensions stay null.
3. **Compute**: ``RelationshipFidelityEngine.compute_fidelity(...)``.
4. **Persist gate**: ``fidelity_mode()`` (``AETHER_RELATIONSHIP_FIDELITY_MODE``,
   default ``off``). The vector is persisted (shadow/warn/enforce) via
   ``persist_fidelity``; in ``off`` (or when ``persist=False``) nothing is
   persisted and the result records ``persisted=False``. shadow/warn runs are
   observation/compare-only.

The pure, deterministic :func:`materialize_observations` helper builds M7
:class:`Observation` rows from raw social-fact dicts (records that cannot be
honestly mapped are skipped — never fabricated).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from services.incentive_context.service import IncentiveContextService
from services.relationship_fidelity import engine as _fidelity_engine
from shared.logger.logger import get_logger, metrics
from shared.relationship_fidelity.evidence import (
    IndependentEvidenceAccount,
    Observation,
    load_m6_independence_resolver,
)

logger = get_logger("aether.relationship_intelligence.coordinator")

# Fidelity modes that permit persistence through the Computation Substrate.
PERSIST_MODES: frozenset[str] = frozenset({"shadow", "warn", "enforce"})

# Incentive-context statuses that honestly assert an incentive is present.
# ``none_observed`` is an assessed absence; ``unknown`` / ``not_applicable`` are
# not incentive-presence (never treated as organic either).
INCENTIVE_PRESENT_STATUSES: frozenset[str] = frozenset(
    {"verified", "declared", "observed", "suspected"}
)

_METER_LABELS_MODE_TENANT = ("mode", "tenant")


def relationship_ref_for(source_entity_id: str, target_entity_id: str) -> str:
    """Canonical relationship-pair reference for one directed entity pair.

    Shared by the coordinator and the read helpers/routes so a persisted run for
    a pair is discoverable by the same reference that coordinates it.
    """
    return f"{source_entity_id}::{target_entity_id}"


# --------------------------------------------------------------------------- #
# Observation materialization (pure / deterministic)
# --------------------------------------------------------------------------- #


def _record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _coerce_float01(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= parsed <= 1.0):
        return None
    return parsed


def _coerce_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(t for t in (part.strip() for part in value.split(",")) if t)
    try:
        return tuple(str(t) for t in value)
    except (TypeError, ValueError):
        return ()


def materialize_observations(
    records: Sequence[dict[str, Any]],
    *,
    default_direction: Optional[str] = None,
) -> list[Observation]:
    """Build M7 fidelity observations from raw social-fact dicts.

    Deterministic and honest: a record that cannot supply an ``observation_id``,
    a canonical ``predicate``, a usable ``observed_at`` and a valid ``direction``
    (outgoing|incoming|undirected, or ``default_direction``) is SKIPPED — an
    observation is never fabricated from partial data. ``source_key`` is
    ``""`` when the record carries no source identity, which the engine and the
    D-04 seam treat as "not attributable" (independence UNKNOWN — never a 0).

    Accepted keys (aliases tolerant, first present wins):
    ``id``/``observation_id``/``event_id``, ``predicate``/``predicate_ref``,
    ``direction``, ``source_key``/``source_id``/``provider``/``source``,
    ``observed_at``/``at``/``occurred_at``/``timestamp``/``time``,
    ``intensity``, ``source_reliability``, ``correlation_family``,
    ``context_tags``, ``incentive_context``, ``incentive_assessed``.
    """
    observations: list[Observation] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        observation_id = _record_value(record, "observation_id", "id", "event_id")
        predicate = _record_value(record, "predicate", "predicate_ref")
        observed_at = _record_value(
            record, "observed_at", "at", "occurred_at", "timestamp", "time"
        )
        direction = _record_value(record, "direction")
        if direction is None:
            direction = default_direction
        if not observation_id or not predicate or observed_at is None or not direction:
            continue
        direction = str(direction).strip().lower()
        if direction not in ("outgoing", "incoming", "undirected"):
            continue
        source_key = str(
            _record_value(record, "source_key", "source_id", "provider", "source") or ""
        ).strip()
        observations.append(
            Observation(
                observation_id=str(observation_id),
                predicate=str(predicate),
                direction=direction,
                source_key=source_key,
                observed_at=str(observed_at),
                intensity=_coerce_float01(_record_value(record, "intensity")),
                source_reliability=_coerce_float01(
                    _record_value(record, "source_reliability")
                ),
                incentive_context=bool(
                    _record_value(record, "incentive_context") or False
                ),
                incentive_assessed=bool(
                    _record_value(record, "incentive_assessed") or False
                ),
                correlation_family=_record_value(record, "correlation_family"),
                context_tags=_coerce_tags(_record_value(record, "context_tags")),
            )
        )
    return observations


# --------------------------------------------------------------------------- #
# Incentive enrichment helpers
# --------------------------------------------------------------------------- #


def _coerce_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _ctx_indicates_incentive(ctx: Any) -> bool:
    """True when a resolved context honestly asserts an incentive is present."""
    status = getattr(ctx, "status", None)
    if status is not None and str(status) in INCENTIVE_PRESENT_STATUSES:
        return True
    return bool(getattr(ctx, "direct_incentive", None))


def _ctx_exposure(ctx: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    start = _coerce_utc(getattr(ctx, "exposure_started_at", None))
    end = _coerce_utc(getattr(ctx, "exposure_ended_at", None))
    return start, end


def _observation_within(observed_at: str, start: Any, end: Any) -> bool:
    stamp = _coerce_utc(observed_at)
    if stamp is None:
        # Timestamp cannot be placed relative to the window => not confirmed as
        # incentive-exposed (assessed stays True, exposure flag stays False).
        return False
    if start is not None and stamp < start:
        return False
    if end is not None and stamp >= end:
        return False
    return True


def _apply_incentive_context(
    observations: Sequence[Observation], ctx: Any
) -> tuple[list[Observation], bool]:
    """Stamp one relationship-level incentive context onto the observations.

    Every observation the resolved context covers is ``incentive_assessed=True``
    (an assessment was made). ``incentive_context`` is ``True`` only when the
    context indicates an incentive AND (when an exposure window is declared) the
    observation falls inside that window. Returns the new observations and
    whether any observation was incentive-assessed.
    """
    indicates = _ctx_indicates_incentive(ctx)
    start, end = _ctx_exposure(ctx)
    has_window = start is not None or end is not None
    out: list[Observation] = []
    assessed = False
    for obs in observations:
        if not has_window or _observation_within(obs.observed_at, start, end):
            exposure = indicates
        else:
            exposure = False
        out.append(
            replace(
                obs,
                incentive_assessed=True,
                incentive_context=bool(exposure),
            )
        )
        assessed = True
    return out, assessed


def _relationship_evidence(
    relationship_ref: str, source_entity_id: str, target_entity_id: str
) -> dict[str, Any]:
    """Relationship-level evidence envelope handed to the incentive resolver."""
    return {
        "relationship_ref": relationship_ref,
        "source_entity_ref": source_entity_id,
        "target_entity_ref": target_entity_id,
    }


# --------------------------------------------------------------------------- #
# Run result + coordinator
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SpineRunResult:
    """Honest outcome of one coordinator run over a relationship pair."""

    relationship_ref: str
    tenant_id: str
    mode: str
    independence_known: bool
    vector: Optional[Any]  # FidelityVector or None (None when no evidence)
    persisted: bool
    run_id: Optional[str]
    incentive_assessed: bool
    limitations: list[str] = field(default_factory=list)


class RelationshipSpineCoordinator:
    """First runtime caller of the relationship-fidelity engine.

    ``engine`` / ``incentive_service`` are injectable for tests. A default
    coordinator constructs the real engine and a flag-gated incentive service.
    """

    def __init__(
        self,
        *,
        engine: Optional[Any] = None,
        incentive_service: Optional[IncentiveContextService] = None,
    ) -> None:
        self._engine = engine or _fidelity_engine.RelationshipFidelityEngine()
        self._incentive_service = incentive_service or IncentiveContextService()

    # ------------------------------------------------------------------ #
    # Main entrypoint
    # ------------------------------------------------------------------ #
    async def run_for_relationship(
        self,
        *,
        tenant_id: str,
        relationship_ref: str,
        source_entity_id: str,
        target_entity_id: str,
        observations: Sequence[Observation],
        measured: Optional[dict[str, float]] = None,
        window_seconds: Optional[float] = None,
        resolve_independence: bool = True,
        enrich_incentives: bool = True,
        persist: Optional[bool] = None,
        independent_account: Optional[IndependentEvidenceAccount] = None,
    ) -> SpineRunResult:
        """Compute + (optionally persist) the fidelity vector for one pair.

        Semantics documented on the module docstring. ``persist=None`` honors
        ``fidelity_mode()``; ``persist=False`` suppresses persistence;
        ``persist=True`` is an explicit override (recorded when it contradicts an
        ``off`` mode). Never fabricates an independent account or a dimension.
        """
        mode = _fidelity_engine.fidelity_mode()
        limitations: list[str] = []
        observations = [
            o for o in (observations or ()) if isinstance(o, Observation)
        ]

        # ── Incentive enrichment (once per relationship) ──────────────────
        incentive_assessed = False
        if enrich_incentives and observations:
            if not self._incentive_service.enabled:
                limitations.append(
                    "Incentive-context enrichment disabled; observations remain "
                    "not incentive-assessed (never treated as organic)."
                )
            else:
                ctx = None
                try:
                    ctx = await self._incentive_service.resolve(
                        tenant_id,
                        evidence=_relationship_evidence(
                            relationship_ref, source_entity_id, target_entity_id
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - enrichment must not abort the run
                    logger.warning(
                        "relationship_intelligence_incentive_resolve_failed",
                        extra={"relationship_ref": relationship_ref, "error": str(exc)},
                    )
                    limitations.append(
                        "Incentive enrichment failed; observations remain not "
                        "incentive-assessed (never treated as organic)."
                    )
                if ctx is not None:
                    observations, incentive_assessed = _apply_incentive_context(
                        observations, ctx
                    )
                    if incentive_assessed:
                        metrics.increment(
                            "relationship_spine.incentive.enriched",
                            value=1,
                            labels={"mode": mode, "tenant": tenant_id},
                        )

        # ── Independence resolution (never fabricated) ─────────────────────
        account: Optional[IndependentEvidenceAccount] = independent_account
        if account is not None and not isinstance(account, IndependentEvidenceAccount):
            account = None
        if resolve_independence and account is None:
            resolver = load_m6_independence_resolver()
            if resolver is not None:
                try:
                    account = resolver(
                        relationship_ref=relationship_ref,
                        tenant_id=tenant_id,
                        observations=list(observations),
                    )
                except Exception as exc:  # noqa: BLE001 - seam must never break a run
                    logger.warning(
                        "relationship_intelligence_independence_resolve_failed",
                        extra={"relationship_ref": relationship_ref, "error": str(exc)},
                    )
                    account = None
                if not isinstance(account, IndependentEvidenceAccount):
                    account = None
        elif not resolve_independence and account is None:
            # Declined grouping: hand the engine an explicit empty account so it
            # does NOT independently load the M6 seam. The engine treats an
            # empty account as independence UNKNOWN -> gated dims stay null.
            account = IndependentEvidenceAccount(
                groups=(),
                provided_by=(
                    "services.relationship_intelligence.coordinator"
                    ":resolve_independence=false"
                ),
            )
            limitations.append(
                "Independent-observation grouping declined by caller; "
                "independence-gated dimensions are UNKNOWN, not zero."
            )

        # ── Compute ────────────────────────────────────────────────────────
        vector = None
        if not observations:
            limitations.append(
                "No observations for this relationship; fidelity unknown (never 0)."
            )
        else:
            try:
                vector = self._engine.compute_fidelity(
                    relationship_ref=relationship_ref,
                    observations=observations,
                    tenant_id=tenant_id,
                    window_seconds=window_seconds,
                    measured=measured,
                    independent_account=account,
                )
            except Exception as exc:  # noqa: BLE001 - compute failure is a limitation
                logger.warning(
                    "relationship_intelligence_fidelity_compute_failed",
                    extra={"relationship_ref": relationship_ref, "error": str(exc)},
                )
                vector = None
                limitations.append(
                    "Fidelity computation failed; fidelity unknown (never 0)."
                )

        independence_known = False
        if vector is not None:
            metrics.increment(
                "relationship_spine.fidelity.computed",
                value=1,
                labels={"mode": mode, "tenant": tenant_id},
            )
            coverage = vector.coverage or {}
            independence_known = not bool(coverage.get("independence_unknown", True))
            if independence_known:
                metrics.increment(
                    "relationship_spine.fidelity.independence_known",
                    value=1,
                    labels={"mode": mode, "tenant": tenant_id},
                )
            for limitation in vector.limitations or ():
                if limitation not in limitations:
                    limitations.append(limitation)

        # ── Persist gate ───────────────────────────────────────────────────
        persisted = False
        run_id = None
        should_persist = persist
        if should_persist is None:
            should_persist = mode in PERSIST_MODES
        if should_persist and vector is not None and vector.observation_count > 0:
            try:
                record = await self._engine.persist_fidelity(
                    tenant_id=tenant_id,
                    vector=vector,
                )
                run_id = (record or {}).get("run_id")
                persisted = bool(run_id)
                if persisted and mode in ("shadow", "warn"):
                    limitations.append(
                        f"Fidelity mode '{mode}': persisted run is "
                        "observation/compare-only; not enforced."
                    )
            except Exception as exc:  # noqa: BLE001 - persist failure recorded, run survives
                logger.warning(
                    "relationship_intelligence_fidelity_persist_failed",
                    extra={"relationship_ref": relationship_ref, "error": str(exc)},
                )
                limitations.append(
                    "Fidelity persistence failed; vector not persisted."
                )
        if mode == "off":
            if should_persist:
                limitations.append(
                    "Fidelity mode 'off': persistence occurred only via an "
                    "explicit caller override."
                )
            else:
                limitations.append(
                    "Fidelity mode 'off': vector not persisted (rollout write OFF)."
                )
        elif vector is None and should_persist:
            limitations.append(
                "Nothing to persist: no computed fidelity vector for this run."
            )
        elif persist is False and mode in PERSIST_MODES:
            limitations.append(
                "Persistence suppressed by caller (persist=False); vector not persisted."
            )
        if persisted:
            metrics.increment(
                "relationship_spine.fidelity.persisted",
                value=1,
                labels={"mode": mode, "tenant": tenant_id},
            )

        metrics.increment(
            "relationship_spine.run",
            value=1,
            labels={"mode": mode, "tenant": tenant_id},
        )
        return SpineRunResult(
            relationship_ref=relationship_ref,
            tenant_id=tenant_id,
            mode=mode,
            independence_known=independence_known,
            vector=vector,
            persisted=persisted,
            run_id=run_id,
            incentive_assessed=incentive_assessed,
            limitations=limitations,
        )


__all__ = [
    "PERSIST_MODES",
    "INCENTIVE_PRESENT_STATUSES",
    "RelationshipSpineCoordinator",
    "SpineRunResult",
    "relationship_ref_for",
    "materialize_observations",
]
