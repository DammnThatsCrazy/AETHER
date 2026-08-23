"""Unit tests for the intelligence-projection ProviderRegistry (P0.5, group 6).

The runtime registry gates every ``register`` on a real registry id and a
contract-major-compatible provider, rejects duplicate identity keys (the SAME
object re-registered is an idempotent no-op; a DIFFERENT object is a
``DuplicateProjection``), and exposes pure introspection — ``availability()``
never claims readiness.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTION_IDS,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


def _subject(kind: str = "entity", ident: str = "ent_1") -> ProjectionSubject:
    return ProjectionSubject(kind=kind, id=ident)


def _request(projection_id: str = "profile360", **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": projection_id,
        "tenantId": "tenant-a",
        "subject": _subject(),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


class _FakeProvider:
    """Minimal concrete provider for registration-behaviour tests."""

    def __init__(self, projection_id: str, contract_version: str = "1.0.0") -> None:
        self.projection_id = projection_id
        self.contract_version = contract_version

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=context.dependencyState,  # type: ignore[attr-defined]
            generatedAt="2026-08-23T12:00:00Z",
            degradedReasons=[],
        )


# ---------------------------------------------------------------------------
# Duplicate rejection / idempotent same-object re-registration
# ---------------------------------------------------------------------------

def test_different_object_for_registered_id_raises_duplicate() -> None:
    reg = ProviderRegistry()
    reg.register(_FakeProvider("profile360"))

    with pytest.raises(DuplicateProjection) as excinfo:
        reg.register(_FakeProvider("profile360"))
    assert excinfo.value.projection_id == "profile360"


def test_same_object_reregister_is_idempotent_noop() -> None:
    reg = ProviderRegistry()
    provider = _FakeProvider("profile360")
    assert reg.register(provider) == "profile360"
    # Same object again -> no raise, same id returned, still a single provider.
    assert reg.register(provider) == "profile360"
    assert reg.register(provider, source="re-registered") == "profile360"
    assert len(reg.list()) == 1
    # The original source is retained (idempotent no-op keeps provenance).
    assert reg.sources()["profile360"] == "direct"


# ---------------------------------------------------------------------------
# Unknown id
# ---------------------------------------------------------------------------

def test_register_unknown_id_raises_projection_not_found() -> None:
    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound) as excinfo:
        reg.register(_FakeProvider("no_such_projection"))
    assert excinfo.value.projection_id == "no_such_projection"
    # Nothing was registered.
    assert reg.list() == []


def test_require_unknown_id_raises_projection_not_found() -> None:
    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound):
        reg.require("profile360")
    assert reg.get("profile360") is None


@pytest.mark.asyncio
async def test_project_unknown_id_raises_projection_not_found() -> None:
    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound):
        await reg.project("profile360", _request())
    # No provider, no context, no result — fail-closed at the boundary.
    assert reg.availability()["profile360"]["registered"] is False


# ---------------------------------------------------------------------------
# Contract version compatibility
# ---------------------------------------------------------------------------

def test_register_different_major_version_raises_incompatible() -> None:
    reg = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible) as excinfo:
        reg.register(_FakeProvider("profile360", contract_version="2.0.0"))
    assert excinfo.value.projection_id == "profile360"
    assert excinfo.value.version == "2.0.0"


def test_register_second_major_version_rejected_when_already_registered() -> None:
    # A duplicate that is ALSO contract-incompatible is rejected at the version
    # gate (register checks unknown-id -> version -> duplicate, in that order).
    reg = ProviderRegistry()
    reg.register(_FakeProvider("profile360", contract_version="1.0.0"))
    with pytest.raises(ContractVersionIncompatible):
        reg.register(_FakeProvider("profile360", contract_version="3.0.0"))


def test_register_same_major_version_accepted() -> None:
    reg = ProviderRegistry()
    # Same major, newer minor/patch -> accepted.
    assert reg.register(_FakeProvider("profile360", contract_version="1.5.0")) == "profile360"
    # A bare-major / pre-release-suffixed same-major version is also accepted.
    reg2 = ProviderRegistry()
    assert reg2.register(_FakeProvider("campaign360", contract_version="1.0.0-beta")) == "campaign360"


def test_supported_contracts_reports_provider_versions() -> None:
    reg = ProviderRegistry()
    reg.register(_FakeProvider("profile360", contract_version="1.0.0"))
    reg.register(_FakeProvider("campaign360", contract_version="1.5.0"))
    assert reg.supported_contracts() == {
        ("profile360", "1.0.0"),
        ("campaign360", "1.5.0"),
    }


# ---------------------------------------------------------------------------
# availability() — pure introspection, never readiness
# ---------------------------------------------------------------------------

def test_availability_unregistered_reports_not_registered() -> None:
    reg = ProviderRegistry()
    entry = reg.availability()["profile360"]
    assert entry["registered"] is False
    assert entry["contractCompatible"] is False
    # registryState comes from the generated definition, not from registration.
    assert entry["registryState"] == INTELLIGENCE_PROJECTION_DEFINITIONS["profile360"]["implementationState"]


def test_availability_registered_reports_definition_state_and_compat() -> None:
    reg = ProviderRegistry()
    provider = _FakeProvider("profile360")
    reg.register(provider)
    entry = reg.availability()["profile360"]
    assert entry["registered"] is True
    assert entry["registryState"] == "in_flight"  # the definition's state
    assert entry["contractCompatible"] is True

    # Simulate a provider whose contract_version drifted out of compatibility.
    provider.contract_version = "2.0.0"
    drifted = reg.availability()["profile360"]
    assert drifted["registered"] is True
    assert drifted["contractCompatible"] is False


def test_availability_never_claims_readiness() -> None:
    reg = ProviderRegistry()
    reg.register(_FakeProvider("profile360"))
    for projection_id, entry in reg.availability().items():
        # contractCompatible is NOT readiness: no ready key, no readiness flag.
        assert "ready" not in entry
        assert "ready" not in projection_id  # sanity guard
        assert set(entry) == {"registered", "registryState", "contractCompatible"}
    assert set(reg.availability().keys()) == set(INTELLIGENCE_PROJECTION_IDS)


def test_availability_covers_every_registry_id() -> None:
    reg = ProviderRegistry()
    reg.register(_FakeProvider("profile360"))
    reg.register(_FakeProvider("temporal360"))
    avail = reg.availability()
    assert len(avail) == len(INTELLIGENCE_PROJECTION_IDS)
    assert avail["profile360"]["registered"] is True
    assert avail["temporal360"]["registered"] is True
    assert avail["campaign360"]["registered"] is False  # unregistered id still present


# ---------------------------------------------------------------------------
# list / sources / unregister
# ---------------------------------------------------------------------------

def test_list_sources_and_unregister_basic_behaviour() -> None:
    reg = ProviderRegistry()
    profile = _FakeProvider("profile360")
    temporal = _FakeProvider("temporal360", contract_version="1.2.0")
    reg.register(profile, source="blueprint")
    reg.register(temporal, source="test")

    assert reg.list() == [profile, temporal]
    assert reg.sources() == {"profile360": "blueprint", "temporal360": "test"}
    assert reg.get("profile360") is profile
    assert reg.require("temporal360") is temporal

    # unregister is a no-op for an absent id.
    reg.unregister("no_such_projection")

    reg.unregister("profile360")
    assert reg.get("profile360") is None
    assert "profile360" not in reg.sources()
    with pytest.raises(ProjectionNotFound):
        reg.require("profile360")
    assert reg.availability()["profile360"]["registered"] is False
    # The other provider is untouched.
    assert reg.get("temporal360") is temporal
