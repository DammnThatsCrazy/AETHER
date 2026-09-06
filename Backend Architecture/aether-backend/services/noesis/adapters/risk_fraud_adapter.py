"""Noesis Risk360/Fraud360 read-only adapter — risk explain / fraud summarize /
risk-vs-fraud contradiction surfacing (Phase 6B of the Risk/Fraud 360 program).

Answers ``risk_assessment_explain`` (stored Risk360 assessments for a subject),
``fraud_hypothesis_summarize`` (stored Fraud360 hypotheses for a subject), and
``risk_fraud_contradiction_lookup`` (honest contradictions / gaps between a
subject's stored Risk360 assessment and its stored Fraud360 hypotheses).

Observation-only. Every method touches ONLY read/list paths on the
risk360/fraud360 stores (``RiskAssessmentRepository.list_by_subject`` /
``list_scoped`` and ``FraudHypothesisRepository.list``) and the declarative
``FRAUD_PATTERNS`` registry for display names. Noesis never creates, updates,
transitions, or relabels an assessment or hypothesis. Stored epistemic
vocabulary is reported verbatim: an unscored fraud dimension is rendered as its
recorded ``ValueState`` (``missing_inputs`` / ``insufficient_data`` / absent) —
never as a fabricated ``0`` and never as an invented contradiction.

Each method returns the standard adapter envelope::

    {"answer": str, "results": list, "sources": list, "sufficient": bool}

A read that raises returns ``sufficient=False`` with an honest answer rather
than crashing the conversation surface.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.risk_fraud")

#: Risk360 value states that genuinely carry a score. A ``missing_inputs`` /
#: ``insufficient_data`` / ``not_applicable`` / ``degraded`` component carries no
#: score and is honestly *not scored* (never coerced to a number).
_VALUE_BEARING_STATES = frozenset({"observed", "estimated"})

#: FraudHypothesis lifecycle phases at which the fraud plane is asserting enough
#: that the risk plane is expected to have corroborating scored data.
_MATERIAL_STATES = frozenset({"supported", "material", "investigating", "confirmed"})

#: Fraud360 risk dimension key on the Risk360 plane (RISK_DIMENSION_KEYS).
_FRAUD_DIMENSION = "fraud"


def _stringify(row: dict[str, Any]) -> dict[str, Any]:
    """Decimal-safe shallow copy — leaves ``None`` and other values untouched."""
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


def _subject_kind(target: str) -> str:
    """Derive the Risk360 subject kind from an id prefix when it encodes one.

    Defaults to ``entity`` for ids that carry no kind marker (or an unknown
    one) — the most common subject kind for risk/fraud subjects.
    """
    t = (target or "").strip().lower()
    if t.startswith(("rel_", "relationship", "rel-")):
        return "relationship"
    if t.startswith(("ag_", "agt_", "agent", "agent_")):
        return "agent"
    return "entity"


def _subject_label(subject_kind: str, subject_id: str) -> str:
    return f"{subject_kind}:{subject_id}"


def _as_dict(value: Any) -> dict[str, Any]:
    """Render a domain contract to a JSON-safe dict (enums become values)."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _evid_ids(refs: list[Any]) -> list[str]:
    out: list[str] = []
    for ref in refs or []:
        if isinstance(ref, dict):
            rid = ref.get("id")
        else:
            rid = getattr(ref, "id", None)
        if rid:
            out.append(str(rid))
    return out


class RiskFraudNoesisAdapter:
    """Deterministic, read-only lookups over the stored Risk360 assessment and
    Fraud360 hypothesis planes. ``target`` is a subject id (entity / relationship
    / agent); where it encodes kind it is honored, otherwise entity is assumed."""

    async def risk_assessment_explain(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from services.risk360.contracts import RiskAssessment
        from services.risk360.store import RiskAssessmentRepository

        repo = RiskAssessmentRepository()
        try:
            if target:
                kind = _subject_kind(target)
                rows = await repo.list_by_subject(tenant_id, kind, target, limit=limit)
                scope_note = f" for {_subject_label(kind, target)}"
            else:
                rows = await repo.list_scoped(tenant_id, limit=limit)
                scope_note = " in tenant scope (no subject targeted)"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis risk_assessment_explain read failed: %s", exc)
            return {
                "answer": "Risk360 assessments are temporarily unavailable.",
                "results": [],
                "sources": ["risk_assessments"],
                "sufficient": False,
            }

        if not rows:
            return {
                "answer": f"No stored Risk360 assessments found{scope_note}.",
                "results": [],
                "sources": ["risk_assessments"],
                "sufficient": False,
            }

        rendered: list[dict[str, Any]] = []
        parts: list[str] = [f"{len(rows)} stored Risk360 assessment(s){scope_note}"]
        for row in rows[:limit]:
            try:
                assessment = RiskAssessment(**row)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Noesis risk assessment row unreadable: %s", exc)
                continue
            row_data = _as_dict(assessment)
            row_subject = _subject_label(
                row_data.get("subject_kind") or "entity",
                row_data.get("subject_id") or target or "?",
            )
            components = row_data.get("vector", {}).get("components", [])
            scored = [
                c for c in components if c.get("state") in _VALUE_BEARING_STATES
            ]
            exposure = row_data.get("exposure") or {}
            exposed = exposure.get("exposed_asset_labels") or []
            econ = exposure.get("economic_value") or {}
            econ_txt = (
                f"{econ.get('amount')} {econ.get('currency')}"
                if econ.get("amount") is not None
                else "unpriced"
            )
            parts.append(
                f"assessment {assessment.assessment_id}: "
                f"claim_state={row_data.get('claim_state')}, "
                f"{len(scored)}/{len(components)} dimension(s) scored"
                f" ({', '.join(c['dimension'] for c in scored) or 'none'})"
            )
            if row_data.get("policy_id"):
                version = row_data.get("policy_version")
                parts.append(
                    f"  policy reference {row_data['policy_id']}"
                    + (f" (v{version})" if version else "")
                    + " — thresholds/outcome live in the decision policy, not in the stored assessment"
                )
            if exposure:
                parts.append(
                    "  exposure: "
                    + (f"assets {', '.join(exposed)}; " if exposed else "")
                    + f"economic value {econ_txt}"
                )
            rendered.append(
                {
                    "subject": row_subject,
                    "assessment_id": assessment.assessment_id,
                    "claim_state": row_data.get("claim_state"),
                    "confidence": row_data.get("confidence"),
                    "dimensions": row_data.get("dimensions", []),
                    "components": components,
                    "policy_id": row_data.get("policy_id"),
                    "policy_version": row_data.get("policy_version"),
                    "exposure": row_data.get("exposure"),
                    "evidence_ref_count": len(row_data.get("evidence_refs", [])),
                    "run_id": row_data.get("run_id"),
                }
            )

        return {
            "answer": "Risk360: " + " ".join(parts) + ".",
            "results": rendered,
            "sources": ["risk_assessments"],
            "sufficient": bool(rendered),
        }

    async def fraud_hypothesis_summarize(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from services.fraud360.patterns import fraud_pattern
        from services.fraud360.store import FraudHypothesisRepository

        repo = FraudHypothesisRepository()
        try:
            hypotheses = await repo.list(tenant_id, limit=max(limit * 4, 100))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis fraud_hypothesis_summarize read failed: %s", exc)
            return {
                "answer": "Fraud360 hypotheses are temporarily unavailable.",
                "results": [],
                "sources": ["fraud_hypotheses"],
                "sufficient": False,
            }

        if target:
            kind = _subject_kind(target)
            hypotheses = [
                h for h in hypotheses if h.subject_id == target
                and (_subject_kind(h.subject_id) == kind or h.subject_kind == kind)
            ]
            label = f" for {_subject_label(kind, target)}"
        else:
            label = " in tenant scope"

        hypotheses = hypotheses[:limit]
        if not hypotheses:
            return {
                "answer": f"No stored Fraud360 hypotheses found{label}.",
                "results": [],
                "sources": ["fraud_hypotheses"],
                "sufficient": False,
            }

        rendered: list[dict[str, Any]] = []
        per: list[str] = []
        for hyp in hypotheses:
            data = _as_dict(hyp)
            matched: list[str] = []
            families: set[str] = set()
            for pid in data.get("matched_pattern_ids", []):
                pattern = fraud_pattern(pid) if isinstance(pid, str) else None
                if pattern is not None:
                    matched.append(pattern.display_name)
                    families.add(pattern.family)
                else:
                    matched.append(pid)
            cross = {
                "risk_assessments": len(data.get("risk_assessment_ids", [])),
                "networks": len(data.get("network_ids", [])),
                "flow_traces": len(data.get("flow_trace_ids", [])),
                "decisions": len(data.get("decision_ids", [])),
            }
            contra_ids = _evid_ids(data.get("contradictory_evidence_refs"))
            evidence_ids = _evid_ids(data.get("evidence_refs"))
            materiality = data.get("materiality")
            per.append(
                f"hypothesis {hyp.hypothesis_id}: state={data.get('state')} "
                f"claim_state={data.get('claim_state')} "
                f"patterns=[{', '.join(matched) or 'none'}]"
                + (f" materiality={materiality}" if materiality is not None else "")
                + (
                    f" contradictory_evidence={len(contra_ids)}"
                    if contra_ids
                    else ""
                )
            )
            rendered.append(
                {
                    "subject": _subject_label(hyp.subject_kind, hyp.subject_id),
                    "hypothesis_id": hyp.hypothesis_id,
                    "state": data.get("state"),
                    "claim_state": data.get("claim_state"),
                    "confidence": data.get("confidence"),
                    "matched_patterns": matched,
                    "families": sorted(families),
                    "materiality": materiality,
                    "supporting_evidence_ids": evidence_ids,
                    "contradictory_evidence_ids": contra_ids,
                    "cross_refs": cross,
                    "run_id": data.get("run_id"),
                }
            )

        answer = (
            f"Fraud360: {len(rendered)} stored hypothesis(es){label}."
            + (" ".join(f" {p}." for p in per))
        )
        return {
            "answer": answer,
            "results": rendered,
            "sources": ["fraud_hypotheses"],
            "sufficient": bool(rendered),
        }

    async def contradiction_surface(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Surface HONEST contradictions / gaps between a subject's stored Risk360
        assessment and its stored Fraud360 hypotheses.

        A genuine item is produced only when the stored records support it —
        never invented:

        * ``recorded_contradiction`` — the fraud plane itself records
          ``contradictory_evidence_refs`` alongside supporting refs.
        * ``unsupported_fraud_claim`` (gap) — a material / confirmed hypothesis
          for a subject whose stored assessment has no *scored* ``fraud``
          dimension (``missing_inputs`` / ``insufficient_data`` / absent). The
          gap is named honestly, not asserted as proof the hypothesis is wrong.
        """
        from services.risk360.contracts import RiskAssessment
        from services.risk360.store import RiskAssessmentRepository
        from services.fraud360.store import FraudHypothesisRepository

        if not target:
            return {
                "answer": "Which subject (entity, relationship, or agent id) should I reconcile?",
                "results": [],
                "sources": ["risk_assessments", "fraud_hypotheses"],
                "sufficient": False,
            }

        kind = _subject_kind(target)
        label = _subject_label(kind, target)

        try:
            assessment_rows = await RiskAssessmentRepository().list_by_subject(
                tenant_id, kind, target, limit=50
            )
            hypotheses = await FraudHypothesisRepository().list(tenant_id, limit=200)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Noesis contradiction_surface read failed: %s", exc)
            return {
                "answer": "Risk360/Fraud360 contradiction surfacing is temporarily unavailable.",
                "results": [],
                "sources": ["risk_assessments", "fraud_hypotheses"],
                "sufficient": False,
            }

        subject_hypotheses = [
            h for h in hypotheses
            if h.subject_id == target and h.subject_kind == kind
        ][:limit]

        assessments: list[Any] = []
        for row in assessment_rows:
            try:
                assessments.append(RiskAssessment(**row))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Noesis risk assessment row unreadable: %s", exc)

        # Has ANY stored assessment for this subject scored the fraud dimension?
        has_scored_fraud = False
        for assessment in assessments:
            data = _as_dict(assessment)
            for comp in data.get("vector", {}).get("components", []):
                if (
                    comp.get("dimension") == _FRAUD_DIMENSION
                    and comp.get("state") in _VALUE_BEARING_STATES
                ):
                    has_scored_fraud = True

        if not subject_hypotheses:
            return {
                "answer": (
                    f"No stored Fraud360 hypotheses for {label}; "
                    "nothing to reconcile against the Risk360 plane."
                ),
                "results": [],
                "sources": ["risk_assessments", "fraud_hypotheses"],
                "sufficient": False,
            }

        items: list[dict[str, Any]] = []
        for hyp in subject_hypotheses:
            data = _as_dict(hyp)
            state = str(data.get("state") or "")
            contra_ids = _evid_ids(data.get("contradictory_evidence_refs"))
            support_ids = _evid_ids(data.get("evidence_refs"))

            if contra_ids:
                items.append(
                    {
                        "subject": _subject_label(hyp.subject_kind, hyp.subject_id),
                        "hypothesis_id": hyp.hypothesis_id,
                        "kind": "recorded_contradiction",
                        "note": (
                            f"Hypothesis {hyp.hypothesis_id} itself records "
                            f"{len(contra_ids)} contradictory evidence ref(s) "
                            f"({', '.join(contra_ids)}) alongside "
                            f"{len(support_ids)} supporting ref(s)."
                        ),
                        "contradictory_evidence_ids": contra_ids,
                        "supporting_evidence_ids": support_ids,
                    }
                )

            if state in _MATERIAL_STATES and not has_scored_fraud:
                if not assessments:
                    note = (
                        f"Hypothesis {hyp.hypothesis_id} is '{state}' (a material/"
                        "confirmed fraud assertion) but no Risk360 assessment is "
                        f"stored for {label} to corroborate it."
                    )
                else:
                    note = (
                        f"Hypothesis {hyp.hypothesis_id} is '{state}' but the "
                        f"stored Risk360 assessment(s) for {label} carry no scored "
                        "'fraud' dimension (missing_inputs / insufficient_data / "
                        "absent) — the fraud claim is not yet corroborated by the "
                        "risk plane."
                    )
                items.append(
                    {
                        "subject": label,
                        "hypothesis_id": hyp.hypothesis_id,
                        "kind": "unsupported_fraud_claim",
                        "note": note,
                    }
                )

        if not items:
            return {
                "answer": (
                    f"No contradictions or gaps surfaced between the stored "
                    f"Risk360 assessment(s) and Fraud360 hypotheses for {label}."
                ),
                "results": [],
                "sources": ["risk_assessments", "fraud_hypotheses"],
                "sufficient": True,
            }

        kinds = sorted({item["kind"] for item in items})
        return {
            "answer": (
                f"Contradiction surface for {label}: {len(items)} honest "
                f"item(s) ({', '.join(kinds)}). "
                + " ".join(item["note"] for item in items)
            ),
            "results": items,
            "sources": ["risk_assessments", "fraud_hypotheses"],
            "sufficient": True,
        }


__all__ = ["RiskFraudNoesisAdapter"]
