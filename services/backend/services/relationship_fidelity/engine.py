"""Relationship Fidelity engine — M7 compute + consume-only persistence.

Runbook
-------
1. ``compute_fidelity`` derives the multidimensional vector from raw
   observations + (optionally) M6 independent-observation grouping. When the M6
   evidence engine is absent, independence is UNKNOWN and independence-gated
   dimensions stay null — never fabricated, never 0.
2. ``persist_fidelity`` writes the vector through
   ``services/computation/repositories.py`` (``ComputedResultsRepository``):
   one ``CanonicalResult`` per materialized dimension + the assembled vector
   document riding in the ``computation_runs.data`` JSONB. No new table.
3. Flag gate: ``AETHER_RELATIONSHIP_FIDELITY_MODE`` (off|shadow|warn|enforce)
   defaults ``off`` and is read defensively. Compute is pure; callers gate
   invocation (persist/emit) on the mode.

Existence-confidence is kept SEPARATE from relationship strength: the vector
carries both ``evidence_confidence`` (existence) and strength dimensions
(``persistence``, ``reciprocity``, ...) as independent, nullable axes.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Optional, Sequence

from shared.computation.definition import ComputationDefinition
from shared.computation.quality import Quality, QualityDimensionName
from shared.computation.registry import register
from shared.computation.result import CanonicalResult, ResultStatus
from shared.computation.types import MathType
from shared.dimension_state import worst_state
from shared.relationship_fidelity.definitions import (
    FIDELITY_COUNT_FIELDS,
    FIDELITY_DEFINITIONS,
    FIDELITY_DEFINITION_VERSION,
    FIDELITY_DIMENSIONS,
    INDEPENDENCE_GATED_DIMENSIONS,
    MEASURED_PASSTHROUGH_DIMENSIONS,
    get_fidelity_definition,
    register_fidelity_definitions,
)
from shared.relationship_fidelity.evidence import (
    EffectiveEvidence,
    EvidenceIndependenceResolver,
    IndependentEvidenceAccount,
    Observation,
    build_effective_evidence,
    load_m6_independence_resolver,
)
from shared.relationship_fidelity.scoring import DERIVERS, passthrough_value
from shared.relationship_fidelity.vector import (
    FidelityVector,
    assemble_fidelity_vector,
)

logger = logging.getLogger("aether.relationship_fidelity")

# Flag: AETHER_RELATIONSHIP_FIDELITY_MODE (off|shadow|warn|enforce). Default off.
FIDELITY_MODES: tuple[str, ...] = ("off", "shadow", "warn", "enforce")
FIDELITY_MODE_ENV: str = "AETHER_RELATIONSHIP_FIDELITY_MODE"

_DEFAULT_VECTOR_DEFINITION_ID = "relationship_fidelity.vector"


def fidelity_mode() -> str:
    """Read the fidelity rollout flag defensively (never edit settings.py).

    Resolution order: environment override → optional settings attribute →
    ``off``. An unrecognized value falls back to ``off`` (new behavior defaults
    OFF until explicit activation).
    """
    value = None
    env_value = __import__("os").environ.get(FIDELITY_MODE_ENV)
    if env_value:
        value = env_value
    else:
        try:
            from config.settings import get_settings  # type: ignore[import-not-found]

            settings = get_settings()
            candidate = getattr(settings, "relationship_fidelity_mode", None)
            if candidate:
                value = candidate
        except Exception:
            value = None
    mode = str(value or "off").strip().lower()
    return mode if mode in FIDELITY_MODES else "off"


def _context_hash(relationship_ref: str, observation_ids: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(relationship_ref.encode("utf-8"))
    for oid in sorted(observation_ids):
        digest.update(b"\x00" + oid.encode("utf-8"))
    return digest.hexdigest()


class RelationshipFidelityEngine:
    """Computes and persists multidimensional relationship-fidelity vectors."""

    def __init__(self, resolver: Optional[EvidenceIndependenceResolver] = None) -> None:
        self._resolver = resolver

    # ------------------------------------------------------------------ #
    # Independence resolution (defensive M6 consumption)
    # ------------------------------------------------------------------ #
    def _obtain_account(
        self,
        *,
        relationship_ref: str,
        tenant_id: str,
        observations: Sequence[Observation],
        explicit: Optional[IndependentEvidenceAccount] = None,
    ) -> Optional[IndependentEvidenceAccount]:
        if explicit is not None:
            return explicit
        candidate: Optional[Callable[..., Optional[IndependentEvidenceAccount]]] = None
        if self._resolver is not None:
            candidate = self._resolver
        else:
            candidate = load_m6_independence_resolver()
        if candidate is None:
            # M6 evidence engine absent => independence UNKNOWN (never fabricated).
            return None
        try:
            account = candidate(
                relationship_ref=relationship_ref,
                tenant_id=tenant_id,
                observations=list(observations),
            )
        except Exception as exc:  # M6 must never break fidelity; degrade to UNKNOWN
            logger.warning(
                "relationship_fidelity_m6_resolver_failed",
                extra={"relationship_ref": relationship_ref, "error": str(exc)},
            )
            return None
        return account if isinstance(account, IndependentEvidenceAccount) else None

    # ------------------------------------------------------------------ #
    # Computation
    # ------------------------------------------------------------------ #
    def compute_fidelity(
        self,
        *,
        relationship_ref: str,
        observations: Sequence[Observation],
        tenant_id: str = "",
        window_seconds: Optional[float] = None,
        measured: Optional[dict[str, float]] = None,
        independent_account: Optional[IndependentEvidenceAccount] = None,
        fidelity_vector_id: Optional[str] = None,
    ) -> FidelityVector:
        """Compute the multidimensional fidelity vector for a relationship.

        Honesty invariants enforced here:
        * independence unknown (no M6 module / resolver) => independent counts
          are null and independence-gated dimensions stay null;
        * unknown is never 0 (dimensions absent from evidence are null);
        * no universal scalar is produced.
        """
        if not relationship_ref:
            raise ValueError("relationship_ref is required")
        account = self._obtain_account(
            relationship_ref=relationship_ref,
            tenant_id=tenant_id,
            observations=observations,
            explicit=independent_account,
        )
        eff = build_effective_evidence(observations, account)

        if eff.observation_count == 0:
            # No evidence: the honest surface is a null/unknown vector (never a
            # fabricated 0 vector). Envelope timestamps cannot be fabricated.
            return self._empty_vector(relationship_ref)

        dimension_values: dict[str, Optional[float]] = {}
        for dim in FIDELITY_DIMENSIONS:
            value: Optional[float]
            if dim in MEASURED_PASSTHROUGH_DIMENSIONS:
                value = passthrough_value((measured or {}).get(dim))
            else:
                ctx = {
                    "window_seconds": window_seconds,
                    "measured": measured or {},
                }
                fn = DERIVERS.get(dim)
                if fn is None:
                    value = None
                else:
                    try:
                        value = fn(eff, ctx)
                    except Exception:
                        value = None
            if value is not None:
                dimension_values[dim] = round(value, 4)
            else:
                dimension_values[dim] = None

        coverage = self._build_coverage(eff, dimension_values)
        quality = self._build_quality(eff, dimension_values)
        uncertainty = self._build_uncertainty(eff)

        return assemble_fidelity_vector(
            fidelity_vector_id=fidelity_vector_id
            or f"fid_{hashlib.sha256(relationship_ref.encode()).hexdigest()[:12]}",
            relationship_ref=relationship_ref,
            dimension_values=dimension_values,
            observation_count=eff.observation_count,
            independent_evidence_count=eff.independent_evidence_count,
            independent_source_count=eff.independent_source_count,
            first_observed_at=eff.first_observed_at,
            last_observed_at=eff.last_observed_at,
            coverage=coverage,
            quality=quality,
            uncertainty=uncertainty,
            limitations=self._limitations(eff),
            evidence_refs=[o.observation_id for o in eff.observations],
            computation_refs=self._computation_refs(dimension_values),
        )

    def _empty_vector(self, relationship_ref: str) -> FidelityVector:
        """Zero-evidence surface: all dimensions null, status ``unknown``.

        No timestamps are fabricated (none observed); the caller treats a
        zero-observation relationship as fidelity-unknown.
        """
        dims = {name: None for name in FIDELITY_DIMENSIONS}
        return assemble_fidelity_vector(
            fidelity_vector_id=f"fid_{hashlib.sha256(relationship_ref.encode()).hexdigest()[:12]}",
            relationship_ref=relationship_ref,
            dimension_values=dims,
            observation_count=0,
            independent_evidence_count=None,
            independent_source_count=None,
            first_observed_at=None,
            last_observed_at=None,
            coverage={"overall": "empty"},
            quality={
                "overall": "empty",
                "dimensions": {"sample_sufficiency": "insufficient_data"},
            },
            uncertainty=None,
            limitations=["No observations for this relationship; fidelity unknown (never 0)."],
            evidence_refs=[],
            computation_refs=[],
        )

    # ------------------------------------------------------------------ #
    # Vector metadata
    # ------------------------------------------------------------------ #
    def _build_coverage(
        self, eff: EffectiveEvidence, dims: dict[str, Optional[float]]
    ) -> dict[str, Any]:
        per_dim: dict[str, Any] = {}
        for dim in FIDELITY_DIMENSIONS:
            value = dims.get(dim)
            state = "available" if value is not None else "insufficient_data"
            if dim in MEASURED_PASSTHROUGH_DIMENSIONS:
                basis = "measured_passthrough"
            elif dim in INDEPENDENCE_GATED_DIMENSIONS:
                basis = "independence_gated"
            else:
                basis = "derived"
            per_dim[dim] = {
                "state": state,
                "basis": basis,
                "math_type": "heuristic_score",
            }
        return {
            "overall": "partial" if any(v is not None for v in dims.values()) else "empty",
            "independent_account": (eff.account.provided_by if eff.account is not None else None),
            "independence_unknown": eff.independence_unknown,
            "damped_support": eff.damped_support,
            "dimensions": per_dim,
        }

    def _build_quality(
        self, eff: EffectiveEvidence, dims: dict[str, Optional[float]]
    ) -> dict[str, Any]:
        sample_state = "ready" if eff.observation_count >= 1 else "insufficient_data"
        independence_state = (
            "ready" if eff.independent_evidence_count is not None else "insufficient_data"
        )
        assessment_state = "ready" if eff.incentive_assessed_count > 0 else "insufficient_data"
        states = [sample_state, independence_state]
        return {
            "overall": worst_state(states),
            "dimensions": {
                "sample_sufficiency": sample_state,
                "independence_sufficiency": independence_state,
                "incentive_assessment_coverage": assessment_state,
            },
        }

    def _build_uncertainty(self, eff: EffectiveEvidence) -> Optional[dict[str, Any]]:
        out: dict[str, Any] = {}
        if eff.observation_count > 0:
            out["evidence_coverage"] = {
                "kind": "evidence_coverage",
                "method": "independent_observation_count",
                "point": (
                    float(eff.independent_evidence_count)
                    if eff.independent_evidence_count is not None
                    else None
                ),
                "observed_count": eff.observation_count,
            }
        if eff.damped_support is not None:
            out["correlation_damping"] = {
                "kind": "evidence_coverage",
                "method": "correlation_damping_0.4",
                "damped_support": eff.damped_support,
                "raw_observation_count": eff.observation_count,
            }
        return out if out else None

    def _limitations(self, eff: EffectiveEvidence) -> list[str]:
        limitations: list[str] = []
        if eff.independence_unknown:
            limitations.append(
                "Independent-observation grouping unavailable (M6 evidence engine "
                "not present); independent counts and independence-gated dimensions "
                "are UNKNOWN, not zero."
            )
        if eff.distinct_sources is None and eff.observation_count:
            limitations.append(
                "Observation source identities unavailable; corroboration cannot be assessed."
            )
        return limitations

    @staticmethod
    def _computation_refs(dims: dict[str, Optional[float]]) -> list[str]:
        return [
            f"relationship_fidelity.{name}@{FIDELITY_DEFINITION_VERSION}"
            for name, value in dims.items()
            if value is not None
        ]

    # ------------------------------------------------------------------ #
    # Persistence (consume-only over services/computation/repositories.py)
    # ------------------------------------------------------------------ #
    async def persist_fidelity(
        self,
        *,
        tenant_id: str,
        vector: FidelityVector,
        context_hash: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist a computed vector through the Computation Substrate.

        Writes one ``CanonicalResult`` per materialized dimension + count and a
        run record carrying the assembled vector document. CONSUME-ONLY: no new
        DDL/table is created here; a need for durable persistence beyond
        ``computed_results``/``computation_runs`` would be recorded as a blocker,
        never migrated.
        """
        register_fidelity_definitions()
        if vector.observation_count == 0:
            raise ValueError(
                "refusing to persist a zero-observation fidelity vector as current; "
                "fidelity is unknown for relationships with no observations"
            )
        from services.computation.repositories import get_computation_repository

        repo = get_computation_repository()
        observation_ids = list(vector.evidence_refs)
        ctx_hash = context_hash or _context_hash(vector.relationship_ref, observation_ids)
        run = {
            "run_id": run_id or f"run_fidelity_{vector.fidelity_vector_id}",
            "tenant_id": tenant_id,
            "definition_id": _DEFAULT_VECTOR_DEFINITION_ID,
            "definition_version": FIDELITY_DEFINITION_VERSION,
            "context_hash": ctx_hash,
            "status": "completed",
            "data": {
                "kind": "fidelity_vector_surface",
                "schema_version": vector.schema_version,
                "fidelity_vector_id": vector.fidelity_vector_id,
                "relationship_ref": vector.relationship_ref,
                "vector": vector.to_contract_dict(),
                "mode": fidelity_mode(),
                "computed_at": vector.computed_at,
            },
            "started_at": vector.computed_at,
            "completed_at": vector.computed_at,
        }
        await repo.insert_run(run)

        inserted: list[str] = []
        for dim, value in vector.dimension_values().items():
            if value is None:
                continue
            definition = get_fidelity_definition(f"relationship_fidelity.{dim}")
            if definition is None:
                continue
            result = self._dimension_result(
                definition=definition,
                tenant_id=tenant_id,
                relationship_ref=vector.relationship_ref,
                value=value,
                context_hash=ctx_hash,
                computed_at=vector.computed_at,
            )
            await repo.insert_result(result.model_dump(mode="json"))
            inserted.append(result.definition_id)
        return {"run_id": run["run_id"], "inserted_definition_ids": inserted}

    def _dimension_result(
        self,
        *,
        definition: ComputationDefinition,
        tenant_id: str,
        relationship_ref: str,
        value: float,
        context_hash: str,
        computed_at: str,
    ) -> CanonicalResult:
        quality = (
            Quality()
            .with_dimension(
                QualityDimensionName.SAMPLE_SUFFICIENCY,
                state="ready",
                reason="observation basis present",
            )
            .with_dimension(
                QualityDimensionName.COVERAGE,
                state="ready",
                reason="dimension materialized",
            )
        )
        return CanonicalResult(
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            tenant_id=tenant_id,
            subject={"relationship_ref": relationship_ref},
            scope={"domain": "relationship_fidelity"},
            grain="relationship",
            dimensions={"relationship_ref": relationship_ref},
            value=value,
            value_type=definition.output_type,
            unit=definition.unit,
            status=ResultStatus.AVAILABLE,
            quality=quality,
            computed_at=computed_at,
            context_hash=context_hash,
        )


__all__ = [
    "FIDELITY_MODES",
    "FIDELITY_MODE_ENV",
    "RelationshipFidelityEngine",
    "fidelity_mode",
]
