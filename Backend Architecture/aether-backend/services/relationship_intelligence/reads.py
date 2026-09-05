"""Canonical read helpers over the Relationship-Intelligence substrate.

Thin, honest read surfaces consumed by the ``/v1/relationships`` routes:

* :func:`read_latest_fidelity` — the ``computation_runs`` row whose
  ``data.kind == "fidelity_vector_surface"`` for one relationship (assembled
  vector contract + run meta), or ``None`` when none exists. Run discovery is
  through the Computation Substrate's sanctioned ``get_run`` read, keyed by the
  engine's deterministic default run id (``run_fidelity_fid_<sha256[:12]>`` of
  ``relationship_ref`` — see :func:`fidelity_run_id_for`). The substrate's
  per-dimension ``CanonicalResult`` rows do not carry ``run_id`` and it exposes
  no run-listing API, so no other relationship->run channel exists; a run
  persisted under a custom ``fidelity_vector_id`` is honestly reported as no
  data rather than guessed at.
* :func:`read_relationship_basis` — an honest explain basis assembled from the
  relationship-predicate registry (registered semantics), the latest persisted
  fidelity (when present) and degraded sections for data this helper cannot
  compute (motif matches over a pair require observed graph edges it is not
  handed; incentive flags are reported from the assessed vector when present).
* :func:`read_influence` — the pure nine-way influence-propagation decomposition
  over the best evidence-backed path supplied by the caller; when no
  evidence-backed path exists it returns an honest empty / ``insufficient_data``
  envelope (never synthesized).

Unknown is never 0: every envelope carries ``available`` / ``insufficient_data``
semantics and a ``degraded`` marker when data is absent.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional, Sequence

from services.relationship_intelligence.coordinator import relationship_ref_for

# Reason-code constants shared by the read envelopes.
REASON_NO_DATA = "no_data"
REASON_INSUFFICIENT_DATA = "insufficient_data"
REASON_MOTIF_EVIDENCE_ABSENT = "motif_match_evidence_absent"
REASON_NO_EVIDENCE_BACKED_PATH = "no_evidence_backed_path"
REASON_INFLUENCE_INPUTS_ABSENT = "influence_inputs_absent"
REASON_NO_PERSISTED_RUN = "no_persisted_fidelity_run"


# --------------------------------------------------------------------------- #
# Latest persisted fidelity
# --------------------------------------------------------------------------- #


def fidelity_run_id_for(relationship_ref: str) -> str:
    """Deterministic engine run id for a relationship's default persist.

    Mirrors ``services/relationship_fidelity/engine.persist_fidelity``: the run
    id defaults to ``run_fidelity_{fidelity_vector_id}`` and the engine derives
    ``fidelity_vector_id = fid_{sha256(relationship_ref)[:12]}`` when the caller
    does not supply one (the coordinator path this package owns). A run
    persisted with a custom ``fidelity_vector_id`` lives under a different id;
    this helper honestly cannot discover it (see :func:`read_latest_fidelity`).
    """
    digest = hashlib.sha256(relationship_ref.encode()).hexdigest()[:12]
    return f"run_fidelity_fid_{digest}"


def _assemble_run_read(run: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Assemble the JSON-safe vector contract + run meta from one run row."""
    return {
        "kind": "fidelity_vector_surface",
        "available": True,
        "degraded": False,
        "run_id": run.get("run_id"),
        "definition_id": run.get("definition_id"),
        "definition_version": run.get("definition_version"),
        "status": run.get("status"),
        "context_hash": run.get("context_hash"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "mode": data.get("mode"),
        "schema_version": data.get("schema_version"),
        "fidelity_vector_id": data.get("fidelity_vector_id"),
        "relationship_ref": data.get("relationship_ref"),
        "computed_at": data.get("computed_at"),
        "vector": data.get("vector"),
    }


async def read_latest_fidelity(
    tenant_id: str, relationship_ref: str
) -> Optional[dict[str, Any]]:
    """The persisted fidelity-vector surface for a relationship, or None.

    Returns an assembled vector-contract + run-meta dict, or ``None`` when no
    ``fidelity_vector_surface`` run exists for the relationship in the tenant
    (no data => ``None`` — never an empty/zero vector).
    """
    from services.computation.repositories import get_computation_repository

    repo = get_computation_repository()
    run = await repo.get_run(tenant_id, fidelity_run_id_for(relationship_ref))
    if run is None:
        return None
    data = run.get("data") or {}
    if data.get("kind") != "fidelity_vector_surface":
        return None
    if data.get("relationship_ref") != relationship_ref:
        return None
    return _assemble_run_read(run, data)


# --------------------------------------------------------------------------- #
# Relationship explain basis
# --------------------------------------------------------------------------- #


def _predicate_summary(entry: dict[str, Any]) -> dict[str, Any]:
    requirements = entry.get("defaultEvidenceRequirements") or {}
    return {
        "predicate": entry.get("predicate"),
        "graph_edge_type": entry.get("graphEdgeType"),
        "registration_state": entry.get("graphRegistrationState"),
        "claim_type_floor": entry.get("claimTypeFloor"),
        "minimum_independent_observations": requirements.get(
            "minimumIndependentObservations"
        ),
        "requires_bidirectional_evidence": requirements.get(
            "requiresBidirectionalEvidence"
        ),
        "incentive_exposure_required": requirements.get("incentiveExposureRequired"),
    }


def _predicate_basis() -> dict[str, Any]:
    """Registered relationship-predicate semantics (static, always available)."""
    from shared.relationship_spine.relationship_registry import all_predicates

    predicates = all_predicates()
    registered = [
        p for p in predicates if p.get("graphRegistrationState") == "REGISTERED"
    ]
    return {
        "available": True,
        "registry": "relationship-predicate-registry.json",
        "registered_predicate_count": len(registered),
        "total_predicate_count": len(predicates),
        "registered_predicates": [_predicate_summary(p) for p in sorted(
            registered, key=lambda p: str(p.get("predicate") or "")
        )],
    }


def _fidelity_basis(read: dict[str, Any]) -> dict[str, Any]:
    from shared.relationship_fidelity.definitions import FIDELITY_DIMENSIONS

    vector = read.get("vector") or {}
    materialized = [d for d in FIDELITY_DIMENSIONS if vector.get(d) is not None]
    quality = (vector.get("quality") or {}).get("overall")
    coverage = (vector.get("coverage") or {}).get("overall")
    return {
        "available": True,
        "run_id": read.get("run_id"),
        "computed_at": read.get("computed_at"),
        "mode": read.get("mode"),
        "status": vector.get("status"),
        "observation_count": vector.get("observation_count"),
        "independent_evidence_count": vector.get("independent_evidence_count"),
        "independent_source_count": vector.get("independent_source_count"),
        "materialized_dimension_count": len(materialized),
        "materialized_dimensions": materialized,
        "quality_overall": quality,
        "coverage_overall": coverage,
        "limitations": vector.get("limitations") or [],
    }


def _motif_basis() -> dict[str, Any]:
    """Motif-match basis is degraded: pair-level observed edges are not supplied.

    ``detect_motifs`` requires the pair's observed relationship edges across the
    graph. A read helper bound only to (tenant, source, target) cannot compute
    them, so the section reports ``insufficient_data`` honestly rather than
    fabricating motif matches or their absence.
    """
    return {
        "available": False,
        "state": REASON_INSUFFICIENT_DATA,
        "reason_code": REASON_MOTIF_EVIDENCE_ABSENT,
        "reason": (
            "Motif matching requires the pair's observed relationship edges; "
            "the read helper is not supplied them. Absence is unknown, never a "
            "definitive no-match."
        ),
    }


def _incentive_basis(read: Optional[dict[str, Any]]) -> dict[str, Any]:
    if read is None:
        return {
            "available": False,
            "state": REASON_INSUFFICIENT_DATA,
            "reason_code": REASON_NO_PERSISTED_RUN,
            "reason": "No persisted fidelity run: incentive presence/absence was not assessed.",
            "incentive_assessment_coverage": None,
            "incentive_exposure": None,
            "incentive_independence_support": None,
        }
    vector = read.get("vector") or {}
    quality = (vector.get("quality") or {}).get("dimensions") or {}
    coverage = quality.get("incentive_assessment_coverage")
    exposure = vector.get("incentive_exposure")
    independence_support = vector.get("incentive_independence_support")
    assessed = bool(exposure is not None or (coverage or "").startswith("ready"))
    if assessed:
        return {
            "available": True,
            "state": "ready",
            "reason_code": "ready",
            "reason": "Incentive presence/absence was assessed on the persisted run.",
            "incentive_assessment_coverage": coverage,
            "incentive_exposure": exposure,
            "incentive_independence_support": independence_support,
        }
    return {
        "available": False,
        "state": REASON_INSUFFICIENT_DATA,
        "reason_code": "incentive_not_assessed_on_run",
        "reason": (
            "The persisted run did not assess incentive presence/absence; "
            "unassessed activity is never treated as organic."
        ),
        "incentive_assessment_coverage": coverage,
        "incentive_exposure": exposure,
        "incentive_independence_support": independence_support,
    }


def _surface_state() -> dict[str, Any]:
    """Honest registry state for the social360 projection surface.

    The social360 row is ``in_flight`` with no registered provider on this
    branch; surfaces report that honestly rather than claiming readiness.
    """
    from shared.intelligence_projections.registry import projection_registry

    availability = dict(
        projection_registry.availability().get("social360", {})
    )
    return {
        "available": False,
        "projection_id": "social360",
        "registry_state": availability.get("registryState"),
        "provider_registered": bool(availability.get("registered")),
        "contract_compatible": bool(availability.get("contractCompatible")),
    }


async def read_relationship_basis(
    tenant_id: str, source_entity_id: str, target_entity_id: str
) -> dict[str, Any]:
    """Honest explain basis for one relationship pair.

    Compose what is genuinely computable from the substrate and degrade the
    rest: registered predicate semantics (available), the latest persisted
    fidelity vector (when present), incentive flags (reported from the assessed
    vector when present) and motif matches (degraded — see
    :func:`_motif_basis`).
    """
    relationship_ref = relationship_ref_for(source_entity_id, target_entity_id)
    latest = await read_latest_fidelity(tenant_id, relationship_ref)

    degraded: list[str] = []
    if latest is None:
        degraded.append(REASON_NO_PERSISTED_RUN)
    fidelity = _fidelity_basis(latest) if latest is not None else {
        "available": False,
        "state": REASON_INSUFFICIENT_DATA,
        "reason_code": REASON_NO_PERSISTED_RUN,
        "reason": "No persisted fidelity run for this relationship (fidelity unknown).",
    }

    return {
        "available": True,
        "relationship_ref": relationship_ref,
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "surface": _surface_state(),
        "sections": {
            "registered_predicates": _predicate_basis(),
            "fidelity": fidelity,
            "incentive": _incentive_basis(latest),
            "motifs": _motif_basis(),
        },
        "degraded": degraded,
    }


# --------------------------------------------------------------------------- #
# Influence propagation read
# --------------------------------------------------------------------------- #


def _component_dict(component: Any) -> dict[str, Any]:
    return {
        "component_id": component.component_id,
        "display_name": component.display_name,
        "blueprint_section": component.blueprint_section,
        "state": component.state,
        "value": component.value,
        "reason_code": component.reason_code,
        "reason": component.reason,
        "formula": component.formula,
        "material_hops": component.material_hops,
        "measured_hops": component.measured_hops,
        "per_hop_values": [[i, v] for i, v in component.per_hop_values],
        "limitations": component.limitations,
    }


def _decomposition_dict(decomposition: Any) -> dict[str, Any]:
    return {
        "source_ref": decomposition.source_ref,
        "target_ref": decomposition.target_ref,
        "algorithm": decomposition.algorithm,
        "version": decomposition.version,
        "as_of": decomposition.as_of,
        "decision": decomposition.decision,
        "propagation_certified": decomposition.propagation_certified,
        "reason_codes": list(decomposition.reason_codes),
        "staleness_status": decomposition.staleness_status,
        "hop_count": decomposition.hop_count,
        "min_epistemic_ceiling": decomposition.min_epistemic_ceiling,
        "available_component_ids": list(decomposition.available_component_ids),
        "components": [_component_dict(c) for c in decomposition.all_components],
    }


async def read_influence(
    tenant_id: str,
    source_entity_id: str,
    target_entity_id: str,
    as_of: Optional[str] = None,
    *,
    path_edges: Optional[Sequence[Any]] = None,
    fidelity_by_hop: Optional[Mapping[Any, Any]] = None,
) -> dict[str, Any]:
    """Decompose influence along the best evidence-backed propagable path.

    ``path_edges`` / ``fidelity_by_hop`` are the pure decomposition module's
    inputs (see ``shared/relationship_spine/influence_propagation.py``). When no
    evidence-backed path is supplied, an honest empty envelope is returned (all
    nine §71 components ``insufficient_data``, decision ``empty``) — never a
    synthesized influence figure.
    """
    relationship_ref = relationship_ref_for(source_entity_id, target_entity_id)
    from shared.relationship_spine.influence_propagation import (
        decompose_influence_propagation,
    )

    hops = list(path_edges or ())
    decomposition = decompose_influence_propagation(
        hops,
        source_ref=source_entity_id,
        target_ref=target_entity_id,
        as_of=as_of,
        fidelity_by_hop=fidelity_by_hop,
    )

    certified = bool(decomposition.propagation_certified)
    if not hops:
        degraded_reason = REASON_NO_EVIDENCE_BACKED_PATH
    elif not certified:
        degraded_reason = str(decomposition.decision)
    elif not decomposition.available_component_ids:
        # A certified propagable path with zero measured components is a
        # degraded read, never a clean one: per-hop measurements are absent.
        degraded_reason = REASON_INFLUENCE_INPUTS_ABSENT
    else:
        degraded_reason = None

    return {
        "available": bool(hops) and certified,
        "relationship_ref": relationship_ref,
        "source_ref": source_entity_id,
        "target_ref": target_entity_id,
        "degraded": degraded_reason is not None,
        "degraded_reason": degraded_reason,
        "insufficient_data": (
            certified
            and list(
                c.component_id
                for c in decomposition.all_components
                if c.state == REASON_INSUFFICIENT_DATA
            )
        )
        or [],
        "decomposition": _decomposition_dict(decomposition),
    }


__all__ = [
    "REASON_NO_DATA",
    "REASON_INSUFFICIENT_DATA",
    "fidelity_run_id_for",
    "read_latest_fidelity",
    "read_relationship_basis",
    "read_influence",
]
