"""Infrastructure360 vertical slice — runtime registration tests.

``register_provider`` (and the provider itself) must conform to the plane's
:class:`ProviderRegistry` gates: real registry id, contract-major-compatible
version, duplicate (different-object) rejection, idempotent same-object
re-registration. The infrastructure360 row lands in the canonical registry as a
SEPARATE integration step, so these tests supply a minimal registry snapshot
containing the row — exactly the gates the orchestrator's regeneration will
enforce against the real registry.
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

from services.infrastructure import register_provider  # noqa: E402
from services.infrastructure.provider import (  # noqa: E402
    Infrastructure360Provider,
)
from shared.intelligence_projections.errors import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionNotFound,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry, projection_registry  # noqa: E402

# The infrastructure360 row, as the orchestrator will add it (the fields the
# runtime registry actually reads; the orchestrator's real row carries the full
# shape).
_INFRASTRUCTURE360_DEFINITION = {
    "id": "infrastructure360",
    "displayName": "Infrastructure 360",
    "projectionKind": "infrastructure_360",
    "implementationState": "implemented",
    "ownsCanonicalTruth": False,
    "hardDependencies": ["contract_spine", "temporal_kernel", "infrastructure_model"],
    "projectionDependencies": [],
    "optionalProjectionDependencies": [],
    "graphMutationPolicy": "read_only",
    "outputSections": ["summary", "state", "deployments", "evidence", "findings"],
    "requiresEvidence": True,
    "tenantScoped": True,
    "legacyBindings": {
        "routes": ["/v1/infrastructure"],
        "surfaceIds": ["infrastructure360"],
        "services": ["Backend Architecture/aether-backend/services/infrastructure"],
        "migrationMode": "converged",
        "migrationBlueprint": "docs/blueprints/infrastructure360.md",
    },
    "pendingAuthority": [],
    "pendingReference": [],
}


def _registry() -> ProviderRegistry:
    return ProviderRegistry(registry_data={"infrastructure360": _INFRASTRUCTURE360_DEFINITION})


class _FakeProvider:
    """Minimal provider for gate tests (id/version are the only surface used)."""

    def __init__(self, projection_id: str, contract_version: str) -> None:
        self.projection_id = projection_id
        self.contract_version = contract_version

    async def project(self, request: object, context: object) -> object:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# register_provider succeeds against a registry that contains the row
# ---------------------------------------------------------------------------

def test_register_provider_succeeds() -> None:
    registry = _registry()
    # The seam's signature is register_provider(registry) -> None; registration
    # is observable on the registry, not via a return value.
    assert register_provider(registry) is None
    assert registry.sources() == {"infrastructure360": "services/infrastructure"}
    entry = registry.availability()["infrastructure360"]
    assert entry["registered"] is True
    assert entry["contractCompatible"] is True
    assert entry["registryState"] == "implemented"


def test_register_provider_idempotent_same_object() -> None:
    registry = _registry()
    provider = Infrastructure360Provider()
    registry.register(provider)
    registry.register(provider, source="again")
    assert len(registry.list()) == 1
    assert registry.sources()["infrastructure360"] == "direct"


def test_register_provider_duplicate_different_object_raises() -> None:
    registry = _registry()
    register_provider(registry)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(registry)
    assert excinfo.value.projection_id == "infrastructure360"


def test_contract_version_is_exact_registry_constant() -> None:
    assert (
        Infrastructure360Provider().contract_version
        == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    )


def test_version_mismatch_raises_contract_version_incompatible() -> None:
    registry = _registry()
    provider = _FakeProvider("infrastructure360", "9.9.9")
    with pytest.raises(ContractVersionIncompatible) as excinfo:
        registry.register(provider)
    assert excinfo.value.projection_id == "infrastructure360"
    assert excinfo.value.version == "9.9.9"


def test_unknown_id_raises_projection_not_found() -> None:
    registry = _registry()
    provider = _FakeProvider("no_such_projection", INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION)
    with pytest.raises(ProjectionNotFound) as excinfo:
        registry.register(provider)
    assert excinfo.value.projection_id == "no_such_projection"
    assert registry.list() == []


def test_registry_reports_read_only_graph_mutation_policy() -> None:
    registry = _registry()
    assert registry.graph_mutation_policy("infrastructure360") == "read_only"


# ---------------------------------------------------------------------------
# No auto-registration on the global plane registry at import time
# ---------------------------------------------------------------------------

def test_importing_the_package_does_not_auto_register_globally() -> None:
    # The plane's global registry stays clean: wiring is the caller's job
    # (register_provider is explicit), so importing the slice has no side
    # effects on the plane.
    assert projection_registry.get("infrastructure360") is None
