"""Server-side verification of declared AI agents and crawlers.

A user-agent string only *declares* an agent: anyone can send ``ChatGPT-User``.
This module upgrades a declaration to verified evidence when the request's
server-observed client IP is inside the published IP range of the provider the
user-agent names (``agent_provider_ranges.json``, refreshed by
``scripts/refresh_agent_provider_ranges.py``).

Privacy: the raw IP is used transiently for the range check and is never
returned. The output carries only the matched signature, provider, and a
boolean verdict.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

RANGES_PATH = Path(__file__).with_name("agent_provider_ranges.json")

#: Verification states, weakest first.
VERIFICATION_UNVERIFIED = "unverified"        # declared; provider publishes no ranges
VERIFICATION_IP_MISMATCH = "ip_mismatch"      # provider publishes ranges; IP is outside them
VERIFICATION_NO_CLIENT_IP = "no_client_ip"    # nothing to check against
VERIFICATION_IP_VERIFIED = "provider_ip_range"


@dataclass(frozen=True)
class _ProviderRanges:
    provider: str
    product: str
    networks: tuple[Any, ...]


@lru_cache(maxsize=1)
def _load_ranges() -> dict[str, _ProviderRanges]:
    try:
        raw = json.loads(RANGES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, _ProviderRanges] = {}
    for signature, entry in (raw.get("signatures") or {}).items():
        networks = []
        for prefix in entry.get("prefixes") or []:
            try:
                networks.append(ipaddress.ip_network(prefix, strict=False))
            except ValueError:
                continue
        out[signature.lower()] = _ProviderRanges(
            provider=str(entry.get("provider") or ""),
            product=str(entry.get("product") or ""),
            networks=tuple(networks),
        )
    return out


def match_declared_signature(user_agent: Optional[str]) -> Optional[str]:
    """The first declared agent/crawler signature found in ``user_agent``."""
    from journeys.traffic.classifier import SourceClassifier

    ua = (user_agent or "").lower()
    if not ua:
        return None
    for signature, *_ in SourceClassifier.MACHINE_USER_AGENTS:
        if signature in ua:
            return signature
    for signature, *_ in SourceClassifier.AGENT_USER_AGENTS:
        if signature in ua:
            return signature
    return None


def has_published_ranges(signature: str) -> bool:
    entry = _load_ranges().get(signature.lower())
    return bool(entry and entry.networks)


def ip_in_provider_range(signature: str, client_ip: Optional[str]) -> bool:
    entry = _load_ranges().get(signature.lower())
    if not entry or not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        return False
    return any(addr.version == net.version and addr in net for net in entry.networks)


def server_agent_evidence(
    user_agent_header: Optional[str], client_ip: Optional[str]
) -> Optional[dict[str, Any]]:
    """Evidence for one request, or ``None`` when the header declares no agent.

    Called with the request's own ``User-Agent`` header and the trusted client
    IP. The returned dict contains no IP.
    """
    signature = match_declared_signature(user_agent_header)
    if signature is None:
        return None
    if not client_ip:
        state = VERIFICATION_NO_CLIENT_IP
    elif not has_published_ranges(signature):
        state = VERIFICATION_UNVERIFIED
    elif ip_in_provider_range(signature, client_ip):
        state = VERIFICATION_IP_VERIFIED
    else:
        state = VERIFICATION_IP_MISMATCH
    return {"ua_signature": signature, "verification": state}


__all__ = [
    "VERIFICATION_IP_MISMATCH",
    "VERIFICATION_IP_VERIFIED",
    "VERIFICATION_NO_CLIENT_IP",
    "VERIFICATION_UNVERIFIED",
    "has_published_ranges",
    "ip_in_provider_range",
    "match_declared_signature",
    "server_agent_evidence",
]
