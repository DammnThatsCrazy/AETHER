"""Source-authority rules for x402 lifecycle records.

Public SDK events are useful observations, but they cannot establish payment
value or settlement state. Only the closed server commerce event registry
promotes these records to server-observed economic evidence.
"""

from __future__ import annotations

from typing import Any


AUTHORITATIVE_X402_SOURCES = {
    "aether.commerce.challenge.issued": ("x402.control_plane", "x402_payment_required"),
    "aether.commerce.payment.submitted": ("x402.control_plane", "x402_payment_submitted"),
    "aether.commerce.settlement.completed": ("x402.settlement", "x402_payment_settled"),
    "aether.commerce.settlement.failed": ("x402.settlement", "x402_payment_failed"),
    "aether.commerce.access.granted": ("x402.control_plane", "x402_access_granted"),
}


def is_server_authoritative_x402_metadata(metadata: Any) -> bool:
    """Accept only the closed server commerce provenance written by ingestion."""
    if not isinstance(metadata, dict):
        return False
    if metadata.get("source_authority") == "x402_commerce":
        return True
    # Compatibility for records written before source_authority was added.
    topic = metadata.get("source_topic")
    source_service = metadata.get("source_service")
    expected = AUTHORITATIVE_X402_SOURCES.get(topic)
    return (
        metadata.get("evidence_status") == "server_observed"
        and expected is not None
        and source_service == expected[0]
    )


def is_public_sdk_x402_metadata(metadata: Any) -> bool:
    return isinstance(metadata, dict) and (
        metadata.get("source_authority") == "public_sdk_observation"
        or metadata.get("source_kind") == "public_sdk"
    )
