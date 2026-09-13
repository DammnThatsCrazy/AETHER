"""Information fidelity — pure measurements over the information layer (SoT §67).

Phase 5 of the Communication360 convergence program. This module is PURE LOGIC:
no DB, no network, no repository imports. It computes the information-fidelity
metrics the spec (§67, §71) names — ``claim_retention_rate``,
``citation_retention_rate``, ``evidence_retention_rate``, ``semantic_drift``,
``omission_rate``, ``unsupported_addition_rate``, ``contradiction_rate`` — over
the frozen Phase-3 contracts (:class:`InformationTransformation`,
:class:`MessageClaimBinding`, :class:`Information`) and deterministic fixture
dicts.

What a transformation contributes to measurement
-------------------------------------------------
An :class:`InformationTransformation` links a ``source_information_ref`` to a
``derived_information_ref`` (kind: summarization | paraphrase | extraction |
reformat | translation). The frozen contract intentionally does NOT carry the
claim/citation/evidence universes of the two endpoints — those are modelled by
:class:`MessageClaimBinding` (a claim bound to an information ref) and
:class:`Information` (``source_refs``). This module therefore accepts either:

* a frozen :class:`InformationTransformation` instance — its identity
  (source/derived refs, kind, ``drift_notes``) is honoured, but with no claim
  measurement attached it contributes an *unmeasured* hop (metrics over such a
  set are NaN — honest absence, never a fabricated zero), or
* a fixture dict that mirrors the contract identity keys AND carries an
  explicit per-hop measurement partition describing how the hop moved claims /
  citations / evidence from source to derived.

Per-hop measurement partition (dict fixtures)
---------------------------------------------
The claim universe of the hop's source information is partitioned exhaustively:

* ``source_claims`` / ``retained_claims`` — required: all source claim ids and
  those preserved as-is in the derived information.
* ``meaning_changed_claims`` — source claims represented but semantically
  altered (default empty).
* ``contradicted_claims`` — source claims represented as a negation /
  contradiction (default empty).
* ``omitted_claims`` — ALWAYS derived as
  ``source - retained - meaning_changed - contradicted`` (never supplied), so
  the partition is mutually exclusive and exhaustive by construction and
  ``claim_retention_rate + semantic_drift + omission_rate == 1``.

Addition / citation / evidence measurement is optional per hop:
``added_claims`` + ``unsupported_added_claims`` (claims introduced and how many
carried no supporting evidence), ``source_citations``/``retained_citations``,
and ``source_evidence_refs``/``retained_evidence_refs``.

Epistemic discipline (R1 + SoT §67)
-----------------------------------
These are DERIVED measurements over a declared transformation lineage — an
``inference is not fact`` surface. :class:`FidelityReport` therefore defaults
``claim_state`` to :attr:`EpistemicStatus.INFERRED` and refuses (raises) any
attempt to build a report in the factual band (``verified`` / ``resolved`` /
``causally_supported``). ``confidence`` is the fraction of hops that carried
claim-measurement data (0.0 when nothing was measured). ``NaN`` marks an
unmeasured metric; it is never a fabricated value.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.communication360.contracts import (
    InformationTransformation,
    MessageClaimBinding,
)
from shared.contracts_models.epistemic import EpistemicStatus

# ─────────────────────────────────────────────────────────────────────────────
# Epistemic guard
# ─────────────────────────────────────────────────────────────────────────────

#: Statuses that must never appear on a derived fidelity measurement.
FACTUAL_BAND: frozenset[EpistemicStatus] = frozenset(
    {
        EpistemicStatus.VERIFIED,
        EpistemicStatus.RESOLVED,
        EpistemicStatus.CAUSALLY_SUPPORTED,
    }
)

#: Default epistemic status for a computed fidelity measurement (R1).
FIDELITY_CLAIM_STATE: EpistemicStatus = EpistemicStatus.INFERRED


def assert_derived_status(status: EpistemicStatus) -> EpistemicStatus:
    """Reject a factual-band status on a derived measurement (inference ≠ fact).

    Fidelity numbers are measurements *about* how information changed across a
    transformation lineage — never a verification that the derived content is
    true or that the transformation was correct.
    """
    if status in FACTUAL_BAND:
        raise ValueError(
            "fidelity measurements are derived/inferred (R1) — "
            f"refusing claim_state {status.value!r}"
        )
    return status


# ─────────────────────────────────────────────────────────────────────────────
# Local result model (never a canonical contract — a computed measurement)
# ─────────────────────────────────────────────────────────────────────────────


class FidelityReport(BaseModel):
    """Deterministic, derived information-fidelity report over a lineage.

    Every rate is bounded to ``[0, 1]`` when measured; a metric whose
    denominator could not be measured is ``NaN`` (honest absence — never a
    fabricated zero). ``claim_state`` defaults to ``inferred`` and cannot be
    raised into the factual band.
    """

    model_config = ConfigDict(extra="forbid")

    claim_retention_rate: float = Field(default=math.nan)
    citation_retention_rate: float = Field(default=math.nan)
    evidence_retention_rate: float = Field(default=math.nan)
    semantic_drift: float = Field(default=math.nan)
    omission_rate: float = Field(default=math.nan)
    unsupported_addition_rate: float = Field(default=math.nan)
    contradiction_rate: float = Field(default=math.nan)
    claim_state: EpistemicStatus = FIDELITY_CLAIM_STATE
    confidence: float = 0.0
    transformation_count: int = 0

    @model_validator(mode="after")
    def _enforce_derived_status(self) -> "FidelityReport":
        assert_derived_status(self.claim_state)
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Hop normalisation
# ─────────────────────────────────────────────────────────────────────────────

#: Partition keys recognised on a fixture-dict hop (each a list of claim ids).
_HOP_PARTITION_KEYS = (
    "source_claims",
    "retained_claims",
    "meaning_changed_claims",
    "contradicted_claims",
    "added_claims",
    "unsupported_added_claims",
    "source_citations",
    "retained_citations",
    "source_evidence_refs",
    "retained_evidence_refs",
)

#: Fixture-only contradiction relation markers on a MessageClaimBinding dict.
_CONTRADICTION_MARKER_KEYS = (
    "contradicts_claim_id",
    "contradicts_information_id",
    "contradiction_of",
)


def _normalize_hops(transformations: Any) -> list[dict[str, Any]]:
    """Return an ordered list of hop dicts (identity + optional partition)."""
    if isinstance(transformations, (InformationTransformation, dict)):
        transformations = [transformations]
    if transformations is None:
        return []
    hops: list[dict[str, Any]] = []
    for item in transformations:
        if isinstance(item, InformationTransformation):
            data: dict[str, Any] = item.model_dump()
        elif isinstance(item, dict):
            data = dict(item)
        else:
            raise TypeError(
                "transformations must be InformationTransformation instances "
                f"or fixture dicts, got {type(item).__name__}"
            )
        hops.append(data)
    return hops


def hop_source_information_id(hop: Union[InformationTransformation, dict]) -> Optional[str]:
    """The ``information_id`` of a hop's source information ref."""
    if isinstance(hop, InformationTransformation):
        return hop.source_information_ref.information_id
    if isinstance(hop, dict):
        ref = hop.get("source_information_ref")
        if isinstance(ref, dict):
            return ref.get("information_id")
        if ref is not None:
            return getattr(ref, "information_id", None)
    return None


def hop_derived_information_id(hop: Union[InformationTransformation, dict]) -> Optional[str]:
    """The ``information_id`` of a hop's derived information ref."""
    if isinstance(hop, InformationTransformation):
        return hop.derived_information_ref.information_id
    if isinstance(hop, dict):
        ref = hop.get("derived_information_ref")
        if isinstance(ref, dict):
            return ref.get("information_id")
        if ref is not None:
            return getattr(ref, "information_id", None)
    return None


def _ids(value: Any, field: str) -> Optional[list[str]]:
    """Normalise a partition value to a list of ids; None when the key is absent."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{field} must be a list of ids (got {value!r}) so that the "
            "omission complement can be derived exactly"
        )
    return [str(v) for v in value]


def _ids_of(hop: dict[str, Any], key: str) -> Optional[list[str]]:
    if key not in hop:
        return None
    return _ids(hop[key], key)


# ─────────────────────────────────────────────────────────────────────────────
# Per-hop measurement extraction
# ─────────────────────────────────────────────────────────────────────────────


def _hop_partition(hop: dict[str, Any]) -> dict[str, Any]:
    """Resolve one hop dict into a complete, exhaustive measurement partition.

    A hop that supplies ``source_claims`` + ``retained_claims`` is
    *claim-measured*; meaning-change / contradiction default to empty and the
    omitted set is derived as the complement, so the four categories partition
    the source universe exactly. Citation / evidence / addition sub-measurements
    are present only when their source and target lists are both supplied.
    """
    has_partition = any(k in hop for k in _HOP_PARTITION_KEYS)

    source_ids = _ids_of(hop, "source_claims")
    retained_ids = _ids_of(hop, "retained_claims")
    meaning_changed_ids = _ids_of(hop, "meaning_changed_claims")
    contradicted_ids = _ids_of(hop, "contradicted_claims")

    claim_measured = source_ids is not None and retained_ids is not None

    omitted_ids: Optional[list[str]] = None
    if claim_measured:
        excluded = set(retained_ids)
        if meaning_changed_ids is not None:
            excluded |= set(meaning_changed_ids)
        if contradicted_ids is not None:
            excluded |= set(contradicted_ids)
        omitted_ids = [c for c in source_ids if c not in excluded]

    source_citations = _ids_of(hop, "source_citations")
    retained_citations = _ids_of(hop, "retained_citations")
    citations_measured = (
        source_citations is not None and retained_citations is not None
    )

    source_evidence = _ids_of(hop, "source_evidence_refs")
    retained_evidence = _ids_of(hop, "retained_evidence_refs")
    evidence_measured = source_evidence is not None and retained_evidence is not None

    added_ids = _ids_of(hop, "added_claims")
    unsupported_added_ids = _ids_of(hop, "unsupported_added_claims")
    additions_measured = added_ids is not None and unsupported_added_ids is not None

    return {
        "has_measurement": has_partition,
        "claim_measured": claim_measured,
        "source": 0.0 if not claim_measured else float(len(source_ids)),
        "retained": 0.0 if not claim_measured else float(len(retained_ids)),
        "meaning_changed": 0.0
        if (not claim_measured or meaning_changed_ids is None)
        else float(len(meaning_changed_ids)),
        "contradicted": 0.0
        if (not claim_measured or contradicted_ids is None)
        else float(len(contradicted_ids)),
        "omitted": 0.0 if omitted_ids is None else float(len(omitted_ids)),
        "omission_measured": omitted_ids is not None,
        "added_measured": additions_measured,
        "added": 0.0 if not additions_measured else float(len(added_ids)),
        "unsupported_added": 0.0
        if not additions_measured
        else float(len(unsupported_added_ids)),
        "citations_measured": citations_measured,
        "source_citations": 0.0
        if not citations_measured
        else float(len(source_citations)),
        "retained_citations": 0.0
        if not citations_measured
        else float(len(retained_citations)),
        "evidence_measured": evidence_measured,
        "source_evidence": 0.0
        if not evidence_measured
        else float(len(source_evidence)),
        "retained_evidence": 0.0
        if not evidence_measured
        else float(len(retained_evidence)),
    }


def _totals(hops: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate partition sums over the hop set (idempotent / order-free)."""
    totals: dict[str, float] = {
        "hop_count": float(len(hops)),
        "claim_measured_hops": 0.0,
        "source": 0.0,
        "retained": 0.0,
        "meaning_changed": 0.0,
        "contradicted": 0.0,
        "omitted": 0.0,
        "added_measured_hops": 0.0,
        "added": 0.0,
        "unsupported_added": 0.0,
        "citations_measured_hops": 0.0,
        "source_citations": 0.0,
        "retained_citations": 0.0,
        "evidence_measured_hops": 0.0,
        "source_evidence": 0.0,
        "retained_evidence": 0.0,
    }
    for hop in hops:
        p = _hop_partition(hop)
        if p["claim_measured"]:
            totals["claim_measured_hops"] += 1.0
            totals["source"] += p["source"]
            totals["retained"] += p["retained"]
            totals["meaning_changed"] += p["meaning_changed"]
            totals["contradicted"] += p["contradicted"]
            if p["omission_measured"]:
                totals["omitted"] += p["omitted"]
        if p["added_measured"]:
            totals["added_measured_hops"] += 1.0
            totals["added"] += p["added"]
            totals["unsupported_added"] += p["unsupported_added"]
        if p["citations_measured"]:
            totals["citations_measured_hops"] += 1.0
            totals["source_citations"] += p["source_citations"]
            totals["retained_citations"] += p["retained_citations"]
        if p["evidence_measured"]:
            totals["evidence_measured_hops"] += 1.0
            totals["source_evidence"] += p["source_evidence"]
            totals["retained_evidence"] += p["retained_evidence"]
    return totals


def _ratio(numerator: float, denominator: float) -> float:
    """Return ``numerator / denominator``; NaN when the universe is unmeasured.

    NaN (not a fabricated zero) is the honest-absence value for a metric whose
    denominator could not be observed.
    """
    if denominator == 0.0:
        return math.nan
    return numerator / denominator


# ─────────────────────────────────────────────────────────────────────────────
# Per-metric helpers — numbers are computed from the hops, never hardcoded
# ─────────────────────────────────────────────────────────────────────────────


def claim_retention(transformations: Any) -> float:
    """Fraction of source claims preserved as-is across the lineage (SoT §67)."""
    totals = _totals(_normalize_hops(transformations))
    return _ratio(totals["retained"], totals["source"])


def citation_retention(transformations: Any) -> float:
    """Fraction of source citations that survive to the derived information."""
    totals = _totals(_normalize_hops(transformations))
    return _ratio(totals["retained_citations"], totals["source_citations"])


def evidence_retention(transformations: Any) -> float:
    """Fraction of source evidence refs that survive to the derived information."""
    totals = _totals(_normalize_hops(transformations))
    return _ratio(totals["retained_evidence"], totals["source_evidence"])


def semantic_drift(transformations: Any) -> float:
    """Fraction of source claims whose meaning shifted (changed or contradicted)."""
    totals = _totals(_normalize_hops(transformations))
    return _ratio(
        totals["meaning_changed"] + totals["contradicted"],
        totals["source"],
    )


def omission_rate(transformations: Any) -> float:
    """Fraction of source claims fully dropped across the lineage."""
    totals = _totals(_normalize_hops(transformations))
    if totals["omitted"] is None:  # pragma: no cover — omitted is always a float
        return math.nan
    return _ratio(totals["omitted"], totals["source"])


def unsupported_addition_rate(transformations: Any) -> float:
    """Unsupported share of claims introduced by the lineage.

    Zero is honest when hops measured additions and observed none (nothing added
    ⇒ nothing unsupported); NaN when no hop reported an addition universe.
    """
    totals = _totals(_normalize_hops(transformations))
    if totals["added_measured_hops"] == 0.0:
        return math.nan
    if totals["added"] == 0.0:
        return 0.0
    return totals["unsupported_added"] / totals["added"]


def _binding_values(binding: Union[MessageClaimBinding, dict]) -> dict[str, Any]:
    if isinstance(binding, MessageClaimBinding):
        data: dict[str, Any] = binding.model_dump()
    elif isinstance(binding, dict):
        data = dict(binding)
    else:
        raise TypeError(
            "bindings must be MessageClaimBinding instances or fixture dicts, "
            f"got {type(binding).__name__}"
        )
    return data


def contradiction_rate(bindings: Any) -> float:
    """Fraction of contradiction-measured claim bindings that are contradictions.

    A contradiction is a *declared* relation between a derived claim and the
    source claim it negates. The frozen :class:`MessageClaimBinding` models the
    claim side, not this relation, so dict fixtures carry the marker
    (``contradicts_claim_id`` / ``contradicts_information_id`` /
    ``contradiction_of``). A bare contract binding carries no such marker and is
    therefore not contradiction-measured (the rate is NaN) rather than a
    fabricated zero.
    """
    items = (
        list(bindings)
        if not isinstance(bindings, (MessageClaimBinding, dict))
        else [bindings]
    )
    measured = 0
    marked = 0
    for item in items:
        data = _binding_values(item)
        if not any(key in data for key in _CONTRADICTION_MARKER_KEYS):
            continue  # not contradiction-measured (e.g. a bare contract binding)
        measured += 1
        if any(data.get(key) for key in _CONTRADICTION_MARKER_KEYS):
            marked += 1
    if measured == 0:
        return math.nan
    return marked / measured


def _contradiction_rate_hops(transformations: Any) -> float:
    """Contradiction fraction over hop source claim universes (report driver)."""
    totals = _totals(_normalize_hops(transformations))
    return _ratio(totals["contradicted"], totals["source"])


# ─────────────────────────────────────────────────────────────────────────────
# Top-level report
# ─────────────────────────────────────────────────────────────────────────────


def compute_fidelity_report(
    transformations: Any,
    *,
    source_information_id: Optional[str] = None,
) -> FidelityReport:
    """Compute a deterministic :class:`FidelityReport` over a lineage.

    ``transformations`` is an ordered collection of
    :class:`InformationTransformation` instances and/or fixture dicts (see the
    module docstring for the measurement-partition schema). When
    ``source_information_id`` is given, the measurement window is restricted to
    hops whose source information carries that id (the fidelity of content
    leaving a specific information object).
    """
    hops = _normalize_hops(transformations)
    if source_information_id is not None:
        hops = [
            hop
            for hop in hops
            if hop_source_information_id(hop) == source_information_id
        ]
    totals = _totals(hops)

    coverage = (
        totals["claim_measured_hops"] / totals["hop_count"]
        if totals["hop_count"]
        else 0.0
    )

    report = FidelityReport(
        claim_retention_rate=_ratio(totals["retained"], totals["source"]),
        citation_retention_rate=_ratio(
            totals["retained_citations"], totals["source_citations"]
        ),
        evidence_retention_rate=_ratio(
            totals["retained_evidence"], totals["source_evidence"]
        ),
        semantic_drift=_ratio(
            totals["meaning_changed"] + totals["contradicted"],
            totals["source"],
        ),
        omission_rate=_ratio(totals["omitted"], totals["source"]),
        unsupported_addition_rate=unsupported_addition_rate(hops),
        contradiction_rate=_contradiction_rate_hops(hops),
        claim_state=FIDELITY_CLAIM_STATE,
        confidence=round(coverage, 6),
        transformation_count=len(hops),
    )
    return report


__all__ = [
    "FACTUAL_BAND",
    "FIDELITY_CLAIM_STATE",
    "FidelityReport",
    "assert_derived_status",
    "citation_retention",
    "claim_retention",
    "compute_fidelity_report",
    "contradiction_rate",
    "evidence_retention",
    "omission_rate",
    "semantic_drift",
    "unsupported_addition_rate",
]
