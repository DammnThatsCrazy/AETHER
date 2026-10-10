"""Geo/ASN provider interface for server-derived network context.

Centralizes the MaxMind logic that previously lived only on the deprecated
``/v1/ingest/events`` alias, behind a small protocol with three
implementations:

- :class:`MaxMindGeoProvider` — local GeoLite2 databases (air-gapped safe;
  no outbound calls). Fails closed to ``not_provisioned`` when the database
  files or the ``maxminddb`` package are absent.
- :class:`DeterministicTestGeoProvider` — fixture-table lookups for CI.
- :class:`NullGeoProvider` — honest ``not_provisioned`` everywhere.

Lookups return COARSE network-egress facts only (country/region/city, ASN
class). Network geography is never physical presence, and nothing here emits
a raw IP — callers pass IPs transiently and persist only derived context.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

# Reserved/private ranges — never geolocate, classify as private.
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Known datacenter/cloud ASNs (coarse likelihood signal, not a verdict).
_DATACENTER_ASNS = frozenset({
    14061,  # DigitalOcean
    16509,  # Amazon AWS
    15169,  # Google
    396982, # Google Cloud
    8075,   # Microsoft Azure
    13335,  # Cloudflare
    20473,  # Vultr
    63949,  # Linode/Akamai
    14618,  # Amazon AWS (alt)
    24940,  # Hetzner
    16276,  # OVH
})


@dataclass(frozen=True)
class GeoLookup:
    """Coarse network-egress facts for one transient IP."""

    state: str  # ready | not_provisioned | private_address | invalid_address | provider_error
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    asn: Optional[int] = None
    asn_class: Optional[str] = None  # datacenter | network | None
    provider: Optional[str] = None
    provider_database_version: Optional[str] = None
    datacenter_likelihood: float = 0.0


class GeoProvider(Protocol):
    def lookup(self, raw_ip: str) -> GeoLookup: ...
    def capability_state(self) -> str:
        """``ready`` | ``not_provisioned`` — honest, never fabricated."""
        ...


def classify_address(raw_ip: str) -> Optional[str]:
    """``private_address`` / ``invalid_address`` / None (public, look it up)."""
    try:
        addr = ipaddress.ip_address(raw_ip.strip())
    except ValueError:
        return "invalid_address"
    if any(addr in net for net in _PRIVATE_RANGES):
        return "private_address"
    return None


class NullGeoProvider:
    """No provider configured — every lookup is honestly ``not_provisioned``."""

    def lookup(self, raw_ip: str) -> GeoLookup:
        pre = classify_address(raw_ip)
        if pre:
            return GeoLookup(state=pre)
        return GeoLookup(state="not_provisioned")

    def capability_state(self) -> str:
        return "not_provisioned"


class DeterministicTestGeoProvider:
    """Fixture-table provider for CI — no databases, fully deterministic."""

    def __init__(self, table: Optional[dict[str, GeoLookup]] = None) -> None:
        self._table = table or {}

    def lookup(self, raw_ip: str) -> GeoLookup:
        pre = classify_address(raw_ip)
        if pre:
            return GeoLookup(state=pre)
        hit = self._table.get(raw_ip.strip())
        if hit is not None:
            return hit
        return GeoLookup(state="ready", provider="deterministic_test")

    def capability_state(self) -> str:
        return "ready"


@dataclass
class MaxMindGeoProvider:
    """Local GeoLite2 city+ASN databases; fail-closed when unavailable."""

    city_db_path: str = field(
        default_factory=lambda: os.environ.get(
            "GEOIP_DB_PATH", "/usr/share/GeoIP/GeoLite2-City.mmdb"
        )
    )
    asn_db_path: str = field(
        default_factory=lambda: os.environ.get(
            "GEOIP_ASN_DB_PATH", "/usr/share/GeoIP/GeoLite2-ASN.mmdb"
        )
    )

    def __post_init__(self) -> None:
        self._city_reader = None
        self._asn_reader = None
        self._available: Optional[bool] = None

    def _ensure(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import maxminddb  # noqa: PLC0415 - optional dependency

            if os.path.exists(self.city_db_path):
                self._city_reader = maxminddb.open_database(self.city_db_path)
            if os.path.exists(self.asn_db_path):
                self._asn_reader = maxminddb.open_database(self.asn_db_path)
            self._available = self._city_reader is not None or self._asn_reader is not None
        except Exception:
            self._available = False
        return self._available

    def capability_state(self) -> str:
        return "ready" if self._ensure() else "not_provisioned"

    def lookup(self, raw_ip: str) -> GeoLookup:
        pre = classify_address(raw_ip)
        if pre:
            return GeoLookup(state=pre)
        if not self._ensure():
            return GeoLookup(state="not_provisioned")
        try:
            country = region = city = None
            asn = None
            if self._city_reader is not None:
                record = self._city_reader.get(raw_ip) or {}
                country = (record.get("country") or {}).get("iso_code")
                subdivisions = record.get("subdivisions") or []
                region = subdivisions[0].get("iso_code") if subdivisions else None
                city = ((record.get("city") or {}).get("names") or {}).get("en")
            if self._asn_reader is not None:
                asn_record = self._asn_reader.get(raw_ip) or {}
                asn = asn_record.get("autonomous_system_number")
            is_dc = asn in _DATACENTER_ASNS if asn else False
            return GeoLookup(
                state="ready",
                country_code=country,
                region_code=region,
                city=city,
                asn=asn,
                asn_class="datacenter" if is_dc else ("network" if asn else None),
                provider="maxmind_geolite2",
                provider_database_version=os.path.basename(self.city_db_path),
                datacenter_likelihood=0.9 if is_dc else 0.0,
            )
        except Exception:
            return GeoLookup(state="provider_error")


def default_geo_provider() -> GeoProvider:
    """MaxMind when provisioned, otherwise the honest null provider."""
    provider = MaxMindGeoProvider()
    if provider.capability_state() == "ready":
        return provider
    return NullGeoProvider()


__all__ = [
    "GeoLookup",
    "GeoProvider",
    "NullGeoProvider",
    "DeterministicTestGeoProvider",
    "MaxMindGeoProvider",
    "default_geo_provider",
    "classify_address",
]
