from aether_agentic import capture_a2a_caller_identity, capture_mcp_client_identity
from aether_agentic.protocol_identity import sha256_hex


def test_mcp_verified_client_hashes_subject():
    ev = capture_mcp_client_identity(
        client_info={"name": "claude-ai", "version": "0.1.0"},
        oauth_verified=True, client_id="client_123", issuer="https://auth.example",
        scopes=["tools:read"], subject="user-42",
    )
    assert ev == {"protocol": "mcp", "mcp": {
        "clientInfo": {"name": "claude-ai", "version": "0.1.0"},
        "oauth": {"verified": True, "clientId": "client_123", "issuer": "https://auth.example",
                  "scopes": ["tools:read"], "subjectHash": sha256_hex("user-42")},
    }}
    assert "user-42" not in str(ev)


def test_mcp_unverified_is_declaration_only():
    ev = capture_mcp_client_identity(client_info={"name": "cursor"}, client_id="ignored")
    assert ev == {"protocol": "mcp", "mcp": {"clientInfo": {"name": "cursor"}}}


def test_a2a_keeps_identity_fields_only():
    ev = capture_a2a_caller_identity(
        agent_card={"name": "Travel Agent", "url": "https://agent.example/a2a",
                    "provider": {"organization": "Example Co"}, "skills": [{"id": "x"}]},
        authenticated=True, auth_scheme="oauth2",
    )
    assert ev == {"protocol": "a2a", "a2a": {
        "agentCard": {"name": "Travel Agent", "url": "https://agent.example/a2a",
                      "provider": {"organization": "Example Co"}},
        "authenticated": True, "authScheme": "oauth2",
    }}
