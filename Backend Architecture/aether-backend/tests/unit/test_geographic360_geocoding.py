"""Geographic360 geocoding tests (G4.3) — vault-backed GeocodingProvider.

Pins the vault-backed geocoding seam beside the network-egress GeoProvider:

* keys live in the credential vault (``CredentialBackend``/``CredentialService``)
  — never env, never hardcoded; the executor receives the resolved key per call;
* reverse answers carry a **client-computed** H3 ``coarse_cell`` and never echo a
  coordinate or claim finer than ``coarse_cell``/``city``;
* every path fails closed — missing/revoked/secret-less credential or no wired
  executor degrades to the honest null provider; an executor failure degrades to
  a typed ``provider_error`` hit, never an exception; bad input is
  ``invalid_input``;
* labels keep the shared vocabulary canonical (unknown region types normalize to
  ``None``).
"""

from __future__ import annotations

from pydantic import SecretStr

from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.types import ApiKeyCredential

from services.geo.geocoding import (
    KIND_FORWARD,
    KIND_REVERSE,
    STATE_INVALID_INPUT,
    STATE_NOT_PROVISIONED,
    STATE_PROVIDER_ERROR,
    STATE_READY,
    GeocodeHit,
    NullGeocodingProvider,
    VaultKeyGeocodingProvider,
    build_vault_geocoding_provider,
    geocoding_ref,
)
from services.geo.spatial_cells import coordinate_to_cell

TENANT = "tenant_geo_g43"
PROVIDER = "acme_geocoder"
PORTLAND_LAT = 45.52
PORTLAND_LON = -122.68
VAULT_KEY = "geo_secret_value_abc"


class RecordingExecutor:
    """Fixture executor: records every api_key it was handed, returns canned hits."""

    def __init__(self, region_type: str = "admin_region") -> None:
        self.seen_keys: list[str] = []
        self.region_type = region_type

    def reverse(self, *, latitude: float, longitude: float, api_key: str) -> GeocodeHit:
        self.seen_keys.append(api_key)
        return GeocodeHit(
            state=STATE_READY,
            kind=KIND_REVERSE,
            country_code="US",
            region_code="OR",
            region_type=self.region_type,
            city="Portland",
            confidence=0.9,
        )

    def forward(self, query: str, *, limit: int, api_key: str) -> list[GeocodeHit]:
        self.seen_keys.append(api_key)
        return [
            GeocodeHit(
                state=STATE_READY,
                kind=KIND_FORWARD,
                country_code="US",
                region_code="OR",
                region_type=self.region_type,
                city="Portland",
                confidence=0.8,
            )
        ]


class ExplodingExecutor:
    """Executor that always fails — the provider must degrade, never raise."""

    def reverse(self, *, latitude: float, longitude: float, api_key: str) -> GeocodeHit:
        raise RuntimeError("upstream geocoder unreachable")

    def forward(self, query: str, *, limit: int, api_key: str) -> list[GeocodeHit]:
        raise RuntimeError("upstream geocoder unreachable")


def _service() -> CredentialService:
    return CredentialService(backend=InMemoryCredentialBackend(store={}))


# --- refs ----------------------------------------------------------------------


def test_geocoding_ref_namespace():
    assert geocoding_ref(PROVIDER) == f"geo:{PROVIDER}"
    # A ref never contains secret material by construction.
    assert VAULT_KEY not in geocoding_ref(PROVIDER)


# --- null provider --------------------------------------------------------------


def test_null_provider_is_honest_not_provisioned():
    provider = NullGeocodingProvider()
    assert provider.capability_state() == STATE_NOT_PROVISIONED
    hit = provider.reverse(latitude=PORTLAND_LAT, longitude=PORTLAND_LON)
    assert hit.state == STATE_NOT_PROVISIONED
    assert hit.kind == KIND_REVERSE
    assert provider.forward("1600 Amphitheatre Pkwy") == []


# --- vault-backed: build + key flow ---------------------------------------------


async def test_build_resolves_key_from_vault_and_delegates():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    executor = RecordingExecutor()

    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=executor
    )

    assert isinstance(provider, VaultKeyGeocodingProvider)
    assert provider.capability_state() == STATE_READY

    hit = provider.reverse(latitude=PORTLAND_LAT, longitude=PORTLAND_LON)
    assert hit.state == STATE_READY
    assert hit.kind == KIND_REVERSE
    assert hit.provider == PROVIDER
    assert hit.country_code == "US"
    assert hit.city == "Portland"
    # Reverse hits carry the client-computed coarse cell for the coordinate.
    assert hit.coarse_cell == coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON)
    # The key reached the executor — from the vault, never env/hardcode.
    assert executor.seen_keys == [VAULT_KEY]


async def test_forward_candidates_are_tagged_not_cell_precise():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    executor = RecordingExecutor()

    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=executor
    )
    candidates = provider.forward("Portland, OR", limit=3)
    assert len(candidates) == 1
    assert candidates[0].kind == KIND_FORWARD
    assert candidates[0].state == STATE_READY
    assert candidates[0].provider == PROVIDER
    # Forward answers label a named place; no single authoritative client cell.
    assert candidates[0].coarse_cell is None


async def test_repr_masks_resolved_key():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=RecordingExecutor()
    )
    rendered = repr(provider)
    assert VAULT_KEY not in rendered
    assert "****" in rendered


# --- vault-backed: fail-closed paths ---------------------------------------------


async def test_missing_credential_builds_null():
    provider = await build_vault_geocoding_provider(
        _service(),
        tenant_id=TENANT,
        provider_name=PROVIDER,
        executor=RecordingExecutor(),
    )
    assert isinstance(provider, NullGeocodingProvider)
    assert provider.capability_state() == STATE_NOT_PROVISIONED


async def test_revoked_credential_builds_null():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    await service.revoke(TENANT, geocoding_ref(PROVIDER))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=RecordingExecutor()
    )
    assert isinstance(provider, NullGeocodingProvider)
    assert provider.capability_state() == STATE_NOT_PROVISIONED


async def test_key_without_executor_never_fabricates_ready():
    # A stored vault key alone is not a provisioned geocoder: no executor can
    # serve the request, so the honest answer is not_provisioned.
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=None
    )
    assert isinstance(provider, NullGeocodingProvider)
    assert provider.capability_state() == STATE_NOT_PROVISIONED


async def test_executor_failure_degrades_to_provider_error():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=ExplodingExecutor()
    )

    hit = provider.reverse(latitude=PORTLAND_LAT, longitude=PORTLAND_LON)  # never raises
    assert hit.state == STATE_PROVIDER_ERROR
    assert hit.kind == KIND_REVERSE
    assert provider.forward("Portland") == []  # never raises


async def test_invalid_coordinate_degrades_to_invalid_input():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=RecordingExecutor()
    )
    hit = provider.reverse(latitude=91.0, longitude=0.0)
    assert hit.state == STATE_INVALID_INPUT
    assert hit.kind == KIND_REVERSE


# --- vocabulary discipline --------------------------------------------------------


def test_unknown_region_type_normalizes_to_none():
    hit = GeocodeHit(
        state=STATE_READY,
        kind=KIND_REVERSE,
        region_type="not_a_region_type",
        country_code="US",
    )
    assert hit.region_type is None


async def test_ready_hit_keeps_known_region_type():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service, tenant_id=TENANT, provider_name=PROVIDER, executor=RecordingExecutor()
    )
    hit = provider.reverse(latitude=PORTLAND_LAT, longitude=PORTLAND_LON)
    assert hit.region_type == "admin_region"  # kept from the shared vocabulary


async def test_region_type_normalized_on_vault_hit():
    service = _service()
    await service.create(TENANT, geocoding_ref(PROVIDER), ApiKeyCredential(api_key=SecretStr(VAULT_KEY)))
    provider = await build_vault_geocoding_provider(
        service,
        tenant_id=TENANT,
        provider_name=PROVIDER,
        executor=RecordingExecutor(region_type="not_a_region_type"),
    )
    hit = provider.reverse(latitude=PORTLAND_LAT, longitude=PORTLAND_LON)
    assert hit.state == STATE_READY
    assert hit.region_type is None
