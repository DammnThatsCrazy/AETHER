"""Source-authority rules for x402 lifecycle records.

Public SDK events are useful observations, but they cannot establish payment
value or settlement state. Only the closed server event registry promotes
these records to server-observed economic evidence.

Aether is observation-only (ADR-012). The only live authority is the x402
settlement observer, which verifies a reported payment on-chain. The former
commerce control plane (challenge, submission, settlement tracker, access
grant) no longer exists; its producers stay in ``HISTORICAL_X402_SOURCES`` so
records it wrote before retirement are still recognised as server-observed.
"""

from __future__ import annotations

from typing import Any


AUTHORITATIVE_X402_SOURCES = {
    "aether.commerce.settlement.completed": ("x402.settlement_observer", "x402_payment_settled"),
    "aether.commerce.settlement.failed": ("x402.settlement_observer", "x402_payment_failed"),
}

# Producers of the retired commerce control plane. Read-only compatibility for
# records written before ADR-012; no live consumer accepts these producers.
HISTORICAL_X402_SOURCES = {
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
    accepted = {
        entry[0]
        for registry in (AUTHORITATIVE_X402_SOURCES, HISTORICAL_X402_SOURCES)
        if (entry := registry.get(topic)) is not None
    }
    return (
        metadata.get("evidence_status") == "server_observed"
        and source_service in accepted
    )


def is_public_sdk_x402_metadata(metadata: Any) -> bool:
    return isinstance(metadata, dict) and (
        metadata.get("source_authority") == "public_sdk_observation"
        or metadata.get("source_kind") == "public_sdk"
    )
