"""Unit tests for the Outcome360 outcome-type registry consumer.

The OutcomeTypeRegistry loads the canonical
``packages/shared/contracts/outcome-type-registry.json`` (repo-root-relative,
NOT a generated twin) and fails closed on an unknown domain, a duplicate id or a
non-lower-snake id. ``ids()`` / ``by_domain()`` are order-stable (sorted).
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

from services.measurement.outcome.registry import (  # noqa: E402
    OutcomeTypeRegistry,
    outcome_type_registry,
)

_EXPECTED_DOMAINS = [
    "commercial",
    "product",
    "operational",
    "agentic",
    "security",
    "fraud",
    "economic",
    "institutional",
    "onchain",
]


def _minimal_data() -> dict:
    return {
        "schemaVersion": 1,
        "contractVersion": "1.0.0",
        "description": "test",
        "domains": ["commercial", "product"],
        "outcomeTypes": [
            {
                "id": "a_commercial_outcome",
                "domain": "commercial",
                "name": "Commercial Outcome",
                "description": "test",
            },
            {
                "id": "b_product_outcome",
                "domain": "product",
                "name": "Product Outcome",
                "description": "test",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Canonical registry load
# ---------------------------------------------------------------------------

def test_canonical_registry_loads() -> None:
    assert outcome_type_registry.domains() == _EXPECTED_DOMAINS
    assert outcome_type_registry.contract_version == "1.0.0"


def test_canonical_registry_ids_sorted() -> None:
    ids = outcome_type_registry.ids()
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_all_canonical_domains_covered() -> None:
    covered = {
        outcome_type_registry.get(type_id)["domain"]
        for type_id in outcome_type_registry.ids()
    }
    assert covered == set(_EXPECTED_DOMAINS)


def test_by_domain_covers_every_declared_domain() -> None:
    for domain in outcome_type_registry.domains():
        members = outcome_type_registry.by_domain(domain)
        assert members, f"domain {domain!r} has no outcome types"


def test_get_returns_definition_and_none_for_unknown() -> None:
    definition = outcome_type_registry.get("journey_completion")
    assert definition is not None
    assert definition["domain"] == "commercial"
    assert definition["name"] == "Journey Completion"
    assert outcome_type_registry.get("not_a_real_outcome") is None


def test_by_domain_only_returns_members_sorted() -> None:
    members = outcome_type_registry.by_domain("commercial")
    ids = [m["id"] for m in members]
    assert ids == sorted(ids)
    assert all(m["domain"] == "commercial" for m in members)
    assert outcome_type_registry.by_domain("onchain") == [
        {
            "id": "onchain_settlement_completed",
            "domain": "onchain",
            "name": "On-Chain Settlement Completed",
            "description": outcome_type_registry.get("onchain_settlement_completed")[
                "description"
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Load-time fail-closed validation
# ---------------------------------------------------------------------------

def test_unknown_domain_rejected_at_load() -> None:
    data = _minimal_data()
    data["outcomeTypes"].append(
        {
            "id": "bogus_outcome",
            "domain": "not_a_domain",
            "name": "Bogus",
            "description": "test",
        }
    )
    with pytest.raises(ValueError, match="unknown domain"):
        OutcomeTypeRegistry(data=data)


def test_duplicate_id_rejected_at_load() -> None:
    data = _minimal_data()
    data["outcomeTypes"].append(dict(data["outcomeTypes"][0]))
    with pytest.raises(ValueError, match="duplicate outcome-type id"):
        OutcomeTypeRegistry(data=data)


def test_non_lower_snake_id_rejected_at_load() -> None:
    data = _minimal_data()
    data["outcomeTypes"][0]["id"] = "Not_Lower_Snake"
    with pytest.raises(ValueError, match="lower_snake"):
        OutcomeTypeRegistry(data=data)


def test_duplicate_domain_rejected_at_load() -> None:
    data = _minimal_data()
    data["domains"].append("commercial")
    with pytest.raises(ValueError, match="duplicate outcome-type domain"):
        OutcomeTypeRegistry(data=data)


def test_non_snake_domain_rejected_at_load() -> None:
    data = _minimal_data()
    data["domains"].append("Commercial")
    with pytest.raises(ValueError, match="lower_snake"):
        OutcomeTypeRegistry(data=data)


def test_empty_outcome_types_rejected_at_load() -> None:
    data = _minimal_data()
    data["outcomeTypes"] = []
    with pytest.raises(ValueError, match="non-empty list"):
        OutcomeTypeRegistry(data=data)


def test_missing_required_field_rejected_at_load() -> None:
    data = _minimal_data()
    del data["outcomeTypes"][0]["description"]
    with pytest.raises(ValueError, match="required field"):
        OutcomeTypeRegistry(data=data)


def test_custom_data_loads_and_sorts_ids() -> None:
    registry = OutcomeTypeRegistry(data=_minimal_data())
    assert registry.ids() == ["a_commercial_outcome", "b_product_outcome"]
    assert registry.domains() == ["commercial", "product"]
