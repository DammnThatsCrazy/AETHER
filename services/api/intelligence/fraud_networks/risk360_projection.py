"""Project exact agentic fraud-network detections into canonical Risk360 rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from graph.operational_intelligence.models import EvidenceRef
from intelligence.fraud_networks.detectors import EvidenceTuple
from intelligence.risk360.pipeline import compute_assessment, persist_assessment
from intelligence.risk360.signals import (
    FraudNetworkSignalEvidence,
    signals_from_fraud_network_evidence,
)


def _parse_observed_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


async def persist_agentic_delegation_assessments(
    *,
    tenant_id: str,
    detector_results: Sequence[EvidenceTuple],
    evidence_refs: Sequence[EvidenceRef],
    observed_at: str,
    agent_identity_reader: Optional[Any] = None,
) -> int:
    """Persist inferred agent Risk360 assessments after canonical attribution.

    Fraud-network detector IDs are source references until Agent360 resolves
    them through tenant-owned deployment namespaces and explicit bindings.
    Risk360 rows are written only against the resolved canonical Agent entity.
    Each RiskSignal retains both network evidence and the identity-binding
    evidence; link evidence still does not create a score, exposure amount, or
    contagion claim. Unresolved, ambiguous, truncated, or cross-scope reads are
    omitted instead of being persisted under a source ID.
    """
    assessed_at = _parse_observed_at(observed_at)
    if assessed_at is None:
        return 0

    by_agent: dict[str, list[FraudNetworkSignalEvidence]] = {}
    for index, result in enumerate(detector_results):
        if index >= len(evidence_refs):
            continue
        signal_name, entity_ids, detail = result
        if signal_name != "agentic_delegation_abuse" or not isinstance(detail, dict):
            continue
        agent_id = detail.get("agent_id")
        evidence_ref = evidence_refs[index]
        if (
            not isinstance(agent_id, str)
            or not agent_id.strip()
            or not evidence_ref.id.strip()
            or not evidence_ref.source.strip()
        ):
            continue
        by_agent.setdefault(agent_id, []).append(
            FraudNetworkSignalEvidence(
                signal_name=signal_name,
                entity_ids=list(entity_ids),
                detail=dict(detail),
                evidence_ref=evidence_ref,
            )
        )

    persisted = 0
    if agent_identity_reader is None:
        from actions.agent.agent360_provider import RepositoryAgent360Source

        agent_identity_reader = RepositoryAgent360Source()

    for source_agent_ref, evidence in sorted(by_agent.items()):
        identity_read = await agent_identity_reader.actor_identity(tenant_id, source_agent_ref)
        if identity_read.truncated or identity_read.scope_mismatch:
            continue
        identity_rows = [
            row
            for row in identity_read.rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("agent_id") == source_agent_ref
            and isinstance(row.get("canonical_agent_entity_id"), str)
            and row.get("canonical_agent_entity_id")
        ]
        canonical_ids = {row["canonical_agent_entity_id"] for row in identity_rows}
        if len(canonical_ids) != 1:
            continue
        agent_id = next(iter(canonical_ids))
        binding_evidence = {
            (row.get("identity_evidence_source"), row.get("identity_evidence_id"))
            for row in identity_rows
            if row.get("canonical_agent_entity_id") == agent_id
            and isinstance(row.get("identity_evidence_source"), str)
            and row.get("identity_evidence_source")
            and isinstance(row.get("identity_evidence_id"), str)
            and row.get("identity_evidence_id")
        }
        if len(binding_evidence) != 1:
            continue
        identity_source, identity_id = next(iter(binding_evidence))
        binding_rows = [
            row
            for row in identity_rows
            if row.get("canonical_agent_entity_id") == agent_id
            and row.get("identity_evidence_source") == identity_source
            and row.get("identity_evidence_id") == identity_id
        ]
        binding_times = [
            _parse_observed_at(row.get("identity_bound_at")) for row in binding_rows
        ]
        # A current identity binding must not retroactively attribute a detector
        # observation that predates the binding. Missing, malformed, naive, or
        # conflicting binding times cannot establish that historical join.
        if (
            not binding_times
            or any(bound_at is None for bound_at in binding_times)
            or len(set(binding_times)) != 1
        ):
            continue
        identity_bound_at = binding_times[0]
        if identity_bound_at is None or identity_bound_at > assessed_at:
            continue
        identity_ref = EvidenceRef(
            id=identity_id,
            type="entity",
            source=identity_source,
            observedAt=identity_bound_at.isoformat(),
            uri=f"store://agent_identity_bindings/{identity_id}",
        )
        signals = signals_from_fraud_network_evidence(
            evidence,
            subject_kind="agent",
            subject_id=agent_id,
            tenant_id=tenant_id,
            observed_at=assessed_at,
        )
        if not signals:
            continue
        signals = [
            signal.model_copy(update={"evidence_refs": [*signal.evidence_refs, identity_ref]})
            for signal in signals
        ]
        result = compute_assessment(
            tenant_id=tenant_id,
            subject_kind="agent",
            subject_id=agent_id,
            signals=signals,
            observed_at=assessed_at,
        )
        await persist_assessment(result, tenant_id=tenant_id, signals=signals)
        persisted += 1
    return persisted


__all__ = ["persist_agentic_delegation_assessments"]
