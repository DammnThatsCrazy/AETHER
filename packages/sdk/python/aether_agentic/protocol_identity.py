"""Agent identity from agent protocols (MCP, A2A) for ``context["agentProtocol"]``.

Mirrors ``captureMcpClientIdentity`` / ``captureA2aCallerIdentity`` in the Node
server SDK. Tokens are never sent; the OAuth subject is SHA-256-hashed here;
only identity fields of an Agent Card are kept. Aether grades the result as
observed by your server.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional, Sequence

_MAX = 256


def _s(value: Any, limit: int = _MAX) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _prune(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if v is not None and v != {}}


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def capture_mcp_client_identity(
    *,
    client_info: Optional[Mapping[str, Any]] = None,
    protocol_version: Optional[str] = None,
    oauth_verified: bool = False,
    client_id: Optional[str] = None,
    issuer: Optional[str] = None,
    scopes: Optional[Sequence[str]] = None,
    subject: Optional[str] = None,
) -> dict[str, Any]:
    """Build MCP client identity.

    Set ``oauth_verified=True`` only when your auth layer validated the bearer
    token; ``client_id``/``issuer``/``scopes``/``subject`` come from that
    validated token. ``subject`` is hashed before it leaves this function.
    """
    info = client_info or {}
    cid = _s(client_id)
    oauth = None
    if oauth_verified:
        oauth = _prune({
            "verified": cid is not None,
            "clientId": cid,
            "issuer": _s(issuer, 2048),
            "scopes": [x for x in (scopes or []) if isinstance(x, str)][:32] or None,
            "subjectHash": sha256_hex(subject) if _s(subject) else None,
        })
    mcp = _prune({
        "clientInfo": _prune({"name": _s(info.get("name")), "version": _s(info.get("version"), 64)}),
        "protocolVersion": _s(protocol_version, 32),
        "oauth": oauth,
    })
    return {"protocol": "mcp", "mcp": mcp}


def capture_a2a_caller_identity(
    *,
    agent_card: Optional[Mapping[str, Any]] = None,
    agent_card_url: Optional[str] = None,
    authenticated: bool = False,
    card_signature_verified: bool = False,
    auth_scheme: Optional[str] = None,
) -> dict[str, Any]:
    """Build A2A caller identity from the caller's Agent Card and your auth result."""
    card = agent_card or {}
    provider = card.get("provider") if isinstance(card.get("provider"), Mapping) else {}
    a2a = _prune({
        "agentCard": _prune({
            "name": _s(card.get("name")),
            "url": _s(card.get("url"), 2048),
            "version": _s(card.get("version"), 64),
            "protocolVersion": _s(card.get("protocolVersion"), 32),
            "provider": _prune({
                "organization": _s(provider.get("organization")),
                "url": _s(provider.get("url"), 2048),
            }),
        }),
        "agentCardUrl": _s(agent_card_url, 2048),
        "authenticated": True if authenticated else None,
        "cardSignatureVerified": True if card_signature_verified else None,
        "authScheme": _s(auth_scheme, 64),
    })
    return {"protocol": "a2a", "a2a": a2a}


__all__ = ["capture_a2a_caller_identity", "capture_mcp_client_identity", "sha256_hex"]
