"""Syndicates identity restatement contract.

Syndicates groups opt in to Population 360's governed membership authority by
setting ``population.metadata.syndicates_group`` to ``true`` and
``population.metadata.syndicates_identity_merge_policy`` to ``union``. This
keeps ordinary populations outside the Syndicates surface and makes merge
behavior explicit per group. Membership writes still pass through
PopulationMembershipGovernor, including tenant, consent, provenance, and graph
ledger controls.

Split reassignment is evidence-gated: the executor accepts only identity alias
and observation references carried by a durable fragment split event. Missing,
mixed, malformed, or unattributed evidence leaves that membership untouched.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Final


SYNDICATES_RESTATEMENT_CAPABILITY: Final[dict[str, object]] = {
    "capability": "identity_restatement",
    "projection": "syndicates",
    "status": "partially_supported",
    "executor_registered": True,
    "reason_code": "syndicates_split_membership_evidence_incomplete",
    "detail": (
        "Syndicates membership is backed only by tenant-scoped Population 360 "
        "groups explicitly tagged with syndicates_group=true. Opted-in groups "
        "must declare syndicates_identity_merge_policy=union. Merge writes "
        "are governed and consent-checked. Split writes use only accepted "
        "identity alias/observation refs tied to the durable split event; "
        "memberships with incomplete or conflicting evidence remain unchanged "
        "and are reported as unsupported. Untagged populations and Cluster360 "
        "state are not treated as Syndicates."
    ),
    "authorities_present": [
        "population360.governed_membership",
        "population360.tenant_scoped_population_registry",
    ],
    "contract_requirements": [
        "membership_evidence_refs_in_alias_observation_namespace",
    ],
}


def syndicates_restatement_evidence() -> dict[str, object]:
    """Return a detached evidence mapping for durable restatement results."""
    return deepcopy(SYNDICATES_RESTATEMENT_CAPABILITY)


SYNDICATES_GROUP_METADATA_KEY: Final[str] = "syndicates_group"
SYNDICATES_MERGE_POLICY_KEY: Final[str] = "syndicates_identity_merge_policy"
SYNDICATES_MERGE_UNION: Final[str] = "union"


def is_syndicates_group(population: dict) -> bool:
    """Return true only for a valid, explicitly opted-in Syndicates group."""
    metadata = population.get("metadata")
    return (
        isinstance(metadata, dict)
        and metadata.get(SYNDICATES_GROUP_METADATA_KEY) is True
        and metadata.get(SYNDICATES_MERGE_POLICY_KEY) == SYNDICATES_MERGE_UNION
    )
