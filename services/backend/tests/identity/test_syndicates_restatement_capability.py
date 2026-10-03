"""Syndicates restatement is scoped to explicitly governed population groups."""

from __future__ import annotations

import os
import sys

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT in sys.path:
    sys.path.remove(_BACKEND_ROOT)
sys.path.insert(0, _BACKEND_ROOT)

from services.identity.models import ProjectionType  # noqa: E402
from services.projections.projection_restatement_orchestrator import (  # noqa: E402
    _UNSUPPORTED_PROJECTION_REASONS,
)

SYNDICATES_RESTATEMENT_CAPABILITY = _UNSUPPORTED_PROJECTION_REASONS[
    ProjectionType.SYNDICATES.value
]


def test_syndicates_contract_supports_merge_and_evidence_gated_split():
    capability = SYNDICATES_RESTATEMENT_CAPABILITY

    assert capability["capability"] == "identity_restatement"
    assert capability["projection"] == ProjectionType.SYNDICATES.value
    assert capability["status"] == "partially_supported"
    assert capability["executor_registered"] is True
    assert capability["reason_code"] == "syndicates_split_membership_evidence_incomplete"
    assert "Population 360" in capability["detail"]
    assert "population360.governed_membership" in capability["authorities_present"]
    assert "cluster360.graph_state" not in capability["authorities_present"]
    assert capability["contract_requirements"] == [
        "membership_evidence_refs_in_alias_observation_namespace"
    ]


def test_only_explicitly_tagged_union_populations_are_syndicates_groups():
    from services.projections.syndicates_restatement_capability import is_syndicates_group

    assert is_syndicates_group({
        "metadata": {
            "syndicates_group": True,
            "syndicates_identity_merge_policy": "union",
        }
    })
    assert not is_syndicates_group({"metadata": {"syndicates_group": True}})
    assert not is_syndicates_group({
        "metadata": {
            "syndicates_group": True,
            "syndicates_identity_merge_policy": "duplicate",
        }
    })


def test_governed_merge_restatement_is_tenant_scoped_and_preserves_provenance():
    import asyncio

    from services.projections.syndicates_restatement import restate_syndicates_merge

    class PopulationRepo:
        async def query_populations(self, tenant_id, limit):
            assert tenant_id == "tenant_a"
            return [
                {
                    "id": "group_a",
                    "tenant_id": "tenant_a",
                    "metadata": {
                        "syndicates_group": True,
                        "syndicates_identity_merge_policy": "union",
                    },
                },
                {
                    "id": "ordinary_population",
                    "tenant_id": "tenant_a",
                    "metadata": {},
                },
                {
                    "id": "foreign_group",
                    "tenant_id": "tenant_b",
                    "metadata": {
                        "syndicates_group": True,
                        "syndicates_identity_merge_policy": "union",
                    },
                },
            ]

    class MembershipRepo:
        async def get_members(self, group_id, limit, include_inactive):
            assert group_id == "group_a"
            assert include_inactive is True
            return [{
                "entity_id": "consumed",
                "tenant_id": "tenant_a",
                "entity_type": "person",
                "membership_state": "active",
                "basis": "manual",
                "confidence": 0.9,
                "source_tag": "crm-import",
                "evidence_refs": ["import-row:42"],
            }]

    class Governor:
        def __init__(self):
            self.adds = []
            self.removes = []

        async def add_membership(self, **kwargs):
            self.adds.append(kwargs)

        async def remove_membership(self, **kwargs):
            self.removes.append(kwargs)

    governor = Governor()
    result = asyncio.run(restate_syndicates_merge(
        tenant_id="tenant_a",
        survivor_entity_id="survivor",
        consumed_entity_ids=["consumed", "survivor"],
        decision_id="decision-1",
        population_repository=PopulationRepo(),
        membership_repository=MembershipRepo(),
        governor=governor,
    ))

    assert result["status"] == "completed"
    assert result["memberships_rewritten"] == 1
    assert len(governor.adds) == len(governor.removes) == 1
    add = governor.adds[0]
    assert add["tenant_id"] == "tenant_a"
    assert add["entity_id"] == "survivor"
    assert add["basis"].value == "manual"
    assert "import-row:42" in add["evidence_refs"]
    assert "identity_restatement:decision-1" in add["evidence_refs"]
    assert governor.removes[0]["entity_id"] == "consumed"


@pytest.mark.asyncio
async def test_fragment_split_routes_only_fully_attributed_membership_refs():
    from services.projections.syndicates_restatement import restate_syndicates_split

    class PopulationRepo:
        async def query_populations(self, tenant_id, limit):
            return [{
                "id": "syndicate-a",
                "tenant_id": tenant_id,
                "metadata": {
                    "syndicates_group": True,
                    "syndicates_identity_merge_policy": "union",
                },
            }]

    class MembershipRepo:
        async def get_members(self, group_id, limit, include_inactive):
            return [
                {
                    "entity_id": "source",
                    "tenant_id": "tenant_a",
                    "membership_state": "active",
                    "basis": "manual",
                    "evidence_refs": [
                        "syndicates:identity_alias:old_moved_alias",
                        "syndicates:identity_observation:moved_observation",
                    ],
                },
                {
                    "entity_id": "source",
                    "tenant_id": "tenant_a",
                    "membership_state": "active",
                    "basis": "manual",
                    "evidence_refs": ["syndicates:identity_alias:source_alias"],
                },
                {
                    "entity_id": "source",
                    "tenant_id": "tenant_a",
                    "membership_state": "active",
                    "basis": "manual",
                    "evidence_refs": [
                        "syndicates:identity_alias:old_moved_alias",
                        "syndicates:identity_alias:source_alias",
                    ],
                },
                {
                    "entity_id": "source",
                    "tenant_id": "tenant_a",
                    "membership_state": "active",
                    "basis": "manual",
                    "evidence_refs": ["crm:row:opaque"],
                },
                {
                    "entity_id": "source",
                    "tenant_id": "tenant_a",
                    "membership_state": "active",
                    "basis": "manual",
                    "evidence_refs": [],
                },
            ]

    class IdentityRepo:
        async def get_alias_by_id(self, alias_id):
            aliases = {
                "old_moved_alias": {
                    "id": alias_id,
                    "tenant_id": "tenant_a",
                    "canonical_entity_id": "source",
                    "revoked_at": "2026-10-01T00:00:00+00:00",
                    "alias_type": "email",
                    "alias_value_hash": "hash-moved",
                },
                "new_moved_alias": {
                    "id": alias_id,
                    "tenant_id": "tenant_a",
                    "canonical_entity_id": "target",
                    "revoked_at": None,
                    "alias_type": "email",
                    "alias_value_hash": "hash-moved",
                },
                "source_alias": {
                    "id": alias_id,
                    "tenant_id": "tenant_a",
                    "canonical_entity_id": "source",
                    "revoked_at": None,
                },
            }
            return aliases.get(alias_id)

        async def get_observation_by_id(self, observation_id):
            if observation_id == "moved_observation":
                return {
                    "id": observation_id,
                    "tenant_id": "tenant_a",
                    "canonical_entity_id": "target",
                }
            return None

    class Governor:
        def __init__(self):
            self.adds = []
            self.removes = []

        async def add_membership(self, **kwargs):
            self.adds.append(kwargs)

        async def remove_membership(self, **kwargs):
            self.removes.append(kwargs)

    governor = Governor()
    result = await restate_syndicates_split(
        tenant_id="tenant_a",
        decision_id="split-1",
        split_event={
            "id": "split-1",
            "tenant_id": "tenant_a",
            "original_entity_id": "source",
            "resulting_entity_ids": ["source", "target"],
            "fragment": {
                "alias_ids": ["old_moved_alias"],
                "moved_alias_ids": ["new_moved_alias"],
                "moved_alias_map": [{
                    "source_alias_id": "old_moved_alias",
                    "resulting_alias_id": "new_moved_alias",
                }],
                "observation_ids": ["moved_observation"],
                "moved_observation_ids": ["moved_observation"],
            },
        },
        population_repository=PopulationRepo(),
        membership_repository=MembershipRepo(),
        identity_repository=IdentityRepo(),
        governor=governor,
    )

    assert result["status"] == "unsupported"
    assert result["rewritten_memberships"] == 1
    assert result["reason_code"] == "syndicates_split_membership_evidence_incomplete"
    assert {row["reason_code"] for row in result["unsupported_memberships"]} == {
        "syndicates_membership_evidence_conflicts_across_fragments",
        "syndicates_membership_evidence_unattributed",
        "syndicates_membership_evidence_missing",
    }
    assert len(governor.adds) == len(governor.removes) == 1
    assert governor.adds[0]["entity_id"] == "target"
    assert governor.removes[0]["entity_id"] == "source"


def test_restatement_evidence_is_detached_from_canonical_capability_contract():
    from services.projections.syndicates_restatement_capability import (
        syndicates_restatement_evidence,
    )

    evidence = syndicates_restatement_evidence()
    evidence["authorities_present"].append("invented.authority")

    assert "invented.authority" not in SYNDICATES_RESTATEMENT_CAPABILITY[
        "authorities_present"
    ]
