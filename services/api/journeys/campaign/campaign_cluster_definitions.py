"""Exact current cluster definition revisions for explicitly linked campaigns.

A population link is the association authority; this reader only validates the
owning population and its current versioned definition. It does not infer
membership, reveal definition contents, or evaluate the definition.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CampaignClusterDefinitionRead:
    tenant_id: str
    population_id: str
    available: bool
    population: Optional[dict[str, Any]] = None
    revision: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


class CampaignClusterDefinitionAuthority:
    async def read(self, tenant_id: str, population_id: str) -> CampaignClusterDefinitionRead:
        if not tenant_id or not population_id:
            return CampaignClusterDefinitionRead(tenant_id, population_id, False, reason="cluster_scope_missing")
        try:
            from identity.population.registry import definition_repo, population_repo

            population = await population_repo.find_by_id(population_id)
            if not isinstance(population, dict):
                return CampaignClusterDefinitionRead(tenant_id, population_id, True)
            if population.get("id") != population_id or population.get("tenant_id") != tenant_id:
                return CampaignClusterDefinitionRead(tenant_id, population_id, False, reason="cluster_population_scope_mismatch")
            if population.get("population_type") != "cluster":
                return CampaignClusterDefinitionRead(tenant_id, population_id, True, population=population)
            version = population.get("definition_version")
            if not isinstance(version, str) or not version:
                return CampaignClusterDefinitionRead(tenant_id, population_id, False, reason="cluster_definition_version_missing")
            revision_id = hashlib.sha256(f"{population_id}:{version}".encode()).hexdigest()[:24]
            revision = await definition_repo.find_by_id(revision_id)
            return CampaignClusterDefinitionRead(
                tenant_id, population_id, True, population=population,
                revision=revision if isinstance(revision, dict) else None,
            )
        except Exception:  # noqa: BLE001 - authority unavailability is isolated to this dimension
            return CampaignClusterDefinitionRead(tenant_id, population_id, False, reason="cluster_definition_authority_unavailable")


def exact_cluster_definition(read: CampaignClusterDefinitionRead) -> Optional[dict[str, str]]:
    """Return sanitized revision metadata only when both canonical rows agree."""
    population, revision = read.population, read.revision
    if not read.available or not isinstance(population, dict) or not isinstance(revision, dict):
        return None
    version = population.get("definition_version")
    if not isinstance(version, str) or not version or not version.isdecimal():
        return None
    expected_id = hashlib.sha256(f"{read.population_id}:{version}".encode()).hexdigest()[:24]
    definition = revision.get("definition")
    if not isinstance(definition, dict) or not isinstance(population.get("definition"), dict):
        return None
    try:
        canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
        current = json.dumps(population["definition"], sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if (
        population.get("tenant_id") != read.tenant_id
        or population.get("id") != read.population_id
        or population.get("population_type") != "cluster"
        or population.get("status") != "active"
        or revision.get("id") != expected_id
        or revision.get("population_id") != read.population_id
        or revision.get("definition_version") != version
        or revision.get("definition_hash") != digest
        or revision.get("status") != "active"
        or canonical != current
    ):
        return None
    return {"populationId": read.population_id, "revisionId": expected_id,
            "definitionVersion": version, "definitionHash": digest}
