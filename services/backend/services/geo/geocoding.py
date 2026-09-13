"""Vault-backed geocoding provider protocol (geographic360 G4.3).

Sits beside the network-egress :class:`GeoProvider`
(``services/ingestion/geo_provider.py``): that provider answers "which
country/region/city does this IP egress from"; this one resolves **named
geography** — a WGS84 coordinate to a coarse region/place label (:meth:`.reverse`)
or an address/place query to candidate labels (:meth:`.forward`).

Every implementation fails closed — a label is never fabricated, an executor
failure degrades to a typed ``provider_error`` hit (never an exception), and a
reverse answer never claims finer than ``coarse_cell``/``city`` (a place label is
not physical presence, so no coordinate is ever echoed).

**Keys live in the credential vault.** An external geocoder is configured by
storing an API-key credential under the tenant-scoped ``geo:{provider_name}`` ref
and building the provider through :func:`build_vault_geocoding_provider`, which
reads the vault via ``CredentialBackend.get`` (through the
``shared.credentials`` facade). Env vars and hardcoded keys are never consulted.
MaxMind GeoLite2 local files remain the air-gapped default (the existing
:class:`GeoProvider`), so no new external dependency is required to converge —
when no vault credential + executor is wired, the honest
:class:`NullGeocodingProvider` answers ``not_provisioned`` and downstream
geographic360 surfaces degrade, never fabricate.

Reverse hits carry a client-computed H3 ``coarse_cell`` (from
:mod:`services.geo.spatial_cells`) — never a string supplied by the external
geocoder — so cells stay authoritative even when the label provider is external.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from pydantic import SecretStr

from shared.credentials.service import CredentialService
from shared.credentials.types import (
    ApiKeyCredential,
    MultiCredential,
    OAuthTokenCredential,
    StructuredCredential,
)
from shared.geo.generated_taxonomy import REGION_TYPES

from services.geo.spatial_cells import (
    SpatialCellError,
    coordinate_to_cell,
)

# Result states — mirrors the GeoProvider ``GeoLookup`` honesty vocabulary.
STATE_READY = "ready"
STATE_NOT_PROVISIONED = "not_provisioned"
STATE_PROVIDER_ERROR = "provider_error"
STATE_INVALID_INPUT = "invalid_input"

KIND_REVERSE = "reverse"
KIND_FORWARD = "forward"

# Credential-ref namespace: ``geo:{provider_name}`` under a tenant.
GEOCODING_REF_PREFIX = "geo"


@dataclass(frozen=True, slots=True)
class GeocodeHit:
    """One typed geocoding answer.

    ``state`` is ``ready`` | ``not_provisioned`` | ``provider_error`` |
    ``invalid_input``. A ``ready`` reverse hit carries coarse region/place labels
    and a client-computed H3 ``coarse_cell``; it never carries a coordinate or a
    precision claim finer than ``coarse_cell``/``city``.
    """

    state: str
    kind: str
    provider: Optional[str] = None
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    region_type: Optional[str] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    coarse_cell: Optional[str] = None
    confidence: float = 0.0
    provider_database_version: Optional[str] = None

    def __post_init__(self) -> None:
        # Keep the vocabulary canonical: an executor that reports an unknown
        # region type is normalized to None rather than leaking a non-taxonomy
        # label into the graph.
        if self.region_type not in REGION_TYPES:
            object.__setattr__(self, "region_type", None)


class GeocodingProvider(Protocol):
    """Honest forward/reverse geocoding surface (never fabricates)."""

    def capability_state(self) -> str:
        """``ready`` | ``not_provisioned`` — honest, never fabricated."""
        ...

    def reverse(self, *, latitude: float, longitude: float) -> GeocodeHit:
        """Label the coordinate as coarsely as the provider can honestly."""
        ...

    def forward(self, query: str, *, limit: int = 5) -> list[GeocodeHit]:
        """Candidate region/place labels for an address/place query, best first."""
        ...


class GeocodingExecutor(Protocol):
    """Per-geocoder reverse/forward executor (infrastructure-wired).

    Executors receive the resolved API key on every call; they never resolve it
    themselves and never log it.
    """

    def reverse(self, *, latitude: float, longitude: float, api_key: str) -> GeocodeHit: ...
    def forward(self, query: str, *, limit: int, api_key: str) -> list[GeocodeHit]: ...


def geocoding_ref(provider_name: str) -> str:
    """Tenant-scoped credential ref for a geocoder key (never a secret itself)."""
    return f"{GEOCODING_REF_PREFIX}:{provider_name}"


class NullGeocodingProvider:
    """No geocoder configured — every answer is honestly ``not_provisioned``."""

    def capability_state(self) -> str:
        return STATE_NOT_PROVISIONED

    def reverse(self, *, latitude: float, longitude: float) -> GeocodeHit:
        return GeocodeHit(state=STATE_NOT_PROVISIONED, kind=KIND_REVERSE)

    def forward(self, query: str, *, limit: int = 5) -> list[GeocodeHit]:
        return []


class VaultKeyGeocodingProvider:
    """Delegates to an executor with an API key resolved from the credential vault.

    The key is held in memory only (this is the trusted resolver) and passed to
    the executor per call — it is never logged, printed, or rendered by
    ``repr``. Reverse answers carry a client-computed H3 ``coarse_cell`` derived
    from the coordinate, never a geocoder-supplied cell string.
    """

    def __init__(
        self,
        executor: GeocodingExecutor,
        *,
        api_key: str,
        provider_name: str,
        provider_database_version: Optional[str] = None,
    ) -> None:
        self._executor = executor
        self._api_key = api_key
        self._provider = provider_name
        self._provider_database_version = provider_database_version

    def __repr__(self) -> str:
        # Explicitly mask the resolved key.
        return f"VaultKeyGeocodingProvider(provider={self._provider!r}, api_key='****')"

    def capability_state(self) -> str:
        return STATE_READY

    def reverse(self, *, latitude: float, longitude: float) -> GeocodeHit:
        try:
            coarse_cell = coordinate_to_cell(latitude, longitude)
        except SpatialCellError:
            return GeocodeHit(state=STATE_INVALID_INPUT, kind=KIND_REVERSE, provider=self._provider)
        try:
            raw = self._executor.reverse(
                latitude=latitude, longitude=longitude, api_key=self._api_key
            )
        except Exception:  # noqa: BLE001 - degrade, never raise
            return GeocodeHit(state=STATE_PROVIDER_ERROR, kind=KIND_REVERSE, provider=self._provider)
        return _finalize_reverse(raw, coarse_cell=coarse_cell, provider=self._provider)

    def forward(self, query: str, *, limit: int = 5) -> list[GeocodeHit]:
        if not query or not query.strip():
            return []
        try:
            raw = self._executor.forward(query=query, limit=limit, api_key=self._api_key)
        except Exception:  # noqa: BLE001 - degrade to an empty result, never raise
            return []
        return [_finalize_forward(hit, provider=self._provider) for hit in raw]


def _finalize_reverse(raw: GeocodeHit, *, coarse_cell: str, provider: str) -> GeocodeHit:
    """Wrap an executor reverse hit: force client-computed cell + our provider tag."""
    if raw.state != STATE_READY:
        return GeocodeHit(state=raw.state, kind=KIND_REVERSE, provider=provider)
    return GeocodeHit(
        state=STATE_READY,
        kind=KIND_REVERSE,
        provider=provider or raw.provider,
        country_code=raw.country_code,
        region_code=raw.region_code,
        region_type=raw.region_type,
        city=raw.city,
        locality=raw.locality,
        coarse_cell=coarse_cell,
        confidence=raw.confidence,
        provider_database_version=raw.provider_database_version,
    )


def _finalize_forward(raw: GeocodeHit, *, provider: str) -> GeocodeHit:
    """Tag an executor forward candidate with the resolved provider name."""
    if raw.state != STATE_READY:
        return GeocodeHit(state=raw.state, kind=KIND_FORWARD, provider=provider)
    return GeocodeHit(
        state=STATE_READY,
        kind=KIND_FORWARD,
        provider=provider or raw.provider,
        country_code=raw.country_code,
        region_code=raw.region_code,
        region_type=raw.region_type,
        city=raw.city,
        locality=raw.locality,
        coarse_cell=None,  # forward labels a named place; no single client cell
        confidence=raw.confidence,
        provider_database_version=raw.provider_database_version,
    )


def _reveal_primary_secret(cred: StructuredCredential) -> Optional[str]:
    """Reveal the single geocoder key string for a stored credential.

    Mirrors ``shared.credentials.service._primary_secret`` (module-private there,
    so kept local): accepts the API-key / OAuth-token / multi / generic-SecretStr
    shapes. Absent secret material resolves to ``None`` (fail closed).
    """
    if isinstance(cred, ApiKeyCredential):
        return cred.api_key.get_secret_value()
    if isinstance(cred, OAuthTokenCredential):
        return cred.access_token.get_secret_value()
    if isinstance(cred, MultiCredential):
        inner = cred.credentials.get("primary") or next(
            iter(cred.credentials.values()), None
        )
        return _reveal_primary_secret(inner) if inner is not None else None
    for value in dict(cred).values():
        if isinstance(value, SecretStr):
            return value.get_secret_value()
    return None


async def build_vault_geocoding_provider(
    service: CredentialService,
    *,
    tenant_id: str,
    provider_name: str,
    executor: Optional[GeocodingExecutor] = None,
) -> GeocodingProvider:
    """Build a vault-backed geocoding provider, fail-closed to the null provider.

    Resolution order: a credential stored under ``geo:{provider_name}`` for
    ``tenant_id`` + a wired executor → :class:`VaultKeyGeocodingProvider`
    (``capability_state() == "ready"``). Otherwise — no credential, a revoked or
    secret-less credential, or no executor — the honest
    :class:`NullGeocodingProvider` is returned. A stored key alone never
    fabricates ``ready``: there must be something able to serve the request.
    """
    cred = await service.get(tenant_id, geocoding_ref(provider_name))
    if cred is None or executor is None:
        return NullGeocodingProvider()
    api_key = _reveal_primary_secret(cred)
    if not api_key:
        return NullGeocodingProvider()
    return VaultKeyGeocodingProvider(
        executor,
        api_key=api_key,
        provider_name=provider_name,
    )


__all__ = [
    "STATE_READY",
    "STATE_NOT_PROVISIONED",
    "STATE_PROVIDER_ERROR",
    "STATE_INVALID_INPUT",
    "KIND_REVERSE",
    "KIND_FORWARD",
    "GEOCODING_REF_PREFIX",
    "GeocodeHit",
    "GeocodingProvider",
    "GeocodingExecutor",
    "geocoding_ref",
    "NullGeocodingProvider",
    "VaultKeyGeocodingProvider",
    "build_vault_geocoding_provider",
]
