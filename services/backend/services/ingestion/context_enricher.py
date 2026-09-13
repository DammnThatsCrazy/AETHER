"""Server-derived request context for canonical ingestion.

Owns trusted client-IP resolution and coarse network/geo enrichment for
``/v1/batch``. Security posture:

- Forwarded headers are trusted ONLY when the direct peer is inside the
  configured trusted-proxy CIDRs; the X-Forwarded-For chain is walked
  RIGHT-TO-LEFT and stops at the first hop not in the trusted set.
- ``CF-Connecting-IP`` is honored only when Cloudflare proxying is enabled
  AND the peer is a trusted proxy.
- The raw IP exists transiently in this module only. Output carries the
  tenant-scoped rotating HMAC + coarse geo/ASN facts — never the address.
- Client-supplied ``context.ip`` is untrusted evidence and is never used
  for server context.

Flag-gated (``AETHER_CONTEXT_ENRICHMENT_ENABLED``, default off): zero cost
while disabled. Enrichment never rejects a valid event — failures yield
explicit states (``not_provisioned`` / ``private_address`` / …).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Optional

from config.settings import settings
from shared.privacy.ip_hmac import ip_hmac_token

from services.ingestion.geo_provider import GeoProvider, default_geo_provider

_MAX_FORWARD_CHAIN = 10


@dataclass(frozen=True)
class ServerObservedContext:
    """What the server observed about the request's network origin — no raw IP."""

    enrichment_state: str  # ready | not_provisioned | private_address | invalid_address | provider_error | no_client_address
    ip_token: Optional[str] = None  # tenant-scoped rotating HMAC (iph1:…)
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    asn_class: Optional[str] = None
    datacenter_likelihood: float = 0.0
    provider: Optional[str] = None
    provider_database_version: Optional[str] = None
    client_ip_source: str = "peer"  # peer | forwarded_chain | cloudflare

    def as_payload(self) -> dict:
        payload = {
            "enrichment_state": self.enrichment_state,
            "client_ip_source": self.client_ip_source,
        }
        for key in (
            "ip_token",
            "country_code",
            "region_code",
            "city",
            "asn_class",
            "provider",
            "provider_database_version",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.datacenter_likelihood:
            payload["datacenter_likelihood"] = self.datacenter_likelihood
        return payload


@lru_cache(maxsize=1)
def _trusted_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks = []
    for cidr in settings.context_intelligence.trusted_proxy_cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(raw_ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(raw_ip.strip())
    except ValueError:
        return False
    return any(addr in net for net in _trusted_networks())


def resolve_client_ip(
    peer_ip: Optional[str],
    forwarded_for: Optional[str],
    cf_connecting_ip: Optional[str],
) -> tuple[Optional[str], str]:
    """Resolve the real client IP; returns (ip, source).

    Untrusted peers get their peer address only — spoofed forwarded headers
    from arbitrary clients are ignored.
    """
    if not peer_ip:
        return None, "peer"
    if not _is_trusted_proxy(peer_ip):
        return peer_ip, "peer"

    if (
        cf_connecting_ip
        and settings.context_intelligence.cloudflare_proxy_enabled
    ):
        try:
            ipaddress.ip_address(cf_connecting_ip.strip())
            return cf_connecting_ip.strip(), "cloudflare"
        except ValueError:
            pass

    if forwarded_for:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        if len(hops) <= _MAX_FORWARD_CHAIN:
            # Right-to-left: the first hop NOT in the trusted set is the client.
            for hop in reversed(hops):
                try:
                    ipaddress.ip_address(hop)
                except ValueError:
                    break  # malformed hop — stop trusting the chain
                if not _is_trusted_proxy(hop):
                    return hop, "forwarded_chain"
            # Every hop was a trusted proxy — fall through to the peer.
    return peer_ip, "peer"


def enrich_request_context(
    *,
    tenant_id: str,
    at: datetime,
    peer_ip: Optional[str],
    forwarded_for: Optional[str] = None,
    cf_connecting_ip: Optional[str] = None,
    provider: Optional[GeoProvider] = None,
) -> ServerObservedContext:
    """Build the server-observed context for one request. Raw IP never leaves."""
    client_ip, source = resolve_client_ip(peer_ip, forwarded_for, cf_connecting_ip)
    if not client_ip:
        return ServerObservedContext(
            enrichment_state="no_client_address", client_ip_source=source
        )

    geo = (provider or default_geo_provider()).lookup(client_ip)
    token = ip_hmac_token(
        client_ip,
        tenant_id,
        at,
        rotation_hours=settings.context_intelligence.ip_hmac_rotation_hours,
    )
    return ServerObservedContext(
        enrichment_state=geo.state,
        ip_token=token,
        country_code=geo.country_code,
        region_code=geo.region_code,
        city=geo.city,
        asn_class=geo.asn_class,
        datacenter_likelihood=geo.datacenter_likelihood,
        provider=geo.provider,
        provider_database_version=geo.provider_database_version,
        client_ip_source=source,
    )


__all__ = ["ServerObservedContext", "resolve_client_ip", "enrich_request_context"]
