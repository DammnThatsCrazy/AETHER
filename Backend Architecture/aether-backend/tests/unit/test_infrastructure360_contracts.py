"""Infrastructure360 vertical slice — canonical contract + no-redefinition tests.

ADR-010 / the vertical-slice checklist §2: the projection reuses the canonical
primitives (``EntityRef`` / ``EvidenceRef`` / ``PageRequest`` / time-range) and
never declares a second copy of any of them. This file proves the infrastructure
package (``services/infrastructure``) re-imports the canonical models by
identity, and that the canonical infrastructure domain contracts construct and
serialize cleanly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import services.infrastructure.contracts as infra_contracts  # noqa: E402
import services.infrastructure.provider as infra_provider  # noqa: E402
from services.operational_intelligence import models as canonical_models  # noqa: E402


# ---------------------------------------------------------------------------
# No-redefinition (ADR-010 / checklist §2)
# ---------------------------------------------------------------------------

def test_infrastructure_package_reuses_canonical_evidence_ref() -> None:
    assert infra_contracts.EvidenceRef is canonical_models.EvidenceRef


def test_infrastructure_package_reuses_canonical_entity_ref() -> None:
    assert infra_contracts.EntityRef is canonical_models.EntityRef


def test_infrastructure_package_reuses_canonical_page_request() -> None:
    assert infra_contracts.PageRequest is canonical_models.PageRequest


def test_infrastructure_package_reuses_canonical_time_range_filter() -> None:
    assert infra_contracts.TimeRangeFilter is canonical_models.TimeRangeFilter


def test_infrastructure_package_declares_no_second_primitives() -> None:
    # The package re-EXPORTS the canonical primitives; it never re-declares
    # them. Any name that exists must be the canonical object by identity.
    for name in ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"):
        ours = getattr(infra_contracts, name)
        assert ours is getattr(canonical_models, name), (
            f"services/infrastructure must reuse canonical {name}, not redefine it"
        )
    # The provider must never define a second EvidenceRef either.
    assert not hasattr(infra_provider, "EvidenceRef") or (
        getattr(infra_provider, "EvidenceRef", None) is canonical_models.EvidenceRef
    )


# ---------------------------------------------------------------------------
# Enum vocabulary — lower_snake, closed sets
# ---------------------------------------------------------------------------

def test_entity_types_are_lower_snake() -> None:
    values = {kind.value for kind in infra_contracts.InfrastructureEntityType}
    assert "service" in values and "host" in values and "orchestrator" in values
    for value in values:
        assert value == value.lower() and "_" not in value


def test_states_are_lower_snake_and_closed() -> None:
    values = {state.value for state in infra_contracts.InfrastructureState}
    assert values == {
        "provisioned",
        "deploying",
        "active",
        "degraded",
        "maintenance",
        "deprovisioning",
        "failed",
        "unknown",
    }


def test_relationship_types_are_lower_snake() -> None:
    values = {rel.value for rel in infra_contracts.InfrastructureRelationshipType}
    assert {
        "depends_on",
        "deployed_on",
        "connects_to",
        "composed_of",
        "scales_with",
    } <= values


# ---------------------------------------------------------------------------
# Domain contract construction / serialization
# ---------------------------------------------------------------------------

def test_deployment_constructs_and_serializes() -> None:
    deployment = infra_contracts.Deployment(
        id="dep_1",
        tenant_id="tenant-a",
        service_id="svc-checkout",
        artifact_ref="aether/checkout:1.2.3",
        state=infra_contracts.InfrastructureState.ACTIVE,
        started_at="2026-08-24T09:00:00Z",
        completed_at=None,
        version="1.2.3",
        infra_entity_ref="host-us-east-1a",
    )
    dumped = deployment.model_dump(mode="json")
    assert dumped["state"] == "active"
    assert dumped["tenant_id"] == "tenant-a"
    assert dumped["completed_at"] is None


def test_infrastructure_entity_constructs_and_serializes() -> None:
    entity = infra_contracts.InfrastructureEntity(
        id="host-us-east-1a",
        tenant_id="tenant-a",
        kind=infra_contracts.InfrastructureEntityType.HOST,
        state=infra_contracts.InfrastructureState.ACTIVE,
        display_name="us-east-1a fleet host",
        attributes={"region": "us-east-1"},
        deployment_refs=["dep_1"],
        relationship_refs=["rel_1"],
    )
    dumped = entity.model_dump(mode="json")
    assert dumped["kind"] == "host"
    assert dumped["state"] == "active"
    assert dumped["attributes"] == {"region": "us-east-1"}
    assert dumped["deployment_refs"] == ["dep_1"]


def test_infrastructure_relationship_constructs() -> None:
    relationship = infra_contracts.InfrastructureRelationship(
        id="rel_1",
        tenant_id="tenant-a",
        source_id="svc-checkout",
        target_id="db-orders",
        relationship_type=infra_contracts.InfrastructureRelationshipType.DEPENDS_ON,
    )
    assert relationship.relationship_type.value == "depends_on"


def test_domain_contracts_are_tolerant_of_additive_fields() -> None:
    # Canonical domain state stays additive (ContractModel, extra="allow");
    # the projection-plane contracts are the ones that fail closed.
    entity = infra_contracts.InfrastructureEntity(
        id="h1",
        tenant_id="tenant-a",
        kind=infra_contracts.InfrastructureEntityType.HOST,
        state=infra_contracts.InfrastructureState.ACTIVE,
        display_name="h1",
        future_field="unknown-but-tolerated",
    )
    assert entity.future_field == "unknown-but-tolerated"
