"""SDK event -> touchpoint row: actor evidence end to end.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector


def _row(context: dict | None = None, **top: object) -> dict:
    event = {
        "type": "page",
        "messageId": "evt-actor-1",
        "timestamp": "2026-11-16T12:00:00Z",
        "context": {"tenantId": "tenant-a", **(context or {})},
        "properties": {},
        **top,
    }
    result = TouchpointProjector().project(event)
    assert result is not None and result.rows
    return result.rows[0]


def test_no_actor_evidence_is_unknown() -> None:
    assert _row()["actor_type"] == "unknown"


def test_webdriver_flag_is_machine_with_auditable_evidence() -> None:
    row = _row({"device": {"automation": {"webdriver": True, "trustedInputSeen": False}}})
    assert row["actor_type"] == "machine"
    assert "actor:webdriver_flag" in row["provenance"]["source_evidence_signals"]
    assert "actor:webdriver_flag" in row["source_classification_evidence"]["signals"]


def test_webdriver_false_is_not_evidence_of_a_human() -> None:
    row = _row({"device": {"automation": {"webdriver": False, "trustedInputSeen": True}}})
    assert row["actor_type"] == "unknown"


def test_declared_agent_beats_webdriver_flag() -> None:
    row = _row({"agentId": "agt_1", "device": {"automation": {"webdriver": True}}})
    assert row["actor_type"] == "agent"


def test_server_verified_agent_is_platform_verified() -> None:
    row = _row(
        {"userAgent": "Mozilla/5.0 ChatGPT-User/1.0"},
        server_context={"agent_verification": {"ua_signature": "chatgpt-user", "verification": "provider_ip_range"}},
    )
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "platform_verified"
    assert row["verification_level"] == "provider_ip_range"


def test_payload_only_agent_claim_is_declared() -> None:
    row = _row({"userAgent": "Mozilla/5.0 ChatGPT-User/1.0"})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "declared"
