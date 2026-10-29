"""Agent behavior → Risk360 signals (WO-093).

Risk owns classification; behavior intelligence only supplies evidence
(anti-pattern: risk logic embedded in behavior projectors). Each adapter turns
one behavior artifact into canonical :class:`RiskSignal`s on a registered
dimension with an honest claim state. Heuristic rates carry no calibrated
score (``score=None``); confidence comes from the behavior confidence envelope.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from graph.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus

from .contracts import RiskSignal
from .signals import _evidence_id, _signal_id

SOURCE = "agent_behavior"
DETECTOR_VERSION = "agent_behavior_model/1"


def _refs(event_ids: Iterable[str], kind: str = "event") -> list[EvidenceRef]:
    return [EvidenceRef(id=_evidence_id("agent_behavior", event_id=e), type=kind, source=f"silver_agent_execution_facts:{e}")
            for e in list(event_ids)[:25]]


def _signal(tenant_id: str, agent_ref: str, dimension: str, kind: str, claim: EpistemicStatus,
            evidence: Iterable[str], confidence: Optional[float] = None, value: Optional[float] = None,
            ) -> RiskSignal:
    evidence = list(evidence)
    return RiskSignal(
        signal_id=_signal_id(producer=SOURCE, tenant=tenant_id, agent=agent_ref, kind=kind, evidence=sorted(evidence)),
        tenant_id=tenant_id, subject_kind="agent", subject_id=agent_ref, risk_dimension=dimension,
        claim_state=claim, confidence=confidence, evidence_refs=_refs(evidence), source=f"{SOURCE}.{kind}",
        detector_version=DETECTOR_VERSION, score=None, value=value,
    )


def signals_from_authority_checks(tenant_id: str, agent_ref: str,
                                  checks: Iterable[dict[str, Any]]) -> list[RiskSignal]:
    """``outside`` boundary checks are observed against recorded grants."""
    out = []
    for chk in checks:
        if chk.get("status") != "outside":
            continue
        out.append(_signal(tenant_id, agent_ref, "agentic", "authority_boundary_exceeded",
                           EpistemicStatus.OBSERVED, chk.get("evidence") or []))
    return out


def signals_from_behavior_model(tenant_id: str, model: dict[str, Any]) -> list[RiskSignal]:
    agent = model["agent_ref"]
    feats = model["features"]
    out: list[RiskSignal] = []
    denial = feats.get("authority_denial_rate") or {}
    if denial.get("value") is not None and denial["value"] >= 0.5:
        out.append(_signal(tenant_id, agent, "agentic", "repeated_authority_denials", EpistemicStatus.DERIVED,
                           denial.get("evidence", []), confidence=denial["interval"][0], value=denial["value"]))
    stale = (feats.get("memory_reuse") or {}).get("stale_use", 0)
    if stale:
        ev = [e for m in model.get("memory", []) for e in m.get("evidence", [])]
        out.append(_signal(tenant_id, agent, "data_quality", "stale_memory_use", EpistemicStatus.DERIVED,
                           ev, value=float(stale)))
    tool = feats.get("tool_success_rate") or {}
    if tool.get("value") is not None and tool["value"] < 0.5:
        out.append(_signal(tenant_id, agent, "execution", "low_tool_success", EpistemicStatus.DERIVED,
                           tool.get("evidence", []), confidence=tool["interval"][0], value=tool["value"]))
    return out


def signals_from_drift(tenant_id: str, agent_ref: str, drift: dict[str, Any]) -> list[RiskSignal]:
    if drift.get("status") != "drift_detected":
        return []
    ev = [e for d in drift.get("dimensions", []) for e in d.get("evidence", [])]
    return [_signal(tenant_id, agent_ref, "behavioral", "behavior_drift", EpistemicStatus.INFERRED, ev,
                    confidence=drift.get("confidence"))]


def signals_from_discontinuity(tenant_id: str, agent_ref: str, finding: dict[str, Any]) -> list[RiskSignal]:
    if finding.get("status") != "discontinuity_suspected":
        return []
    return [_signal(tenant_id, agent_ref, "identity", "behavioral_identity_discontinuity",
                    EpistemicStatus.INFERRED, finding.get("evidence", []), confidence=finding.get("confidence"))]


def signals_from_adversarial(tenant_id: str, agent_ref: str, findings: Iterable[dict[str, Any]]) -> list[RiskSignal]:
    return [_signal(tenant_id, agent_ref, "security", f"adversarial_{f['kind']}",
                    EpistemicStatus.OBSERVED if f.get("basis") == "observed" else EpistemicStatus.INFERRED,
                    f.get("evidence", []), confidence=f.get("confidence"))
            for f in findings]
