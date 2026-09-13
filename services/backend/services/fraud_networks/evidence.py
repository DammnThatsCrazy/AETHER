"""Fraud Network Intelligence — evidence builder.

Converts raw detector results and repo data into EvidenceRef objects
compatible with the existing operational_intelligence.models.EvidenceRef type.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from services.fraud_networks.detectors import EvidenceTuple
from services.operational_intelligence.models import EvidenceRef


_SIGNAL_TO_EVIDENCE_TYPE = {
    "shared_device": "relationship",
    "shared_ip": "relationship",
    "shared_wallet": "relationship",
    "circular_transfer": "transaction",
    "split_merge": "transaction",
    "reward_farming": "transaction",
    "agentic_delegation_abuse": "relationship",
    "commerce_abuse": "transaction",
}

_SIGNAL_TO_SOURCE = {
    "shared_device": "aether.fraud.detector.device",
    "shared_ip": "aether.fraud.detector.ip",
    "shared_wallet": "aether.fraud.detector.wallet",
    "circular_transfer": "aether.fraud.detector.circular",
    "split_merge": "aether.fraud.detector.split_merge",
    "reward_farming": "aether.fraud.detector.reward_farming",
    "agentic_delegation_abuse": "aether.fraud.detector.delegation",
    "commerce_abuse": "aether.fraud.detector.commerce",
}

_SIGNAL_CONFIDENCE = {
    "shared_device": 0.85,
    "shared_ip": 0.65,
    "shared_wallet": 0.90,
    "circular_transfer": 0.92,
    "split_merge": 0.80,
    "reward_farming": 0.70,
    "agentic_delegation_abuse": 0.78,
    "commerce_abuse": 0.72,
}


def build_evidence_refs(
    detector_results: list[EvidenceTuple],
    network_id: str,
    tenant_id: str,
    observed_at: str | None = None,
) -> list[EvidenceRef]:
    """Convert a list of detector evidence tuples to EvidenceRef objects.

    Args:
        detector_results: list of (signal_name, entity_ids, detail_dict) tuples
                          from any detector function.
        network_id: the ID of the fraud network these refs belong to.
        tenant_id: the tenant owning the network.
        observed_at: ISO timestamp; defaults to current UTC time.

    Returns:
        A list of EvidenceRef objects, one per detector result.
    """
    if observed_at is None:
        observed_at = datetime.now(timezone.utc).isoformat()

    refs: list[EvidenceRef] = []
    for signal_name, entity_ids, detail in detector_results:
        evidence_type = _SIGNAL_TO_EVIDENCE_TYPE.get(signal_name, "model_output")
        source = _SIGNAL_TO_SOURCE.get(signal_name, "aether.fraud.detector.unknown")
        confidence = _SIGNAL_CONFIDENCE.get(signal_name, 0.60)

        # URI encodes the context for the evidence (not a real URL — internal ref)
        uri = (
            f"aether://fraud-networks/{network_id}/evidence"
            f"?signal={signal_name}"
            f"&entities={','.join(sorted(entity_ids))}"
        )

        refs.append(EvidenceRef(
            id=str(uuid.uuid4()),
            type=evidence_type,
            source=source,
            observedAt=observed_at,
            confidence=confidence,
            uri=uri,
        ))
    return refs
