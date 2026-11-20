"""MCP / A2A agent identity: grading, ingestion stripping, classification.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from journeys.traffic.protocol_identity import evaluate_agent_protocol

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "sdk", "python"))
)
from aether_agentic import capture_a2a_caller_identity, capture_mcp_client_identity  # noqa: E402

SUB_HASH = hashlib.sha256(b"user-42").hexdigest()


def test_verified_mcp_oauth_client() -> None:
    v = evaluate_agent_protocol(capture_mcp_client_identity(
        client_info={"name": "claude-ai", "version": "0.1"}, oauth_verified=True,
        client_id="client_123", issuer="https://auth.example/path", scopes=["tools:read"], subject="user-42",
    ))
    assert v["verification"] == "mcp_oauth_client"
    assert v["provider"] == "anthropic" and v["product"] == "claude"
    assert v["oauth_client_id"] == "client_123"
    assert v["oauth_issuer"] == "https://auth.example/path"  # full issuer, not just the origin
    assert v["principal_subject_hash"] == SUB_HASH
    assert v["observed_by"] == "tenant_server"


def _issuer_of(issuer: str) -> str:
    return evaluate_agent_protocol(capture_mcp_client_identity(
        client_info={"name": "claude-ai"}, oauth_verified=True, client_id="c",
        issuer=issuer, subject="user-42",
    ))["oauth_issuer"]


def test_issuers_sharing_an_origin_stay_distinct() -> None:
    one = _issuer_of("https://Auth.Example/realms/one/")
    two = _issuer_of("https://auth.example/realms/two")
    assert one == "https://auth.example/realms/one"
    assert two == "https://auth.example/realms/two"
    assert one != two
    assert _issuer_of("https://auth.example/realms/one?x=1#f") == one  # query/fragment ignored


def test_oversized_issuer_is_bounded_but_not_collapsed() -> None:
    a = _issuer_of("https://auth.example/" + "a" * 400)
    b = _issuer_of("https://auth.example/" + "b" * 400)
    assert a.startswith("https://auth.example/#sha256=") and len(a) <= 200
    assert a != b


def test_mcp_client_info_alone_is_declared_and_drops_oauth_fields() -> None:
    raw = {"protocol": "mcp", "mcp": {"clientInfo": {"name": "Cursor"},
                                     "oauth": {"verified": False, "clientId": "c", "subjectHash": SUB_HASH}}}
    v = evaluate_agent_protocol(raw)
    assert v["verification"] == "mcp_client_info_declared"
    assert v["oauth_client_id"] is None and v["principal_subject_hash"] is None
    assert v["provider"] == "anysphere"


def test_raw_subject_is_never_accepted_as_hash() -> None:
    raw = {"protocol": "mcp", "mcp": {"clientInfo": {"name": "x"},
                                     "oauth": {"verified": True, "clientId": "c", "subjectHash": "user-42"}}}
    assert evaluate_agent_protocol(raw)["principal_subject_hash"] is None


@pytest.mark.parametrize(
    ("kwargs", "verification"),
    [
        ({"authenticated": True, "card_signature_verified": True}, "a2a_authenticated_signed_card"),
        ({"authenticated": True}, "a2a_authenticated"),
        ({}, "a2a_agent_card_declared"),
        ({"card_signature_verified": True}, "a2a_agent_card_declared"),
    ],
)
def test_a2a_grades(kwargs: dict, verification: str) -> None:
    card = {"name": "Travel Agent", "url": "https://agent.example/a2a",
            "provider": {"organization": "Example Co", "url": "https://example.com"}}
    v = evaluate_agent_protocol(capture_a2a_caller_identity(agent_card=card, **kwargs))
    assert v["verification"] == verification
    assert v["agent_url"] == "https://agent.example"


def test_a2a_card_from_another_origin_never_reaches_signed_grade() -> None:
    v = evaluate_agent_protocol(capture_a2a_caller_identity(
        agent_card={"name": "A", "url": "https://agent.example/a2a"},
        agent_card_url="https://evil.example/.well-known/agent-card.json",
        authenticated=True, card_signature_verified=True,
    ))
    assert v["verification"] == "a2a_authenticated"
    assert v["origin_consistent"] is False


@pytest.mark.parametrize("raw", [None, {}, {"protocol": "mcp"}, {"protocol": "mcp", "mcp": {}},
                                 {"protocol": "a2a", "a2a": {"agentCard": {}}}, {"protocol": "x", "x": {}}])
def test_nothing_identifiable(raw) -> None:
    assert evaluate_agent_protocol(raw) is None


def test_ingestion_replaces_raw_with_verdict() -> None:
    from ingestion.ingestion.batch import EventContext, _apply_agent_protocol_identity

    raw = capture_mcp_client_identity(client_info={"name": "claude-ai"}, oauth_verified=True,
                                      client_id="client_123", subject="user-42")
    EventContext(agentProtocol=raw)  # accepted by the strict context model
    normalized = {"context": {"agentProtocol": raw}}
    _apply_agent_protocol_identity(normalized)
    assert "agentProtocol" not in normalized["context"]
    assert normalized["server_context"]["agent_protocol"]["verification"] == "mcp_oauth_client"
    assert "user-42" not in json.dumps(normalized)


def _project(server_context: dict, context: dict | None = None) -> dict:
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    result = TouchpointProjector().project({
        "type": "page", "messageId": "evt-proto-1", "timestamp": "2026-11-19T12:00:00Z",
        "context": {"tenantId": "tenant-a", **(context or {})},
        "properties": {}, "server_context": server_context,
    })
    return result.rows[0]


def test_mcp_oauth_client_classified_as_server_observed_agent() -> None:
    v = evaluate_agent_protocol(capture_mcp_client_identity(
        client_info={"name": "claude-ai"}, oauth_verified=True, client_id="client_123"))
    row = _project({"agent_protocol": v})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "server_observed"
    assert row["verification_level"] == "mcp_oauth_client"
    assert row["ai_provider"] == "anthropic"


def test_declared_a2a_caller_is_declared_agent() -> None:
    v = evaluate_agent_protocol(capture_a2a_caller_identity(agent_card={"name": "Bot", "url": "https://b.example"}))
    row = _project({"agent_protocol": v})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "declared"


def test_verified_web_bot_auth_outranks_protocol_identity() -> None:
    row = _project({
        "web_bot_auth": {"verification": "web_bot_auth_verified", "signature_agent": "https://chatgpt.com",
                         "provider": "openai", "product": "chatgpt", "actor_type": "agent"},
        "agent_protocol": {"protocol": "mcp", "verification": "mcp_client_info_declared",
                           "provider": None, "product": "x"},
    })
    assert row["verification_level"] == "web_bot_auth"
