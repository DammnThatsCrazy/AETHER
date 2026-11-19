"""Grade agent identity evidence from agent protocols: MCP and A2A.

A customer's MCP server or A2A agent knows who is calling it far better than
any browser signal: the MCP ``initialize`` handshake names the client
(``clientInfo``), MCP authorization identifies it with an OAuth ``client_id``,
and an A2A caller presents an Agent Card and authenticates with the scheme the
card declares. The server SDK helpers (``captureMcpClientIdentity`` /
``captureA2aCallerIdentity``) forward that as ``context.agentProtocol``.

Grading — the evidence was observed by the tenant's server, so nothing here is
``platform_verified``:

- MCP OAuth client authenticated by the tenant's server -> ``server_observed``
- A2A caller authenticated by the tenant's server -> ``server_observed``
  (higher confidence when the tenant also verified the Agent Card signature)
- MCP ``clientInfo`` or an A2A Agent Card alone -> ``declared``

Privacy: tokens are never accepted, the OAuth subject arrives SHA-256-hashed
from the SDK, and only identity fields of an Agent Card are kept.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlsplit

OBSERVED_BY = "tenant_server"
_MAX = 256
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

#: Well-known MCP client / A2A provider names -> (ai_provider, ai_product).
#: Matched as lower-case substrings of the declared name; unknown names keep
#: the declared name as the product and no provider.
KNOWN_AGENT_CLIENTS: tuple[tuple[str, str, str], ...] = (
    ("claude", "anthropic", "claude"),
    ("anthropic", "anthropic", "claude"),
    ("chatgpt", "openai", "chatgpt"),
    ("openai", "openai", "chatgpt"),
    ("gemini", "google", "gemini"),
    ("copilot", "microsoft", "copilot"),
    ("cursor", "anysphere", "cursor"),
    ("perplexity", "perplexity", "perplexity"),
)


def _s(value: Any, limit: int = _MAX) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _origin(url: Any) -> Optional[str]:
    text = _s(url, 2048)
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname.lower()}" + (f":{parts.port}" if parts.port else "")


def _known(name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    lower = (name or "").lower()
    for needle, provider, product in KNOWN_AGENT_CLIENTS:
        if needle in lower:
            return provider, product
    return None, (re.sub(r"[^a-z0-9._-]+", "_", lower).strip("_")[:64] or None)


def _evaluate_mcp(mcp: dict[str, Any]) -> Optional[dict[str, Any]]:
    client_info = mcp.get("clientInfo") if isinstance(mcp.get("clientInfo"), dict) else {}
    client_name = _s(client_info.get("name"))
    client_version = _s(client_info.get("version"), 64)
    oauth = mcp.get("oauth") if isinstance(mcp.get("oauth"), dict) else {}
    client_id = _s(oauth.get("clientId"))
    verified = oauth.get("verified") is True and client_id is not None
    if not client_name and not client_id:
        return None
    provider, product = _known(client_name)
    subject_hash = _s(oauth.get("subjectHash"), 64)
    scopes = [s for s in (oauth.get("scopes") or []) if isinstance(s, str)][:32] if isinstance(oauth.get("scopes"), list) else []
    return {
        "protocol": "mcp",
        "verification": "mcp_oauth_client" if verified else "mcp_client_info_declared",
        "client_name": client_name,
        "client_version": client_version,
        "protocol_version": _s(mcp.get("protocolVersion"), 32),
        "oauth_client_id": client_id if verified else None,
        "oauth_issuer": _origin(oauth.get("issuer")) if verified else None,
        "oauth_scopes": scopes if verified else [],
        # Pseudonymous principal reference (the user who authorized the client).
        "principal_subject_hash": subject_hash if verified and subject_hash and _HEX64.match(subject_hash) else None,
        "provider": provider,
        "product": product,
        "observed_by": OBSERVED_BY,
    }


def _evaluate_a2a(a2a: dict[str, Any]) -> Optional[dict[str, Any]]:
    card = a2a.get("agentCard") if isinstance(a2a.get("agentCard"), dict) else {}
    name = _s(card.get("name"))
    card_url = _origin(card.get("url"))
    provider_info = card.get("provider") if isinstance(card.get("provider"), dict) else {}
    provider_org = _s(provider_info.get("organization"))
    provider_url = _origin(provider_info.get("url"))
    fetched_from = _origin(a2a.get("agentCardUrl"))
    if not name and not card_url:
        return None
    authenticated = a2a.get("authenticated") is True
    signature_verified = a2a.get("cardSignatureVerified") is True
    # An Agent Card fetched from a different origin than the endpoint it
    # advertises is an inconsistency worth recording; it never verifies.
    origin_consistent = fetched_from is None or card_url is None or fetched_from == card_url
    if authenticated and signature_verified and origin_consistent:
        verification = "a2a_authenticated_signed_card"
    elif authenticated:
        verification = "a2a_authenticated"
    else:
        verification = "a2a_agent_card_declared"
    provider, product = _known(provider_org or name)
    return {
        "protocol": "a2a",
        "verification": verification,
        "agent_name": name,
        "agent_url": card_url,
        "agent_card_origin": fetched_from,
        "origin_consistent": origin_consistent,
        "provider_organization": provider_org,
        "provider_url": provider_url,
        "auth_scheme": _s(a2a.get("authScheme"), 64) if authenticated else None,
        "protocol_version": _s(card.get("protocolVersion"), 32),
        "provider": provider,
        "product": product or _known(name)[1],
        "observed_by": OBSERVED_BY,
    }


def evaluate_agent_protocol(raw: Any) -> Optional[dict[str, Any]]:
    """Grade ``context.agentProtocol``; ``None`` when it identifies nothing."""
    if not isinstance(raw, dict):
        return None
    protocol = _s(raw.get("protocol"), 16)
    if protocol == "mcp" and isinstance(raw.get("mcp"), dict):
        return _evaluate_mcp(raw["mcp"])
    if protocol == "a2a" and isinstance(raw.get("a2a"), dict):
        return _evaluate_a2a(raw["a2a"])
    return None


#: verification -> (proof_level, confidence)
GRADES: dict[str, tuple[str, float]] = {
    "mcp_oauth_client": ("server_observed", 0.85),
    "mcp_client_info_declared": ("declared", 0.6),
    "a2a_authenticated_signed_card": ("server_observed", 0.9),
    "a2a_authenticated": ("server_observed", 0.8),
    "a2a_agent_card_declared": ("declared", 0.6),
}


__all__ = ["GRADES", "KNOWN_AGENT_CLIENTS", "OBSERVED_BY", "evaluate_agent_protocol"]
